"""ClaudeRateLimitCollector — hermetic tests. Claude limits are EVENT-DRIVEN, so
the collector is fed RateLimitInfo dicts (as the adapter's `rate_limit` AgentEvent
payload) and returns the latest, or an honest UNKNOWN until one is seen. No SDK,
no network — the collector consumes plain dicts by design.
"""
from __future__ import annotations

import asyncio

from command_center.usage.collectors.claude_agent import (
    CLAUDE_RUNTIME_ID,
    ClaudeRateLimitCollector,
    translate_rate_limit_info,
)
from command_center.usage.schemas import (
    AvailabilityState,
    LimitScope,
    LimitState,
    UsageSource,
)


def _info(**kw):
    base = {"status": "allowed", "rate_limit_type": "five_hour",
            "utilization": 0.4, "resets_at": 1783861277}
    base.update(kw)
    return base


# ── translation ──────────────────────────────────────────────────────────────

def test_translate_allowed_maps_to_available_and_ok_bucket():
    r = translate_rate_limit_info(_info(status="allowed", utilization=0.4), "2026-07-12T00:00:00+00:00")
    assert r.availability[0].state == AvailabilityState.AVAILABLE
    bucket = r.limits[0]
    assert bucket.bucket_id == "five_hour"
    assert bucket.scope == LimitScope.PROVIDER
    assert bucket.source == UsageSource.PROVIDER_NATIVE
    assert bucket.state == LimitState.OK
    assert bucket.used_percent == 40.0          # utilization 0.4 -> 40%
    assert bucket.reset_at == "2026-07-12T13:01:17+00:00"


def test_translate_warning_and_rejected_states():
    warn = translate_rate_limit_info(_info(status="allowed_warning", utilization=0.82), "t")
    assert warn.availability[0].state == AvailabilityState.NEAR_LIMIT
    assert warn.limits[0].state == LimitState.NEAR_LIMIT

    rej = translate_rate_limit_info(
        _info(status="rejected", rate_limit_type="seven_day_opus", utilization=1.0), "t")
    assert rej.availability[0].state == AvailabilityState.EXHAUSTED
    assert rej.limits[0].bucket_id == "seven_day_opus"
    assert rej.limits[0].state == LimitState.EXHAUSTED


def test_translate_emits_a_separate_overage_bucket():
    r = translate_rate_limit_info(
        _info(status="allowed", overage_status="allowed_warning",
              overage_resets_at=1784400188), "t")
    buckets = {b.bucket_id: b for b in r.limits}
    assert set(buckets) == {"five_hour", "overage"}
    assert buckets["overage"].state == LimitState.NEAR_LIMIT


def test_utilization_already_a_percent_is_not_double_scaled():
    # a value >1 is treated as already-a-percent, not multiplied to 6700%
    r = translate_rate_limit_info(_info(utilization=67.0), "t")
    assert r.limits[0].used_percent == 67.0


# ── collector (event-fed) ────────────────────────────────────────────────────

def test_collect_before_any_event_is_honest_unknown():
    r = asyncio.run(ClaudeRateLimitCollector().collect())
    assert r.limits == []
    assert r.availability[0].state == AvailabilityState.UNKNOWN
    assert r.availability[0].runtime_id == CLAUDE_RUNTIME_ID
    assert r.warnings


def test_collect_after_feed_returns_the_latest_translation():
    c = ClaudeRateLimitCollector()
    c.feed(_info(status="allowed_warning", rate_limit_type="seven_day_sonnet",
                 utilization=0.9), observed_at="2026-07-12T00:00:00+00:00")
    r = asyncio.run(c.collect())
    assert r.availability[0].state == AvailabilityState.NEAR_LIMIT
    assert r.limits[0].bucket_id == "seven_day_sonnet"
    assert r.limits[0].used_percent == 90.0


def test_feed_replaces_with_the_newest_state():
    c = ClaudeRateLimitCollector()
    c.feed(_info(status="allowed"))
    c.feed(_info(status="rejected", utilization=1.0))
    r = asyncio.run(c.collect())
    assert r.availability[0].state == AvailabilityState.EXHAUSTED


def test_runtime_ids_and_source():
    c = ClaudeRateLimitCollector()
    assert c.runtime_ids() == [CLAUDE_RUNTIME_ID]
    assert c.source == UsageSource.PROVIDER_NATIVE
