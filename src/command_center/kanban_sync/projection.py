"""Projections of the kanban event log: fold, verify, reconcile, write-through.

The event log is the source of truth. `project_cards` folds events into current
card state. `verify_projection` compares a surface snapshot to that fold.
`reconcile` detects drift vs conflict and applies the conflict policy (Ledger
wins agent-owned fields; human approval fields are never overwritten; divergent
status becomes review_required — never silent last-write-wins). `AppFlowyProjection`
write-through fails closed when the sandbox/board env is absent.
"""
from __future__ import annotations

import time
from typing import Any, Callable

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


class AppFlowyProjection:
    """Write-through AppFlowy projection. Fails closed when the board env is absent.

    Mirrors the kanban-bridge direct_api path (gotrue token + row update). It is a
    projection writer only: it sets card status/fields from an event; it never
    approves, merges, or deletes.
    """

    def __init__(self, *, env: dict[str, str],
                 base_url_env: str = "APPFLOWY_BASE_URL",
                 workspace_id_env: str = "APPFLOWY_WORKSPACE_ID",
                 database_id_env: str = "APPFLOWY_DATABASE_ID",
                 user_env: str = "APPFLOWY_EMAIL", password_env: str = "APPFLOWY_PASSWORD",
                 client_factory: Callable[..., Any] | None = None):
        self.env = env
        self.refs = {"base": base_url_env, "workspace": workspace_id_env,
                     "database": database_id_env, "user": user_env, "password": password_env}
        self._client_factory = client_factory

    def configured(self) -> bool:
        return all(self.env.get(name) for name in self.refs.values())

    def write_through(self, event: KanbanEvent, *,
                      status_label: str | None = None) -> dict[str, Any]:
        """Set the card's status on the board. `status_label` overrides the event's
        status (used by reconcile to repair to the folded target, not the last
        event). A human-owned approval status is never written — fail closed."""
        label = status_label or event.status_after or _EVENT_TO_STATUS_KEY.get(event.event_type)
        if is_human_owned_status(label):
            return {"status": "refused", "card_id": event.card_id,
                    "reason": "refuse_to_write_human_owned_status", "wrote": False}
        if not self.configured():
            return {"status": "degraded", "card_id": event.card_id,
                    "reason": "appflowy_projection_not_configured", "wrote": False}
        if self._client_factory is None:
            import httpx
            self._client_factory = httpx.Client
        base = self.env[self.refs["base"]].rstrip("/")
        ws = self.env[self.refs["workspace"]]
        db = self.env[self.refs["database"]]
        status_label = label
        start = time.perf_counter_ns()
        with self._client_factory(timeout=30) as client:
            auth = client.post(f"{base}/gotrue/token?grant_type=password",
                               json={"email": self.env[self.refs["user"]],
                                     "password": self.env[self.refs["password"]]})
            auth.raise_for_status()
            token = auth.json()["access_token"]
            resp = client.put(
                f"{base}/api/workspace/{ws}/database/{db}/row",
                headers={"Authorization": f"Bearer {token}"},
                json={"pre_hash": event.card_id, "cells": {"Status": status_label},
                      "document": None})
            resp.raise_for_status()
        ms = (time.perf_counter_ns() - start) / 1_000_000
        return {"status": "written", "card_id": event.card_id,
                "status_label": status_label, "write_ms": ms, "wrote": True}
