"""
Canonical SQLite DDL for the experiment registry.

This EXTENDS the Ledger — the same ledger.db that already holds missions, events,
approvals, and leases — rather than standing up a second runtime database. The
tables are additive (CREATE ... IF NOT EXISTS), so migrating an existing ledger.db
leaves the mission tables untouched.

`SCHEMA_SQL` is the single source of truth. The standalone Ledger FastAPI service
(services/ledger/app.py) carries a byte-identical copy because its container cannot
import this package; `tests/test_ledger_experiment_schema.py` asserts the two never
drift.

Design:
  * experiments        — one row per experiment; the registered definition is stored
                         immutably as JSON; status changes are also appended as events.
  * experiment_events  — append-only lifecycle + execution audit trail.
  * experiment_runs    — one row per baseline/candidate/verifier run; raw metrics +
                         budget consumption retained; FAILED/EXCLUDED runs are kept.
  * experiment_artifacts — content-addressed evidence (path + sha256 + bytes).
  * experiment_links   — supersedes / reopened_from / related relationships.
  * schema_migrations  — records which registry schema versions have been applied.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = "improvement.v1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id     TEXT PRIMARY KEY,
    mission_id        TEXT,
    title             TEXT,
    owner             TEXT,
    target_type       TEXT,
    target_ref        TEXT,
    risk_tier         TEXT,
    status            TEXT,
    baseline_version  TEXT,
    candidate_version TEXT,
    definition_json   TEXT,
    definition_hash   TEXT,
    baseline_locked   INTEGER DEFAULT 0,
    baseline_hash     TEXT,
    verifier_verdict  TEXT,
    human_decision    TEXT,
    canary_status     TEXT,
    rollback_status   TEXT,
    created_at        TEXT,
    updated_at        TEXT,
    expires_at        TEXT
);

CREATE TABLE IF NOT EXISTS experiment_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    ts            TEXT,
    kind          TEXT,
    actor_role    TEXT,
    actor_model   TEXT,
    action        TEXT,
    payload       TEXT,
    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id          TEXT PRIMARY KEY,
    experiment_id   TEXT,
    role            TEXT,
    iteration       INTEGER DEFAULT 0,
    started_at      TEXT,
    finished_at     TEXT,
    status          TEXT,
    cache_state     TEXT,
    commit_ref      TEXT,
    sample_count    INTEGER DEFAULT 0,
    metrics         TEXT,
    budget          TEXT,
    excluded_reason TEXT,
    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    run_id        TEXT,
    name          TEXT,
    kind          TEXT,
    path          TEXT,
    sha256        TEXT,
    bytes         INTEGER,
    ts            TEXT,
    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_links (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id   TEXT,
    to_id     TEXT,
    relation  TEXT,
    ts        TEXT
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(conn: sqlite3.Connection) -> str:
    """Apply the experiment-registry DDL to ``conn`` (idempotent) and record the
    schema version. Returns the applied version. Safe to run against a ledger.db
    that already holds the mission tables — every statement is additive."""
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, _now()),
    )
    conn.commit()
    return SCHEMA_VERSION


def applied_versions(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]
