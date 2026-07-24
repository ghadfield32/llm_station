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
        def verified_runtime_backup() -> dict:
            """Hard prerequisite: no daily job mutation without a verified snapshot."""
            from command_center.runtime_backup import create_default_snapshot

            manifest = create_default_snapshot()
            return {key: manifest.get(key) for key in (
                "snapshot_id", "source_set_watermark", "gate_checked_at",
                "created_at", "consistency", "reused_exact_watermark",
            ) if manifest.get(key) is not None}

        @task
        def load_profile(_backup: dict) -> dict:
            from command_center.job_search.profile_ingest import ingest_profile

            return ingest_profile()

        @task
        def validate_examples(_backup: dict) -> dict:
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
        def discover_live(_backup: dict) -> dict:
            from pathlib import Path

            from command_center.job_search.cli import (
                _daily_discovery_terms,
                _suggest_from_file,
            )
            from command_center.job_search.config import load_config
            from command_center.job_search.live_sources import discover_live_postings

            # Search terms derive from the ADJUSTABLE job categories
            # (configs/job_search.yaml + profile/search_settings.yml overrides,
            # editable from the cockpit Jobs settings drawer) — changing a
            # category's keywords changes what this DAG looks for tomorrow.
            cfg = load_config()
            keywords, company_targets, remotive_searches = (
                _daily_discovery_terms(cfg))
            # Jobicy wants slug-style tags; Remotive takes free text.
            jobicy_tags = sorted({kw.lower().replace(" ", "-") for kw in keywords})

            runs = [
                discover_live_postings(
                    sources=["jobicy"],
                    tags=jobicy_tags,
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
                    tags=remotive_searches,
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
                "company_targets": company_targets,
                "remotive_searches_today": remotive_searches,
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
        def retention_plan(_backup: dict) -> dict:
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
        ) -> dict:
            from command_center.job_search.digest import (
                read_digest_items,
                write_digest,
            )

            path = write_digest()
            return {"path": str(path), "items": read_digest_items()}

        @task
        def push_digest(digest: dict) -> dict:
            """Notify only; missing channel config records the exact would-send."""
            import json
            import os
            from pathlib import Path

            from command_center.cli.notify import read_env, send_discord
            from command_center.job_search.proactive import (
                render_job_digest_ping,
            )

            env = {**read_env(), **os.environ}
            board_url = (
                env.get("JOB_SEARCH_BOARD_URL")
                or env.get("KANBAN_UI_URL")
                or (
                    "http://127.0.0.1:8787/"
                    "?view=domains&domain=job_application"
                )
            )
            line = render_job_digest_ping(digest["items"], board_url)
            if line is None:
                print("[job_search_daily] no reviewable jobs; no digest push")
                return {"status": "no_push", "count": 0}

            record_path = Path(digest["path"]).with_name(
                "job-search-digest-push.log"
            )

            def record(status: str, detail: str) -> dict:
                row = {
                    "at": datetime.now().astimezone().isoformat(),
                    "status": status,
                    "detail": detail,
                    "line": line,
                }
                print(
                    f"[job_search_daily] {status.upper()}: {detail}; "
                    f"would-send: {line}"
                )
                try:
                    with record_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                except OSError as exc:
                    # The Airflow task log above is itself the durable fallback.
                    print(
                        "[job_search_daily] notification record file unavailable: "
                        f"{type(exc).__name__}: {exc}"
                    )
                return {
                    "status": status,
                    "count": len(digest["items"]),
                    "record_path": str(record_path),
                    "line": line,
                }

            token = env.get("DISCORD_BOT_TOKEN", "")
            channel = env.get("DISCORD_CHANNEL_ID") or next(
                (
                    value.strip()
                    for value in env.get(
                        "DISCORD_ALLOWED_CHANNEL_IDS", ""
                    ).split(",")
                    if value.strip()
                ),
                "",
            )
            missing = [
                name
                for name, value in (
                    ("DISCORD_BOT_TOKEN", token),
                    (
                        "DISCORD_CHANNEL_ID "
                        "(or DISCORD_ALLOWED_CHANNEL_IDS)",
                        channel,
                    ),
                )
                if not value
            ]
            if missing:
                return record(
                    "recorded_only",
                    "channel unconfigured; missing " + ", ".join(missing),
                )
            try:
                send_discord(channel, token, line)
            except Exception as exc:
                return record(
                    "error",
                    f"channel send failed: {type(exc).__name__}: {exc}",
                )
            print(
                "[job_search_daily] SENT: "
                f"{len(digest['items'])} reviewable job(s) to channel {channel}"
            )
            return {
                "status": "sent",
                "count": len(digest["items"]),
                "channel": channel,
                "line": line,
            }

        backup = verified_runtime_backup()
        profile = load_profile(backup)
        live = discover_live(backup)
        examples = validate_examples(backup)
        published = publish_to_board(live)
        processed = process_geoff_selected(published)
        retention = retention_plan(backup)
        digest = emit_digest(
            profile, live, examples, published, processed, retention
        )
        push_digest(digest)

    dag = job_search_daily()
else:
    dag = None
