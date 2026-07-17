from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import yaml

from command_center.job_search.config import data_root, ensure_data_dirs, load_config
from command_center.job_search.application_memory import save_application
from command_center.job_search.schemas import ApplicationRecord
from command_center.write_locking import application_memory_write_lock


def _parse_day(value: str) -> date:
    return datetime.fromisoformat(value).date()


def _archive_db(root: Path) -> Path:
    path = root / "applications_archive" / "outcomes.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_db(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS outcomes (
                application_id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                role_title TEXT NOT NULL,
                source TEXT NOT NULL,
                portal TEXT NOT NULL,
                applied_at TEXT,
                final_status TEXT NOT NULL,
                category TEXT NOT NULL,
                resume_variant TEXT NOT NULL,
                fit_score INTEGER NOT NULL,
                salary_min INTEGER,
                salary_max INTEGER,
                bullet_ids_used TEXT NOT NULL,
                archived_at TEXT NOT NULL
            )
            """
        )


def plan_retention(*, root: Path | None = None, today: date | None = None) -> dict:
    cfg = load_config()
    base = root or data_root(cfg)
    ensure_data_dirs(base)
    now = today or date.today()
    active_statuses = set(cfg.retention.active_statuses)
    rows: list[dict] = []
    for app_file in (base / "applications_active").glob("*/application.yml"):
        record = ApplicationRecord.model_validate(yaml.safe_load(app_file.read_text(encoding="utf-8")))
        retention_until = _parse_day(record.retention_until)
        active = record.status in active_statuses or record.stage == "interviewing"
        if record.keep_rich:
            action = "retain_keep_rich"
        elif not record.applied_at:
            # The outcomes ledger is specifically a history of jobs actually
            # submitted. Prepared/abandoned packets remain outside that DB.
            action = "retain_not_applied"
        elif record.rich_compacted and record.archived_at:
            action = "already_archived"
        elif active and retention_until >= now:
            action = "retain_active_process"
        elif retention_until < now:
            action = "archive_compact"
        else:
            action = "retain_until_retention_date"
        rows.append(
            {
                "application_id": record.application_id,
                "status": record.status,
                "stage": record.stage,
                "retention_until": record.retention_until,
                "action": action,
                "path": str(app_file.parent),
            }
        )
    return {
        "today": now.isoformat(),
        "purge_rich_files": cfg.retention.purge_rich_files,
        "records": rows,
    }


def apply_retention(*, root: Path | None = None, today: date | None = None) -> dict:
    cfg = load_config()
    base = root or data_root(cfg)
    plan = plan_retention(root=base, today=today)
    db_path = _archive_db(base)
    _ensure_db(db_path)
    archived: list[str] = []
    for row in plan["records"]:
        if row["action"] != "archive_compact":
            continue
        app_dir = Path(row["path"])
        application_id = str(row["application_id"])
        with application_memory_write_lock(base, application_id):
            # Re-read under the same lock used by notes/submission. A plan can
            # become stale between preview and apply; a qualifying message must
            # win instead of being overwritten by archival metadata.
            record = ApplicationRecord.model_validate(
                yaml.safe_load(
                    (app_dir / "application.yml").read_text(encoding="utf-8"))
            )
            retention_until = _parse_day(record.retention_until)
            if (
                not record.applied_at
                or record.keep_rich
                or (record.rich_compacted and record.archived_at)
                or retention_until >= _parse_day(plan["today"])
            ):
                continue
            archived_at = plan["today"]
            with sqlite3.connect(db_path) as db:
                db.execute(
                    """
                    INSERT OR REPLACE INTO outcomes (
                        application_id, company, role_title, source, portal, applied_at,
                        final_status, category, resume_variant, fit_score, salary_min, salary_max,
                        bullet_ids_used, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.application_id,
                        record.company,
                        record.role_title,
                        record.source,
                        record.portal,
                        record.applied_at,
                        record.status,
                        record.category,
                        record.resume_variant,
                        record.fit.score,
                        record.salary.min,
                        record.salary.max,
                        ",".join(record.bullet_ids_used),
                        archived_at,
                    ),
                )
            record.archived_at = archived_at
            record.rich_compacted = True
            save_application(app_dir, record)
            (app_dir / "ARCHIVED_MINIMAL_LEDGER_WRITTEN.txt").write_text(
                "Minimal archive row written. Rich file deletion is disabled by default.\n",
                encoding="utf-8",
            )
            archived.append(record.application_id)
    return {"archived": archived, "db_path": str(db_path), "plan": plan}
