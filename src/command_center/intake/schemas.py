"""Capture contracts — the immutable intake record + its (separate, appendable)
classification. The raw thought is preserved verbatim and never overwritten;
status transitions and classification are appended as events.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# What the user was doing when they captured it (kept broad, extended later).
SourceType = Literal[
    "text", "voice", "url", "document", "screenshot", "email",
    "chat", "list", "card", "conversation"]

# The requested handling — capture is NOT automatically work (§ "save/organize/…").
RequestedMode = Literal["save_only", "prepare_later", "prepare_now", "create_task"]

# The classifier's kinds. board_candidate = "this looks like a whole new realm".
CAPTURE_KINDS: tuple[str, ...] = (
    "note", "idea", "todo", "research_question", "post", "paper", "project",
    "bug", "feature", "maintenance", "decision", "reminder", "reference",
    "board_candidate")
CaptureKind = Literal[
    "note", "idea", "todo", "research_question", "post", "paper", "project",
    "bug", "feature", "maintenance", "decision", "reminder", "reference",
    "board_candidate"]

# The Universal Inbox lanes — the safety net a capture is always recoverable from.
INBOX_STATUSES: tuple[str, ...] = (
    "captured", "needs_clarification", "ready_to_route", "preparing",
    "ready_for_review", "routed", "archived")
ProcessingStatus = Literal[
    "captured", "needs_clarification", "ready_to_route", "preparing",
    "ready_for_review", "routed", "archived"]


class CaptureRecord(BaseModel):
    """The IMMUTABLE raw capture. Frozen on purpose — a captured thought is never
    edited in place; reclassification/routing/status changes are appended events
    (see CaptureEvent) and the current status lives in the store, not here."""
    model_config = ConfigDict(frozen=True)

    capture_id: str
    raw_content: str
    source_type: SourceType = "text"
    source_ref: str | None = None          # url / message id / file ref — never a secret
    captured_at: str                        # ISO-8601, stamped by the service
    captured_by: str | None = None
    # optional context the capture was made from — used later for routing, never
    # forces work to start
    current_board_id: str | None = None
    current_card_id: str | None = None
    conversation_id: str | None = None
    batch_id: str | None = None             # set when split from a bulk list
    attachments: list[str] = Field(default_factory=list)
    requested_mode: RequestedMode = "save_only"


class CaptureClassification(BaseModel):
    """A SEPARATE, appendable classification — never mutates the raw record. A
    re-classification is a new record/event, so the original thought is intact."""
    capture_id: str
    capture_kind: CaptureKind
    intent: str = ""
    topic_tags: list[str] = Field(default_factory=list)
    urgency: str | None = None
    time_horizon: str | None = None
    suggested_board_id: str | None = None
    suggested_card_type: str | None = None
    candidate_boards: list[str] = Field(default_factory=list)
    routing_evidence: list[str] = Field(default_factory=list)
    confidence: float | None = None
    needs_clarification: list[str] = Field(default_factory=list)
    duplicate_candidates: list[str] = Field(default_factory=list)
    classified_at: str | None = None
    classified_by: str | None = None        # which role/model produced it


class CaptureEvent(BaseModel):
    """Append-only history entry — status transitions, classification, routing,
    card/mission links. The capture's current state is folded from these."""
    capture_id: str
    ts: str
    kind: str                               # status | classify | route | link | note
    payload: dict = Field(default_factory=dict)


class CaptureView(BaseModel):
    """A read model: the immutable record + its current derived status + latest
    classification. What the API/Inbox render — the store folds events into this."""
    record: CaptureRecord
    processing_status: ProcessingStatus
    classification: CaptureClassification | None = None
    event_count: int = 0
    updated_at: str


# Bullets include the Unicode markers phone note apps emit on paste:
# ◦ U+25E6 white, ⁃ U+2043 hyphen, ‣ U+2023 triangular. A marker at
# end-of-line is an empty bullet: recognized, then dropped as empty.
_SPLIT_PREFIX = re.compile(r"^\s*(?:[-*+•◦⁃‣]|\d+[.)])(?:\s+|$)")


def split_bulk_list(text: str) -> list[str]:
    """Split a pasted idea list into individual capture bodies WITHOUT losing
    anything. A line that is a bullet/number item is its own capture; consecutive
    non-bulleted lines that look like prose stay joined. Blank lines separate.
    Returns [] for empty input, [text] for a single-item paste with no markers."""
    lines = text.replace("\r\n", "\n").split("\n")
    items: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        joined = "\n".join(buf).strip()
        if joined:
            items.append(joined)
        buf.clear()

    saw_marker = False
    for line in lines:
        if not line.strip():
            flush()
            continue
        if _SPLIT_PREFIX.match(line):
            saw_marker = True
            flush()
            # strip stacked markers ("◦ - item") — formatting, never content
            while _SPLIT_PREFIX.match(line):
                line = _SPLIT_PREFIX.sub("", line, count=1)
            buf.append(line.strip())
            flush()
        else:
            buf.append(line)
    flush()

    if not saw_marker and len(items) <= 1:
        # a single free-text paste is ONE capture, not split on newlines
        whole = text.strip()
        return [whole] if whole else []
    return items
