"""Concurrency-sweep load driver — the I/O layer on top of the pure serving_slo analysis.

For each request-rate point it issues `concurrency` requests at once, turns the resulting
latency samples into a `SweepPoint` (p90 TTFT/TTLT + sustained RPS + error rate), and lets
serving_slo pick the operating point (highest RPS under the p90 SLO). The per-request
measurement is INJECTED (`measure_fn`) and the wall clock is injectable, so the whole sweep +
analysis is unit-tested deterministically without a live Ollama.

Privacy: only timing/metric numbers are produced — never raw prompts or generated text.
A single batched wall measurement is an honest proxy for sustained RPS at a concurrency level
(rps = completed / batch_wall); it is measured, never fabricated.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .serving_benchmark import ServingSample, measure_once
from .serving_slo import OperatingPoint, SweepPoint, operating_point, percentile

# A zero-arg call that performs ONE request and returns its latency sample.
MeasureFn = Callable[[], ServingSample]


@dataclass(frozen=True)
class PointResult:
    """Raw outcome of one concurrency level before analysis."""
    concurrency: int
    samples: list[ServingSample] = field(default_factory=list)
    n_errors: int = 0
    wall_seconds: float = 0.0


def run_point(measure_fn: MeasureFn, concurrency: int, *, max_workers: int | None = None,
              clock: Callable[[], float] = time.perf_counter) -> PointResult:
    """Issue `concurrency` requests concurrently; collect samples + count failures. A failed
    request is COUNTED, never silently dropped or retried into a fake success."""
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1, got {concurrency}")
    workers = max_workers or concurrency
    samples: list[ServingSample] = []
    n_errors = 0
    start = clock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(measure_fn) for _ in range(concurrency)]
        for fut in as_completed(futures):
            try:
                samples.append(fut.result())
            except Exception:   # a failed request is a real signal (error_rate), not swallowed
                n_errors += 1
    wall = max(clock() - start, 1e-9)
    return PointResult(concurrency=concurrency, samples=samples,
                       n_errors=n_errors, wall_seconds=wall)


def point_to_sweep(result: PointResult) -> SweepPoint:
    """Turn a raw PointResult into the SweepPoint serving_slo consumes. An all-failed point
    reports rps=0 + error_rate=1 with the observed wall as its latency (so it fails any SLO),
    rather than a fabricated number."""
    total = len(result.samples) + result.n_errors
    if not result.samples:
        return SweepPoint(
            concurrency=result.concurrency, rps=0.0,
            p90_ttft_s=result.wall_seconds, p90_ttlt_s=result.wall_seconds,
            error_rate=1.0 if total else 0.0)
    return SweepPoint(
        concurrency=result.concurrency,
        rps=len(result.samples) / result.wall_seconds,
        p90_ttft_s=percentile([s.ttft_s for s in result.samples], 90),
        p90_ttlt_s=percentile([s.ttlt_s for s in result.samples], 90),
        error_rate=result.n_errors / total if total else 0.0)


def run_sweep(measure_fn: MeasureFn, concurrency_points: list[int], *,
              max_workers: int | None = None,
              clock: Callable[[], float] = time.perf_counter) -> list[SweepPoint]:
    """Run every concurrency point and return one SweepPoint each (in input order)."""
    return [point_to_sweep(run_point(measure_fn, c, max_workers=max_workers, clock=clock))
            for c in concurrency_points]


def sweep_and_operating_point(measure_fn: MeasureFn, scenario_name: str, *,
                              concurrency_points: list[int], slo_p90_ttft_s: float,
                              slo_p90_ttlt_s: float, max_error_rate: float = 0.0,
                              clock: Callable[[], float] = time.perf_counter) -> dict:
    """Full local serving evaluation for one scenario: sweep + operating-point selection."""
    sweep = run_sweep(measure_fn, concurrency_points, clock=clock)
    op: OperatingPoint = operating_point(
        scenario_name, sweep, slo_p90_ttft_s=slo_p90_ttft_s,
        slo_p90_ttlt_s=slo_p90_ttlt_s, max_error_rate=max_error_rate)
    return {
        "scenario": scenario_name,
        "concurrency_points": concurrency_points,
        "sweep": [p.to_dict() for p in sweep],
        "operating_point": op.to_dict(),
    }


def build_measure_fn(model: str, *, input_tokens: int, output_tokens: int,
                     base_url: str) -> MeasureFn:
    """A live measure_fn that sends one Ollama request sized to a scenario. Uses a synthetic
    filler prompt (~input_tokens words) so no real/private content is sent. Live path — not
    exercised in tests (those inject a deterministic measure_fn)."""
    prompt = ("benchmark filler token " * max(input_tokens // 3, 1)).strip()

    def _measure() -> ServingSample:
        return measure_once(model, prompt, base_url=base_url, num_predict=output_tokens)

    return _measure
