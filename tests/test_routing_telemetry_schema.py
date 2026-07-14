"""Guard: the Ledger service's inlined routing-telemetry DDL must not drift from
the canonical schema in command_center.work_graph.telemetry_schema.

Mirrors tests/test_work_graph_ledger_schema.py. Reads the service source as text
(does NOT import app.py, which would open a real DB at import time).
"""
from __future__ import annotations

import re
from pathlib import Path

from command_center.work_graph.telemetry_schema import SCHEMA_SQL

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


def _extract_service_ddl() -> str:
    text = LEDGER_APP.read_text(encoding="utf-8")
    m = re.search(r'ROUTING_TELEMETRY_SCHEMA_SQL\s*=\s*"""(.*?)"""', text, re.DOTALL)
    assert m, "ROUTING_TELEMETRY_SCHEMA_SQL not found in services/ledger/app.py"
    return m.group(1)


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", "", sql)


def test_ledger_service_telemetry_ddl_matches_canonical():
    assert _normalize(SCHEMA_SQL) == _normalize(_extract_service_ddl()), (
        "services/ledger/app.py ROUTING_TELEMETRY_SCHEMA_SQL has drifted from "
        "command_center.work_graph.telemetry_schema.SCHEMA_SQL — keep them identical")


def test_routing_corrections_table_present_in_service():
    assert "CREATE TABLE IF NOT EXISTS routing_corrections" in _extract_service_ddl()
