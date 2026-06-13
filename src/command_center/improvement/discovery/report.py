"""
The decision-grade report — one Markdown artifact a human can act on in a morning.

It is deliberately honest: it leads with which sources FAILED (a down feed is a visible line,
never a silently missing pillar), shows the ranked proposals that became Backlog cards with
their score / target / risk / confidence band / explicit unknowns, and — importantly — lists
what was DELIBERATELY NOT proposed because the negative-result memory already recorded a human
rejection. Every drafted item is `Proposed`; promotion and canary stay human-only, by design.

Pure string building; deterministic given its inputs (the date is injected, never read here).
"""
from __future__ import annotations

from collections import Counter

from ..schema import TargetType
from .findings import Finding
from .ranking import confidence_band
from .sources import ScanOutcome
from .triage import TriageDecision, TriageResult


def _band(f: Finding) -> str:
    lo, hi = confidence_band(f)
    return f"{lo:.2f}–{hi:.2f}"


def _target(f: Finding) -> str:
    tt = f.suggested_target_type
    return tt.value if isinstance(tt, TargetType) else str(tt)


def render_report(*, date: str, method: str,
                  ranked_drafts: list[tuple[Finding, float]],
                  triage_results: list[TriageResult],
                  outcomes: list[ScanOutcome],
                  drafted_ids: set[str],
                  applied: bool = True,
                  n_capped: int = 0) -> str:
    n_findings = len(triage_results)
    counts = Counter(r.decision for r in triage_results)
    failed = [o for o in outcomes if not o.ok]
    held = (counts[TriageDecision.DUPLICATE_OPEN] + counts[TriageDecision.DUPLICATE_BATCH]
            + counts[TriageDecision.COOLDOWN] + counts[TriageDecision.NOISE])
    lines: list[str] = []
    a = lines.append

    mode = "" if applied else "  *(DRY RUN — no cards written)*"
    a(f"# Daily Self-Improvement Report — {date}{mode}")
    a("")
    a("> Observer-only scan. Every item below is a **Proposed** Backlog card. "
      "Nothing here is approved, promoted, merged, or deployed — the human wall is unchanged.")
    a("")
    a("## Summary")
    a("")
    a(f"- Sources run: **{len(outcomes)}** ({len(failed)} failed)")
    a(f"- Findings: **{n_findings}**")
    verb = "Drafted" if applied else "Would draft"
    a(f"- {verb} as Backlog cards: **{len(drafted_ids)}** (ranked by `{method.upper()}`)")
    if n_capped:
        a(f"- Held by card cap (NOT dropped — surfaced next run): **{n_capped}**")
    a(f"- Suppressed by negative-result memory: **{counts[TriageDecision.NEGATIVE_MEMORY]}**")
    a(f"- Held (duplicate/cooldown/noise): **{held}**")
    a("")

    # Failed sources FIRST — honesty before recommendations.
    if failed:
        a("## ⚠ Failed sources (no findings collected — investigate)")
        a("")
        for o in failed:
            a(f"- **{o.scanner}** ({o.pillar.value}): {o.error}")
        a("")

    a("## Proposed improvements (ranked)")
    a("")
    if not ranked_drafts:
        a("_No new actionable findings this run._")
        a("")
    else:
        a("| # | Pillar | Score | Target | Risk | Conf. | Proposal |")
        a("|--:|--------|------:|--------|------|-------|----------|")
        for i, (f, sc) in enumerate(ranked_drafts, 1):
            mark = "" if f.experiment_id in drafted_ids else " ⚠(not written)"
            a(f"| {i} | {f.pillar.value} | {sc:.3f} | {_target(f)} | "
              f"{f.suggested_risk.value} | {_band(f)} | {f.title}{mark} |")
        a("")
        a("### Evidence & unknowns")
        a("")
        for i, (f, _sc) in enumerate(ranked_drafts, 1):
            a(f"**{i}. {f.title}** — `{f.experiment_id}`  ")
            a(f"  - Claim: {f.claim}  ")
            a(f"  - Evidence: {f.evidence}  ")
            if f.unknowns:
                a(f"  - Unknowns: {f.unknowns}  ")
        a("")

    # Negative-result memory — the no-repeat-mistakes evidence.
    neg = [r for r in triage_results if r.decision is TriageDecision.NEGATIVE_MEMORY]
    if neg:
        a("## Not proposed — negative-result memory")
        a("")
        a("_The system already learned these; re-proposing would be forgetting._")
        a("")
        for r in neg:
            a(f"- **{r.finding.title}** ({r.finding.pillar.value}) — {r.reason}")
        a("")

    # Per-pillar tally across all findings.
    a("## Findings by pillar")
    a("")
    pill = Counter(r.finding.pillar.value for r in triage_results)
    for name, n in sorted(pill.items()):
        a(f"- {name}: {n}")
    a("")
    a("---")
    a("_Promotion and canary are human-only. Drafted cards enter the existing "
      "experiment lifecycle in the `Proposed` state and wait at the Kanban wall._")
    return "\n".join(lines)
