"""EvalPlus (HumanEval+/MBPP+) runner — execution-based pass@1, supporting evidence only.

The first external code runner: HumanEval+/MBPP+ add ~80x/~35x more tests than the originals,
so pass@1 here is far harder to game than a substring check. Runs against the local Ollama
OpenAI-compatible endpoint. Off by default; bounded by sample_budget. This module owns the
result PARSING (unit-tested) and the control flow; the actual `evalplus.evaluate` shell-out is
an injected executor (never auto-launched, never tested live).
"""
from __future__ import annotations

from .runner import FrameworkResult, run_framework

FRAMEWORK = "evalplus"


def parse_evalplus(raw: dict, name: str, spec) -> list[FrameworkResult]:
    """Normalize an EvalPlus results payload into per-dataset pass@1 records.

    Accepts the common shapes: {"humaneval+": {"pass@1": 0.63}, ...} or a flat
    {"pass@1": 0.63}. A missing/Non-numeric score becomes None (never fabricated)."""
    results: list[FrameworkResult] = []
    if "pass@1" in raw:
        raw = {spec.datasets[0] if spec.datasets else "humaneval": {"pass@1": raw["pass@1"]}}
    for dataset, payload in raw.items():
        score = None
        n = None
        if isinstance(payload, dict):
            val = payload.get("pass@1")
            score = float(val) if isinstance(val, (int, float)) else None
            n_val = payload.get("n") or payload.get("num_samples")
            n = int(n_val) if isinstance(n_val, int) else None
        results.append(FrameworkResult(
            framework=name, informs_role=spec.informs_role, status="ok",
            note=f"EvalPlus {dataset} pass@1 (supporting evidence only)",
            metric="pass@1", score=score, dataset=str(dataset), n_samples=n))
    if not results:
        results.append(FrameworkResult(
            framework=name, informs_role=spec.informs_role, status="error",
            note="EvalPlus output had no recognizable pass@1 scores"))
    return results


def run(spec, *, subprocess_runner=None, available_fn=None) -> list[FrameworkResult]:
    kwargs = {"parse_fn": parse_evalplus, "subprocess_runner": subprocess_runner}
    if available_fn is not None:
        kwargs["available_fn"] = available_fn
    return run_framework(FRAMEWORK, spec, **kwargs)
