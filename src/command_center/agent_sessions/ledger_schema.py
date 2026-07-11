"""
Canonical SQLite DDL for agent-session durability.

This EXTENDS the Ledger — the same ledger.db that already holds missions, events,
approvals, leases, and the experiment registry — rather than standing up a second
runtime database. The tables are additive (CREATE ... IF NOT EXISTS), so migrating
an existing ledger.db leaves every other table untouched. This mirrors the exact
precedent set by `command_center.improvement.ledger_schema` for the experiment
registry (see that module's docstring).

`SCHEMA_SQL` is the single source of truth. The standalone Ledger FastAPI service
(services/ledger/app.py) carries a byte-identical copy because its container cannot
import this package; `tests/test_agent_session_ledger_schema.py` asserts the two
never drift.

Design:
  * agent_sessions        — one row per agent session (Claude Agent / Codex Agent /
                            FakeHarness). Mirrors the fields of
                            command_center.agent_sessions.store.SessionRecord so a
                            row can be unpacked straight into that dataclass.
  * agent_session_events   — append-only, PRIMARY KEY (session_id, sequence). The
                            Ledger — not the harness — assigns `sequence`
                            transactionally, so a vendor-supplied ordering is never
                            trusted (see GatewayCore's frontier tool_calls incident
                            for why that distinction is load-bearing).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = "agent_sessions.v1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id          TEXT PRIMARY KEY,
    conversation_id     TEXT,
    harness              TEXT,
    provider_profile    TEXT,
    model                TEXT,
    external_session_id TEXT,
    repo_id              TEXT,
    workspace_path       TEXT,
    worktree_path        TEXT,
    branch                TEXT,
    base_branch          TEXT,
    permission_profile   TEXT,
    worker_id            TEXT,
    status                TEXT,
    created_at           TEXT,
    updated_at           TEXT,
    last_event_sequence  INTEGER DEFAULT 0,
    cost_usd              REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS agent_session_events (
    session_id TEXT,
    sequence   INTEGER,
    ts         TEXT,
    type       TEXT,
    payload    TEXT,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(conn: sqlite3.Connection) -> str:
    """Apply the agent-session DDL to ``conn`` (idempotent) and record the schema
    version. Safe to run against a ledger.db that already holds the mission/
    experiment tables — every statement is additive."""
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, _now()),
    )
    conn.commit()
    return SCHEMA_VERSION
