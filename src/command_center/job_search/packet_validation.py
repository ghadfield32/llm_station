"""Packet completeness/correctness validation — the gate in front of submit.

Follows the repo's list-of-errors idiom (validate_claim_ids): every check returns
a row {id, label, ok, level, detail}; level "error" blocks submission, level
"warning" is surfaced but does not block. Nothing here mutates the packet.
"""
from __future__ import annotations

from pathlib import Path

from command_center.job_search.achievement_bank import AchievementBank, validate_claim_ids
from command_center.job_search.agent_writer import TRACE_FILENAME, read_trace
from command_center.job_search.application_memory import read_job_description
from command_center.job_search.schemas import ApplicationRecord


def _check(check_id: str, label: str, ok: bool, level: str, detail: str) -> dict:
    return {"id": check_id, "label": label, "ok": ok, "level": level, "detail": detail}


def validate_packet(
    app_dir: Path,
    record: ApplicationRecord,
    bank: AchievementBank,
) -> dict:
    checks: list[dict] = []

    missing_files = []
    empty_files = []
    for name, filename in record.materials.items():
        path = app_dir / filename
        if not path.is_file():
            missing_files.append(f"{name} ({filename})")
        elif path.stat().st_size == 0:
            empty_files.append(f"{name} ({filename})")
    checks.append(_check(
        "materials_present", "All packet files exist and are non-empty",
        not missing_files and not empty_files, "error",
        "OK: " + ", ".join(record.materials.values()) if not missing_files and not empty_files
        else "missing: " + ", ".join(missing_files) + ("; empty: " + ", ".join(empty_files) if empty_files else "")))

    try:
        description = read_job_description(app_dir)
        description_detail = (
            f"{len(description)} characters stored" if description.strip()
            else "job_description.md.gz is missing or empty")
    except (OSError, EOFError) as exc:
        description = ""
        description_detail = f"job_description.md.gz is corrupt: {type(exc).__name__}: {exc}"
    checks.append(_check(
        "job_description", "Job description is stored and readable",
        bool(description.strip()), "error", description_detail))

    checks.append(_check(
        "apply_url", "Apply URL is recorded",
        record.apply_url.startswith(("http://", "https://")), "error",
        record.apply_url or "no apply_url on the application record"))

    claim_ids = [str(c) for c in (record.generation.get("claim_ids") or record.bullet_ids_used)]
    claim_errors = validate_claim_ids(bank, claim_ids)
    checks.append(_check(
        "claims_valid", "Every claim traces to the achievement bank",
        bool(claim_ids) and not claim_errors, "error",
        f"{len(claim_ids)} claim id(s) verified: {', '.join(claim_ids)}"
        if claim_ids and not claim_errors
        else "; ".join(claim_errors) or "no claim ids recorded for this packet"))

    mode = str(record.generation.get("mode") or "unknown")
    generation_error = str(record.generation.get("error") or "")
    checks.append(_check(
        "agent_generated", "Materials were written by the agent writer",
        mode == "agent", "warning",
        f"mode=agent, model={record.generation.get('model')}, "
        f"attempts={record.generation.get('attempts')}" if mode == "agent"
        else f"mode={mode}: {generation_error or 'template output — regenerate before submitting'}"))

    trace = read_trace(app_dir)
    checks.append(_check(
        "agent_trace", "Agent thinking/context is on disk for review",
        any(t.get("ok") for t in trace), "warning",
        f"{len(trace)} trace entr(ies) in {TRACE_FILENAME}" if trace
        else "no agent trace recorded (template-mode packet)"))

    used_master = bool(record.generation.get("master_bank"))
    if used_master:
        master_detail = "master bullet bank was in the writer context"
    elif mode != "agent":
        # vacuously ok: the agent_generated warning above already tells Geoff
        # to regenerate; this check judges master-bank use of AGENT output
        master_detail = "not judged until the packet is agent-generated"
    else:
        master_detail = (
            "written without profile/master_resume_bank.md (or the source "
            ".docx) — regenerate after restoring it so the resume uses "
            "Geoff's own bullets, skills sections, and education")
    checks.append(_check(
        "master_bank", "Resume composed from Geoff's master bullet bank",
        mode != "agent" or used_master, "warning", master_detail))

    tone_flags = [str(t) for t in (record.generation.get("tone_flags") or [])]
    checks.append(_check(
        "tone", "No AI-tell phrasing survived generation",
        not tone_flags, "warning",
        "clean" if not tone_flags else "; ".join(tone_flags)))

    checks.append(_check(
        "review_clean", "No unresolved change requests",
        record.review_state != "changes_requested", "error",
        f"review_state={record.review_state}, revision={record.revision}"))

    # Keyed on applied_at, not status: a later recruiter/interview note flips
    # status to recruiter_contact but must never re-arm a second submission.
    checks.append(_check(
        "not_already_submitted", "Application has not already been submitted",
        not record.applied_at, "error",
        f"status={record.status}, applied_at={record.applied_at or '-'}"))

    errors = [c for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warning"]
    return {
        "ok": not errors,
        "errors": [c["id"] for c in errors],
        "warnings": [c["id"] for c in warnings],
        "checks": checks,
    }
