"""Desktop adapter readiness tests.

Hermetic: no browser, no screenshots, no GUI actions, no AppFlowy network.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import yaml

from command_center.cli import desktop_adapter

REPO_ROOT = Path(__file__).resolve().parents[1]


def _raw_config():
    return yaml.safe_load((REPO_ROOT / "configs" / "autonomy.yaml").read_text(encoding="utf-8"))


def _write_snapshot(root, *, status: str = "In Progress") -> None:
    snapshot = {
        "generated_at": "2026-06-17T00:00:00+00:00",
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


def test_desktop_adapter_blocks_current_disabled_manifest(tmp_path):
    _write_snapshot(tmp_path)

    result = desktop_adapter.verify_readiness(root=tmp_path)

    assert result["status"] == "blocked"
    assert "desktop_target_appflowy_browser_staging_not_enabled" in result["blockers"]
    assert "desktop_target_appflowy_browser_staging_action_timeout_policy_missing" in result["blockers"]
    assert result["desktop_actions_performed"] is False
    assert result["screenshots_captured"] is False
    assert result["clipboard_read"] is False
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False


def test_desktop_adapter_passes_fully_declared_manifest_without_actions(tmp_path):
    raw = _raw_config()
    target = deepcopy(raw["desktop_targets"][0])
    target.update({
        "enabled": True,
        "ttl_minutes": 5,
        "ttl_source": "test_policy",
        "action_timeout_seconds": 30,
        "action_timeout_source": "test_policy",
        "human_takeover_hotkey": "Ctrl+Alt+Esc",
        "screenshot_artifact_policy": "redacted_hashes_and_refs_only",
        "blockers": [],
    })
    raw["desktop_targets"][0] = target
    config_path = _write_config(tmp_path, raw)
    _write_snapshot(tmp_path)
    output = tmp_path / "desktop-adapter-readiness.json"

    result = desktop_adapter.verify_readiness(
        config_path=config_path,
        root=tmp_path,
        output=output,
    )
    saved = output.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["targets"][0]["live_actions_enabled"] is True
    assert result["desktop_actions_performed"] is False
    assert result["screenshots_captured"] is False
    assert "Ctrl+Alt+Esc" not in saved
