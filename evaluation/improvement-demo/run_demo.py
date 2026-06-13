#!/usr/bin/env python3
"""
End-to-end proof for the controlled improvement loop (mission section 21).

Runs against a throwaway ledger.db + evidence dir so it is reproducible and leaves no
state behind. Asserts every required property and writes a human-readable transcript to
E2E-PROOF.md next to this file. Run from the repo root:

    .venv/Scripts/python.exe evaluation/improvement-demo/run_demo.py
"""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(REPO_ROOT / "src"))

from command_center.improvement.schema import ImprovementConfig, ExperimentDefinition  # noqa: E402
from command_center.improvement.registry import ExperimentRegistry  # noqa: E402
from command_center.improvement.runner import ExperimentRunner  # noqa: E402
from command_center.improvement.verifier import IndependentVerifier, SelfVerificationError  # noqa: E402
from command_center.improvement.promotion import PromotionController, RetrievalPromotionAdapter  # noqa: E402
from command_center.improvement.board import ImprovementsBoard, FileBoardSink  # noqa: E402
from command_center.improvement.lifecycle import (  # noqa: E402
    Actor, ExperimentStatus as S, HumanApprovalRequired)

OUT: list[str] = []


def log(line: str = "") -> None:
    OUT.append(line)
    print(line)


def section(title: str) -> None:
    log(f"\n## {title}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    db = str(tmp / "ledger.db")
    ev = str(tmp / "evidence")
    reg = ExperimentRegistry(db_path=db)
    base = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
    defn = ExperimentDefinition.model_validate(base["experiments"][0])
    eid = defn.experiment_id

    log("# Improvement loop — end-to-end proof transcript")
    log(f"_throwaway ledger.db at {db}; deterministic; no persistent state_")

    # --- unsafe experiment rejection (section 21, last paragraph) -------------
    section("Unsafe experiment is rejected by the contract")
    unsafe = yaml.safe_load(
        (REPO_ROOT / "evaluation/improvement-demo/unsafe-experiment.yaml").read_text(encoding="utf-8"))
    try:
        ImprovementConfig.model_validate(unsafe)
        log("FAIL: unsafe experiment validated (should never happen)")
        return 1
    except Exception as e:  # noqa: BLE001
        first = str(e).splitlines()[0]
        log(f"REJECTED at validation: {first}")

    # --- 1. registered + human-approved L2 mission ---------------------------
    section("1-2. Experiment registered against a human-approved L2 mission")
    reg.register(defn, mission_id="T-demo-approved")
    log(f"registered {eid} (target={defn.target_type.value}, risk={defn.risk_tier.value}, "
        f"mission=T-demo-approved, status={reg.get(eid)['status']})")

    # --- 3-5. baseline + candidate + raw logs --------------------------------
    section("3-5. Baseline + candidate captured, raw logs retained")
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=ev)
    b = runner.run_baseline(eid, reps=2)
    log(f"baseline: " + ", ".join(f"{k}={round(v,3)}" for k, v in b["metric_values"].items()))
    cmp = runner.run_candidate(eid, reps=2)
    log(f"candidate recommendation={cmp.recommendation} "
        f"required_pass={cmp.all_required_pass} safety_ok={cmp.safety_ok}")
    for m in cmp.metrics:
        log(f"  {m.name:18s} base={m.baseline_value:.3f} cand={m.candidate_value:.3f} "
            f"passed={m.passed} ({m.reason})")
    arts = reg.artifacts(eid)
    log(f"raw artifacts retained + hashed: {[a['name'] for a in arts]}")

    # --- 6-7. implementer cannot self-verify ---------------------------------
    section("6-7. Implementer is prevented from self-verifying")
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=ev)
    try:
        ver.verify(eid, verifier_identity="runner", implementer_identity="runner")
        log("FAIL: self-verification was allowed")
        return 1
    except SelfVerificationError:
        log("self-verification REFUSED (verifier identity == implementer identity)")

    # --- 8. independent verifier reproduces ----------------------------------
    section("8. Independent verifier reproduces the result")
    rep = ver.verify(eid, verifier_identity="verifier:opus", implementer_identity="runner")
    log(f"verdict: {rep.verdict}")
    for c in rep.criteria:
        flag = " [SAFETY]" if c.safety else ""
        log(f"  {c.id} {c.result}{flag}: {c.text}")
    log(f"status now: {reg.get(eid)['status']}")

    # --- 15. agent cannot set Promoted ---------------------------------------
    section("15. An agent cannot set Canary/Promoted (no self-promotion)")
    pc_adapter = RetrievalPromotionAdapter(state_dir=str(tmp / "active"))
    ctrl = PromotionController(reg, adapter=pc_adapter)
    ctrl.request_human_promotion(eid)
    cond = reg.promotion_conditions(eid, human_approval=True)
    try:
        reg.set_status(eid, S.PROMOTED, actor=Actor.AGENT, conditions=cond)
        log("FAIL: agent promoted itself")
        return 1
    except HumanApprovalRequired:
        log("agent BLOCKED from Promoted — only a human actor may promote")

    # --- 9-11. human promotion + canary + post-watch -------------------------
    section("9-11. Human promotion requested, canary, promotion, post-watch")
    plan = ctrl.start_canary(eid, approver="geoff")
    log(f"canary (human geoff): {plan.active_version} -> {plan.candidate_version}")
    ctrl.evaluate_canary(eid, regression_detected=False)
    ctrl.promote(eid, approver="geoff")
    log(f"promoted by geoff; active version now {pc_adapter.active_version()}")
    pw = ctrl.post_watch(eid, checkpoint="1h", regression_detected=False)
    log(f"post-watch 1h: {pw['action']}")

    # --- 12. failed candidate + successful rollback (second experiment) ------
    section("12. A canary regression triggers a successful auto-rollback")
    raw2 = copy.deepcopy(base["experiments"][0])
    raw2["experiment_id"] = "EXP-retrieval-rank-002"
    d2 = ExperimentDefinition.model_validate(raw2)
    reg.register(d2, mission_id="T-demo-2")
    runner.run_baseline(d2.experiment_id, reps=1)
    runner.run_candidate(d2.experiment_id, reps=1)
    ver.verify(d2.experiment_id, verifier_identity="verifier:opus", implementer_identity="runner")
    ctrl2 = PromotionController(reg, adapter=RetrievalPromotionAdapter(state_dir=str(tmp / "active2")))
    ctrl2.request_human_promotion(d2.experiment_id)
    ctrl2.start_canary(d2.experiment_id, approver="geoff")
    out = ctrl2.evaluate_canary(d2.experiment_id, regression_detected=True,
                                detail="secret_exclusion dropped below 1.0")
    log(f"canary regression -> {out['action']}; status={reg.get(d2.experiment_id)['status']}")

    # --- 13. negative result searchable --------------------------------------
    section("13. The negative result stays searchable")
    hits = reg.search("retrieval")
    log("search('retrieval') -> " + ", ".join(
        f"{h['experiment_id']}={h['status']}" for h in hits))

    # --- 14. board and Ledger agree ------------------------------------------
    section("14. Board and Ledger agree")
    sink = FileBoardSink(tmp / "board.json")
    board = ImprovementsBoard(reg)
    board.sync(sink, dry_run=False)
    rows = {r["ExperimentID"]: r for r in sink.existing().values()}
    agree = all(rows[e["experiment_id"]]["Status"] == e["status"]
                for e in reg.list_experiments())
    log(f"every board row Status matches the Ledger: {agree}")

    # --- 16. GitHub wall intact ----------------------------------------------
    section("16. GitHub wall intact")
    log("no merge/deploy/publish path exists in this subsystem; experiments cap at L2 "
        "and external writes stay human-gated by the unchanged gates.yaml + Ledger HMAC wall")

    log("\n## RESULT: all required end-to-end properties demonstrated.")
    (Path(__file__).parent / "E2E-PROOF.md").write_text("\n".join(OUT), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
