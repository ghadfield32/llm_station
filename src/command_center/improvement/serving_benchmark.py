"""Serving-performance measurement against a local Ollama endpoint.

Turns Ollama's own `/api/generate` timing fields (nanoseconds) into the three latency numbers
that matter — TTFT, ITL, TTLT — plus the output-token count. No fabrication: a response missing
a required timing field raises rather than guessing a duration.

This module is the thin measurement layer; the deterministic analysis (percentiles,
three-nineties, operating point) lives in serving_slo.py. A concurrency-sweep load driver
(threads/async hitting the endpoint to measure sustained RPS at each `concurrency_sweep` point)
is the remaining wiring on top of `measure_once` — see docs/model-serving-benchmarks.md.

Privacy: like the quality harness, callers should persist only timing/metric numbers and
hashes — never raw prompts or generated text.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass

import httpx

NS_PER_S = 1_000_000_000
# Ollama /api/generate timing fields (all nanoseconds) we read.
_REQUIRED_TIMING_FIELDS = (
    "total_duration", "load_duration", "prompt_eval_duration", "eval_count", "eval_duration",
)
DEFAULT_OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


class ServingBenchmarkError(RuntimeError):
    """Raised when Ollama is unreachable or a required timing field is absent."""


@dataclass(frozen=True)
class ServingSample:
    """One request's measured serving latencies, in seconds."""
    ttft_s: float          # time to first token ≈ load + prompt-eval
    itl_s: float           # inter-token latency ≈ eval_duration / output tokens
    ttlt_s: float          # time to last token ≈ total_duration
    output_tokens: int
    input_tokens: int

    def to_dict(self) -> dict:
        return asdict(self)


def parse_ollama_timings(resp: dict) -> ServingSample:
    """Derive TTFT / ITL / TTLT from an Ollama /api/generate (non-stream) response.

      TTFT ≈ (load_duration + prompt_eval_duration) / 1e9
      ITL  ≈ (eval_duration / eval_count) / 1e9
      TTLT ≈ total_duration / 1e9

    Raises ServingBenchmarkError on any missing field or a zero output-token count (a model
    that produced nothing is a failed sample, not a divide-by-zero we paper over)."""
    missing = [k for k in _REQUIRED_TIMING_FIELDS if k not in resp]
    if missing:
        raise ServingBenchmarkError(
            f"Ollama response missing required timing field(s): {missing}")
    eval_count = int(resp["eval_count"])
    if eval_count <= 0:
        raise ServingBenchmarkError(
            "Ollama response has eval_count<=0 (no tokens generated) — failed sample")
    load = int(resp["load_duration"])
    prompt_eval = int(resp["prompt_eval_duration"])
    eval_dur = int(resp["eval_duration"])
    total = int(resp["total_duration"])
    return ServingSample(
        ttft_s=(load + prompt_eval) / NS_PER_S,
        itl_s=(eval_dur / eval_count) / NS_PER_S,
        ttlt_s=total / NS_PER_S,
        output_tokens=eval_count,
        input_tokens=int(resp.get("prompt_eval_count", 0)),
    )


def measure_once(model: str, prompt: str, *, base_url: str = DEFAULT_OLLAMA_BASE,
                 num_predict: int = 256, timeout_s: float = 300.0) -> ServingSample:
    """One non-streaming generation, returned as a ServingSample. Fails loud if the endpoint
    is unreachable or the response lacks timings. (Live call — exercised via stub in tests.)"""
    try:
        with httpx.Client(base_url=base_url, timeout=timeout_s) as c:
            r = c.post("/api/generate", json={
                "model": model, "prompt": prompt, "stream": False,
                "options": {"num_predict": num_predict},
            })
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as exc:
        raise ServingBenchmarkError(
            f"Ollama /api/generate failed for {model!r} at {base_url}: {exc}") from exc
    return parse_ollama_timings(data)
