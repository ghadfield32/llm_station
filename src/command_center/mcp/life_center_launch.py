"""Life Center Launch — the typed, joined view backing the cockpit's Launch tab.

Joins four existing authorities WITHOUT copying their data permanently
anywhere new — this module only READS all four; nothing here writes to any
board (that stays in ``command_center.improvement.discovery.life_center``'s
sync jobs):

  - life-center-infra/catalog.py   stable facts (via ``lc catalog``, subprocess)
  - life_center_services board     human admission lane + owner
  - life_center_overview board     machine health projection
  - life_center_operations board   setup/incident work

``build_launch_view`` is pure — it takes already-fetched dicts, so it is
testable offline with fakes, no board_store, no subprocess. ``live_launch_view``
binds the real fetches. Missing/stale health is reported as ``unknown``,
never silently presented as healthy.
"""
from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

SCHEMA_VERSION = "life-center.launch.v1"
STALE_AFTER_SECONDS = 3600  # health older than this reports as stale/unknown, never "healthy"

# The action broker's actions split into "applies to one service" (shown on
# each tile) vs. "applies to the whole page" (shown once) — life_center_actions
# itself is a flat, service-agnostic registry; this is a presentation-only split.
_SERVICE_ACTIONS = ("life_center.verify_service", "life_center.verify_links")
_GLOBAL_ACTIONS = ("life_center.refresh_status", "life_center.refresh_catalog_projection")

# CommandCenterBoardProvider.upsert_card always pops "status" from `fields`
# ("status truth is the fold, not the store" — its own module docstring), so
# the raw pass/warn/fail verdict Opus's sync also tried to stash as a field
# never actually persists. What list_cards() returns as "status" is the LANE
# the event-log fold placed the card in — ready/blocked/rejected — not the
# verdict. Map from what's ACTUALLY there, confirmed by reading a live card.
_OVERVIEW_STATUS_TO_HEALTH = {"ready": "healthy", "blocked": "attention", "rejected": "down"}


@dataclass(frozen=True)
class LaunchLink:
    kind: str            # app | setup | docs | runbook | status | native
    label: str
    href: str | None


@dataclass(frozen=True)
class LaunchAdmission:
    lane: str
    owner: str


@dataclass(frozen=True)
class LaunchHealth:
    status: str           # healthy | attention | down | unknown
    last_check: str | None
    stale: bool


@dataclass(frozen=True)
class LaunchSetup:
    required: bool
    completed: bool
    operations_card_id: str | None
    evidence_refs: str


@dataclass(frozen=True)
class LaunchService:
    service_id: str
    application: str
    category: str
    short_description: str
    lifecycle: str
    risk_tier: str
    sort_order: int
    primary_action_label: str
    admission: LaunchAdmission
    health: LaunchHealth
    setup: LaunchSetup
    links: tuple[LaunchLink, ...]
    service_action_ids: tuple[str, ...]


@dataclass(frozen=True)
class LaunchSummary:
    total: int
    healthy: int
    attention: int
    setup_pending: int
    unknown: int


@dataclass(frozen=True)
class LaunchView:
    schema_version: str
    generated_at: str
    catalog_digest: str
    status_generated_at: str | None
    status_stale: bool
    summary: LaunchSummary
    global_action_ids: tuple[str, ...]
    services: tuple[LaunchService, ...]


def _parse_iso(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def build_launch_view(
    *,
    catalog_services: Sequence[Mapping],
    catalog_digest: str,
    services_cards: Sequence[Mapping],
    overview_cards: Sequence[Mapping],
    operations_cards: Sequence[Mapping],
    generated_at: str,
    status_generated_at: str | None,
) -> LaunchView:
    services_by_id = {str(c["service_id"]): c for c in services_cards if c.get("service_id")}
    overview_by_id = {str(c["service"]): c for c in overview_cards if c.get("service")}
    operations_by_service: dict[str, list[Mapping]] = {}
    for c in operations_cards:
        sid = c.get("service_id")
        if sid:
            operations_by_service.setdefault(str(sid), []).append(c)

    now = _parse_iso(generated_at) or datetime.datetime.now(datetime.timezone.utc)

    out_services: list[LaunchService] = []
    healthy = attention = unknown = setup_pending = 0
    for svc in catalog_services:
        display = svc.get("display") or {}
        if not display.get("show_in_launch", True):
            continue
        sid = str(svc["service_id"])

        admission_card = services_by_id.get(sid, {})
        admission = LaunchAdmission(
            lane=str(admission_card.get("status") or "Backlog"),
            owner=str(admission_card.get("owner") or ""),
        )

        # `lc verify`'s container/HTTP checks key by the actual Docker Compose
        # service name, which sometimes differs from this catalog's more
        # readable service_id (e.g. "immich" -> "immich-server") — catalog
        # entries that differ set automation.health_probe_id to the real name.
        probe_id = ((svc.get("automation") or {}).get("health_probe_id")) or sid
        overview_card = overview_by_id.get(probe_id)
        last_check = overview_card.get("last_check") if overview_card else None
        checked_at = _parse_iso(last_check)
        stale = checked_at is None or (now - checked_at).total_seconds() > STALE_AFTER_SECONDS
        health_status = "unknown" if (not overview_card or stale) else \
            _OVERVIEW_STATUS_TO_HEALTH.get(str(overview_card.get("status")), "unknown")
        health = LaunchHealth(status=health_status, last_check=last_check, stale=stale)

        setup_info = svc.get("setup") or {}
        op_cards = operations_by_service.get(sid, [])
        setup_card = next((c for c in op_cards if c.get("operation_type") == "setup"), None)
        # `registration_must_close` is its own trigger, not folded into wizard_
        # required — a service whose account is already created (wizard done)
        # but whose public registration is still open is genuinely still
        # pending. Found live: Immich's wizard_required flipped to False after
        # its admin account was created via API, which silently dropped its
        # still-open "close registration" step from setup_pending until this
        # was corrected to check all three flags.
        setup_required = bool(setup_info.get("wizard_required")
                               or setup_info.get("default_credentials_must_rotate")
                               or setup_info.get("registration_must_close"))
        setup_lane = str(setup_card.get("status", "")).strip().lower() if setup_card else ""
        setup_completed = setup_required and setup_lane == "done"
        setup = LaunchSetup(
            required=setup_required, completed=setup_completed,
            operations_card_id=str(setup_card["card_id"]) if setup_card else None,
            evidence_refs=str(setup_card.get("evidence_refs", "")) if setup_card else "",
        )

        links_dict = svc.get("links") or {}
        links = tuple(
            LaunchLink(kind=k, label=k.capitalize(), href=links_dict.get(k))
            for k in ("app", "setup", "docs", "runbook", "status", "native")
            if links_dict.get(k)
        )

        out_services.append(LaunchService(
            service_id=sid, application=str(svc.get("application", sid)),
            category=str(svc.get("category", "")),
            short_description=str(display.get("short_description", "")),
            lifecycle=str(svc.get("lifecycle", "")),
            risk_tier=str(svc.get("risk_tier", "low")),
            sort_order=int(display.get("sort_order", 999)),
            primary_action_label=str(display.get("primary_action_label", "Open")),
            admission=admission, health=health, setup=setup, links=links,
            service_action_ids=_SERVICE_ACTIONS,
        ))

        if health_status == "healthy":
            healthy += 1
        elif health_status == "unknown":
            unknown += 1
        else:
            attention += 1
        if setup_required and not setup_completed:
            setup_pending += 1

    out_services.sort(key=lambda s: (s.sort_order, s.application))

    return LaunchView(
        schema_version=SCHEMA_VERSION, generated_at=generated_at, catalog_digest=catalog_digest,
        status_generated_at=status_generated_at, status_stale=status_generated_at is None,
        summary=LaunchSummary(total=len(out_services), healthy=healthy, attention=attention,
                               setup_pending=setup_pending, unknown=unknown),
        global_action_ids=_GLOBAL_ACTIONS,
        services=tuple(out_services),
    )


def live_launch_view() -> LaunchView:
    """Bind `build_launch_view` to the real catalog + boards."""
    import os
    from pathlib import Path

    from command_center.boards.command_center_provider import CommandCenterBoardProvider
    from command_center.improvement.discovery.life_center import (
        BOARD_OPERATIONS, BOARD_OVERVIEW, BOARD_SERVICES, run_lc,
    )
    from command_center.kanban_sync.events import EventLog

    def _provider(board_id: str) -> CommandCenterBoardProvider:
        event_path = os.environ.get("KANBAN_EVENT_LOG", "generated/kanban-events.jsonl")
        store_path = os.environ.get("KANBAN_BOARD_STORE", "generated/boards")
        return CommandCenterBoardProvider(
            board_id=board_id, event_log=EventLog(event_path), store_dir=Path(store_path))

    catalog = run_lc("catalog")
    # `lc catalog`'s links are raw templates (e.g. "${NEXTCLOUD_PORT:-8085}")
    # — only `lc links --json` applies .env-based ${VAR:-default} resolution.
    # Found live: without this, every "Open app" href in this API was the
    # literal unresolved template string, not a working URL.
    resolved_links = {s["service_id"]: s["links"] for s in run_lc("links", "--json")["services"]}
    catalog_services = [
        {**svc, "links": resolved_links.get(svc["service_id"], svc.get("links", {}))}
        for svc in catalog["services"]
    ]
    services_cards = _provider(BOARD_SERVICES).list_cards()
    overview_cards = _provider(BOARD_OVERVIEW).list_cards()
    operations_cards = _provider(BOARD_OPERATIONS).list_cards()

    checks = [c.get("last_check") for c in overview_cards if c.get("last_check")]
    status_generated_at = max(checks) if checks else None

    return build_launch_view(
        catalog_services=catalog_services, catalog_digest=catalog["catalog_digest"],
        services_cards=services_cards, overview_cards=overview_cards,
        operations_cards=operations_cards,
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status_generated_at=status_generated_at,
    )


def to_dict(view: LaunchView) -> dict:
    return asdict(view)
