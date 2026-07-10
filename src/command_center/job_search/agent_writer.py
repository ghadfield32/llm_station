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

_SECTIONS = ("RESUME", "COVER LETTER", "OUTREACH", "ANSWERS", "CLAIM IDS")


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
    # profile/contact.yml — printed verbatim as the resume contact header
    # (ATS: contact must be extractable from the document body).
    contact: dict = field(default_factory=dict)
    # profile/evidence_policy.yml held_claims — metrics whose sources conflict
    # or are single-variant. The writer must not use them; leakage is a hard
    # problem that triggers a corrective retry.
    held_claims: list = field(default_factory=list)
    # profile/ats_resume_example.md — an approved past resume, injected as the
    # structure/voice exemplar (content is reselected per job).
    format_example: str = ""


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
    # 6-8 job-specific application/interview answers (SDARL structure),
    # written to answer_bank.md.
    answers: str = ""


MASTER_BANK_FILENAME = "master_resume_bank.md"
_MASTER_BANK_DOCX = "Master_Resume_Bullet_Bank.docx"
CONTACT_FILENAME = "contact.yml"
EVIDENCE_POLICY_FILENAME = "evidence_policy.yml"
FORMAT_EXAMPLE_FILENAME = "ats_resume_example.md"


def load_contact(base: Path) -> dict:
    """profile/contact.yml as a dict; {} when absent (recorded honestly in
    generation provenance — the ATS contact check will warn)."""
    path = base / "profile" / CONTACT_FILENAME
    if not path.is_file():
        return {}
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def load_evidence_policy(base: Path) -> list[dict]:
    """held_claims from profile/evidence_policy.yml; [] when absent."""
    path = base / "profile" / EVIDENCE_POLICY_FILENAME
    if not path.is_file():
        return []
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    held = data.get("held_claims") if isinstance(data, dict) else None
    return [h for h in (held or []) if isinstance(h, dict)]


def load_format_example(base: Path) -> str:
    """profile/ats_resume_example.md minus its provenance comment header."""
    path = base / "profile" / FORMAT_EXAMPLE_FILENAME
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not ln.startswith("#")]
    return "\n".join(kept).strip()


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
    # empty-claim words the pipeline standard flags
    "results-driven", "world-class", "visionary",
)


def _contact_header(contact: dict) -> list[str]:
    """The two contact lines printed verbatim under the name (ATS: contact must
    live in the document body)."""
    line1 = " | ".join(str(contact[k]) for k in ("location", "phone", "email")
                       if contact.get(k))
    line2 = " | ".join(str(contact[k]) for k in ("portfolio", "github", "linkedin")
                       if contact.get(k))
    return [ln for ln in (line1, line2) if ln]


def build_messages(inputs: MaterialInputs, bank: AchievementBank) -> list[dict]:
    has_master = bool(inputs.master_bank.strip())
    contact_lines = _contact_header(inputs.contact)
    system = "\n".join([
        "You write job application materials for Geoffrey Hadfield. The output",
        "must read as if Geoff wrote it himself, pass ATS text extraction, and",
        "survive a skeptical recruiter's fact check.",
        "",
        "VOICE RULES — violating any of these makes the output unusable:",
        "1. Every fact, metric, tool, employer, date, and degree MUST come from",
        "   the MASTER RESUME BANK, the ACHIEVEMENT BANK, or the APPROVED",
        "   RESUME EXEMPLAR below. Never invent employers, dates, degrees,",
        "   certifications, contact details, or numbers.",
        ("2. Compose resume bullets from MASTER RESUME BANK / EXEMPLAR lines"
         if has_master else
         "2. Compose resume bullets from ACHIEVEMENT BANK bullets"),
        "   near-verbatim (drop any [bracketed tags]). Light edits for flow are",
        "   fine; new claims are not.",
        "3. Never state derived totals (e.g. 'N+ years of experience') — the",
        "   dates on record speak for themselves.",
        "   Never claim experience with a technology or domain the banks do",
        "   not record (e.g. 'LLM systems' when no bank line mentions LLMs),",
        "   even when the job description asks for it — name the closest REAL",
        "   experience and let the reader draw the connection.",
        "4. HELD CLAIMS: the metrics listed under HELD CLAIMS below have",
        "   unresolved evidence and must NOT appear anywhere in the output —",
        "   not reworded, not approximated. Use the confirmed metrics instead.",
        "5. Banned words/phrases (they read as AI, Geoff never writes them):",
        "   " + ", ".join(BANNED_PHRASES) + ", and exclamation marks.",
        "6. Resume voice: no first-person pronouns; verb-first bullets shaped",
        "   'Action + method/tool + decision/output + measured result'. One",
        "   main achievement per bullet.",
        "7. Cover letter and answers voice: first person, plain, direct, short",
        "   sentences, specific to this company and role. No flattery.",
        "8. ATS: mirror the job description's own terminology for skills Geoff",
        "   actually has (e.g. say 'experimentation' if the posting says it);",
        "   never add a keyword without a supporting fact.",
        "",
        "RESUME FORMAT — Markdown, single column, exactly these sections in",
        "this order (match the APPROVED RESUME EXEMPLAR's structure):",
        "# GEOFFREY HADFIELD",
        *(contact_lines or
          ["(no contact block on file — omit rather than invent)"]),
        "<HEADLINE: role-family + 2-3 pipe-separated keyword themes from THIS",
        "job description, uppercase, one line>",
        "## Professional Summary",
        "   2-3 sentences: what Geoff does, strongest evidence areas for THIS",
        "   role, and current work. Composed only from bank/exemplar facts.",
        "## Core Expertise",
        "   3-4 grouped lines, 'Group name: item, item, item' — group names",
        "   chosen to mirror this job's requirement language; items only where",
        "   evidence exists.",
        "## Experience",
        "   EVERY role, reverse-chronological, headed exactly",
        "   'Company | Title (dates)' as recorded — World Model Sports LLC",
        "   first, then remaining roles by date. 3-4 bullets for World Model",
        "   Sports and the JPMorgan Chase Analytics Engineer role; 2-3 for each",
        "   earlier role. Pick the bullets that best match the job description.",
        "## Selected Technical Projects",
        "   The 2-4 most relevant projects for this job, one bullet each:",
        "   'Project name: what was built (tools); result'.",
        "## Education",
        ("   All three degrees exactly as recorded in the master bank/exemplar."
         if has_master else
         "   Only degrees recorded in the banks; omit the section if none."),
        "Do NOT include: a 'Target:' line, claim ids, fit scores, agent/trace",
        "language, tables, or a Claim Traceability section — this file goes to",
        "the employer.",
        "",
        "COVER LETTER FORMAT: 250-350 words, 4 short paragraphs — (1) the role",
        "and the two strongest requirements Geoff matches, naming them in the",
        "posting's words; (2) the strongest business/analytics evidence with",
        "its confirmed metrics; (3) current World Model Sports work and, when",
        "the role touches AI, the governed human-reviewed agent workflow as",
        "distinctive proof; (4) a direct close. Sign off:",
        "Best,",
        "Geoffrey Hadfield",
        "",
        "OUTREACH FORMAT — one Markdown document with exactly these headings:",
        "## LinkedIn Connection Request   (under 300 characters)",
        "## Recruiter Direct Message      (under 170 words, names the role and",
        "   2-3 confirmed proof points)",
        "## Recruiter Email               (subject line + under 250 words)",
        "## Hiring-Manager Note           (3-4 sentences, decision-focused)",
        "## 60-Second Pitch               (spoken-style paragraph)",
        "## Follow-Up 1 - Five Business Days",
        "## Follow-Up 2 - Seven to Ten Business Days Later",
        "## Stop Rule                     (no more than two unanswered",
        "   follow-ups; add new information only with a real update)",
        "",
        "ANSWERS FORMAT — one Markdown document: 6-8 likely application and",
        "interview questions FOR THIS SPECIFIC JOB (why this role, technical",
        "leadership, analysis that influenced strategy, platform/instrumentation",
        "work, cross-team leadership, responsible AI when relevant, complex",
        "modeling, executive communication — pick what fits the posting). Each:",
        "'## <question>' then one first-person paragraph structured Situation,",
        "Decision, Action, Result, Learning — concrete, using only confirmed",
        "facts and metrics.",
        "",
        "Close with a '=== CLAIM IDS ===' section listing, one per line, the id",
        "of every ACHIEVEMENT BANK entry whose facts you used anywhere. Output",
        "the five sections in this exact order, each opened by its delimiter",
        "line: === RESUME ===, === COVER LETTER ===, === OUTREACH ===,",
        "=== ANSWERS ===, === CLAIM IDS ===.",
    ])
    notes_block = ""
    if inputs.reviewer_notes:
        notes_block = "\n".join([
            "",
            "REVIEWER NOTES (Geoff reviewed an earlier draft — address every note):",
            *[f"- {n}" for n in inputs.reviewer_notes],
        ])
    held_block = ""
    if inputs.held_claims:
        held_block = "\n".join([
            "",
            "HELD CLAIMS (unresolved evidence — never use these in any output):",
            *[f"- {h.get('claim', h.get('id', '?'))}: {h.get('reason', '')}"
              for h in inputs.held_claims],
        ])
    example_block = ""
    if inputs.format_example.strip():
        example_block = "\n".join([
            "",
            "APPROVED RESUME EXEMPLAR (a past Geoff-approved application —",
            "match its structure, voice, and bullet density; RESELECT the",
            "headline, summary, expertise groups, and bullets for the target",
            "job; its facts are pre-verified and safe to reuse):",
            inputs.format_example.strip(),
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
        held_block,
        "",
        "JOB DESCRIPTION",
        inputs.description_text.strip(),
        example_block,
        master_block,
        "",
        "ACHIEVEMENT BANK (validated claims with ids — every fact you use must",
        "trace here, to the master bank, or to the approved exemplar)",
        _bank_context(bank),
    ])
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


_REQUIRED_RESUME_HEADINGS = (
    "## Professional Summary", "## Core Expertise", "## Experience",
    "## Selected Technical Projects", "## Education")

# Internal-only artifacts that must never reach an employer-facing resume.
_EMPLOYER_FACING_FORBIDDEN = ("Target:", "## Claim Traceability", "fit score",
                              "agent trace", "claim id")


def _structure_problems(resume: str, has_master_bank: bool,
                        contact: dict | None = None,
                        employers: list[str] | None = None) -> list[str]:
    """Hard problems: a resume missing its required ATS sections, missing its
    contact block, dropping a recorded employer, or leaking internal-only
    content is not employer-ready. Without the master bank, only the core
    sections are required."""
    required = _REQUIRED_RESUME_HEADINGS if has_master_bank else (
        "## Professional Summary", "## Experience")
    problems = [f"resume is missing the '{h}' section" for h in required
                if h not in resume]
    email = (contact or {}).get("email")
    if email and email not in resume:
        problems.append(
            f"resume is missing the contact header (email {email})")
    # every recorded employer must appear (reverse-chron completeness);
    # spaces/case-insensitive so 'JP Morgan Chase' matches 'JPMorgan Chase'
    squashed = re.sub(r"\s+", "", resume).lower()
    for employer in (employers or []):
        if re.sub(r"\s+", "", employer).lower() not in squashed:
            problems.append(
                f"resume dropped the recorded employer {employer!r} — "
                "EVERY role appears, reverse-chronological")
    lowered = resume.lower()
    for marker in _EMPLOYER_FACING_FORBIDDEN:
        if marker.lower() in lowered:
            problems.append(
                f"resume contains internal-only content: {marker!r}")
    return problems


def _cover_letter_problems(cover_letter: str) -> list[str]:
    """Hard problem: the standard is 250-350 words; enforce with slack. A
    too-short letter reads as low effort; a too-long one does not get read."""
    words = len(cover_letter.split())
    if words < 200:
        return [f"cover letter is {words} words — expand to 250-350 words "
                "(4 short paragraphs with confirmed metrics)"]
    if words > 400:
        return [f"cover letter is {words} words — tighten to 250-350 words"]
    return []


def bank_employers(bank: AchievementBank) -> list[str]:
    """Distinct real employers recorded in the bank (excludes the 'Project'
    placeholder used for standalone projects)."""
    seen: list[str] = []
    for a in bank.achievements:
        if a.company and a.company.lower() != "project" and a.company not in seen:
            seen.append(a.company)
    return seen


def _held_claim_problems(sections: dict[str, str],
                         held_claims: list) -> list[str]:
    """Hard problems: a held claim (conflicting/single-source evidence) leaked
    into any output section. Accuracy failures always trigger a retry."""
    combined = "\n".join(sections.get(s, "") for s in _SECTIONS
                         if s != "CLAIM IDS").lower()
    problems = []
    for h in held_claims:
        for needle in (h.get("detect") or []):
            if str(needle).lower() in combined:
                problems.append(
                    f"held claim leaked into output: {h.get('claim', h.get('id'))} "
                    f"(matched {needle!r}) — {h.get('reason', '')}")
                break
    return problems


def _tone_problems(sections: dict[str, str]) -> list[str]:
    """Soft problems: AI-tell phrases anywhere in the output. They trigger a
    corrective retry; if the model still won't drop them, the output is kept
    and the flags surface as a validation warning for Geoff (a word choice
    must not force template fallback)."""
    combined = "\n".join(sections.get(s, "") for s in _SECTIONS
                         if s != "CLAIM IDS").lower()
    flags = [f"banned phrase in output: {p!r}" for p in BANNED_PHRASES
             if p in combined]
    for name in ("RESUME", "COVER LETTER"):
        if "!" in sections.get(name, ""):
            flags.append(f"{name.lower()} contains an exclamation mark")
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


def resume_ats_text(resume_md: str) -> str:
    """Deterministic Markdown -> plain-text conversion for the ATS upload
    variant: uppercase headings, bullet dots, no markup. Regenerated whenever
    the resume changes so the two files cannot drift."""
    out: list[str] = []
    for line in resume_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            out.append(stripped.lstrip("#").strip().upper())
        elif stripped.startswith(("- ", "* ")):
            out.append("• " + stripped[2:].strip())
        else:
            out.append(stripped)
    text = "\n".join(out)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = text.replace("`", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


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
    # 3 attempts: the ATS-standard contract (held claims, contact header,
    # every employer, word bands) is strict enough that the local model
    # sometimes needs two corrections (batch of 15: 12 passed by attempt 2,
    # 3 exhausted it)
    max_attempts: int = 3,
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
                sections["RESUME"], bool(inputs.master_bank.strip()),
                inputs.contact, bank_employers(bank)))
        if sections.get("COVER LETTER"):
            hard_problems.extend(
                _cover_letter_problems(sections["COVER LETTER"]))
        hard_problems.extend(
            _held_claim_problems(sections, inputs.held_claims))
        tone_flags = _tone_problems(sections)
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
                recruiter_message=sections["OUTREACH"],
                claim_ids=claim_ids,
                model=cfg.model,
                attempts=attempt,
                tone_flags=tone_flags,
                answers=sections["ANSWERS"],
            )
        last_error = "; ".join(problems)
        messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": (
                "Your previous answer had these problems:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\nRewrite the full answer with all five sections, keeping "
                  "the required resume format (contact header included), using "
                  "only achievement ids that exist in the ACHIEVEMENT BANK, "
                  "never using a held claim, and avoiding every banned "
                  "phrase.")},
        ]
    raise AgentWriterError(
        f"writer output invalid after {max_attempts} attempts: {last_error}")
