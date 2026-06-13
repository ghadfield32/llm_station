"""Judge-calibration tests: confusion-matrix math, the safety-aware promotion gate,
and the anti-self-certification guard."""
from __future__ import annotations

from pathlib import Path

import pytest

from command_center.improvement.calibration import (
    load_cases, score, gate, independence_violation, reference_defensive_judge,
    candidate_defensive_judge, score_predictions, load_predictions,
    CalibrationReport, BLOCK, ALLOW,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES = REPO_ROOT / "data/calibration/judge-calibration.json"


def test_dataset_loads_and_covers_categories():
    cases = load_cases(CASES)
    cats = {c.category for c in cases}
    # the calibration set spans the mission's categories
    for need in ("secret_exposure", "prompt_injection", "scope_creep", "test_weakening",
                 "temporal_leakage", "selective_reporting", "misleading_docs",
                 "reviewer_manipulation", "clean_change", "real_defect"):
        assert need in cats


def test_reference_judge_metrics_are_honest():
    cases = load_cases(CASES)
    rep = score(cases, reference_defensive_judge)
    # the reference judge catches every safety case but misses two subtle defects
    assert rep.safety_missed_defect_rate == 0.0
    assert rep.fn == 2                       # selective-reporting + misleading-docs slip through
    assert rep.fp == 0                       # it does not block clean changes
    assert rep.precision == 1.0
    assert 0.8 < rep.recall < 0.9
    assert rep.missed_defect_rate > 0.0      # honest: it is not perfect


def test_agreement_with_human_gold_kappa():
    cases = load_cases(CASES)
    # the reference judge agrees substantially with the human gold labels (κ in 0.6-0.9)
    ref = score(cases, reference_defensive_judge)
    assert ref.kappa_vs_human is not None and 0.6 <= ref.kappa_vs_human <= 0.9
    # the improved candidate (catches the 2 misses) agrees more
    cand = score(cases, candidate_defensive_judge)
    assert cand.kappa_vs_human > ref.kappa_vs_human
    assert cand.kappa_vs_human == 1.0        # candidate matches every gold label


def test_perfect_judge_promotes_over_reference():
    cases = load_cases(CASES)
    baseline = score(cases, reference_defensive_judge)
    # an oracle that knows the gold labels
    gold = {c.text: c.gold for c in cases}
    candidate = score(cases, lambda t: gold[t])
    decision = gate(baseline, candidate)
    assert decision.promote, decision.reasons


def test_safety_regression_blocks_promotion():
    cases = load_cases(CASES)
    baseline = score(cases, reference_defensive_judge)
    # a candidate that allows everything: misses safety defects -> must be rejected
    candidate = score(cases, lambda t: ALLOW)
    decision = gate(baseline, candidate)
    assert not decision.promote
    assert any("safety" in r for r in decision.reasons)


def test_false_block_regression_blocks_promotion():
    cases = load_cases(CASES)
    baseline = score(cases, reference_defensive_judge)
    # a candidate that blocks everything: catches all defects but false-blocks clean work
    candidate = score(cases, lambda t: BLOCK)
    decision = gate(baseline, candidate)
    assert not decision.promote
    assert any("false-block" in r for r in decision.reasons)


def test_independence_violation_detected():
    cases = load_cases(CASES)
    # the real set is independently labeled (geoff + reviewer2) -> no violation
    assert not independence_violation(cases, "defensive-coding-judge")
    # a set the judge authored AND labeled entirely == self-certification
    from command_center.improvement.calibration import CalibrationCase
    selfmade = [CalibrationCase(id="x", category="real_defect", gold="block", text="t",
                                author="judgeX", labeler="judgeX")]
    assert independence_violation(selfmade, "judgeX")


def test_report_serializable():
    rep = score(load_cases(CASES), reference_defensive_judge)
    assert isinstance(rep, CalibrationReport)
    d = rep.to_dict()
    assert {"precision", "recall", "false_block_rate", "missed_defect_rate",
            "safety_missed_defect_rate", "per_category"} <= set(d)


# ---- live-judge path: score from precomputed predictions -------------------

def test_score_predictions_matches_callable():
    # the live-judge path must agree with the deterministic callable when fed the same verdicts
    cases = load_cases(CASES)
    verdicts = {c.id: candidate_defensive_judge(c.text) for c in cases}
    from_preds = score_predictions(cases, verdicts)
    from_callable = score(cases, candidate_defensive_judge)
    assert from_preds.recall == from_callable.recall
    assert from_preds.tp == from_callable.tp and from_preds.fn == from_callable.fn
    assert from_preds.recall == 1.0          # the candidate ruleset catches every defect


def test_score_predictions_missing_case_raises():
    cases = load_cases(CASES)
    partial = {c.id: BLOCK for c in cases[:-1]}   # drop one
    with pytest.raises(ValueError):
        score_predictions(cases, partial)


def test_confidence_calibration_computed():
    cases = load_cases(CASES)
    verdicts = {c.id: c.gold for c in cases}      # a perfect judge
    # confident when correct (all correct here) -> positive separation
    confidences = {c.id: 0.9 for c in cases}
    rep = score_predictions(cases, verdicts, confidences)
    assert rep.confidence_calibration is not None
    assert rep.confidence_calibration >= 0.0


def test_load_predictions_file(tmp_path):
    import json as _json
    cases = load_cases(CASES)
    payload = {"predictions": {c.id: {"verdict": c.gold, "confidence": 0.8} for c in cases}}
    p = tmp_path / "preds.json"
    p.write_text(_json.dumps(payload), encoding="utf-8")
    verdicts, confidences = load_predictions(p)
    assert len(verdicts) == len(cases) and len(confidences) == len(cases)
    rep = score_predictions(cases, verdicts, confidences)
    assert rep.accuracy == 1.0                    # perfect judge scored from the file
