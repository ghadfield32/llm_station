"""LedgerUsageStore must be interchangeable with the in-memory UsageStore —
same UsageService, same FakeCollector, backed by a real (test) Ledger
instance instead of a dict. This is the durable-backend proof for "the
UsageStoreProtocol surface stays stable so the service/UI/router never care
which backend they hold" — a real cross-backend run of the same invariants
(idempotency, source-priority, alert dedup, roll-up), not just an assertion.

No Docker: the Ledger FastAPI app is loaded via importlib and driven with
Starlette's TestClient over its ASGI app, exactly like
test_agent_session_ledger_rest.py.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from command_center.usage.collectors.fake import FakeCollector
from command_center.usage.ledger_store import LedgerUsageStore
from command_center.usage.schemas import (
    AvailabilityState,
    LimitScope,
    LimitState,
    LimitSnapshot,
    UsageSource,
    compute_source_hash,
)
from command_center.usage.service import UsageService

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


@pytest.fixture
def ledger_store(tmp_path):
    import os
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location("ledger_app_usage_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    client = TestClient(mod.app)
    return LedgerUsageStore(client)


def _limit(rid, bucket, source, obs, state, pct, parts):
    h = compute_source_hash(*parts)
    return LimitSnapshot(snapshot_id=f"LS-{h[:12]}", runtime_id=rid, bucket_id=bucket,
                         scope=LimitScope.PROVIDER, source=source, state=state,
                         observed_at=obs, ingested_at=obs, source_hash=h,
                         used_percent=pct)


def test_full_pipeline_against_the_real_ledger_backend(ledger_store):
    svc = UsageService(ledger_store, staleness_seconds=1e9)
    fired = asyncio.run(svc.run_collector(
        FakeCollector("codex_agent", primary_used_percent=92.0, budget_used_percent=15.0,
                      availability=AvailabilityState.NEAR_LIMIT)))
    assert "limit_critical" in {a.kind.value for a in fired}

    st = svc.runtime_status("codex_agent")
    assert st.availability == AvailabilityState.NEAR_LIMIT
    buckets = {lim.bucket_id: lim for lim in st.limits}
    assert set(buckets) == {"primary", "monthly_budget"}   # kept separate, durably
    assert buckets["primary"].scope == LimitScope.PROVIDER
    assert buckets["monthly_budget"].scope == LimitScope.INTERNAL_BUDGET
    assert st.rolled_usage.total_tokens == 1000


def test_idempotent_and_alert_dedup_against_ledger(ledger_store):
    svc = UsageService(ledger_store, staleness_seconds=1e9)
    collector = FakeCollector("r", primary_used_percent=95.0)
    first = asyncio.run(svc.run_collector(collector))
    second = asyncio.run(svc.run_collector(collector))   # identical source_hashes
    assert first
    assert second == []   # server-side UNIQUE constraints + dedup_key held
    assert len(ledger_store.samples_since("r")) == 1
    assert len(ledger_store.list_alerts("r")) == 1


def test_source_priority_holds_on_the_ledger_backend(ledger_store):
    # estimate is NEWER; must not displace the provider_native value durably
    ledger_store.ingest_limit(_limit("r", "primary", UsageSource.PROVIDER_NATIVE,
                                      "2026-07-12T00:00:00+00:00", LimitState.OK, 40.0, ("p",)))
    ledger_store.ingest_limit(_limit("r", "primary", UsageSource.ESTIMATE,
                                     "2026-07-12T05:00:00+00:00", LimitState.NEAR_LIMIT,
                                     88.0, ("e",)))
    winners = ledger_store.latest_limits("r")
    assert len(winners) == 1
    assert winners[0].source == UsageSource.PROVIDER_NATIVE
    assert winners[0].used_percent == 40.0


def test_availability_and_unknown_round_trip_through_ledger(ledger_store):
    svc = UsageService(ledger_store, staleness_seconds=1e9)
    # an UNKNOWN bucket must round-trip as UNKNOWN (None percent), never 0
    asyncio.run(svc.run_collector(
        FakeCollector("r", primary_used_percent=None, budget_used_percent=None)))
    st = svc.runtime_status("r")
    primary = next(lim for lim in st.limits if lim.bucket_id == "primary")
    assert primary.state == LimitState.UNKNOWN
    assert primary.used_percent is None


def test_restart_recovery_new_store_same_db(tmp_path):
    """A brand-new LedgerUsageStore against the SAME db file recovers every
    row — the durability point of the whole layer."""
    import os
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location("ledger_app_usage_restart", LEDGER_APP)
    from starlette.testclient import TestClient

    mod1 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod1)
    store1 = LedgerUsageStore(TestClient(mod1.app))
    asyncio.run(UsageService(store1).run_collector(FakeCollector("r", primary_used_percent=50.0)))

    # simulate a full restart: fresh app import against the same file
    spec2 = importlib.util.spec_from_file_location("ledger_app_usage_restart2", LEDGER_APP)
    mod2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod2)
    store2 = LedgerUsageStore(TestClient(mod2.app))
    st = UsageService(store2).runtime_status("r")
    assert next(lim for lim in st.limits if lim.bucket_id == "primary").used_percent == 50.0
