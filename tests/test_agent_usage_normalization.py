"""Agent `usage` event -> attributed UsageSample normalization: honest
subscription cost, uncached-token math, per-model/per-effort attribution, a
durable Ledger round-trip of the new fields, and the worker-side feed. This is
what powers "what used the most and why?" (top model / top effort / top
uncached-context session).
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from command_center.usage.agent_usage import agent_usage_sample
from command_center.usage.attribution import rank_by
from command_center.usage.ledger_store import LedgerUsageStore
from command_center.usage.schemas import CostSource, SampleKind, UsageSource

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"

# the real claude_code_local `usage` event payload shape
_CLAUDE_USAGE = {
    "cost_usd": None, "cost_source": "subscription_not_metered",
    "api_equivalent_cost_usd": 0.19, "num_turns": 1, "duration_ms": 1350,
    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 18938,
              "cache_read_input_tokens": 100, "output_tokens": 4},
    "model_usage": {}}


# ── translator ───────────────────────────────────────────────────────────────

def test_claude_subscription_usage_is_honest_and_attributed():
    s = agent_usage_sample(_CLAUDE_USAGE, runtime_id="claude_code_local",
                           session_id="sess-1", repo_id="llm_station",
                           model="opus", effort="high",
                           observed_at="2026-07-13T00:00:00+00:00")
    assert s.cost_usd is None                              # subscription: never $0.00
    assert s.cost_source == CostSource.SUBSCRIPTION_NOT_METERED
    assert s.api_equivalent_cost_usd == 0.19               # kept separately
    assert s.sample_kind == SampleKind.REQUEST_DELTA       # additive -> rolls up
    assert s.source == UsageSource.PROVIDER_DERIVED
    assert s.model == "opus" and s.effort == "high"
    assert s.attribution.agent_session_id == "sess-1"
    assert s.attribution.repo_id == "llm_station"
    # input_tokens = uncached(2) + cache_create(18938) + cache_read(100);
    # cached = 19038; so uncached = input - cached = 2
    assert s.input_tokens == 2 + 18938 + 100
    assert s.cached_input_tokens == 18938 + 100
    assert s.output_tokens == 4


def test_api_lane_usage_records_real_cost():
    payload = {"cost_usd": 0.42, "usage": {"input_tokens": 10, "output_tokens": 5}}
    s = agent_usage_sample(payload, runtime_id="claude_agent", model="sonnet")
    assert s.cost_usd == 0.42
    assert s.cost_source == CostSource.PROVIDER_REPORTED


def test_codex_cached_input_is_a_subset_not_added_twice():
    payload = {
        "cost_usd": None,
        "cost_source": "subscription_not_metered",
        "total": {
            "input_tokens": 100,
            "cached_input_tokens": 80,
            "output_tokens": 25,
            "total_tokens": 125,
        },
    }
    sample = agent_usage_sample(payload, runtime_id="codex_agent")
    assert sample.input_tokens == 100
    assert sample.cached_input_tokens == 80
    assert sample.total_tokens == 125
    assert sample.cost_source == CostSource.SUBSCRIPTION_NOT_METERED


# ── per-model / per-effort attribution ───────────────────────────────────────

def test_rank_by_model_and_effort():
    samples = [
        agent_usage_sample({"usage": {"output_tokens": 100}}, runtime_id="r",
                           model="opus", effort="high"),
        agent_usage_sample({"usage": {"output_tokens": 40}}, runtime_id="r",
                           model="sonnet", effort="medium"),
        agent_usage_sample({"usage": {"output_tokens": 60}}, runtime_id="r",
                           model="opus", effort="high"),
    ]
    by_model = rank_by(samples, dimension="model", metric="output_tokens")
    assert by_model[0].key == "opus" and by_model[0].metric_value == 160.0
    by_effort = rank_by(samples, dimension="effort", metric="output_tokens")
    assert {r.key for r in by_effort} == {"high", "medium"}
    with pytest.raises(ValueError):
        rank_by(samples, dimension="nonsense", metric="output_tokens")


# ── durable round-trip of the new fields ─────────────────────────────────────

@pytest.fixture
def ledger_store(tmp_path):
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location("ledger_app_usage_norm_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    return LedgerUsageStore(TestClient(mod.app))


def test_model_effort_and_api_equivalent_cost_survive_the_ledger(ledger_store):
    s = agent_usage_sample(_CLAUDE_USAGE, runtime_id="claude_code_local",
                           session_id="sess-9", model="opus", effort="xhigh")
    ledger_store.ingest_sample(s)
    back = ledger_store.samples_since("claude_code_local")
    assert len(back) == 1
    r = back[0]
    assert r.model == "opus" and r.effort == "xhigh"
    assert r.cost_usd is None
    assert r.api_equivalent_cost_usd == 0.19


# ── worker-side feed ─────────────────────────────────────────────────────────

def test_worker_feeds_a_usage_event_as_a_sample():
    import types

    from command_center.agent_sessions import worker_app as wa
    from command_center.agent_sessions.events import AgentEvent
    from command_center.usage.service import UsageService
    from command_center.usage.store import UsageStore

    usage = UsageService(UsageStore())
    record = types.SimpleNamespace(harness="claude_code_local", session_id="s1",
                                   repo_id="llm_station", conversation_id="c1",
                                   model="opus")
    ev = AgentEvent("usage", dict(_CLAUDE_USAGE))
    ev.ts = "2026-07-13T00:00:00+00:00"
    wa._worker_feed_usage(usage, record, "high", ev)
    samples = usage.store.samples_since("claude_code_local")
    assert len(samples) == 1
    assert samples[0].model == "opus" and samples[0].effort == "high"
    # a non-usage/limit event or a non-agent harness is ignored
    wa._worker_feed_usage(usage, record, "high", AgentEvent("assistant_message", {}))
    assert len(usage.store.samples_since("claude_code_local")) == 1
