"""Guard: the Ledger service's inlined Readiness Packet DDL must not drift from
the canonical schema in command_center.work_graph.packet_ledger_schema.

Mirrors tests/test_work_graph_ledger_schema.py, for the packet tables. Reads the
service source as text (does NOT import app.py, which would open a real DB at
import time). Also asserts the packet.v1 migration version is recorded — a gap the
work-graph drift test leaves open.
"""
from __future__ import annotations

import re
from pathlib import Path

from command_center.work_graph.packet_ledger_schema import (
    PACKET_SCHEMA_SQL,
    SCHEMA_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"

_PACKET_TABLES = (
    "readiness_packets",
    "packet_revisions",
    "packet_reviews",
    "packet_events",
    "packet_work_links",
)


def _service_text() -> str:
    return LEDGER_APP.read_text(encoding="utf-8")


def _extract_service_ddl() -> str:
    m = re.search(r'PACKET_SCHEMA_SQL\s*=\s*"""(.*?)"""', _service_text(), re.DOTALL)
    assert m, "PACKET_SCHEMA_SQL constant not found in services/ledger/app.py"
    return m.group(1)


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", "", sql)


def test_ledger_service_packet_ddl_matches_canonical():
    assert _normalize(PACKET_SCHEMA_SQL) == _normalize(_extract_service_ddl()), (
        "services/ledger/app.py PACKET_SCHEMA_SQL has drifted from "
        "command_center.work_graph.packet_ledger_schema.PACKET_SCHEMA_SQL — "
        "keep them identical"
    )


def test_all_packet_tables_present_in_service():
    service = _extract_service_ddl()
    for table in _PACKET_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in service


def test_service_records_packet_schema_version():
    # init_db must record the packet.v1 migration, not silently skip it.
    assert SCHEMA_VERSION == "packet.v1"
    assert f'"{SCHEMA_VERSION}", _now()' in _service_text() or \
        f"'{SCHEMA_VERSION}', _now()" in _service_text(), (
        "services/ledger/app.py init_db does not record the "
        f"{SCHEMA_VERSION} schema_migrations version"
    )


def test_canonical_migrate_is_idempotent(tmp_path):
    import sqlite3

    from command_center.work_graph.packet_ledger_schema import migrate

    db = tmp_path / "ledger.db"
    conn = sqlite3.connect(db)
    try:
        assert migrate(conn) == "packet.v1"
        migrate(conn)  # second apply must not raise (IF NOT EXISTS / OR IGNORE)
        rows = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in _PACKET_TABLES:
            assert table in rows
        versions = {r[0] for r in conn.execute(
            "SELECT version FROM schema_migrations")}
        assert "packet.v1" in versions
    finally:
        conn.close()
