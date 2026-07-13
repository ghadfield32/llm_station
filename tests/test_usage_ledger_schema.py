"""Guard: the Ledger service's inlined usage DDL must not drift from the
canonical schema in command_center.usage.ledger_schema.

Mirrors tests/test_agent_session_ledger_schema.py exactly, for the usage
tables. Reads the service source as text (does NOT import app.py, which would
open a real DB at import time).
"""
from __future__ import annotations

import re
from pathlib import Path

from command_center.usage.ledger_schema import SCHEMA_SQL

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


def _extract_service_ddl() -> str:
    text = LEDGER_APP.read_text(encoding="utf-8")
    m = re.search(r'USAGE_SCHEMA_SQL\s*=\s*"""(.*?)"""', text, re.DOTALL)
    assert m, "USAGE_SCHEMA_SQL constant not found in services/ledger/app.py"
    return m.group(1)


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", "", sql)


def test_ledger_service_ddl_matches_canonical():
    canonical = _normalize(SCHEMA_SQL)
    service = _normalize(_extract_service_ddl())
    assert canonical == service, (
        "services/ledger/app.py USAGE_SCHEMA_SQL has drifted from "
        "command_center.usage.ledger_schema.SCHEMA_SQL — keep them identical"
    )


def test_all_usage_tables_present_in_service():
    service = _extract_service_ddl()
    for table in ("model_usage_samples", "model_limit_snapshots",
                  "model_availability_events", "model_usage_alerts",
                  "model_routing_decisions", "schema_migrations"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in service


def test_idempotency_and_dedup_uniques_are_present():
    service = _extract_service_ddl()
    # every idempotency/dedup key is a UNIQUE column so a repeat is a real no-op
    assert service.count("source_hash         TEXT NOT NULL UNIQUE") >= 1  # samples
    assert "dedup_key  TEXT NOT NULL UNIQUE" in service                    # alerts


def test_migrate_is_additive_and_records_version(tmp_path):
    """migrate() applies the DDL to a real sqlite db and records usage.v1,
    without disturbing a pre-existing (mission-like) table."""
    import sqlite3
    from command_center.usage.ledger_schema import SCHEMA_VERSION, migrate

    db = tmp_path / "ledger.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE missions (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO missions VALUES ('M-1')")
    conn.commit()

    assert migrate(conn) == SCHEMA_VERSION
    # pre-existing table untouched
    assert conn.execute("SELECT id FROM missions").fetchone()[0] == "M-1"
    # usage tables now exist
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"model_usage_samples", "model_limit_snapshots",
            "model_availability_events", "model_usage_alerts",
            "model_routing_decisions"} <= tables
    # version recorded, idempotent re-run is safe
    assert migrate(conn) == SCHEMA_VERSION
    rows = conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=?",
        (SCHEMA_VERSION,)).fetchone()[0]
    assert rows == 1
    conn.close()
