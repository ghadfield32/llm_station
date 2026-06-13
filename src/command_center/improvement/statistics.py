"""
Phase-0 statistical foundations for trustworthy baseline-vs-candidate comparison.

Pure standard library (no numpy/scipy) — consistent with the lean control plane. Every
function here feeds the *Proposed → Verified* portion of the lifecycle: it decides whether
a candidate is statistically *eligible* to reach a human, and it is evidence the independent
verifier recomputes. None of it can promote; significance only gates eligibility and the
verifier's reject path.

Toolkit (mission research roadmap, Area A1):
  * bootstrap confidence intervals (distribution-free; the honest tool at small n)
  * paired and unpaired difference tests via the bootstrap
  * Benjamini-Hochberg FDR correction across the many metrics/targets tested
  * Sample Ratio Mismatch (SRM) chi-squared check (invalidate at p < 0.001)
  * pre-registered sample-size / minimum-detectable-effect (MDE) power analysis
  * an A/A helper for false-positive-rate control

The bootstrap is seeded (deterministic) so the verifier reproduces the implementer's
numbers exactly — the same independence guarantee the rest of the loop relies on.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


# ---- normal + chi-squared primitives (stdlib only) --------------------------

def normal_cdf(z: float) -> float:
    """Standard normal CDF Φ(z)."""
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def normal_ppf(p: float) -> float:
    """Inverse standard normal (Acklam's rational approximation; |error| < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("normal_ppf requires 0 < p < 1")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _gammln(x: float) -> float:
    cof = [76.18009172947146, -86.50532032941677, 24.01409824083091,
           -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5]
    y = x
    tmp = x + 5.5
    tmp -= (x + 0.5) * math.log(tmp)
    ser = 1.000000000190015
    for c in cof:
        y += 1
        ser += c / y
    return -tmp + math.log(2.5066282746310005 * ser / x)


def _gammq(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) (Numerical Recipes gser/gcf)."""
    if x < 0 or a <= 0:
        raise ValueError("invalid args to _gammq")
    if x == 0:
        return 1.0
    if x < a + 1.0:                                  # series for P, then Q = 1 - P
        ap, total, term = a, 1.0 / a, 1.0 / a
        for _ in range(1000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-12:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - _gammln(a))
    # continued fraction for Q directly
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - _gammln(a)) * h


def chi2_sf(x: float, df: int) -> float:
    """Upper tail P(χ²_df > x)."""
    if x <= 0:
        return 1.0
    return _gammq(df / 2.0, x / 2.0)


# ---- summary stats ----------------------------------------------------------

def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs) -> float:
    xs = list(xs)
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


# ---- bootstrap CIs + difference tests ---------------------------------------

@dataclass
class CI:
    point: float
    low: float
    high: float

    def excludes(self, value: float) -> bool:
        return value < self.low or value > self.high


def bootstrap_ci(xs, *, alpha: float = 0.05, n_resamples: int = 2000,
                 seed: int = 12345, statistic=mean) -> CI:
    """Percentile bootstrap CI for ``statistic`` (default mean). Deterministic given seed."""
    xs = list(xs)
    if not xs:
        return CI(0.0, 0.0, 0.0)
    rng = random.Random(seed)
    n = len(xs)
    stats = []
    for _ in range(n_resamples):
        sample = [xs[rng.randrange(n)] for _ in range(n)]
        stats.append(statistic(sample))
    stats.sort()
    lo = stats[max(0, int((alpha / 2) * n_resamples))]
    hi = stats[min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))]
    return CI(point=statistic(xs), low=lo, high=hi)


@dataclass
class DiffResult:
    diff: float                 # candidate - baseline, in the metric's native units
    ci: CI                      # bootstrap CI of the difference
    p_value: float              # two-sided bootstrap p-value
    significant: bool           # CI excludes 0 at the chosen alpha
    n_baseline: int
    n_candidate: int
    paired: bool

    def to_dict(self) -> dict:
        return {"diff": self.diff, "ci_low": self.ci.low, "ci_high": self.ci.high,
                "p_value": self.p_value, "significant": self.significant,
                "n_baseline": self.n_baseline, "n_candidate": self.n_candidate,
                "paired": self.paired}


def bootstrap_diff(baseline, candidate, *, paired: bool = False, alpha: float = 0.05,
                   n_resamples: int = 2000, seed: int = 12345) -> DiffResult:
    """Bootstrap the difference in means (candidate - baseline). Paired bootstraps the
    per-item differences (requires equal length); unpaired resamples each arm."""
    b = list(baseline)
    c = list(candidate)
    observed = mean(c) - mean(b)
    rng = random.Random(seed)
    diffs = []
    if paired:
        if len(b) != len(c):
            raise ValueError("paired bootstrap requires equal-length samples")
        pair_d = [ci - bi for bi, ci in zip(b, c)]
        n = len(pair_d)
        if n == 0:
            return DiffResult(0.0, CI(0, 0, 0), 1.0, False, 0, 0, True)
        for _ in range(n_resamples):
            diffs.append(mean([pair_d[rng.randrange(n)] for _ in range(n)]))
    else:
        nb, nc = len(b), len(c)
        if nb == 0 or nc == 0:
            return DiffResult(observed, CI(observed, observed, observed), 1.0, False, nb, nc, False)
        for _ in range(n_resamples):
            mb = mean([b[rng.randrange(nb)] for _ in range(nb)])
            mc = mean([c[rng.randrange(nc)] for _ in range(nc)])
            diffs.append(mc - mb)
    diffs.sort()
    lo = diffs[max(0, int((alpha / 2) * n_resamples))]
    hi = diffs[min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))]
    # two-sided bootstrap p-value via the proportion on the wrong side of 0
    frac_le = sum(1 for d in diffs if d <= 0) / len(diffs)
    frac_ge = sum(1 for d in diffs if d >= 0) / len(diffs)
    p = min(1.0, 2 * min(frac_le, frac_ge))
    ci = CI(point=observed, low=lo, high=hi)
    return DiffResult(diff=observed, ci=ci, p_value=p, significant=ci.excludes(0.0),
                      n_baseline=len(b), n_candidate=len(c), paired=paired)


# ---- mSPRT: always-valid sequential testing (no peeking penalty) ------------

@dataclass
class MSPRTResult:
    stopped: bool              # did the always-valid p-value ever cross alpha?
    stop_n: int                # sample index at which it first crossed (or total n)
    p_value: float             # final always-valid p-value (running minimum of 1/Λ_n)
    n: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def msprt_pvalues(diffs, *, tau: float, sigma: float | None = None) -> list[float]:
    """Always-valid p-values for a one-sample mixture SPRT of mean(diffs)==0, with a
    N(0, τ²) mixing prior over the alternative (Robbins / Johari-Pekelis-Walsh). Returns the
    running-minimum p-value p_n = min_{m≤n} 1/Λ_m, valid under continuous monitoring.

    sigma is the known per-observation SD; if omitted it is the plug-in sample SD (the GAVI
    variant). Raises on empty input or non-positive tau — no silent fallback."""
    xs = list(diffs)
    if not xs:
        raise ValueError("msprt_pvalues requires at least one observation")
    if tau <= 0:
        raise ValueError("tau (mixing SD) must be positive")
    s2 = (sigma ** 2) if sigma is not None else max(stdev(xs) ** 2, 1e-12)
    t2 = tau ** 2
    p = 1.0
    out: list[float] = []
    total = 0.0
    for n, x in enumerate(xs, start=1):
        total += x
        xbar = total / n
        denom = s2 + n * t2
        # work in log space: 1/Λ_n = exp(-log Λ_n) underflows to 0 (no exp overflow)
        log_lam = 0.5 * math.log(s2 / denom) + (n ** 2) * t2 * (xbar ** 2) / (2 * s2 * denom)
        inv_lam = math.exp(-log_lam)
        p = min(p, min(1.0, inv_lam))
        out.append(p)
    return out


def msprt_decision(diffs, *, tau: float, alpha: float = 0.05,
                   sigma: float | None = None) -> MSPRTResult:
    """Run the mSPRT and report the first sample at which the always-valid p-value crosses
    alpha (the point an early-stopping experiment could have stopped)."""
    pv = msprt_pvalues(diffs, tau=tau, sigma=sigma)
    for i, pp in enumerate(pv):
        if pp <= alpha:
            return MSPRTResult(stopped=True, stop_n=i + 1, p_value=pv[-1], n=len(pv))
    return MSPRTResult(stopped=False, stop_n=len(pv), p_value=pv[-1], n=len(pv))


# ---- CUPED: variance reduction with a pre-experiment covariate --------------

@dataclass
class CupedResult:
    theta: float
    variance_reduction: float        # fraction of variance removed (0..1)
    adjusted: list[float]

    def to_dict(self) -> dict:
        return {"theta": self.theta, "variance_reduction": self.variance_reduction}


def cuped_adjust(y, x) -> CupedResult:
    """CUPED (Deng/Xu/Kohavi/Walker, WSDM 2013): Y_cuped = Y - θ(X - E[X]), θ=cov(Y,X)/var(X).
    Removes the variance in Y explained by the pre-experiment covariate X while preserving the
    mean (E[Y_cuped]=E[Y]). Raises on length mismatch or zero-variance covariate — no fallback."""
    y = list(y)
    x = list(x)
    if len(y) != len(x):
        raise ValueError("cuped_adjust requires equal-length y and x")
    if len(y) < 2:
        raise ValueError("cuped_adjust requires at least two observations")
    mx, my = mean(x), mean(y)
    var_x = sum((xi - mx) ** 2 for xi in x) / (len(x) - 1)
    if var_x <= 0:
        raise ValueError("covariate has zero variance; CUPED is undefined")
    cov_xy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / (len(y) - 1)
    theta = cov_xy / var_x
    adjusted = [yi - theta * (xi - mx) for yi, xi in zip(y, x)]
    var_y = sum((yi - my) ** 2 for yi in y) / (len(y) - 1)
    var_adj = stdev(adjusted) ** 2
    reduction = 0.0 if var_y <= 0 else max(0.0, 1.0 - var_adj / var_y)
    return CupedResult(theta=theta, variance_reduction=reduction, adjusted=adjusted)


# ---- multiple-testing correction --------------------------------------------

def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> tuple[list[bool], list[float]]:
    """Benjamini-Hochberg FDR. Returns (rejected[], q_values[]) in the INPUT order."""
    m = len(p_values)
    if m == 0:
        return [], []
    order = sorted(range(m), key=lambda i: p_values[i])
    q = [0.0] * m
    rejected = [False] * m
    # adjusted q-values with monotonicity from the largest p down
    prev = 1.0
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        val = min(prev, p_values[idx] * m / rank)
        q[idx] = val
        prev = val
    # rejection: largest k with p_(k) <= (k/m) alpha
    kmax = 0
    for rank in range(1, m + 1):
        if p_values[order[rank - 1]] <= (rank / m) * alpha:
            kmax = rank
    for rank in range(1, kmax + 1):
        rejected[order[rank - 1]] = True
    return rejected, q


# ---- sample ratio mismatch (SRM) --------------------------------------------

@dataclass
class SRMResult:
    chi2: float
    p_value: float
    mismatch: bool
    observed: list[int]
    expected: list[float]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def sample_ratio_mismatch(observed: list[int], expected_ratio: list[float] | None = None,
                          *, threshold: float = 0.001) -> SRMResult:
    """Chi-squared goodness-of-fit on assignment counts. A mismatch (p < threshold) means
    the baseline/candidate split is not what was intended — invalidate the experiment."""
    total = sum(observed)
    k = len(observed)
    if expected_ratio is None:
        expected_ratio = [1.0 / k] * k
    s = sum(expected_ratio)
    exp = [total * (r / s) for r in expected_ratio]
    chi2 = sum((o - e) ** 2 / e for o, e in zip(observed, exp) if e > 0)
    p = chi2_sf(chi2, df=k - 1) if k > 1 else 1.0
    return SRMResult(chi2=chi2, p_value=p, mismatch=p < threshold,
                     observed=list(observed), expected=exp)


# ---- power / sample size (two-sample, normal approx) ------------------------

def required_sample_size(mde: float, sd: float, *, alpha: float = 0.05,
                         power: float = 0.8) -> int:
    """Per-arm sample size to detect an absolute effect ``mde`` at given α and power."""
    if mde <= 0 or sd <= 0:
        return 0
    za = normal_ppf(1 - alpha / 2)
    zb = normal_ppf(power)
    n = 2 * (za + zb) ** 2 * (sd ** 2) / (mde ** 2)
    return int(math.ceil(n))


def achieved_mde(n_per_arm: int, sd: float, *, alpha: float = 0.05,
                 power: float = 0.8) -> float:
    """The smallest absolute effect detectable with ``n_per_arm`` samples per arm."""
    if n_per_arm <= 0 or sd <= 0:
        return float("inf")
    za = normal_ppf(1 - alpha / 2)
    zb = normal_ppf(power)
    return (za + zb) * sd * math.sqrt(2.0 / n_per_arm)


# ---- A/A false-positive control --------------------------------------------

@dataclass
class AAResult:
    n_trials: int
    false_positive_rate: float
    alpha: float
    within_tolerance: bool
    p_values: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["p_values"] = self.p_values[:50]   # cap for storage
        return d


@dataclass
class MetricStat:
    name: str
    direction: str
    baseline_ci: CI
    candidate_ci: CI
    diff: DiffResult
    q_value: float
    significant_fdr: bool
    improved: bool             # significant AND in the metric's good direction

    def to_dict(self) -> dict:
        return {"name": self.name, "direction": self.direction,
                "baseline": [self.baseline_ci.low, self.baseline_ci.point, self.baseline_ci.high],
                "candidate": [self.candidate_ci.low, self.candidate_ci.point, self.candidate_ci.high],
                "diff": self.diff.to_dict(), "q_value": self.q_value,
                "significant_fdr": self.significant_fdr, "improved": self.improved}


@dataclass
class StatisticalReport:
    experiment_id: str
    primary_metric: str | None
    primary_improved: bool
    primary_q_value: float | None
    underpowered: bool
    srm: SRMResult | None
    metric_stats: list[MetricStat] = field(default_factory=list)
    notes: str = ""
    # Phase-1 rigor on the primary metric (paired designs):
    primary_msprt_p: float | None = None          # always-valid p-value (no peeking penalty)
    primary_msprt_stop_n: int | None = None        # samples an early-stopping run needed
    primary_variance_reduction: float | None = None  # CUPED fraction of variance removed

    def to_dict(self) -> dict:
        return {"experiment_id": self.experiment_id, "primary_metric": self.primary_metric,
                "primary_improved": self.primary_improved, "primary_q_value": self.primary_q_value,
                "underpowered": self.underpowered,
                "srm": self.srm.to_dict() if self.srm else None,
                "metric_stats": [m.to_dict() for m in self.metric_stats], "notes": self.notes,
                "primary_msprt_p": self.primary_msprt_p,
                "primary_msprt_stop_n": self.primary_msprt_stop_n,
                "primary_variance_reduction": self.primary_variance_reduction}


def _infer_primary(metric_specs: list[dict]) -> str | None:
    for m in metric_specs:
        if m.get("required") and m.get("minimum_improvement") is not None:
            return m["name"]
    for m in metric_specs:
        if m.get("required") and not m.get("safety"):
            return m["name"]
    return metric_specs[0]["name"] if metric_specs else None


def analyze_experiment(experiment_id: str, metric_specs: list[dict], plan: dict,
                       baseline_samples: dict[str, list[float]],
                       candidate_samples: dict[str, list[float]]) -> StatisticalReport:
    """Multidimensional statistical comparison: per-metric bootstrap CIs + difference tests,
    Benjamini-Hochberg FDR across the tested metrics, SRM, and a power check on the primary
    metric. Pure evidence — it decides eligibility/verifier-reject, never promotion."""
    alpha = plan.get("alpha", 0.05)
    n_res = plan.get("n_resamples", 2000)
    seed = plan.get("seed", 12345)
    power = plan.get("power", 0.8)
    test_type = plan.get("test_type", "auto")
    primary = plan.get("primary_metric") or _infer_primary(metric_specs)
    dir_by_name = {m["name"]: m.get("direction", "increase") for m in metric_specs}

    tested = [m for m in metric_specs
              if baseline_samples.get(m["name"]) and candidate_samples.get(m["name"])]
    stats: list[MetricStat] = []
    pvals: list[float] = []
    for m in tested:
        name = m["name"]
        b, c = baseline_samples[name], candidate_samples[name]
        paired = test_type == "paired" or (test_type == "auto" and len(b) == len(c) and len(b) > 0)
        diff = bootstrap_diff(b, c, paired=paired, alpha=alpha, n_resamples=n_res, seed=seed)
        stats.append(MetricStat(
            name=name, direction=dir_by_name[name],
            baseline_ci=bootstrap_ci(b, alpha=alpha, n_resamples=n_res, seed=seed),
            candidate_ci=bootstrap_ci(c, alpha=alpha, n_resamples=n_res, seed=seed),
            diff=diff, q_value=1.0, significant_fdr=False, improved=False))
        pvals.append(diff.p_value)
    if pvals:
        rejected, qvals = benjamini_hochberg(pvals, alpha=alpha)
        for st, rej, q in zip(stats, rejected, qvals):
            st.q_value = q
            st.significant_fdr = rej
            good = (st.diff.diff > 0) if st.direction == "increase" else (st.diff.diff < 0)
            st.improved = rej and good

    primary_stat = next((s for s in stats if s.name == primary), None)
    underpowered = False
    srm = None
    msprt_p: float | None = None
    msprt_stop_n: int | None = None
    var_reduction: float | None = None
    improved = bool(primary_stat and primary_stat.improved)
    if primary is not None and primary_stat is not None:
        b_prim = baseline_samples.get(primary, [])
        c_prim = candidate_samples.get(primary, [])
        # power: underpowered if a pre-registered MDE can't be detected at the achieved n
        if plan.get("mde"):
            sd = stdev(b_prim + c_prim)
            if sd > 0:
                underpowered = len(c_prim) < required_sample_size(
                    plan["mde"], sd, alpha=alpha, power=power)
        # SRM on the per-arm sample counts (intended equal measurement)
        if len(b_prim) + len(c_prim) > 0:
            srm = sample_ratio_mismatch([len(b_prim), len(c_prim)])
        # Phase 1: on a paired primary, add the always-valid mSPRT p-value (no peeking
        # penalty) and a CUPED variance-reduction estimate (baseline = covariate).
        if len(b_prim) == len(c_prim) and len(b_prim) >= 2:
            diffs = [ci - bi for bi, ci in zip(b_prim, c_prim)]
            tau = plan.get("mde") or 0.1
            md = msprt_decision(diffs, tau=tau, alpha=alpha)
            msprt_p, msprt_stop_n = md.p_value, md.stop_n
            # the always-valid test must also agree before we call it an improvement
            improved = improved and md.p_value <= alpha
            # CUPED requires a varying covariate; skip cleanly when the baseline is constant
            if stdev(b_prim) > 0:
                var_reduction = cuped_adjust(c_prim, b_prim).variance_reduction

    return StatisticalReport(
        experiment_id=experiment_id, primary_metric=primary,
        primary_improved=improved,
        primary_q_value=primary_stat.q_value if primary_stat else None,
        underpowered=underpowered, srm=srm, metric_stats=stats,
        notes="no per-sample data for any metric" if not tested else "",
        primary_msprt_p=msprt_p, primary_msprt_stop_n=msprt_stop_n,
        primary_variance_reduction=var_reduction)


def aa_test(samples, *, alpha: float = 0.05, n_trials: int = 200, seed: int = 7,
            tolerance: float = 0.03) -> AAResult:
    """Split a homogeneous sample in half repeatedly; the fraction of 'significant'
    splits should sit near α. A large excess signals a broken test or biased estimator."""
    xs = list(samples)
    rng = random.Random(seed)
    n = len(xs)
    half = n // 2
    fps = 0
    pvals: list[float] = []
    for t in range(n_trials):
        shuffled = xs[:]
        rng.shuffle(shuffled)
        a, b = shuffled[:half], shuffled[half:2 * half]
        res = bootstrap_diff(a, b, paired=False, alpha=alpha, n_resamples=400, seed=seed + t)
        pvals.append(res.p_value)
        if res.significant:
            fps += 1
    fpr = fps / n_trials if n_trials else 0.0
    return AAResult(n_trials=n_trials, false_positive_rate=fpr, alpha=alpha,
                    within_tolerance=fpr <= alpha + tolerance, p_values=pvals)
