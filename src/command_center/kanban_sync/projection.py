"""Projections of the kanban event log: fold, verify, reconcile, write-through.

The event log is the source of truth. `project_cards` folds events into current
card state. `verify_projection` compares a surface snapshot to that fold.
`reconcile` detects drift vs conflict and applies the conflict policy (Ledger
wins agent-owned fields; human approval fields are never overwritten; divergent
status becomes review_required — never silent last-write-wins). The first-party
board store and governed event log remain authoritative.
"""
from __future__ import annotations

from typing import Any

from command_center.kanban_sync.events import KanbanEvent, is_human_owned_status, normalize_status

_EVENT_TO_STATUS_KEY = {
    "kanban.card.created": "Backlog", "kanban.card.staged": "Ready",
    "kanban.card.started": "In Progress", "kanban.card.blocked": "Blocked",
    "kanban.card.rejected": "Rejected", "kanban.card.done": "Done",
}
# Terminal statuses — once a card is here, the board moving it elsewhere is a
# human decision (re-opening), not projection lag: a conflict, not drift.
_TERMINAL_STATUSES = frozenset({"rejected", "done"})


def project_cards(events: list[KanbanEvent]) -> dict[str, dict[str, Any]]:
    """Fold the event log into current card state (last writer per card wins, in order)."""
    cards: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.event_type not in _EVENT_TO_STATUS_KEY and e.event_type != "kanban.card.progress_comment_added":
            continue
        card = cards.setdefault(e.card_id, {
            "card_id": e.card_id, "board_id": e.board_id, "repo_id": e.repo_id,
            "status": None, "last_event_id": None, "last_actor": None,
        })
        if e.event_type in _EVENT_TO_STATUS_KEY:
            card["status"] = e.status_after or _EVENT_TO_STATUS_KEY[e.event_type]
        card["last_event_id"] = e.event_id
        card["last_actor"] = e.actor_type
    return cards


def verify_projection(
    events: list[KanbanEvent], snapshot: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Compare a surface snapshot to the event-log fold. DEGRADED if no snapshot."""
    if snapshot is None:
        return {"status": "degraded", "reason": "projection_snapshot_unavailable",
                "mismatches": []}
    expected = project_cards(events)
    mismatches = []
    for card_id, exp in expected.items():
        snap = snapshot.get(card_id)
        if snap is None:
            mismatches.append({"card_id": card_id, "expected": exp["status"],
                               "actual": None, "kind": "missing_in_projection"})
        elif snap.get("status") != exp["status"]:
            mismatches.append({"card_id": card_id, "expected": exp["status"],
                               "actual": snap.get("status"), "kind": "status_mismatch"})
    return {"status": "pass" if not mismatches else "blocked", "mismatches": mismatches,
            "n_cards": len(expected)}


def reconcile(
    events: list[KanbanEvent], snapshot: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Detect drift (repairable) vs conflict (review_required). Never approve/merge/delete."""
    if snapshot is None:
        return {"status": "degraded", "drift": [], "conflicts": [],
                "reason": "projection_snapshot_unavailable"}
    expected = project_cards(events)
    drift: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for card_id, exp in expected.items():
        snap = snapshot.get(card_id)
        if snap is None:
            drift.append({"card_id": card_id, "repair_to": exp["status"],
                          "kind": "missing_projection"})
        elif snap.get("status") != exp["status"]:
            board_status = snap.get("status")
            if is_human_owned_status(board_status):
                # a human moved the card into an approval state — never overwrite it
                conflicts.append({"card_id": card_id, "ledger": exp["status"],
                                  "board": board_status,
                                  "resolution": "review_required",
                                  "reason": "human_approval_field_protected"})
            elif normalize_status(exp["status"]) in _TERMINAL_STATUSES:
                # the log says terminal (Rejected/Done) but the board moved it
                # elsewhere — a human re-opened it; never silently revert.
                conflicts.append({"card_id": card_id, "ledger": exp["status"],
                                  "board": board_status,
                                  "resolution": "review_required",
                                  "reason": "human_reopened_terminal_card"})
            else:
                drift.append({"card_id": card_id, "repair_to": exp["status"],
                              "board": board_status, "kind": "projection_drift"})
    for card_id in snapshot:
        if card_id not in expected:
            conflicts.append({"card_id": card_id, "ledger": None,
                              "board": snapshot[card_id].get("status"),
                              "resolution": "review_required",
                              "reason": "card_on_board_not_in_event_log"})
    status = "pass" if not drift and not conflicts else "drift_or_conflict"
    return {"status": status, "drift": drift, "conflicts": conflicts,
            "writes_performed": False}
