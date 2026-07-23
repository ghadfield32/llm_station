"""Deterministic, append-only Kanban maintenance suggestions.

The analyzer only recommends. Decisions are durable events; accepting begins a
resumable state machine but never merges, archives, moves, or deletes a board.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from command_center.write_locking import exclusive_write_lock

SCHEMA_VERSION = "command-center.kanban-maintenance.v1"
PROTECTED_BOARDS = frozenset({
    "personal_todos", "betts_basketball_grand_todo", "grand_todo",
})


class MaintenanceError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _suggestion_id(kind: str, board_ids: list[str], evidence: dict[str, Any]) -> str:
    payload = json.dumps({
        "kind": kind, "board_ids": sorted(board_ids), "evidence": evidence,
    }, sort_keys=True, separators=(",", ":"))
    return "KMS-" + hashlib.sha256(payload.encode()).hexdigest()[:20]


def _candidate(kind: str, board_ids: list[str], title: str,
               reason: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "suggestion_id": _suggestion_id(kind, board_ids, evidence),
        "kind": kind,
        "board_ids": sorted(board_ids),
        "title": title,
        "reason": reason,
        "evidence": evidence,
    }


def analyze(
    boards: list[dict[str, Any]], placements: list[Any],
    *, direct_card_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    direct_card_counts = direct_card_counts or {}
    active = [
        board for board in boards
        if not board.get("archived")
        and board.get("board_id")
        and board.get("card_component") == "generic_task"
        and board.get("board_id") not in PROTECTED_BOARDS
        and board.get("domain_id") not in PROTECTED_BOARDS
    ]
    work_by_board: dict[str, set[str]] = {
        str(board["board_id"]): set() for board in active
    }
    for placement in placements:
        board_id = str(getattr(placement, "board_id", ""))
        removed_at = getattr(placement, "removed_at", None)
        if board_id in work_by_board and removed_at is None:
            work_by_board[board_id].add(str(getattr(placement, "work_item_id", "")))

    candidates: list[dict[str, Any]] = []
    title_groups: dict[str, list[dict[str, Any]]] = {}
    for board in active:
        title_groups.setdefault(_normalized_title(str(board.get("title") or "")), []).append(board)
    for normalized, group in title_groups.items():
        if normalized and len(group) > 1:
            ids = [str(board["board_id"]) for board in group]
            candidates.append(_candidate(
                "duplicate_title", ids, "Review boards with the same normalized title",
                "These active generic boards have the same title after punctuation/case normalization.",
                {"normalized_title": normalized},
            ))

    ordered = sorted(active, key=lambda board: str(board["board_id"]))
    for index, left in enumerate(ordered):
        left_id = str(left["board_id"])
        left_work = work_by_board[left_id]
        left_direct = direct_card_counts.get(left_id, 0)
        if not left_work and left_direct == 0:
            candidates.append(_candidate(
                "empty_board", [left_id], f"Review empty board: {left.get('title') or left_id}",
                "This active generic board has no current WorkItem placements.",
                {"work_item_ids": [], "direct_card_count": 0},
            ))
        for right in ordered[index + 1:]:
            right_id = str(right["board_id"])
            right_work = work_by_board[right_id]
            right_direct = direct_card_counts.get(right_id, 0)
            # Direct/imported cards have identities outside the Work Graph. Until
            # those are canonicalized, membership comparison would be incomplete.
            if left_direct or right_direct:
                continue
            if left_work and left_work == right_work:
                candidates.append(_candidate(
                    "identical_membership", [left_id, right_id],
                    "Review boards with identical active work",
                    "Both boards project the exact same non-empty WorkItem set.",
                    {"work_item_ids": sorted(left_work)},
                ))
            elif left_work and right_work and (left_work < right_work or right_work < left_work):
                smaller, larger = (
                    (left_id, right_id) if left_work < right_work else (right_id, left_id)
                )
                candidates.append(_candidate(
                    "subset_membership", [smaller, larger],
                    "Review a board whose work is a strict subset of another",
                    "Every active item on one board is already projected on the other board.",
                    {"subset_board_id": smaller, "superset_board_id": larger,
                     "subset_work_item_ids": sorted(work_by_board[smaller])},
                ))
    return sorted(candidates, key=lambda row: row["suggestion_id"])


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MaintenanceError(f"invalid maintenance event line {line_number}: {exc}") from exc
        if event.get("schema_version") != SCHEMA_VERSION:
            raise MaintenanceError(f"unsupported maintenance event at line {line_number}")
        events.append(event)
    return events


def _append_locked(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def reconcile_suggestions(path: Path, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    lock = path.parent / ".locks" / f"{path.name}.write.lock"
    with exclusive_write_lock(lock):
        events = read_events(path)
        known = {str(event.get("suggestion_id")) for event in events}
        current_ids = {candidate["suggestion_id"] for candidate in candidates}
        state = review(path)
        state_by_id = {
            row["suggestion_id"]: row
            for row in [*state["open"], *state["pending"], *state["history"]]
        }
        superseded = []
        for row in state["open"]:
            suggestion_id = row["suggestion_id"]
            if suggestion_id in current_ids:
                continue
            _append_locked(path, {
                "schema_version": SCHEMA_VERSION, "event": "superseded",
                "at": _now(), "suggestion_id": suggestion_id,
                "reason_note": "current evidence no longer supports this suggestion",
            })
            events.append({"suggestion_id": suggestion_id})
            superseded.append(suggestion_id)
        created = []
        reopened = []
        for candidate in candidates:
            if candidate["suggestion_id"] in known:
                previous = state_by_id.get(candidate["suggestion_id"], {})
                if previous.get("status") == "superseded":
                    _append_locked(path, {
                        "schema_version": SCHEMA_VERSION, "event": "reopened",
                        "at": _now(), "suggestion_id": candidate["suggestion_id"],
                    })
                    reopened.append(candidate["suggestion_id"])
                continue
            event = {
                "schema_version": SCHEMA_VERSION,
                "event": "suggested",
                "at": _now(),
                **candidate,
            }
            _append_locked(path, event)
            events.append(event)
            known.add(candidate["suggestion_id"])
            created.append(candidate["suggestion_id"])
    return {"candidate_count": len(candidates), "created_count": len(created),
            "created_suggestion_ids": created, "superseded_count": len(superseded),
            "superseded_suggestion_ids": superseded, "reopened_count": len(reopened),
            "reopened_suggestion_ids": reopened}


def review(path: Path) -> dict[str, Any]:
    events = read_events(path)
    suggestions: dict[str, dict[str, Any]] = {}
    for event in events:
        suggestion_id = str(event["suggestion_id"])
        row = suggestions.setdefault(suggestion_id, {"suggestion_id": suggestion_id})
        if event["event"] == "suggested":
            row.update({key: event[key] for key in (
                "kind", "board_ids", "title", "reason", "evidence")})
            row.update({"status": "open", "suggested_at": event["at"]})
        elif event["event"] == "accepted_pending":
            row.update({"status": "accepted_pending", "decided_at": event["at"]})
        elif event["event"] == "accepted_fulfilled":
            row.update({"status": "accepted", "decided_at": event["at"],
                        "work_item_id": event["work_item_id"]})
        elif event["event"] == "rejected":
            row.update({"status": "rejected", "decided_at": event["at"],
                        "reason_note": event.get("reason_note")})
        elif event["event"] == "superseded":
            row.update({"status": "superseded", "decided_at": event["at"],
                        "reason_note": event.get("reason_note")})
        elif event["event"] == "reopened":
            row.update({"status": "open", "suggested_at": event["at"]})
            row.pop("decided_at", None)
            row.pop("reason_note", None)
    rows = sorted(suggestions.values(), key=lambda row: (
        row.get("status") != "open", row.get("suggested_at", "")))
    return {
        "open": [row for row in rows if row.get("status") == "open"],
        "pending": [row for row in rows if row.get("status") == "accepted_pending"],
        "history": [row for row in rows if row.get("status") not in {"open", "accepted_pending"}],
        "event_count": len(events),
    }


def begin_decision(path: Path, suggestion_id: str,
                   decision: Literal["accept", "reject"], *,
                   reason_note: str | None = None) -> dict[str, Any]:
    lock = path.parent / ".locks" / f"{path.name}.write.lock"
    with exclusive_write_lock(lock):
        state = review(path)
        rows = [*state["open"], *state["pending"], *state["history"]]
        row = next((item for item in rows if item["suggestion_id"] == suggestion_id), None)
        if row is None:
            raise MaintenanceError(f"unknown suggestion: {suggestion_id}")
        status = row.get("status")
        if decision == "reject":
            if status == "rejected":
                return row
            if status != "open":
                raise MaintenanceError(f"cannot reject suggestion in {status} state")
            event = {"schema_version": SCHEMA_VERSION, "event": "rejected",
                     "at": _now(), "suggestion_id": suggestion_id,
                     "reason_note": reason_note}
            _append_locked(path, event)
            return {**row, "status": "rejected", "reason_note": reason_note}
        if status == "accepted":
            return row
        if status == "rejected":
            raise MaintenanceError("a rejected suggestion cannot be accepted unless evidence changes")
        if status not in {"open", "accepted_pending"}:
            raise MaintenanceError(f"cannot accept suggestion in {status} state")
        if status == "open":
            _append_locked(path, {
                "schema_version": SCHEMA_VERSION, "event": "accepted_pending",
                "at": _now(), "suggestion_id": suggestion_id,
            })
        return {**row, "status": "accepted_pending"}


def fulfill_accept(path: Path, suggestion_id: str, work_item_id: str) -> dict[str, Any]:
    lock = path.parent / ".locks" / f"{path.name}.write.lock"
    with exclusive_write_lock(lock):
        state = review(path)
        row = next((item for item in [*state["pending"], *state["history"]]
                    if item["suggestion_id"] == suggestion_id), None)
        if row is None or row.get("status") not in {"accepted_pending", "accepted"}:
            raise MaintenanceError("acceptance was not begun")
        if row.get("status") == "accepted":
            if row.get("work_item_id") != work_item_id:
                raise MaintenanceError("accepted suggestion has a conflicting WorkItem")
            return row
        _append_locked(path, {
            "schema_version": SCHEMA_VERSION, "event": "accepted_fulfilled",
            "at": _now(), "suggestion_id": suggestion_id,
            "work_item_id": work_item_id,
        })
        return {**row, "status": "accepted", "work_item_id": work_item_id}
