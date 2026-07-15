"""Hermetic tests for the live kanban sync engine (events, projection, reconcile)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from command_center.kanban_sync import (
    ALLOWED_EVENT_TYPES,
    FORBIDDEN_EVENT_TYPES,
    EventLog,
    GovernanceViolation,
    KanbanEvent,
    emit_event,
    is_human_owned_status,
    project_cards,
    reconcile,
    verify_projection,
)

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def _log(tmp_path):
    return EventLog(tmp_path / "kanban-events.jsonl")


def test_emit_records_card_stage_event(tmp_path):
    log = _log(tmp_path)
    ev = emit_event(log, action="stage_card", board_id="b1", card_id="c1",
                    source_surface="discord", status_before="Backlog",
                    status_after="Ready", now=NOW)
    assert ev.event_type == "kanban.card.staged"
    assert ev.source_surface == "discord" and ev.status_after == "Ready"
    assert log.read()[0].event_id == ev.event_id


def test_wall_actions_cannot_emit_an_event(tmp_path):
    log = _log(tmp_path)
    for wall in ("approve_card", "merge", "deploy", "delete_card", "delete_board"):
        with pytest.raises(GovernanceViolation):
            emit_event(log, action=wall, board_id="b1", card_id="c1",
                       source_surface="discord", now=NOW)
    assert log.read() == []  # nothing written


def test_all_surfaces_use_the_same_event_path(tmp_path):
    log = _log(tmp_path)
    for surface in ("discord", "sms", "internal_ui", "daily_dag"):
        emit_event(log, action="stage_card", board_id="b1", card_id=f"c-{surface}",
                   source_surface=surface, status_after="Ready", now=NOW)
    surfaces = {e.source_surface for e in log.read()}
    assert surfaces == {"discord", "sms", "internal_ui", "daily_dag"}
    assert all(e.event_type == "kanban.card.staged" for e in log.read())


def test_project_folds_events_to_current_state(tmp_path):
    log = _log(tmp_path)
    emit_event(log, action="add_mission_card", board_id="b1", card_id="c1",
               source_surface="discord", status_after="Backlog", now=NOW)
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="internal_ui", status_after="Ready", now=NOW)
    cards = project_cards(log.read())
    assert cards["c1"]["status"] == "Ready"


def test_events_store_refs_not_raw_payloads(tmp_path):
    from pydantic import ValidationError
    log = _log(tmp_path)
    ev = emit_event(log, action="stage_card", board_id="b1", card_id="c1",
                    source_surface="discord", status_after="Ready",
                    evidence_ref="evidence/x.json", payload_ref="ledger:mission/1", now=NOW)
    assert "evidence_ref" in ev.model_dump_json() and "payload_ref" in ev.model_dump_json()
    # the schema is Strict (extra='forbid'): a raw/free-text content field is
    # structurally rejected, so secrets cannot ride along inside an event.
    base = ev.model_dump()
    with pytest.raises(ValidationError):
        KanbanEvent(**{**base, "raw_payload": "sk-secret-content"})


def test_verify_blocks_on_mismatch_and_degrades_without_snapshot(tmp_path):
    log = _log(tmp_path)
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="discord", status_after="Ready", now=NOW)
    assert verify_projection(log.read(), {"c1": {"status": "Ready"}})["status"] == "pass"
    assert verify_projection(log.read(), {"c1": {"status": "Backlog"}})["status"] == "blocked"
    assert verify_projection(log.read(), None)["status"] == "degraded"


def test_reconcile_detects_drift_vs_human_conflict(tmp_path):
    log = _log(tmp_path)
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="discord", status_after="Ready", now=NOW)
    # board lagging (Backlog) -> repairable drift
    drifted = reconcile(log.read(), {"c1": {"status": "Backlog"}})
    assert drifted["drift"] and not drifted["conflicts"]
    # board human-approved -> conflict, never overwritten
    conflicted = reconcile(log.read(), {"c1": {"status": "Approved"}})
    assert conflicted["conflicts"][0]["resolution"] == "review_required"
    assert conflicted["writes_performed"] is False


def test_status_value_wall_blocks_agent_set_approval(tmp_path):
    """The wall is on the status VALUE: a permitted verb can't carry an approval."""
    log = _log(tmp_path)
    for approval in ("Approved", "approved", "Awaiting Approval", "awaiting_approval"):
        with pytest.raises(GovernanceViolation):
            emit_event(log, action="stage_card", board_id="b1", card_id="c1",
                       source_surface="discord", status_after=approval, now=NOW)
    assert log.read() == []


def test_kanban_event_validator_rejects_human_owned_status():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        KanbanEvent(event_id="x", event_type="kanban.card.staged", board_id="b",
                    card_id="c", action="stage_card", source_surface="discord",
                    actor_type="agent", status_after="approved", created_at="t")


def test_reconcile_protects_lowercase_approved(tmp_path):
    """The missions board uses lowercase 'approved' — case-fold must protect it."""
    log = _log(tmp_path)
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="discord", status_after="Ready", now=NOW)
    res = reconcile(log.read(), {"c1": {"status": "approved"}})
    assert not res["drift"]
    assert res["conflicts"][0]["reason"] == "human_approval_field_protected"


def test_reconcile_terminal_reopen_is_conflict_not_drift(tmp_path):
    log = _log(tmp_path)
    emit_event(log, action="reject_card", board_id="b1", card_id="c1",
               source_surface="discord", status_after="Rejected", now=NOW)
    # a human re-opened a rejected card on the board — never silently revert it
    res = reconcile(log.read(), {"c1": {"status": "In Progress"}})
    assert not res["drift"]
    assert res["conflicts"][0]["reason"] == "human_reopened_terminal_card"


def test_reconcile_branches_missing_and_extra_and_degraded(tmp_path):
    log = _log(tmp_path)
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="discord", status_after="Ready", now=NOW)
    # no snapshot -> degraded, never a fake pass
    assert reconcile(log.read(), None)["status"] == "degraded"
    # card in log but not on board -> repairable drift (missing_projection)
    miss = reconcile(log.read(), {})
    assert miss["drift"][0]["kind"] == "missing_projection"
    # card on board but not in log -> conflict (human-created)
    extra = reconcile(log.read(), {"c1": {"status": "Ready"}, "ghost": {"status": "Ready"}})
    assert any(c["reason"] == "card_on_board_not_in_event_log" for c in extra["conflicts"])


def test_allowed_and_forbidden_event_types_are_disjoint():
    assert ALLOWED_EVENT_TYPES.isdisjoint(FORBIDDEN_EVENT_TYPES)
    assert is_human_owned_status("APPROVED ") and not is_human_owned_status("In Progress")


def test_read_after_clamps_negative_and_overlarge_offset(tmp_path):
    log = _log(tmp_path)
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="discord", status_after="Ready", now=NOW)
    new, nxt = log.read_after(offset=-5)
    assert len(new) == 1 and nxt == 1
    none_new, nxt2 = log.read_after(offset=99)
    assert none_new == [] and nxt2 == 1
