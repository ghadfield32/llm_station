"""Render the kanban observability digest — real metrics + the tuning verdict.

Pure string concatenation (the repo's digest idiom: usage_digest.py, discovery
delivery/digest.py — no templating engine). Same inputs in → same Markdown out.
"""
from __future__ import annotations

from pathlib import Path

from .metrics import Metrics
from .tuning import TuneResult


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def render_digest(metrics: Metrics, tune: TuneResult, *, generated_at: str,
                  log_file: Path | str) -> str:
    m = metrics
    lines = [
        "# Agent Kanban Surface — observability digest",
        "",
        f"Generated: `{generated_at}`",
        f"Source log: `{log_file}`",
        "",
        "## Activity",
        "",
        f"- Total tool calls: **{m.total_calls}**"
        + ("  _(no calls logged yet — figures are zero until agents run)_"
           if m.total_calls == 0 else ""),
        f"- By surface: {m.by_surface or '—'}",
        f"- Error rate: **{_pct(m.error_rate)}**",
        f"- Board mutations: **{m.board_mutations}**",
        "",
        "## Surface health (the tune-by metrics)",
        "",
        f"- **Redundant-call rate**: {_pct(m.redundant_rate)} "
        "— consecutive identical calls; board re-injection should drive this down.",
        f"- **Intent-verb adoption**: {_pct(m.intent_verb_share)} "
        f"({m.intent_verb_calls} verb vs {m.generic_mutator_calls} generic "
        "set_status) — should trend to 100% now that set_status is off the agent surface.",
        "",
        "## Per-tool",
        "",
        "| tool | calls | errors | err% | p50 ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for t in m.per_tool:
        lines.append(f"| {t['tool']} | {t['calls']} | {t['errors']} | "
                     f"{t['error_rate'] * 100:.0f}% | {t['p50_ms']} |")
    if not m.per_tool:
        lines.append("| _(none)_ |  |  |  |  |")
    lines += [
        "",
        "## Tuning — fuzzy title matcher",
        "",
        f"- Decision: **{tune.source}** → fuzzy_min_ratio = `{tune.value}`",
        f"- Why: {tune.reason}",
        f"- Labelled decisions: {tune.n}",
        "",
        "_Cadence (`refresh_every_rounds`) is config-governed; its outcome metric is "
        "the redundant-call rate above. Auto-tuning it needs a controlled cadence "
        "experiment — not fabricated here._",
        "",
    ]
    return "\n".join(lines)
