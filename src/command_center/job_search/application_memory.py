from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from command_center.job_search.achievement_bank import AchievementBank, ensure_bank
from command_center.job_search.config import data_root, ensure_data_dirs, load_config
from command_center.job_search.followups import generate_followup
from command_center.job_search.interview_prep import render_answer_bank
from command_center.job_search.resume_selection import render_selection_report
from command_center.job_search.scoring import application_id_for
from command_center.job_search.schemas import (
    ApplicationRecord,
    ApplicationSalary,
    AutomationResult,
    CanonicalJob,
    FitResult,
    ResumeSelection,
)


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
        },
        followup={
            "next_action": "Geoff reviews the prepared materials and submits manually if appropriate.",
            "suggested_reply_ready": True,
            "talking_points": selection.selected_achievement_ids[:4],
        },
        bullet_ids_used=selection.selected_achievement_ids,
    )
    _write_yaml(app_dir / "application.yml", record.model_dump(mode="json"))
    with gzip.open(app_dir / "job_description.md.gz", "wt", encoding="utf-8") as fh:
        fh.write(job.description_text)
    comms_path = app_dir / "communications.jsonl"
    if not comms_path.exists():
        comms_path.write_text("", encoding="utf-8")
    notes_path = app_dir / "recruiter_notes.md"
    if not notes_path.exists():
        notes_path.write_text("# Recruiter Notes\n", encoding="utf-8")
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
    return f"""# Manual Application Checklist - {job.company} {job.role_title}

## Apply URL
{job.apply_url}

## Why Automation Stopped
{blocker_lines}

## Executor
Requested executor: `{executor}`. Executor choice does not weaken claim validation,
manual blockers, or no-submit MVP behavior.

## Steps
1. Open the apply URL.
2. Upload `generated_resume.md` content after converting to the chosen resume format.
3. Upload or paste `cover_letter.md` only if the portal asks for one.
4. Review `recruiter_message.md` before sending any message.
5. Answer all review-required questions yourself.
6. Paste any new portal questions into `recruiter_notes.md` or add them with `cc job-search note`.
7. After submission, run `uv run cc job-search mark-submitted <application_id>`.

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


def append_note(app_id: str, note_type: str, note_file: Path, *, root: Path | None = None) -> dict:
    cfg = load_config()
    app_dir, record = load_application(app_id, root=root)
    content = note_file.read_text(encoding="utf-8")
    summary = content.strip().splitlines()[0][:240] if content.strip() else "Empty note."
    now = datetime.now(timezone.utc)
    event = {
        "ts": now.isoformat(),
        "type": note_type,
        "summary": summary,
        "action_needed": "Review follow-up pack and reply draft.",
        "source": "manual_note",
    }
    with (app_dir / "communications.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")
    record.last_activity_at = now.date().isoformat()
    record.status = "recruiter_contact" if "recruiter" in note_type else record.status
    record.retention_until = (now.date() + timedelta(days=cfg.retention.rich_application_cache_days)).isoformat()
    record.followup["next_action"] = event["action_needed"]
    save_application(app_dir, record)
    generate_followup(app_dir)
    return event
