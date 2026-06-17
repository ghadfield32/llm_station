"""Autonomy hardening primitives: canonical events and completion verification."""
from .events import CanonicalEvent, validate_event_record
from .verifier import CompletionVerdict, verify_completion

__all__ = [
    "CanonicalEvent",
    "CompletionVerdict",
    "validate_event_record",
    "verify_completion",
]
