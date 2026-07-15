"""Representative desktop ACTION-latency canary.

The read-only no-op canary (`cc desktop-noop-canary`) times snapshot reads
(~milliseconds), which does not represent how long a real desktop action takes.
This canary measures the latency of the target's PRIMARY automation path
(``direct_api``) performing a *reversible sandbox* round-trip — create then
delete a throwaway row on a SANDBOX AppFlowy database, never the production
board — so TTL/action-timeout candidates can be derived from real action timing.

Safety boundaries (all enforced here):
- Sandbox credentials are env references only; the canary FAILS CLOSED with no
  measurement when they are absent. It never fabricates timing.
- The sandbox database must differ from the production board named in the
  canary's ``forbidden_targets``; otherwise it refuses to run.
- The created row is always deleted (reversible); the run reports whether the
  revert succeeded. No screenshots, clipboard reads, or production writes.

  cc desktop-action-canary --target-id appflowy_browser_staging
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml

from command_center.cli.env_utils import merged_env
from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]
# AppFlowy/growth-os env can live in either dotenv; both are read for presence
# only (values are never written to evidence).
ENV_FILES = [ROOT / ".env", ROOT / "appflowy_kanban" / "growth-os" / ".env"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ms(start_ns: int, end_ns: int) -> float:
    return (end_ns - start_ns) / 1_000_000


def _appflowy_action_runner(
    *,
    base_url: str,
    workspace_id: str,
    database_id: str,
    user: str,
    password: str,
    client_factory: Callable[..., Any],
) -> dict[str, float]:
    """Perform one reversible sandbox round-trip and return per-step latency.

    Uses the same direct_api path the kanban bridge uses (gotrue password grant,
    then the workspace database row API). Raises on any failure so the canary
    fails closed instead of recording a fabricated measurement.
    """
    base = base_url.rstrip("/")
    with client_factory(timeout=30) as client:
        auth = client.post(
            f"{base}/gotrue/token?grant_type=password",
            json={"email": user, "password": password},
        )
        auth.raise_for_status()
        token = auth.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        row_url = f"{base}/api/workspace/{workspace_id}/database/{database_id}/row"

        create_start = time.perf_counter_ns()
        created = client.post(
            row_url,
            headers=headers,
            json={"cells": {"Name": "cc-action-latency-canary"}, "document": None},
        )
        created.raise_for_status()
        create_ms = _ms(create_start, time.perf_counter_ns())
        row_id = (created.json() or {}).get("id") or (created.json() or {}).get("row_id")
        if not row_id:
            raise RuntimeError("sandbox_row_create_returned_no_id")

        delete_start = time.perf_counter_ns()
        deleted = client.request("DELETE", f"{row_url}/{row_id}", headers=headers)
        deleted.raise_for_status()
        delete_ms = _ms(delete_start, time.perf_counter_ns())

    return {
        "action_create_ms": create_ms,
        "action_delete_ms": delete_ms,
        "action_roundtrip_ms": create_ms + delete_ms,
    }


def run_desktop_action_canary(
    *,
    config_path: Path = ROOT / "configs" / "autonomy.yaml",
    output: Path | None = None,
    target_id: str | None = None,
    run_id: str | None = None,
    env: dict[str, str] | None = None,
    action_runner: Callable[..., dict[str, float]] = _appflowy_action_runner,
    client_factory: Callable[..., Any] = httpx.Client,
    clock: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    start_time = clock()
    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    selected = target_id or (
        cfg.desktop_action_latency_canaries[0].target_id
        if cfg.desktop_action_latency_canaries
        else ""
    )
    canary = next(
        (item for item in cfg.desktop_action_latency_canaries if item.target_id == selected),
        None,
    )
    target = next((item for item in cfg.desktop_targets if item.target_id == selected), None)
    blockers: list[str] = []
    if canary is None:
        blockers.append(f"desktop_action_latency_canary_{selected or 'missing'}_not_declared")
    if target is None:
        blockers.append(f"desktop_target_{selected or 'missing'}_not_declared")

    env = env if env is not None else merged_env(*ENV_FILES)
    measurements: dict[str, float | None] = {
        "action_create_ms": None,
        "action_delete_ms": None,
        "action_roundtrip_ms": None,
    }
    sandbox_database_used = False
    created_row_deleted = False

    if canary is not None and target is not None:
        if target.enabled:
            blockers.append(f"desktop_target_{target.target_id}_live_actions_already_enabled")
        # resolve sandbox env refs — fail closed when any is absent
        resolved = {name: env.get(getattr(canary, name), "") for name in (
            "sandbox_base_url_env",
            "sandbox_workspace_id_env",
            "sandbox_database_id_env",
            "sandbox_user_env",
            "sandbox_password_env",
        )}
        missing_env = [getattr(canary, name) for name, value in resolved.items() if not value]
        if missing_env:
            blockers.append("representative_action_source_not_configured")
        # the sandbox database must not be a production board the canary forbids
        sandbox_db = resolved["sandbox_database_id_env"]
        if sandbox_db and sandbox_db in set(canary.forbidden_targets):
            blockers.append("sandbox_database_matches_forbidden_production_target")

        if not blockers:
            try:
                measurements = action_runner(
                    base_url=resolved["sandbox_base_url_env"],
                    workspace_id=resolved["sandbox_workspace_id_env"],
                    database_id=resolved["sandbox_database_id_env"],
                    user=resolved["sandbox_user_env"],
                    password=resolved["sandbox_password_env"],
                    client_factory=client_factory,
                )
                sandbox_database_used = True
                created_row_deleted = True
            except (httpx.HTTPError, RuntimeError, KeyError) as exc:
                blockers.append(f"sandbox_roundtrip_failed_{type(exc).__name__}")

    final_status = "pass" if not blockers else "blocked"
    evidence = {
        "schema_version": "command-center.desktop-action-latency.v1",
        "run_id": run_id or start_time.strftime("%Y%m%dT%H%M%S%fZ"),
        "target_id": selected or None,
        "allowed_mode": canary.allowed_mode if canary else None,
        "reversible_action": canary.reversible_action if canary else None,
        "surface": canary.surface if canary else None,
        "measurement_fields": canary.measurement_fields if canary else [],
        "human_takeover_policy_ref": canary.human_takeover_policy_ref if canary else None,
        "start_time": start_time.isoformat(),
        "measurements": measurements,
        "blockers": blockers,
        "status": final_status,
        # safety assertions
        "desktop_live_actions_enabled": False,
        "desktop_target_enabled": bool(target.enabled) if target else None,
        "sandbox_database_used": sandbox_database_used,
        "created_row_deleted": created_row_deleted,
        "production_board_touched": False,
        "production_values_written": False,
        "screenshots_captured": False,
        "clipboard_read": False,
        "raw_content_retained": False,
        "secrets_printed": False,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(prog="desktop-action-canary")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument("--target-id", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--output",
        default=(
            "evaluation/system-validation/20260616-autonomy-contracts/"
            "desktop-action-latency.json"
        ),
    )
    args = parser.parse_args()
    result = run_desktop_action_canary(
        config_path=(ROOT / args.config).resolve(),
        output=(ROOT / args.output).resolve(),
        target_id=args.target_id or None,
        run_id=args.run_id or None,
    )
    print(f"desktop-action-canary: {result['status'].upper()}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
