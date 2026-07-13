"""
self_improvement_daily — the scheduled, observer-only self-improvement scan.

Once a day (and on demand from any touchpoint) the control plane runs its own improvement loop
ON ITSELF: it scans many sources across nine pillars — automation, structure, updated metrics
(models/providers/leaderboards), code quality, rules/standards, data handling, full-idea research,
reliability/observability, cost/FinOps — classifies and dedupes the findings, ranks them
(ICE/RICE/WSJF/VOI), and drafts BOUNDED experiment proposals.

╔══════════════════════════════════════════════════════════════════════════════════════╗
║ OBSERVER-ONLY — THE HUMAN WALL IS STRUCTURAL                                            ║
║ This DAG holds NO write/promote/merge/deploy credentials. Its ONLY outputs are          ║
║ `Proposed` Backlog cards and ONE decision-grade report, written exclusively through     ║
║ the ObserverCharter (which exposes no promote/canary/merge/deploy/set_status method).   ║
║ It never auto-merges a dependency PR. Promotion and canary stay HUMAN-ONLY at the       ║
║ Kanban wall. Even a buggy or compromised task cannot escalate — the capability is not   ║
║ reachable from here.                                                                     ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

Stages (the addendum's pipeline; stage 1 is dynamically task-mapped, one task per source):
    scan_*  →  classify_and_dedup  →  score_and_rank  →  draft_proposals  →  emit_report_and_cards

Idempotency: experiment ids are content hashes of the finding, drafting is dedup-guarded, and
the run is keyed to its logical date — re-running a day produces no duplicate cards.

Scheduling: DatasetOrTimeSchedule = daily cron OR an out-of-band trigger. The SCAN_REQUEST
dataset is the "set it loose from Kanban/Discord/CLI" signal — updating that asset fires a scan
between the daily runs. (On Airflow 3.x: Dataset→Asset, DatasetOrTimeSchedule→AssetOrTimeSchedule.)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from airflow.datasets import Dataset
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.timetables.datasets import DatasetOrTimeSchedule
from airflow.timetables.trigger import CronTriggerTimetable

from command_center.improvement.discovery import dag_support

# The five logical stages (stage 1 fans out per source). Kept explicit for operators + tests.
STAGES = ["scan", "classify_and_dedup", "score_and_rank", "draft_proposals",
          "emit_report_and_cards"]

# "Set it loose" signal: any touchpoint (Kanban automation, Discord bot, CLI) can update this
# asset to request an out-of-band scan in addition to the daily cron.
SCAN_REQUEST = Dataset("command-center://improvement/scan-request")

# The report itself is published as an asset other DAGs/automations can subscribe to.
REPORT_ASSET = Dataset("command-center://improvement/daily-report")

LEDGER_DB_PATH = os.environ.get("LEDGER_DB_PATH", "data/ledger.db")
# Apply (draft real cards) by default; set to "false" for a read-only preview run.
APPLY = os.environ.get("SELF_IMPROVEMENT_APPLY", "true").lower() == "true"
# Draft the top findings as human-gated mission_intake cards each morning (off by default —
# opt in once the workspace board is reachable from the scheduler). Approval stays a human drag.
KANBAN = os.environ.get("SELF_IMPROVEMENT_KANBAN", "false").lower() == "true"
KANBAN_TOP = int(os.environ.get("SELF_IMPROVEMENT_KANBAN_TOP", "3"))


def _registry():
    # Imported lazily so DAG parsing never needs the full app on the scheduler.
    from command_center.improvement.registry import ExperimentRegistry
    return ExperimentRegistry(db_path=LEDGER_DB_PATH)


def _fetch(spec: dict) -> list[dict]:
    """Live records for a feed source.

    Most sources are pre-ingested into an Airflow Variable as a JSON list (an upstream
    ingestion task writes e.g. ``improvement_feed_arxiv``). The model/registry pillar is the
    exception: when its Variable is empty, this calls the model-scout bridge
    (``scan_feed_records``) directly and caches the result back into the Variable — so the
    SCHEDULED run is never blind to newly released models. GLM/Kimi enter the loop here via the
    watchlist (track-as-context for the ones too big to run; propose-pull for the ones that
    fit). Errors propagate into the per-source isolate guard as a visible failed source, never
    a silent empty pillar. (This is the wiring that makes the docstring's old "phantom upstream
    ingestion DAG" real for the model pillar.)"""
    raw = Variable.get(f"improvement_feed_{spec['name']}", default_var="")
    if raw:
        return json.loads(raw)
    if spec["name"] == "litellm_registry":
        from command_center.registry.model_scout import scan_feed_records
        records = scan_feed_records(offline=False)
        Variable.set("improvement_feed_litellm_registry", json.dumps(records))
        return records
    return []


@dag(
    dag_id="self_improvement_daily",
    description="Observer-only daily self-improvement scan (drafts Proposed cards + one report)",
    schedule=DatasetOrTimeSchedule(
        timetable=CronTriggerTimetable("0 6 * * *", timezone="UTC"),   # 06:00 UTC daily
        datasets=[SCAN_REQUEST],                                        # …or on demand
    ),
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,                          # no overlapping scans (idempotency)
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5), "owner": "command-center"},
    tags=["self-improvement", "observer-only", "human-gated"],
    doc_md=__doc__,
)
def self_improvement_daily():

    @task
    def list_sources() -> list[dict]:
        """The standing source set the scan fans out over (stage 1 is mapped over this)."""
        return dag_support.SOURCE_REGISTRY

    @task
    def scan(spec: dict) -> dict:
        """ONE source -> a ScanOutcome dict. Fetch/scan errors are captured as a visible
        failed source (never swallowed); other sources are unaffected."""
        return dag_support.scan_one(spec, _registry(), _fetch)

    @task(outlets=[REPORT_ASSET])
    def classify_rank_draft_emit(outcomes: list[dict], **context) -> dict:
        """Stages 2–5 in the tested pipeline: classify_and_dedup → score_and_rank →
        draft_proposals (Proposed cards via the charter) → emit_report_and_cards. Keyed to the
        run's logical date for deterministic, idempotent re-runs."""
        date = context["ds"]            # YYYY-MM-DD (logical date)
        now_iso = context["ts"]         # ISO-8601 logical timestamp
        report = dag_support.finish(outcomes, _registry(), date=date, now_iso=now_iso,
                                    apply=APPLY, draft_kanban=KANBAN, kanban_top=KANBAN_TOP)
        n_failed = report["n_failed"]
        if n_failed:
            # surfaced, not hidden: failed sources are in the report; flag them at the DAG level
            print(f"[self_improvement_daily] {n_failed} source(s) failed: "
                  f"{report['failed_sources']}")
        return report

    # stage 1 fans out per source; stages 2–5 collect and emit.
    outcomes = scan.expand(spec=list_sources())
    classify_rank_draft_emit(outcomes)


dag = self_improvement_daily()
