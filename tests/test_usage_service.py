"""UsageService: collector ingest → deduplicated alert firing → roll-up into
a RuntimeUsageStatus. Covers the alert threshold matrix (incl. never
alerting on UNKNOWN), idempotent re-runs, honest staleness, and availability
transitions — driven by the deterministic FakeCollector.
"""
from __future__ import annotations

import asyncio

from command_center.usage.alerts import AlertThresholds
from command_center.usage.collectors.fake import FakeCollector
from command_center.usage.schemas import AvailabilityState, LimitState, now_iso
from command_center.usage.service import UsageService
from command_center.usage.store import UsageStore


def test_critical_alert_fires_for_a_bucket_over_the_critical_threshold():
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=1e9)
    fired = asyncio.run(svc.run_collector(
        FakeCollector("codex_agent", primary_used_percent=92.0, budget_used_percent=10.0)))
    kinds = {a.kind.value for a in fired}
    assert "limit_critical" in kinds
    assert not any(a.subject_id == "monthly_budget" for a in fired)   # 10% budget: no alert


def test_warning_alert_fires_between_warning_and_critical():
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=1e9)
    fired = asyncio.run(svc.run_collector(
        FakeCollector("r", primary_used_percent=78.0, budget_used_percent=0.0)))
    assert {a.kind.value for a in fired} & {"limit_warning"}
    assert "limit_critical" not in {a.kind.value for a in fired}


def test_no_alert_when_bucket_is_unknown():
    """You cannot warn on a quota the provider never reported."""
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=1e9)
    fired = asyncio.run(svc.run_collector(
        FakeCollector("r", primary_used_percent=None, budget_used_percent=None,
                      availability=AvailabilityState.AVAILABLE)))
    assert not any(a.kind.value in ("limit_warning", "limit_critical") for a in fired)
    st = svc.runtime_status("r")
    primary = next(lim for lim in st.limits if lim.bucket_id == "primary")
    assert primary.state == LimitState.UNKNOWN
    assert primary.used_percent is None   # never coerced to 0


def test_reingest_is_idempotent_and_alerts_dedup():
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=1e9)
    collector = FakeCollector("r", primary_used_percent=95.0)
    first = asyncio.run(svc.run_collector(collector))
    second = asyncio.run(svc.run_collector(collector))   # same source_hashes
    assert first          # fired the first time
    assert second == []   # nothing new — idempotent ingest + alert dedup


def test_status_flags_staleness_honestly():
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=0.0)   # everything older than 0s is stale
    asyncio.run(svc.run_collector(
        FakeCollector("r", observed_at="2000-01-01T00:00:00+00:00")))
    st = svc.runtime_status("r")
    assert st.stale is True   # visibly stale, value still shown


def test_status_is_fresh_when_recent():
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=1e9)
    asyncio.run(svc.run_collector(FakeCollector("r", observed_at=now_iso())))
    assert svc.runtime_status("r").stale is False


def test_rolled_usage_sums_samples():
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=1e9)
    asyncio.run(svc.run_collector(
        FakeCollector("r", observed_at="2026-07-12T00:00:00+00:00",
                      total_tokens=100, cost_usd=0.01)))
    asyncio.run(svc.run_collector(
        FakeCollector("r", observed_at="2026-07-12T01:00:00+00:00",
                      total_tokens=250, cost_usd=0.03)))
    rolled = svc.runtime_status("r").rolled_usage
    assert rolled.total_tokens == 350
    assert rolled.cost_usd == 0.04


def test_unknown_availability_when_no_signal():
    store = UsageStore()
    svc = UsageService(store)
    st = svc.runtime_status("never-seen")
    assert st.availability == AvailabilityState.UNKNOWN   # never "available" by default


def test_availability_change_fires_an_alert():
    store = UsageStore()
    svc = UsageService(store, staleness_seconds=1e9)
    asyncio.run(svc.run_collector(
        FakeCollector("r", observed_at="2026-07-12T00:00:00+00:00",
                      availability=AvailabilityState.AVAILABLE)))
    fired = asyncio.run(svc.run_collector(
        FakeCollector("r", observed_at="2026-07-12T01:00:00+00:00",
                      availability=AvailabilityState.EXHAUSTED,
                      availability_reason="primary window exhausted")))
    assert any(a.kind.value == "availability_changed" for a in fired)


def test_custom_thresholds_are_honored():
    store = UsageStore()
    svc = UsageService(store, thresholds=AlertThresholds(warning_percent=50, critical_percent=60),
                       staleness_seconds=1e9)
    fired = asyncio.run(svc.run_collector(
        FakeCollector("r", primary_used_percent=55.0, budget_used_percent=0.0)))
    assert "limit_warning" in {a.kind.value for a in fired}   # 55% > custom warning 50
