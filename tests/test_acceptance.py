"""
The data-derived acceptance ranker: leakage-safe features, the pure-Python logistic model,
AUC, temporal split, and the champion-challenger that abstains to the formula below the sample
floor and only adopts the learned model when it beats the formula on held-out AUC.
"""
from __future__ import annotations

import pytest

from command_center.improvement.discovery import (
    DecisionRecord, FeatureLog, Finding, Pillar, build_records, features_of, label_from_row,
    roc_auc, score_findings, train_acceptance,
)
from command_center.improvement.discovery.acceptance import (
    FEATURE_NAMES, AcceptanceHarness, temporal_split,
)
from command_center.improvement.schema import AcceptanceKnobs
from command_center.improvement.registry import ExperimentRegistry


def _finding(i, pillar=Pillar.CODE_QUALITY, **kw):
    return Finding(pillar=pillar, source="t", title=f"card {i}", claim="c", evidence="e", **kw)


# --------------------------------------------------------------------- features / labels

def test_features_vector_shape_and_formula_first():
    f = _finding(1, impact=0.7)
    vec = features_of(f, formula_value=1.23)
    assert len(vec) == len(FEATURE_NAMES)
    assert vec[0] == 1.23                         # formula score is feature 0
    # exactly one pillar one-hot is set
    assert sum(vec[len(FEATURE_NAMES) - 9:]) == 1.0


def test_label_from_row_maps_human_decision_and_states():
    assert label_from_row({"human_decision": "accept"}) == 1
    assert label_from_row({"human_decision": "Rejected"}) == 0
    assert label_from_row({"status": "Promoted"}) == 1      # human-only state
    assert label_from_row({"status": "Canary"}) == 1
    assert label_from_row({"status": "Rejected"}) == 0
    assert label_from_row({"status": "Proposed"}) is None   # undecided
    assert label_from_row({"status": "Deferred"}) is None   # ambiguous → excluded


# --------------------------------------------------------------------- roc_auc

def test_roc_auc_known_values():
    assert roc_auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == pytest.approx(1.0)
    assert roc_auc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(0.0)
    assert roc_auc([1, 0], [0.5, 0.5]) == pytest.approx(0.5)   # all ties → 0.5
    assert roc_auc([1, 1, 1], [0.1, 0.2, 0.3]) is None         # single class → undefined


# --------------------------------------------------------------------- temporal split

def test_temporal_split_oldest_trains_newest_validates():
    recs = [DecisionRecord(f"e{i}", f"2026-01-{i+1:02d}", [0.0], 0.0, i % 2) for i in range(10)]
    train, holdout = temporal_split(recs, 0.3)
    assert len(holdout) == 3 and len(train) == 7
    assert train[0].drafted_at < holdout[0].drafted_at        # strictly temporal
    # never leaves training empty even with a tiny set
    t2, h2 = temporal_split(recs[:2], 0.9)
    assert len(t2) == 1 and len(h2) == 1


# --------------------------------------------------------------------- champion / challenger

def _records(labels, pillars, fscores, start_day=1):
    out = []
    for i, (lab, pil, fs) in enumerate(zip(labels, pillars, fscores)):
        f = _finding(i, pillar=pil)
        out.append(DecisionRecord(f"e{i}", f"2026-02-{start_day+i:02d}",
                                  features_of(f, fs), fs, lab))
    return out


def test_abstains_below_min_decisions():
    recs = _records([1, 0, 1, 0, 1], [Pillar.CODE_QUALITY] * 5, [0.5] * 5)
    res = train_acceptance(recs, AcceptanceKnobs(min_decisions=10))
    assert res.champion == "formula" and res.model is None
    assert "abstain" in res.reason and res.n_decisions == 5


def test_learned_wins_when_it_beats_the_formula():
    # acceptance is perfectly explained by pillar (a feature the formula score ignores);
    # the formula score is constant → formula AUC 0.5, learned AUC ~1.0 → learned takes over.
    n = 30
    labels = [i % 2 for i in range(n)]
    pillars = [Pillar.CODE_QUALITY if lab else Pillar.AUTOMATION for lab in labels]
    recs = _records(labels, pillars, [0.5] * n)
    res = train_acceptance(recs, AcceptanceKnobs(min_decisions=10, holdout_fraction=0.3))
    assert res.champion == "learned"
    assert res.learned_auc is not None and res.formula_auc is not None
    assert res.learned_auc > res.formula_auc


def test_formula_kept_when_already_optimal():
    # the formula score already equals the label → formula AUC 1.0, learned cannot beat it
    n = 30
    labels = [i % 2 for i in range(n)]
    recs = _records(labels, [Pillar.CODE_QUALITY] * n, [float(lab) for lab in labels])
    res = train_acceptance(recs, AcceptanceKnobs(min_decisions=10, min_auc_uplift=0.02))
    assert res.champion == "formula"
    assert res.formula_auc == pytest.approx(1.0)


def test_single_class_holdout_keeps_formula():
    # all newest (holdout) cards accepted → AUC undefined → keep the formula
    n = 20
    labels = [0] * 14 + [1] * 6          # holdout (last 30% = 6) is all label 1
    recs = _records(labels, [Pillar.CODE_QUALITY] * n, [0.5] * n)
    res = train_acceptance(recs, AcceptanceKnobs(min_decisions=10, holdout_fraction=0.3))
    assert res.champion == "formula"
    assert "single class" in res.reason


def test_score_findings_uses_champion():
    findings = [_finding(1, pillar=Pillar.AUTOMATION, impact=0.1),
                _finding(2, pillar=Pillar.CODE_QUALITY, impact=0.9)]
    # learned champion: pillar drives acceptance → code_quality ranks first
    learned = train_acceptance(
        _records([i % 2 for i in range(30)],
                 [Pillar.CODE_QUALITY if i % 2 else Pillar.AUTOMATION for i in range(30)],
                 [0.5] * 30),
        AcceptanceKnobs(min_decisions=10))
    ranked = score_findings(findings, learned, method="wsjf")
    assert ranked[0][0].pillar is Pillar.CODE_QUALITY


# --------------------------------------------------------------------- feature log + harness

def test_feature_log_round_trip(tmp_path):
    log = FeatureLog(tmp_path / "feat.jsonl")
    f = _finding(1, impact=0.6)
    log.append(f, formula_value=2.0, drafted_at="2026-02-01")
    rows = log.rows()
    assert len(rows) == 1 and rows[0]["experiment_id"] == f.experiment_id
    assert rows[0]["formula_score"] == 2.0


def test_build_records_joins_log_with_ledger_outcomes(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    log = FeatureLog(tmp_path / "feat.jsonl")
    decided, undecided = _finding(1, pillar=Pillar.CODE_QUALITY), _finding(2, pillar=Pillar.AUTOMATION)
    for f in (decided, undecided):
        reg.register(f.to_experiment_definition())
        log.append(f, formula_value=1.0, drafted_at="2026-02-01")
    reg.set_human_decision(decided.experiment_id, "accept")     # only this one is labeled
    records = build_records(log.rows(), reg)
    assert len(records) == 1 and records[0].label == 1
    assert records[0].experiment_id == decided.experiment_id


def test_harness_evaluate_end_to_end(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    log = FeatureLog(tmp_path / "feat.jsonl")
    for i in range(12):
        f = _finding(i, pillar=Pillar.CODE_QUALITY if i % 2 else Pillar.AUTOMATION)
        reg.register(f.to_experiment_definition())
        log.append(f, formula_value=0.5, drafted_at=f"2026-03-{i+1:02d}")
        reg.set_human_decision(f.experiment_id, "accept" if i % 2 else "reject")
    res = AcceptanceHarness(reg, log, AcceptanceKnobs(min_decisions=6)).evaluate()
    assert res.n_decisions == 12
    assert res.champion in ("formula", "learned")
    assert isinstance(res.to_dict()["n_decisions"], int)
