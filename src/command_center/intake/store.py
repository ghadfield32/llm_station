"""In-memory CaptureStore. The durable, Ledger-backed sibling is the immediate
follow-up; this implements the same surface the LedgerCaptureStore will, so the
service/API never care which backend they hold (mirrors the usage subsystem).

The raw record is stored once and never mutated; status/classification changes
are appended events and the current status is a separate fold.
"""
from __future__ import annotations

from .schemas import (
    CaptureClassification,
    CaptureEvent,
    CaptureRecord,
    CaptureView,
)


class InMemoryCaptureStore:
    def __init__(self) -> None:
        self._records: dict[str, CaptureRecord] = {}
        self._status: dict[str, str] = {}
        self._classification: dict[str, CaptureClassification] = {}
        self._events: dict[str, list[CaptureEvent]] = {}
        self._order: list[str] = []

    def add(self, record: CaptureRecord, *, status: str, at: str) -> None:
        if record.capture_id in self._records:
            raise KeyError(f"capture {record.capture_id} already exists")
        self._records[record.capture_id] = record
        self._status[record.capture_id] = status
        self._events[record.capture_id] = [CaptureEvent(
            capture_id=record.capture_id, ts=at, kind="status",
            payload={"status": status, "created": True})]
        self._order.append(record.capture_id)

    def _require(self, capture_id: str) -> CaptureRecord:
        rec = self._records.get(capture_id)
        if rec is None:
            raise KeyError(f"no such capture: {capture_id}")
        return rec

    def append_event(self, event: CaptureEvent) -> None:
        self._require(event.capture_id)
        self._events[event.capture_id].append(event)

    def set_status(self, capture_id: str, status: str, at: str) -> None:
        self._require(capture_id)
        self._status[capture_id] = status
        self.append_event(CaptureEvent(
            capture_id=capture_id, ts=at, kind="status", payload={"status": status}))

    def set_classification(self, cls: CaptureClassification, at: str) -> None:
        self._require(cls.capture_id)
        self._classification[cls.capture_id] = cls
        self.append_event(CaptureEvent(
            capture_id=cls.capture_id, ts=at, kind="classify", payload=cls.model_dump()))

    def view(self, capture_id: str) -> CaptureView:
        self._require(capture_id)
        events = self._events[capture_id]
        return CaptureView(
            record=self._records[capture_id],
            processing_status=self._status[capture_id],  # type: ignore[arg-type]
            classification=self._classification.get(capture_id),
            event_count=len(events), updated_at=events[-1].ts)

    def list(self, *, status: str | None = None,
             batch_id: str | None = None) -> list[CaptureView]:
        out: list[CaptureView] = []
        for cid in self._order:
            if status is not None and self._status[cid] != status:
                continue
            if batch_id is not None and self._records[cid].batch_id != batch_id:
                continue
            out.append(self.view(cid))
        return out

    def events(self, capture_id: str) -> list[CaptureEvent]:
        self._require(capture_id)
        return list(self._events[capture_id])
