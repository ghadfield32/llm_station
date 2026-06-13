"""Phase-0 integration: the statistical report flows through the runner and the verifier's
significance criterion (C9) — which can only reject, never promote.

The gate is OFF by default (require_significance=False → C9 is NA), so it never blocks the
synthetic demos; when a real experiment pre-registers it, the four outcomes (PASS / FAIL /
INCONCLUSIVE / NA) behave correctly.
"""
from __future__ import annotations

import copy

import yaml
from pathlib import Path

from command_center.improvement.schema import ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner
from command_center.improvement.verifier import IndependentVerifier
from command_center.improvement import statistics as st

REPO_ROOT = Path(__file__).resolve().parents[1]
_CFG = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
_RETRIEVAL = _CFG["experiments"][0]


def _retrieval_defn(require_sig=False, primary="recall_at_5", mde=None, eid="EXP-stat-001"):
    raw = copy.deepcopy(_RETRIEVAL)
    raw["experiment_id"] = eid
    raw["statistics"] = {"require_significance": require_sig, "primary_metric": primary}
    if mde is not None:
        raw["statistics"]["mde"] = mde
    return ExperimentDefinition.model_validate(raw)


# ---- end-to-end: report attached, significant primary -> C9 PASS -----------

def test_runner_attaches_statistical_report(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    defn = _retrieval_defn(require_sig=True)
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    cmp = runner.run_candidate(defn.experiment_id, reps=1)
    rep = cmp.statistics
    assert rep["primary_metric"] == "recall_at_5"
    assert rep["metric_stats"]                          # per-metric CIs computed
    assert any(m["name"] == "recall_at_5" for m in rep["metric_stats"])
    assert rep["srm"] is not None
    # the report is persisted as a hashed artifact
    arts = [a for a in reg.artifacts(defn.experiment_id) if a["kind"] == "statistics"]
    assert arts and Path(arts[0]["path"]).exists()


def test_significance_gate_passes_on_real_win(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    defn = _retrieval_defn(require_sig=True)
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    runner.run_candidate(defn.experiment_id, reps=1)
    ver = IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    rep = ver.verify(defn.experiment_id, verifier_identity="v:det", implementer_identity="runner")
    c9 = next(c for c in rep.criteria if c.id == "C9")
    assert c9.result == "PASS", c9.detail
    assert rep.verdict == "PASS"


# ---- the four C9 branches, exercised directly (no harness needed) ----------

def _verifier(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    return IndependentVerifier(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))


def test_c9_na_when_gate_disabled(tmp_path):
    ver = _verifier(tmp_path)
    defn = _retrieval_defn(require_sig=False)
    c = ver._check_significance(defn, {"recall_at_5": [0.0] * 10}, {"recall_at_5": [1.0] * 10})
    assert c.result == "NOT_APPLICABLE" and not c.required


def test_c9_pass_on_significant_improvement(tmp_path):
    ver = _verifier(tmp_path)
    defn = _retrieval_defn(require_sig=True)
    c = ver._check_significance(defn, {"recall_at_5": [0.0] * 20}, {"recall_at_5": [1.0] * 20})
    assert c.result == "PASS"


def test_c9_fail_on_null_result(tmp_path):
    ver = _verifier(tmp_path)
    defn = _retrieval_defn(require_sig=True)
    same = [0.5, 0.4, 0.6, 0.5, 0.55, 0.45, 0.5, 0.5]
    c = ver._check_significance(defn, {"recall_at_5": same}, {"recall_at_5": list(same)})
    assert c.result == "FAIL" and "no significant improvement" in c.detail


def test_c9_inconclusive_when_underpowered(tmp_path):
    ver = _verifier(tmp_path)
    defn = _retrieval_defn(require_sig=True, mde=0.001)   # absurdly small effect to require huge n
    c = ver._check_significance(defn, {"recall_at_5": [0.0, 0.1, 0.0, 0.2, 0.0]},
                                {"recall_at_5": [0.1, 0.2, 0.1, 0.3, 0.1]})
    assert c.result == "INCONCLUSIVE" and "underpowered" in c.detail


def test_c9_fail_on_sample_ratio_mismatch(tmp_path):
    ver = _verifier(tmp_path)
    defn = _retrieval_defn(require_sig=True)
    # 70 vs 30 assignment -> chi2 = 16, p ~ 6e-5 -> mismatch
    c = ver._check_significance(defn, {"recall_at_5": [0.0] * 70}, {"recall_at_5": [1.0] * 30})
    assert c.result == "FAIL" and "mismatch" in c.detail


# ---- analyze_experiment shape ----------------------------------------------

def test_analyze_experiment_multidimensional():
    specs = [{"name": "recall", "direction": "increase", "required": True, "safety": False,
              "minimum_improvement": 0.05},
             {"name": "fbr", "direction": "decrease", "required": True, "safety": True,
              "minimum_improvement": None}]
    plan = {"alpha": 0.05, "n_resamples": 500, "seed": 1, "test_type": "auto",
            "primary_metric": "recall", "power": 0.8, "mde": None}
    b = {"recall": [0.0] * 15, "fbr": [0.0] * 15}
    c = {"recall": [1.0] * 15, "fbr": [0.0] * 15}
    rep = st.analyze_experiment("X", specs, plan, b, c)
    assert rep.primary_metric == "recall" and rep.primary_improved
    # multidimensional: a stat per tested metric, never collapsed to one score
    assert {m.name for m in rep.metric_stats} == {"recall", "fbr"}
