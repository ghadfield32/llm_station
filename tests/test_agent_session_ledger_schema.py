"""Guard: the Ledger service's inlined agent-session DDL must not drift from the
canonical schema in command_center.agent_sessions.ledger_schema.

Mirrors tests/test_ledger_experiment_schema.py exactly, for the agent-session
tables instead of the experiment registry. It reads the service source as text
(does NOT import app.py, which would open a real DB at import time).
"""
from __future__ import annotations

import re
from pathlib import Path

from command_center.agent_sessions.ledger_schema import SCHEMA_SQL

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


def _extract_service_ddl() -> str:
    text = LEDGER_APP.read_text(encoding="utf-8")
    m = re.search(r'AGENT_SESSION_SCHEMA_SQL\s*=\s*"""(.*?)"""', text, re.DOTALL)
    assert m, "AGENT_SESSION_SCHEMA_SQL constant not found in services/ledger/app.py"
    return m.group(1)


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", "", sql)


def test_ledger_service_ddl_matches_canonical():
    canonical = _normalize(SCHEMA_SQL)
    service = _normalize(_extract_service_ddl())
    assert canonical == service, (
        "services/ledger/app.py AGENT_SESSION_SCHEMA_SQL has drifted from "
        "command_center.agent_sessions.ledger_schema.SCHEMA_SQL — keep them identical"
    )


def test_all_agent_session_tables_present_in_service():
    service = _extract_service_ddl()
    for table in ("agent_sessions", "agent_session_events", "schema_migrations"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in service


def test_agent_session_events_primary_key_prevents_sequence_collision():
    service = _extract_service_ddl()
    assert "PRIMARY KEY (session_id, sequence)" in service
