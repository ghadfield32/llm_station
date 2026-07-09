"""LLM-backed application material generation with a persisted agent trace.

The writer talks to the same LiteLLM proxy the cockpit chat uses (LITELLM_BASE_URL
+ LITELLM_API_KEY/LITELLM_MASTER_KEY, model role alias — default "chat"). Every
attempt is appended to <app_dir>/agent_trace.jsonl with the FULL prompt and raw
model output, so the agent's thinking and context are reviewable at any point.

Claim safety: the prompt carries the complete achievement bank and the model must
close with a "=== CLAIM IDS ===" section naming every achievement it used. Those
ids are checked with validate_claim_ids; an invalid set gets one corrective retry
and a still-invalid result raises — the caller decides whether to fall back to the
deterministic templates (recorded honestly in application.yml, never silently).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from command_center.job_search.achievement_bank import validate_claim_ids
from command_center.job_search.schemas import AchievementBank, repo_root

TRACE_FILENAME = "agent_trace.jsonl"

_SECTIONS = ("RESUME", "COVER LETTER", "RECRUITER MESSAGE", "CLAIM IDS")


class AgentWriterError(RuntimeError):
    """Generation failed after retries (transport, parse, or claim validation)."""


def writer_env() -> dict[str, str]:
    """Repo .env merged under the live process environment (process wins) — the
    same resolution GatewayCore uses, kept local so the pipeline does not import
    the channel stack."""
    out: dict[str, str] = {}
    env_path = repo_root() / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    out.update(os.environ)
    return out


@dataclass
class WriterConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 300.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "WriterConfig":
        e = env if env is not None else writer_env()
        return cls(
            base_url=e.get("LITELLM_BASE_URL", "http://localhost:4000/v1").rstrip("/"),
            api_key=e.get("LITELLM_API_KEY") or e.get("LITELLM_MASTER_KEY", ""),
            model=e.get("JOB_SEARCH_WRITER_MODEL", "chat"),
            timeout=float(e.get("JOB_SEARCH_WRITER_TIMEOUT", "300")),
        )


@dataclass
class MaterialInputs:
    company: str
    role_title: str
    description_text: str
    apply_url: str
    resume_variant: str
    matched_keywords: list[str] = field(default_factory=list)
    fit_reasons: list[str] = field(default_factory=list)
    fit_score: int | None = None
    reviewer_notes: list[str] = field(default_factory=list)
    writing_style: dict[str, str] = field(default_factory=dict)


@dataclass
class GeneratedMaterials:
    resume: str
    cover_letter: str
    recruiter_message: str
    claim_ids: list[str]
    model: str
    attempts: int


def _bank_context(bank: AchievementBank) -> str:
    """Render the COMPLETE achievement bank — every achievement, every variant
    bullet, and the full STAR story — so the model works from Geoff's full record,
    not a pre-trimmed subset."""
    blocks: list[str] = []
    for a in bank.achievements:
        lines = [
            f"### {a.id}",
            f"- title: {a.title}",
            f"- company: {a.company} | role: {a.role} | dates: {a.dates}",
            f"- type: {a.type} | confidence: {a.confidence} | resume_safe: {a.resume_safe}",
            f"- tools: {', '.join(a.tools) or '-'}",
            f"- domains: {', '.join(a.domains) or '-'}",
            f"- metrics: {', '.join(a.metrics) or '-'}",
        ]
        for variant, bullet in a.bullet_versions.items():
            if bullet:
                lines.append(f"- bullet[{variant}]: {bullet}")
        if a.full_story:
            lines.append(f"- full story: {a.full_story}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_messages(inputs: MaterialInputs, bank: AchievementBank) -> list[dict]:
    style_resume = inputs.writing_style.get(
        "resume", "Concise, evidence-backed, technical, impact-oriented.")
    style_cover = inputs.writing_style.get(
        "cover_letter", "Direct, role-specific, no generic enthusiasm filler.")
    system = "\n".join([
        "You write job application materials for Geoffrey Hadfield.",
        "Hard rules — violating any of these makes the output unusable:",
        "1. Every experience, project, metric, tool, and claim MUST come from the",
        "   ACHIEVEMENT BANK below. Never invent employers, dates, degrees,",
        "   certifications, contact details, or numbers that are not in the bank.",
        "2. You may rephrase bank bullets and stories for the target role, but the",
        "   underlying facts must stay exactly as recorded.",
        "   Never state derived totals (e.g. 'N+ years of experience') — refer to",
        "   the dates on record instead.",
        "3. Close your answer with a '=== CLAIM IDS ===' section listing, one per",
        "   line, the id of every achievement you used anywhere in the materials.",
        "4. Output the four sections in this exact order, each opened by its",
        "   delimiter line: === RESUME ===, === COVER LETTER ===,",
        "   === RECRUITER MESSAGE ===, === CLAIM IDS ===.",
        f"Resume style: {style_resume}",
        f"Cover letter style: {style_cover}",
        "Resume format: Markdown. Sections: heading '# Geoffrey Hadfield',",
        "a one-line target ('Target: <company> — <role>'), '## Summary' (2-3",
        "sentences), '## Experience' (group bullets under company/role/dates from",
        "the bank), '## Projects' (if project achievements are used), '## Skills'",
        "(only tools that appear in the achievements you used), and finally",
        "'## Claim Traceability' listing the same achievement ids in backticks.",
        "Cover letter: 3-4 short paragraphs, addressed to the hiring team,",
        "specific to this company and role, grounded only in cited achievements",
        "and the job description. Recruiter message: under 120 words, direct.",
    ])
    notes_block = ""
    if inputs.reviewer_notes:
        notes_block = "\n".join([
            "",
            "REVIEWER NOTES (Geoff reviewed an earlier draft — address every note):",
            *[f"- {n}" for n in inputs.reviewer_notes],
        ])
    user = "\n".join([
        f"Target job: {inputs.role_title} at {inputs.company}",
        f"Apply URL: {inputs.apply_url}",
        f"Resume variant to emphasize: {inputs.resume_variant}",
        f"Fit score: {inputs.fit_score if inputs.fit_score is not None else '-'}",
        f"Matched keywords: {', '.join(inputs.matched_keywords) or '-'}",
        f"Fit reasons: {'; '.join(inputs.fit_reasons) or '-'}",
        notes_block,
        "",
        "JOB DESCRIPTION",
        inputs.description_text.strip(),
        "",
        "ACHIEVEMENT BANK (the complete, only allowed source of claims)",
        _bank_context(bank),
    ])
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def _split_sections(text: str) -> dict[str, str]:
    """Split the model output on the required '=== NAME ===' delimiter lines.
    Returns {} keys only for sections actually present — the caller validates."""
    pattern = re.compile(
        r"^\s*=+\s*(" + "|".join(_SECTIONS) + r")\s*=+\s*$",
        re.IGNORECASE | re.MULTILINE)
    found: dict[str, str] = {}
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1).upper()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        found[name] = text[m.end():end].strip()
    return found


def _parse_claim_ids(block: str) -> list[str]:
    ids: list[str] = []
    for raw in re.split(r"[,\n]", block):
        token = raw.strip().strip("`-* ").strip()
        if token and re.fullmatch(r"[a-z0-9_]+", token):
            ids.append(token)
    return list(dict.fromkeys(ids))


def append_trace(trace_path: Path, entry: dict) -> None:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_trace(app_dir: Path) -> list[dict]:
    path = app_dir / TRACE_FILENAME
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _default_post(config: WriterConfig, messages: list[dict]) -> dict:
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    r = httpx.post(
        f"{config.base_url}/chat/completions",
        headers=headers,
        json={"model": config.model, "messages": messages},
        timeout=config.timeout,
    )
    r.raise_for_status()
    return r.json()


def generate_materials(
    inputs: MaterialInputs,
    bank: AchievementBank,
    *,
    trace_path: Path,
    trace_step: str = "generate_materials",
    config: WriterConfig | None = None,
    post_fn: Callable[[WriterConfig, list[dict]], dict] | None = None,
    max_attempts: int = 2,
) -> GeneratedMaterials:
    """One model call producing resume + cover letter + recruiter message, with a
    corrective retry when sections are missing or claim ids fail validation.
    Every attempt — including failures — lands in the trace file verbatim."""
    cfg = config or WriterConfig.from_env()
    post = post_fn or _default_post
    messages = build_messages(inputs, bank)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "step": trace_step,
            "attempt": attempt,
            "model": cfg.model,
            "base_url": cfg.base_url,
            "messages": messages,
        }
        try:
            raw = post(cfg, messages)
        except Exception as exc:  # transport failure — trace it, then surface it
            entry.update({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "duration_ms": int((time.monotonic() - started) * 1000),
            })
            append_trace(trace_path, entry)
            raise AgentWriterError(
                f"writer model call failed ({cfg.base_url}, model {cfg.model!r}): "
                f"{type(exc).__name__}: {exc}") from exc
        content = str(raw["choices"][0]["message"].get("content") or "")
        usage = raw.get("usage")
        sections = _split_sections(content)
        missing = [s for s in _SECTIONS if s not in sections or not sections[s]]
        claim_ids = _parse_claim_ids(sections.get("CLAIM IDS", ""))
        claim_errors = validate_claim_ids(bank, claim_ids) if claim_ids else (
            [] if "CLAIM IDS" in missing else ["claim ids section is empty"])
        problems = [f"missing or empty section: {s}" for s in missing]
        problems.extend(claim_errors)
        entry.update({
            "ok": not problems,
            "response": content,
            "usage": usage,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "claim_ids": claim_ids,
            "problems": problems,
        })
        append_trace(trace_path, entry)
        if not problems:
            return GeneratedMaterials(
                resume=sections["RESUME"],
                cover_letter=sections["COVER LETTER"],
                recruiter_message=sections["RECRUITER MESSAGE"],
                claim_ids=claim_ids,
                model=cfg.model,
                attempts=attempt,
            )
        last_error = "; ".join(problems)
        messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": (
                "Your previous answer had these problems:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\nRewrite the full answer with all four sections, using only "
                  "achievement ids that exist in the ACHIEVEMENT BANK.")},
        ]
    raise AgentWriterError(
        f"writer output invalid after {max_attempts} attempts: {last_error}")
