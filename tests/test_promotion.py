"""Promotion / canary / rollback tests — the lifecycle tail.

Prove: rollback is demonstrated before promotion, an agent can't reach Canary/Promoted,
a clean canary lets a human promote (switching the active version), and a canary or
post-watch regression auto-rolls-back only because the target is reversible/local/L2.
"""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path

from command_center.improvement.schema import ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner
from command_center.improvement.verifier import IndependentVerifier
from command_center.improvement.promotion import (
    PromotionController, RetrievalPromotionAdapter,
)
from command_center.improvement.lifecycle import Actor, HumanApprovalRequired, ExperimentStatus

REPO_ROOT = Path(__file__).resolve().parents[1]


def _defn() -> ExperimentDefinition:
    data = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
    return ExperimentDefinition.model_validate(data["experiments"][0])


def _verified(tmp_path):
    """Register -> baseline -> candidate -> independently verify (PASS) -> Verified."""
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    defn = _defn()
    reg.register(defn, mission_id="T-demo")
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    runner.run_candidate(defn.experiment_id, reps=1)
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    ver.verify(defn.experiment_id, verifier_identity="verifier:det", implementer_identity="runner")
    assert reg.get(defn.experiment_id)["status"] == "Verified"
    adapter = RetrievalPromotionAdapter(state_dir=str(tmp_path / "active"))
    return reg, defn, PromotionController(reg, adapter=adapter), adapter


def test_full_promotion_path(tmp_path):
    reg, defn, ctrl, adapter = _verified(tmp_path)
    eid = defn.experiment_id
    # agent requests human promotion (rollback demonstrated first)
    ctrl.request_human_promotion(eid)
    assert reg.get(eid)["status"] == "Awaiting Human Promotion"
    assert reg.get(eid)["rollback_status"] == "demonstrated"
    # human starts canary
    ctrl.start_canary(eid, approver="geoff")
    assert reg.get(eid)["status"] == "Canary"
    # clean canary
    ctrl.evaluate_canary(eid, regression_detected=False)
    assert reg.get(eid)["canary_status"] == "passed"
    # human promotes -> active version switches to the candidate
    before = adapter.active_version()
    ctrl.promote(eid, approver="geoff")
    assert reg.get(eid)["status"] == "Promoted"
    assert adapter.active_version() != before
    # post-watch clean
    assert ctrl.post_watch(eid, checkpoint="1h", regression_detected=False)["action"] == "ok"


def test_rollback_demonstrated_before_promotion(tmp_path):
    reg, defn, ctrl, _ = _verified(tmp_path)
    assert reg.get(defn.experiment_id)["rollback_status"] in (None, "")
    ctrl.request_human_promotion(defn.experiment_id)
    # the controller demonstrated rollback (dry-run) before advancing
    assert reg.get(defn.experiment_id)["rollback_status"] == "demonstrated"


def test_agent_cannot_promote_via_controller_gate(tmp_path):
    # the only promote/canary entrypoints set Actor.HUMAN; prove the underlying
    # lifecycle refuses an agent reaching Canary even with good conditions
    reg, defn, ctrl, _ = _verified(tmp_path)
    ctrl.request_human_promotion(defn.experiment_id)
    cond = reg.promotion_conditions(defn.experiment_id, human_approval=True)
    with pytest.raises(HumanApprovalRequired):
        reg.set_status(defn.experiment_id, ExperimentStatus.CANARY,
                       actor=Actor.AGENT, conditions=cond)


def test_canary_regression_auto_rolls_back(tmp_path):
    reg, defn, ctrl, adapter = _verified(tmp_path)
    eid = defn.experiment_id
    ctrl.request_human_promotion(eid)
    ctrl.start_canary(eid, approver="geoff")
    out = ctrl.evaluate_canary(eid, regression_detected=True, detail="secret_exclusion dropped")
    assert out["action"] == "auto_rolled_back"          # reversible + local + L2
    assert reg.get(eid)["status"] == "Rolled Back"
    assert reg.get(eid)["rollback_status"] == "rolled_back"


def test_post_watch_regression_rolls_back(tmp_path):
    reg, defn, ctrl, adapter = _verified(tmp_path)
    eid = defn.experiment_id
    ctrl.request_human_promotion(eid)
    ctrl.start_canary(eid, approver="geoff")
    ctrl.evaluate_canary(eid, regression_detected=False)
    ctrl.promote(eid, approver="geoff")
    out = ctrl.post_watch(eid, checkpoint="24h", regression_detected=True)
    assert out["action"] == "auto_rolled_back"
    assert reg.get(eid)["status"] == "Rolled Back"


def test_promotion_blocked_without_verification(tmp_path):
    # an unverified experiment cannot reach Awaiting Human Promotion (gate unmet)
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    defn = _defn()
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    runner.run_candidate(defn.experiment_id, reps=1)   # Awaiting Verification, NOT verified
    ctrl = PromotionController(reg, adapter=RetrievalPromotionAdapter(state_dir=str(tmp_path / "a")))
    # status is Awaiting Verification; request_human_promotion tries Verified->... which is illegal
    with pytest.raises(Exception):
        ctrl.request_human_promotion(defn.experiment_id)
