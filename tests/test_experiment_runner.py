"""Runner tests: metric comparison, budgets, stopping rules, equivalence, evidence.

The stub harness drives the control-flow cases deterministically; one integration
test exercises the real retrieval A/B over the repo to prove the candidate actually
improves recall while safety holds.
"""
from __future__ import annotations

import copy

import pytest
import yaml
from pathlib import Path

from command_center.improvement.schema import ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import (
    ExperimentRunner, Harness, MeasureResult, compare_metrics,
    EquivalenceError, BudgetExhausted, RetrievalHarness,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _defn() -> ExperimentDefinition:
    data = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
    return ExperimentDefinition.model_validate(data["experiments"][0])


class StubHarness(Harness):
    def __init__(self, baseline_vals: dict, candidate_vals: dict):
        self.baseline_vals = baseline_vals
        self.candidate_vals = candidate_vals
        self.eq = {"corpus_hash": "C", "gold_set_hash": "G", "commit": "abc"}

    def equivalence_key(self):
        return dict(self.eq)

    def measure(self, role, reps):
        vals = self.baseline_vals if role == "baseline" else self.candidate_vals
        return MeasureResult(metric_values=dict(vals), raw_log=f"role={role}",
                             sample_count=reps, failures=[])


def _registry(tmp_path) -> ExperimentRegistry:
    return ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))


def _all_good_candidate() -> dict:
    # beats baseline on recall, holds safety, modest efficiency cost
    return {"recall_at_5": 0.8, "bytes_read_proxy": 600.0,
            "query_latency_ms": 6.0, "secret_exclusion": 1.0}


def _baseline_vals() -> dict:
    return {"recall_at_5": 0.5, "bytes_read_proxy": 500.0,
            "query_latency_ms": 5.0, "secret_exclusion": 1.0}


# ---- comparison logic -------------------------------------------------------

def test_compare_promote_when_required_and_safety_pass():
    defn = _defn()
    cmp = compare_metrics(defn, _baseline_vals(), _all_good_candidate())
    assert cmp.all_required_pass and cmp.safety_ok
    assert cmp.recommendation == "promote"


def test_compare_reject_on_safety_regression():
    defn = _defn()
    cand = _all_good_candidate()
    cand["secret_exclusion"] = 0.8           # a secret leaked
    cmp = compare_metrics(defn, _baseline_vals(), cand)
    assert not cmp.safety_ok
    assert cmp.recommendation == "reject"
    leaked = next(m for m in cmp.metrics if m.name == "secret_exclusion")
    assert not leaked.passed and "SAFETY" in leaked.reason


def test_compare_revise_when_required_misses_but_safety_ok():
    defn = _defn()
    cand = _all_good_candidate()
    cand["recall_at_5"] = 0.50               # no improvement over baseline 0.50
    cmp = compare_metrics(defn, _baseline_vals(), cand)
    assert cmp.safety_ok and not cmp.all_required_pass
    assert cmp.recommendation == "revise"


def test_compare_revise_when_required_metrics_only_tie():
    raw = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
    exp = copy.deepcopy(raw["experiments"][0])
    exp["experiment_id"] = "EXP-tie-is-not-promotion"
    for metric in exp["metrics"]:
        if metric["name"] == "recall_at_5":
            metric["minimum_improvement"] = 0.0
            metric["maximum_regression"] = 0.0
    defn = ExperimentDefinition.model_validate(exp)

    cmp = compare_metrics(defn, _baseline_vals(), dict(_baseline_vals()))

    assert cmp.safety_ok and cmp.all_required_pass
    assert cmp.recommendation == "revise"
    assert cmp.note == "no required non-safety metric improved"


# ---- full baseline -> candidate via stub ------------------------------------

def test_runner_records_runs_events_and_evidence(tmp_path):
    reg = _registry(tmp_path)
    defn = _defn()
    reg.register(defn)
    harness = StubHarness(_baseline_vals(), _all_good_candidate())
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT),
                              evidence_root=str(tmp_path / "ev"), harness_override=harness)
    runner.run_baseline(defn.experiment_id, reps=2)
    assert reg.baseline_locked(defn.experiment_id)
    cmp = runner.run_candidate(defn.experiment_id, reps=2)
    assert cmp.recommendation == "promote"
    # implementer/runner hands off but never self-verifies: lands at Awaiting Verification
    assert reg.get(defn.experiment_id)["status"] == "Awaiting Verification"
    kinds = [e["kind"] for e in reg.events(defn.experiment_id)]
    for need in ("BASELINE_STARTED", "BASELINE_COMPLETED", "CANDIDATE_STARTED",
                 "CANDIDATE_COMPLETED", "VERIFICATION_REQUESTED"):
        assert need in kinds
    # raw evidence retained + hashed
    arts = reg.artifacts(defn.experiment_id)
    assert {a["kind"] for a in arts} >= {"stdout", "metrics", "equivalence"}
    assert all(a["sha256"] and a["bytes"] for a in arts)


# ---- equivalence guard ------------------------------------------------------

def test_equivalence_loss_fails_loudly(tmp_path):
    reg = _registry(tmp_path)
    defn = _defn()
    reg.register(defn)
    harness = StubHarness(_baseline_vals(), _all_good_candidate())
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT),
                              evidence_root=str(tmp_path / "ev"), harness_override=harness)
    runner.run_baseline(defn.experiment_id, reps=1)
    harness.eq["corpus_hash"] = "DIFFERENT"   # the basis changed under us
    with pytest.raises(EquivalenceError):
        runner.run_candidate(defn.experiment_id, reps=1)
    # an excluded run is recorded with the exact reason — not silently dropped
    excluded = [r for r in reg.runs(defn.experiment_id, role="candidate")
                if r["status"] == "excluded"]
    assert excluded and "equivalence" in excluded[0]["excluded_reason"]
    assert reg.get(defn.experiment_id)["status"] == "Inconclusive"


# ---- budgets + stopping rules ----------------------------------------------

def test_iteration_budget_exhaustion(tmp_path):
    reg = _registry(tmp_path)
    defn_raw = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
    one = copy.deepcopy(defn_raw["experiments"][0])
    one["experiment_id"] = "EXP-budget-001"
    one["budgets"]["max_iterations"] = 1
    defn = ExperimentDefinition.model_validate(one)
    reg.register(defn)
    harness = StubHarness(_baseline_vals(), _all_good_candidate())
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT),
                              evidence_root=str(tmp_path / "ev"), harness_override=harness)
    runner.run_baseline(defn.experiment_id, reps=1)
    runner.run_candidate(defn.experiment_id, reps=1)        # iteration 1 ok
    with pytest.raises(BudgetExhausted):
        runner.run_candidate(defn.experiment_id, reps=1)    # iteration 2 over budget
    kinds = [e["kind"] for e in reg.events(defn.experiment_id)]
    assert "BUDGET_EXHAUSTED" in kinds
    assert reg.get(defn.experiment_id)["status"] == "Inconclusive"


def test_no_material_improvement_stops(tmp_path):
    reg = _registry(tmp_path)
    defn = _defn()
    reg.register(defn)
    flat = dict(_baseline_vals())            # candidate identical to baseline -> no improvement
    harness = StubHarness(_baseline_vals(), flat)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT),
                              evidence_root=str(tmp_path / "ev"), harness_override=harness)
    runner.run_baseline(defn.experiment_id, reps=1)
    runner.run_candidate(defn.experiment_id, reps=1)        # iter 1: no improvement
    cmp2 = runner.run_candidate(defn.experiment_id, reps=1)  # iter 2: stop
    assert "no material improvement" in cmp2.note
    assert reg.get(defn.experiment_id)["status"] == "Inconclusive"


# ---- real retrieval integration --------------------------------------------

def test_real_retrieval_candidate_beats_baseline(tmp_path):
    reg = _registry(tmp_path)
    defn = _defn()
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT),
                              evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    cmp = runner.run_candidate(defn.experiment_id, reps=1)
    recall = next(m for m in cmp.metrics if m.name == "recall_at_5")
    secret = next(m for m in cmp.metrics if m.name == "secret_exclusion")
    assert recall.candidate_value > recall.baseline_value     # ranked beats literal
    assert recall.candidate_value >= 0.5
    assert secret.candidate_value == 1.0 and secret.passed     # no secret ever surfaced
    assert cmp.safety_ok and cmp.all_required_pass


def test_retrieval_harness_excludes_secrets_directly():
    h = RetrievalHarness(REPO_ROOT)
    # the adversarial bait query must never return a secret file
    mr = h.measure("candidate", 1)
    assert mr.metric_values["secret_exclusion"] == 1.0
    assert not mr.failures
