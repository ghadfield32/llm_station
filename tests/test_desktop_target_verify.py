"""Desktop target verifier tests.

Hermetic: the tests use synthetic board snapshots and perform no UI/cockpit
actions.
"""
from __future__ import annotations

import json

from command_center.cli import desktop_target_verify


def _write_snapshot(root, *, status: str) -> None:
    snapshot = {
        "generated_at": "2026-06-17T00:00:00+00:00",
        "boards": [{
            "board": "mission_intake",
            "columns": [{
                "name": status,
                "cards": [{
                    "title": "review Q3 odds metrics",
                    "meta": "L1 - Command Center - P2",
                    "fields": {
                        "CardKey": "card-review q3 odds metrics",
                        "Status": status,
                        "Risk": "L1",
                    },
                }],
            }],
        }],
    }
    path = root / "generated" / "board-snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot), encoding="utf-8")


def test_desktop_target_verify_passes_matching_snapshot(tmp_path):
    _write_snapshot(tmp_path, status="In Progress")
    output = tmp_path / "desktop-target-verify.json"

    result = desktop_target_verify.verify_desktop_targets(
        output=output,
        root=tmp_path,
    )

    assert result["status"] == "pass"
    assert result["targets"][0]["card_found"] is True
    assert result["targets"][0]["status_field"] == "In Progress"
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False
    assert output.exists()


def test_desktop_target_verify_blocks_mismatched_snapshot(tmp_path):
    _write_snapshot(tmp_path, status="Rejected")

    result = desktop_target_verify.verify_desktop_targets(root=tmp_path)

    assert result["status"] == "blocked"
    assert result["targets"][0]["status_field"] == "Rejected"
    assert (
        "desktop_target_cockpit_browser_staging_missing_verifier_value_In Progress"
        in result["blockers"]
    )
