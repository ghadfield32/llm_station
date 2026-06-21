"""BigCodeBench runner — realistic function-call code tasks, supporting evidence only.

Heavier and more realistic than HumanEval+ (diverse library/function-call tasks); a good fit
for the repo-agent/code-change use case. Same posture as EvalPlus: local OpenAI-compatible
endpoint, off by default, sample-budget-bounded, parsing unit-tested, the `bigcodebench.evaluate`
shell-out injected and never auto-launched. pass@1 here is SUPPORTING evidence — never a gate.
"""
from __future__ import annotations

from .runner import FrameworkResult, run_framework

FRAMEWORK = "bigcodebench"


def parse_bigcodebench(raw: dict, name: str, spec) -> list[FrameworkResult]:
    """Normalize a BigCodeBench payload. Accepts {"pass@1": 0.45} or split modes
    {"complete": {"pass@1": ...}, "instruct": {"pass@1": ...}}."""
    subset = spec.subset or "full"
    results: list[FrameworkResult] = []
    if "pass@1" in raw:
        val = raw.get("pass@1")
        results.append(FrameworkResult(
            framework=name, informs_role=spec.informs_role, status="ok",
            note=f"BigCodeBench {subset} pass@1 (supporting evidence only)",
            metric="pass@1", dataset=subset,
            score=float(val) if isinstance(val, (int, float)) else None))
        return results
    for mode, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        val = payload.get("pass@1")
        results.append(FrameworkResult(
            framework=name, informs_role=spec.informs_role, status="ok",
            note=f"BigCodeBench {subset}/{mode} pass@1 (supporting evidence only)",
            metric="pass@1", dataset=f"{subset}/{mode}",
            score=float(val) if isinstance(val, (int, float)) else None))
    if not results:
        results.append(FrameworkResult(
            framework=name, informs_role=spec.informs_role, status="error",
            note="BigCodeBench output had no recognizable pass@1 scores"))
    return results


def run(spec, *, subprocess_runner=None, available_fn=None) -> list[FrameworkResult]:
    kwargs = {"parse_fn": parse_bigcodebench, "subprocess_runner": subprocess_runner}
    if available_fn is not None:
        kwargs["available_fn"] = available_fn
    return run_framework(FRAMEWORK, spec, **kwargs)
