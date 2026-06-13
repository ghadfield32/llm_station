"""Phase-5 drift + canary tests. PSI/KL/JS/KS checked against known/closed-form values;
the canary analysis flags champion-vs-challenger regressions (and forces on safety)."""
from __future__ import annotations

import math

import pytest

from command_center.improvement.drift import (
    psi, psi_label, kl_divergence, js_divergence, ks_statistic, drift_report,
    evaluate_canary, ramp_schedule,
)


# ---- PSI --------------------------------------------------------------------

def test_psi_zero_for_identical_distribution():
    xs = list(range(100))
    assert psi(xs, xs, bins=10) < 0.01
    assert psi_label(psi(xs, xs)) == "stable"


def test_psi_flags_a_shift():
    baseline = [float(i) for i in range(100)]
    shifted = [float(i) + 50 for i in range(100)]
    val = psi(baseline, shifted, bins=10)
    assert val > 0.2 and psi_label(val) == "significant"


def test_psi_rejects_too_few_bins():
    with pytest.raises(ValueError):
        psi([1.0, 2.0], [1.0], bins=10)


# ---- KL / JS ----------------------------------------------------------------

def test_kl_zero_and_asymmetric():
    p = [0.5, 0.5]
    assert kl_divergence(p, p) == 0.0
    q = [0.9, 0.1]
    assert kl_divergence(p, q) > 0
    assert kl_divergence(p, q) != kl_divergence(q, p)        # asymmetric


def test_js_symmetric_and_bounded():
    p, q = [0.7, 0.3], [0.2, 0.8]
    assert abs(js_divergence(p, q) - js_divergence(q, p)) < 1e-12   # symmetric
    assert 0.0 <= js_divergence(p, q) <= math.log(2) + 1e-12        # bounded by ln 2
    assert js_divergence(p, p) == 0.0


# ---- KS ---------------------------------------------------------------------

def test_ks_statistic_bounds():
    assert ks_statistic([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 0.0
    assert ks_statistic([1, 2, 3], [10, 11, 12]) == 1.0     # fully separated
    mid = ks_statistic([1, 2, 3, 4], [3, 4, 5, 6])
    assert 0.0 < mid < 1.0


def test_drift_report_flags():
    base = [float(i) for i in range(100)]
    drifted = drift_report(base, [x + 50 for x in base])
    assert drifted.drifted and drifted.psi_label == "significant"
    stable = drift_report(base, base)
    assert not stable.drifted


# ---- canary analysis --------------------------------------------------------

SPECS = [
    {"name": "recall", "direction": "increase", "required": True, "maximum_regression": 0.0},
    {"name": "secret", "direction": "increase", "safety": True, "maximum_regression": 0.0},
    {"name": "latency", "direction": "decrease", "maximum_regression": 0.5},
]


def test_canary_clean_no_regression():
    v = evaluate_canary({"recall": 0.8, "secret": 1.0, "latency": 5.0},
                        {"recall": 0.82, "secret": 1.0, "latency": 5.2}, SPECS)
    assert not v.regression and v.reasons == []


def test_canary_metric_regression_detected():
    v = evaluate_canary({"recall": 0.8, "secret": 1.0, "latency": 5.0},
                        {"recall": 0.70, "secret": 1.0, "latency": 5.0}, SPECS)
    assert v.regression and any("recall" in r for r in v.reasons)


def test_canary_safety_regression_forces_rollback():
    v = evaluate_canary({"recall": 0.8, "secret": 1.0, "latency": 5.0},
                        {"recall": 0.8, "secret": 0.9, "latency": 5.0}, SPECS)
    assert v.regression and any("SAFETY" in r for r in v.reasons)


# ---- ramp -------------------------------------------------------------------

def test_ramp_schedule_default_and_validation():
    assert ramp_schedule() == [5, 20, 50, 100]
    assert ramp_schedule([10, 100]) == [10, 100]
    with pytest.raises(ValueError):
        ramp_schedule([50, 20, 100])        # not increasing
    with pytest.raises(ValueError):
        ramp_schedule([5, 20, 50])          # must end at 100


# ---- integration: metrics-driven canary auto-rollback ----------------------

def test_promotion_controller_metrics_canary_rolls_back(tmp_path):
    import copy
    import yaml
    from pathlib import Path
    from command_center.improvement.schema import ExperimentDefinition
    from command_center.improvement.registry import ExperimentRegistry
    from command_center.improvement.promotion import PromotionController, RetrievalPromotionAdapter
    from command_center.improvement.events import EventRecord, ExperimentEventType
    from command_center.improvement.lifecycle import Actor, ExperimentStatus as S

    repo = Path(__file__).resolve().parents[1]
    raw = copy.deepcopy(
        yaml.safe_load((repo / "configs/improvement.yaml").read_text(encoding="utf-8"))["experiments"][0])
    raw["experiment_id"] = "EXP-canary-metrics"
    defn = ExperimentDefinition.model_validate(raw)
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    reg.register(defn)
    eid = defn.experiment_id

    # drive to Canary through the registry (no harness/corpus needed)
    reg.append_event(EventRecord(kind=ExperimentEventType.CANDIDATE_COMPLETED.value,
                                 experiment_id=eid, action="x"))
    reg.set_verifier_verdict(eid, "PASS", detail={"independent": True})
    reg.set_rollback_status(eid, "demonstrated")
    reg.set_status(eid, S.BASELINE_READY, actor=Actor.AGENT)
    reg.set_status(eid, S.RUNNING, actor=Actor.AGENT)
    reg.set_status(eid, S.AWAITING_VERIFICATION, actor=Actor.AGENT)
    reg.set_status(eid, S.VERIFIED, actor=Actor.AGENT)
    reg.set_status(eid, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT,
                   conditions=reg.promotion_conditions(eid))
    reg.set_status(eid, S.CANARY, actor=Actor.HUMAN,
                   conditions=reg.promotion_conditions(eid, human_approval=True))

    ctrl = PromotionController(reg, adapter=RetrievalPromotionAdapter(state_dir=str(tmp_path / "a")))
    # a safety regression in the canary (secret_exclusion drops) -> auto-rollback
    out = ctrl.evaluate_canary_metrics(
        eid,
        active={"recall_at_5": 0.8, "secret_exclusion": 1.0},
        canary={"recall_at_5": 0.8, "secret_exclusion": 0.9})
    assert out["action"] == "auto_rolled_back"
    assert out["canary_verdict"]["regression"]
    assert reg.get(eid)["status"] == "Rolled Back"
