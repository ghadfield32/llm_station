"""Serving-SLO analysis — the pure, deterministic, unit-tested core of serving evaluation.

No I/O, no models, no Ollama. Given measured latency samples and a request-rate sweep, it
computes the percentiles that actually matter (p50/p90/p95/p99), predicts p90 TTLT via the
"three-nineties" rule, and selects the OPERATING POINT: the highest sustainable request rate
whose p90 latency still meets the scenario SLO. This is the chart that matters — not a single
tokens/sec number.

Definitions (all seconds):
  - TTFT  time to first token        (prompt processing + first decode)
  - ITL   inter-token latency        (steady-state per-output-token decode time)
  - TTLT  time to last token         (the user's total wait)
  - RPS   requests per second sustained at a given concurrency

Three-nineties rule: p90 TTLT ≈ p90 TTFT + p90 ITL × output_tokens. Lets you predict the
tail without running production traffic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


class ServingSloError(ValueError):
    """Raised on degenerate input (empty samples, bad percentile) — never papered over."""


def percentile(samples: list[float], p: float) -> float:
    """Linear-interpolation percentile, p in [0, 100]. Raises on empty input — an empty
    latency vector is a measurement failure, not a zero."""
    if not samples:
        raise ServingSloError("percentile of an empty sample set is undefined")
    if not 0.0 <= p <= 100.0:
        raise ServingSloError(f"percentile p must be in [0, 100], got {p}")
    ordered = sorted(samples)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def summarize_latency(samples: list[float]) -> dict[str, float]:
    """p50/p90/p95/p99 + min/max for a latency vector (seconds)."""
    return {
        "p50": percentile(samples, 50),
        "p90": percentile(samples, 90),
        "p95": percentile(samples, 95),
        "p99": percentile(samples, 99),
        "min": float(min(samples)),
        "max": float(max(samples)),
        "n": float(len(samples)),
    }


def predict_p90_ttlt(p90_ttft_s: float, p90_itl_s: float, output_tokens: int) -> float:
    """The three-nineties rule: p90 TTLT ≈ p90 TTFT + p90 ITL × output_tokens."""
    if min(p90_ttft_s, p90_itl_s) < 0 or output_tokens < 0:
        raise ServingSloError("three-nineties inputs must be non-negative")
    return p90_ttft_s + p90_itl_s * output_tokens


@dataclass(frozen=True)
class SweepPoint:
    """One measured point of the request-rate sweep for one scenario."""
    concurrency: int
    rps: float                # sustained requests/sec at this concurrency
    p90_ttft_s: float
    p90_ttlt_s: float
    error_rate: float = 0.0   # fraction of requests that failed/timed out at this rate

    def to_dict(self) -> dict:
        return asdict(self)


def meets_slo(point: SweepPoint, slo_p90_ttft_s: float, slo_p90_ttlt_s: float,
              max_error_rate: float = 0.0) -> bool:
    """A point is acceptable only if BOTH latency SLOs hold AND it is not erroring out."""
    return (point.p90_ttft_s <= slo_p90_ttft_s
            and point.p90_ttlt_s <= slo_p90_ttlt_s
            and point.error_rate <= max_error_rate)


@dataclass(frozen=True)
class OperatingPoint:
    scenario: str
    found: bool
    concurrency: int | None
    rps: float | None
    p90_ttft_s: float | None
    p90_ttlt_s: float | None
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def operating_point(scenario: str, points: list[SweepPoint], *, slo_p90_ttft_s: float,
                    slo_p90_ttlt_s: float, max_error_rate: float = 0.0) -> OperatingPoint:
    """The operating point = the highest-RPS sweep point that still meets the SLO. If no point
    meets it (even single-request is too slow), `found` is False with an explicit reason —
    never a fabricated "it's fine"."""
    if not points:
        raise ServingSloError(f"scenario {scenario!r} has no sweep points to analyze")
    acceptable = [p for p in points
                  if meets_slo(p, slo_p90_ttft_s, slo_p90_ttlt_s, max_error_rate)]
    if not acceptable:
        slowest_ok = min(points, key=lambda p: p.concurrency)
        return OperatingPoint(
            scenario=scenario, found=False, concurrency=None, rps=None,
            p90_ttft_s=None, p90_ttlt_s=None,
            reason=(f"no sweep point meets SLO (p90 TTFT<= {slo_p90_ttft_s}s, "
                    f"p90 TTLT<= {slo_p90_ttlt_s}s); even concurrency="
                    f"{slowest_ok.concurrency} gave p90 TTLT={slowest_ok.p90_ttlt_s:.1f}s"))
    best = max(acceptable, key=lambda p: p.rps)
    return OperatingPoint(
        scenario=scenario, found=True, concurrency=best.concurrency, rps=best.rps,
        p90_ttft_s=best.p90_ttft_s, p90_ttlt_s=best.p90_ttlt_s,
        reason=(f"highest sustainable rate under SLO: concurrency={best.concurrency}, "
                f"rps={best.rps:.2f}, p90 TTLT={best.p90_ttlt_s:.1f}s"))
