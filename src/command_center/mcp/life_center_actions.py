"""life-center-actions — the default-deny action broker for the Life Center.

Separate MCP surface from ``life_center_status.py`` on purpose: status is a
pure read gateway, this is where any FUTURE mutation would be admitted one
action at a time under signed approval — see
``docs/operations/HARDWARE_AND_LIFE_CENTER_PLAN.md``.

Only the plan's "Read-only, no approval" tier is implemented here:
``refresh_status``, ``verify_service``, ``verify_links``,
``refresh_catalog_projection``. Every one is a pure read/refresh — nothing
here creates, deletes, approves, or mutates board, container, network, or
credential state. The "bounded verification" / "human approved" / "signed
approval" tiers from the plan are deliberately NOT implemented: building an
execution path for those without a real approval/idempotency/rollback
mechanism behind it would be building the on-ramp to autonomous mutation
before anything governs it. Extending ``_REGISTRY`` with a genuinely mutating
action is a separate, individually-reviewed change — never an incremental
addition to this file.

NEVER add these here: arbitrary shell/SQL/Docker/path/URL/env/container
arguments, Restic forget/prune, volume/original-file deletion, public
exposure, DNS mutation, vault-content access, credential rotation/disclosure,
real Actual Budget reads/writes, unrestricted Home Assistant control, Dockge
use.

Run (once ``mcp`` is available in the runtime env):

    python -m command_center.mcp.life_center_actions            # stdio
    python -m command_center.mcp.life_center_actions --http     # 127.0.0.1:8800
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SERVER_NAME = "life-center-actions"
HTTP_HOST = "127.0.0.1"        # loopback only; share via `tailscale serve`, never Funnel
HTTP_PORT = 8800

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LC_PY = _REPO_ROOT / "life-center-infra" / "lc.py"


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    request_id: str
    idempotency_key: str
    service_id: str | None = None
    parameters: dict = field(default_factory=dict)
    # Accepted but unused by every action registered today — no handler here
    # needs approval, since none of them mutate anything. Kept in the schema
    # so it doesn't have to change shape when a higher tier is ever added.
    approval_id: str | None = None
    catalog_digest: str | None = None


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    request_id: str
    status: str  # ok | error | rejected
    result: dict
    error: str | None = None


def _run_lc(*args: str) -> dict:
    """Subprocess boundary into life-center-infra/lc.py — never a Python
    import (life-center-infra is a self-contained seed meant to be extracted
    into its own private repo; see its README)."""
    if not _LC_PY.exists():
        raise FileNotFoundError(f"lc.py not found at {_LC_PY}")
    proc = subprocess.run(
        [sys.executable, str(_LC_PY), *args],
        capture_output=True, encoding="utf-8", errors="replace", check=True,
    )
    return json.loads(proc.stdout)


def _refresh_status(_req: ActionRequest) -> dict:
    """Re-run the status collector, then return the fresh overview."""
    from command_center.mcp.life_center_status import get_overview
    from command_center.mcp.life_center_status_collector import main as collect

    rc = collect(["--profile", "everything"])
    if rc != 0:
        raise RuntimeError("status collector run failed; see its stderr")
    return {"overview": get_overview()}


def _verify_service(req: ActionRequest) -> dict:
    if not req.service_id:
        raise ValueError("verify_service requires service_id")
    report = _run_lc("verify", "--profile", "everything", "--json")
    checks = [c for c in report["checks"] if c.get("service_id") == req.service_id]
    if not checks:
        raise ValueError(f"no checks found for service_id {req.service_id!r} "
                          f"(not currently admitted, or not a real service_id)")
    return {"service_id": req.service_id, "checks": checks}


def _verify_links(req: ActionRequest) -> dict:
    profile = req.parameters.get("profile", "everything")
    return _run_lc("link-check", "--profile", str(profile), "--json")


def _refresh_catalog_projection(_req: ActionRequest) -> dict:
    """Re-run the Kanban catalog-sync entrypoint (services/operations boards)."""
    proc = subprocess.run(
        [sys.executable, "-m", "command_center.cli.life_center_sync"],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    return {"exit_code": proc.returncode, "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-2000:]}


# The complete, fixed registry. No other action_id is dispatchable. Every
# handler here is a pure read/refresh — see the module docstring's boundary.
_REGISTRY: dict[str, Callable[[ActionRequest], dict]] = {
    "life_center.refresh_status": _refresh_status,
    "life_center.verify_service": _verify_service,
    "life_center.verify_links": _verify_links,
    "life_center.refresh_catalog_projection": _refresh_catalog_projection,
}
ADMITTED_ACTION_IDS: tuple[str, ...] = tuple(sorted(_REGISTRY))


def dispatch(
    action_id: str,
    *,
    service_id: str | None = None,
    idempotency_key: str | None = None,
    parameters: dict | None = None,
    approval_id: str | None = None,
    catalog_digest: str | None = None,
) -> ActionResult:
    """The single legal entry point — no caller-supplied shell/path/command."""
    request_id = str(uuid.uuid4())
    if action_id not in _REGISTRY:
        return ActionResult(action_id=action_id, request_id=request_id, status="rejected",
                             result={}, error=f"unregistered action_id: {action_id!r}")
    req = ActionRequest(
        action_id=action_id, request_id=request_id,
        idempotency_key=idempotency_key or request_id,
        service_id=service_id, parameters=parameters or {},
        approval_id=approval_id, catalog_digest=catalog_digest,
    )
    try:
        result = _REGISTRY[action_id](req)
        return ActionResult(action_id=action_id, request_id=request_id, status="ok", result=result)
    except Exception as exc:  # noqa: BLE001 - report the failure, don't crash the broker
        return ActionResult(action_id=action_id, request_id=request_id, status="error",
                             result={}, error=str(exc))


def _dispatch_action(action_id: str, service_id: str = "", idempotency_key: str = "",
                      parameters_json: str = "{}") -> dict:
    """The one MCP tool this server exposes — a thin, validated wrapper around
    `dispatch()`. Free-form `parameters_json` is parsed but only ever consulted
    by handlers above that explicitly document what they read from it (today:
    only `verify_links`'s `profile` key) — nothing here forwards it to a shell,
    path, or command."""
    try:
        parameters = json.loads(parameters_json) if parameters_json else {}
    except json.JSONDecodeError as exc:
        return {"status": "rejected", "error": f"parameters_json is not valid JSON: {exc}"}
    result = dispatch(
        action_id, service_id=service_id or None,
        idempotency_key=idempotency_key or None, parameters=parameters,
    )
    return {"action_id": result.action_id, "request_id": result.request_id,
            "status": result.status, "result": result.result, "error": result.error}


def build_server():
    """Construct the FastMCP server, registering exactly one dispatch tool.

    Imports FastMCP lazily so this module (and ADMITTED_ACTION_IDS) stays
    importable/testable without the ``mcp`` package installed.
    """
    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415 (lazy by design)

    server = FastMCP(SERVER_NAME)
    server.tool()(_dispatch_action)
    return server


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    server = build_server()
    if "--http" in argv:
        server.settings.host = HTTP_HOST
        server.settings.port = HTTP_PORT
        server.run(transport="streamable-http")
    else:
        server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
