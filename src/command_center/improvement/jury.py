"""
Phase 2 — judge/jury hardening.

LLM-as-judge bias is large and well documented (position, verbosity, self-preference,
bandwagon). None of it is fully solved; the strongest current practice is a *diverse panel*
with explicit bias controls plus continuous agreement-with-humans tracking. This module
gives that, deterministically and offline:

  * inter-rater agreement: Cohen's κ (two raters), Fleiss' κ (panels), Krippendorff's α
    (panels with missing data) — correlation alone is insufficient, so we track κ/α.
  * a `Jury` that aggregates diverse judges by majority vote and surfaces the *disagreement
    set* (items the panel can't agree on) for human attention.
  * bias controls: position/order consistency (swap and require agreement), a verbosity-bias
    slope (score vs length), and identity anonymization (attacks self-preference).

Everything here informs the verifier and the morning brief; like the rest of the loop it can
reject/flag but never promote. The judges plugged in are deterministic here; a real diverse
LLM panel slots in behind the same `Jury` interface when models are reachable.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable


# ---- inter-rater agreement (pure math, verified against textbook values) -----

def cohens_kappa(rater_a: list, rater_b: list) -> float:
    """Cohen's κ for two raters over the same items. Raises on length mismatch."""
    if len(rater_a) != len(rater_b):
        raise ValueError("cohens_kappa requires equal-length rater lists")
    n = len(rater_a)
    if n == 0:
        raise ValueError("cohens_kappa requires at least one item")
    cats = set(rater_a) | set(rater_b)
    po = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    ca = Counter(rater_a)
    cb = Counter(rater_b)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    return 1.0 if pe == 1.0 else (po - pe) / (1 - pe)


def fleiss_kappa(ratings: list[list[int]]) -> float:
    """Fleiss' κ. ``ratings`` is N items × K categories, each cell = number of raters who
    assigned that category to that item (constant raters per item). Raises on ragged input."""
    if not ratings:
        raise ValueError("fleiss_kappa requires at least one item")
    n_raters = sum(ratings[0])
    if any(sum(row) != n_raters for row in ratings):
        raise ValueError("every item must have the same number of ratings")
    if n_raters < 2:
        raise ValueError("fleiss_kappa requires >= 2 raters per item")
    n_items = len(ratings)
    k = len(ratings[0])
    p_j = [sum(ratings[i][j] for i in range(n_items)) / (n_items * n_raters) for j in range(k)]
    p_i = [(sum(c * c for c in row) - n_raters) / (n_raters * (n_raters - 1)) for row in ratings]
    p_bar = sum(p_i) / n_items
    p_e = sum(p * p for p in p_j)
    return 1.0 if p_e == 1.0 else (p_bar - p_e) / (1 - p_e)


def krippendorff_alpha(data: list[list], *, missing=None) -> float:
    """Krippendorff's α (nominal) over a coders × units matrix; ``missing`` marks no-rating.
    Handles unequal ratings per unit. Raises if no pairable data exists."""
    n_units = len(data[0]) if data else 0
    units: list[list] = []
    for u in range(n_units):
        vals = [coder[u] for coder in data if coder[u] is not missing]
        if len(vals) >= 2:
            units.append(vals)
    if not units:
        raise ValueError("krippendorff_alpha needs units with >= 2 ratings")
    # coincidence matrix
    coincidence: dict[tuple, float] = {}
    n_c: dict[Any, float] = {}
    total = 0.0
    for vals in units:
        m = len(vals)
        for i in range(m):
            for j in range(m):
                if i == j:
                    continue
                key = (vals[i], vals[j])
                coincidence[key] = coincidence.get(key, 0.0) + 1.0 / (m - 1)
    for (c, _k), v in coincidence.items():
        n_c[c] = n_c.get(c, 0.0) + v
        total += v
    observed_disagree = sum(v for (c, k), v in coincidence.items() if c != k)  # D_o
    if total <= 1:
        return 1.0
    expected_disagree = (total ** 2 - sum(v * v for v in n_c.values())) / (total - 1)  # D_e
    if expected_disagree == 0:
        return 1.0
    return 1.0 - observed_disagree / expected_disagree


def agreement_label(kappa: float) -> str:
    """Landis & Koch interpretation bands."""
    if kappa < 0.0:
        return "poor"
    if kappa < 0.2:
        return "slight"
    if kappa < 0.4:
        return "fair"
    if kappa < 0.6:
        return "moderate"
    if kappa < 0.8:
        return "substantial"
    return "near-perfect"


# ---- the jury (diverse panel + disagreement set) ----------------------------

@dataclass
class JuryVerdict:
    item_id: Any
    label: str
    votes: dict[str, str]
    agreement: float        # fraction voting for the winning label
    unanimous: bool

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class JuryResult:
    verdicts: list[JuryVerdict]
    disagreement_ids: list = field(default_factory=list)
    inter_judge_kappa: float | None = None    # mean pairwise Cohen's κ across the panel

    def majority_labels(self) -> dict:
        return {v.item_id: v.label for v in self.verdicts}


class Jury:
    """A panel of diverse judges. Each judge is a callable item -> label. The jury reports a
    majority label, the per-judge votes, and the disagreement set for human review."""

    def __init__(self, judges: dict[str, Callable[[Any], str]]):
        if len(judges) < 2:
            raise ValueError("a jury needs at least two judges (diversity is the point)")
        self.judges = judges

    def vote(self, item: Any, item_id: Any = None) -> JuryVerdict:
        votes = {name: fn(item) for name, fn in self.judges.items()}
        tally = Counter(votes.values())
        label, count = tally.most_common(1)[0]
        return JuryVerdict(item_id=item_id if item_id is not None else item, label=label,
                           votes=votes, agreement=count / len(votes), unanimous=len(tally) == 1)

    def evaluate(self, items: list, ids: list | None = None) -> JuryResult:
        ids = ids if ids is not None else list(range(len(items)))
        verdicts = [self.vote(it, i) for it, i in zip(items, ids)]
        disagreement = [v.item_id for v in verdicts if not v.unanimous]
        # mean pairwise Cohen's κ across judges (panel cohesion)
        names = list(self.judges)
        per_judge = {n: [v.votes[n] for v in verdicts] for n in names}
        pair_kappas = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pair_kappas.append(cohens_kappa(per_judge[names[i]], per_judge[names[j]]))
        mean_kappa = sum(pair_kappas) / len(pair_kappas) if pair_kappas else None
        return JuryResult(verdicts=verdicts, disagreement_ids=disagreement,
                          inter_judge_kappa=mean_kappa)


# ---- bias controls ----------------------------------------------------------

def position_consistent(pairwise_judge: Callable[[Any, Any], str], a: Any, b: Any) -> bool:
    """Run a pairwise judge in both orders; a position-bias-free judge gives a consistent
    preference. pairwise_judge(x, y) returns 'first' | 'second' | 'tie'."""
    fwd = pairwise_judge(a, b)
    rev = pairwise_judge(b, a)
    return (fwd, rev) in (("first", "second"), ("second", "first"), ("tie", "tie"))


def verbosity_bias_slope(scores: list[float], lengths: list[float]) -> float:
    """Pearson correlation of score with output length. A large positive value is a verbosity-
    bias red flag (the judge rewards length, not quality)."""
    if len(scores) != len(lengths) or len(scores) < 2:
        raise ValueError("need equal-length series of >= 2 points")
    n = len(scores)
    ms, ml = sum(scores) / n, sum(lengths) / n
    cov = sum((s - ms) * (length - ml) for s, length in zip(scores, lengths))
    vs = sum((s - ms) ** 2 for s in scores)
    vl = sum((length - ml) ** 2 for length in lengths)
    if vs == 0 or vl == 0:
        return 0.0
    return cov / (vs ** 0.5 * vl ** 0.5)


_IDENTITY_MARKERS = [
    r"\bas an ai\b", r"\bas a large language model\b", r"\bmy (?:answer|response|output)\b",
    r"\bi (?:wrote|generated|produced) this\b", r"\b(?:gpt|claude|gemini|qwen|llama)[-\w.]*\b",
    r"\bmodel [AB]\b", r"\bassistant [AB]\b",
]


def anonymize(text: str) -> str:
    """Strip identity/self-reference markers before judging — attacks self-preference and
    bandwagon bias. Deterministic; no model call."""
    out = text
    for pat in _IDENTITY_MARKERS:
        out = re.sub(pat, "[ANON]", out, flags=re.IGNORECASE)
    return out
