"""
The daily self-improvement scan (the Airflow DAG's brain, callable from any touchpoint).

An OBSERVER-ONLY pipeline that scans many sources (Kanban/Ledger, papers, models/providers,
dependencies, code health, data/drift, cost), classifies and dedupes findings across nine
pillars, ranks them (ICE/RICE/WSJF/VOI), drafts BOUNDED experiment proposals in the `Proposed`
state, and emits exactly two artifacts — Backlog cards and one decision-grade report.

It inherits the proactive-runner charter exactly: it may observe, classify, summarize, draft,
and open a Backlog card; it may NOT approve, execute, promote, merge, deploy, change risk
policy, rotate secrets, or auto-merge anything. Promotion and canary stay human-only. The
`ObserverCharter` makes that structural, not a convention.

The heavy logic lives here (deterministic, offline, unit-tested) so the Airflow DAG, the CLI
(`make improvement-scan`), and a Discord/Kanban "set it loose" command are all thin callers.
"""
from __future__ import annotations

from .pillars import Pillar, PILLAR_TARGETS, PILLAR_SOURCES, target_for
from .findings import Finding
from .ranking import ice, rice, wsjf, cost_of_delay, voi, rank, confidence_band
from .charter import ObserverCharter, CharterViolation
from .sources import (
    Scanner, ScanOutcome, run_scanners, CodeHealthScanner, CodeHealthThresholds,
    FeedScanner, PapersScanner, ModelRegistryScanner, DependencyScanner, KanbanScanner,
    ResearchSourceScanner, LedgerHealthScanner,
)
from .triage import Triage, TriageDecision, TriageResult
from .report import render_report
from .pipeline import ScanPipeline, ScanReport
from .config import (
    DiscoveryConfig, RankingKnobs, TriageKnobs, CodeHealthKnobs, AcceptanceKnobs,
    load_discovery_config,
)
from .acceptance import (
    AcceptanceHarness, AcceptanceResult, DecisionRecord, FeatureLog, LogisticModel,
    build_records, features_of, label_from_row, roc_auc, score_findings, train_acceptance,
)
from .manifest import ReportManifest, build_manifest, write_manifest
from .kanban import (
    command_center_card_drafter, draft_self_improvement_cards, growthos_card_drafter,
)
from .life_center import (
    command_center_operations_binder, command_center_overview_binder,
    command_center_services_binder, run_lc, seed_operations_from_setup,
    sync_overview_from_verification, sync_services_from_catalog,
)
from .dag_support import (
    SOURCE_REGISTRY, build_scanner, finish, offline_specs, registered_repository_specs,
    scan_one, scheduled_source_registry, DEFAULT_REPORT_PATH,
)

__all__ = [
    "Pillar", "PILLAR_TARGETS", "PILLAR_SOURCES", "target_for",
    "Finding", "ice", "rice", "wsjf", "cost_of_delay", "voi", "rank", "confidence_band",
    "ObserverCharter", "CharterViolation",
    "Scanner", "ScanOutcome", "run_scanners", "CodeHealthScanner", "CodeHealthThresholds",
    "FeedScanner", "PapersScanner", "ModelRegistryScanner", "DependencyScanner",
    "KanbanScanner", "LedgerHealthScanner",
    "Triage", "TriageDecision", "TriageResult", "render_report", "ScanPipeline", "ScanReport",
    "SOURCE_REGISTRY", "build_scanner", "scan_one", "finish", "offline_specs",
    "registered_repository_specs", "scheduled_source_registry",
    "DEFAULT_REPORT_PATH",
    "DiscoveryConfig", "RankingKnobs", "TriageKnobs", "CodeHealthKnobs", "AcceptanceKnobs",
    "load_discovery_config",
    "AcceptanceHarness", "AcceptanceResult", "DecisionRecord", "FeatureLog", "LogisticModel",
    "build_records", "features_of", "label_from_row", "roc_auc", "score_findings",
    "train_acceptance",
    "ReportManifest", "build_manifest", "write_manifest",
    "command_center_card_drafter", "draft_self_improvement_cards", "growthos_card_drafter",
    "run_lc", "sync_services_from_catalog", "seed_operations_from_setup",
    "sync_overview_from_verification", "command_center_services_binder",
    "command_center_operations_binder", "command_center_overview_binder",
]
