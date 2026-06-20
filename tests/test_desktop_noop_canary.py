"""Desktop no-op canary telemetry tests.

Hermetic: no browser, no screenshots, no GUI actions, no AppFlowy network.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import yaml

from command_center.cli import desktop_noop_canary, desktop_timing_derive

REPO_ROOT = Path(__file__).resolve().parents[1]


def _raw_config():
    return yaml.safe_load((REPO_ROOT / "configs" / "autonomy.yaml").read_text(encoding="utf-8"))


def _write_snapshot(root, *, status: str = "In Progress") -> None:
    snapshot = {
        "generated_at": "2026-06-20T00:00:00+00:00",
        "boards": [{
            "board": "mission_intake",
            "columns": [{
                "name": status,
                "cards": [{
                    "title": "review Q3 odds metrics",
                    "fields": {
                        "CardKey": "card-review q3 odds metrics",
                        "Status": status,
                    },
                }],
            }],
        }],
    }
    path = root / "generated" / "board-snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot), encoding="utf-8")


def _write_config(root, raw) -> Path:
    path = root / "configs" / "autonomy.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _clock():
    return datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)


def test_desktop_noop_canary_writes_redacted_evidence_only(tmp_path):
    _write_snapshot(tmp_path)
    output = tmp_path / "desktop-noop-canary.json"

    result = desktop_noop_canary.run_desktop_noop_canary(
        root=tmp_path,
        output=output,
        run_id="unit-run",
        clock=_clock,
    )
    saved = output.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["target_id"] == "appflowy_browser_staging"
    assert result["allowed_mode"] == "read_only"
    assert result["visible_target_assertions"]["target_identity_verified"] is True
    assert result["human_takeover_value_retained"] is False
    assert result["desktop_live_actions_enabled"] is False
    assert result["desktop_actions_performed"] is False
    assert result["screenshots_captured"] is False
    assert result["clipboard_read"] is False
    assert result["password_fields_read"] is False
    assert result["writes_performed"] is False
    assert result["raw_content_retained"] is False
    assert result["production_values_written"] is False
    assert "Ctrl+Alt+Pause" not in saved
    assert "OPENAI_API_KEY" not in saved
    private_key_marker = "BEGIN " + "PRIVATE " + "KEY"
    assert private_key_marker not in saved


def test_desktop_noop_canary_fails_loudly_on_missing_target(tmp_path):
    _write_snapshot(tmp_path)

    result = desktop_noop_canary.run_desktop_noop_canary(
        root=tmp_path,
        target_id="missing_target",
        clock=_clock,
    )

    assert result["status"] == "blocked"
    assert "desktop_noop_canary_missing_target_not_declared" in result["blockers"]
    assert "desktop_target_missing_target_not_declared" in result["blockers"]
    assert result["desktop_actions_performed"] is False


def test_desktop_noop_canary_fails_on_out_of_scope_window(tmp_path):
    raw = _raw_config()
    raw["desktop_noop_canaries"][0]["allowed_apps_windows_domains"] = ["OtherApp"]
    config_path = _write_config(tmp_path, raw)
    _write_snapshot(tmp_path)

    result = desktop_noop_canary.run_desktop_noop_canary(
        config_path=config_path,
        root=tmp_path,
        clock=_clock,
    )

    assert result["status"] == "blocked"
    assert "desktop_noop_canary_appflowy_browser_staging_target_out_of_scope" in result["blockers"]
    assert result["desktop_actions_performed"] is False


def test_desktop_noop_canary_blocks_if_live_actions_already_enabled(tmp_path):
    raw = _raw_config()
    target = deepcopy(raw["desktop_targets"][0])
    target.update({
        "enabled": True,
        "ttl_minutes": 5,
        "ttl_source": "unit_test_measurement_fixture",
        "action_timeout_seconds": 30,
        "action_timeout_source": "unit_test_measurement_fixture",
        "blockers": [],
    })
    raw["desktop_targets"][0] = target
    config_path = _write_config(tmp_path, raw)
    _write_snapshot(tmp_path)

    result = desktop_noop_canary.run_desktop_noop_canary(
        config_path=config_path,
        root=tmp_path,
        clock=_clock,
    )

    assert result["status"] == "blocked"
    assert "desktop_target_appflowy_browser_staging_live_actions_already_enabled" in result["blockers"]
    assert result["desktop_live_actions_enabled"] is False
    assert result["desktop_actions_performed"] is False


def _write_canary_sample(path: Path, *, status: str = "pass", target_id: str = "appflowy_browser_staging", total: float = 120.0, load: float = 40.0, verify: float = 80.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "status": status,
        "target_id": target_id,
        "allowed_mode": "read_only",
        "measurements": {
            "snapshot_load_ms": load,
            "target_verify_ms": verify,
            "total_duration_ms": total,
        },
    }), encoding="utf-8")


def test_timing_derivation_blocks_on_insufficient_samples(tmp_path):
    sample = tmp_path / "sample.json"
    _write_canary_sample(sample)

    result = desktop_timing_derive.derive_timing_candidates(
        evidence_paths=[sample],
        target_id="appflowy_browser_staging",
        required_samples=2,
        required_samples_source="unit_test_sample_plan",
    )

    assert result["status"] == "blocked"
    assert "insufficient_noop_canary_telemetry" in result["blockers"]
    assert result["observed_sample_count"] == 1
    assert result["additional_samples_required"] == 1
    assert result["candidates"] is None


def test_timing_derivation_uses_only_measured_evidence(tmp_path):
    sample_a = tmp_path / "sample-a.json"
    sample_b = tmp_path / "sample-b.json"
    _write_canary_sample(sample_a, total=120.0, load=40.0, verify=80.0)
    _write_canary_sample(sample_b, total=240.0, load=100.0, verify=90.0)

    result = desktop_timing_derive.derive_timing_candidates(
        evidence_paths=[sample_a, sample_b],
        target_id="appflowy_browser_staging",
        required_samples=2,
        required_samples_source="unit_test_sample_plan",
    )

    assert result["status"] == "proposed"
    assert result["blockers"] == []
    assert result["candidates"]["ttl_minutes_candidate"] == 240.0 / 60_000
    assert result["candidates"]["action_timeout_seconds_candidate"] == 100.0 / 1_000
    assert result["candidates"]["provisional_only_not_production_enabled"] is True
    assert result["production_values_written"] is False
    assert result["desktop_target_enabled"] is False
    assert result["placeholder_values_used"] is False


def test_timing_derivation_requires_sample_plan(tmp_path):
    sample = tmp_path / "sample.json"
    _write_canary_sample(sample)

    result = desktop_timing_derive.derive_timing_candidates(
        evidence_paths=[sample],
        target_id="appflowy_browser_staging",
    )

    assert result["status"] == "blocked"
    assert "sample_plan_missing" in result["blockers"]


def test_timing_derivation_uses_config_sample_plan_refs(tmp_path):
    raw = _raw_config()
    raw["desktop_timing_sample_plans"][0]["required_evidence_refs"] = [
        "evaluation/system-validation/unit/sample-a.json",
        "evaluation/system-validation/unit/sample-b.json",
    ]
    raw["desktop_timing_sample_plans"][0]["required_sample_count_source"] = (
        "configs/autonomy.yaml:desktop_timing_sample_plans[unit].required_evidence_refs"
    )
    config_path = _write_config(tmp_path, raw)
    _write_canary_sample(
        tmp_path / "evaluation/system-validation/unit/sample-a.json",
        total=120.0,
        load=40.0,
        verify=80.0,
    )
    _write_canary_sample(
        tmp_path / "evaluation/system-validation/unit/sample-b.json",
        total=240.0,
        load=100.0,
        verify=90.0,
    )

    result = desktop_timing_derive.derive_timing_candidates_from_config(
        config_path=config_path,
        root=tmp_path,
        target_id="appflowy_browser_staging",
    )

    assert result["status"] == "proposed"
    assert result["required_sample_count"] == 2
    assert "required_evidence_refs" in result["required_sample_count_source"]
    assert result["sample_plan"]["live_actions_allowed"] is False
    assert result["sample_plan"]["production_enabling"] is False
    assert result["candidates"]["ttl_minutes_candidate"] == 240.0 / 60_000
    assert result["candidates"]["action_timeout_seconds_candidate"] == 100.0 / 1_000
    assert result["production_values_written"] is False


def test_timing_derivation_from_config_blocks_missing_plan_evidence(tmp_path):
    raw = _raw_config()
    raw["desktop_timing_sample_plans"][0]["required_evidence_refs"] = [
        "evaluation/system-validation/unit/sample-a.json",
        "evaluation/system-validation/unit/sample-missing.json",
    ]
    config_path = _write_config(tmp_path, raw)
    _write_canary_sample(tmp_path / "evaluation/system-validation/unit/sample-a.json")

    result = desktop_timing_derive.derive_timing_candidates_from_config(
        config_path=config_path,
        root=tmp_path,
        target_id="appflowy_browser_staging",
    )

    assert result["status"] == "blocked"
    assert "insufficient_noop_canary_telemetry" in result["blockers"]
    assert result["observed_sample_count"] == 1
    assert result["additional_samples_required"] == 1
    assert {
        "path": "evaluation/system-validation/unit/sample-missing.json",
        "reason": "evidence_missing",
    } in result["rejected_evidence"]
