"""
Learned, data-derived ranking — P(accept) from the Ledger's own card outcomes.

The ICE/RICE/WSJF formula is the interpretable *baseline*. This module is the standards' "data-
derived decision" upgrade: it learns the probability a human accepts a drafted card from the
history of accepted/rejected cards, and only takes over from the formula when it demonstrably
beats it (champion–challenger). Until enough decisions exist it ABSTAINS — uses the formula and
says so. No fake model, no fabricated confidence.

Discipline carried from the modeling guides:
  * leakage control — features are the finding's pre-decision signals only; the human's decision
    and anything derived from it are never features.
  * temporal split — train on older cards, validate on newer (never a random shuffle).
  * standardize on TRAIN only — the holdout is transformed with train statistics.
  * champion–challenger — the learned model wins only by `min_auc_uplift` on held-out AUC.
  * documented minimum — below `min_decisions` it abstains (mirrors GBDT's sample-size floor).

Pure Python / stdlib (logistic regression via gradient descent + L2), deterministic.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..registry import ExperimentRegistry
from ..schema import AcceptanceKnobs
from .findings import Finding
from .pillars import Pillar
from .ranking import score as formula_score

# leakage-safe numeric features (pre-decision only). formula_score is feature 0.
_NUMERIC = ["formula_score", "confidence", "impact", "ease", "effort",
            "time_criticality", "risk_reduction", "reach", "voi_value", "voi_prob", "cost"]
_PILLARS = [p.value for p in Pillar]
FEATURE_NAMES = _NUMERIC + [f"pillar={p}" for p in _PILLARS]

# how a registry row's terminal/decision maps to an accept/reject label (None = undecided)
_ACCEPT_WORDS = {"accept", "accepted", "approve", "approved"}
_REJECT_WORDS = {"reject", "rejected", "decline", "declined"}
_HUMAN_ACCEPTED_STATES = {"Promoted", "Canary"}   # human-only states: a human chose to advance it


def features_of(finding: Finding, formula_value: float) -> list[float]:
    """The model's input vector for one finding — pre-decision signals only."""
    num = [formula_value, finding.confidence, finding.impact, finding.ease, finding.effort,
           finding.time_criticality, finding.risk_reduction, finding.reach,
           finding.voi_value, finding.voi_prob, finding.cost]
    onehot = [1.0 if finding.pillar.value == p else 0.0 for p in _PILLARS]
    return num + onehot


def label_from_row(row: dict) -> int | None:
    """1 = human accepted, 0 = human rejected, None = undecided (exclude from training)."""
    hd = (row.get("human_decision") or "").strip().lower()
    if hd in _ACCEPT_WORDS:
        return 1
    if hd in _REJECT_WORDS:
        return 0
    status = row.get("status", "")
    if status in _HUMAN_ACCEPTED_STATES:
        return 1
    if status == "Rejected":
        return 0
    return None


# --------------------------------------------------------------------------- feature log

class FeatureLog:
    """Append-only JSONL of every drafted card's pre-decision features (the training signal).
    Written at draft time; an observer artifact like the report (records what was drafted)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, finding: Finding, formula_value: float, drafted_at: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"experiment_id": finding.experiment_id, "drafted_at": drafted_at,
               "formula_score": formula_value, "finding": finding.to_dict()}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out


@dataclass
class DecisionRecord:
    experiment_id: str
    drafted_at: str
    features: list[float]
    formula_score: float
    label: int


def build_records(feature_rows: list[dict], registry: ExperimentRegistry) -> list[DecisionRecord]:
    """Join logged draft features with each card's human outcome in the Ledger. Only cards with
    a clear accept/reject label become training rows (undecided/deferred are excluded)."""
    out: list[DecisionRecord] = []
    for r in feature_rows:
        eid = r["experiment_id"]
        row = registry.get(eid)
        if row is None:
            continue
        label = label_from_row(row)
        if label is None:
            continue
        finding = Finding.from_dict(r["finding"])
        out.append(DecisionRecord(
            experiment_id=eid, drafted_at=r["drafted_at"],
            features=features_of(finding, r["formula_score"]),
            formula_score=r["formula_score"], label=label))
    return out


# --------------------------------------------------------------------------- logistic model

def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass
class LogisticModel:
    weights: list[float]
    bias: float
    mean: list[float]
    std: list[float]

    def _standardize(self, x: list[float]) -> list[float]:
        return [(xi - m) / s for xi, m, s in zip(x, self.mean, self.std)]

    def predict_proba(self, x: list[float]) -> float:
        z = self.bias + sum(w * xi for w, xi in zip(self.weights, self._standardize(x)))
        return _sigmoid(z)


def _fit_logistic(X: list[list[float]], y: list[int], knobs: AcceptanceKnobs) -> LogisticModel:
    n = len(X)
    d = len(X[0])
    mean = [sum(row[j] for row in X) / n for j in range(d)]
    var = [sum((row[j] - mean[j]) ** 2 for row in X) / n for j in range(d)]
    std = [math.sqrt(v) if v > 1e-12 else 1.0 for v in var]   # constant feature → std 1 (no effect)
    Z = [[(row[j] - mean[j]) / std[j] for j in range(d)] for row in X]
    w = [0.0] * d
    b = 0.0
    lr, l2 = knobs.learning_rate, knobs.l2
    for _ in range(knobs.max_iterations):
        gw = [0.0] * d
        gb = 0.0
        for i in range(n):
            p = _sigmoid(b + sum(w[j] * Z[i][j] for j in range(d)))
            err = p - y[i]
            gb += err
            for j in range(d):
                gw[j] += err * Z[i][j]
        b -= lr * (gb / n)
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
    return LogisticModel(weights=w, bias=b, mean=mean, std=std)


def roc_auc(y: list[int], scores: list[float]) -> float | None:
    """Average-rank (Mann–Whitney) AUC. None if only one class is present (undefined)."""
    pos = [i for i, v in enumerate(y) if v == 1]
    neg = [i for i, v in enumerate(y) if v == 0]
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0                 # 1-based average rank for ties
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    sum_pos = sum(ranks[i] for i in pos)
    return (sum_pos - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def temporal_split(records: list[DecisionRecord],
                   holdout_fraction: float) -> tuple[list[DecisionRecord], list[DecisionRecord]]:
    """Oldest cards train, newest validate — never a random shuffle (temporal safety)."""
    ordered = sorted(records, key=lambda r: (r.drafted_at, r.experiment_id))
    n_holdout = max(1, round(len(ordered) * holdout_fraction))
    n_holdout = min(n_holdout, len(ordered) - 1)   # keep at least one training row
    return ordered[:-n_holdout], ordered[-n_holdout:]


@dataclass
class AcceptanceResult:
    champion: str                    # "formula" | "learned"
    reason: str
    n_decisions: int
    formula_auc: float | None = None
    learned_auc: float | None = None
    model: LogisticModel | None = None

    @property
    def uses_learned(self) -> bool:
        return self.champion == "learned" and self.model is not None

    def to_dict(self) -> dict:
        return {"champion": self.champion, "reason": self.reason,
                "n_decisions": self.n_decisions, "formula_auc": self.formula_auc,
                "learned_auc": self.learned_auc}


def train_acceptance(records: list[DecisionRecord], knobs: AcceptanceKnobs) -> AcceptanceResult:
    """Champion–challenger. Abstain (formula) below the documented minimum; otherwise fit on the
    temporal train split and adopt the learned model only if it beats the formula by
    `min_auc_uplift` on held-out AUC."""
    n = len(records)
    if n < knobs.min_decisions:
        return AcceptanceResult("formula", f"{n} decisions < min {knobs.min_decisions} — abstain", n)
    train, holdout = temporal_split(records, knobs.holdout_fraction)
    hy = [r.label for r in holdout]
    formula_auc = roc_auc(hy, [r.formula_score for r in holdout])
    model = _fit_logistic([r.features for r in train], [r.label for r in train], knobs)
    learned_auc = roc_auc(hy, [model.predict_proba(r.features) for r in holdout])
    if formula_auc is None or learned_auc is None:
        return AcceptanceResult("formula", "holdout has a single class — cannot compare", n,
                                formula_auc, learned_auc, model)
    if learned_auc >= formula_auc + knobs.min_auc_uplift:
        return AcceptanceResult("learned",
                                f"learned AUC {learned_auc:.3f} beats formula {formula_auc:.3f} "
                                f"+{knobs.min_auc_uplift}", n, formula_auc, learned_auc, model)
    return AcceptanceResult("formula",
                            f"learned AUC {learned_auc:.3f} did not beat formula {formula_auc:.3f} "
                            f"+{knobs.min_auc_uplift}", n, formula_auc, learned_auc, model)


def score_findings(findings: list[Finding], result: AcceptanceResult,
                   method: str) -> list[tuple[Finding, float]]:
    """Rank by learned P(accept) when it is champion, else by the formula score. Best-first."""
    if result.uses_learned and result.model is not None:
        scored = [(f, result.model.predict_proba(features_of(f, formula_score(f, method))))
                  for f in findings]
    else:
        scored = [(f, formula_score(f, method)) for f in findings]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


@dataclass
class AcceptanceHarness:
    """Convenience: read the feature log, join outcomes, train, and report — the read-only
    surface the CLI/email use to say whether the learned ranker is ready."""
    registry: ExperimentRegistry
    feature_log: FeatureLog
    knobs: AcceptanceKnobs = field(default_factory=AcceptanceKnobs)

    def evaluate(self) -> AcceptanceResult:
        records = build_records(self.feature_log.rows(), self.registry)
        return train_acceptance(records, self.knobs)
