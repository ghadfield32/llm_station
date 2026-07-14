"""
Canonical SQLite DDL for durable Readiness Packet storage (Phase H slice 2).

EXTENDS the Ledger (the same ledger.db holding missions, agent sessions, usage,
captures, and the work graph) — additive, mirroring the exact precedent of
`command_center.work_graph.ledger_schema` and `command_center.intake.ledger_schema`.

`PACKET_SCHEMA_SQL` is the single source of truth; services/ledger/app.py carries
a byte-identical copy (its container can't import this package) and
tests/test_packet_ledger_schema.py asserts they never drift.

Model:
  * `readiness_packets` is the current-state row; `reviews_json` holds the CURRENT
    review slots (authoritative for reconstructing ReadinessPacket.reviews).
  * `packet_revisions` is append-only and immutable: one row per plan-content
    revision, keyed (packet_id, revision), carrying the content_digest + a full
    snapshot. Reviews never define a revision (they are excluded from the digest).
  * `packet_reviews` is the append-only audit binding a review outcome to the
    revision it reviewed; `session_id` links the agent-session/judge run.
  * `packet_work_links` is authoritative for the work items a committed packet
    created (ReadinessPacket.work_item_ids is reconstructed from it).
  * A committed packet (`committed_at` set) is frozen — the Ledger rejects review
    and revision writes against it.
No secrets or uncontrolled environment data are stored (plan/research text only).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = "packet.v1"

PACKET_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS readiness_packets (
    packet_id         TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'draft',
    capture_id        TEXT,
    conversation_id   TEXT,
    research          TEXT,
    plan_json         TEXT NOT NULL,
    plan_summary_json TEXT NOT NULL,
    runbook_json      TEXT,
    acceptance_json   TEXT,
    reviews_json      TEXT,
    current_revision  INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    committed_at      TEXT
);

CREATE TABLE IF NOT EXISTS packet_revisions (
    packet_id      TEXT NOT NULL,
    revision       INTEGER NOT NULL,
    content_digest TEXT NOT NULL,
    snapshot_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (packet_id, revision)
);

CREATE TABLE IF NOT EXISTS packet_reviews (
    packet_id     TEXT NOT NULL,
    revision      INTEGER NOT NULL,
    role          TEXT NOT NULL,
    status        TEXT NOT NULL,
    summary       TEXT,
    findings_json TEXT,
    session_id    TEXT,
    reviewed_at   TEXT NOT NULL,
    PRIMARY KEY (packet_id, revision, role)
);

CREATE TABLE IF NOT EXISTS packet_events (
    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    packet_id TEXT NOT NULL,
    ts        TEXT NOT NULL,
    kind      TEXT NOT NULL,
    payload   TEXT
);

CREATE TABLE IF NOT EXISTS packet_work_links (
    packet_id    TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    PRIMARY KEY (packet_id, work_item_id)
);

CREATE INDEX IF NOT EXISTS ix_packet_revisions_packet
    ON packet_revisions (packet_id);
CREATE INDEX IF NOT EXISTS ix_packet_reviews_packet
    ON packet_reviews (packet_id, revision);
CREATE INDEX IF NOT EXISTS ix_packet_events_packet
    ON packet_events (packet_id, event_seq);
CREATE INDEX IF NOT EXISTS ix_packet_work_links_packet
    ON packet_work_links (packet_id);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(conn: sqlite3.Connection) -> str:
    """Apply the packet DDL to ``conn`` (idempotent) and record the schema
    version. Additive — safe against a ledger.db already holding the other
    subsystems' tables."""
    conn.executescript(PACKET_SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, _now()),
    )
    conn.commit()
    return SCHEMA_VERSION
