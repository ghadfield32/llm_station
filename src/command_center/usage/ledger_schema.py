"""
Canonical SQLite DDL for unified runtime usage/limits/availability durability.

EXTENDS the Ledger (the same ledger.db that already holds missions, events,
approvals, leases, the experiment registry, and agent sessions) — not a
second database. Tables are additive (CREATE ... IF NOT EXISTS), mirroring
the exact precedent of `command_center.agent_sessions.ledger_schema` and
`command_center.improvement.ledger_schema`.

`SCHEMA_SQL` is the single source of truth. services/ledger/app.py carries a
byte-identical copy (its container can't import this package);
tests/test_usage_ledger_schema.py asserts they never drift.

Idempotency/dedup are enforced at the SQL layer so a repeat is a genuine
no-op regardless of backend:
  * model_usage_samples.source_hash        UNIQUE
  * model_limit_snapshots.source_hash      UNIQUE
  * model_availability_events.source_hash  UNIQUE
  * model_usage_alerts.dedup_key           UNIQUE

Attribution is stored as flat columns (tenant/workspace/user/conversation/
session/mission/repo/provider_request/source_record) so usage can be traced —
and later filtered in SQL — to exactly who/what consumed it. NO credential,
token, or raw-provider-response column exists here, by design.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = "usage.v1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS model_usage_samples (
    sample_id           TEXT PRIMARY KEY,
    runtime_id          TEXT NOT NULL,
    source              TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    ingested_at         TEXT NOT NULL,
    source_hash         TEXT NOT NULL UNIQUE,
    sample_kind         TEXT NOT NULL DEFAULT 'request_delta',
    input_tokens        INTEGER DEFAULT 0,
    cached_input_tokens INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    reasoning_tokens    INTEGER DEFAULT 0,
    total_tokens        INTEGER DEFAULT 0,
    calls               INTEGER DEFAULT 0,
    sessions            INTEGER DEFAULT 0,
    tool_calls          INTEGER DEFAULT 0,
    duration_ms         INTEGER DEFAULT 0,
    cost_usd            REAL,
    cost_source         TEXT,
    window_start        TEXT,
    window_end          TEXT,
    aggregation_key     TEXT,
    repository_scans    INTEGER DEFAULT 0,
    test_runs           INTEGER DEFAULT 0,
    retries             INTEGER DEFAULT 0,
    failed_calls        INTEGER DEFAULT 0,
    worker_restarts     INTEGER DEFAULT 0,
    session_resumes     INTEGER DEFAULT 0,
    tenant_id           TEXT,
    workspace_id        TEXT,
    user_id             TEXT,
    conversation_id     TEXT,
    agent_session_id    TEXT,
    mission_id          TEXT,
    repo_id             TEXT,
    provider_request_id TEXT,
    source_record_id    TEXT
);

CREATE TABLE IF NOT EXISTS model_limit_snapshots (
    snapshot_id       TEXT PRIMARY KEY,
    runtime_id        TEXT NOT NULL,
    bucket_id         TEXT NOT NULL,
    scope             TEXT NOT NULL,
    source            TEXT NOT NULL,
    state             TEXT NOT NULL,
    observed_at       TEXT NOT NULL,
    ingested_at       TEXT NOT NULL,
    source_hash       TEXT NOT NULL UNIQUE,
    label             TEXT,
    used_percent      REAL,
    used_amount       REAL,
    limit_amount      REAL,
    remaining_amount  REAL,
    unit              TEXT,
    window_seconds    INTEGER,
    reset_at          TEXT,
    plan_type         TEXT,
    credits_remaining REAL
);

CREATE TABLE IF NOT EXISTS model_availability_events (
    event_id    TEXT PRIMARY KEY,
    runtime_id  TEXT NOT NULL,
    source      TEXT NOT NULL,
    state       TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    source_hash TEXT NOT NULL UNIQUE,
    reason      TEXT,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS model_usage_alerts (
    alert_id   TEXT PRIMARY KEY,
    runtime_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    dedup_key  TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    subject_id TEXT,
    threshold  REAL,
    message    TEXT,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS model_routing_decisions (
    decision_id                 TEXT PRIMARY KEY,
    created_at                  TEXT NOT NULL,
    mission_id                  TEXT,
    runtime_id                  TEXT NOT NULL,
    selected                    INTEGER NOT NULL,
    reason                      TEXT,
    usage_snapshot_id           TEXT,
    limit_snapshot_ids          TEXT,
    availability_at_selection   TEXT,
    budget_state_at_selection   TEXT
);

CREATE TABLE IF NOT EXISTS model_usage_collection_state (
    collector_id          TEXT PRIMARY KEY,
    updated_at            TEXT NOT NULL,
    last_success_at       TEXT,
    last_cursor           TEXT,
    last_source_record_id TEXT,
    last_error            TEXT,
    consecutive_failures  INTEGER DEFAULT 0,
    next_eligible_at      TEXT,
    auth_state            TEXT DEFAULT 'unknown'
);

CREATE INDEX IF NOT EXISTS ix_usage_samples_runtime_observed
    ON model_usage_samples (runtime_id, observed_at);
CREATE INDEX IF NOT EXISTS ix_usage_samples_mission
    ON model_usage_samples (mission_id);
CREATE INDEX IF NOT EXISTS ix_usage_samples_repo
    ON model_usage_samples (repo_id);
CREATE INDEX IF NOT EXISTS ix_usage_samples_user
    ON model_usage_samples (user_id);
CREATE INDEX IF NOT EXISTS ix_usage_samples_session
    ON model_usage_samples (agent_session_id);
CREATE INDEX IF NOT EXISTS ix_limit_snapshots_runtime_bucket_observed
    ON model_limit_snapshots (runtime_id, bucket_id, observed_at);
CREATE INDEX IF NOT EXISTS ix_availability_runtime_observed
    ON model_availability_events (runtime_id, observed_at);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(conn: sqlite3.Connection) -> str:
    """Apply the usage DDL to ``conn`` (idempotent) and record the schema
    version. Additive — safe against a ledger.db already holding the mission/
    experiment/agent-session tables."""
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, _now()),
    )
    conn.commit()
    return SCHEMA_VERSION
