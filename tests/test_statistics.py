"""Unit tests for the Phase-0 statistical toolkit, checked against closed-form / known
values. This is the measurement-science core, so it is tested hard."""
from __future__ import annotations

import math
import random

import pytest

from command_center.improvement.statistics import (
    normal_cdf, normal_ppf, chi2_sf, bootstrap_ci, bootstrap_diff,
    benjamini_hochberg, sample_ratio_mismatch, required_sample_size, achieved_mde,
    aa_test, msprt_pvalues, msprt_decision, cuped_adjust, mean, stdev,
)


# ---- primitives -------------------------------------------------------------

def test_normal_cdf_known_points():
    assert abs(normal_cdf(0.0) - 0.5) < 1e-12
    assert abs(normal_cdf(1.959964) - 0.975) < 1e-4
    assert abs(normal_cdf(-1.959964) - 0.025) < 1e-4


def test_normal_ppf_roundtrip():
    for p in (0.01, 0.1, 0.5, 0.8, 0.975, 0.999):
        assert abs(normal_cdf(normal_ppf(p)) - p) < 1e-6
    assert abs(normal_ppf(0.975) - 1.959964) < 1e-4


def test_chi2_sf_matches_closed_form_df1():
    # for df=1, P(χ² > x) == erfc(sqrt(x/2))
    for x in (0.5, 1.0, 3.8415, 6.635, 10.0):
        assert abs(chi2_sf(x, 1) - math.erfc(math.sqrt(x / 2))) < 1e-6
    assert abs(chi2_sf(3.8415, 1) - 0.05) < 1e-3      # the classic 1.96² critical value
    assert chi2_sf(0.0, 3) == 1.0


# ---- bootstrap --------------------------------------------------------------

def test_bootstrap_ci_contains_mean_and_is_deterministic():
    xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    ci1 = bootstrap_ci(xs, seed=42)
    ci2 = bootstrap_ci(xs, seed=42)
    assert ci1.low == ci2.low and ci1.high == ci2.high      # seeded -> reproducible
    assert ci1.low <= ci1.point <= ci1.high
    assert abs(ci1.point - 5.5) < 1e-9


def test_bootstrap_diff_detects_real_shift():
    baseline = [0.0] * 20
    candidate = [1.0] * 20
    res = bootstrap_diff(baseline, candidate, paired=True)
    assert res.diff == 1.0 and res.significant and res.ci.excludes(0.0)
    assert res.p_value < 0.05


def test_bootstrap_diff_null_is_not_significant():
    xs = [0.5, 0.4, 0.6, 0.55, 0.45, 0.5, 0.52, 0.48]
    res = bootstrap_diff(xs, xs, paired=True)        # identical -> no difference
    assert res.diff == 0.0 and not res.significant
    assert res.p_value > 0.05


# ---- Benjamini-Hochberg FDR -------------------------------------------------

def test_benjamini_hochberg_rejection_count():
    # thresholds k/m*alpha = [.01,.02,.03,.04,.05]; only the first two p's clear them
    p = [0.001, 0.008, 0.039, 0.041, 0.9]
    rejected, q = benjamini_hochberg(p, alpha=0.05)
    assert rejected == [True, True, False, False, False]
    assert all(0.0 <= qi <= 1.0 for qi in q)
    assert q[0] <= q[1] <= q[2]                       # monotone in sorted order


def test_benjamini_hochberg_all_or_none():
    assert benjamini_hochberg([], 0.05) == ([], [])
    rej, _ = benjamini_hochberg([0.9, 0.8, 0.95], 0.05)
    assert rej == [False, False, False]


# ---- SRM --------------------------------------------------------------------

def test_srm_balanced_split_ok():
    res = sample_ratio_mismatch([500, 500])
    assert not res.mismatch and res.p_value > 0.001 and res.chi2 < 1e-6


def test_srm_detects_imbalance():
    res = sample_ratio_mismatch([600, 400])          # chi2 = 40 -> p ~ 2.5e-10
    assert res.mismatch and res.p_value < 0.001
    assert abs(res.chi2 - 40.0) < 1e-6


def test_srm_small_imbalance_not_flagged():
    res = sample_ratio_mismatch([520, 480])          # chi2 = 1.6 -> p ~ 0.21
    assert not res.mismatch


# ---- power / sample size ----------------------------------------------------

def test_required_sample_size_matches_formula():
    # n per arm = 2 (z_{.975}+z_{.8})^2 sd^2 / mde^2 ; mde=.1 sd=1 -> ~1570
    n = required_sample_size(0.1, 1.0, alpha=0.05, power=0.8)
    assert 1560 <= n <= 1580


def test_sample_size_monotone_in_mde():
    big = required_sample_size(0.05, 1.0)
    small = required_sample_size(0.2, 1.0)
    assert big > small                                # smaller effect needs more data


def test_achieved_mde_inverse_consistency():
    n = required_sample_size(0.1, 1.0, alpha=0.05, power=0.8)
    assert abs(achieved_mde(n, 1.0, alpha=0.05, power=0.8) - 0.1) < 0.005


# ---- A/A false-positive control --------------------------------------------

def test_aa_false_positive_rate_near_alpha():
    # a homogeneous sample split repeatedly should rarely look 'significant'
    rng_sample = [math.sin(i) for i in range(80)]     # deterministic, no real effect
    res = aa_test(rng_sample, alpha=0.05, n_trials=120, seed=3)
    assert res.false_positive_rate <= 0.05 + 0.03     # near alpha, within tolerance
    assert res.within_tolerance


# ---- Phase 1: mSPRT always-valid stopping -----------------------------------

def test_msprt_no_peeking_false_positive_control():
    # THE always-valid property: under H0 (mean-0 stream), monitoring continuously and
    # stopping the first time p<=alpha must reject in <= alpha of streams (no peeking penalty).
    rng = random.Random(20260613)
    alpha, n_streams = 0.05, 400
    rejected = 0
    for _ in range(n_streams):
        stream = [rng.gauss(0.0, 1.0) for _ in range(60)]   # known sigma=1
        if msprt_decision(stream, tau=1.0, alpha=alpha, sigma=1.0).stopped:
            rejected += 1
    fp_rate = rejected / n_streams
    assert fp_rate <= alpha + 0.02            # bounded by alpha (Ville's inequality)


def test_msprt_stops_early_on_real_effect():
    rng = random.Random(7)
    stream = [rng.gauss(0.6, 1.0) for _ in range(200)]      # real positive effect
    res = msprt_decision(stream, tau=0.6, alpha=0.05, sigma=1.0)
    assert res.stopped and res.p_value <= 0.05
    assert res.stop_n < 200                                  # stopped before exhausting data


def test_msprt_pvalue_is_monotone_nonincreasing():
    pv = msprt_pvalues([0.4] * 30, tau=0.4, sigma=1.0)
    assert all(pv[i] >= pv[i + 1] for i in range(len(pv) - 1))   # running minimum
    assert pv[0] == 1.0 and pv[-1] < pv[0]      # evidence accumulates -> p decreases


def test_msprt_rejects_bad_input():
    with pytest.raises(ValueError):
        msprt_pvalues([], tau=1.0)
    with pytest.raises(ValueError):
        msprt_pvalues([0.1, 0.2], tau=0.0)


# ---- Phase 1: CUPED variance reduction --------------------------------------

def test_cuped_reduces_variance_and_preserves_mean():
    rng = random.Random(11)
    x = [rng.gauss(0, 1) for _ in range(500)]               # pre-experiment covariate
    y = [xi + rng.gauss(0, 0.3) for xi in x]                # strongly correlated metric
    res = cuped_adjust(y, x)
    assert res.variance_reduction > 0.5                     # ~ the Bing "halve the variance"
    assert abs(mean(res.adjusted) - mean(y)) < 1e-9         # mean preserved exactly
    assert stdev(res.adjusted) < stdev(y)                   # tighter


def test_cuped_uncorrelated_covariate_barely_helps():
    rng = random.Random(13)
    x = [rng.gauss(0, 1) for _ in range(400)]
    y = [rng.gauss(0, 1) for _ in range(400)]               # independent of x
    res = cuped_adjust(y, x)
    assert res.variance_reduction < 0.1                     # no free lunch when uncorrelated


def test_cuped_rejects_bad_input():
    with pytest.raises(ValueError):
        cuped_adjust([1, 2, 3], [1, 2])                     # length mismatch
    with pytest.raises(ValueError):
        cuped_adjust([1, 2, 3], [5, 5, 5])                  # zero-variance covariate
