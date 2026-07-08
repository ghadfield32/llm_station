"""
job_search_daily - prepare/manual-first job-search maintenance DAG.

This DAG has no submit authority. Its MVP responsibilities are profile readiness,
local/example suggestion validation, digest generation, and retention planning.
Live source adapters and AppFlowy writes should be added only after the CLI path
and manual blocker tests are reliable.
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
        def retention_plan() -> dict:
            from command_center.job_search.retention import plan_retention

            return plan_retention()

        @task
        def emit_digest(_profile: dict, _examples: dict, _retention: dict) -> str:
            from command_center.job_search.digest import write_digest

            return str(write_digest())

        profile = load_profile()
        examples = validate_examples()
        retention = retention_plan()
        emit_digest(profile, examples, retention)

    dag = job_search_daily()
else:
    dag = None
