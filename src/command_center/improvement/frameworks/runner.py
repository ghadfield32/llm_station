"""Shared scaffolding for external code-eval framework runners.

`availability` checks whether the framework CLI/module is installed (it usually is NOT — these
are heavy optional deps), so a runner can fail soft. `run_framework` is the common control
flow: disabled -> unavailable -> ready (available but no executor passed) -> ok/error. The
actual shell-out is INJECTED (`subprocess_runner`) so tests never launch a real tool, and a
runner is never auto-launched (you pass an executor to actually run it). Every result is
`supporting_evidence_only` and `is_decision_gate()` is always False.
"""
from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FrameworkResult:
    framework: str
    informs_role: str
    status: str                  # disabled | unavailable | ready | ok | error
    note: str
    trust: str = "supporting_evidence_only"
    metric: str | None = None    # e.g. "pass@1"
    score: float | None = None   # never fabricated — None unless the tool reported it
    dataset: str | None = None
    n_samples: int | None = None

    def is_decision_gate(self) -> bool:
        """A framework result can NEVER gate a promotion — by construction."""
        return False

    def to_dict(self) -> dict:
        return asdict(self)


def availability(cli_command: str) -> tuple[bool, str]:
    """Is the framework runnable here? True if its CLI is on PATH or its top module imports.
    Honest about absence — these tools are optional heavy deps and usually not installed."""
    if shutil.which(cli_command):
        return True, f"{cli_command} on PATH"
    module = cli_command.split(".")[0].replace("-", "_")
    try:
        if importlib.util.find_spec(module) is not None:
            return True, f"module {module!r} importable"
    except (ImportError, ValueError):
        pass
    return False, f"{cli_command} not installed (module {module!r} absent)"


def _status(framework: str, informs_role: str, status: str, note: str) -> FrameworkResult:
    return FrameworkResult(framework=framework, informs_role=informs_role,
                           status=status, note=note)


def run_framework(name: str, spec, *, parse_fn: Callable[[dict, str, object], list],
                  subprocess_runner: Callable[[object], dict] | None = None,
                  available_fn: Callable[[str], tuple[bool, str]] = availability) -> list:
    """Common control flow for a framework runner. Returns a list of FrameworkResult.

    disabled            -> framework is off in config
    unavailable         -> CLI/module not installed (soft — supporting evidence, not a failure)
    ready               -> available + enabled, but no executor was passed (never auto-runs)
    ok / error          -> executor ran; parsed results or a captured failure
    """
    if not spec.enabled:
        return [_status(name, spec.informs_role, "disabled",
                        "framework disabled (enabled: false)")]
    ok, why = available_fn(spec.cli_command)
    if not ok:
        return [_status(name, spec.informs_role, "unavailable", why)]
    if subprocess_runner is None:
        return [_status(name, spec.informs_role, "ready",
                        f"available ({why}); pass an executor to run (bounded by "
                        f"sample_budget={spec.sample_budget})")]
    try:
        raw = subprocess_runner(spec)
    except Exception as exc:   # captured as a result, not swallowed silently
        return [_status(name, spec.informs_role, "error", f"executor failed: {exc}")]
    return parse_fn(raw, name, spec)
