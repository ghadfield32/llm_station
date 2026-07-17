"""Finalize an application: validate the packet, mark it submitted, email the
record, and write submission_record.json as evidence.

Both cockpit paths — recording an external submission and dragging the card to
Completed — run through finalize_application, so there is exactly one gate.
Validation errors BLOCK finalization (FinalizeBlocked carries the full check
list); email problems never block (the packet record on disk is authoritative)
but are reported verbatim in the result and evidence file.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from command_center.job_search.achievement_bank import ensure_bank
from command_center.job_search.application_memory import (
    atomic_write_text,
    load_application,
    mark_submitted,
)
from command_center.job_search.config import data_root, load_config
from command_center.job_search.packet_validation import validate_packet
from command_center.job_search.record_email import send_application_record
from command_center.write_locking import application_memory_write_lock

SUBMISSION_RECORD_FILENAME = "submission_record.json"


class FinalizeBlocked(RuntimeError):
    def __init__(self, validation: dict):
        self.validation = validation
        failed = ", ".join(validation.get("errors", []))
        super().__init__(f"packet validation failed: {failed}")


def finalize_application(
    app_id: str,
    *,
    root: Path | None = None,
    sender_fn=None,
    env=None,
) -> dict:
    cfg = load_config()
    base = root or data_root(cfg)
    with application_memory_write_lock(base, app_id):
        # Re-read and validate inside the same boundary as applied_at. A packet
        # edit/change request cannot land after validation but before marking,
        # and a second finalizer sees applied_at before it can send another mail.
        app_dir, record = load_application(app_id, root=base)
        bank = ensure_bank(base / "profile" / "achievement_bank.yml")
        validation = validate_packet(app_dir, record, bank)
        if not validation["ok"]:
            raise FinalizeBlocked(validation)
        record = mark_submitted(app_id, root=base)
        finalized_at = datetime.now(timezone.utc).isoformat()
        evidence = {
            "finalized_at": finalized_at,
            "application_id": app_id,
            "company": record.company,
            "role_title": record.role_title,
            "apply_url": record.apply_url,
            "revision": record.revision,
            "generation_mode": record.generation.get("mode"),
            "validation": validation,
            # Crash-safe marker: applied_at is already durable and retry is
            # blocked, so a crash cannot cause a duplicate external email.
            "email": {"status": "pending", "record_path": None},
        }
        submission_path = app_dir / SUBMISSION_RECORD_FILENAME
        atomic_write_text(
            submission_path,
            json.dumps(evidence, indent=2, ensure_ascii=False),
        )
        email = send_application_record(
            app_dir, record, sender_fn=sender_fn, env=env)
        evidence["email"] = email
        atomic_write_text(
            submission_path,
            json.dumps(evidence, indent=2, ensure_ascii=False),
        )
        return {
            "application_id": app_id,
            "record": record.model_dump(mode="json"),
            "validation": validation,
            "email": email,
            "submission_record_path": str(submission_path),
        }
