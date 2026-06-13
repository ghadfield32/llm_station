"""End-to-end proof, as a deterministic test (mission section 21).

One experiment walks the whole lifecycle to Promoted through the real modules; a
second is rolled back from a canary regression and stays searchable; the unsafe
fixture is rejected; the board agrees with the Ledger.
"""
from __future__ import annotations

import copy

import pytest
import yaml
from pathlib import Path

from command_center.improvement.schema import ImprovementConfig, ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner
from command_center.improvement.verifier import IndependentVerifier, SelfVerificationError
from command_center.improvement.promotion import PromotionController, RetrievalPromotionAdapter
from command_center.improvement.board import ImprovementsBoard, FileBoardSink
from command_center.improvement.lifecycle import Actor, ExperimentStatus as S, HumanApprovalRequired

REPO_ROOT = Path(__file__).resolve().parents[1]
_BASE = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))


def _defn(eid="EXP-retrieval-rank-001") -> ExperimentDefinition:
    raw = copy.deepcopy(_BASE["experiments"][0])
    raw["experiment_id"] = eid
    return ExperimentDefinition.model_validate(raw)


def test_unsafe_fixture_is_rejected():
    unsafe = yaml.safe_load(
        (REPO_ROOT / "evaluation/improvement-demo/unsafe-experiment.yaml").read_text(encoding="utf-8"))
    with pytest.raises(Exception):
        ImprovementConfig.model_validate(unsafe)


def test_full_lifecycle_to_promoted(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    defn = _defn()
    eid = defn.experiment_id
    reg.register(defn, mission_id="T-demo-approved")
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(eid, reps=1)
    runner.run_candidate(eid, reps=1)

    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    with pytest.raises(SelfVerificationError):
        ver.verify(eid, verifier_identity="runner", implementer_identity="runner")
    rep = ver.verify(eid, verifier_identity="verifier:opus", implementer_identity="runner")
    assert rep.verdict == "PASS"
    assert reg.get(eid)["status"] == "Verified"

    ctrl = PromotionController(reg, adapter=RetrievalPromotionAdapter(state_dir=str(tmp_path / "a")))
    ctrl.request_human_promotion(eid)
    # agent cannot self-promote
    cond = reg.promotion_conditions(eid, human_approval=True)
    with pytest.raises(HumanApprovalRequired):
        reg.set_status(eid, S.PROMOTED, actor=Actor.AGENT, conditions=cond)
    # human path
    ctrl.start_canary(eid, approver="geoff")
    ctrl.evaluate_canary(eid, regression_detected=False)
    ctrl.promote(eid, approver="geoff")
    assert reg.get(eid)["status"] == "Promoted"
    assert ctrl.post_watch(eid, checkpoint="1h", regression_detected=False)["action"] == "ok"


def test_canary_regression_rolls_back_and_stays_searchable(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    d = _defn("EXP-retrieval-rank-002")
    reg.register(d, mission_id="T-2")
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(d.experiment_id, reps=1)
    runner.run_candidate(d.experiment_id, reps=1)
    IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev")).verify(
        d.experiment_id, verifier_identity="verifier:opus", implementer_identity="runner")
    ctrl = PromotionController(reg, adapter=RetrievalPromotionAdapter(state_dir=str(tmp_path / "a2")))
    ctrl.request_human_promotion(d.experiment_id)
    ctrl.start_canary(d.experiment_id, approver="geoff")
    out = ctrl.evaluate_canary(d.experiment_id, regression_detected=True)
    assert out["action"] == "auto_rolled_back"
    assert reg.get(d.experiment_id)["status"] == "Rolled Back"
    # negative result is searchable
    assert any(h["experiment_id"] == d.experiment_id for h in reg.search("retrieval"))


def test_two_experiments_have_distinct_run_ids(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    for eid in ("EXP-a", "EXP-b"):
        reg.register(_defn(eid))
        runner.run_baseline(eid, reps=1)
    a = reg.runs("EXP-a", role="baseline")[0]["run_id"]
    b = reg.runs("EXP-b", role="baseline")[0]["run_id"]
    assert a != b and a.startswith("EXP-a") and b.startswith("EXP-b")


def test_board_and_ledger_agree(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    reg.register(_defn("EXP-x"))
    reg.register(_defn("EXP-y"))
    sink = FileBoardSink(tmp_path / "board.json")
    ImprovementsBoard(reg).sync(sink, dry_run=False)
    rows = {r["ExperimentID"]: r for r in sink.existing().values()}
    for e in reg.list_experiments():
        assert rows[e["experiment_id"]]["Status"] == e["status"]
