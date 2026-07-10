"""External code-eval framework runners (EvalPlus, BigCodeBench).

These produce SUPPORTING evidence only — never a promotion gate (the repo's own role suites
decide). Each runner is fail-soft: disabled or not-installed returns a status, not a crash, and
`FrameworkResult.is_decision_gate()` is always False. They run against the local Ollama
OpenAI-compatible endpoint and are bounded by a sample budget.
"""
from .runner import FrameworkResult, availability, run_framework

__all__ = ["FrameworkResult", "availability", "run_framework"]
