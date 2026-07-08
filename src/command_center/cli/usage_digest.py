#!/usr/bin/env python3
"""Create a weekly usage digest from LiteLLM and Ledger.

This is intentionally an operator/scheduled script, not part of the
secret-free proactive runner. It reads `.env`, queries LiteLLM spend endpoints
with the master key, summarizes Ledger mission state, and can optionally record
the digest back into the Ledger as a global event.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"
DEFAULT_OUTPUT = ROOT / "generated" / "usage-digest.md"

# abtop (PILOT, read-only): the pinned binary lives in the evaluation dir, not
# on PATH. Resolution order: --abtop-bin arg > ABTOP_BIN env > this default.
# We only ever invoke it with `--json` (a read-only snapshot); `--setup` (which
# writes ~/.claude/settings.json) is never used. See
# docs/evaluation/capability-evaluation-loop.md Part C and evaluation/.../abtop/.
ABTOP_DEFAULT_BIN = ROOT / "evaluation" / "capability-assessment" / "abtop" / "bin" / "abtop.exe"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k not in values})
    return values


def get_json(url: str, headers: dict[str, str] | None = None) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    try:
        response = httpx.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json(), None
    except Exception as exc:  # network/service failure should be visible in the report
        return None, str(exc)


def key_info(litellm_url: str, master_key: str, key_value: str) -> tuple[dict[str, Any] | None, str | None]:
    if not key_value:
        return None, "key missing from .env"
    headers = {"Authorization": f"Bearer {master_key}"}
    data, err = get_json(f"{litellm_url.rstrip('/')}/key/info?key={key_value}", headers=headers)
    if err:
        return None, err
    if isinstance(data, dict):
        return data.get("info", data), None
    return None, "unexpected LiteLLM response shape"


def ledger_summary(ledger_url: str) -> tuple[dict[str, Any], str | None]:
    data, err = get_json(f"{ledger_url.rstrip('/')}/missions")
    if err:
        return {}, err
    if not isinstance(data, list):
        return {}, "unexpected Ledger response shape"

    by_status: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for mission in data:
        if not isinstance(mission, dict):
            continue
        status = str(mission.get("status", "unknown"))
        risk = str(mission.get("risk", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
        by_risk[risk] = by_risk.get(risk, 0) + 1
    return {"mission_count": len(data), "by_status": by_status, "by_risk": by_risk}, None


def resolve_abtop_bin(env: dict[str, str], arg: str | None) -> Path:
    """Resolve the abtop binary path. Fail loud if requested but absent —
    a missing pinned binary is an operator config error, not something to
    paper over with a silent skip."""
    candidate = Path(arg) if arg else Path(env["ABTOP_BIN"]) if env.get("ABTOP_BIN") else ABTOP_DEFAULT_BIN
    if not candidate.is_file():
        raise SystemExit(
            f"--abtop requested but binary not found at {candidate}. "
            f"Pass --abtop-bin <path> or set ABTOP_BIN. (The pinned v0.4.8 "
            f"binary lives under evaluation/capability-assessment/abtop/bin/.)"
        )
    return candidate


def abtop_snapshot(bin_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read-only one-shot snapshot of live agent sessions. Invokes ONLY
    `<bin> --json`; never `--setup`. Runtime/parse failures surface as a
    visible error string in the report (not swallowed)."""
    try:
        proc = subprocess.run(
            [str(bin_path), "--json"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:  # exec failure must be visible in the report
        return None, f"abtop exec failed: {exc}"
    if proc.returncode != 0:
        return None, f"abtop exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"abtop output not JSON: {exc}"


def render_abtop_section(snapshot: dict[str, Any] | None, error: str | None) -> list[str]:
    lines = ["", "## Active Agent Sessions (abtop, read-only)", ""]
    if error:
        lines.append(f"- abtop unavailable: `{error}`")
        return lines
    sessions = snapshot.get("sessions", []) if isinstance(snapshot, dict) else []
    if not sessions:
        lines.append("- No active Claude/Codex sessions detected.")
        return lines
    by_cli: dict[str, int] = {}
    for s in sessions:
        by_cli[str(s.get("agent_cli", "unknown"))] = by_cli.get(str(s.get("agent_cli", "unknown")), 0) + 1
    lines.append(f"- Sessions: `{len(sessions)}` — by CLI: `{by_cli}`")
    lines += ["", "| pid | cli | model | status | context % | project |",
              "| ---: | --- | --- | --- | ---: | --- |"]
    for s in sessions:
        ctx = s.get("context_percent")
        ctx_str = f"{float(ctx):.1f}" if isinstance(ctx, (int, float)) else "n/a"
        lines.append(
            f"| {s.get('pid', '?')} | {s.get('agent_cli', '?')} | "
            f"{s.get('model', '?')} | {s.get('status', '?')} | {ctx_str} | "
            f"{s.get('project_name', '')} |"
        )
    return lines


def money(value: Any) -> str:
    try:
        return f"${float(value):,.4f}"
    except Exception:
        return "n/a"


def render_report(env: dict[str, str], abtop_bin: Path | None = None) -> tuple[str, dict[str, Any]]:
    litellm_url = env.get("LITELLM_URL") or "http://localhost:4000"
    ledger_url = env.get("LEDGER_BASE_URL") or "http://localhost:8090"
    master_key = env.get("LITELLM_MASTER_KEY", "")

    keys = {
        "hermes-orchestrator": env.get("HERMES_LITELLM_KEY", ""),
        "judge-gate": env.get("JUDGE_GATE_LITELLM_KEY", ""),
    }
    key_rows: list[dict[str, Any]] = []
    for alias, key_value in keys.items():
        if not master_key:
            info, err = None, "LITELLM_MASTER_KEY missing"
        else:
            info, err = key_info(litellm_url, master_key, key_value)
        key_rows.append({"alias": alias, "info": info or {}, "error": err})

    missions, ledger_error = ledger_summary(ledger_url)
    abtop_data, abtop_error = (None, None)
    if abtop_bin is not None:
        abtop_data, abtop_error = abtop_snapshot(abtop_bin)
    generated_at = datetime.now(timezone.utc).isoformat()

    lines = [
        "# Usage Digest",
        "",
        f"Generated: `{generated_at}`",
        "",
        "## LiteLLM Spend",
        "",
        "| key | spend | budget | status |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in key_rows:
        info = row["info"]
        status = row["error"] or "ok"
        lines.append(
            f"| {row['alias']} | {money(info.get('spend'))} | "
            f"{money(info.get('max_budget'))} | {status} |"
        )

    lines += ["", "## Ledger", ""]
    if ledger_error:
        lines.append(f"- Ledger unavailable: `{ledger_error}`")
    else:
        lines.append(f"- Missions scanned: `{missions.get('mission_count', 0)}`")
        lines.append(f"- By status: `{missions.get('by_status', {})}`")
        lines.append(f"- By risk: `{missions.get('by_risk', {})}`")

    if abtop_bin is not None:
        lines += render_abtop_section(abtop_data, abtop_error)

    evidence = {
        "generated_at": generated_at,
        "litellm": {row["alias"]: {"info": row["info"], "error": row["error"]} for row in key_rows},
        "ledger": {"summary": missions, "error": ledger_error},
        "abtop": {"sessions": (abtop_data or {}).get("sessions", []) if abtop_data else [], "error": abtop_error} if abtop_bin is not None else None,
    }
    return "\n".join(lines) + "\n", evidence


def post_to_ledger(env: dict[str, str], report: str, evidence: dict[str, Any]) -> None:
    ledger_url = env.get("LEDGER_BASE_URL") or "http://localhost:8090"
    summary = report.splitlines()[0] if report else "Usage digest"
    response = httpx.post(
        f"{ledger_url.rstrip('/')}/events",
        json={
            "source": "usage-digest",
            "kind": "usage_digest",
            "summary": summary,
            "evidence": evidence,
        },
        timeout=20,
    )
    response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--post-ledger", action="store_true")
    parser.add_argument("--abtop", action="store_true",
                        help="include a read-only live agent-session snapshot via the pinned abtop binary")
    parser.add_argument("--abtop-bin", default=None,
                        help="path to the abtop binary (overrides ABTOP_BIN env and the default eval path)")
    args = parser.parse_args()

    env = load_env()
    abtop_bin = resolve_abtop_bin(env, args.abtop_bin) if (args.abtop or args.abtop_bin) else None
    report, evidence = render_report(env, abtop_bin=abtop_bin)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"wrote {out}")

    if args.post_ledger:
        post_to_ledger(env, report, evidence)
        print("posted digest to Ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
