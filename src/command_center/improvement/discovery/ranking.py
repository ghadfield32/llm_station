"""
Prioritization of a large candidate set: ICE, RICE, WSJF, and VOI.

Layered by design (addendum Topic 5):
  * ICE   — Impact × Confidence × Ease, fast first-pass triage.
  * RICE  — Reach × Impact × Confidence ÷ Effort, for feature-level (Full Idea) items.
  * WSJF  — Cost of Delay ÷ Job Size, for portfolio sequencing; specifically RESCUES
            security/risk-reduction work (CVEs, tech-debt) that pure value scoring buries.
  * VOI   — Value of Information: rank experiments by expected decision-uncertainty reduction
            vs cost — the principled answer to "is this experiment worth the budget?"

Pure functions over a `Finding`; deterministic.
"""
from __future__ import annotations

from .findings import Finding

_EPS = 1e-9


def ice(f: Finding) -> float:
    """Impact × Confidence × Ease (0..1)."""
    return f.impact * f.confidence * f.ease


def rice(f: Finding) -> float:
    """Reach × Impact × Confidence ÷ Effort."""
    return (f.reach * f.impact * f.confidence) / max(f.effort, _EPS)


def cost_of_delay(f: Finding) -> float:
    """SAFe Cost of Delay = business value + time criticality + risk-reduction/opportunity.
    Using impact as the value proxy. This is what lifts CVE/debt work up the queue."""
    return f.impact + f.time_criticality + f.risk_reduction


def wsjf(f: Finding) -> float:
    """Weighted Shortest Job First = Cost of Delay ÷ Job Size."""
    return cost_of_delay(f) / max(f.effort, _EPS)


def voi(f: Finding) -> float:
    """Value of Information ≈ (value if resolved × P(changes decision)) ÷ expected cost."""
    return (f.voi_value * f.voi_prob) / max(f.cost, _EPS)


_METHODS = {"ice": ice, "rice": rice, "wsjf": wsjf, "voi": voi}


def score(f: Finding, method: str = "wsjf") -> float:
    if method not in _METHODS:
        raise ValueError(f"unknown ranking method {method!r}; use {sorted(_METHODS)}")
    return _METHODS[method](f)


def rank(findings: list[Finding], method: str = "wsjf") -> list[tuple[Finding, float]]:
    """Findings paired with their score, best-first. Deterministic (ties keep input order)."""
    scored = [(f, score(f, method)) for f in findings]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def confidence_band(f: Finding, *, half_width: float = 0.15) -> tuple[float, float]:
    """A reported confidence interval around the point confidence — never collapse uncertainty
    to a single number. Width can shrink with more corroborating evidence (detail['n_sources'])."""
    n = max(1, int(f.detail.get("n_sources", 1)))
    hw = half_width / (n ** 0.5)
    return (max(0.0, f.confidence - hw), min(1.0, f.confidence + hw))
