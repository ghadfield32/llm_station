"""CaptureService — the intake API's brain. Generates ids + timestamps, preserves
the raw thought immutably, splits bulk lists into individual captures (retaining
the batch), and folds everything into the Universal Inbox.

It NEVER starts work: a capture is saved/organized, not executed. Classification,
routing, packet building, and the daily DAG are later phases that append to this
same stable record. Clock + id factory are injected so it stays hermetic.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from .schemas import (
    INBOX_STATUSES,
    CaptureEvent,
    CaptureRecord,
    CaptureView,
    split_bulk_list,
)
from .store import InMemoryCaptureStore

# requested_mode -> the status a fresh capture lands in. Only "captured" today;
# routing/preparation (later phases) advance it. Saving is never starting work.
_START_STATUS = "captured"

_PREPARE_ACTIONS = (
    {
        "id": "continue_in_chat",
        "label": "Continue in chat",
        "description": "Clarify and organize the capture before choosing a destination.",
    },
    {
        "id": "route_to_todos",
        "label": "Add to General Todos",
        "description": "Route the capture to the General Todos board.",
    },
    {
        "id": "choose_existing_board",
        "label": "Choose an existing kanban",
        "description": "Review the available boards and choose the best existing home.",
    },
    {
        "id": "create_new_board",
        "label": "Create a new kanban",
        "description": "Define a new board only when the capture represents a distinct realm.",
    },
)


class CaptureService:
    def __init__(self, store: InMemoryCaptureStore, *,
                 clock: Callable[[], str], id_factory: Callable[[], str]) -> None:
        self._store = store
        self._clock = clock
        self._id = id_factory

    def capture(self, raw_content: str, **fields) -> CaptureView:
        """Create ONE immutable capture. Raises ValueError on empty content."""
        content = (raw_content or "").strip()
        if not content:
            raise ValueError("capture raw_content must not be empty")
        now = self._clock()
        record = CaptureRecord(
            capture_id=self._id(), raw_content=content, captured_at=now, **fields)
        self._store.add(record, status=_START_STATUS, at=now)
        return self._store.view(record.capture_id)

    def capture_batch(self, text: str, **fields) -> list[CaptureView]:
        """Split a pasted idea list into individual captures, sharing one batch_id
        and retaining item order — nothing is lost. A single-item paste is one
        capture. batch_id must NOT be supplied by the caller (this owns it)."""
        fields.pop("batch_id", None)
        items = split_bulk_list(text or "")
        if not items:
            return []
        batch_id = self._id()
        return [self.capture(item, batch_id=batch_id, **fields) for item in items]

    def get(self, capture_id: str) -> CaptureView:
        return self._store.view(capture_id)

    def list(self, *, status: str | None = None) -> list[CaptureView]:
        return self._store.list(status=status)

    def prepare(self, capture_id: str) -> dict:
        """Open an idempotent routing conversation without creating work.

        The prompt is derived from the immutable record, so it survives a
        service restart and always carries the complete captured text. The
        stable conversation id is independent of whichever chat thread was
        active when the thought was captured.
        """
        current = self._store.view(capture_id)  # KeyError if unknown
        if current.processing_status in {"routed", "archived"}:
            raise ValueError(
                f"capture {capture_id} is already {current.processing_status}"
            )
        if current.processing_status != "ready_to_route":
            self._store.set_status(capture_id, "ready_to_route", at=self._clock())
        conversation_id = f"capture:{capture_id}"
        raw_content = current.record.raw_content
        chat_prompt = (
            "Help Geoff prepare this saved capture for routing. Do not start or "
            "create work yet. Preserve the raw capture as immutable source text, "
            "clarify it conversationally if needed, then offer these choices: "
            "continue in chat, add it to General Todos, choose an existing kanban, or "
            "create a new kanban. A route must remain an explicit later choice.\n\n"
            f"Capture ID: {capture_id}\n"
            "IMMUTABLE RAW CAPTURE (complete, verbatim)\n"
            "--- BEGIN RAW CAPTURE ---\n"
            f"{raw_content}\n"
            "--- END RAW CAPTURE ---"
        )
        return {
            "capture_id": capture_id,
            "conversation_id": conversation_id,
            "processing_status": "ready_to_route",
            "chat_prompt": chat_prompt,
            "available_actions": [dict(action) for action in _PREPARE_ACTIONS],
        }

    def inbox(self) -> dict:
        """The Universal Inbox: every capture grouped into its lane, in canonical
        order, plus a total. Nothing is ever dropped — a capture is recoverable
        here even after it is routed elsewhere."""
        by_status: dict[str, list[dict]] = {s: [] for s in INBOX_STATUSES}
        views = self._store.list()
        for v in views:
            by_status.setdefault(v.processing_status, []).append(_card(v))
        columns = [{"name": s, "captures": by_status[s]}
                   for s in INBOX_STATUSES if by_status.get(s)]
        # any non-canonical status (future lanes) still shows, never hidden
        columns += [{"name": s, "captures": c} for s, c in by_status.items()
                    if s not in INBOX_STATUSES and c]
        return {"columns": columns, "total": len(views)}

    def mark_converted(self, capture_id: str, work_item_ids: Sequence[str], *,
                       conversation_id: str | None = None,
                       operation_key: str | None = None) -> CaptureView:
        """Record that a capture became canonical work: append a 'link' event
        carrying the created work_item_ids, then move the capture to the 'routed'
        lane. The capture is NEVER destroyed — it stays recoverable in the Inbox,
        now linked to the work it produced (capture→work; the reverse work→capture
        lives on WorkItem.capture_id). KeyError if the capture is unknown."""
        now = self._clock()
        self._store.mark_converted(
            capture_id, list(work_item_ids),
            conversation_id=conversation_id, operation_key=operation_key, at=now,
        )
        return self._store.view(capture_id)

    def archive(self, capture_id: str, *, reason: str) -> CaptureView:
        """Safe discard: hide the capture from the active Inbox lanes while
        PRESERVING its immutable raw record and full event history. Never a
        hard delete; a routed capture cannot be archived (it is already the
        provenance of canonical work). Idempotent."""
        current = self._store.view(capture_id)  # KeyError if unknown
        if current.processing_status == "archived":
            return current
        if current.processing_status == "routed":
            raise ValueError(
                f"capture {capture_id} is routed — it is the provenance of "
                "existing work and cannot be discarded")
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("an archive reason is required")
        now = self._clock()
        self._store.append_event(CaptureEvent(
            capture_id=capture_id, ts=now, kind="archived",
            payload={"reason": reason}))
        self._store.set_status(capture_id, "archived", at=now)
        return self._store.view(capture_id)


def _card(v: CaptureView) -> dict:
    r = v.record
    return {
        "capture_id": r.capture_id,
        "preview": r.raw_content[:160],
        "source_type": r.source_type,
        "requested_mode": r.requested_mode,
        "processing_status": v.processing_status,
        "batch_id": r.batch_id,
        "capture_kind": v.classification.capture_kind if v.classification else None,
        "suggested_board_id": (v.classification.suggested_board_id
                               if v.classification else None),
        "captured_at": r.captured_at,
        "updated_at": v.updated_at,
    }
