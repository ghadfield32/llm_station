"""Adaptive-rubric LLM-as-judge runner, supporting evidence only.

The local judge call is injected as ``judge_runner``. This module never starts a model,
contacts a provider, or promotes a result; it only applies the shared framework control flow
and normalizes reported rubric scores.
"""
from __future__ import annotations

import math
from numbers import Real

from .runner import FrameworkResult, run_framework

FRAMEWORK = "rubric_judge"


def _numeric_score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    score = float(value)
    return score if math.isfinite(score) else None


def parse_rubric_judge(raw: dict, name: str, spec) -> list[FrameworkResult]:
    """Normalize per-criterion ``{"score", "explanation"}`` judge JSON.

    Accepted shapes are a direct criterion mapping, a mapping under ``criteria``, or one
    top-level score payload. Missing/non-numeric scores remain ``None``.
    """
    if not isinstance(raw, dict):
        raw = {}

    if isinstance(raw.get("criteria"), dict):
        payloads = raw["criteria"]
    elif "score" in raw or "explanation" in raw:
        payloads = {"overall": raw}
    else:
        payloads = raw

    results: list[FrameworkResult] = []
    for criterion, payload in payloads.items():
        score = None
        explanation = None
        n_samples = None
        if isinstance(payload, dict):
            score = _numeric_score(payload.get("score"))
            raw_explanation = payload.get("explanation")
            if isinstance(raw_explanation, str) and raw_explanation:
                explanation = raw_explanation
            raw_n = payload.get("n_samples")
            if isinstance(raw_n, int) and not isinstance(raw_n, bool) and raw_n >= 1:
                n_samples = raw_n
        note = f"Rubric judge {criterion} score (supporting evidence only)"
        if explanation is not None:
            note = f"{note}: {explanation}"
        results.append(FrameworkResult(
            framework=name,
            informs_role=spec.informs_role,
            status="ok",
            note=note,
            metric="rubric_score",
            score=score,
            dataset=str(criterion),
            n_samples=n_samples,
        ))

    if not results:
        results.append(FrameworkResult(
            framework=name,
            informs_role=spec.informs_role,
            status="error",
            note="Rubric judge output had no criterion scores (supporting evidence only)",
            metric="rubric_score",
        ))
    return results


def run(spec, *, judge_runner=None, available_fn=None) -> list[FrameworkResult]:
    """Run only through an explicitly injected local judge executor."""
    kwargs = {"parse_fn": parse_rubric_judge, "subprocess_runner": judge_runner}
    if available_fn is not None:
        kwargs["available_fn"] = available_fn
    return run_framework(FRAMEWORK, spec, **kwargs)
