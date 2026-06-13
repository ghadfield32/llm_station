"""
Self-improvement metrics — the loop measuring its OWN rate of improvement.

If the daily scan is the engine, these are the instruments. Pure stdlib, deterministic, and
honest about missing data (a median over no deploys is `None`, never a fabricated 0):

  * DORA — deployment frequency, lead time for changes, change-failure rate, MTTR, read
    straight from the experiment lifecycle (a PROMOTED event is a deploy; a later ROLLED_BACK
    is a failure). These are the industry's accepted delivery-performance metrics.
  * Acceptance rate by pillar / rollback rate / cost-per-accepted-improvement — is the loop
    proposing things humans actually accept, and at what unit cost?
  * Negative-result-memory hit rate — how often the scan correctly DECLINED to re-propose a
    known dead end. A loop that doesn't repeat its mistakes should show this rising.
  * Convergence power-law fit  AP*(N) ≈ a − b·N^(−c) — are returns to additional improvement
    effort diminishing (and toward what asymptote a)? Fit with no SciPy: for a fixed exponent c
    the model is linear in (a, b), so we grid-search c and solve the rest in closed form.
  * BWT / FWT (Gradient Episodic Memory) — does improving a new capability help or hurt the
    ones we already had (backward transfer) and the ones we haven't trained yet (forward)?
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .registry import ExperimentRegistry

# pillar 4-char code -> pillar name, to attribute a scan-drafted experiment to its pillar
_PILLAR_PREFIX = {
    "auto": "automation", "stru": "structure", "upda": "updated_metrics",
    "code": "code_quality", "rule": "rules_standards", "data": "data_handling",
    "full": "full_idea", "reli": "reliability_observability", "cost": "cost_finops",
}


def _parse(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError) as e:
        raise ValueError(f"un-parseable timestamp {ts!r}") from e


def _hours(a: str, b: str) -> float:
    return (_parse(b) - _parse(a)).total_seconds() / 3600.0


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


# ===========================================================================
# Lifecycle timelines (the substrate for DORA + acceptance + rollback)
# ===========================================================================

@dataclass
class ExperimentTimeline:
    experiment_id: str
    group: str                       # pillar (for scan cards) or target_type
    created_at: str
    promoted_at: str | None = None
    rolled_back_at: str | None = None
    terminal_status: str | None = None

    @property
    def accepted(self) -> bool:
        return self.promoted_at is not None

    @property
    def failed_in_prod(self) -> bool:
        return self.promoted_at is not None and self.rolled_back_at is not None


def _group_of(experiment_id: str, target_type: str) -> str:
    if experiment_id.startswith("EXP-scan-"):
        code = experiment_id.split("-")[2][:4]
        return _PILLAR_PREFIX.get(code, target_type)
    return target_type


def timelines_from_registry(reg: ExperimentRegistry) -> list[ExperimentTimeline]:
    """Read each experiment's PROMOTED / ROLLED_BACK event timestamps from the Ledger."""
    out: list[ExperimentTimeline] = []
    for row in reg.list_experiments():
        eid = row["experiment_id"]
        promoted_at = rolled_back_at = None
        for ev in reg.events(eid):
            if ev["kind"] == "PROMOTED":
                promoted_at = ev["ts"]
            elif ev["kind"] == "ROLLED_BACK":
                rolled_back_at = ev["ts"]
        out.append(ExperimentTimeline(
            experiment_id=eid, group=_group_of(eid, row["target_type"]),
            created_at=row["created_at"], promoted_at=promoted_at,
            rolled_back_at=rolled_back_at, terminal_status=row["status"]))
    return out


# ===========================================================================
# DORA
# ===========================================================================

@dataclass
class DoraMetrics:
    deploys: int
    window_days: float
    deployment_frequency_per_week: float
    lead_time_hours_median: float | None
    change_failure_rate: float
    mttr_hours_median: float | None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def compute_dora(timelines: list[ExperimentTimeline], *, window_days: float,
                 now_iso: str) -> DoraMetrics:
    if window_days <= 0:
        raise ValueError("window_days must be > 0")
    now = _parse(now_iso)
    horizon = now.timestamp() - window_days * 86400.0
    lead_times: list[float] = []
    mttrs: list[float] = []
    deploys = 0
    failures = 0
    for t in timelines:
        if t.promoted_at is None:
            continue
        if _parse(t.promoted_at).timestamp() < horizon:
            continue                                   # promoted before the window
        deploys += 1
        lead_times.append(_hours(t.created_at, t.promoted_at))
        if t.rolled_back_at is not None:
            failures += 1
            mttrs.append(_hours(t.promoted_at, t.rolled_back_at))
    freq = deploys / (window_days / 7.0)
    cfr = failures / deploys if deploys else 0.0
    return DoraMetrics(
        deploys=deploys, window_days=window_days, deployment_frequency_per_week=freq,
        lead_time_hours_median=_median(lead_times), change_failure_rate=cfr,
        mttr_hours_median=_median(mttrs))


# ===========================================================================
# Acceptance / rollback / unit cost
# ===========================================================================

@dataclass
class GroupAcceptance:
    group: str
    accepted: int
    total: int

    @property
    def rate(self) -> float:
        return self.accepted / self.total if self.total else 0.0


def acceptance_by_group(timelines: list[ExperimentTimeline]) -> list[GroupAcceptance]:
    acc: dict[str, list[int]] = {}
    for t in timelines:
        a = acc.setdefault(t.group, [0, 0])
        a[1] += 1
        if t.accepted:
            a[0] += 1
    return [GroupAcceptance(g, a[0], a[1]) for g, a in sorted(acc.items())]


def rollback_rate(timelines: list[ExperimentTimeline]) -> float:
    promoted = [t for t in timelines if t.accepted]
    if not promoted:
        return 0.0
    return sum(1 for t in promoted if t.failed_in_prod) / len(promoted)


def cost_per_accepted(total_cost_usd: float, accepted_count: int) -> float | None:
    """Unit economics of the loop. None when nothing has been accepted yet (no fake 0)."""
    if total_cost_usd < 0:
        raise ValueError("total_cost_usd must be >= 0")
    if accepted_count <= 0:
        return None
    return total_cost_usd / accepted_count


def negative_result_hit_rate(n_suppressed_negative: int, n_findings: int) -> float:
    """Fraction of findings the scan correctly declined as known dead ends."""
    if n_suppressed_negative < 0 or n_findings < 0:
        raise ValueError("counts must be >= 0")
    if n_suppressed_negative > n_findings:
        raise ValueError("suppressed cannot exceed total findings")
    return n_suppressed_negative / n_findings if n_findings else 0.0


# ===========================================================================
# Convergence: AP*(N) ≈ a − b·N^(−c)
# ===========================================================================

@dataclass
class PowerLawFit:
    a: float                 # estimated asymptote (ceiling) of the improvement curve
    b: float                 # gap scale
    c: float                 # decay exponent (> 0 => diminishing returns)
    r2: float                # goodness of fit
    n_points: int

    def predict(self, n: float) -> float:
        return self.a - self.b * (n ** (-self.c))


def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Ordinary least squares y = intercept + slope·x; returns (intercept, slope, sse)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    sse = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    return intercept, slope, sse


def fit_convergence(ns: list[int], aps: list[float]) -> PowerLawFit:
    """Fit AP*(N) ≈ a − b·N^(−c). For fixed c the model is linear in (a, b):
    AP = a − b·x with x = N^(−c), so we grid-search c (coarse then refined) and solve a,b in
    closed form at each c. Deterministic; no SciPy. Needs ≥3 points with varying N."""
    if len(ns) != len(aps):
        raise ValueError("ns and aps must be the same length")
    if len(ns) < 3:
        raise ValueError("need at least 3 points to fit 3 parameters")
    if any(n <= 0 for n in ns):
        raise ValueError("all N must be > 0")
    if len(set(ns)) < 2:
        raise ValueError("N values must vary")
    my = sum(aps) / len(aps)
    sst = sum((y - my) ** 2 for y in aps) or 1e-12

    def best_over(c_values: list[float]) -> tuple[float, float, float, float]:
        best = None
        for c in c_values:
            x = [n ** (-c) for n in ns]
            intercept, slope, sse = _linreg(x, aps)
            if best is None or sse < best[3]:
                best = (intercept, -slope, c, sse)   # a=intercept, b=-slope
        assert best is not None
        return best

    coarse = [i / 20.0 for i in range(2, 61)]                     # c in [0.10, 3.00] step 0.05
    a, b, c, sse = best_over(coarse)
    fine = [c + d / 200.0 for d in range(-9, 10) if c + d / 200.0 > 0]   # ±0.045 step 0.005
    a, b, c, sse = best_over(fine)
    return PowerLawFit(a=a, b=b, c=c, r2=1.0 - sse / sst, n_points=len(ns))


# ===========================================================================
# Transfer: BWT / FWT (Lopez-Paz & Ranzato, GEM)
# ===========================================================================

def _square(R: list[list[float]]) -> int:
    t = len(R)
    if t < 2:
        raise ValueError("transfer needs at least 2 tasks")
    if any(len(row) != t for row in R):
        raise ValueError("R must be a square T×T matrix")
    return t


def bwt(R: list[list[float]]) -> float:
    """Backward transfer: mean change on each earlier task i after learning the final task,
    R[T-1][i] − R[i][i]. Positive = learning later tasks HELPED earlier ones; negative =
    forgetting."""
    t = _square(R)
    return sum(R[t - 1][i] - R[i][i] for i in range(t - 1)) / (t - 1)


def fwt(R: list[list[float]], baseline: list[float]) -> float:
    """Forward transfer: mean of R[i-1][i] − baseline[i] for i≥1 — how much having learned the
    previous tasks helps a task BEFORE it is trained, vs its at-random baseline."""
    t = _square(R)
    if len(baseline) != t:
        raise ValueError("baseline must have one entry per task")
    return sum(R[i - 1][i] - baseline[i] for i in range(1, t)) / (t - 1)


# ===========================================================================
# Roll-up
# ===========================================================================

@dataclass
class SelfImprovementSnapshot:
    dora: DoraMetrics
    acceptance: list[GroupAcceptance] = field(default_factory=list)
    rollback_rate: float = 0.0
    cost_per_accepted_usd: float | None = None
    negative_hit_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "dora": self.dora.to_dict(),
            "acceptance": [{"group": g.group, "accepted": g.accepted,
                            "total": g.total, "rate": g.rate} for g in self.acceptance],
            "rollback_rate": self.rollback_rate,
            "cost_per_accepted_usd": self.cost_per_accepted_usd,
            "negative_hit_rate": self.negative_hit_rate,
        }


def snapshot(reg: ExperimentRegistry, *, window_days: float, now_iso: str,
             total_cost_usd: float = 0.0, n_suppressed_negative: int = 0,
             n_findings: int = 0) -> SelfImprovementSnapshot:
    timelines = timelines_from_registry(reg)
    dora = compute_dora(timelines, window_days=window_days, now_iso=now_iso)
    accepted = sum(1 for t in timelines if t.accepted)
    return SelfImprovementSnapshot(
        dora=dora, acceptance=acceptance_by_group(timelines),
        rollback_rate=rollback_rate(timelines),
        cost_per_accepted_usd=cost_per_accepted(total_cost_usd, accepted),
        negative_hit_rate=negative_result_hit_rate(n_suppressed_negative, n_findings))
