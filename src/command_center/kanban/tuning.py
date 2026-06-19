"""Data-derived tuning for the fuzzy title-matcher — abstains until it has data.

Mirrors the discovery scan's champion–challenger discipline (acceptance.py): the
config value is the champion; a value learned from logged resolution outcomes is
the challenger and only wins if it beats the champion on a *temporal* holdout by
the configured margin. Below `tuning.min_decisions` it abstains and the config
value stands. No threshold is hardcoded in code — the only literals are the config
defaults, and they are overridable by data.

A ResolutionRecord is one labelled fuzzy match: the match_ratio we accepted at and
whether that match turned out correct. The label arrives from downstream signals
(e.g. an immediate human/agent correction); until that label pipeline runs in
production this abstains — which is the intended Phase-3 ship state. The learner is
fully exercised on synthetic labelled records in tests, so it is real, not a stub.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..schemas import TuningKnobs


@dataclass
class ResolutionRecord:
    ts: str                 # ISO timestamp — temporal ordering, never a feature
    match_ratio: float      # the similarity we accepted at (pre-decision)
    correct: bool           # did the accepted match turn out right (the label)


@dataclass
class TuneResult:
    source: str             # "config" (abstained) | "learned"
    value: float            # the recommended fuzzy_min_ratio
    reason: str
    n: int                  # labelled decisions considered


def temporal_split(records: list[ResolutionRecord], holdout_fraction: float
                   ) -> tuple[list[ResolutionRecord], list[ResolutionRecord]]:
    """Oldest train, newest validate — never a random shuffle (temporal safety)."""
    ordered = sorted(records, key=lambda r: r.ts)
    n_holdout = max(1, round(len(ordered) * holdout_fraction))
    n_holdout = min(n_holdout, len(ordered) - 1)
    return ordered[:-n_holdout], ordered[-n_holdout:]


def _balanced_accuracy(records: list[ResolutionRecord], threshold: float) -> float:
    """Accept iff match_ratio >= threshold; score balanced accuracy vs the label
    (mean of true-positive rate and true-negative rate). Balanced so a skewed
    correct/incorrect mix can't be gamed by always-accept."""
    tp = fn = tn = fp = 0
    for r in records:
        accept = r.match_ratio >= threshold
        if r.correct and accept:
            tp += 1
        elif r.correct and not accept:
            fn += 1
        elif not r.correct and not accept:
            tn += 1
        else:
            fp += 1
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    return (tpr + tnr) / 2


def recommend_fuzzy_ratio(records: list[ResolutionRecord], knobs: TuningKnobs,
                          current: float) -> TuneResult:
    """Champion (config `current`) vs challenger (the observed ratio maximizing
    balanced accuracy on a temporal holdout). The challenger wins only if it beats
    the champion by `min_auc_uplift`."""
    n = len(records)
    if n < knobs.min_decisions:
        return TuneResult("config", current,
                          f"{n} labelled decisions < floor {knobs.min_decisions} "
                          "- abstaining, config value stands", n)
    train, holdout = temporal_split(records, knobs.holdout_fraction)
    # candidate thresholds = the distinct ratios actually observed in training
    candidates = sorted({round(r.match_ratio, 3) for r in train})
    if not candidates:
        return TuneResult("config", current, "no training ratios — abstaining", n)
    best = max(candidates, key=lambda t: _balanced_accuracy(train, t))
    champ_score = _balanced_accuracy(holdout, current)
    chall_score = _balanced_accuracy(holdout, best)
    if chall_score >= champ_score + knobs.min_auc_uplift:
        return TuneResult("learned", best,
                          f"learned ratio {best} beats config {current} on holdout "
                          f"({chall_score:.3f} vs {champ_score:.3f})", n)
    return TuneResult("config", current,
                      f"config {current} not beaten by margin {knobs.min_auc_uplift} "
                      f"(best learned {best}: {chall_score:.3f} vs {champ_score:.3f})", n)
