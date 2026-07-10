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
        raw_timeout = e.get("JOB_SEARCH_WRITER_TIMEOUT", "300")
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise AgentWriterError(
                f"JOB_SEARCH_WRITER_TIMEOUT must be numeric seconds, "
                f"got {raw_timeout!r}") from exc
        return cls(
            base_url=e.get("LITELLM_BASE_URL", "http://localhost:4000/v1").rstrip("/"),
            api_key=e.get("LITELLM_API_KEY") or e.get("LITELLM_MASTER_KEY", ""),
            model=e.get("JOB_SEARCH_WRITER_MODEL", "chat"),
            timeout=timeout,
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
    # Geoff's Master Resume Bullet Bank text — the phrasing source. When
    # present, the resume is composed from HIS OWN bullets/summaries/skills/
    # education, so the output reads as if he wrote it (he did).
    master_bank: str = ""


@dataclass
class GeneratedMaterials:
    resume: str
    cover_letter: str
    recruiter_message: str
    claim_ids: list[str]
    model: str
    attempts: int
    # AI-tell phrases that survived the corrective retry. Surfaced as a
    # validation warning for Geoff's review — never silently dropped.
    tone_flags: list[str] = field(default_factory=list)


MASTER_BANK_FILENAME = "master_resume_bank.md"
_MASTER_BANK_DOCX = "Master_Resume_Bullet_Bank.docx"


def ensure_master_bank_text(base: Path) -> str:
    """The Master Resume Bullet Bank as text. Cached at
    profile/master_resume_bank.md; extracted from the .docx on first use (the
    QUICK TAILORING TIPS tail is process guidance, not resume content). Returns
    '' when neither exists — the caller records that honestly."""
    cached = base / "profile" / MASTER_BANK_FILENAME
    if cached.is_file():
        return cached.read_text(encoding="utf-8")
    docx = base / _MASTER_BANK_DOCX
    if not docx.is_file():
        return ""
    from command_center.job_search.profile_ingest import extract_docx_text
    paragraphs = extract_docx_text(docx)
    kept: list[str] = []
    for p in paragraphs:
        if p.strip().upper().startswith("QUICK TAILORING TIPS"):
            break
        kept.append(p)
    text = "\n".join(kept)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8")
    return text


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


# Phrases that read as AI-written, not Geoff-written. Checked in the output;
# survivors after the corrective retry become a validation warning.
BANNED_PHRASES = (
    "passionate", "thrilled", "excited to", "delve", "leverage", "leveraging",
    "spearheaded", "cutting-edge", "seamless", "utilize", "i believe",
    "proven track record of success", "dynamic environment", "fast-paced",
    "wealth of experience", "honed", "esteemed",
)


def build_messages(inputs: MaterialInputs, bank: AchievementBank) -> list[dict]:
    has_master = bool(inputs.master_bank.strip())
    system = "\n".join([
        "You write job application materials for Geoffrey Hadfield. The output",
        "must read as if Geoff wrote it himself.",
        "",
        "VOICE RULES — violating any of these makes the output unusable:",
        "1. Every fact, metric, tool, employer, date, and degree MUST come from",
        "   the MASTER RESUME BANK or the ACHIEVEMENT BANK below. Never invent",
        "   employers, dates, degrees, certifications, contact details, or",
        "   numbers.",
        ("2. Compose the resume from MASTER RESUME BANK lines near-verbatim"
         if has_master else
         "2. Compose the resume from ACHIEVEMENT BANK bullets near-verbatim"),
        "   (drop the [bracketed tags]). Light edits for flow are fine; new",
        "   claims are not.",
        "3. Never state derived totals (e.g. 'N+ years of experience') — the",
        "   dates on record speak for themselves.",
        "   Never claim experience with a technology or domain the banks do",
        "   not record (e.g. 'LLM systems' when no bank line mentions LLMs),",
        "   even when the job description asks for it — name the closest REAL",
        "   experience and let the reader draw the connection.",
        "4. Banned words/phrases (they read as AI, Geoff never writes them):",
        "   " + ", ".join(BANNED_PHRASES) + ", and exclamation marks.",
        "5. Resume voice: no first-person pronouns; terse verb-first bullets in",
        "   the bank's own style — 'Built X (tools); impact metric'.",
        "6. Cover letter voice: first person, plain, direct, short sentences,",
        "   specific to this company and role. No flattery, no filler.",
        "",
        "RESUME FORMAT — Markdown, exactly these sections in this order:",
        "# Geoffrey Hadfield",
        "Data Scientist | <subtitle fitting this role>",
        "Target: <company> — <role>",
        "## Summary",
        ("   Pick the PROFESSIONAL SUMMARY from the master bank that best fits"
         "\n   the variant; you may adapt at most one sentence to this job."
         if has_master else
         "   2-3 sentences composed only from bank facts."),
        "## Core Skills",
        ("   Use the master bank CORE SKILLS section matching the resume"
         "\n   variant, keeping its pipe-delimited grouping."
         if has_master else
         "   Group only tools that appear in the achievements you used."),
        "## Experience",
        "   EVERY role, reverse-chronological, headed exactly",
        "   'Company — Title (dates)' as recorded. World Model Sports LLC",
        "   (2026 - Present, from the achievement bank) comes first, then the",
        "   remaining roles by date. 4-6 bullets for World Model Sports and the",
        "   JP Morgan Chase Analytics Engineer role; 2-3 bullets for each",
        "   earlier role. Choose the bullets that best match the job",
        "   description.",
        "## Projects",
        "   The 2-3 most relevant project bullets for this job.",
        "## Education",
        ("   All three degrees, verbatim from the master bank EDUCATION section."
         if has_master else
         "   Include only degrees recorded in the banks; omit the section if"
         "\n   none are recorded."),
        "## Claim Traceability",
        "   The achievement bank ids used, in backticks.",
        "",
        "COVER LETTER FORMAT: exactly 3 short paragraphs — (1) the role and the",
        "one-line reason Geoff fits, naming 2 specific requirements from the job",
        "description; (2) the 2-3 most relevant proof points with their metrics;",
        "(3) a direct close. Under 250 words. Sign off:",
        "Best,",
        "Geoffrey Hadfield",
        "",
        "RECRUITER MESSAGE: under 120 words, plain, one concrete proof point,",
        "no greeting fluff.",
        "",
        "Close with a '=== CLAIM IDS ===' section listing, one per line, the id",
        "of every ACHIEVEMENT BANK entry whose facts you used. Output the four",
        "sections in this exact order, each opened by its delimiter line:",
        "=== RESUME ===, === COVER LETTER ===, === RECRUITER MESSAGE ===,",
        "=== CLAIM IDS ===.",
    ])
    notes_block = ""
    if inputs.reviewer_notes:
        notes_block = "\n".join([
            "",
            "REVIEWER NOTES (Geoff reviewed an earlier draft — address every note):",
            *[f"- {n}" for n in inputs.reviewer_notes],
        ])
    master_block = ""
    if has_master:
        master_block = "\n".join([
            "",
            "MASTER RESUME BANK (Geoff's own writing — the preferred source for",
            "every resume line; bracketed [tags] are selection hints, not output)",
            inputs.master_bank.strip(),
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
        master_block,
        "",
        "ACHIEVEMENT BANK (validated claims with ids — every fact you use must",
        "trace here or to the master bank)",
        _bank_context(bank),
    ])
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


_REQUIRED_RESUME_HEADINGS = ("## Summary", "## Core Skills", "## Experience",
                             "## Education", "## Claim Traceability")


def _structure_problems(resume: str, has_master_bank: bool) -> list[str]:
    """Hard problems: a resume missing its required sections is not reviewable.
    Without the master bank, Core Skills/Education may legitimately be absent."""
    required = _REQUIRED_RESUME_HEADINGS if has_master_bank else (
        "## Summary", "## Experience", "## Claim Traceability")
    return [f"resume is missing the '{h}' section" for h in required
            if h not in resume]


def _tone_problems(resume: str, cover_letter: str) -> list[str]:
    """Soft problems: AI-tell phrases. They trigger a corrective retry; if the
    model still won't drop them, the output is kept and the flags surface as a
    validation warning for Geoff (a word choice must not force template
    fallback)."""
    combined = f"{resume}\n{cover_letter}".lower()
    flags = [f"banned phrase in output: {p!r}" for p in BANNED_PHRASES
             if p in combined]
    if "!" in cover_letter:
        flags.append("cover letter contains an exclamation mark")
    return flags


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
    """Every listed token is kept and sent to validate_claim_ids — a malformed
    or hallucinated id must FAIL claim validation (triggering the corrective
    retry), never be silently discarded."""
    ids: list[str] = []
    for raw in re.split(r"[,\n]", block):
        token = raw.strip().strip("`-* ").strip()
        if token:
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
        try:
            content = str(raw["choices"][0]["message"].get("content") or "")
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            # a 200 with a malformed body must land in the same trace +
            # AgentWriterError contract as a transport failure — never escape
            # as a bare KeyError that skips the template fallback
            entry.update({
                "ok": False,
                "error": f"malformed gateway response: {type(exc).__name__}: {exc}",
                "response_raw": json.dumps(raw, default=str)[:2000],
                "duration_ms": int((time.monotonic() - started) * 1000),
            })
            append_trace(trace_path, entry)
            raise AgentWriterError(
                f"gateway returned a malformed completion payload "
                f"(model {cfg.model!r}): {type(exc).__name__}: {exc}") from exc
        usage = raw.get("usage")
        sections = _split_sections(content)
        missing = [s for s in _SECTIONS if s not in sections or not sections[s]]
        claim_ids = _parse_claim_ids(sections.get("CLAIM IDS", ""))
        claim_errors = validate_claim_ids(bank, claim_ids) if claim_ids else (
            [] if "CLAIM IDS" in missing else ["claim ids section is empty"])
        hard_problems = [f"missing or empty section: {s}" for s in missing]
        hard_problems.extend(claim_errors)
        if sections.get("RESUME"):
            hard_problems.extend(_structure_problems(
                sections["RESUME"], bool(inputs.master_bank.strip())))
        tone_flags = _tone_problems(
            sections.get("RESUME", ""), sections.get("COVER LETTER", ""))
        problems = hard_problems + tone_flags
        entry.update({
            "ok": not hard_problems,
            "response": content,
            "usage": usage,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "claim_ids": claim_ids,
            "problems": problems,
        })
        append_trace(trace_path, entry)
        accept_with_flags = (
            not hard_problems and tone_flags and attempt == max_attempts)
        if not problems or accept_with_flags:
            # A stubborn word choice never forces template fallback — the
            # surviving tone flags are returned and surface as a validation
            # warning for Geoff's review.
            return GeneratedMaterials(
                resume=sections["RESUME"],
                cover_letter=sections["COVER LETTER"],
                recruiter_message=sections["RECRUITER MESSAGE"],
                claim_ids=claim_ids,
                model=cfg.model,
                attempts=attempt,
                tone_flags=tone_flags,
            )
        last_error = "; ".join(problems)
        messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": (
                "Your previous answer had these problems:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\nRewrite the full answer with all four sections, keeping "
                  "the required resume format, using only achievement ids that "
                  "exist in the ACHIEVEMENT BANK, and avoiding every banned "
                  "phrase.")},
        ]
    raise AgentWriterError(
        f"writer output invalid after {max_attempts} attempts: {last_error}")
