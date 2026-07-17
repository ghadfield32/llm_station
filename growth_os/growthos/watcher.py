"""Observable first-party board upkeep loop.

This replaces the retired shell loop that swallowed every task failure with
``|| true``. Each task outcome is logged and atomically recorded so one failed
source remains visible while later hourly retries continue.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import tempfile
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable

from command_center.write_locking import BoardWriteLocked, exclusive_write_lock
from .models import RESEARCH_ANALYSIS_SCHEMA_VERSION

log = logging.getLogger("growthos.watcher")
Task = Callable[[], object]


def _tasks() -> tuple[dict[str, Task], dict[str, Task]]:
    from . import airflow_sync, brief, curate, guidelines, retention

    def maintenance_review() -> object:
        base = os.environ.get("KANBAN_UI_BASE_URL", "http://agent-kanban-ui:8787")
        request = urllib.request.Request(
            f"{base.rstrip('/')}/api/kanban-maintenance/scan",
            data=b"{}", headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError(f"maintenance API returned HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))

    return (
        {"curate": curate.run, "airflow_sync": airflow_sync.main},
        {"brief": brief.main, "guidelines": guidelines.main,
         "retention": retention.main, "kanban_maintenance": maintenance_review},
    )


def _atomic_status(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _refresh_lock(path: Path):
    return exclusive_write_lock(path.parent / ".research-refresh.write.lock")


def _read_refresh(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _replace_refresh_if_current(
    path: Path, request_id: str, value: dict,
) -> bool:
    """Replace status unless the cockpit queued a newer request meanwhile."""
    with _refresh_lock(path):
        current = _read_refresh(path)
        if current.get("request_id") != request_id:
            return False
        _atomic_status(path, value)
        return True


def process_research_refresh(
    *, refresh_path: Path, backup: Task | None = None,
) -> dict | None:
    """Run one durable ingestion + bounded-analysis unit when requested.

    Every invocation handles at most one analysis batch per requested board.
    Remaining cards stay queued for the next short control poll, keeping status
    current and ensuring an unavailable local model fails visibly instead of
    creating an unbounded hot loop.
    """
    with _refresh_lock(refresh_path):
        request = _read_refresh(refresh_path)
        if request.get("state") not in {"queued", "running"}:
            return None
        request_id = str(request.get("request_id") or "")
        if not request_id:
            return None
        request = {
            **request,
            "state": "running",
            "analysis_schema_version": RESEARCH_ANALYSIS_SCHEMA_VERSION,
            "analysis": (
                request.get("analysis", {})
                if request.get("analysis_schema_version")
                == RESEARCH_ANALYSIS_SCHEMA_VERSION
                else {}
            ),
            "started_at": request.get("started_at")
            or datetime.now().astimezone().isoformat(),
            "message": "Refreshing sources and filling research details",
        }
        _atomic_status(refresh_path, request)

    if backup is None:
        from command_center.runtime_backup import create_default_snapshot
        backup = create_default_snapshot
    try:
        receipt = None
        prior_snapshot_id = str(request.get("backup_snapshot_id") or "")
        if prior_snapshot_id:
            from command_center.runtime_backup import (
                default_sources, verify_snapshot_authorities,
            )
            root = Path(os.environ.get(
                "KANBAN_BACKUP_ROOT", "backups/kanban"))
            authorities = [
                source for source in default_sources()
                if source.name in {"domain_config", "autonomy_config"}
            ]
            try:
                receipt = verify_snapshot_authorities(
                    root / prior_snapshot_id, authorities)
            except Exception as exc:
                log.warning(
                    "research refresh backup receipt is stale; creating a "
                    "current authority snapshot: %s", exc)
        if receipt is None:
            receipt = backup()
        from . import curate
        from .config import load_config, load_settings
        from .internal_board import InternalBoardClient

        settings = load_settings()
        config = load_config(
            domain_surfaces_path=settings.growthos_domain_surfaces)
        boards = InternalBoardClient(
            store_dir=settings.growthos_board_store,
            event_log=settings.growthos_kanban_event_log,
            dry_run=settings.growthos_dry_run,
            out_dir="./_export",
        )
        ingested = list(request.get("ingested_sources") or [])
        ingestion = dict(request.get("ingestion") or {})
        analysis = dict(request.get("analysis") or {})
        requested = [
            source for source in request.get("requested_sources", [])
            if source in {"paper", "repo"}
        ]
        mapping = {
            "paper": ("arxiv", "papers", config.sources.arxiv.analysis_batch_size),
            "repo": ("github", "repos", config.sources.github.analysis_batch_size),
        }
        for source in requested:
            provider, db_name, batch_size = mapping[source]
            if source not in ingested:
                ingestion[source] = curate.run(only=provider)
                ingested.append(source)
            previous = dict(analysis.get(source, {}) or {})
            before = boards.analysis_progress(db_name)
            baseline_complete = int(previous.get(
                "baseline_complete", before["complete"]))
            batch = curate.run(
                reanalyze=db_name, analysis_limit=batch_size)
            progress = boards.analysis_progress(db_name)
            analysis[source] = {
                **batch,
                "analysis_schema_version": RESEARCH_ANALYSIS_SCHEMA_VERSION,
                "baseline_complete": baseline_complete,
                "stored_total": progress["stored_total"],
                "strict_total": progress["total"],
                "strict_titled": progress["titled"],
                "strict_complete": progress["complete"],
                "strict_pending": progress["pending"],
                "missing_title": progress["missing_title"],
                "completed_this_request": max(
                    0, progress["complete"] - baseline_complete),
                "remaining": progress["pending"] > 0,
            }
        remaining = [
            source for source in requested
            if analysis.get(source, {}).get("remaining")
        ]
        stalled = [
            source for source in remaining
            if int(analysis.get(source, {}).get(
                f"{'papers' if source == 'paper' else 'repos'}_analysis_complete", 0
            )) == 0
        ]
        if stalled:
            state = "blocked"
            message = (
                "Analysis could not complete a batch for: "
                + ", ".join(stalled)
                + ". Check the local model, then retry."
            )
        elif remaining:
            state = "queued"
            message = "Source refresh finished; continuing analysis backfill"
        else:
            state = "complete"
            message = "Research sources and complete card details are up to date"
        finished = {
            **request,
            "state": state,
            "message": message,
            "ingested_sources": ingested,
            "ingestion": ingestion,
            "analysis": analysis,
            "last_batch_at": datetime.now().astimezone().isoformat(),
        }
        if state in {"complete", "blocked"}:
            finished["finished_at"] = datetime.now().astimezone().isoformat()
        if isinstance(receipt, dict) and receipt.get("snapshot_id"):
            finished["backup_snapshot_id"] = str(receipt["snapshot_id"])
    except (Exception, SystemExit) as exc:
        log.error("research refresh failed: %s\n%s", exc, traceback.format_exc())
        finished = {
            **request,
            "state": "blocked",
            "message": "Research refresh failed; inspect watcher logs and retry",
            "finished_at": datetime.now().astimezone().isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    _replace_refresh_if_current(refresh_path, request_id, finished)
    return finished


def _run_with_lock_retry(
    name: str, task: Task, *, attempts: int, delay_seconds: float,
) -> None:
    """Retry only safe board-lock contention inside the current upkeep cycle."""
    for attempt in range(1, attempts + 1):
        try:
            task()
            return
        except BoardWriteLocked:
            if attempt == attempts:
                raise
            log.warning(
                "%s hit board contention; retrying %s/%s in %.2fs",
                name, attempt + 1, attempts, delay_seconds,
            )
            time.sleep(delay_seconds)


def run_cycle(
    *, status_path: Path, now: datetime, daily_hour: int,
    hourly: dict[str, Task] | None = None,
    daily: dict[str, Task] | None = None,
    backup: Task | None = None,
    lock_retry_attempts: int = 4,
    lock_retry_delay: float = 0.25,
) -> dict:
    if lock_retry_attempts <= 0 or lock_retry_delay < 0:
        raise ValueError("lock retry policy requires attempts > 0 and delay >= 0")
    if hourly is None or daily is None:
        default_hourly, default_daily = _tasks()
        hourly = default_hourly if hourly is None else hourly
        daily = default_daily if daily is None else daily
    prior = {}
    if status_path.is_file():
        prior = json.loads(status_path.read_text(encoding="utf-8"))
    today = now.date().isoformat()
    daily_success = dict(prior.get("last_daily_success") or {})
    due_daily = {
        name: task for name, task in daily.items()
        if now.hour >= daily_hour and daily_success.get(name) != today
    }
    selected = {**hourly, **due_daily}
    outcomes: dict[str, dict[str, str]] = {}
    if backup is None:
        from command_center.runtime_backup import create_default_snapshot
        backup = create_default_snapshot
    backup_started = datetime.now().astimezone().isoformat()
    try:
        receipt = backup()
    except (Exception, SystemExit) as exc:
        log.error("backup failed; all mutating upkeep is blocked: %s\n%s",
                  exc, traceback.format_exc())
        outcomes["backup"] = {
            "status": "failed", "started_at": backup_started,
            "finished_at": datetime.now().astimezone().isoformat(),
            "error_type": type(exc).__name__, "error": str(exc),
        }
        for name in selected:
            outcomes[name] = {
                "status": "skipped_backup", "started_at": backup_started,
                "finished_at": datetime.now().astimezone().isoformat(),
                "error_type": "BackupPrerequisiteFailed",
                "error": "verified current backup is required before mutating upkeep",
            }
        result = {
            "schema_version": "growthos.watcher-status.v1",
            "cycle_started_at": now.astimezone().isoformat(),
            "cycle_finished_at": datetime.now().astimezone().isoformat(),
            "last_daily_success": daily_success,
            "tasks": outcomes,
        }
        _atomic_status(status_path, result)
        return result
    outcomes["backup"] = {
        "status": "ok", "started_at": backup_started,
        "finished_at": datetime.now().astimezone().isoformat(),
    }
    if isinstance(receipt, dict):
        for key in ("snapshot_id", "source_set_watermark", "created_at"):
            if receipt.get(key) is not None:
                outcomes["backup"][key] = str(receipt[key])
    for name, task in selected.items():
        started = datetime.now().astimezone().isoformat()
        if name == "kanban_maintenance" and any(
            row.get("status") != "ok" for prior_name, row in outcomes.items()
            if prior_name != "backup"
        ):
            outcomes[name] = {
                "status": "skipped_dependency", "started_at": started,
                "finished_at": datetime.now().astimezone().isoformat(),
                "error_type": "SourceReconciliationIncomplete",
                "error": "maintenance suggestions require all preceding sync tasks to succeed",
            }
            continue
        try:
            _run_with_lock_retry(
                name, task,
                attempts=lock_retry_attempts,
                delay_seconds=lock_retry_delay,
            )
        except (Exception, SystemExit) as exc:
            log.error("%s failed: %s\n%s", name, exc, traceback.format_exc())
            outcomes[name] = {
                "status": "failed", "started_at": started,
                "finished_at": datetime.now().astimezone().isoformat(),
                "error_type": type(exc).__name__, "error": str(exc),
            }
        else:
            outcomes[name] = {
                "status": "ok", "started_at": started,
                "finished_at": datetime.now().astimezone().isoformat(),
            }
            if name in due_daily:
                daily_success[name] = today
    result = {
        "schema_version": "growthos.watcher-status.v1",
        "cycle_started_at": now.astimezone().isoformat(),
        "cycle_finished_at": datetime.now().astimezone().isoformat(),
        "last_daily_success": daily_success,
        "tasks": outcomes,
    }
    _atomic_status(status_path, result)
    return result


def _install_stop_event() -> threading.Event:
    """Turn termination signals into graceful stop requests.

    The handler never raises inside a board transaction. The current cycle runs
    to completion, releases its cross-process locks, and the outer loop exits
    before another cycle starts.
    """
    stop_event = threading.Event()

    def request_stop(signum, _frame) -> None:
        log.info("received signal %s; finishing the active cycle before exit", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    return stop_event


def _initial_upkeep_delay(refresh_path: Path, interval: int) -> float:
    """Resume durable research work before repeating a recent upkeep cycle."""
    request = _read_refresh(refresh_path)
    return float(interval) if request.get("state") in {"queued", "running"} else 0.0


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("GROWTHOS_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    interval = int(os.environ.get("GROWTHOS_WATCH_INTERVAL_SECONDS", "3600"))
    control_poll = int(os.environ.get("GROWTHOS_CONTROL_POLL_SECONDS", "5"))
    daily_hour = int(os.environ.get("GROWTHOS_DAILY_HOUR", "6"))
    if interval <= 0 or control_poll <= 0 or not 0 <= daily_hour <= 23:
        raise SystemExit(
            "watcher cadence requires positive interval/control poll and daily hour 0..23")
    status_path = Path(os.environ.get(
        "GROWTHOS_WATCHER_STATUS", "./_state/watcher_status.json"))
    refresh_path = Path(os.environ.get(
        "GROWTHOS_RESEARCH_REFRESH", "./_state/research_refresh.json"))
    stop_event = _install_stop_event()
    initial_delay = _initial_upkeep_delay(refresh_path, interval)
    deadline = time.monotonic() + initial_delay
    if initial_delay:
        log.info(
            "active research refresh detected; resuming it before the next "
            "upkeep cycle in %ss", interval,
        )
    while not stop_event.is_set():
        if time.monotonic() >= deadline:
            result = run_cycle(
                status_path=status_path,
                now=datetime.now().astimezone(),
                daily_hour=daily_hour,
            )
            failed = [name for name, row in result["tasks"].items()
                      if row["status"] == "failed"]
            log.info(
                "cycle complete; failed=%s; next upkeep cycle in %ss",
                failed, interval,
            )
            deadline = time.monotonic() + interval
        if stop_event.is_set():
            log.info("graceful watcher shutdown complete")
            break
        process_research_refresh(refresh_path=refresh_path)
        remaining = max(0.0, deadline - time.monotonic())
        if stop_event.wait(min(control_poll, remaining)):
            log.info("graceful watcher shutdown complete")
            break


if __name__ == "__main__":
    main()
