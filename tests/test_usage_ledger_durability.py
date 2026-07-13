"""Restart-proof, single-authoritative usage: a rate_limit observation ingested
through ONE Ledger-backed UsageService (the worker) is visible to a SEPARATE,
freshly-constructed Ledger-backed UsageService reading the SAME Ledger (the
cockpit, and equivalently either side after a restart). Proves the "worker owns
ingestion → durable LedgerUsageStore → cockpit reads durable result" wiring is
real, per-lane, and idempotent — not an in-memory illusion.

No Docker: the Ledger FastAPI app is loaded via importlib + Starlette TestClient,
exactly like test_usage_ledger_store.py.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from command_center.usage.collectors.claude_agent import translate_rate_limit_info
from command_center.usage.ledger_store import LedgerUsageStore
from command_center.usage.service import UsageService

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


@pytest.fixture
def ledger_client(tmp_path):
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location("ledger_app_durability_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    return TestClient(mod.app)


_RL = {"status": "allowed_warning", "rate_limit_type": "five_hour",
       "utilization": None, "resets_at": 1783896000}


def test_worker_ingested_claude_limit_is_visible_to_a_fresh_cockpit_service(ledger_client):
    # WORKER side: ingest a live claude_code_local rate_limit into the Ledger.
    worker = UsageService(LedgerUsageStore(ledger_client), staleness_seconds=1e9)
    worker.ingest_collector_result(
        translate_rate_limit_info(_RL, "2026-07-12T00:00:00+00:00", "claude_code_local"))

    # COCKPIT side (and equivalently either process after a restart): a BRAND
    # NEW service over a NEW store against the SAME Ledger still sees it.
    cockpit = UsageService(LedgerUsageStore(ledger_client), staleness_seconds=1e9)
    status = cockpit.runtime_status("claude_code_local")
    assert status.availability.value == "near_limit"
    assert any(lim.bucket_id == "five_hour" for lim in status.limits)
    # the API lane was never fed -> its card is absent, not conflated
    assert "claude_code_local" in cockpit.store.list_runtime_ids()
    assert "claude_agent" not in cockpit.store.list_runtime_ids()


def test_re_ingesting_the_same_event_is_idempotent(ledger_client):
    svc = UsageService(LedgerUsageStore(ledger_client), staleness_seconds=1e9)
    result = translate_rate_limit_info(_RL, "2026-07-12T00:00:00+00:00", "claude_code_local")
    svc.ingest_collector_result(result)
    svc.ingest_collector_result(result)      # tee + worker could both feed the same event
    limits = svc.store.latest_limits("claude_code_local")
    assert len([lim for lim in limits if lim.bucket_id == "five_hour"]) == 1
