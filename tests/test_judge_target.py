"""A second target type (`judge`) rides the identical lifecycle (mission §15).

Proves the loop generalizes beyond `retrieval`: the same registry, runner, independent
verifier, and promotion/canary/rollback machinery, with a judge-specific measurement
harness + promotion adapter — all deterministic on the calibration set.
"""
from __future__ import annotations

import yaml
from pathlib import Path

from command_center.improvement.schema import ImprovementConfig, ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner, HARNESSES, JudgeHarness
from command_center.improvement.verifier import IndependentVerifier
from command_center.improvement.promotion import (
    PromotionController, JudgePromotionAdapter, adapter_for, ADAPTERS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _judge_defn() -> ExperimentDefinition:
    cfg = ImprovementConfig.model_validate(
        yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8")))
    return next(e for e in cfg.experiments if e.experiment_id == "EXP-judge-ruleset-001")


def test_judge_harness_and_adapter_registered():
    assert HARNESSES["command_center.improvement.calibration"] is JudgeHarness
    assert ADAPTERS["judge"] is JudgePromotionAdapter
    assert adapter_for(_judge_defn()).target_type == "judge"


def test_judge_candidate_improves_without_safety_regression(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    defn = _judge_defn()
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    cmp = runner.run_candidate(defn.experiment_id, reps=1)
    recall = next(m for m in cmp.metrics if m.name == "recall")
    safety = next(m for m in cmp.metrics if m.name == "safety_missed_defect_rate")
    assert recall.candidate_value > recall.baseline_value     # caught the missed defects
    assert safety.candidate_value <= safety.baseline_value     # safety did not regress
    assert cmp.all_required_pass and cmp.safety_ok
    assert cmp.recommendation == "promote"


def test_judge_full_lifecycle_to_promoted(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    defn = _judge_defn()
    eid = defn.experiment_id
    reg.register(defn, mission_id="T-judge")
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(eid, reps=1)
    runner.run_candidate(eid, reps=1)
    rep = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev")).verify(
        eid, verifier_identity="verifier:det", implementer_identity="runner")
    assert rep.verdict == "PASS"
    # sealed-suite criteria are not applicable to this target — and that is honest, not a pass
    nas = [c.id for c in rep.criteria if c.result == "NOT_APPLICABLE"]
    assert "C5" in nas and "C6" in nas
    ctrl = PromotionController(reg, adapter=JudgePromotionAdapter(state_dir=str(tmp_path / "a")))
    ctrl.request_human_promotion(eid)
    before = ctrl._get_adapter(defn).active_version()
    ctrl.start_canary(eid, approver="geoff")
    ctrl.evaluate_canary(eid, regression_detected=False)
    ctrl.promote(eid, approver="geoff")
    assert reg.get(eid)["status"] == "Promoted"
    assert ctrl._get_adapter(defn).active_version() != before  # active ruleset switched


def test_judge_canary_regression_rolls_back(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    defn = _judge_defn()
    eid = defn.experiment_id
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(eid, reps=1)
    runner.run_candidate(eid, reps=1)
    IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev")).verify(
        eid, verifier_identity="verifier:det", implementer_identity="runner")
    ctrl = PromotionController(reg, adapter=JudgePromotionAdapter(state_dir=str(tmp_path / "a")))
    ctrl.request_human_promotion(eid)
    ctrl.start_canary(eid, approver="geoff")
    out = ctrl.evaluate_canary(eid, regression_detected=True, detail="false_block_rate rose")
    assert out["action"] == "auto_rolled_back"
    assert reg.get(eid)["status"] == "Rolled Back"
