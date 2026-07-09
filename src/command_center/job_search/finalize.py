"""Finalize an application: validate the packet, mark it submitted, email the
record, and write submission_record.json as evidence.

Both cockpit paths — the Approve & Submit button and dragging the card to
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
    load_application,
    mark_submitted,
)
from command_center.job_search.config import data_root, load_config
from command_center.job_search.packet_validation import validate_packet
from command_center.job_search.record_email import send_application_record

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
    app_dir, record = load_application(app_id, root=root)
    bank = ensure_bank(base / "profile" / "achievement_bank.yml")
    validation = validate_packet(app_dir, record, bank)
    if not validation["ok"]:
        raise FinalizeBlocked(validation)
    record = mark_submitted(app_id, root=root)
    email = send_application_record(
        app_dir, record, sender_fn=sender_fn, env=env)
    evidence = {
        "finalized_at": datetime.now(timezone.utc).isoformat(),
        "application_id": app_id,
        "company": record.company,
        "role_title": record.role_title,
        "apply_url": record.apply_url,
        "revision": record.revision,
        "generation_mode": record.generation.get("mode"),
        "validation": validation,
        "email": email,
    }
    (app_dir / SUBMISSION_RECORD_FILENAME).write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "application_id": app_id,
        "record": record.model_dump(mode="json"),
        "validation": validation,
        "email": email,
        "submission_record_path": str(app_dir / SUBMISSION_RECORD_FILENAME),
    }
