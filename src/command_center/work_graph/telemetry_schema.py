"""
Canonical SQLite DDL for durable router-correction telemetry.

EXTENDS the Ledger (the same ledger.db holding missions, agent sessions, usage,
captures, and the work graph) — additive, mirroring the exact precedent of
`command_center.work_graph.ledger_schema`.

`SCHEMA_SQL` is the single source of truth; services/ledger/app.py carries a
byte-identical copy (its container can't import this package) and
tests/test_routing_telemetry_schema.py asserts they never drift.

A routing_correction is the durable GROUND TRUTH of what a human chose after the
router proposed (or declined to propose) a board. Nothing is derived from it
here — it is the evidence a later, evidence-backed calibration phase learns from
(temporally: past corrections only). Rows are append-only; a correction is never
edited (a re-decision is a new row).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = "routing.telemetry.v1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS routing_corrections (
    correction_id      TEXT PRIMARY KEY,
    at                 TEXT NOT NULL,
    title              TEXT NOT NULL,
    ref                TEXT,
    suggested_board_id TEXT,
    chosen_board_id    TEXT,
    accepted           INTEGER NOT NULL DEFAULT 0,
    matched_keywords   TEXT,
    conversation_id    TEXT,
    capture_id         TEXT,
    source             TEXT NOT NULL DEFAULT 'chat'
);

CREATE INDEX IF NOT EXISTS ix_routing_corrections_at
    ON routing_corrections (at);
CREATE INDEX IF NOT EXISTS ix_routing_corrections_chosen
    ON routing_corrections (chosen_board_id);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(conn: sqlite3.Connection) -> str:
    """Apply the telemetry DDL to ``conn`` (idempotent) and record the schema
    version. Additive — safe against a ledger.db already holding the other
    subsystems' tables."""
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, _now()),
    )
    conn.commit()
    return SCHEMA_VERSION
