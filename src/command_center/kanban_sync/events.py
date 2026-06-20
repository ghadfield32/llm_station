"""Kanban event schema + governed append-only event log.

`emit_event` is the single legal writer: it maps a granted agent action to an
allowed event type and appends a `KanbanEvent`. Wall actions (approve_card,
merge, deploy, delete_card, delete_board) raise `GovernanceViolation` — they can
never produce a legal event, so no projection of them is possible.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import model_validator

from command_center.schemas import Strict

# Allowed event types — the only events a projection may act on.
ALLOWED_EVENT_TYPES = frozenset({
    "kanban.card.created", "kanban.card.staged", "kanban.card.started",
    "kanban.card.blocked", "kanban.card.rejected", "kanban.card.done",
    "kanban.card.progress_comment_added",
    "kanban.projection.verified", "kanban.projection.drift_detected",
    "kanban.conflict.review_required",
})
# Event types that must never be emitted by a kanban agent action.
FORBIDDEN_EVENT_TYPES = frozenset({
    "kanban.card.approved_by_agent", "kanban.card.deleted_by_agent",
    "kanban.board.deleted_by_agent", "merge", "deploy", "publish",
})
# Granted agent action -> the card event it emits (the only legal write path).
_ACTION_TO_EVENT = {
    "add_mission_card": "kanban.card.created",
    "stage_card": "kanban.card.staged",
    "start_todo": "kanban.card.started",
    "block_card": "kanban.card.blocked",
    "reject_card": "kanban.card.rejected",
    "finish_todo": "kanban.card.done",
    "progress_comment": "kanban.card.progress_comment_added",
}
# Wall actions — never mappable to a legal event.
_WALL_ACTIONS = frozenset({
    "approve_card", "merge", "deploy", "publish", "delete_card", "delete_board",
})
_CARD_STATUS_EVENTS = {
    "kanban.card.created", "kanban.card.staged", "kanban.card.started",
    "kanban.card.blocked", "kanban.card.rejected", "kanban.card.done",
}
# Statuses only a human sets — an agent must never *set* one (the wall is on the
# status VALUE, not just the action name). Normalised so capitalization and
# space/underscore variants across boards (mission_intake "Approved" vs the
# missions board's "approved"/"awaiting_approval") are all caught.
_HUMAN_OWNED_STATUSES = frozenset({"Approved", "Awaiting Approval", "awaiting_approval"})

# The whitelist and forbidden sets must be disjoint, otherwise the validator's
# allow-check could pass a forbidden type. Pinned at import time.
assert ALLOWED_EVENT_TYPES.isdisjoint(FORBIDDEN_EVENT_TYPES), \
    "ALLOWED_EVENT_TYPES and FORBIDDEN_EVENT_TYPES must be disjoint"


def normalize_status(status: str | None) -> str:
    return (status or "").strip().casefold().replace(" ", "_")


_HUMAN_OWNED_NORM = frozenset(normalize_status(s) for s in _HUMAN_OWNED_STATUSES)


def is_human_owned_status(status: str | None) -> bool:
    """True for any approval status a human owns — agents may never set it."""
    return normalize_status(status) in _HUMAN_OWNED_NORM


class GovernanceViolation(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KanbanEvent(Strict):
    event_id: str
    event_type: str
    board_id: str
    repo_id: str | None = None
    mission_id: str | None = None
    card_id: str
    action: str
    source_surface: Literal["discord", "slack", "telegram", "whatsapp", "sms",
                            "internal_ui", "daily_dag", "repo_agent", "reconciler"]
    actor_type: Literal["agent", "human", "system"]
    status_before: str | None = None
    status_after: str | None = None
    payload_ref: str | None = None
    evidence_ref: str | None = None
    created_at: str
    redaction_status: Literal["redacted", "not_required"] = "not_required"
    projection_status: Literal["pending", "verified", "drift", "degraded", "blocked"] = "pending"
    conflict_status: Literal["none", "review_required"] = "none"

    @model_validator(mode="after")
    def _checks(self):
        if self.event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"event_type {self.event_type!r} is not an allowed kanban event")
        if not self.card_id:
            raise ValueError("kanban event needs a card_id")
        if not self.created_at:
            raise ValueError("kanban event needs created_at")
        if self.event_type in _CARD_STATUS_EVENTS and not self.status_after:
            raise ValueError(f"{self.event_type} requires status_after")
        # the wall is on the status VALUE, not just the action name: no kanban
        # event may carry a human-owned approval status (approval stays human-only).
        if is_human_owned_status(self.status_after):
            raise ValueError(
                f"status_after {self.status_after!r} is a human-owned approval "
                "status; an agent event can never set it")
        return self


class EventLog:
    """Append-only JSONL kanban event log (per-deployment runtime state)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read(self) -> list[KanbanEvent]:
        if not self.path.is_file():
            return []
        out: list[KanbanEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(KanbanEvent.model_validate_json(line))
        return out

    def append(self, event: KanbanEvent) -> KanbanEvent:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")
        return event

    def read_after(self, *, offset: int) -> tuple[list[dict[str, Any]], int]:
        """Return events with index >= offset (for the UI SSE tail) + the new offset.

        The offset is clamped to [0, len] so a stale/negative cursor cannot rewind
        or over-read — the invariant lives with the method, not its callers.
        """
        events = self.read()
        offset = min(max(0, offset), len(events))
        new = [e.model_dump(mode="json") for e in events[offset:]]
        return new, len(events)


def _event_id(board_id: str, card_id: str, event_type: str, created_at: str) -> str:
    digest = hashlib.sha256(
        f"{board_id}|{card_id}|{event_type}|{created_at}".encode("utf-8")
    ).hexdigest()[:12]
    return f"kev-{digest}"


def emit_event(
    log: EventLog,
    *,
    action: str,
    board_id: str,
    card_id: str,
    source_surface: str,
    actor_type: str = "agent",
    repo_id: str | None = None,
    mission_id: str | None = None,
    status_before: str | None = None,
    status_after: str | None = None,
    evidence_ref: str | None = None,
    payload_ref: str | None = None,
    now: datetime | None = None,
) -> KanbanEvent:
    """The single legal kanban writer. Rejects wall actions structurally."""
    if action in _WALL_ACTIONS:
        raise GovernanceViolation(
            f"action {action!r} is a wall action — it cannot emit a kanban event; "
            "approval/merge/deploy/delete stay human-only"
        )
    event_type = _ACTION_TO_EVENT.get(action)
    if event_type is None:
        raise GovernanceViolation(f"action {action!r} has no legal kanban event mapping")
    if is_human_owned_status(status_after):
        raise GovernanceViolation(
            f"status_after {status_after!r} is a human-owned approval status; "
            "an agent action can never set it — approval stays human-only")
    created_at = (now or _utc_now()).isoformat()
    event = KanbanEvent(
        event_id=_event_id(board_id, card_id, event_type, created_at),
        event_type=event_type, board_id=board_id, repo_id=repo_id,
        mission_id=mission_id, card_id=card_id, action=action,
        source_surface=source_surface,  # type: ignore[arg-type]
        actor_type=actor_type,  # type: ignore[arg-type]
        status_before=status_before, status_after=status_after,
        evidence_ref=evidence_ref, payload_ref=payload_ref, created_at=created_at,
    )
    return log.append(event)
