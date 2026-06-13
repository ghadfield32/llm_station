"""Guard: the Ledger service's inlined experiment DDL must not drift from the
canonical schema in command_center.improvement.ledger_schema.

The Ledger runs as a standalone container that cannot import command_center, so the
DDL is necessarily duplicated. This test is what keeps the duplication honest — if
the two ever disagree on a table or column, it fails. It reads the service source as
text (it does NOT import app.py, which would open a real DB at import time).
"""
from __future__ import annotations

import re
from pathlib import Path

from command_center.improvement.ledger_schema import SCHEMA_SQL

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


def _extract_service_ddl() -> str:
    text = LEDGER_APP.read_text(encoding="utf-8")
    m = re.search(r'EXPERIMENT_SCHEMA_SQL\s*=\s*"""(.*?)"""', text, re.DOTALL)
    assert m, "EXPERIMENT_SCHEMA_SQL constant not found in services/ledger/app.py"
    return m.group(1)


def _normalize(sql: str) -> str:
    # collapse all whitespace so formatting differences don't count as drift
    return re.sub(r"\s+", "", sql)


def test_ledger_service_ddl_matches_canonical():
    canonical = _normalize(SCHEMA_SQL)
    service = _normalize(_extract_service_ddl())
    assert canonical == service, (
        "services/ledger/app.py EXPERIMENT_SCHEMA_SQL has drifted from "
        "command_center.improvement.ledger_schema.SCHEMA_SQL — keep them identical"
    )


def test_all_experiment_tables_present_in_service():
    service = _extract_service_ddl()
    for table in ("experiments", "experiment_events", "experiment_runs",
                  "experiment_artifacts", "experiment_links", "schema_migrations"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in service


def test_service_status_endpoint_keeps_human_only_wall():
    # the Ledger REST surface must keep Canary/Promoted human-only
    text = LEDGER_APP.read_text(encoding="utf-8")
    assert '_EXP_HUMAN_ONLY = {"Canary", "Promoted"}' in text
    assert "human-only; no self-promotion" in text
