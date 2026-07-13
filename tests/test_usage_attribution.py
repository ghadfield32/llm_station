"""Attribution ranking ("what used the most?") and cross-source
reconciliation — both answer from RECORDED fact, never a guess.
"""
from __future__ import annotations

import pytest

from command_center.usage.attribution import rank_by
from command_center.usage.reconciliation import reconcile
from command_center.usage.schemas import (
    Attribution,
    UsageSample,
    UsageSource,
)


def _s(rid, source, mission=None, repo=None, tokens=0, cost=0.0, cached=0, inp=0):
    return UsageSample(
        sample_id=f"US-{rid}-{mission}-{tokens}", runtime_id=rid, source=source,
        observed_at="2026-07-12T00:00:00+00:00", ingested_at="2026-07-12T00:00:00+00:00",
        source_hash=f"{rid}{mission}{tokens}{cost}", total_tokens=tokens,
        input_tokens=inp, cached_input_tokens=cached, cost_usd=cost,
        attribution=Attribution(mission_id=mission, repo_id=repo))


def test_rank_by_cost_across_missions():
    samples = [
        _s("codex", UsageSource.FAKE, mission="M-1", cost=7.42),
        _s("codex", UsageSource.FAKE, mission="M-2", cost=4.13),
        _s("codex", UsageSource.FAKE, mission="M-1", cost=1.00),
    ]
    rows = rank_by(samples, dimension="mission", metric="cost")
    assert rows[0].key == "M-1"
    assert round(rows[0].metric_value, 2) == 8.42
    assert rows[1].key == "M-2"
    # shares sum to 1 over the full set
    assert round(sum(r.share for r in rows), 6) == 1.0
    assert rows[0].sample_count == 2


def test_rank_by_uncached_input_tokens_is_computed():
    samples = [_s("r", UsageSource.FAKE, mission="M-1", inp=1000, cached=700)]
    rows = rank_by(samples, dimension="mission", metric="uncached_input_tokens")
    assert rows[0].metric_value == 300.0   # 1000 - 700 cached


def test_missing_dimension_rolls_into_explicit_unattributed_bucket():
    samples = [
        _s("r", UsageSource.FAKE, mission="M-1", tokens=100),
        _s("r", UsageSource.FAKE, mission=None, tokens=50),   # no mission
    ]
    rows = {r.key: r for r in rank_by(samples, dimension="mission", metric="total_tokens")}
    assert "(unattributed)" in rows        # never dropped, never guessed
    assert rows["(unattributed)"].metric_value == 50.0


def test_rank_by_rejects_unknown_dimension_or_metric():
    with pytest.raises(ValueError, match="dimension"):
        rank_by([], dimension="nope", metric="cost")
    with pytest.raises(ValueError, match="metric"):
        rank_by([], dimension="mission", metric="nope")


def test_reconcile_flags_a_provider_vs_reconciler_gap():
    samples = [
        _s("codex", UsageSource.PROVIDER_NATIVE, tokens=1000),
        _s("codex", UsageSource.RECONCILER, tokens=600),
    ]
    mismatches = reconcile(samples, runtime_id="codex", metric="total_tokens")
    assert len(mismatches) == 1
    m = mismatches[0]
    # provider_native is the higher-authority side
    assert m.authoritative_source == "provider_native"
    assert m.authoritative_value == 1000
    assert m.other_source == "reconciler"
    assert m.difference == 400
    assert "outside the metered surfaces" in m.note


def test_reconcile_within_tolerance_is_no_mismatch():
    samples = [
        _s("r", UsageSource.PROVIDER_NATIVE, tokens=1000),
        _s("r", UsageSource.RECONCILER, tokens=995),
    ]
    assert reconcile(samples, runtime_id="r", tolerance=10) == []
