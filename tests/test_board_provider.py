"""Hermetic tests for the provider-agnostic board layer (boards/)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from command_center.boards import (
    APPFLOWY_CAPABILITIES,
    COMMAND_CENTER_CAPABILITIES,
    UnsupportedOperation,
    provider_for_board,
)
from command_center.boards.appflowy_provider import AppFlowyBoardProvider
from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.kanban_sync import EventLog, GovernanceViolation, emit_event
from command_center.schemas.contracts import KanbanBoardSpec

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)

_STATUS_MAPPING = {
    "backlog": "Backlog", "ready": "Ready", "in_progress": "In Progress",
    "done": "Done", "blocked": "Blocked", "rejected": "Rejected",
    "awaiting_approval": "Awaiting Approval",
}


def _spec(provider: str, board_id: str = "b1") -> KanbanBoardSpec:
    return KanbanBoardSpec(
        board_id=board_id, provider=provider,
        workspace_ref="env:APPFLOWY_WORKSPACE_ID" if provider == "appflowy" else "self",
        board_ref=board_id, repo_ids=["llm_station"],
        status_mapping=dict(_STATUS_MAPPING),
        required_fields=["MissionID"],
        allowed_agent_verbs=["add_mission_card", "stage_card"],
        forbidden_agent_verbs=["approve_card", "merge", "deploy",
                               "delete_card", "delete_board"])


def _internal(tmp_path, board_id="b1") -> CommandCenterBoardProvider:
    return CommandCenterBoardProvider(
        board_id=board_id, event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards", status_mapping=dict(_STATUS_MAPPING))


# ---- factory ----------------------------------------------------------------

def test_factory_picks_provider_from_registry_spec(tmp_path):
    internal = provider_for_board(_spec("command_center_ui"),
                                  event_log=EventLog(tmp_path / "e.jsonl"),
                                  store_dir=tmp_path / "boards")
    appflowy = provider_for_board(_spec("appflowy"), env={})
    assert isinstance(internal, CommandCenterBoardProvider)
    assert isinstance(appflowy, AppFlowyBoardProvider)
    assert internal.capabilities() is COMMAND_CENTER_CAPABILITIES
    assert appflowy.capabilities() is APPFLOWY_CAPABILITIES


# ---- capability truth ---------------------------------------------------------

def test_capability_flags_are_honest():
    # AppFlowy REST gaps (verified 2026-07-08) and the universal delete wall.
    assert not APPFLOWY_CAPABILITIES.supports_delete_row
    assert not APPFLOWY_CAPABILITIES.supports_group_by_api
    assert not APPFLOWY_CAPABILITIES.supports_select_option_create
    assert APPFLOWY_CAPABILITIES.supports_mobile_native
    assert not COMMAND_CENTER_CAPABILITIES.supports_delete_row  # wall, not gap
    assert COMMAND_CENTER_CAPABILITIES.supports_custom_card_rendering
    assert COMMAND_CENTER_CAPABILITIES.supports_live_sync


# ---- appflowy fails loud ------------------------------------------------------

def test_appflowy_unsupported_ops_raise_with_remedy():
    p = AppFlowyBoardProvider(board_id="b1", env={})
    for call in (lambda: p.delete_row("c1"),
                 lambda: p.set_group_by("Status"),
                 lambda: p.create_select_option("Status", "New")):
        with pytest.raises(UnsupportedOperation) as err:
            call()
        assert err.value.remedy  # every gap names its manual fallback


def test_appflowy_unconfigured_is_degraded_not_crash():
    p = AppFlowyBoardProvider(board_id="b1", env={})
    out = p.upsert_card("c1", {"company": "X"})
    assert out == {"status": "degraded", "card_id": "c1",
                   "reason": "appflowy_projection_not_configured", "wrote": False}
    assert p.snapshot() is None      # no reader -> honest DEGRADED
    assert p.list_cards() == []
    assert p.validate()["configured"] is False


def test_appflowy_upsert_refuses_human_owned_status():
    p = AppFlowyBoardProvider(board_id="b1", env={})
    out = p.upsert_card("c1", {}, status="Awaiting Approval")
    assert out["status"] == "refused" and out["wrote"] is False


# ---- internal provider ---------------------------------------------------------

def test_internal_status_truth_is_the_event_fold(tmp_path):
    p = _internal(tmp_path)
    p.upsert_card("c1", {"company": "Acme", "fit_score": 91}, status="Backlog")
    emit_event(p.log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="internal_ui", status_after="Ready", now=NOW)
    cards = p.list_cards()
    assert len(cards) == 1
    card = cards[0]
    assert card["status"] == "Ready"          # fold wins
    assert card["company"] == "Acme" and card["fit_score"] == 91
    assert p.snapshot() == {"c1": p.snapshot()["c1"]}  # snapshot is the fold


def test_internal_store_never_overrides_status(tmp_path):
    p = _internal(tmp_path)
    p.upsert_card("c1", {"status": "Done", "company": "Acme"}, status="Backlog")
    card = p.list_cards()[0]
    assert card["status"] == "Backlog"        # sneaky field-status dropped


def test_internal_upsert_with_human_owned_status_refused(tmp_path):
    p = _internal(tmp_path)
    out = p.upsert_card("c1", {}, status="awaiting_approval")
    assert out["status"] == "refused"
    assert p.list_cards() == []               # nothing stored, nothing emitted


def test_internal_wall_verbs_still_governed(tmp_path):
    p = _internal(tmp_path)
    with pytest.raises(GovernanceViolation):
        emit_event(p.log, action="approve_card", board_id="b1", card_id="c1",
                   source_surface="internal_ui", now=NOW)
    with pytest.raises(UnsupportedOperation):
        p.delete_row("c1")


def test_internal_card_ids_cannot_traverse_paths(tmp_path):
    p = _internal(tmp_path)
    p.upsert_card("../../evil", {"company": "X"})
    store = (tmp_path / "boards" / "b1").resolve()
    stored = list(store.glob("*.json"))
    assert len(stored) == 1
    # separators are stripped, so the file cannot escape the board's store dir
    assert "/" not in stored[0].name and "\\" not in stored[0].name
    assert stored[0].resolve().parent == store


def test_internal_fieldless_card_surfaces_with_none_status(tmp_path):
    p = _internal(tmp_path)
    p.upsert_card("c-orphan", {"company": "NoEventsYet"})
    cards = p.list_cards()
    assert cards[0]["card_id"] == "c-orphan" and cards[0]["status"] is None
