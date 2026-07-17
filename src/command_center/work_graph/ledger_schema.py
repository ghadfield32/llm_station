"""
Canonical SQLite DDL for durable work-graph storage (WorkItem/placement/edge).

EXTENDS the Ledger (the same ledger.db holding missions, agent sessions, usage,
and captures) — additive, mirroring the exact precedent of
`command_center.intake.ledger_schema` and `command_center.usage.ledger_schema`.

`SCHEMA_SQL` is the single source of truth; services/ledger/app.py carries a
byte-identical copy (its container can't import this package) and
tests/test_work_graph_ledger_schema.py asserts they never drift.

Placements and edges are SOFT-removed (removed_at set) — the canonical WorkItem
and its history are never destroyed by removing a projection or a link. Edges are
work_item <-> work_item only; board membership is a work_placement, never an edge.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = "workgraph.v1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS work_items (
    work_item_id      TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    description       TEXT,
    kind              TEXT NOT NULL DEFAULT 'todo',
    canonical_status  TEXT NOT NULL DEFAULT 'backlog',
    primary_board_id  TEXT,
    owner             TEXT,
    priority          TEXT,
    due_at            TEXT,
    capture_id        TEXT,
    capture_batch_id  TEXT,
    packet_id         TEXT,
    conversation_id   TEXT,
    mission_id        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_placements (
    placement_id    TEXT PRIMARY KEY,
    work_item_id    TEXT NOT NULL,
    board_id        TEXT NOT NULL,
    domain_id       TEXT NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    placement_stage TEXT,
    card_component  TEXT NOT NULL DEFAULT 'generic_task',
    local_fields    TEXT,
    created_at      TEXT NOT NULL,
    removed_at      TEXT
);

CREATE TABLE IF NOT EXISTS work_edges (
    edge_id            TEXT PRIMARY KEY,
    from_work_item_id  TEXT NOT NULL,
    to_work_item_id    TEXT NOT NULL,
    relation           TEXT NOT NULL,
    blocking           INTEGER NOT NULL DEFAULT 0,
    reason             TEXT,
    evidence_refs      TEXT,
    created_by         TEXT,
    created_at         TEXT NOT NULL,
    removed_at         TEXT
);

CREATE TABLE IF NOT EXISTS work_events (
    event_seq    INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL,
    ts           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    payload      TEXT
);

CREATE INDEX IF NOT EXISTS ix_work_placements_item
    ON work_placements (work_item_id);
CREATE INDEX IF NOT EXISTS ix_work_placements_board
    ON work_placements (board_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_work_placements_active_target
    ON work_placements (work_item_id, board_id, domain_id)
    WHERE removed_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_work_placements_active_primary
    ON work_placements (work_item_id)
    WHERE is_primary = 1 AND removed_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_work_edges_from ON work_edges (from_work_item_id);
CREATE INDEX IF NOT EXISTS ix_work_edges_to ON work_edges (to_work_item_id);
CREATE INDEX IF NOT EXISTS ix_work_events_item
    ON work_events (work_item_id, event_seq);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(conn: sqlite3.Connection) -> str:
    """Apply the work-graph DDL to ``conn`` (idempotent) and record the schema
    version. Additive — safe against a ledger.db already holding the other
    subsystems' tables."""
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, _now()),
    )
    conn.commit()
    return SCHEMA_VERSION
