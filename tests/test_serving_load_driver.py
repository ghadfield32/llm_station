"""Concurrency-sweep load-driver tests. Deterministic: measure_fn + clock are injected, so no
live Ollama and no real timing. Covers sample collection, error counting, SweepPoint math, and
operating-point wiring."""
import itertools

import pytest

from command_center.improvement import serving_load_driver as sld
from command_center.improvement.serving_benchmark import ServingSample


def _sample(ttft=1.0, itl=0.05, ttlt=10.0, out=100, inp=2000):
    return ServingSample(ttft_s=ttft, itl_s=itl, ttlt_s=ttlt, output_tokens=out,
                         input_tokens=inp)


class _FakeClock:
    """Returns 0.0, wall, 0.0, wall, ... so each run_point measures exactly `wall` seconds."""
    def __init__(self, wall: float):
        self._it = itertools.cycle([0.0, wall])

    def __call__(self) -> float:
        return next(self._it)


def test_run_point_collects_all_samples():
    res = sld.run_point(lambda: _sample(), concurrency=8, clock=_FakeClock(1.0))
    assert len(res.samples) == 8
    assert res.n_errors == 0
    assert res.wall_seconds == pytest.approx(1.0)


def test_run_point_counts_failures_not_swallowed():
    def boom():
        raise RuntimeError("ollama down")
    res = sld.run_point(boom, concurrency=5, clock=_FakeClock(1.0))
    assert res.samples == []
    assert res.n_errors == 5


def test_run_point_rejects_zero_concurrency():
    with pytest.raises(ValueError):
        sld.run_point(lambda: _sample(), concurrency=0)


def test_point_to_sweep_computes_p90_and_rps():
    # 10 samples, wall 2s, concurrency 10 -> rps 5.0; p90 of constant ttlt is that value
    res = sld.PointResult(concurrency=10, samples=[_sample(ttft=2.0, ttlt=20.0)] * 10,
                          n_errors=0, wall_seconds=2.0)
    sp = sld.point_to_sweep(res)
    assert sp.rps == pytest.approx(5.0)
    assert sp.p90_ttft_s == pytest.approx(2.0)
    assert sp.p90_ttlt_s == pytest.approx(20.0)
    assert sp.error_rate == 0.0


def test_point_to_sweep_partial_errors_set_error_rate():
    res = sld.PointResult(concurrency=10, samples=[_sample()] * 8, n_errors=2, wall_seconds=1.0)
    sp = sld.point_to_sweep(res)
    assert sp.error_rate == pytest.approx(0.2)


def test_point_to_sweep_all_failed_is_unusable():
    res = sld.PointResult(concurrency=4, samples=[], n_errors=4, wall_seconds=3.0)
    sp = sld.point_to_sweep(res)
    assert sp.rps == 0.0
    assert sp.error_rate == 1.0
    assert sp.p90_ttlt_s == pytest.approx(3.0)   # observed wall, not a fabricated number


def test_run_sweep_one_point_per_concurrency():
    sweep = sld.run_sweep(lambda: _sample(ttlt=10.0), [1, 2, 4], clock=_FakeClock(1.0))
    assert [p.concurrency for p in sweep] == [1, 2, 4]
    assert [p.rps for p in sweep] == [1.0, 2.0, 4.0]   # wall=1s -> rps == concurrency


def test_sweep_and_operating_point_picks_highest_rps_under_slo():
    out = sld.sweep_and_operating_point(
        lambda: _sample(ttft=2.0, ttlt=20.0), "repo_triage",
        concurrency_points=[1, 2, 4, 8], slo_p90_ttft_s=4, slo_p90_ttlt_s=90,
        clock=_FakeClock(1.0))
    op = out["operating_point"]
    assert op["found"] is True
    assert op["concurrency"] == 8          # all pass SLO -> highest rps wins
    assert len(out["sweep"]) == 4


def test_sweep_and_operating_point_reports_no_fit_when_slo_too_tight():
    out = sld.sweep_and_operating_point(
        lambda: _sample(ttlt=20.0), "long_repo_reader",
        concurrency_points=[1, 2], slo_p90_ttft_s=4, slo_p90_ttlt_s=5,  # ttlt 20 > 5
        clock=_FakeClock(1.0))
    assert out["operating_point"]["found"] is False
