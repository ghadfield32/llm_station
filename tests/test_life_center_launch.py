"""build_launch_view() is pure: catalog + three board card lists in, one typed
LaunchView out. No board_store, no subprocess — that's live_launch_view()'s job."""
from __future__ import annotations

from command_center.mcp.life_center_launch import STALE_AFTER_SECONDS, build_launch_view

_NOW = "2026-07-18T12:00:00+00:00"

_CATALOG_SERVICES = [
    {
        "service_id": "nextcloud", "application": "Nextcloud", "category": "core",
        "lifecycle": "keep", "risk_tier": "moderate",
        "display": {"short_description": "Sync files.", "sort_order": 10,
                     "show_in_launch": True, "primary_action_label": "Open Nextcloud"},
        "setup": {"wizard_required": False, "default_credentials_must_rotate": False},
        "links": {"app": "http://127.0.0.1:8085", "docs": "https://docs.nextcloud.com/"},
    },
    {
        "service_id": "immich", "application": "Immich", "category": "core",
        "lifecycle": "keep", "risk_tier": "moderate",
        "display": {"short_description": "Photos.", "sort_order": 11, "show_in_launch": True},
        "setup": {"wizard_required": True, "default_credentials_must_rotate": False},
        "links": {"app": "http://127.0.0.1:2283"},
        # compose service name differs from service_id — see life-center-infra/
        # catalog.py's comment on this exact entry, found live.
        "automation": {"health_probe_id": "immich-server"},
    },
    {
        "service_id": "command-center-work-graph", "application": "Kanban", "category": "tasks",
        "lifecycle": "keep", "risk_tier": "low",
        "display": {"short_description": "hidden", "sort_order": 999, "show_in_launch": False},
        "setup": {}, "links": {},
    },
]


def test_hidden_catalog_entries_never_become_tiles():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES, catalog_digest="sha256:x",
        services_cards=[], overview_cards=[], operations_cards=[],
        generated_at=_NOW, status_generated_at=_NOW,
    )
    ids = {s.service_id for s in view.services}
    assert "command-center-work-graph" not in ids
    assert view.summary.total == 2


def test_missing_overview_card_is_unknown_never_healthy():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES, catalog_digest="sha256:x",
        services_cards=[], overview_cards=[], operations_cards=[],
        generated_at=_NOW, status_generated_at=None,
    )
    by_id = {s.service_id: s for s in view.services}
    assert by_id["nextcloud"].health.status == "unknown"
    assert by_id["nextcloud"].health.stale is True
    assert view.summary.unknown == 2
    assert view.summary.healthy == 0


def test_fresh_ready_overview_card_reports_healthy_and_not_stale():
    # "ready" is the LANE list_cards() actually returns (the event-log fold's
    # status, per CommandCenterBoardProvider.upsert_card popping any "status"
    # field) — not the raw pass/warn/fail verdict, which never persists as a
    # field. Confirmed against a live card before writing this fixture.
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES, catalog_digest="sha256:x",
        services_cards=[], operations_cards=[],
        overview_cards=[{"service": "nextcloud", "status": "ready", "last_check": _NOW}],
        generated_at=_NOW, status_generated_at=_NOW,
    )
    nc = next(s for s in view.services if s.service_id == "nextcloud")
    assert nc.health.status == "healthy"
    assert nc.health.stale is False
    assert view.summary.healthy == 1


def test_old_overview_card_reports_stale_and_unknown_even_if_it_said_ready():
    old = "2026-07-18T10:00:00+00:00"  # 2h before _NOW, > STALE_AFTER_SECONDS (1h)
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[:1], catalog_digest="sha256:x",
        services_cards=[], operations_cards=[],
        overview_cards=[{"service": "nextcloud", "status": "ready", "last_check": old}],
        generated_at=_NOW, status_generated_at=old,
    )
    nc = view.services[0]
    assert nc.health.stale is True
    assert nc.health.status == "unknown"  # a stale "ready" must NOT surface as healthy


def test_blocked_and_rejected_map_to_attention_and_down():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[:2], catalog_digest="sha256:x",
        services_cards=[], operations_cards=[],
        overview_cards=[
            {"service": "nextcloud", "status": "blocked", "last_check": _NOW},
            {"service": "immich-server", "status": "rejected", "last_check": _NOW},
        ],
        generated_at=_NOW, status_generated_at=_NOW,
    )
    by_id = {s.service_id: s for s in view.services}
    assert by_id["nextcloud"].health.status == "attention"
    assert by_id["immich"].health.status == "down"
    assert view.summary.attention == 2  # both attention and down count against the "attention" bucket


def test_health_lookup_uses_health_probe_id_when_compose_name_differs():
    # immich's catalog service_id is "immich" but its running container is
    # "immich-server" — the overview card is keyed by the compose name.
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[:2], catalog_digest="sha256:x",
        services_cards=[], operations_cards=[],
        overview_cards=[{"service": "immich-server", "status": "ready", "last_check": _NOW}],
        generated_at=_NOW, status_generated_at=_NOW,
    )
    immich = next(s for s in view.services if s.service_id == "immich")
    assert immich.health.status == "healthy"


def test_admission_lane_and_owner_come_from_the_services_board_untouched():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[:1], catalog_digest="sha256:x",
        services_cards=[{"service_id": "nextcloud", "status": "In Progress", "owner": "geoff"}],
        overview_cards=[], operations_cards=[],
        generated_at=_NOW, status_generated_at=None,
    )
    nc = view.services[0]
    assert nc.admission.lane == "In Progress"
    assert nc.admission.owner == "geoff"


def test_setup_required_and_open_card_reports_pending_not_completed():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[1:2], catalog_digest="sha256:x",  # immich: wizard_required
        services_cards=[], overview_cards=[],
        operations_cards=[{"service_id": "immich", "operation_type": "setup",
                            "status": "Backlog", "card_id": "immich:setup:initial",
                            "evidence_refs": "owner account required"}],
        generated_at=_NOW, status_generated_at=None,
    )
    im = view.services[0]
    assert im.setup.required is True
    assert im.setup.completed is False
    assert im.setup.operations_card_id == "immich:setup:initial"
    assert view.summary.setup_pending == 1


def test_setup_card_moved_to_done_reports_completed():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[1:2], catalog_digest="sha256:x",
        services_cards=[], overview_cards=[],
        operations_cards=[{"service_id": "immich", "operation_type": "setup",
                            "status": "Done", "card_id": "immich:setup:initial"}],
        generated_at=_NOW, status_generated_at=None,
    )
    im = view.services[0]
    assert im.setup.completed is True
    assert view.summary.setup_pending == 0


def test_links_only_include_kinds_actually_present():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[:1], catalog_digest="sha256:x",
        services_cards=[], overview_cards=[], operations_cards=[],
        generated_at=_NOW, status_generated_at=None,
    )
    kinds = {link.kind for link in view.services[0].links}
    assert kinds == {"app", "docs"}  # only what _CATALOG_SERVICES[0] actually set


def test_services_are_sorted_by_sort_order_then_application():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[:2], catalog_digest="sha256:x",
        services_cards=[], overview_cards=[], operations_cards=[],
        generated_at=_NOW, status_generated_at=None,
    )
    assert [s.service_id for s in view.services] == ["nextcloud", "immich"]  # sort_order 10 < 11


def test_global_and_service_action_ids_are_always_the_read_only_four():
    view = build_launch_view(
        catalog_services=_CATALOG_SERVICES[:1], catalog_digest="sha256:x",
        services_cards=[], overview_cards=[], operations_cards=[],
        generated_at=_NOW, status_generated_at=None,
    )
    assert set(view.global_action_ids) == {
        "life_center.refresh_status", "life_center.refresh_catalog_projection"}
    assert set(view.services[0].service_action_ids) == {
        "life_center.verify_service", "life_center.verify_links"}


def test_stale_after_seconds_is_one_hour():
    assert STALE_AFTER_SECONDS == 3600
