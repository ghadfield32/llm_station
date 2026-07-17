"""
Airflow-free glue for the daily DAG, so ALL of the scan logic stays unit-tested here and the
DAG file is thin orchestration. The DAG dynamically maps `scan_one` over `SOURCE_REGISTRY`
(one task per source), then calls `finish` once to classify → rank → draft → emit.

Failures are first-class: a feed's live fetch runs as a closure INSIDE the isolate path, so a
network error becomes a recorded `ScanOutcome.error` (a visible "failed source" line in the
report and an Airflow log) rather than a swallowed exception or a silently missing pillar.

`finish` only ever writes `Proposed` cards + one report, and only through the `ObserverCharter`.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import yaml

from ..registry import ExperimentRegistry
from command_center.schemas.contracts import AutonomyConfig
from .board_feed import fetch_all_board_records
from .charter import ObserverCharter
from .codesota import fetch_codesota_records
from .pillars import Pillar
from .pipeline import ScanPipeline
from .config import load_discovery_config
from .sources import (
    CodeHealthScanner, CodeHealthThresholds, DependencyScanner, KanbanScanner,
    LedgerHealthScanner, ModelRegistryScanner, PapersScanner, ResearchSourceScanner,
    ScanOutcome, Scanner, run_scanners,
)

DEFAULT_REPORT_PATH = "generated/self-improvement-report.md"

_OFFLINE_KINDS = frozenset({"code_health", "ledger"})
_FEED_KINDS = frozenset({"papers", "model_registry", "dependencies", "kanban", "research"})

# The standing set of sources the daily scan maps over. Each is XCom-safe (plain dict).
# Offline sources need no fetch; feed sources read their records from the DAG's fetch.
SOURCE_REGISTRY: list[dict] = [
    {"name": "code_health", "kind": "code_health",
     "pillar": "code_quality", "config": {
         "root": "src", "repo_ids": ["llm_station"],
         "repository_reason": "Dogfood the command center's own implementation and standards."}},
    {"name": "ledger", "kind": "ledger", "pillar": "reliability_observability",
     "config": {"repo_ids": ["llm_station"],
                "repository_reason": "Ledger reliability governs every llm_station workflow."}},
    {"name": "arxiv", "kind": "papers", "pillar": "full_idea",
     "config": {"repo_ids": ["llm_station"],
                "repository_reason": "Evaluate relevant research against llm_station capabilities."}},
    {"name": "litellm_registry", "kind": "model_registry",
     "pillar": "updated_metrics", "config": {
         "repo_ids": ["llm_station"],
         "repository_reason": "Model routing and evaluation are core llm_station capabilities."}},
    # Frontier-watch awareness: keyless CodeSOTA leaderboard picks (closed + open SOTA).
    # A LIVE-FETCH source (see LIVE_FETCHERS) — it pulls fresh at scan time via
    # `discovery.codesota.fetch_codesota_records()`, so there is NO Variable to set.
    {"name": "codesota", "kind": "model_registry",
     "pillar": "updated_metrics", "config": {
         "repo_ids": ["llm_station"],
         "repository_reason": "Frontier model changes can improve llm_station routing decisions."}},
    {"name": "pip_audit", "kind": "dependencies", "pillar": "code_quality",
     "config": {"repo_ids": ["llm_station"],
                "repository_reason": "Dependency health directly affects llm_station safety."}},
    {"name": "kanban_cycle_time", "kind": "kanban", "pillar": "automation", "config": {}},
    # External-idea intake (MASTER.md §5.2). Records come from the research catalog via
    # `cc research-digest feed`; each `evaluate` source becomes one read-only (L1)
    # evaluation card. Propose-only, exactly like model-scout — no adoption here.
    {"name": "research_digest", "kind": "research", "pillar": "full_idea", "config": {}},
]


def registered_repository_specs(
    config_path: str | Path | None = None,
    *,
    self_root: str | Path | None = None,
) -> list[dict]:
    """Build one deterministic code-health source per registered repository.

    The manifest is the sole source of repository coverage. Missing environment
    paths remain explicit invalid roots, so that repository becomes a visible
    failed source instead of silently disappearing from the daily report.
    """
    path = Path(config_path or os.environ.get(
        "SELF_IMPROVEMENT_REPO_CONFIG", "configs/autonomy.yaml"))
    config = AutonomyConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8")))
    own_root = Path(self_root or os.environ.get(
        "SELF_IMPROVEMENT_REPO_ROOT", "."))
    specs: list[dict] = []
    for repo in config.repo_manifests:
        ref = repo.local_path_ref
        if ref == "self":
            root = own_root
        elif ref and ref.startswith("env:"):
            env_name = ref.split(":", 1)[1]
            root = Path(os.environ.get(
                env_name, f"__missing_registered_repo_path__/{repo.repo_id}"))
        else:
            root = Path(f"__missing_registered_repo_path__/{repo.repo_id}")
        capabilities = list(repo.research_capabilities)
        reason = (
            f"Check {repo.repo_id} against its declared capabilities: "
            + "; ".join(capabilities)
            if capabilities else
            f"Check {repo.repo_id} because it is a registered work repository; "
            "code-health drift and standards gaps should be surfaced explicitly."
        )
        specs.append({
            "name": f"code_health_{repo.repo_id}",
            "kind": "code_health",
            "pillar": "code_quality",
            "config": {
                "root": str(root),
                "repo_ids": [repo.repo_id],
                "repository_reason": reason,
                "remote_url": repo.remote_url,
                "research_capabilities": capabilities,
            },
        })
    return specs


def scheduled_source_registry() -> list[dict]:
    """Daily source set with repository scans expanded from the live manifest."""
    non_repo_sources = [
        spec for spec in SOURCE_REGISTRY if spec["name"] != "code_health"]
    return [
        *registered_repository_specs(),
        *non_repo_sources,
    ]

# A fetch maps a source spec -> its already-parsed records (the DAG owns the live call).
Fetch = Callable[[dict], list[dict]]

# Live-fetch sources pull their own records at scan time instead of reading a pre-ingested
# `improvement_feed_<name>` Variable. Used for keyless feeds (no auth/secret) so there is no
# manual `airflow variables set` step and the data is never stale. A fetcher that raises is
# NOT swallowed — the per-source isolate guard records it as a visible failed source.
LIVE_FETCHERS: dict[str, Callable[[], list[dict]]] = {
    "codesota": fetch_codesota_records,
    # New registered boards become scan inputs automatically; there is no
    # second Airflow Variable/list to keep synchronized.
    "kanban_cycle_time": fetch_all_board_records,
}


def fetch_records(spec: dict, variable_get: Callable[[str], str]) -> list[dict]:
    """Records for one feed source. A source registered in LIVE_FETCHERS pulls fresh at scan
    time (keyless, automatable — no Variable to set); every other source reads its pre-ingested
    `improvement_feed_<name>` Variable via the injected `variable_get` (the DAG passes a real
    Airflow `Variable.get`; tests pass a stub). The Variable indirection stays the default."""
    name = spec["name"]
    live = LIVE_FETCHERS.get(name)
    if live is not None:
        return live()
    return json.loads(variable_get(f"improvement_feed_{name}"))


def build_scanner(spec: dict, registry: ExperimentRegistry,
                  fetch: Fetch | None = None) -> Scanner:
    """Construct the one scanner a source spec describes. For feed kinds the live `fetch` is
    bound as a closure that runs at scan() time (so its errors land inside the isolate guard)."""
    kind = spec["kind"]
    name = spec["name"]
    config = spec.get("config", {})
    if kind == "code_health":
        knobs = load_discovery_config().code_health
        return CodeHealthScanner(config.get("root", "src"), name=name,
                                 thresholds=CodeHealthThresholds.from_config(knobs))
    if kind == "ledger":
        return LedgerHealthScanner(registry)
    if kind not in _FEED_KINDS:
        raise ValueError(f"unknown source kind {kind!r} for source {name!r}")
    if fetch is None:
        raise ValueError(f"feed source {name!r} ({kind}) requires a fetch")

    def feed() -> list[dict]:
        return fetch(spec)

    if kind == "papers":
        return PapersScanner(feed, name=name)
    if kind == "model_registry":
        return ModelRegistryScanner(feed, name=name)
    if kind == "dependencies":
        return DependencyScanner(feed, name=name)
    if kind == "research":
        return ResearchSourceScanner(feed, name=name)
    return KanbanScanner(feed, name=name)


def scan_one(spec: dict, registry: ExperimentRegistry, fetch: Fetch | None = None) -> dict:
    """Run exactly ONE source (the body of a dynamically-mapped Airflow task). Returns a
    ScanOutcome dict; any fetch/scan error is captured as outcome.error, never swallowed."""
    scanner = build_scanner(spec, registry, fetch)
    outcome = run_scanners([scanner], isolate=True)[0]
    metadata = spec.get("config", {})
    for finding in outcome.findings:
        if metadata.get("repo_ids") and not finding.detail.get("repo_ids"):
            finding.detail["repo_ids"] = list(metadata["repo_ids"])
        if metadata.get("repository_reason") and not finding.detail.get("repository_reason"):
            finding.detail["repository_reason"] = metadata["repository_reason"]
    return outcome.to_dict()


def finish(outcome_dicts: list[dict], registry: ExperimentRegistry, *, date: str, now_iso: str,
           apply: bool = True, method: str = "wsjf", max_cards: int = 20,
           report_path: str = DEFAULT_REPORT_PATH, draft_kanban: bool = False,
           kanban_top: int = 3, card_drafter: Callable[..., str] | None = None) -> dict:
    """Stages 2–5 over the mapped scan outcomes: classify → rank → draft Proposed cards →
    emit one report. Observer-only — the only writes are through the ObserverCharter.

    When `draft_kanban` is set (and applying), the top findings are also drafted as human-gated
    Backlog cards on the first-party Self Improvement board. The card drafter is injectable
    (tests pass a fake); it defaults to the governed first-party board provider."""
    outcomes = [ScanOutcome.from_dict(d) for d in outcome_dicts]
    charter = ObserverCharter(registry, report_path=report_path)
    pipe = ScanPipeline(charter, method=method, max_cards=max_cards)
    report = pipe.run_from_outcomes(outcomes, date=date, now_iso=now_iso, apply=apply)
    result = report.to_dict()
    if apply and draft_kanban:
        from .kanban import command_center_card_drafter, draft_self_improvement_cards
        drafter = card_drafter if card_drafter is not None else command_center_card_drafter()
        cards = draft_self_improvement_cards(report, draft_card=drafter, top_n=kanban_top)
        result["kanban_cards"] = [c["experiment_id"] for c in cards]
    return result


def offline_specs() -> list[dict]:
    """The sources that need no network (always runnable, even with no feeds configured)."""
    return [s for s in SOURCE_REGISTRY if s["kind"] in _OFFLINE_KINDS]


def pillar_of(spec: dict) -> Pillar:
    return Pillar(spec["pillar"])
