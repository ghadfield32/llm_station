"""LedgerCaptureStore — the durable sibling of store.InMemoryCaptureStore, backed
by the Ledger's /capture* endpoints. Same surface, so CaptureService/API never
care which backend they hold (mirrors usage.LedgerUsageStore and
agent_sessions.LedgerSessionStore).

Sync, injected httpx.Client (never constructed here); 404 → KeyError, matching
the in-memory store's contract. The raw capture is written once and never
mutated; status/classification are appended events, ordered by the Ledger's
monotonic event_seq. Durable: captures + their event log survive a cockpit or
worker restart, unlike the in-memory store.
"""
from __future__ import annotations

import httpx

from .schemas import (
    CaptureClassification,
    CaptureEvent,
    CaptureRecord,
    CaptureView,
)
from .store import CaptureConversionConflict

# the immutable CaptureRecord fields the Ledger row carries back
_RECORD_FIELDS = (
    "capture_id", "raw_content", "source_type", "source_ref", "captured_at",
    "captured_by", "current_board_id", "current_card_id", "conversation_id",
    "batch_id", "attachments", "requested_mode")


def _row_to_view(d: dict) -> CaptureView:
    record = CaptureRecord(**{f: d.get(f) for f in _RECORD_FIELDS
                              if d.get(f) is not None or f in ("capture_id",
                                                               "raw_content",
                                                               "captured_at")})
    cls = d.get("classification")
    classification = CaptureClassification(**cls) if cls else None
    return CaptureView(
        record=record,
        processing_status=d["processing_status"],
        classification=classification,
        event_count=d.get("event_count", 0) or 0,
        updated_at=d.get("updated_at") or d["captured_at"])


class LedgerCaptureStore:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def add(self, record: CaptureRecord, *, status: str, at: str) -> None:
        body = record.model_dump()
        body["status"] = status
        r = self._client.post("/capture", json=body)
        r.raise_for_status()

    def append_event(self, event: CaptureEvent) -> None:
        r = self._client.post(
            f"/capture/{event.capture_id}/event",
            json={"ts": event.ts, "kind": event.kind, "payload": event.payload})
        if r.status_code == 404:
            raise KeyError(f"no such capture: {event.capture_id}")
        r.raise_for_status()

    def set_status(self, capture_id: str, status: str, at: str) -> None:
        r = self._client.post(f"/capture/{capture_id}/status",
                              json={"status": status, "ts": at})
        if r.status_code == 404:
            raise KeyError(f"no such capture: {capture_id}")
        r.raise_for_status()

    def set_classification(self, cls: CaptureClassification, at: str) -> None:
        r = self._client.post(f"/capture/{cls.capture_id}/classify",
                              json={"classification": cls.model_dump(), "ts": at})
        if r.status_code == 404:
            raise KeyError(f"no such capture: {cls.capture_id}")
        r.raise_for_status()

    def mark_converted(
        self, capture_id: str, work_item_ids: list[str], *,
        conversation_id: str | None, operation_key: str | None = None, at: str,
    ) -> None:
        r = self._client.post(
            f"/capture/{capture_id}/converted",
            json={
                "work_item_ids": work_item_ids,
                "conversation_id": conversation_id,
                "operation_key": operation_key,
                "ts": at,
            },
        )
        if r.status_code == 404:
            raise KeyError(f"no such capture: {capture_id}")
        if r.status_code == 409:
            raise CaptureConversionConflict(r.json().get(
                "detail", "capture conversion conflict",
            ))
        r.raise_for_status()

    def view(self, capture_id: str) -> CaptureView:
        r = self._client.get(f"/capture/{capture_id}")
        if r.status_code == 404:
            raise KeyError(f"no such capture: {capture_id}")
        r.raise_for_status()
        return _row_to_view(r.json())

    def list(self, *, status: str | None = None,
             batch_id: str | None = None) -> list[CaptureView]:
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status
        if batch_id is not None:
            params["batch_id"] = batch_id
        r = self._client.get("/captures", params=params)
        r.raise_for_status()
        return [_row_to_view(row) for row in r.json()]

    def events(self, capture_id: str) -> list[CaptureEvent]:
        r = self._client.get(f"/capture/{capture_id}/events")
        if r.status_code == 404:
            raise KeyError(f"no such capture: {capture_id}")
        r.raise_for_status()
        return [CaptureEvent(**e) for e in r.json()]
