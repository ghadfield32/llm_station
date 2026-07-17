"""Deterministic, append-only Kanban maintenance review behavior."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from command_center.kanban_maintenance import (
    MaintenanceError,
    analyze,
    begin_decision,
    fulfill_accept,
    reconcile_suggestions,
    review,
)


class Placement:
    def __init__(self, board_id: str, work_item_id: str, removed_at=None):
        self.board_id = board_id
        self.work_item_id = work_item_id
        self.removed_at = removed_at


def _board(board_id: str, title: str, *, archived: bool = False) -> dict:
    return {
        "board_id": board_id,
        "domain_id": board_id,
        "title": title,
        "card_component": "generic_task",
        "archived": archived,
    }


def test_analysis_is_deterministic_broad_and_never_targets_protected_boards():
    boards = [
        _board("personal_todos", "Personal TODOs"),
        _board("alpha", "Research Queue"),
        _board("beta", "research-queue"),
        _board("subset", "Evidence"),
        _board("empty", "Empty Board"),
        _board("old", "Old", archived=True),
    ]
    placements = [
        Placement("alpha", "W1"), Placement("alpha", "W2"),
        Placement("beta", "W1"), Placement("beta", "W2"),
        Placement("subset", "W1"),
    ]
    first = analyze(boards, placements)
    assert first == analyze(list(reversed(boards)), list(reversed(placements)))
    assert {row["kind"] for row in first} >= {
        "duplicate_title", "identical_membership", "subset_membership", "empty_board"}
    assert all("personal_todos" not in row["board_ids"] for row in first)
    assert all("old" not in row["board_ids"] for row in first)


def test_direct_cards_prevent_false_empty_and_incomplete_membership_advice():
    boards = [_board("legacy", "Legacy"), _board("canonical", "Canonical")]
    placements = [Placement("canonical", "W1")]
    rows = analyze(boards, placements, direct_card_counts={"legacy": 3})
    assert all(row["kind"] != "empty_board" for row in rows)
    assert all("legacy" not in row["board_ids"] for row in rows)


def test_reconcile_reject_and_evidence_change_are_append_only(tmp_path):
    path = tmp_path / "maintenance.jsonl"
    [candidate] = analyze([_board("empty", "Empty")], [])
    first = reconcile_suggestions(path, [candidate])
    second = reconcile_suggestions(path, [candidate])
    assert first["created_count"] == 1
    assert second["created_count"] == 0
    begin_decision(path, candidate["suggestion_id"], "reject", reason_note="intentional")
    assert review(path)["history"][0]["status"] == "rejected"

    changed = analyze(
        [_board("empty", "Empty"), _board("larger", "Larger")],
        [Placement("empty", "W1"), Placement("larger", "W1"), Placement("larger", "W2")],
    )
    reconcile_suggestions(path, changed)
    state = review(path)
    assert any(row["status"] == "rejected" for row in state["history"])
    assert state["open"]


def test_disappeared_evidence_supersedes_open_suggestion(tmp_path):
    path = tmp_path / "maintenance.jsonl"
    [candidate] = analyze([_board("empty", "Empty")], [])
    reconcile_suggestions(path, [candidate])
    receipt = reconcile_suggestions(path, [])
    state = review(path)
    assert receipt["superseded_count"] == 1
    assert state["open"] == []
    assert state["history"][0]["status"] == "superseded"
    with pytest.raises(MaintenanceError, match="cannot accept"):
        begin_decision(path, candidate["suggestion_id"], "accept")

    recurrence = reconcile_suggestions(path, [candidate])
    assert recurrence["reopened_count"] == 1
    assert review(path)["open"][0]["suggestion_id"] == candidate["suggestion_id"]


def test_accept_state_is_resumable_idempotent_and_conflict_checked(tmp_path):
    path = tmp_path / "maintenance.jsonl"
    [candidate] = analyze([_board("empty", "Empty")], [])
    reconcile_suggestions(path, [candidate])
    suggestion_id = candidate["suggestion_id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(
            lambda _: begin_decision(path, suggestion_id, "accept"), range(4)))
    assert all(row["status"] == "accepted_pending" for row in rows)
    assert [event["status"] for event in review(path)["pending"]] == ["accepted_pending"]

    accepted = fulfill_accept(path, suggestion_id, "WI-1")
    assert accepted["status"] == "accepted"
    assert fulfill_accept(path, suggestion_id, "WI-1")["work_item_id"] == "WI-1"
    with pytest.raises(MaintenanceError, match="conflicting"):
        fulfill_accept(path, suggestion_id, "WI-2")
    with pytest.raises(MaintenanceError, match="cannot reject"):
        begin_decision(path, suggestion_id, "reject")
