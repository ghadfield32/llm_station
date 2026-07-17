"""life-center-status — read-only MCP gateway for the Life Center.

This is the ``life-center-status`` surface described in
``docs/operations/HARDWARE_AND_LIFE_CENTER_PLAN.md`` (Dashboard and Kanban
decision). It is **read-only by contract**: it exposes exactly the eight
allowlisted summary functions below, each taking **no free-form arguments**, and
returns only typed, redacted health facts — never file contents, secrets,
note/document titles, financial detail, or a filesystem browser. There is
deliberately **no** ``life-center-actions`` surface here (mutations are admitted
one at a time later, under the security baseline).

STUB STATUS: the real Life Center host does not exist yet (Gate 5). Every
function returns typed **fixture** data so the shape, the redaction contract, and
the board projection can be exercised now. Wire these to the real host's probes
when the appliance is built.

Design mirrors ``growth_os/agent/growthos_mcp.py``: a thin FastMCP registration
layer over pre-verified functions. FastMCP is imported lazily inside
``build_server`` so the allowlist and shapes stay importable/testable without the
``mcp`` dependency installed.

Run (once ``mcp`` is available in the runtime env):

    python -m command_center.mcp.life_center_status            # stdio
    python -m command_center.mcp.life_center_status --http     # 127.0.0.1:8799
"""
from __future__ import annotations

import sys
from typing import Callable, TypedDict

SERVER_NAME = "life-center-status"
HTTP_HOST = "127.0.0.1"        # loopback only; share via `tailscale serve`, never Funnel
HTTP_PORT = 8799


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
    """One-glance Life Center health summary (redacted)."""
    return Overview(
        generated_at="1970-01-01T00:00:00Z",
        services_total=0,
        services_healthy=0,
        services_attention=0,
        oldest_backup_age_hours=0.0,
        pool_used_pct=0.0,
        open_security_findings=0,
    )


def get_service_health() -> list[ServiceHealth]:
    """Per-service status + native deep links (no contents)."""
    return []


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


def get_pending_maintenance() -> list[MaintenanceItem]:
    """Human-authored / proposed maintenance items with risk tier."""
    return []


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
