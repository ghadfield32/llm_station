"""Universal Capture / intake — turn a rough thought into a durable, recoverable
intake record BEFORE deciding whether it becomes a card, a project, or nothing.

The raw capture is immutable; every later change (status, classification, routing)
is an appended event. Classification / routing / packet building are later phases;
this package is the stable record they all build on.
"""
from .schemas import (
    CAPTURE_KINDS,
    INBOX_STATUSES,
    CaptureClassification,
    CaptureEvent,
    CaptureRecord,
    CaptureView,
    split_bulk_list,
)
from .service import CaptureService
from .ledger_store import LedgerCaptureStore
from .store import InMemoryCaptureStore

__all__ = [
    "CAPTURE_KINDS",
    "INBOX_STATUSES",
    "CaptureClassification",
    "CaptureEvent",
    "CaptureRecord",
    "CaptureView",
    "CaptureService",
    "InMemoryCaptureStore",
    "LedgerCaptureStore",
    "split_bulk_list",
]
