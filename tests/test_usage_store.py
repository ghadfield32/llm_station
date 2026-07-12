"""In-memory UsageStore behaviours: idempotent ingestion, source-priority
winner selection (an estimate never displaces a provider_native value),
alert dedup, and the query surface. These are the invariants the whole
subsystem rests on.
"""
from __future__ import annotations

from command_center.usage.schemas import (
    AlertKind,
    AvailabilityEvent,
    AvailabilityState,
    LimitScope,
    LimitSnapshot,
    LimitState,
    UsageAlert,
    UsageSample,
    UsageSource,
    compute_source_hash,
)
from command_center.usage.store import UsageStore


def _sample(rid, source, obs, hash_parts, tokens=100):
    h = compute_source_hash(*hash_parts)
    return UsageSample(sample_id=f"US-{h[:12]}", runtime_id=rid, source=source,
                       observed_at=obs, ingested_at=obs, source_hash=h,
                       total_tokens=tokens)


def _limit(rid, bucket, source, obs, state, pct, hash_parts,
           scope=LimitScope.PROVIDER):
    h = compute_source_hash(*hash_parts)
    return LimitSnapshot(snapshot_id=f"LS-{h[:12]}", runtime_id=rid, bucket_id=bucket,
                         scope=scope, source=source, state=state, observed_at=obs,
                         ingested_at=obs, source_hash=h, used_percent=pct)


def _avail(rid, source, obs, state, hash_parts):
    h = compute_source_hash(*hash_parts)
    return AvailabilityEvent(event_id=f"AV-{h[:12]}", runtime_id=rid, source=source,
                             state=state, observed_at=obs, ingested_at=obs, source_hash=h)


def test_ingest_sample_is_idempotent_by_source_hash():
    store = UsageStore()
    s = _sample("r", UsageSource.FAKE, "2026-07-12T00:00:00+00:00", ("a",))
    first = store.ingest_sample(s)
    again = store.ingest_sample(s)   # same source_hash
    assert first is again
    assert len(store.samples_since("r")) == 1   # not duplicated


def test_latest_limits_provider_native_beats_estimate_even_if_newer():
    store = UsageStore()
    # estimate is NEWER but must not win over the provider_native value
    store.ingest_limit(_limit("r", "primary", UsageSource.PROVIDER_NATIVE,
                              "2026-07-12T00:00:00+00:00", LimitState.OK, 40.0, ("p",)))
    store.ingest_limit(_limit("r", "primary", UsageSource.ESTIMATE,
                              "2026-07-12T01:00:00+00:00", LimitState.NEAR_LIMIT, 88.0, ("e",)))
    winners = store.latest_limits("r")
    assert len(winners) == 1
    assert winners[0].source == UsageSource.PROVIDER_NATIVE
    assert winners[0].used_percent == 40.0


def test_latest_limits_newer_wins_within_same_source():
    store = UsageStore()
    store.ingest_limit(_limit("r", "primary", UsageSource.PROVIDER_NATIVE,
                              "2026-07-12T00:00:00+00:00", LimitState.OK, 40.0, ("p1",)))
    store.ingest_limit(_limit("r", "primary", UsageSource.PROVIDER_NATIVE,
                              "2026-07-12T02:00:00+00:00", LimitState.NEAR_LIMIT, 80.0, ("p2",)))
    winners = store.latest_limits("r")
    assert winners[0].used_percent == 80.0   # newest of the same source


def test_latest_limits_keeps_buckets_separate():
    store = UsageStore()
    store.ingest_limit(_limit("r", "primary", UsageSource.FAKE,
                              "2026-07-12T00:00:00+00:00", LimitState.OK, 40.0, ("a",)))
    store.ingest_limit(_limit("r", "weekly", UsageSource.FAKE,
                              "2026-07-12T00:00:00+00:00", LimitState.NEAR_LIMIT, 80.0, ("b",),
                              scope=LimitScope.PROVIDER))
    winners = {w.bucket_id: w for w in store.latest_limits("r")}
    assert set(winners) == {"primary", "weekly"}   # never flattened into one


def test_latest_availability_authority_then_recency():
    store = UsageStore()
    store.ingest_availability(_avail("r", UsageSource.FAKE, "2026-07-12T02:00:00+00:00",
                                     AvailabilityState.AVAILABLE, ("f",)))
    store.ingest_availability(_avail("r", UsageSource.PROVIDER_NATIVE,
                                     "2026-07-12T00:00:00+00:00",
                                     AvailabilityState.LIMITED, ("p",)))
    # provider_native outranks the newer fake
    assert store.latest_availability("r").state == AvailabilityState.LIMITED


def test_record_alert_dedups_by_dedup_key():
    store = UsageStore()
    a = UsageAlert(alert_id="A1", runtime_id="r", kind=AlertKind.LIMIT_WARNING,
                   dedup_key="r|primary|limit_warning|75|reset", created_at="t")
    assert store.record_alert(a) is a
    # same dedup_key -> not re-recorded
    a2 = UsageAlert(alert_id="A2", runtime_id="r", kind=AlertKind.LIMIT_WARNING,
                    dedup_key="r|primary|limit_warning|75|reset", created_at="t2")
    assert store.record_alert(a2) is None
    assert len(store.list_alerts("r")) == 1


def test_samples_since_filters_by_time():
    store = UsageStore()
    store.ingest_sample(_sample("r", UsageSource.FAKE, "2026-07-12T00:00:00+00:00", ("a",)))
    store.ingest_sample(_sample("r", UsageSource.FAKE, "2026-07-12T02:00:00+00:00", ("b",)))
    since = store.samples_since("r", "2026-07-12T01:00:00+00:00")
    assert [s.observed_at for s in since] == ["2026-07-12T02:00:00+00:00"]


def test_list_runtime_ids_unions_all_record_types():
    store = UsageStore()
    store.ingest_sample(_sample("r1", UsageSource.FAKE, "2026-07-12T00:00:00+00:00", ("a",)))
    store.ingest_limit(_limit("r2", "primary", UsageSource.FAKE,
                              "2026-07-12T00:00:00+00:00", LimitState.OK, 10.0, ("b",)))
    store.ingest_availability(_avail("r3", UsageSource.FAKE, "2026-07-12T00:00:00+00:00",
                                     AvailabilityState.AVAILABLE, ("c",)))
    assert store.list_runtime_ids() == ["r1", "r2", "r3"]
