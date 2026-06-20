"""Every target type rides the identical lifecycle to Promoted (mission §4, §15).

Parametrized over ALL registered experiments (the worked retrieval + judge examples plus
the per-target reference experiments in configs/improvement-targets.yaml). Each one:
register → baseline → candidate → independent verify (PASS) → request human promotion →
human canary → human promote → Promoted, with the active version switched. Proves the
machinery generalizes across all 13 target types, deterministically and offline.
"""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path

from command_center.improvement.schema import ImprovementConfig, ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner, HARNESSES
from command_center.improvement.verifier import IndependentVerifier
from command_center.improvement.promotion import PromotionController, ADAPTERS, adapter_for
from command_center.improvement.lifecycle import Actor, ExperimentStatus as S, HumanApprovalRequired

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ["configs/improvement.yaml", "configs/improvement-targets.yaml"]


def _all_experiments() -> list[ExperimentDefinition]:
    out: list[ExperimentDefinition] = []
    for path in CONFIGS:
        p = REPO_ROOT / path
        if p.exists():
            cfg = ImprovementConfig.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
            out.extend(cfg.experiments)
    return out


ALL = _all_experiments()
EXECUTABLE = [e for e in ALL if e.automated]
MANUAL_PROPOSALS = [e for e in ALL if not e.automated]
IDS = [e.experiment_id for e in EXECUTABLE]


def test_all_thirteen_target_types_present():
    types = {e.target_type.value for e in ALL}
    expected = {"model", "prompt", "skill", "judge", "routing", "tool", "retrieval",
                "memory", "standard", "proactive_check", "workflow", "documentation",
                "repository_template"}
    assert expected <= types, f"missing target types: {expected - types}"
    # every executable experiment's target_ref resolves to a registered harness + adapter
    for e in ALL:
        assert adapter_for(e) is not None, f"no adapter for {e.target_type.value}"
        if e.automated:
            assert e.target_ref in HARNESSES, f"no harness for {e.target_ref}"
        else:
            assert not e.promotion.automatic_promotion
            assert e.status.value == "Proposed"
            assert e.verification.required_evidence


@pytest.mark.parametrize("defn", EXECUTABLE, ids=IDS)
def test_target_type_full_lifecycle(defn, tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    eid = defn.experiment_id
    reg.register(defn, mission_id=f"T-{eid[-6:]}")
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(eid, reps=1)
    cmp = runner.run_candidate(eid, reps=1)
    assert cmp.all_required_pass and cmp.safety_ok, \
        f"{eid}: " + "; ".join(f"{m.name}:{m.passed}({m.reason})" for m in cmp.metrics)

    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    rep = ver.verify(eid, verifier_identity="verifier:det", implementer_identity="runner")
    assert rep.verdict == "PASS", f"{eid}: {rep.summary} :: " + \
        "; ".join(f"{c.id}={c.result}" for c in rep.criteria)
    assert reg.get(eid)["status"] == "Verified"

    adapter = ADAPTERS[defn.target_type.value](state_dir=str(tmp_path / "active"))
    ctrl = PromotionController(reg, adapter=adapter)
    ctrl.request_human_promotion(eid)
    # the wall holds for every target type: an agent cannot promote
    cond = reg.promotion_conditions(eid, human_approval=True)
    with pytest.raises(HumanApprovalRequired):
        reg.set_status(eid, S.CANARY, actor=Actor.AGENT, conditions=cond)
    before = adapter.active_version()
    ctrl.start_canary(eid, approver="geoff")
    ctrl.evaluate_canary(eid, regression_detected=False)
    ctrl.promote(eid, approver="geoff")
    assert reg.get(eid)["status"] == "Promoted"
    assert adapter.active_version() != before


@pytest.mark.parametrize("defn", MANUAL_PROPOSALS, ids=[e.experiment_id for e in MANUAL_PROPOSALS])
def test_manual_proposals_are_not_runner_executable_until_harnessed(defn, tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    with pytest.raises(RuntimeError, match="automated=false"):
        runner.run_baseline(defn.experiment_id, reps=1)


# ---- targeted safety properties --------------------------------------------

def test_tool_target_secret_exclusion_is_the_safety_axis(tmp_path):
    defn = next(e for e in ALL if e.target_type.value == "tool")
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    cmp = runner.run_candidate(defn.experiment_id, reps=1)
    secret = next(m for m in cmp.metrics if m.name == "secret_exclusion")
    assert secret.safety and secret.candidate_value == 1.0
    assert secret.candidate_value > secret.baseline_value   # tightened secret handling


def test_routing_target_blocks_unsafe_downgrade(tmp_path):
    defn = next(e for e in ALL if e.target_type.value == "routing")
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    cmp = runner.run_candidate(defn.experiment_id, reps=1)
    unsafe = next(m for m in cmp.metrics if m.name == "unsafe_downgrades")
    assert unsafe.safety and unsafe.candidate_value == 0.0  # no L3/L4 routed below L3
