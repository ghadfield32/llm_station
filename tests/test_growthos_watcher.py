"""Observable Growth OS watcher behavior."""
from __future__ import annotations

import json
import sys
from types import ModuleType
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "growth_os"))
import growthos
from growthos.watcher import (
    _initial_upkeep_delay,
    _install_stop_event,
    process_research_refresh,
    run_cycle,
)
from command_center.write_locking import BoardWriteLocked


def _stub_curate(monkeypatch, run):
    """Install the narrow curate seam without importing optional source clients."""
    module = ModuleType("growthos.curate")
    module.run = run
    monkeypatch.setitem(sys.modules, "growthos.curate", module)
    monkeypatch.setattr(growthos, "curate", module, raising=False)


def test_failure_is_recorded_and_does_not_hide_other_tasks(tmp_path):
    called = []

    def fail():
        raise RuntimeError("source unavailable")

    result = run_cycle(
        status_path=tmp_path / "watcher.json",
        now=datetime(2026, 7, 15, 7),
        daily_hour=6,
        hourly={"curate": fail, "airflow": lambda: called.append("airflow")},
        daily={"brief": lambda: called.append("brief")},
        backup=lambda: {"snapshot_id": "S-1"},
    )

    assert called == ["airflow", "brief"]
    assert result["tasks"]["curate"]["status"] == "failed"
    assert result["tasks"]["curate"]["error"] == "source unavailable"
    assert json.loads((tmp_path / "watcher.json").read_text()) == result


def test_daily_tasks_run_once_per_date_but_hourly_tasks_keep_running(tmp_path):
    status = tmp_path / "watcher.json"
    called = []
    kwargs = {
        "status_path": status,
        "daily_hour": 6,
        "hourly": {"hourly": lambda: called.append("hourly")},
        "daily": {"daily": lambda: called.append("daily")},
        "backup": lambda: {"snapshot_id": "S-1"},
    }
    run_cycle(now=datetime(2026, 7, 15, 7), **kwargs)
    run_cycle(now=datetime(2026, 7, 15, 8), **kwargs)
    run_cycle(now=datetime(2026, 7, 16, 7), **kwargs)

    assert called == ["hourly", "daily", "hourly", "hourly", "daily"]


def test_failed_daily_task_retries_next_hour(tmp_path):
    status = tmp_path / "watcher.json"
    attempts = []

    def daily():
        attempts.append("daily")
        if len(attempts) == 1:
            raise RuntimeError("temporary failure")

    for hour in (7, 8, 9):
        run_cycle(
            status_path=status, now=datetime(2026, 7, 15, hour),
            daily_hour=6, hourly={}, daily={"daily": daily},
            backup=lambda: {"snapshot_id": "S-1"})

    assert attempts == ["daily", "daily"]
    saved = json.loads(status.read_text())
    assert saved["last_daily_success"]["daily"] == "2026-07-15"


def test_board_lock_contention_retries_inside_same_cycle(tmp_path):
    attempts = []

    def contended():
        attempts.append("try")
        if len(attempts) < 3:
            raise BoardWriteLocked("another writer")

    result = run_cycle(
        status_path=tmp_path / "watcher.json",
        now=datetime(2026, 7, 15, 7),
        daily_hour=6,
        hourly={"airflow": contended},
        daily={},
        backup=lambda: {"snapshot_id": "S-1"},
        lock_retry_attempts=4,
        lock_retry_delay=0,
    )

    assert attempts == ["try", "try", "try"]
    assert result["tasks"]["airflow"]["status"] == "ok"


def test_backup_runs_first_and_failure_blocks_every_mutation(tmp_path):
    called = []

    def fail_backup():
        called.append("backup")
        raise RuntimeError("backup disk unavailable")

    result = run_cycle(
        status_path=tmp_path / "watcher.json",
        now=datetime(2026, 7, 16, 7), daily_hour=6,
        backup=fail_backup,
        hourly={"curate": lambda: called.append("curate")},
        daily={"brief": lambda: called.append("brief")},
    )

    assert called == ["backup"]
    assert result["tasks"]["backup"]["status"] == "failed"
    assert result["tasks"]["curate"]["status"] == "skipped_backup"
    assert result["tasks"]["brief"]["status"] == "skipped_backup"


def test_backup_receipt_precedes_mutating_tasks(tmp_path):
    called = []
    result = run_cycle(
        status_path=tmp_path / "watcher.json",
        now=datetime(2026, 7, 16, 7), daily_hour=6,
        backup=lambda: called.append("backup") or {
            "snapshot_id": "S-current", "source_set_watermark": "abc"},
        hourly={"curate": lambda: called.append("curate")}, daily={},
    )
    assert called == ["backup", "curate"]
    assert result["tasks"]["backup"]["snapshot_id"] == "S-current"


def test_maintenance_skips_when_a_sync_dependency_failed(tmp_path):
    called = []

    def fail_sync():
        raise RuntimeError("source unavailable")

    result = run_cycle(
        status_path=tmp_path / "watcher.json",
        now=datetime(2026, 7, 16, 7), daily_hour=6,
        backup=lambda: {"snapshot_id": "S-current"},
        hourly={"curate": fail_sync},
        daily={"kanban_maintenance": lambda: called.append("maintenance")},
    )

    assert called == []
    assert result["tasks"]["kanban_maintenance"]["status"] == "skipped_dependency"


def test_maintenance_runs_after_successful_sources(tmp_path):
    called = []
    result = run_cycle(
        status_path=tmp_path / "watcher.json",
        now=datetime(2026, 7, 16, 7), daily_hour=6,
        backup=lambda: {"snapshot_id": "S-current"},
        hourly={"curate": lambda: called.append("curate")},
        daily={"kanban_maintenance": lambda: called.append("maintenance")},
    )

    assert called == ["curate", "maintenance"]
    assert result["tasks"]["kanban_maintenance"]["status"] == "ok"


def test_termination_signal_requests_graceful_cycle_exit(monkeypatch):
    handlers = {}
    monkeypatch.setattr(
        "growthos.watcher.signal.signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )

    stop_event = _install_stop_event()
    assert not stop_event.is_set()

    handlers[__import__("signal").SIGTERM](
        __import__("signal").SIGTERM, None)
    assert stop_event.is_set()


def test_compose_grace_period_can_drain_a_complete_research_unit():
    """Deployment must not force-kill a valid local-model batch before commit."""
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load(
        (root / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["growthos-watcher"]["stop_grace_period"] == "900s"


def test_active_refresh_defers_only_the_initial_upkeep_cycle(tmp_path):
    refresh = tmp_path / "research-refresh.json"
    assert _initial_upkeep_delay(refresh, 3600) == 0
    refresh.write_text(json.dumps({"state": "complete"}), encoding="utf-8")
    assert _initial_upkeep_delay(refresh, 3600) == 0
    refresh.write_text(json.dumps({"state": "queued"}), encoding="utf-8")
    assert _initial_upkeep_delay(refresh, 3600) == 3600
    refresh.write_text(json.dumps({"state": "running"}), encoding="utf-8")
    assert _initial_upkeep_delay(refresh, 3600) == 3600


def test_research_refresh_ingests_and_backfills_before_completing(
    monkeypatch, tmp_path,
):
    from types import SimpleNamespace

    refresh = tmp_path / "research-refresh.json"
    refresh.write_text(json.dumps({
        "schema_version": "growthos.research-refresh.v1",
        "request_id": "refresh-1",
        "state": "queued",
        "requested_sources": ["paper", "repo"],
        "ingested_sources": [],
        "analysis_schema_version": "growthos.research-analysis.v2",
        "analysis": {
            "paper": {"completed_this_request": 575},
            "repo": {"completed_this_request": 92},
        },
    }), encoding="utf-8")
    called = []
    monkeypatch.setattr(
        "growthos.config.load_settings",
        lambda: SimpleNamespace(
            growthos_domain_surfaces="domains.yaml",
            growthos_board_store=str(tmp_path / "boards"),
            growthos_kanban_event_log=str(tmp_path / "events.jsonl"),
            growthos_dry_run=False,
        ),
    )
    monkeypatch.setattr(
        "growthos.config.load_config",
        lambda **_kwargs: SimpleNamespace(sources=SimpleNamespace(
            arxiv=SimpleNamespace(analysis_batch_size=4),
            github=SimpleNamespace(analysis_batch_size=3),
        )),
    )
    _stub_curate(
        monkeypatch,
        lambda **kwargs: called.append(kwargs) or {
            (kwargs.get("reanalyze") or kwargs.get("only")): 1,
        },
    )
    monkeypatch.setattr(
        "growthos.internal_board.InternalBoardClient.analysis_candidates",
        lambda *_args, **_kwargs: [],
    )

    result = process_research_refresh(
        refresh_path=refresh,
        backup=lambda: called.append({"backup": True}) or {"snapshot_id": "S-1"},
    )

    assert result["state"] == "complete"
    assert result["analysis_schema_version"] == "growthos.research-analysis.v5"
    assert result["ingested_sources"] == ["paper", "repo"]
    assert result["analysis"]["paper"] == {
        "papers": 1,
        "analysis_schema_version": "growthos.research-analysis.v5",
        "baseline_complete": 0,
        "stored_total": 0,
        "strict_total": 0,
        "strict_titled": 0,
        "strict_complete": 0,
        "strict_pending": 0,
        "missing_title": 0,
        "completed_this_request": 0,
        "remaining": False,
    }
    assert result["analysis"]["repo"]["completed_this_request"] == 0
    assert called == [
        {"backup": True},
        {"only": "arxiv"},
        {"reanalyze": "papers", "analysis_limit": 4},
        {"only": "github"},
        {"reanalyze": "repos", "analysis_limit": 3},
    ]
    assert json.loads(refresh.read_text(encoding="utf-8"))["state"] == "complete"


def test_research_refresh_blocks_when_a_source_pull_fails(
    monkeypatch, tmp_path,
):
    from types import SimpleNamespace

    refresh = tmp_path / "research-refresh.json"
    refresh.write_text(json.dumps({
        "schema_version": "growthos.research-refresh.v1",
        "request_id": "refresh-failed",
        "state": "queued",
        "requested_sources": ["paper"],
        "ingested_sources": [],
    }), encoding="utf-8")
    monkeypatch.setattr(
        "growthos.config.load_settings",
        lambda: SimpleNamespace(
            growthos_domain_surfaces="domains.yaml",
            growthos_board_store=str(tmp_path / "boards"),
            growthos_kanban_event_log=str(tmp_path / "events.jsonl"),
            growthos_dry_run=False,
        ),
    )
    monkeypatch.setattr(
        "growthos.config.load_config",
        lambda **_kwargs: SimpleNamespace(sources=SimpleNamespace(
            arxiv=SimpleNamespace(analysis_batch_size=4),
            github=SimpleNamespace(analysis_batch_size=3),
        )),
    )
    _stub_curate(
        monkeypatch,
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("every arXiv research query failed")),
    )

    result = process_research_refresh(
        refresh_path=refresh,
        backup=lambda: {"snapshot_id": "S-failed"},
    )

    assert result["state"] == "blocked"
    assert result["error_type"] == "RuntimeError"
    assert "arXiv" in result["error"]
    assert json.loads(refresh.read_text(encoding="utf-8"))["state"] == "blocked"
