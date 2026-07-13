"""
Canonical SQLite DDL for durable Universal Capture (intake) storage.

EXTENDS the Ledger (the same ledger.db that holds missions, events, approvals,
leases, the experiment registry, agent sessions, and usage) — not a second
database. Tables are additive (CREATE ... IF NOT EXISTS), mirroring the exact
precedent of `command_center.usage.ledger_schema` and
`command_center.agent_sessions.ledger_schema`.

`SCHEMA_SQL` is the single source of truth. services/ledger/app.py carries a
byte-identical copy (its container can't import this package);
tests/test_capture_ledger_schema.py asserts they never drift.

The raw capture is IMMUTABLE — `captures.raw_content` is written once and never
updated. Status transitions and classification are appended to `capture_events`
(monotonic `event_seq` → guaranteed ordering); the current status/classification
are also folded onto the `captures` row for cheap listing. NO credential, token,
or raw-provider-response column exists here, by design — capture stores the
user's own rough text, not third-party responses.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = "capture.v1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS captures (
    capture_id        TEXT PRIMARY KEY,
    raw_content       TEXT NOT NULL,
    source_type       TEXT NOT NULL DEFAULT 'text',
    source_ref        TEXT,
    captured_at       TEXT NOT NULL,
    ingested_at       TEXT NOT NULL,
    captured_by       TEXT,
    current_board_id  TEXT,
    current_card_id   TEXT,
    conversation_id   TEXT,
    batch_id          TEXT,
    attachments       TEXT,
    requested_mode    TEXT NOT NULL DEFAULT 'save_only',
    processing_status TEXT NOT NULL DEFAULT 'captured',
    classification    TEXT,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capture_events (
    event_seq  INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    ts         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    payload    TEXT
);

CREATE INDEX IF NOT EXISTS ix_captures_status ON captures (processing_status);
CREATE INDEX IF NOT EXISTS ix_captures_batch ON captures (batch_id);
CREATE INDEX IF NOT EXISTS ix_capture_events_cap
    ON capture_events (capture_id, event_seq);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(conn: sqlite3.Connection) -> str:
    """Apply the capture DDL to ``conn`` (idempotent) and record the schema
    version. Additive — safe against a ledger.db already holding the mission/
    experiment/agent-session/usage tables."""
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, _now()),
    )
    conn.commit()
    return SCHEMA_VERSION
