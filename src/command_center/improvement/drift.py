"""
Phase 5 — drift detection + formal canary analysis.

Production ML already has the operational playbook the autonomy frontier needs: drift
detection (PSI, KL/JS divergence, KS test) and canary analysis with automated rollback.
This module ports those statistics in pure stdlib and a `CanaryAnalysis` that compares a
challenger (canary) against the concurrent champion using the error-DIFFERENCE approach
(compare canary vs stable, not absolute) to cut false-positive rollbacks.

Safety note: automated *rollback* is the safe direction and is already authorized for
reversible/local/within-tier targets — this module only decides *whether* a canary regressed
and produces reasons. It never promotes or expands traffic on ambiguous results.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---- distribution drift -----------------------------------------------------

def _bin_props(samples: list[float], edges: list[float]) -> list[float]:
    bins = len(edges) + 1
    counts = [0] * bins
    for x in samples:
        b = 0
        while b < bins - 1 and x > edges[b]:
            b += 1
        counts[b] += 1
    n = len(samples)
    return [c / n for c in counts] if n else [0.0] * bins


def psi(expected: list[float], actual: list[float], *, bins: int = 10,
        eps: float = 1e-6) -> float:
    """Population Stability Index between two samples (quantile bins from ``expected``).
    Rule of thumb: < 0.1 stable, 0.1–0.2 moderate shift, > 0.2 significant shift."""
    if len(expected) < bins or not actual:
        raise ValueError("psi needs >= `bins` expected samples and a non-empty actual set")
    e = sorted(expected)
    n = len(e)
    edges = [e[min(n - 1, (i * n) // bins)] for i in range(1, bins)]
    pe = _bin_props(expected, edges)
    pa = _bin_props(actual, edges)
    return sum((a - x) * math.log((a + eps) / (x + eps)) for x, a in zip(pe, pa))


def psi_label(value: float) -> str:
    if value < 0.1:
        return "stable"
    if value < 0.2:
        return "moderate"
    return "significant"


def kl_divergence(p: list[float], q: list[float], *, eps: float = 1e-12) -> float:
    """KL(p || q) for probability vectors of equal length. Asymmetric, >= 0."""
    if len(p) != len(q):
        raise ValueError("kl_divergence requires equal-length distributions")
    return sum(pi * math.log((pi + eps) / (qi + eps)) for pi, qi in zip(p, q) if pi > 0)


def js_divergence(p: list[float], q: list[float]) -> float:
    """Jensen-Shannon divergence — symmetric, bounded by ln(2)."""
    if len(p) != len(q):
        raise ValueError("js_divergence requires equal-length distributions")
    m = [(pi + qi) / 2 for pi, qi in zip(p, q)]
    return 0.5 * kl_divergence(p, m) + 0.5 * kl_divergence(q, m)


def ks_statistic(a: list[float], b: list[float]) -> float:
    """Two-sample Kolmogorov-Smirnov statistic: the max gap between the two empirical CDFs."""
    if not a or not b:
        raise ValueError("ks_statistic needs two non-empty samples")
    grid = sorted(set(a) | set(b))
    na, nb = len(a), len(b)
    sa, sb = sorted(a), sorted(b)

    def cdf(sorted_xs, n, v):
        # fraction <= v
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if sorted_xs[mid] <= v:
                lo = mid + 1
            else:
                hi = mid
        return lo / n
    return max(abs(cdf(sa, na, v) - cdf(sb, nb, v)) for v in grid)


@dataclass
class DriftReport:
    psi: float
    psi_label: str
    js: float
    ks: float
    drifted: bool

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def drift_report(baseline: list[float], current: list[float], *, bins: int = 10,
                 psi_threshold: float = 0.2) -> DriftReport:
    """Full distribution-drift report between a baseline and a current sample."""
    p_val = psi(baseline, current, bins=bins)
    # coarse histograms for JS (shared edges from baseline quantiles)
    e = sorted(baseline)
    n = len(e)
    edges = [e[min(n - 1, (i * n) // bins)] for i in range(1, bins)]
    pe, pa = _bin_props(baseline, edges), _bin_props(current, edges)
    return DriftReport(psi=p_val, psi_label=psi_label(p_val),
                       js=js_divergence(pe, pa), ks=ks_statistic(baseline, current),
                       drifted=p_val >= psi_threshold)


# ---- formal canary analysis (champion vs challenger) ------------------------

@dataclass
class CanaryVerdict:
    regression: bool
    reasons: list[str] = field(default_factory=list)
    per_metric: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"regression": self.regression, "reasons": self.reasons,
                "per_metric": self.per_metric}


def evaluate_canary(active: dict, canary: dict, metric_specs: list[dict],
                    *, tolerance: float = 1e-9) -> CanaryVerdict:
    """Compare a canary (challenger) to the concurrent champion per metric. A metric whose
    canary value is worse than the champion beyond its tolerated regression is a regression;
    any SAFETY-metric regression forces it. Mirrors the runner's metric semantics."""
    reasons: list[str] = []
    per: dict = {}
    for m in metric_specs:
        name = m["name"]
        if name not in active or name not in canary:
            continue
        a, c = active[name], canary[name]
        good = (c - a) if m.get("direction", "increase") == "increase" else (a - c)
        regressed = good < -(m.get("maximum_regression") or 0.0) - tolerance
        per[name] = {"active": a, "canary": c, "delta_good": good, "regressed": regressed}
        if regressed:
            tag = " (SAFETY)" if m.get("safety") else ""
            reasons.append(f"{name} regressed by {-good:.4g}{tag}")
    return CanaryVerdict(regression=bool(reasons), reasons=reasons, per_metric=per)


def ramp_schedule(steps: list[int] | None = None) -> list[int]:
    """Progressive-delivery traffic ramp (percent). Default 5 → 20 → 50 → 100; each gate is a
    human/automated metric check before widening — never widen automatically on ambiguity."""
    steps = steps or [5, 20, 50, 100]
    if steps != sorted(steps) or steps[-1] != 100 or any(s <= 0 for s in steps):
        raise ValueError("ramp must be strictly increasing positive percents ending at 100")
    return steps
