"""Phase 1.1 hardening: honest unknown/subscription cost (never $0.00),
no cross-collector double-counting (only REQUEST_DELTA is additive),
collector checkpoints, and retention pruning.
"""
from __future__ import annotations

from command_center.usage.schemas import (
    Attribution,
    CollectionState,
    CostSource,
    SampleKind,
    UsageSample,
    UsageSource,
    now_iso,
    summarize_cost,
)
from command_center.usage.service import UsageService
from command_center.usage.store import UsageStore


def _sample(rid, kind, hash_parts, *, tokens=0, cost=None,
            cost_source=CostSource.UNKNOWN, obs="2026-07-12T00:00:00+00:00"):
    from command_center.usage.schemas import compute_source_hash
    h = compute_source_hash(*hash_parts)
    return UsageSample(sample_id=f"US-{h[:12]}", runtime_id=rid, source=UsageSource.FAKE,
                       observed_at=obs, ingested_at=obs, source_hash=h,
                       sample_kind=kind, total_tokens=tokens, cost_usd=cost,
                       cost_source=cost_source, attribution=Attribution())


# ── honest cost ─────────────────────────────────────────────────────────────

def test_summarize_cost_all_subscription_is_none_not_zero():
    samples = [
        _sample("r", SampleKind.REQUEST_DELTA, ("a",),
                cost=None, cost_source=CostSource.SUBSCRIPTION_NOT_METERED),
        _sample("r", SampleKind.REQUEST_DELTA, ("b",),
                cost=None, cost_source=CostSource.SUBSCRIPTION_NOT_METERED),
    ]
    total, source = summarize_cost(samples)
    assert total is None                                    # NEVER 0.0
    assert source == CostSource.SUBSCRIPTION_NOT_METERED


def test_summarize_cost_all_unknown_is_none():
    samples = [_sample("r", SampleKind.REQUEST_DELTA, ("a",), cost=None)]
    total, source = summarize_cost(samples)
    assert total is None
    assert source == CostSource.UNKNOWN


def test_summarize_cost_mixed_provider_and_estimated():
    samples = [
        _sample("r", SampleKind.REQUEST_DELTA, ("a",), cost=1.0,
                cost_source=CostSource.PROVIDER_REPORTED),
        _sample("r", SampleKind.REQUEST_DELTA, ("b",), cost=0.5,
                cost_source=CostSource.ESTIMATED),
    ]
    total, source = summarize_cost(samples)
    assert total == 1.5
    assert source == CostSource.MIXED


def test_rolled_cost_is_none_for_subscription_usage():
    store = UsageStore()
    store.ingest_sample(_sample("codex", SampleKind.REQUEST_DELTA, ("a",),
                                tokens=1000, cost=None,
                                cost_source=CostSource.SUBSCRIPTION_NOT_METERED))
    svc = UsageService(store, staleness_seconds=1e9)
    rolled = svc.runtime_status("codex").rolled_usage
    assert rolled.total_tokens == 1000       # activity is real
    assert rolled.cost_usd is None           # but the dollar cost is not $0.00
    assert rolled.cost_source == CostSource.SUBSCRIPTION_NOT_METERED


# ── no double-counting ──────────────────────────────────────────────────────

def test_rollup_sums_only_additive_request_deltas():
    """The SAME activity observed as a request_delta AND as a
    provider_window_total must not be summed — only the additive delta
    counts toward the cockpit-attributed roll-up."""
    store = UsageStore()
    store.ingest_sample(_sample("codex", SampleKind.REQUEST_DELTA, ("d",), tokens=100))
    store.ingest_sample(
        _sample("codex", SampleKind.PROVIDER_WINDOW_TOTAL, ("w",), tokens=5000))
    store.ingest_sample(
        _sample("codex", SampleKind.RECONCILIATION_OBSERVATION, ("c",), tokens=4800))
    svc = UsageService(store, staleness_seconds=1e9)
    rolled = svc.runtime_status("codex").rolled_usage
    assert rolled.total_tokens == 100        # NOT 100+5000+4800
    assert rolled.sample_kind == SampleKind.SESSION_TOTAL


def test_rollup_is_none_when_only_non_additive_snapshots_exist():
    store = UsageStore()
    store.ingest_sample(_sample("r", SampleKind.PROVIDER_WINDOW_TOTAL, ("w",), tokens=5000))
    svc = UsageService(store, staleness_seconds=1e9)
    assert svc.runtime_status("r").rolled_usage is None


# ── collector checkpoints ───────────────────────────────────────────────────

def test_collection_state_round_trips_in_memory():
    store = UsageStore()
    assert store.get_collection_state("codex_collector") is None   # never ran
    state = CollectionState(collector_id="codex_collector", updated_at=now_iso(),
                            last_cursor="cursor-42", consecutive_failures=0,
                            auth_state="ok")
    store.set_collection_state(state)
    got = store.get_collection_state("codex_collector")
    assert got.last_cursor == "cursor-42"
    assert got.auth_state == "ok"


# ── retention ───────────────────────────────────────────────────────────────

def test_prune_samples_removes_old_and_keeps_recent():
    store = UsageStore()
    store.ingest_sample(_sample("r", SampleKind.REQUEST_DELTA, ("old",),
                                obs="2020-01-01T00:00:00+00:00"))
    store.ingest_sample(_sample("r", SampleKind.REQUEST_DELTA, ("new",),
                                obs="2026-07-12T00:00:00+00:00"))
    removed = store.prune_samples("2026-01-01T00:00:00+00:00")
    assert removed == 1
    remaining = store.samples_since("r")
    assert [s.observed_at for s in remaining] == ["2026-07-12T00:00:00+00:00"]
    # the pruned hash frees up (a later re-ingest of the same row is allowed)
    reingested = store.ingest_sample(_sample("r", SampleKind.REQUEST_DELTA, ("old",),
                                             obs="2020-01-01T00:00:00+00:00"))
    assert reingested is not None
