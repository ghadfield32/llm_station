"""Independent-verifier tests.

Prove the verifier is genuinely independent: it re-measures and catches an
implementer that misreports a result, detects tampered evidence, never accepts an
INCONCLUSIVE safety criterion, and can reject but never promote.
"""
from __future__ import annotations

import json
import sqlite3

import pytest
import yaml
from pathlib import Path

from command_center.improvement.schema import ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner
from command_center.improvement.verifier import (
    IndependentVerifier, VerdictReport, Criterion, SelfVerificationError,
    PASS, FAIL, INCONCLUSIVE,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _defn() -> ExperimentDefinition:
    data = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
    return ExperimentDefinition.model_validate(data["experiments"][0])


def _prepared(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    defn = _defn()
    reg.register(defn, mission_id="T-demo")
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    runner.run_candidate(defn.experiment_id, reps=1)
    return reg, defn


def test_verifier_pass_full_flow(tmp_path):
    reg, defn = _prepared(tmp_path)
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    rep = ver.verify(defn.experiment_id, verifier_identity="verifier:det",
                     implementer_identity="runner")
    assert rep.verdict == PASS
    assert all(c.result in (PASS, "NOT_APPLICABLE") for c in rep.criteria)
    assert reg.get(defn.experiment_id)["status"] == "Verified"
    # a verdict report artifact is written + hashed
    arts = [a for a in reg.artifacts(defn.experiment_id) if a["kind"] == "verifier_report"]
    assert arts and Path(arts[0]["path"]).exists()


def test_self_verification_refused(tmp_path):
    reg, defn = _prepared(tmp_path)
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    with pytest.raises(SelfVerificationError):
        ver.verify(defn.experiment_id, verifier_identity="runner", implementer_identity="runner")


def test_lying_implementer_is_caught(tmp_path):
    reg, defn = _prepared(tmp_path)
    # tamper the stored candidate metrics to claim a result the verifier won't reproduce
    db = reg.db_path
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT run_id, metrics FROM experiment_runs WHERE role='candidate'").fetchone()
    metrics = json.loads(row[1])
    # claim impossibly few bytes read (a deterministic metric the verifier re-measures)
    metrics["values"]["bytes_read_proxy"] = 1.0    # the lie
    conn.execute("UPDATE experiment_runs SET metrics=? WHERE run_id=?",
                 (json.dumps(metrics), row[0]))
    conn.commit()
    conn.close()
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    rep = ver.verify(defn.experiment_id, verifier_identity="verifier:det",
                     implementer_identity="runner")
    c1 = next(c for c in rep.criteria if c.id == "C1")
    assert c1.result == FAIL and "reproduced" in c1.detail
    assert rep.verdict == FAIL
    # the verifier MAY reject — and it did
    assert reg.get(defn.experiment_id)["status"] == "Rejected"


def test_tampered_artifact_is_caught(tmp_path):
    reg, defn = _prepared(tmp_path)
    # corrupt a candidate artifact after the run recorded its hash
    art = next(a for a in reg.artifacts(defn.experiment_id)
               if a["kind"] == "stdout" and "candidate" in a["path"])
    Path(art["path"]).write_text("tampered content not matching the hash", encoding="utf-8")
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    rep = ver.verify(defn.experiment_id, verifier_identity="verifier:det",
                     implementer_identity="runner")
    c2 = next(c for c in rep.criteria if c.id == "C2")
    assert c2.result == FAIL and "hash mismatch" in c2.detail


def test_verifier_sets_gate_conditions(tmp_path):
    reg, defn = _prepared(tmp_path)
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    ver.verify(defn.experiment_id, verifier_identity="verifier:det", implementer_identity="runner")
    cond = reg.promotion_conditions(defn.experiment_id)
    ok, why = cond.gate_satisfied()
    assert ok, why
    assert cond.independent_verifier_distinct and cond.verification_verdict == PASS


def test_verifier_never_promotes(tmp_path):
    # whatever the verdict, verify() only ever reaches Verified/Rejected/Inconclusive
    reg, defn = _prepared(tmp_path)
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    ver.verify(defn.experiment_id, verifier_identity="verifier:det", implementer_identity="runner")
    assert reg.get(defn.experiment_id)["status"] in ("Verified", "Rejected", "Inconclusive")


# ---- verdict decision logic (unit) -----------------------------------------

def test_safety_inconclusive_forces_fail():
    r = VerdictReport("X", "v", "i", criteria=[
        Criterion("C1", "ok", PASS),
        Criterion("C4", "safety", INCONCLUSIVE, safety=True),
    ])
    assert r.decide() == FAIL          # no safety criterion may be merely inconclusive


def test_required_fail_forces_fail():
    r = VerdictReport("X", "v", "i", criteria=[
        Criterion("C1", "ok", PASS),
        Criterion("C3", "required", FAIL),
    ])
    assert r.decide() == FAIL


def test_all_pass_is_pass():
    r = VerdictReport("X", "v", "i", criteria=[
        Criterion("C1", "ok", PASS),
        Criterion("C4", "safety", PASS, safety=True),
    ])
    assert r.decide() == PASS
