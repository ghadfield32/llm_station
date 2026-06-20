"""Desktop adapter readiness gate.

This is the smallest safe adapter layer: it validates the desktop target
manifest and current target evidence before any live GUI/browser action can be
enabled. It performs no clicks, keystrokes, screenshots, clipboard reads, or
desktop writes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from command_center.cli.desktop_target_verify import verify_desktop_targets
from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]
SUPPORTED_SURFACES = {"direct_api", "browser"}


def verify_readiness(
    *,
    config_path: Path = ROOT / "configs" / "autonomy.yaml",
    output: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    target_evidence = verify_desktop_targets(config_path=config_path, root=root)
    evidence_by_id = {
        item["target_id"]: item
        for item in target_evidence.get("targets", [])
    }
    targets: list[dict[str, Any]] = []
    blockers: list[str] = []
    timeout_takeover_policy_declared = (
        "desktop_timeout_and_human_takeover_policy_declared" in cfg.completed_work
    )

    for target in cfg.desktop_targets:
        target_blockers: list[str] = []
        target_state = evidence_by_id.get(target.target_id, {})
        if target_state.get("status") != "pass":
            target_blockers.append(f"desktop_target_{target.target_id}_state_not_verified")
        if target.surface not in SUPPORTED_SURFACES:
            target_blockers.append(f"desktop_target_{target.target_id}_surface_not_supported")
        if not target.enabled:
            target_blockers.append(f"desktop_target_{target.target_id}_not_enabled")
        if not timeout_takeover_policy_declared:
            target_blockers.append(
                f"desktop_target_{target.target_id}_timeout_takeover_policy_missing"
            )
        if target.ttl_minutes is None:
            target_blockers.append(f"desktop_target_{target.target_id}_ttl_measurement_missing")
        if target.action_timeout_seconds is None:
            target_blockers.append(
                f"desktop_target_{target.target_id}_action_timeout_measurement_missing"
            )
        if not target.human_takeover_hotkey:
            target_blockers.append(f"desktop_target_{target.target_id}_human_takeover_missing")
        if not target.screenshot_artifact_policy:
            target_blockers.append(f"desktop_target_{target.target_id}_screenshot_policy_missing")

        result = {
            "target_id": target.target_id,
            "surface": target.surface,
            "target_state_status": target_state.get("status", "missing"),
            "adapter_supported": target.surface in SUPPORTED_SURFACES,
            "live_actions_enabled": target.enabled,
            "timeout_takeover_policy_declared": timeout_takeover_policy_declared,
            "ttl_control_measured": target.ttl_minutes is not None,
            "ttl_source": target.ttl_source,
            "action_timeout_control_measured": target.action_timeout_seconds is not None,
            "action_timeout_source": target.action_timeout_source,
            "human_takeover_declared": bool(target.human_takeover_hotkey),
            "human_takeover_value_retained": False,
            "screenshot_artifact_policy": target.screenshot_artifact_policy,
            "allowed_actions": target.allowed_actions,
            "forbidden_actions": target.forbidden_actions,
            "blockers": target_blockers,
            "status": "pass" if not target_blockers else "blocked",
        }
        targets.append(result)
        blockers.extend(target_blockers)

    result = {
        "status": "pass" if not blockers else "blocked",
        "capabilities": [
            "verify_target_state",
            "enforce_manifest_before_actions",
            "write_redacted_readiness_evidence",
        ],
        "targets": targets,
        "blockers": blockers,
        "desktop_actions_performed": False,
        "screenshots_captured": False,
        "clipboard_read": False,
        "writes_performed": False,
        "secrets_printed": False,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="desktop-adapter")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument(
        "--output",
        default="evaluation/system-validation/20260616-autonomy-contracts/desktop-adapter-readiness.json",
    )
    args = parser.parse_args()

    result = verify_readiness(
        config_path=(ROOT / args.config).resolve(),
        output=(ROOT / args.output).resolve(),
    )
    print(f"desktop-adapter: {result['status'].upper()}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
