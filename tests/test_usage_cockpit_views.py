"""Pure unit tests for the Usage & Limits cockpit view builders
(command_center.usage.cockpit_views) — no FastAPI, no vendor SDK. Seed a
UsageService with the deterministic FakeCollector and assert the exact JSON
shape the cockpit page renders, including the honesty invariants (buckets stay
separate, UNKNOWN stays UNKNOWN, no fabricated data on an unseen runtime).
"""
from __future__ import annotations

import asyncio

from command_center.usage import cockpit_views as cv
from command_center.usage.collectors.fake import FakeCollector
from command_center.usage.service import UsageService
from command_center.usage.store import UsageStore


def _seeded(**kw):
    svc = UsageService(UsageStore())
    asyncio.run(svc.run_collector_tracked(FakeCollector(**kw), "fake"))
    return svc


def test_usage_overview_has_one_row_per_runtime_with_buckets_and_rollup():
    svc = _seeded()
    rows = cv.usage_overview(svc)
    assert len(rows) == 1
    row = rows[0]
    assert row["runtime_id"] == "fake_runtime"
    assert row["availability"] == "available"
    # provider bucket + internal budget kept SEPARATE (never one flattened %)
    assert {lim["bucket_id"] for lim in row["limits"]} == {"primary", "monthly_budget"}
    assert row["rolled_usage"]["total_tokens"] == 1000


def test_limits_overview_tags_each_bucket_with_runtime_availability_and_scope():
    rows = cv.limits_overview(_seeded())
    by_bucket = {r["bucket_id"]: r for r in rows}
    assert by_bucket["primary"]["scope"] == "provider"
    assert by_bucket["monthly_budget"]["scope"] == "internal_budget"
    assert all(r["runtime_availability"] == "available" for r in rows)
    assert all(r["runtime_stale"] is False for r in rows)


def test_runtime_detail_of_unseen_runtime_is_unknown_never_fabricated():
    detail = cv.runtime_detail(_seeded(), "never_seen")
    assert detail["availability"] == "unknown"
    assert detail["limits"] == []
    assert detail["rolled_usage"] is None


def test_top_drivers_rolls_unattributed_samples_into_an_explicit_bucket():
    out = cv.top_drivers(_seeded(), runtime_id="fake_runtime",
                         dimension="mission", metric="total_tokens")
    assert out["dimension"] == "mission" and out["metric"] == "total_tokens"
    # the fake sample carries no mission_id -> explicit "(unattributed)", not dropped
    assert out["rows"][0]["key"] == "(unattributed)"
    assert out["rows"][0]["metric_value"] == 1000.0
    assert out["rows"][0]["share"] == 1.0


def test_top_drivers_excludes_non_additive_snapshots():
    from dataclasses import replace

    from command_center.usage.schemas import SampleKind

    svc = _seeded()
    original = svc.store.samples_since("fake_runtime")[0]
    svc.store.ingest_sample(replace(
        original,
        sample_id="snapshot",
        source_hash="snapshot",
        sample_kind=SampleKind.SESSION_TOTAL,
    ))
    out = cv.top_drivers(
        svc, runtime_id="fake_runtime",
        dimension="mission", metric="total_tokens",
    )
    assert out["rows"][0]["metric_value"] == 1000.0


def test_recent_activity_is_sanitized_and_includes_runtime_kpis():
    from command_center.usage.agent_usage import agent_usage_sample

    svc = UsageService(UsageStore())
    sample = agent_usage_sample(
        {"usage": {"input_tokens": 100, "cached_input_tokens": 80,
                   "output_tokens": 25}, "duration_ms": 2000,
         "cost_source": "subscription_not_metered"},
        runtime_id="codex_agent", repo_id="llm_station",
        conversation_id="private-conversation-id", model="recorded-model",
        effort="high", observed_at="2026-07-16T12:00:00+00:00")
    svc.store.ingest_sample(sample)

    out = cv.recent_activity(svc, runtime_id="codex_agent")
    assert out["rows"][0]["purpose"] == "Repository llm_station"
    assert out["rows"][0]["model"] == "recorded-model"
    assert out["rows"][0]["total_tokens"] == 125
    assert out["kpis"]["average_tokens_per_call"] == 125.0
    assert out["kpis"]["cached_input_share_percent"] == 80.0
    assert out["kpis"]["success_rate_percent"] is None
    assert "private-conversation-id" not in str(out)


def test_codex_rollup_identifies_subscription_for_legacy_rows():
    from command_center.usage.agent_usage import agent_usage_sample

    svc = UsageService(UsageStore())
    svc.store.ingest_sample(agent_usage_sample(
        {"total": {"input_tokens": 10, "output_tokens": 2,
                   "total_tokens": 12}},
        runtime_id="codex_agent",
        observed_at="2026-07-16T12:00:00+00:00",
    ))
    rolled = svc.runtime_status("codex_agent").to_dict()["rolled_usage"]
    assert rolled["cost_usd"] is None
    assert rolled["cost_source"] == "subscription_not_metered"


def test_agent_average_runtime_requires_duration_for_every_call():
    from command_center.usage.agent_usage import agent_usage_sample

    svc = UsageService(UsageStore())
    for index, duration in enumerate((1000, 0)):
        svc.store.ingest_sample(agent_usage_sample(
            {"total": {"input_tokens": 10, "output_tokens": 2,
                       "total_tokens": 12}, "duration_ms": duration},
            runtime_id="codex_agent",
            observed_at=f"2026-07-16T12:00:0{index}+00:00",
        ))
    detail = cv.recent_activity(svc, runtime_id="codex_agent")
    assert detail["kpis"]["average_duration_ms"] is None


def test_collector_health_reports_ran_and_never_ran():
    svc = _seeded()
    health = {h["collector_id"]: h for h in cv.collector_health(svc, ["fake", "ghost"])}
    assert health["fake"]["never_ran"] is False
    assert health["fake"]["auth_state"] == "ok"
    assert health["fake"]["consecutive_failures"] == 0
    assert health["ghost"]["never_ran"] is True


def test_alerts_view_surfaces_a_critical_alert_when_a_bucket_is_hot():
    # a bucket at 92% must produce a critical alert (FakeCollector contract)
    svc = _seeded(primary_used_percent=92.0)
    alerts = cv.alerts_view(svc, "fake_runtime")
    assert alerts, "expected a limit alert for a 92% bucket"
    assert any(a["kind"].startswith("limit_") for a in alerts)


def test_alerts_view_is_empty_when_everything_is_healthy():
    assert cv.alerts_view(_seeded(), "fake_runtime") == []


def test_refresh_runs_every_registered_collector_and_reports_counts():
    svc = UsageService(UsageStore())
    collectors = [(FakeCollector(runtime_id="a"), "ca"),
                  (FakeCollector(runtime_id="b"), "cb")]
    out = asyncio.run(cv.refresh(svc, collectors))
    assert out["collectors_run"] == 2
    assert {r["collector_id"] for r in out["results"]} == {"ca", "cb"}
    # both runtimes are now observable through the same service
    assert {row["runtime_id"] for row in cv.usage_overview(svc)} == {"a", "b"}


def test_refresh_with_no_collectors_is_an_honest_noop():
    out = asyncio.run(cv.refresh(UsageService(UsageStore()), []))
    assert out == {"collectors_run": 0, "results": []}
