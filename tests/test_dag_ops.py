"""
The Airflow operator surface (cli.dag_ops): doctor + report wrap the `airflow`
CLI inside the container. These tests inject a fake command runner returning
canned `airflow ... --output json`, so the logic — health classification, window
filtering, graceful degradation when airflow is down — is verified without a
live scheduler.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from command_center.cli import dag_ops


def _fake_runner(*, version_rc=0, dags=None, import_errors=None, details=None, runs=None):
    """Build a runner that answers each `airflow ...` subcommand with canned JSON."""
    def run(args):
        if "version" in args:
            return (version_rc, "2.10.5\n", "" if version_rc == 0 else "not running")
        if "list-import-errors" in args:
            return (0, json.dumps(import_errors or []), "")
        if "list-runs" in args:
            return (0, json.dumps(runs or []), "")
        if "details" in args:
            return (0, json.dumps(details or {}), "")
        if "list" in args:
            return (0, json.dumps(dags or []), "")
        return (0, "", "")
    return run


HEALTHY = dict(
    dags=[{"dag_id": "self_improvement_daily"}, {"dag_id": "other"}],
    import_errors=[],
    details={"is_paused": False, "next_dagrun": "2026-06-24T06:00:00+00:00"},
    runs=[{"run_id": "scheduled__2026-06-23", "state": "success",
           "start_date": "2026-06-23T06:00:00+00:00"}],
)


# ── doctor ────────────────────────────────────────────────────────────

def test_doctor_pass_when_airflow_healthy():
    result = dag_ops.run_doctor(runner=_fake_runner(**HEALTHY))
    assert result["status"] == "pass"
    assert result["reachable"] is True
    statuses = {c["check"]: c["status"] for c in result["checks"]}
    assert statuses["dag_registered"] == "PASS"
    assert statuses["no_import_errors"] == "PASS"
    assert statuses["dag_unpaused"] == "PASS"
    assert statuses["last_run"] == "PASS"


def test_doctor_degrades_when_airflow_unreachable():
    result = dag_ops.run_doctor(runner=_fake_runner(version_rc=1))
    assert result["status"] == "degraded"
    assert result["reachable"] is False
    statuses = {c["check"]: c["status"] for c in result["checks"]}
    assert statuses["airflow_reachable"] == "DEGRADED"
    # no airflow-dependent checks were attempted
    assert "dag_registered" not in statuses


def test_doctor_blocked_on_import_errors():
    bad = dict(HEALTHY)
    bad["import_errors"] = [{"filepath": "/opt/airflow/dags/self_improvement_daily.py",
                             "error": "boom"}]
    result = dag_ops.run_doctor(runner=_fake_runner(**bad))
    assert result["status"] == "blocked"
    assert "no_import_errors" in result["blockers"]


def test_doctor_warns_when_paused_but_not_blocked():
    paused = dict(HEALTHY)
    paused["details"] = {"is_paused": True, "next_dagrun": None}
    result = dag_ops.run_doctor(runner=_fake_runner(**paused))
    assert result["status"] == "pass"  # paused is WARN, not BLOCKED
    statuses = {c["check"]: c["status"] for c in result["checks"]}
    assert statuses["dag_unpaused"] == "WARN"


def test_doctor_blocked_when_dag_file_missing(tmp_path):
    result = dag_ops.run_doctor(runner=_fake_runner(**HEALTHY),
                                dag_file=tmp_path / "nope.py")
    assert result["status"] == "blocked"
    assert "dag_file_present" in result["blockers"]


def test_doctor_blocked_when_dag_not_registered():
    missing = dict(HEALTHY)
    missing["dags"] = [{"dag_id": "other"}]
    result = dag_ops.run_doctor(runner=_fake_runner(**missing))
    assert result["status"] == "blocked"
    assert "dag_registered" in result["blockers"]


# ── report ────────────────────────────────────────────────────────────

def test_report_degrades_when_unreachable():
    result = dag_ops.run_report(runner=_fake_runner(version_rc=1))
    assert result["status"] == "degraded"
    assert result["runs"] == []


def test_report_counts_runs_in_window():
    now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    runs = [
        {"run_id": "a", "state": "success", "start_date": "2026-06-23T06:00:00+00:00"},
        {"run_id": "b", "state": "failed", "start_date": "2026-06-22T06:00:00+00:00"},
        {"run_id": "old", "state": "success", "start_date": "2026-06-01T06:00:00+00:00"},
    ]
    result = dag_ops.run_report(runner=_fake_runner(runs=runs), last="7d", now=now)
    assert result["status"] == "ok"
    assert result["total"] == 2  # 'old' is outside the 7d window
    assert result["by_state"] == {"success": 1, "failed": 1}


def test_parse_window():
    assert dag_ops._parse_window("7d").days == 7
    assert dag_ops._parse_window("24h").total_seconds() == 24 * 3600


# ── up / down ─────────────────────────────────────────────────────────

def test_up_reports_blocked_on_compose_failure():
    def runner(args):
        return (1, "", "Cannot connect to the Docker daemon")
    result = dag_ops.run_up(runner=runner)
    assert result["status"] == "blocked"
    assert result["blockers"]


def test_up_ok_when_compose_succeeds():
    result = dag_ops.run_up(runner=lambda args: (0, "started", ""))
    assert result["status"] == "ok"
