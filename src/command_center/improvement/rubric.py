"""Pure adaptive-rubric scoring and loss-pattern analysis.

Judge execution belongs outside this module. These functions only normalize already-returned
sample values, aggregate them, and surface incomplete evidence. As with the jury, rubric
verdicts can reject or flag but never promote.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any

from command_center.schemas.contracts import Rubric

from .jury import agreement_label, cohens_kappa


@dataclass(frozen=True)
class CriterionVerdict:
    name: str
    score: float | None
    agreement: float | None
    agreement_band: str | None
    explanations: tuple[str, ...]
    valid_samples: int


@dataclass(frozen=True)
class RubricVerdict:
    rubric_id: str
    overall_score: float | None
    criteria: dict[str, CriterionVerdict]
    flagged: bool
    missing_criteria: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    score = float(value)
    return score if math.isfinite(score) else None


def _sample_value(sample: object) -> tuple[float | None, str | None]:
    if isinstance(sample, Mapping):
        score = _numeric(sample.get("score"))
        explanation = sample.get("explanation")
        return score, explanation if isinstance(explanation, str) and explanation else None
    return _numeric(sample), None


def _sample_agreement(scores: Sequence[float]) -> float | None:
    """Mean pairwise exact-score Cohen's kappa across repeated judge samples."""
    if len(scores) < 2:
        return None
    pairwise = [
        cohens_kappa([left], [right])
        for index, left in enumerate(scores)
        for right in scores[index + 1:]
    ]
    return sum(pairwise) / len(pairwise)


def score_rubric(
    rubric: Rubric,
    samples: Mapping[str, Sequence[object]],
) -> RubricVerdict:
    """Aggregate per-criterion judge samples into a fail-closed rubric verdict.

    Samples may be raw numeric scores or ``{"score": ..., "explanation": ...}`` mappings.
    Missing, non-numeric, non-finite, and out-of-scale scores are dropped. If a criterion has
    no valid score, the overall is ``None`` and the verdict is flagged; no value is imputed.
    """
    criterion_names = {criterion.name for criterion in rubric.criteria}
    unknown = set(samples) - criterion_names
    if unknown:
        raise ValueError(f"judge samples contain unknown rubric criteria: {sorted(unknown)}")

    verdicts: dict[str, CriterionVerdict] = {}
    missing: list[str] = []
    weighted_total = 0.0
    total_weight = 0.0

    for criterion in rubric.criteria:
        lower, upper = criterion.scale
        valid_scores: list[float] = []
        explanations: list[str] = []
        for sample in samples.get(criterion.name, ()):
            score, explanation = _sample_value(sample)
            if score is None or not lower <= score <= upper:
                continue
            valid_scores.append(score)
            if explanation is not None:
                explanations.append(explanation)

        score = float(statistics.median(valid_scores)) if valid_scores else None
        agreement = _sample_agreement(valid_scores)
        verdicts[criterion.name] = CriterionVerdict(
            name=criterion.name,
            score=score,
            agreement=agreement,
            agreement_band=agreement_label(agreement) if agreement is not None else None,
            explanations=tuple(explanations),
            valid_samples=len(valid_scores),
        )
        if score is None:
            missing.append(criterion.name)
        else:
            weighted_total += score * criterion.weight
            total_weight += criterion.weight

    overall = None if missing else weighted_total / total_weight
    return RubricVerdict(
        rubric_id=rubric.id,
        overall_score=overall,
        criteria=verdicts,
        flagged=bool(missing),
        missing_criteria=tuple(missing),
    )


def analyze_loss_patterns(
    verdicts: Iterable[RubricVerdict],
    threshold: float,
) -> Counter[str]:
    """Rank criteria by how often they are missing or score below ``threshold``."""
    numeric_threshold = _numeric(threshold)
    if numeric_threshold is None:
        raise ValueError("loss-pattern threshold must be a finite number")

    counts: Counter[str] = Counter()
    for verdict in verdicts:
        for name, criterion in verdict.criteria.items():
            if criterion.score is None or criterion.score < numeric_threshold:
                counts[name] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return Counter(dict(ranked))
