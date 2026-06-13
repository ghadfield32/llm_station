"""
The pipeline — the scan's single entry point, shared by the Airflow DAG, the CLI, and any
"set it loose" touchpoint (Discord/Kanban). It chains the five stages the addendum specifies:

    scan_*  ->  classify_and_dedup  ->  score_and_rank  ->  draft_proposals  ->  emit_report

It writes EXACTLY two kinds of artifact and only through the `ObserverCharter`: `Proposed`
Backlog cards and one report. `apply=False` (the default) is a true dry run — it computes and
renders the full report but performs ZERO registry writes, so any touchpoint can preview safely.

The card cap never silently drops work: anything over the cap is reported as "held by card cap"
and resurfaces next run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .charter import ObserverCharter
from .findings import Finding
from .ranking import rank
from .report import render_report
from .sources import ScanOutcome, Scanner, run_scanners
from .triage import Triage, TriageDecision, TriageResult


@dataclass
class ScanReport:
    date: str
    method: str
    applied: bool
    n_sources: int
    n_failed: int
    n_findings: int
    drafted_ids: list[str]
    would_draft_ids: list[str]
    suppressed_negative: int
    held: int
    n_capped: int
    report_markdown: str
    report_path: str = ""
    outcomes: list[ScanOutcome] = field(default_factory=list)
    triage: list[TriageResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date, "method": self.method, "applied": self.applied,
            "n_sources": self.n_sources, "n_failed": self.n_failed,
            "n_findings": self.n_findings, "drafted": self.drafted_ids,
            "would_draft": self.would_draft_ids, "suppressed_negative": self.suppressed_negative,
            "held": self.held, "n_capped": self.n_capped, "report_path": self.report_path,
            "failed_sources": [o.scanner for o in self.outcomes if not o.ok],
        }


class ScanPipeline:
    def __init__(self, charter: ObserverCharter, *, method: str = "wsjf",
                 min_confidence: float = 0.4, cooldown_hours: float = 168.0,
                 max_cards: int = 20):
        self.charter = charter
        self.method = method
        self.max_cards = max_cards
        self.triage = Triage(charter.reg, min_confidence=min_confidence,
                             cooldown_hours=cooldown_hours)

    def run(self, scanners: list[Scanner], *, date: str, now_iso: str,
            apply: bool = False) -> ScanReport:
        # 1. scan_* (failures recorded as outcomes, never swallowed)
        outcomes = run_scanners(scanners, isolate=True)
        return self.run_from_outcomes(outcomes, date=date, now_iso=now_iso, apply=apply)

    def run_from_outcomes(self, outcomes: list[ScanOutcome], *, date: str, now_iso: str,
                          apply: bool = False) -> ScanReport:
        """Stages 2–5 over already-collected scan outcomes. The Airflow DAG runs stage 1 as
        dynamically-mapped per-source tasks and hands their outcomes here; the CLI calls run()."""
        findings: list[Finding] = [f for o in outcomes for f in o.findings]

        # 2. classify_and_dedup
        triage_results = self.triage.classify(findings, now_iso=now_iso)
        draft_findings = [r.finding for r in triage_results if r.is_draft]

        # 3. score_and_rank (full ranking; cap applied after, surplus reported not dropped)
        ranked_all = rank(draft_findings, self.method)
        ranked = ranked_all[:self.max_cards]
        n_capped = max(0, len(ranked_all) - len(ranked))
        would_draft_ids = [f.experiment_id for f, _ in ranked]

        # 4. draft_proposals (only on apply; only Proposed cards via the charter)
        drafted_ids: set[str] = set()
        if apply:
            for f, _sc in ranked:
                row = self.charter.draft_backlog_card(f.to_experiment_definition())
                if row is not None:
                    drafted_ids.add(f.experiment_id)

        # 5. emit_report (rendered always; written to disk only on apply)
        shown_ids = drafted_ids if apply else set(would_draft_ids)
        md = render_report(date=date, method=self.method, ranked_drafts=ranked,
                           triage_results=triage_results, outcomes=outcomes,
                           drafted_ids=shown_ids, applied=apply, n_capped=n_capped)
        report_path = self.charter.write_report(md) if apply else ""

        counts = {d: sum(1 for r in triage_results if r.decision is d) for d in TriageDecision}
        held = (counts[TriageDecision.DUPLICATE_OPEN] + counts[TriageDecision.DUPLICATE_BATCH]
                + counts[TriageDecision.COOLDOWN] + counts[TriageDecision.NOISE])
        return ScanReport(
            date=date, method=self.method, applied=apply, n_sources=len(outcomes),
            n_failed=sum(1 for o in outcomes if not o.ok), n_findings=len(findings),
            drafted_ids=sorted(drafted_ids), would_draft_ids=would_draft_ids,
            suppressed_negative=counts[TriageDecision.NEGATIVE_MEMORY], held=held,
            n_capped=n_capped, report_markdown=md, report_path=report_path,
            outcomes=outcomes, triage=triage_results)
