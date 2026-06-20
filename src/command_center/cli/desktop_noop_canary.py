"""Read-only desktop/browser canary telemetry.

This canary records timing evidence for the declared desktop target without
clicking, typing, capturing screenshots, reading the clipboard, or mutating
AppFlowy. It is instrumentation only; it cannot enable desktop live actions or
write production TTL/action-timeout controls.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from command_center.cli.desktop_target_verify import verify_desktop_targets
from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _duration_ms(start_ns: int, end_ns: int) -> float:
    return (end_ns - start_ns) / 1_000_000


def _load_json_timed(path: Path) -> tuple[dict[str, Any] | None, float, str | None]:
    start = time.perf_counter_ns()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, _duration_ms(start, time.perf_counter_ns()), "snapshot_missing"
    except json.JSONDecodeError:
        return None, _duration_ms(start, time.perf_counter_ns()), "snapshot_unreadable"
    return data, _duration_ms(start, time.perf_counter_ns()), None


def _target_result(targets: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
    return next((target for target in targets if target.get("target_id") == target_id), None)


def run_desktop_noop_canary(
    *,
    config_path: Path = ROOT / "configs" / "autonomy.yaml",
    output: Path | None = None,
    root: Path = ROOT,
    target_id: str | None = None,
    run_id: str | None = None,
    clock: Any = _utc_now,
) -> dict[str, Any]:
    start_time = clock()
    start_ns = time.perf_counter_ns()
    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    selected = target_id or (cfg.desktop_noop_canaries[0].target_id if cfg.desktop_noop_canaries else "")
    canary = next((item for item in cfg.desktop_noop_canaries if item.target_id == selected), None)
    target = next((item for item in cfg.desktop_targets if item.target_id == selected), None)
    blockers: list[str] = []

    if canary is None:
        blockers.append(f"desktop_noop_canary_{selected or 'missing'}_not_declared")
    if target is None:
        blockers.append(f"desktop_target_{selected or 'missing'}_not_declared")

    measurements = {
        "snapshot_load_ms": None,
        "target_verify_ms": None,
        "total_duration_ms": None,
    }
    visible_target_assertions: dict[str, Any] = {
        "snapshot_present": False,
        "target_identity_verified": False,
        "card_ref_matched": False,
        "must_show_values_matched": [],
    }
    verifier_result: dict[str, Any] = {"status": "blocked", "blockers": []}

    if canary is not None and target is not None:
        if canary.allowed_mode != "read_only":
            blockers.append(f"desktop_noop_canary_{canary.target_id}_mode_not_implemented")
        if target.enabled:
            blockers.append(f"desktop_target_{target.target_id}_live_actions_already_enabled")
        allowed_targets = set(canary.allowed_apps_windows_domains)
        declared_windows = set(target.allowed_windows)
        if declared_windows and allowed_targets.isdisjoint(declared_windows):
            blockers.append(f"desktop_noop_canary_{canary.target_id}_target_out_of_scope")

        snapshot_ref = target.snapshot_evidence_ref or ""
        snapshot_path = Path(snapshot_ref)
        if not snapshot_path.is_absolute():
            snapshot_path = root / snapshot_path
        snapshot, snapshot_load_ms, snapshot_error = _load_json_timed(snapshot_path)
        measurements["snapshot_load_ms"] = snapshot_load_ms
        visible_target_assertions["snapshot_present"] = snapshot is not None
        if snapshot_error:
            blockers.append(f"desktop_noop_canary_{canary.target_id}_{snapshot_error}")

        verify_start = time.perf_counter_ns()
        verifier_result = verify_desktop_targets(config_path=config_path, root=root)
        measurements["target_verify_ms"] = _duration_ms(verify_start, time.perf_counter_ns())
        target_state = _target_result(verifier_result.get("targets", []), canary.target_id)
        if target_state is None:
            blockers.append(f"desktop_noop_canary_{canary.target_id}_verifier_target_missing")
        else:
            target_blockers = target_state.get("blockers", [])
            if target_state.get("status") != "pass":
                blockers.extend(str(blocker) for blocker in target_blockers)
            visible_target_assertions.update({
                "target_identity_verified": target_state.get("status") == "pass",
                "card_ref_matched": bool(target_state.get("card_found")),
                "must_show_values_matched": target.verifier.must_show,
            })

    end_time = clock()
    measurements["total_duration_ms"] = _duration_ms(start_ns, time.perf_counter_ns())
    final_status = "pass" if not blockers else "blocked"
    evidence = {
        "schema_version": "command-center.desktop-noop-canary.v1",
        "run_id": run_id or start_time.strftime("%Y%m%dT%H%M%S%fZ"),
        "mission_id": None,
        "synthetic_canary_id": f"desktop-noop-{selected or 'missing'}",
        "target_id": selected or None,
        "target_type": canary.target_type if canary else None,
        "allowed_mode": canary.allowed_mode if canary else None,
        "allowed_apps_windows_domains": canary.allowed_apps_windows_domains if canary else [],
        "forbidden_actions": canary.forbidden_actions if canary else [],
        "evidence_policy": canary.evidence_policy if canary else None,
        "screenshot_policy": canary.screenshot_policy if canary else None,
        "redaction_policy": canary.redaction_policy if canary else None,
        "human_takeover_policy_ref": canary.human_takeover_policy_ref if canary else None,
        "human_takeover_value_retained": False,
        "measurement_fields": canary.measurement_fields if canary else [],
        "max_action_count": canary.max_action_count if canary else None,
        "max_action_count_source": canary.max_action_count_source if canary else None,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_ms": measurements["total_duration_ms"],
        "measurements": measurements,
        "visible_target_assertions": visible_target_assertions,
        "verifier_result": {
            "status": verifier_result.get("status"),
            "blockers": verifier_result.get("blockers", []),
        },
        "blockers": blockers,
        "final_status": final_status,
        "status": final_status,
        "desktop_live_actions_enabled": False,
        "desktop_actions_performed": False,
        "action_count_performed": 0,
        "screenshots_captured": False,
        "clipboard_read": False,
        "password_fields_read": False,
        "writes_performed": False,
        "raw_content_retained": False,
        "secrets_printed": False,
        "production_values_written": False,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(prog="desktop-noop-canary")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument("--target-id", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--output",
        default="evaluation/system-validation/20260616-autonomy-contracts/desktop-noop-canary.json",
    )
    args = parser.parse_args()

    result = run_desktop_noop_canary(
        config_path=(ROOT / args.config).resolve(),
        output=(ROOT / args.output).resolve(),
        target_id=args.target_id or None,
        run_id=args.run_id or None,
    )
    print(f"desktop-noop-canary: {result['status'].upper()}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
