"""
Per-card mission dependencies (blocked_by / unblocks): the typed edge model, the pure
blocked-computation, the board-registry opt-in contract, and the deterministic board-state
surfacing. Dependencies carry no approval authority — a resolved blocker only makes a card
eligible to start.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from command_center.channels.board_state import _dep_marker
from command_center.kanban_sync import (
    CardDependencies, is_card_blocked, parse_card_dependencies, unmet_blockers,
)
from command_center.schemas.contracts import KanbanBoardSpec


# --------------------------------------------------------------------- edge model

def test_dependencies_dedup_and_reject_overlap():
    with pytest.raises(ValidationError):
        CardDependencies(blocked_by=["M1", "M1"])          # duplicate
    with pytest.raises(ValidationError):
        CardDependencies(blocked_by=["M1"], unblocks=["M1"])  # a card can't block+unblock same id
    with pytest.raises(ValidationError):
        CardDependencies(blocked_by=[" "])                 # empty id


def test_parse_from_row_accepts_list_or_string():
    assert parse_card_dependencies({"blocked_by": ["M1", "M2"]}).blocked_by == ["M1", "M2"]
    assert parse_card_dependencies({"blocked_by": "M1, M2"}).blocked_by == ["M1", "M2"]
    assert parse_card_dependencies({"title": "x"}).blocked_by == []


# --------------------------------------------------------------------- blocked math

def test_unmet_blockers_and_is_card_blocked():
    assert unmet_blockers(["M1", "M2"], ["M1"]) == ["M2"]
    assert unmet_blockers(["M1"], ["M1"]) == []
    assert is_card_blocked({"blocked_by": "M1,M2"}, ["M1"]) is True
    assert is_card_blocked({"blocked_by": ["M1", "M2"]}, ["M1", "M2"]) is False
    assert is_card_blocked({"title": "independent"}, []) is False   # no deps => never blocked


# --------------------------------------------------------------------- board registry opt-in

def _board(**kw):
    base = dict(
        board_id="b", provider="command_center_ui", workspace_ref="self", board_ref="b",
        repo_ids=["r"],
        status_mapping={"backlog": "B", "ready": "R", "in_progress": "I", "done": "D",
                        "blocked": "K", "rejected": "J", "awaiting_approval": "A"},
        required_fields=["MissionID"],
        allowed_agent_verbs=["add_mission_card"],
        forbidden_agent_verbs=["approve_card", "merge", "deploy", "delete_card", "delete_board"],
    )
    base.update(kw)
    return KanbanBoardSpec(**base)


def test_board_accepts_recognised_dependency_fields():
    b = _board(dependency_fields=["blocked_by", "unblocks"])
    assert set(b.dependency_fields) == {"blocked_by", "unblocks"}
    assert _board().dependency_fields == []                 # default: no dependency chains


def test_board_rejects_unknown_or_required_dependency_fields():
    with pytest.raises(ValidationError):
        _board(dependency_fields=["depends_on"])            # not a recognised field
    with pytest.raises(ValidationError):
        _board(dependency_fields=["blocked_by", "blocked_by"])  # duplicate
    with pytest.raises(ValidationError):
        # a dependency field must stay optional, never required
        _board(required_fields=["MissionID", "blocked_by"], dependency_fields=["blocked_by"])


# --------------------------------------------------------------------- deterministic surfacing

def test_dep_marker_is_additive():
    assert _dep_marker({"title": "x"}) == ""                # no field => unchanged rendering
    assert _dep_marker({"blocked_by": "M1,M2"}) == " ⛔blocked_by:M1,M2"
    assert _dep_marker({"blocked_by": ["M1", "M2"]}) == " ⛔blocked_by:M1,M2"
