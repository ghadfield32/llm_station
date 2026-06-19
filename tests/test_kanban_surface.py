"""Phase 3: observability metrics + data-derived tuning + the N/N gate.

Hermetic — metrics are computed from synthetic call records, the tuning learner
is exercised on synthetic labelled records (both the abstain and the learn paths),
and the gate runs against the committed config.
"""
from command_center.kanban.digest import render_digest
from command_center.kanban.metrics import compute_metrics
from command_center.kanban.tuning import (
    ResolutionRecord, recommend_fuzzy_ratio, temporal_split)
from command_center.kanban.validate import gate_checks, run_gate
from command_center.schemas import TuningKnobs


def _call(tool, surface="discord", ok=True, ms=10.0, **args):
    return {"ts": "2026-01-01T00:00:00", "surface": surface, "tool": tool,
            "args": args, "ok": ok, "ms": ms}


def test_metrics_empty_is_zero_and_share_none():
    m = compute_metrics([])
    assert m.total_calls == 0 and m.intent_verb_share is None


def test_redundant_rate_counts_consecutive_identical():
    calls = [_call("list_cards"), _call("list_cards"),   # immediate repeat
             _call("stage_card", title="A")]
    m = compute_metrics(calls)
    assert m.redundant_rate == round(1 / 3, 3)


def test_intent_verb_adoption_share():
    calls = [_call("stage_card", title="A"),
             _call("set_status", database="todos", key="x", status="Done")]
    m = compute_metrics(calls)
    assert m.intent_verb_calls == 1 and m.generic_mutator_calls == 1
    assert m.intent_verb_share == 0.5


def test_error_rate_and_per_tool():
    m = compute_metrics([_call("dag_health", ok=False), _call("dag_health")])
    assert m.error_rate == 0.5
    tool = next(t for t in m.per_tool if t["tool"] == "dag_health")
    assert tool["errors"] == 1 and tool["calls"] == 2


def test_tuning_abstains_below_floor():
    res = recommend_fuzzy_ratio([], TuningKnobs(min_decisions=40), current=0.6)
    assert res.source == "config" and res.value == 0.6 and res.n == 0


def test_tuning_learns_when_data_clearly_separable():
    knobs = TuningKnobs(min_decisions=10, min_auc_uplift=0.0)
    recs = [ResolutionRecord(ts=f"2026-01-{i % 28 + 1:02d}T00:00:00",
                             match_ratio=0.9 if i % 2 == 0 else 0.5,
                             correct=(0.9 if i % 2 == 0 else 0.5) >= 0.8)
            for i in range(40)]
    res = recommend_fuzzy_ratio(recs, knobs, current=0.3)   # 0.3 accepts the bad ones
    assert res.source == "learned" and 0.5 < res.value <= 0.9


def test_temporal_split_is_chronological_not_random():
    recs = [ResolutionRecord(ts=f"2026-01-{i:02d}T00:00:00", match_ratio=0.7,
                             correct=True) for i in (3, 1, 4, 2)]
    train, hold = temporal_split(recs, 0.25)
    assert [r.ts[-11:-9] for r in train] == ["01", "02", "03"]
    assert [r.ts[-11:-9] for r in hold] == ["04"]


def test_gate_passes_and_each_check_ok():
    assert run_gate() is True
    assert all(ok for _, ok, _ in gate_checks())


def test_digest_uses_real_counts_and_reports_abstain():
    m = compute_metrics([_call("stage_card", title="A")])
    res = recommend_fuzzy_ratio([], TuningKnobs(min_decisions=40), current=0.6)
    md = render_digest(m, res, generated_at="2026-06-13T00:00:00Z",
                       log_file="x.jsonl")
    assert "Total tool calls: **1**" in md
    assert "config" in md and "0.6" in md
