"""
The discovery-scan orchestrator — the scan's single entry point, shared by the Airflow DAG, the
CLI, and any "set it loose" touchpoint (Discord/Kanban).

MODULE TREE (canonical locations; PIPELINE_STANDARDS §6 module-tree header)
    pillars.py        pillar → target-type + named sources
    findings.py       Finding model + → bounded `Proposed` experiment (+ JSON round-trip)
    config.py         loader for configs/discovery.yaml (knobs; contract in ..schema)
    ranking.py        ICE/RICE/WSJF/VOI + confidence band (the formula baseline)
    acceptance.py     learned P(accept) from Ledger outcomes (champion–challenger vs formula)
    charter.py        ObserverCharter — the structural observer-only wall
    sources.py        scanners (offline code-health + injected feeds) → ScanOutcome
    triage.py         dedup vs open cards + negative-result memory + cooldown
    report.py         the decision-grade Markdown report
    pipeline.py       THIS FILE — chains the five stages below
    dag_support.py    Airflow-free glue + XCom (de)serialization

STAGES (strict linear chain; each reads only the prior stage; promotion/draft is last)
    1 scan_*              sources.py    per-source (DAG: dynamic-mapped); a dead feed → recorded
                                        error, never a swallowed exception
    2 classify_and_dedup  triage.py     drop noise (< min_confidence), dedup vs open cards,
                                        suppress negative-result memory, honor cooldown
    3 score_and_rank      ranking.py    formula score; or learned P(accept) when it is champion
    4 draft_proposals     charter.py    top-N → bounded, secret-free, L2-capped `Proposed` cards;
                                        each drafted card's features are logged for acceptance.py
    5 emit_report_and_cards report.py   one report (+ manifest); cards via the charter

MODES
    dry-run (apply=False, default)  compute + render everything, ZERO registry/file writes
    apply (apply=True)              draft `Proposed` cards + write the report (+ feature log)

OBSERVER BOUNDARY (the human wall is structural)
    Every write goes through ObserverCharter, which exposes only read_* / draft_backlog_card
    (Proposed-only, idempotent) / write_report. promote / canary / merge / deploy / set_status
    raise CharterViolation. The pipeline cannot escalate; promotion stays human-only.

HARD CONTRACTS
    * idempotent — content-hashed experiment ids + dedup-guarded drafting + logical-date keyed.
    * no silent truncation — overflow past the card cap is reported ("held by card cap"), kept.
    * no defensive coding — a failed source is a visible ScanOutcome.error; missing data fails
      loud; every threshold is a documented config knob (configs/discovery.yaml), not a literal.
    * no leakage — a finding scored at time T uses only evidence ≤ T; the learned ranker trains
      on older cards and validates on newer (temporal split), never an outcome-derived feature.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .acceptance import FeatureLog
from .charter import ObserverCharter
from .config import DiscoveryConfig, load_discovery_config
from .findings import Finding
from .manifest import build_manifest, write_manifest
from .ranking import rank, score
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
    manifest_path: str = ""
    outcomes: list[ScanOutcome] = field(default_factory=list)
    triage: list[TriageResult] = field(default_factory=list)
    ranked: list[tuple[Finding, float]] = field(default_factory=list)   # top-N (finding, score)

    def to_dict(self) -> dict:
        return {
            "date": self.date, "method": self.method, "applied": self.applied,
            "n_sources": self.n_sources, "n_failed": self.n_failed,
            "n_findings": self.n_findings, "drafted": self.drafted_ids,
            "would_draft": self.would_draft_ids, "suppressed_negative": self.suppressed_negative,
            "held": self.held, "n_capped": self.n_capped, "report_path": self.report_path,
            "manifest_path": self.manifest_path,
            "failed_sources": [o.scanner for o in self.outcomes if not o.ok],
        }


class ScanPipeline:
    def __init__(self, charter: ObserverCharter, *, config: DiscoveryConfig | None = None,
                 method: str | None = None, min_confidence: float | None = None,
                 cooldown_hours: float | None = None, max_cards: int | None = None,
                 feature_log: FeatureLog | None = None):
        self.charter = charter
        # Every default comes from the validated config — no inline literals. Explicit args
        # still override (CLI flags, tests), but the operating point lives in configs/discovery.yaml.
        self.config = config or load_discovery_config()
        # Optional acceptance-feedback log: records each drafted card's pre-decision features so
        # the P(accept) ranker can learn from human accept/reject outcomes (acceptance.py).
        self.feature_log = feature_log
        r, t = self.config.ranking, self.config.triage
        self.method = method or r.default_method
        self.max_cards = max_cards if max_cards is not None else t.max_cards
        self.confidence_half_width = r.confidence_band_half_width
        conf = min_confidence if min_confidence is not None else t.min_confidence
        cool = cooldown_hours if cooldown_hours is not None else t.cooldown_hours
        self.triage = Triage(charter.reg, min_confidence=conf, cooldown_hours=cool)

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
                    if self.feature_log is not None:
                        # record the formula score (the leakage-safe baseline feature), not the
                        # live rank score (which may itself be a learned P(accept)).
                        self.feature_log.append(f, score(f, self.method), drafted_at=now_iso)

        # 5. emit_report (rendered always; written to disk only on apply)
        shown_ids = drafted_ids if apply else set(would_draft_ids)
        md = render_report(date=date, method=self.method, ranked_drafts=ranked,
                           triage_results=triage_results, outcomes=outcomes,
                           drafted_ids=shown_ids, applied=apply, n_capped=n_capped,
                           confidence_half_width=self.confidence_half_width)
        report_path = self.charter.write_report(md) if apply else ""
        manifest_path = ""
        if apply and report_path:
            # provenance sidecar: sha256 of the report + which code/inputs produced it
            manifest = build_manifest(report_markdown=md, produced_at=now_iso, outcomes=outcomes,
                                      n_findings=len(findings), n_drafted=len(drafted_ids),
                                      method=self.method)
            manifest_path = write_manifest(report_path, manifest)

        counts = {d: sum(1 for r in triage_results if r.decision is d) for d in TriageDecision}
        held = (counts[TriageDecision.DUPLICATE_OPEN] + counts[TriageDecision.DUPLICATE_BATCH]
                + counts[TriageDecision.COOLDOWN] + counts[TriageDecision.NOISE])
        return ScanReport(
            date=date, method=self.method, applied=apply, n_sources=len(outcomes),
            n_failed=sum(1 for o in outcomes if not o.ok), n_findings=len(findings),
            drafted_ids=sorted(drafted_ids), would_draft_ids=would_draft_ids,
            suppressed_negative=counts[TriageDecision.NEGATIVE_MEMORY], held=held,
            n_capped=n_capped, report_markdown=md, report_path=report_path,
            manifest_path=manifest_path, outcomes=outcomes, triage=triage_results,
            ranked=ranked)
