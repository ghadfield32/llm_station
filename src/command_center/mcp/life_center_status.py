"""life-center-status — read-only MCP gateway for the Life Center.

This is the ``life-center-status`` surface described in
``docs/operations/HARDWARE_AND_LIFE_CENTER_PLAN.md`` (Dashboard and Kanban
decision). It is **read-only by contract**: it exposes exactly the eight
allowlisted summary functions below, each taking **no free-form arguments**, and
returns only typed, redacted health facts — never file contents, secrets,
note/document titles, financial detail, or a filesystem browser. There is
deliberately **no** ``life-center-actions`` surface here (mutations are admitted
one at a time later, under the security baseline).

PARTIALLY WIRED (this trial): the appliance itself does not exist yet (Gate 5),
but the desktop proof-of-concept trial does — ``get_overview``/``get_service_health``
now read a real, periodically-refreshed snapshot written by
``life_center_status_collector.py`` (itself a thin subprocess wrapper around
``life-center-infra/lc.py verify --json``), and ``get_pending_maintenance``
reads the real ``life_center_operations`` board. ``get_backup_status``,
``get_storage_capacity``, ``get_model_inventory``, ``get_archive_freshness``,
and ``get_security_findings`` remain typed **fixture** stubs (empty lists) —
there is genuinely no automated backup-age/storage/model-inventory/security
probe yet (``lc verify`` itself reports those as ``unknown``, not measured;
returning fabricated numbers here would be worse than returning nothing). Wire
each one for real only once its underlying probe exists.

Design mirrors ``growth_os/agent/growthos_mcp.py``: a thin FastMCP registration
layer over pre-verified functions. FastMCP is imported lazily inside
``build_server`` so the allowlist and shapes stay importable/testable without the
``mcp`` dependency installed.

Run (once ``mcp`` is available in the runtime env):

    python -m command_center.mcp.life_center_status            # stdio
    python -m command_center.mcp.life_center_status --http     # 127.0.0.1:8799
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable, TypedDict

SERVER_NAME = "life-center-status"
HTTP_HOST = "127.0.0.1"        # loopback only; share via `tailscale serve`, never Funnel
HTTP_PORT = 8799

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SNAPSHOT_PATH = "generated/life-center-status-snapshot.json"


def _snapshot_path() -> Path:
    raw = os.environ.get("LIFE_CENTER_STATUS_SNAPSHOT", _DEFAULT_SNAPSHOT_PATH)
    p = Path(raw)
    return p if p.is_absolute() else _REPO_ROOT / p


def _load_snapshot() -> dict | None:
    """None if the collector has never run (or its output is unreadable) — the
    caller must treat that as "unknown/stale", never as "everything healthy"."""
    path = _snapshot_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── typed return shapes (redacted health facts only) ─────────────────────────
class Overview(TypedDict):
    generated_at: str
    services_total: int
    services_healthy: int
    services_attention: int
    oldest_backup_age_hours: float
    pool_used_pct: float
    open_security_findings: int


class ServiceHealth(TypedDict):
    service: str
    status: str            # healthy | attention | down | maintenance
    last_check: str
    deep_link: str         # native client URL (tailnet); never contents


class BackupStatus(TypedDict):
    scope: str
    last_success: str
    age_hours: float
    restore_tested: str    # ISO date of last proven restore, or "never"
    offsite: bool


class StorageCapacity(TypedDict):
    dataset: str
    used_tib: float
    budget_tib: float
    used_pct: float


class ModelInventory(TypedDict):
    name: str
    kind: str              # active | archived
    license: str
    provenance: str
    sha256: str


class ArchiveFreshness(TypedDict):
    archive: str
    last_pull: str
    versions_retained: int
    last_integrity_check: str


class SecurityFinding(TypedDict):
    id: str
    severity: str          # low | medium | high | critical
    kind: str              # patch | vuln | certificate | backup | restore-test
    summary: str           # redacted; never raw sensitive logs


class MaintenanceItem(TypedDict):
    id: str
    title: str
    risk_tier: str         # L0..L4 (see policy/risk-tiers.md)
    proposed: bool


# ── the eight allowlisted read-only tools (no free-form args) ────────────────
def get_overview() -> Overview:
    """One-glance Life Center health summary (redacted).

    Reads the collector's snapshot when one exists; a missing/unreadable
    snapshot means "never collected", reported as zeroed with generated_at
    pinned to the epoch — never presented as a real, current all-healthy read.
    """
    snap = _load_snapshot()
    if not snap:
        return Overview(
            generated_at="1970-01-01T00:00:00Z",
            services_total=0, services_healthy=0, services_attention=0,
            oldest_backup_age_hours=0.0, pool_used_pct=0.0, open_security_findings=0,
        )
    ov = snap["overview"]
    return Overview(
        generated_at=ov["generated_at"],
        services_total=ov["services_total"],
        services_healthy=ov["services_healthy"],
        services_attention=ov["services_attention"],
        oldest_backup_age_hours=ov["oldest_backup_age_hours"],
        pool_used_pct=ov["pool_used_pct"],
        open_security_findings=ov["open_security_findings"],
    )


def get_service_health() -> list[ServiceHealth]:
    """Per-service status + native deep links (no contents).

    deep_link stays empty for now: the collector's snapshot carries status
    only, not resolved URLs — wiring that is a small follow-up, not something
    to fabricate here.
    """
    snap = _load_snapshot()
    if not snap:
        return []
    return [
        ServiceHealth(service=s["service"], status=s["status"],
                      last_check=s["last_check"], deep_link="")
        for s in snap.get("services", [])
    ]


def get_backup_status() -> list[BackupStatus]:
    """Per-scope backup age, restore-test date, and off-site presence."""
    return []


def get_storage_capacity() -> list[StorageCapacity]:
    """Per-dataset usage against its planning budget."""
    return []


def get_model_inventory() -> list[ModelInventory]:
    """Active/archived model catalog: license, provenance, hashes."""
    return []


def get_archive_freshness() -> list[ArchiveFreshness]:
    """Site/CV/model archive pull recency + integrity-check recency."""
    return []


def get_security_findings() -> list[SecurityFinding]:
    """Open patch/vuln/cert/backup/restore-test findings (redacted)."""
    return []


# life-center-infra/catalog.py risk_tier (low/moderate/sensitive/privileged) ->
# this codebase's L0-L4 risk codes (see kanban.py's _VALID_RISK). A judgment
# call, not a fact: "sensitive"/"privileged" data doesn't automatically mean
# an L3/L4-risk ACTION, but absent a per-action risk assessment, defaulting to
# the data's own sensitivity is the conservative (never under-stated) choice.
_CATALOG_RISK_TO_L_CODE = {"low": "L1", "moderate": "L2", "sensitive": "L3", "privileged": "L4"}


def get_pending_maintenance() -> list[MaintenanceItem]:
    """Human-authored / proposed maintenance items with risk tier.

    Reads real cards from the life_center_operations board (read-only —
    list_cards() has no side effect on the event log). Every card is honestly
    marked proposed=True: this MCP surface has no action broker behind it, so
    nothing here has ever actually been executed.
    """
    from command_center.boards.command_center_provider import CommandCenterBoardProvider
    from command_center.kanban_sync.events import EventLog

    event_path = os.environ.get("KANBAN_EVENT_LOG", "generated/kanban-events.jsonl")
    store_path = os.environ.get("KANBAN_BOARD_STORE", "generated/boards")
    provider = CommandCenterBoardProvider(
        board_id="life_center_operations",
        event_log=EventLog(event_path),
        store_dir=Path(store_path),
    )
    items = []
    for card in provider.list_cards():
        risk = _CATALOG_RISK_TO_L_CODE.get(str(card.get("risk_tier", "")).lower(), "L1")
        items.append(MaintenanceItem(
            id=str(card.get("card_id", "")),
            title=f"{card.get('service_id', '?')}: {card.get('operation_type', 'operation')}",
            risk_tier=risk, proposed=True,
        ))
    return items


# The complete, fixed allowlist. No other function is exposed. Nothing here
# accepts a caller-supplied shell command, SQL, path, URL, container name, or env.
READONLY_TOOLS: list[Callable[[], object]] = [
    get_overview,
    get_service_health,
    get_backup_status,
    get_storage_capacity,
    get_model_inventory,
    get_archive_freshness,
    get_security_findings,
    get_pending_maintenance,
]


def build_server():
    """Construct the FastMCP server, registering only READONLY_TOOLS.

    Imports FastMCP lazily so this module (and its allowlist/shapes) stays
    importable without the ``mcp`` package installed.
    """
    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415 (lazy by design)

    server = FastMCP(SERVER_NAME)
    for fn in READONLY_TOOLS:
        server.tool()(fn)
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
