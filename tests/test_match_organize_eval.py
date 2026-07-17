"""Match & Organize KPI leaderboard regression: the candidate hybrid engine
must Pareto-dominate the exact-title baseline on the labeled REAL cases from
the 2026-07-16 import, without regressing the hard safety invariants.

No invented promotion threshold: assertions pin the baseline comparison and
the structural safety facts, not an arbitrary composite score.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "eval_match_organize_under_test", ROOT / "scripts" /
    "eval_match_organize.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["eval_match_organize_under_test"] = mod
spec.loader.exec_module(mod)


def test_candidate_pareto_dominates_baseline():
    result = mod.evaluate()
    base = result["kpis"]["baseline"]
    cand = result["kpis"]["candidate"]
    # exact recall must never regress from the baseline's 1.0
    assert cand["exact_recall"]["value"] == 1.0
    # the headline win: paraphrases the baseline entirely missed
    assert base["paraphrase_recall"]["value"] == 0.0
    assert cand["paraphrase_recall"]["value"] >= 0.85
    # repeated progress and expansions are new capabilities
    assert cand["occurrence_vs_new_task_accuracy"]["value"] == 1.0
    assert cand["expansion_classification_accuracy"]["value"] == 1.0
    # negatives must never read as same work
    assert cand["negative_safety"]["value"] == 1.0


def test_hard_safety_invariants_hold():
    result = mod.evaluate()
    for engine in ("baseline", "candidate"):
        kpis = result["kpis"][engine]
        assert kpis["false_automatic_merges"]["value"] == 0
        assert kpis["silent_discarded_captures"]["value"] == 0
        assert kpis["source_data_loss"]["value"] == 0
    assert result["dependency_false_positives"] == []


def test_known_misses_are_documented_not_hidden():
    """The two honest candidate misses stay visible until a semantic stage
    or a deliberate rule change closes them — this test forces the eval to
    keep REPORTING them rather than quietly reclassifying."""
    result = mod.evaluate()
    miss_ids = {m["id"] for m in result["misses"]["candidate"]}
    assert miss_ids == {"recaulk-tub", "camera-research-buy"}
