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


def test_collection_state_and_prune_against_ledger(ledger_store):
    from command_center.usage.schemas import CollectionState, now_iso

    assert ledger_store.get_collection_state("codex_collector") is None
    ledger_store.set_collection_state(CollectionState(
        collector_id="codex_collector", updated_at=now_iso(),
        last_cursor="c-7", consecutive_failures=2, auth_state="ok"))
    got = ledger_store.get_collection_state("codex_collector")
    assert got.last_cursor == "c-7"
    assert got.consecutive_failures == 2

    # retention prune round-trips through the Ledger DELETE endpoint
    svc = UsageService(ledger_store, staleness_seconds=1e9)
    asyncio.run(svc.run_collector(
        FakeCollector("r", observed_at="2020-01-01T00:00:00+00:00")))
    removed = ledger_store.prune_samples("2026-01-01T00:00:00+00:00")
    assert removed == 1
    assert ledger_store.samples_since("r") == []


def test_sample_hardening_fields_round_trip_through_ledger(ledger_store):
    """sample_kind + nullable cost + driver facts survive the REST round-trip."""
    from command_center.usage.schemas import (
        Attribution, CostSource, SampleKind, UsageSample, UsageSource, now_iso)
    s = UsageSample(
        sample_id="US-hard", runtime_id="codex", source=UsageSource.PROVIDER_NATIVE,
        observed_at=now_iso(), ingested_at=now_iso(), source_hash="hardhash-1",
        sample_kind=SampleKind.PROVIDER_WINDOW_TOTAL, total_tokens=5000,
        reasoning_tokens=120, cost_usd=None,
        cost_source=CostSource.SUBSCRIPTION_NOT_METERED, repository_scans=3,
        test_runs=2, retries=1, worker_restarts=1,
        attribution=Attribution(mission_id="M-9"))
    ledger_store.ingest_sample(s)
    back = ledger_store.samples_since("codex")[0]
    assert back.sample_kind == SampleKind.PROVIDER_WINDOW_TOTAL
    assert back.cost_usd is None                        # nullable, not 0.0
    assert back.cost_source == CostSource.SUBSCRIPTION_NOT_METERED
    assert back.reasoning_tokens == 120
    assert back.repository_scans == 3 and back.test_runs == 2 and back.retries == 1
    assert back.worker_restarts == 1
    assert back.attribution.mission_id == "M-9"


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
