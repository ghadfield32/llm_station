"""
life-center-infra catalog/verify → Command Center Kanban, at the pure-function
seam. Each sync takes an injected `upsert_card` recorder (no real board_store,
no subprocess), so these assert the exact write contract:

  - services:   one permanent card per catalog service; existing cards refresh
                ONLY the join keys (lane + owner/notes are human-owned).
  - operations: one setup card per service needing first-run setup; card_id is
                the idempotency key, so reruns refresh, never duplicate.
  - overview:   machine-owned health projection whose cards move lanes every run
                (status=lane on every upsert, regardless of prior existence).
"""
from __future__ import annotations

from command_center.improvement.discovery import (
    seed_operations_from_setup, sync_overview_from_verification,
    sync_services_from_catalog,
)
from command_center.improvement.discovery.life_center import (
    _OVERALL_TO_LANE, _setup_evidence,
)

DIGEST = "sha256:deadbeef"


class _Recorder:
    """Fake upsert_card matching CommandCenterBoardProvider.upsert_card's shape:
    upsert_card(card_id, fields, *, status=None)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert(self, card_id, fields, *, status=None):
        self.calls.append({"card_id": card_id, "fields": dict(fields), "status": status})
        return {"status": "written", "card_id": card_id, "wrote": True}

    def by_id(self, card_id):
        return [c for c in self.calls if c["card_id"] == card_id]


def _svc(service_id, *, setup=None, risk_tier="low"):
    return {"service_id": service_id, "risk_tier": risk_tier, "setup": setup or {}}


# ── services ───────────────────────────────────────────────────────────────────

def test_new_service_seeds_backlog_with_human_owned_fields_blank():
    rec = _Recorder()
    services = [_svc("immich"), _svc("nextcloud")]
    out = sync_services_from_catalog(
        services, upsert_card=rec.upsert, existing_ids=set(), catalog_digest=DIGEST)

    assert [o["action"] for o in out] == ["created", "created"]
    call = rec.by_id("immich")[0]
    assert call["status"] == "Backlog"                      # created in Backlog lane
    assert call["fields"]["service_id"] == "immich"
    assert call["fields"]["catalog_digest"] == DIGEST
    assert call["fields"]["admission_status"] == "Backlog"
    # human-owned fields seeded blank so a human fills them, never the sync
    assert call["fields"]["owner"] == ""
    assert call["fields"]["human_notes"] == ""
    assert call["fields"]["decision_explanation"] == ""


def test_existing_service_refreshes_only_join_keys_never_lane_or_human_fields():
    rec = _Recorder()
    services = [_svc("immich")]
    out = sync_services_from_catalog(
        services, upsert_card=rec.upsert, existing_ids={"immich"}, catalog_digest=DIGEST)

    assert out == [{"card_id": "immich", "service_id": "immich", "action": "updated"}]
    call = rec.by_id("immich")[0]
    assert call["status"] is None                           # never moves the lane
    # ONLY the two join keys — admission_status/owner/notes/decision are untouched
    assert set(call["fields"]) == {"service_id", "catalog_digest"}
    assert call["fields"]["catalog_digest"] == DIGEST


def test_service_card_id_is_service_id_so_reruns_are_idempotent():
    rec = _Recorder()
    services = [_svc("paperless-ngx")]
    sync_services_from_catalog(services, upsert_card=rec.upsert,
                               existing_ids=set(), catalog_digest=DIGEST)
    sync_services_from_catalog(services, upsert_card=rec.upsert,
                               existing_ids={"paperless-ngx"}, catalog_digest=DIGEST)
    # same card_id both runs — no second card is minted
    assert {c["card_id"] for c in rec.calls} == {"paperless-ngx"}


# ── operations ─────────────────────────────────────────────────────────────────

def test_operations_seeded_only_for_services_needing_setup():
    rec = _Recorder()
    services = [
        _svc("immich", setup={"wizard_required": True}),
        _svc("calibre-web", setup={"default_credentials_must_rotate": True}),
        _svc("restic", setup={}),                # neither flag → no operations card
        _svc("tailscale", setup={"note": "host-level"}),  # note only → skipped
    ]
    out = seed_operations_from_setup(
        services, upsert_card=rec.upsert, existing_ids=set())

    assert [o["service_id"] for o in out] == ["immich", "calibre-web"]
    assert {c["card_id"] for c in rec.calls} == {
        "immich:setup:initial", "calibre-web:setup:initial"}


def test_new_operation_card_full_field_set_in_backlog():
    rec = _Recorder()
    services = [_svc("immich", risk_tier="moderate",
                     setup={"wizard_required": True, "registration_must_close": True,
                            "note": "claim admin then close registration"})]
    seed_operations_from_setup(services, upsert_card=rec.upsert, existing_ids=set())

    call = rec.by_id("immich:setup:initial")[0]
    assert call["status"] == "Backlog"
    f = call["fields"]
    assert f["service_id"] == "immich"
    assert f["operation_type"] == "setup"
    assert f["risk_tier"] == "moderate"
    assert f["idempotency_key"] == "immich:setup:initial"   # card_id IS the key
    assert f["finding_key"] is None
    assert f["requested_action_id"] is None
    assert f["approval_id"] is None
    assert "first-run wizard" in f["evidence_refs"]
    assert "close open registration" in f["evidence_refs"]


def test_existing_operation_card_refreshes_only_evidence_and_risk_not_lane():
    rec = _Recorder()
    services = [_svc("immich", risk_tier="moderate", setup={"wizard_required": True})]
    out = seed_operations_from_setup(
        services, upsert_card=rec.upsert, existing_ids={"immich:setup:initial"})

    assert out[0]["action"] == "updated"
    call = rec.by_id("immich:setup:initial")[0]
    assert call["status"] is None                           # human may have moved it
    assert set(call["fields"]) == {"evidence_refs", "risk_tier"}


def test_setup_evidence_is_human_readable_and_never_empty():
    assert _setup_evidence({"wizard_required": True}) == \
        "first-run wizard / owner account required"
    assert "rotate default credentials" in \
        _setup_evidence({"default_credentials_must_rotate": True})
    assert _setup_evidence({}) == "initial setup required"  # never a bare empty string


# ── overview ───────────────────────────────────────────────────────────────────

def _check(service_id, status, check_id=None):
    return {"check_id": check_id or f"c:{service_id}", "service_id": service_id,
            "status": status, "evidence": "x"}


def test_overview_skips_profile_wide_none_service_disclaimers():
    rec = _Recorder()
    checks = [
        _check("immich", "pass"),
        {"check_id": "not_automated:backup_age", "service_id": None,
         "status": "unknown", "evidence": "not automated"},
    ]
    out = sync_overview_from_verification(
        checks, "2026-07-17T00:00:00+00:00", upsert_card=rec.upsert)

    assert [o["service"] for o in out] == ["immich"]        # None-service skipped
    assert {c["card_id"] for c in rec.calls} == {"overview:immich"}


def test_overview_verdict_rollup_and_lane_mapping():
    rec = _Recorder()
    checks = [
        _check("healthy-svc", "pass", "a"), _check("healthy-svc", "pass", "b"),
        _check("warn-svc", "pass", "a"), _check("warn-svc", "warn", "b"),
        _check("unknown-svc", "pass", "a"), _check("unknown-svc", "unknown", "b"),
        _check("fail-svc", "pass", "a"), _check("fail-svc", "fail", "b"),
        _check("fail-svc", "warn", "c"),  # a single fail dominates warn
    ]
    out = sync_overview_from_verification(
        checks, "2026-07-17T00:00:00+00:00", upsert_card=rec.upsert)
    verdicts = {o["service"]: (o["status"], o["lane"]) for o in out}

    assert verdicts["healthy-svc"] == ("pass", "ready")
    assert verdicts["warn-svc"] == ("warn", "blocked")
    assert verdicts["unknown-svc"] == ("warn", "blocked")   # non-pass → warn
    assert verdicts["fail-svc"] == ("fail", "rejected")     # any fail → fail
    # the lane map is exactly the health→lane contract
    assert _OVERALL_TO_LANE == {"pass": "ready", "warn": "blocked", "fail": "rejected"}


def test_overview_always_passes_status_lane_so_cards_move_every_run():
    rec = _Recorder()
    ts = "2026-07-17T00:00:00+00:00"
    # run 1: immich healthy
    sync_overview_from_verification([_check("immich", "pass")], ts, upsert_card=rec.upsert)
    # run 2: immich now failing — same card_id, new lane
    sync_overview_from_verification([_check("immich", "fail")], ts, upsert_card=rec.upsert)

    calls = rec.by_id("overview:immich")
    assert len(calls) == 2
    assert calls[0]["status"] == "ready"                    # Healthy
    assert calls[1]["status"] == "rejected"                 # moved to Retired
    # every run carries status (the lane) — this is what drives the fold's move
    assert all(c["status"] is not None for c in calls)
    # the surfaced fields carry service + verdict + timestamp
    assert calls[1]["fields"] == {"service": "immich", "status": "fail", "last_check": ts}
