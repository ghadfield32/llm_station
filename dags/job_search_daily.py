"""
job_search_daily - prepare/manual-first job-search maintenance DAG.

This DAG has no submit authority. Its MVP responsibilities are profile readiness,
live discovery, local/example suggestion validation, digest generation, and
retention planning.
"""
from __future__ import annotations

from datetime import datetime, timedelta

try:
    from airflow.decorators import dag, task
    from airflow.timetables.trigger import CronTriggerTimetable

    AIRFLOW_AVAILABLE = True
except ModuleNotFoundError:  # lets local unit tests import this file without Airflow installed
    AIRFLOW_AVAILABLE = False


if AIRFLOW_AVAILABLE:

    @dag(
        dag_id="job_search_daily",
        description="Prepare/manual-first job-search suggestions, digest, and retention",
        schedule=CronTriggerTimetable("0 8 * * *", timezone="America/New_York"),
        start_date=datetime(2026, 1, 1),
        catchup=False,
        max_active_runs=1,
        default_args={"retries": 1, "retry_delay": timedelta(minutes=5), "owner": "command-center"},
        tags=["job-search", "manual-first", "no-submit"],
        doc_md=__doc__,
    )
    def job_search_daily():
        @task
        def load_profile() -> dict:
            from command_center.job_search.profile_ingest import ingest_profile

            return ingest_profile()

        @task
        def validate_examples() -> dict:
            from pathlib import Path

            from command_center.job_search.cli import _suggest_from_file

            rows = []
            for example in sorted(Path("docs/job_search/examples").glob("*.md")):
                result = _suggest_from_file(example, write=True)
                rows.append(
                    {
                        "file": str(example),
                        "job_key": result["job"]["job_key"],
                        "score": result["fit"]["score"],
                        "automation": result["automation"]["value"],
                    }
                )
            return {"examples": rows}

        @task
        def discover_live() -> dict:
            from pathlib import Path

            from command_center.job_search.cli import _suggest_from_file
            from command_center.job_search.live_sources import discover_live_postings

            runs = [
                discover_live_postings(
                    sources=["jobicy"],
                    tags=[
                        "python",
                        "machine-learning",
                        "sql",
                        "analytics",
                        "dbt",
                        "snowflake",
                        "airflow",
                        "experimentation",
                    ],
                    industries=[
                        "data-science",
                        "engineering",
                        "dev",
                        "management",
                        "accounting-finance",
                        "marketing",
                        "business",
                    ],
                    count=100,
                    write=True,
                ),
                discover_live_postings(
                    sources=["remotive"],
                    tags=[
                        "data",
                        "analytics",
                        "machine learning",
                        "ai engineer",
                        "data engineer",
                        "python",
                        "sql",
                        "dbt",
                        "snowflake",
                        "airflow",
                    ],
                    count=100,
                    write=True,
                ),
                discover_live_postings(
                    sources=["remoteok"],
                    tags=[],
                    count=100,
                    write=True,
                ),
            ]
            posting_paths = []
            seen_paths = set()
            for run in runs:
                for path in run["posting_paths"]:
                    if path not in seen_paths:
                        seen_paths.add(path)
                        posting_paths.append(path)
            suggestions = []
            for path in posting_paths:
                result = _suggest_from_file(Path(path), write=True)
                suggestions.append(
                    {
                        "file": str(path),
                        "job_key": result["job"]["job_key"],
                        "score": result["fit"]["score"],
                        "automation": result["automation"]["value"],
                    }
                )
            return {
                "runs": runs,
                "postings_found": sum(run["postings_found"] for run in runs),
                "posting_paths": posting_paths,
                "suggestions_written": suggestions,
            }

        @task
        def publish_to_board(_live: dict) -> dict:
            from command_center.job_search.board import publish_suggestions

            return publish_suggestions(backend="internal", apply=True,
                                       exclude_sources=("fixture",))

        @task
        def process_geoff_selected(_published: dict) -> dict:
            from command_center.job_search.board import process_selected

            return process_selected(backend="internal", apply=True, executor="codex")

        @task
        def retention_plan() -> dict:
            from command_center.job_search.retention import plan_retention

            return plan_retention()

        @task
        def emit_digest(
            _profile: dict,
            _live: dict,
            _examples: dict,
            _published: dict,
            _processed: dict,
            _retention: dict,
        ) -> str:
            from command_center.job_search.digest import write_digest

            return str(write_digest())

        profile = load_profile()
        live = discover_live()
        examples = validate_examples()
        published = publish_to_board(live)
        processed = process_geoff_selected(published)
        retention = retention_plan()
        emit_digest(profile, live, examples, published, processed, retention)

    dag = job_search_daily()
else:
    dag = None
