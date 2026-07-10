from __future__ import annotations

import gzip
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from command_center.job_search.achievement_bank import AchievementBank, ensure_bank
from command_center.job_search.agent_writer import (
    TRACE_FILENAME,
    AgentWriterError,
    MaterialInputs,
    ensure_master_bank_text,
    generate_materials,
    load_contact,
    load_evidence_policy,
    load_format_example,
    resume_ats_text,
)
from command_center.job_search.config import data_root, ensure_data_dirs, load_config
from command_center.job_search.followups import generate_followup
from command_center.job_search.interview_prep import render_answer_bank
from command_center.job_search.resume_selection import render_selection_report
from command_center.job_search.scoring import application_id_for
from command_center.job_search.standing_answers import (
    load_standing_answers,
    render_application_answers,
    split_detected_phrases,
)
from command_center.job_search.schemas import (
    ApplicationRecord,
    ApplicationSalary,
    AutomationResult,
    CanonicalJob,
    FitResult,
    ResumeSelection,
)

REVIEW_NOTES_FILENAME = "review_notes.md"


def _load_writing_style(base: Path) -> dict[str, str]:
    path = base / "profile" / "writing_style.yml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: str(v) for k, v in data.items() if isinstance(v, str)}


def _agent_writer_enabled() -> bool:
    """The agent writer is the default path; JOB_SEARCH_AGENT_WRITER=0 pins the
    deterministic templates (tests, offline runs). Either way application.yml
    records which mode actually produced the materials."""
    return os.environ.get("JOB_SEARCH_AGENT_WRITER", "1") != "0"


def _read_review_notes(app_dir: Path) -> list[str]:
    path = app_dir / REVIEW_NOTES_FILENAME
    if not path.is_file():
        return []
    notes: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- "):
            notes.append(line[2:].strip())
    return notes


def _append_review_note(app_dir: Path, note: str) -> None:
    path = app_dir / REVIEW_NOTES_FILENAME
    if not path.is_file():
        path.write_text("# Review Notes\n\n", encoding="utf-8")
    stamp = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- {note.strip()} ({stamp})\n")


def _run_agent_writer(
    app_dir: Path,
    inputs: MaterialInputs,
    bank: AchievementBank,
    *,
    trace_step: str,
) -> dict:
    """Generate resume/cover letter/recruiter message with the LLM writer and
    overwrite the packet files. Returns the `generation` provenance dict for
    application.yml; on failure the template files stay in place and the failure
    is recorded (mode template_fallback + error) — visible, never silent."""
    now = datetime.now(timezone.utc).isoformat()
    if not _agent_writer_enabled():
        return {
            "mode": "template_fallback",
            "error": "agent writer disabled via JOB_SEARCH_AGENT_WRITER=0",
            "generated_at": now,
        }
    try:
        materials = generate_materials(
            inputs, bank, trace_path=app_dir / TRACE_FILENAME, trace_step=trace_step)
    except AgentWriterError as exc:
        return {"mode": "template_fallback", "error": str(exc), "generated_at": now}
    (app_dir / "generated_resume.md").write_text(materials.resume + "\n", encoding="utf-8")
    (app_dir / "resume_ats.txt").write_text(
        resume_ats_text(materials.resume), encoding="utf-8")
    (app_dir / "cover_letter.md").write_text(materials.cover_letter + "\n", encoding="utf-8")
    (app_dir / "recruiter_message.md").write_text(
        materials.recruiter_message + "\n", encoding="utf-8")
    if materials.answers.strip():
        (app_dir / "answer_bank.md").write_text(
            materials.answers + "\n", encoding="utf-8")
    return {
        "mode": "agent",
        "model": materials.model,
        "attempts": materials.attempts,
        "claim_ids": materials.claim_ids,
        "generated_at": now,
        # provenance for validation: which profile context was in the prompt,
        # and did any AI-tell phrases survive the corrective retry?
        "master_bank": bool(inputs.master_bank.strip()),
        "contact": bool(inputs.contact),
        "evidence_policy": bool(inputs.held_claims),
        "format_example": bool(inputs.format_example.strip()),
        "tone_flags": materials.tone_flags,
    }


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _write_yaml(path: Path, data: object) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def create_prepared_application(
    job: CanonicalJob,
    fit: FitResult,
    automation: AutomationResult,
    selection: ResumeSelection,
    *,
    root: Path | None = None,
    executor: str = "auto",
    bank: AchievementBank | None = None,
) -> Path:
    cfg = load_config()
    base = root or data_root(cfg)
    ensure_data_dirs(base)
    today = _today()
    app_id = application_id_for(job, today.isoformat())
    app_dir = base / "applications_active" / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    retention_until = today + timedelta(days=cfg.retention.rich_application_cache_days)
    manual_reason = "; ".join(automation.blockers) if automation.blockers else (
        "MVP submit path is disabled; Geoff must review and submit manually."
    )
    record = ApplicationRecord(
        application_id=app_id,
        company=job.company,
        role_title=job.role_title,
        category=selection.resume_variant,
        source=job.source,
        portal=job.portal,
        apply_url=job.apply_url,
        status="prepared",
        stage="needs_geoff",
        automation_class=automation.value,
        manual_required=True,
        manual_reason=manual_reason,
        resume_variant=selection.resume_variant,
        applied_at=None,
        last_activity_at=today.isoformat(),
        retention_until=retention_until.isoformat(),
        salary=ApplicationSalary(
            listed=job.salary_min is not None,
            min=job.salary_min,
            max=job.salary_max,
            currency=job.currency,
            notes=job.salary_text,
        ),
        fit=fit,
        keywords={
            "required": [],
            "preferred": selection.matched_keywords,
            "matched": selection.matched_keywords,
            "gaps": selection.unsupported_keywords,
        },
        materials={
            "resume_markdown": "generated_resume.md",
            "cover_letter_markdown": "cover_letter.md",
            "recruiter_message": "recruiter_message.md",
            "job_description_gz": "job_description.md.gz",
            "resume_selection_report": "resume_selection_report.md",
            "manual_checklist": "manual_checklist.md",
            "executor_metadata": "executor.json",
            "answer_bank": "answer_bank.md",
            "application_answers": "application_answers.md",
        },
        followup={
            "next_action": "Geoff reviews the prepared materials and submits manually if appropriate.",
            "suggested_reply_ready": True,
            "talking_points": selection.selected_achievement_ids[:4],
        },
        bullet_ids_used=selection.selected_achievement_ids,
    )
    with gzip.open(app_dir / "job_description.md.gz", "wt", encoding="utf-8") as fh:
        fh.write(job.description_text)
    comms_path = app_dir / "communications.jsonl"
    if not comms_path.exists():
        comms_path.write_text("", encoding="utf-8")
    notes_path = app_dir / "recruiter_notes.md"
    if not notes_path.exists():
        notes_path.write_text("# Recruiter Notes\n", encoding="utf-8")
    # Deterministic templates first (they are the honest fallback), then the agent
    # writer overwrites resume/cover letter/recruiter message when it succeeds.
    (app_dir / "generated_resume.md").write_text(render_resume(job, selection), encoding="utf-8")
    (app_dir / "cover_letter.md").write_text(render_cover_letter(job, selection), encoding="utf-8")
    (app_dir / "recruiter_message.md").write_text(render_recruiter_message(job), encoding="utf-8")
    (app_dir / "manual_checklist.md").write_text(
        render_manual_checklist(job, automation, cfg, executor), encoding="utf-8"
    )
    answer_bank_bank = bank or ensure_bank(base / "profile" / "achievement_bank.yml")
    (app_dir / "answer_bank.md").write_text(
        render_answer_bank(job, answer_bank_bank, selection), encoding="utf-8"
    )
    # Standing answers are rendered deterministically (compliance answers are
    # exact, never model-paraphrased) using THIS posting's detected questions
    # and salary range.
    (app_dir / "application_answers.md").write_text(
        render_application_answers(
            load_standing_answers(base),
            salary_max=job.salary_max, salary_text=job.salary_text,
            currency=job.currency,
            detected_phrases=automation.auto_answered),
        encoding="utf-8")
    record.generation = _run_agent_writer(
        app_dir,
        MaterialInputs(
            company=job.company,
            role_title=job.role_title,
            description_text=job.description_text,
            apply_url=job.apply_url,
            resume_variant=selection.resume_variant,
            matched_keywords=selection.matched_keywords,
            fit_reasons=fit.reasons,
            fit_score=fit.score,
            writing_style=_load_writing_style(base),
            master_bank=ensure_master_bank_text(base),
            contact=load_contact(base),
            held_claims=load_evidence_policy(base),
            format_example=load_format_example(base),
        ),
        answer_bank_bank,
        trace_step="generate_materials",
    )
    _write_yaml(app_dir / "application.yml", record.model_dump(mode="json"))
    (app_dir / "executor.json").write_text(
        json.dumps(
            {
                "requested_executor": executor,
                "safety_rule": (
                    "executor choice does not change claim validation, manual blockers, "
                    "or no-submit MVP behavior"
                ),
                "auto_submit_enabled": cfg.job_search.auto_submit_enabled,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (app_dir / "resume_selection_report.md").write_text(
        render_selection_report(job, selection), encoding="utf-8"
    )
    generate_followup(app_dir)
    return app_dir


def render_resume(job: CanonicalJob, selection: ResumeSelection) -> str:
    return "\n".join(
        [
            "# Geoffrey Hadfield - Targeted Resume Draft",
            "",
            f"Target: {job.company} - {job.role_title}",
            f"Variant: {selection.resume_variant}",
            "",
            "## Selected Experience Bullets",
            *[f"- {bullet}" for bullet in selection.selected_bullets],
            "",
            "## Claim Traceability",
            *[f"- `{achievement_id}`" for achievement_id in selection.selected_achievement_ids],
            "",
            "Note: MVP output is Markdown. PDF/DOCX rendering is a later step after claim validation.",
            "",
        ]
    )


def render_cover_letter(job: CanonicalJob, selection: ResumeSelection) -> str:
    bullets = "; ".join(selection.selected_achievement_ids[:3])
    return f"""# Cover Letter Draft

I am interested in the {job.role_title} role at {job.company} because it maps directly to my analytics engineering, applied ML, and product-facing data science background. The strongest evidence for this role is: {bullets}.

I would tailor this further after reviewing the company's team, product surface, and any recruiter context. This draft is not sent automatically.
"""


def render_recruiter_message(job: CanonicalJob) -> str:
    return f"""Hi - I am interested in the {job.role_title} role at {job.company}. The role appears to line up with my experience in production analytics engineering, experimentation, applied ML, and recent World Model Sports work. I would be glad to connect if the team is looking for someone who can move between data infrastructure, modeling, and stakeholder-facing decision tools.

Draft only. Geoff reviews before sending.
"""


def render_manual_checklist(job: CanonicalJob, automation: AutomationResult, cfg, executor: str) -> str:
    blockers = automation.blockers or [
        "MVP submit path is disabled; Geoff reviews and submits manually."
    ]
    review_required = "\n".join(
        f"- {item}" for item in cfg.application_questions.review_required
    )
    draft_defaults = "\n".join(
        f"- {key}: {value}" for key, value in cfg.application_questions.draft_defaults.items()
    )
    never_auto = "\n".join(
        f"- {item}" for item in cfg.application_questions.never_auto_answer
    )
    blocker_lines = "\n".join(f"- {item}" for item in blockers)
    auto_answered_block = ""
    if automation.auto_answered:
        answered = "\n".join(f"- {item}" for item in automation.auto_answered)
        auto_answered_block = (
            "\n## Questions Auto-Answered From Standing Answers\n"
            "Review them in application_answers.md before submitting.\n"
            f"{answered}\n")
    return f"""# Manual Application Checklist - {job.company} {job.role_title}

## Apply URL
{job.apply_url}

## Why Automation Stopped
{blocker_lines}
{auto_answered_block}

## Executor
Requested executor: `{executor}`. Executor choice does not weaken claim validation,
manual blockers, or no-submit MVP behavior.

## Steps
1. Open the apply URL.
2. Upload `generated_resume.md` content after converting to the chosen resume format.
3. Upload or paste `cover_letter.md` only if the portal asks for one.
4. Review `recruiter_message.md` before sending any message.
5. Answer all review-required questions yourself.
6. Paste any new portal questions into `recruiter_notes.md`, add them from the cockpit card,
   or add them with `cc job-search note`.
7. After submission, drag the cockpit job card to `Completed`.

## Review-Required Question Types
{review_required}

## Draft Defaults For Non-Sensitive Questions
{draft_defaults}

## Never Auto-Answer
{never_auto}
"""


def load_application(app_id: str, *, root: Path | None = None) -> tuple[Path, ApplicationRecord]:
    cfg = load_config()
    base = root or data_root(cfg)
    path = base / "applications_active" / app_id / "application.yml"
    record = ApplicationRecord.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return path.parent, record


def save_application(app_dir: Path, record: ApplicationRecord) -> None:
    _write_yaml(app_dir / "application.yml", record.model_dump(mode="json"))


def mark_submitted(app_id: str, *, root: Path | None = None) -> ApplicationRecord:
    cfg = load_config()
    app_dir, record = load_application(app_id, root=root)
    today = _today()
    record.status = "applied"
    record.stage = "completed"
    record.applied_at = today.isoformat()
    record.last_activity_at = today.isoformat()
    record.retention_until = (today + timedelta(days=cfg.retention.rich_application_cache_days)).isoformat()
    record.followup["next_action"] = "Wait 5 business days, then follow up if no response."
    save_application(app_dir, record)
    generate_followup(app_dir)
    return record


def append_note_text(
    app_id: str,
    note_type: str,
    content: str,
    *,
    root: Path | None = None,
    source: str = "manual_note",
) -> dict:
    cfg = load_config()
    app_dir, record = load_application(app_id, root=root)
    summary = content.strip().splitlines()[0][:240] if content.strip() else "Empty note."
    now = datetime.now(timezone.utc)
    event = {
        "ts": now.isoformat(),
        "type": note_type,
        "summary": summary,
        "action_needed": "Review follow-up pack and reply draft.",
        "source": source,
    }
    with (app_dir / "communications.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")
    record.last_activity_at = now.date().isoformat()
    record.status = (
        "recruiter_contact"
        if "recruiter" in note_type or "interview" in note_type
        else record.status
    )
    record.retention_until = (now.date() + timedelta(days=cfg.retention.rich_application_cache_days)).isoformat()
    record.followup["next_action"] = event["action_needed"]
    save_application(app_dir, record)
    generate_followup(app_dir)
    return event


def append_note(app_id: str, note_type: str, note_file: Path, *, root: Path | None = None) -> dict:
    content = note_file.read_text(encoding="utf-8")
    return append_note_text(app_id, note_type, content, root=root, source="manual_note")


def read_job_description(app_dir: Path) -> str:
    path = app_dir / "job_description.md.gz"
    if not path.is_file():
        return ""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()


def request_changes(
    app_id: str,
    notes: str,
    *,
    root: Path | None = None,
    source: str = "cockpit",
) -> tuple[Path, ApplicationRecord]:
    """Geoff's 'not ready / needs updates' action: record the note, flip the
    review gate to changes_requested, and log it in communications. Regeneration
    is a separate explicit step so a failed model call never loses the note."""
    app_dir, record = load_application(app_id, root=root)
    text = notes.strip()
    if not text:
        raise ValueError("request_changes requires a non-empty note")
    _append_review_note(app_dir, text)
    record.review_state = "changes_requested"
    save_application(app_dir, record)
    append_note_text(
        app_id, "review_changes_requested", text, root=root, source=source)
    _, record = load_application(app_id, root=root)
    return app_dir, record


def regenerate_materials(
    app_id: str,
    *,
    root: Path | None = None,
    bank: AchievementBank | None = None,
) -> tuple[Path, ApplicationRecord]:
    """Re-run the agent writer against ALL accumulated review notes, bump the
    revision, and return the packet to ready_for_review. The job context comes
    from the stored record + compressed job description — no re-scrape."""
    cfg = load_config()
    base = root or data_root(cfg)
    app_dir, record = load_application(app_id, root=root)
    description = read_job_description(app_dir)
    if not description.strip():
        raise ValueError(
            f"application {app_id} has no stored job description; cannot regenerate")
    writer_bank = bank or ensure_bank(base / "profile" / "achievement_bank.yml")
    generation = _run_agent_writer(
        app_dir,
        MaterialInputs(
            company=record.company,
            role_title=record.role_title,
            description_text=description,
            apply_url=record.apply_url,
            resume_variant=record.resume_variant,
            matched_keywords=list(record.keywords.get("matched", [])),
            fit_reasons=record.fit.reasons,
            fit_score=record.fit.score,
            reviewer_notes=_read_review_notes(app_dir),
            writing_style=_load_writing_style(base),
            master_bank=ensure_master_bank_text(base),
            contact=load_contact(base),
            held_claims=load_evidence_policy(base),
            format_example=load_format_example(base),
        ),
        writer_bank,
        trace_step=f"regenerate_materials_rev{record.revision + 1}",
    )
    if generation.get("mode") != "agent":
        # Keep changes_requested: the notes were NOT addressed. Surfacing the
        # error is the fix path, not quietly reverting to templates.
        raise AgentWriterError(str(generation.get("error") or "agent writer failed"))
    # Refresh the deterministic standing answers alongside the regenerated
    # materials so profile edits (Jobs settings drawer) propagate on the next
    # regenerate; detected questions are re-derived from the stored JD.
    standing = load_standing_answers(base)
    asked, _uncovered = split_detected_phrases(
        description, cfg.automation.manual_phrases, standing)
    (app_dir / "application_answers.md").write_text(
        render_application_answers(
            standing,
            salary_max=record.salary.max, salary_text=record.salary.notes,
            currency=record.salary.currency, detected_phrases=asked),
        encoding="utf-8")
    # Re-load before mutating: the model call above can take minutes, and a
    # note that landed meanwhile (append_note_text load->save) must not be
    # clobbered by saving this function's stale pre-call snapshot.
    app_dir, record = load_application(app_id, root=root)
    record.generation = generation
    record.revision = record.revision + 1
    record.review_state = "ready_for_review"
    record.last_activity_at = _today().isoformat()
    record.materials.setdefault("application_answers", "application_answers.md")
    save_application(app_dir, record)
    append_note_text(
        app_id,
        "materials_regenerated",
        f"Materials regenerated (revision {record.revision}) addressing "
        f"{len(_read_review_notes(app_dir))} review note(s).",
        root=root,
        source="agent_writer",
    )
    _, record = load_application(app_id, root=root)
    return app_dir, record
