"""CaptureService — the intake API's brain. Generates ids + timestamps, preserves
the raw thought immutably, splits bulk lists into individual captures (retaining
the batch), and folds everything into the Universal Inbox.

It NEVER starts work: a capture is saved/organized, not executed. Classification,
routing, packet building, and the daily DAG are later phases that append to this
same stable record. Clock + id factory are injected so it stays hermetic.
"""
from __future__ import annotations

from collections.abc import Callable

from .schemas import (
    INBOX_STATUSES,
    CaptureRecord,
    CaptureView,
    split_bulk_list,
)
from .store import InMemoryCaptureStore

# requested_mode -> the status a fresh capture lands in. Only "captured" today;
# routing/preparation (later phases) advance it. Saving is never starting work.
_START_STATUS = "captured"


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
