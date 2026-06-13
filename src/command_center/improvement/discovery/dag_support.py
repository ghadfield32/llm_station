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

from collections.abc import Callable

from ..registry import ExperimentRegistry
from .charter import ObserverCharter
from .pillars import Pillar
from .pipeline import ScanPipeline
from .sources import (
    CodeHealthScanner, DependencyScanner, KanbanScanner, LedgerHealthScanner,
    ModelRegistryScanner, PapersScanner, ScanOutcome, Scanner, run_scanners,
)

DEFAULT_REPORT_PATH = "generated/self-improvement-report.md"

_OFFLINE_KINDS = frozenset({"code_health", "ledger"})
_FEED_KINDS = frozenset({"papers", "model_registry", "dependencies", "kanban"})

# The standing set of sources the daily scan maps over. Each is XCom-safe (plain dict).
# Offline sources need no fetch; feed sources read their records from the DAG's fetch.
SOURCE_REGISTRY: list[dict] = [
    {"name": "code_health", "kind": "code_health",
     "pillar": "code_quality", "config": {"root": "src"}},
    {"name": "ledger", "kind": "ledger", "pillar": "reliability_observability", "config": {}},
    {"name": "arxiv", "kind": "papers", "pillar": "full_idea", "config": {}},
    {"name": "litellm_registry", "kind": "model_registry",
     "pillar": "updated_metrics", "config": {}},
    {"name": "pip_audit", "kind": "dependencies", "pillar": "code_quality", "config": {}},
    {"name": "kanban_cycle_time", "kind": "kanban", "pillar": "automation", "config": {}},
]

# A fetch maps a source spec -> its already-parsed records (the DAG owns the live call).
Fetch = Callable[[dict], list[dict]]


def build_scanner(spec: dict, registry: ExperimentRegistry,
                  fetch: Fetch | None = None) -> Scanner:
    """Construct the one scanner a source spec describes. For feed kinds the live `fetch` is
    bound as a closure that runs at scan() time (so its errors land inside the isolate guard)."""
    kind = spec["kind"]
    name = spec["name"]
    config = spec.get("config", {})
    if kind == "code_health":
        return CodeHealthScanner(config.get("root", "src"), name=name)
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
    return KanbanScanner(feed, name=name)


def scan_one(spec: dict, registry: ExperimentRegistry, fetch: Fetch | None = None) -> dict:
    """Run exactly ONE source (the body of a dynamically-mapped Airflow task). Returns a
    ScanOutcome dict; any fetch/scan error is captured as outcome.error, never swallowed."""
    scanner = build_scanner(spec, registry, fetch)
    outcome = run_scanners([scanner], isolate=True)[0]
    return outcome.to_dict()


def finish(outcome_dicts: list[dict], registry: ExperimentRegistry, *, date: str, now_iso: str,
           apply: bool = True, method: str = "wsjf", max_cards: int = 20,
           report_path: str = DEFAULT_REPORT_PATH) -> dict:
    """Stages 2–5 over the mapped scan outcomes: classify → rank → draft Proposed cards →
    emit one report. Observer-only — the only writes are through the ObserverCharter."""
    outcomes = [ScanOutcome.from_dict(d) for d in outcome_dicts]
    charter = ObserverCharter(registry, report_path=report_path)
    pipe = ScanPipeline(charter, method=method, max_cards=max_cards)
    report = pipe.run_from_outcomes(outcomes, date=date, now_iso=now_iso, apply=apply)
    return report.to_dict()


def offline_specs() -> list[dict]:
    """The sources that need no network (always runnable, even with no feeds configured)."""
    return [s for s in SOURCE_REGISTRY if s["kind"] in _OFFLINE_KINDS]


def pillar_of(spec: dict) -> Pillar:
    return Pillar(spec["pillar"])
