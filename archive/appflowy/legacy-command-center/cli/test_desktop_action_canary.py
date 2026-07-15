"""Hermetic tests for the representative desktop action-latency canary.

No AppFlowy network, no GUI: the action round-trip and env are injected.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from command_center.cli import desktop_action_canary

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "configs" / "autonomy.yaml"
NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def _full_env():
    return {
        "APPFLOWY_SANDBOX_BASE_URL": "http://sandbox.local",
        "APPFLOWY_SANDBOX_WORKSPACE_ID": "ws-sandbox",
        "APPFLOWY_SANDBOX_DATABASE_ID": "db-sandbox",
        "APPFLOWY_SANDBOX_USER": "sandbox@example.invalid",
        "APPFLOWY_SANDBOX_PASSWORD": "sandbox-pass",
    }


def _runner(**kwargs):
    return {"action_create_ms": 600.0, "action_delete_ms": 900.0, "action_roundtrip_ms": 1500.0}


def test_action_canary_fails_closed_without_sandbox_env(tmp_path):
    result = desktop_action_canary.run_desktop_action_canary(
        config_path=CONFIG,
        target_id="appflowy_browser_staging",
        env={},  # nothing configured
        action_runner=_runner,
        clock=lambda: NOW,
        output=tmp_path / "evidence.json",
    )
    assert result["status"] == "blocked"
    assert "representative_action_source_not_configured" in result["blockers"]
    # no fabricated measurement
    assert result["measurements"]["action_roundtrip_ms"] is None
    assert result["sandbox_database_used"] is False
    assert result["production_board_touched"] is False


def test_action_canary_measures_reversible_roundtrip_when_configured(tmp_path):
    captured: dict = {}

    def runner(**kwargs):
        captured.update(kwargs)
        return _runner()

    result = desktop_action_canary.run_desktop_action_canary(
        config_path=CONFIG,
        target_id="appflowy_browser_staging",
        env=_full_env(),
        action_runner=runner,
        clock=lambda: NOW,
        output=tmp_path / "evidence.json",
    )
    assert result["status"] == "pass"
    assert result["blockers"] == []
    assert result["measurements"]["action_roundtrip_ms"] == 1500.0
    assert result["sandbox_database_used"] is True
    assert result["created_row_deleted"] is True
    assert result["allowed_mode"] == "reversible_sandbox_roundtrip"
    # the runner received the resolved sandbox values, never the production board
    assert captured["database_id"] == "db-sandbox"
    # secrets/values never serialized into the evidence artifact
    saved = (tmp_path / "evidence.json").read_text(encoding="utf-8")
    assert "sandbox-pass" not in saved


def test_action_canary_refuses_when_sandbox_points_at_forbidden_production_target(tmp_path):
    env = _full_env()
    env["APPFLOWY_SANDBOX_DATABASE_ID"] = "mission_intake"  # the production board
    result = desktop_action_canary.run_desktop_action_canary(
        config_path=CONFIG,
        target_id="appflowy_browser_staging",
        env=env,
        action_runner=_runner,
        clock=lambda: NOW,
        output=tmp_path / "evidence.json",
    )
    assert result["status"] == "blocked"
    assert "sandbox_database_matches_forbidden_production_target" in result["blockers"]
    assert result["sandbox_database_used"] is False
