#!/usr/bin/env python3
"""
dag_ops.py — operator surface over the Airflow deployment (profile: airflow).

Wraps the real `airflow` CLI inside the running container so DAG health and
recent runs are one command away:

  cc dag up         # start the airflow profile (docker compose --profile airflow up -d)
  cc dag doctor     # airflow reachable? DAG registered, import-error free, unpaused, last/next run
  cc dag report     # recent self_improvement_daily runs (counts by state) in a window
  cc dag down       # stop the airflow service

doctor/report shell into the container via `docker compose exec -T airflow
airflow ...`. When airflow is not running they DEGRADE (clear status + how to
start it) instead of crashing. The command runner is injectable so the logic is
tested against canned `airflow ... --output json` without a live scheduler.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
DAG_ID = "self_improvement_daily"
DAG_FILE = ROOT / "dags" / f"{DAG_ID}.py"

# A runner takes an argv list and returns (returncode, stdout, stderr).
Runner = Callable[[list[str]], tuple[int, str, str]]


def _default_runner(args: list[str]) -> tuple[int, str, str]:
    import subprocess
    try:
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired as e:
        return 124, "", str(e)


def _airflow(runner: Runner, *cargs: str) -> tuple[int, str, str]:
    """Run `airflow <cargs>` inside the running airflow container."""
    return runner(["docker", "compose", "exec", "-T", "airflow", "airflow", *cargs])


def _json_or_none(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


# ── up / down ─────────────────────────────────────────────────────────

def run_up(*, runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or _default_runner
    rc, out, err = runner(["docker", "compose", "--profile", "airflow", "up", "-d", "airflow"])
    ok = rc == 0
    return {"status": "ok" if ok else "blocked",
            "blockers": [] if ok else [f"compose up failed: {(err or out).strip()[:200]}"],
            "next": "cc dag doctor" if ok else "check docker is running"}


def run_down(*, runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or _default_runner
    rc, out, err = runner(["docker", "compose", "--profile", "airflow", "stop", "airflow"])
    ok = rc == 0
    return {"status": "ok" if ok else "blocked",
            "blockers": [] if ok else [f"compose stop failed: {(err or out).strip()[:200]}"]}


# ── doctor ────────────────────────────────────────────────────────────

def run_doctor(*, runner: Runner | None = None, dag_id: str = DAG_ID,
               dag_file: Path = DAG_FILE) -> dict[str, Any]:
    """Health of the Airflow deployment + the self-improvement DAG.

    Statuses: PASS, WARN, BLOCKED, DEGRADED (airflow unreachable). Overall
    status is `blocked` on any BLOCKED, else `degraded` if airflow is down, else
    `pass`.
    """
    runner = runner or _default_runner
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    # 1. DAG file present (filesystem — works with or without airflow).
    if dag_file.exists():
        add("dag_file_present", "PASS", str(dag_file.relative_to(ROOT)))
    else:
        add("dag_file_present", "BLOCKED", f"missing {dag_file}")

    # 2. Airflow reachable (container running + CLI answers).
    rc, out, err = _airflow(runner, "version")
    reachable = rc == 0
    if reachable:
        add("airflow_reachable", "PASS", f"airflow {out.strip()}")
    else:
        add("airflow_reachable", "DEGRADED",
            "airflow container not reachable — start it with `cc dag up`")

    if reachable:
        # 3. DAG registered.
        rc, out, _ = _airflow(runner, "dags", "list", "--output", "json")
        listed = _json_or_none(out) or []
        ids = {d.get("dag_id") for d in listed} if isinstance(listed, list) else set()
        if dag_id in ids:
            add("dag_registered", "PASS", f"{dag_id} present ({len(ids)} dags)")
        else:
            add("dag_registered", "BLOCKED", f"{dag_id} not in airflow dags list")

        # 4. No import errors.
        rc, out, _ = _airflow(runner, "dags", "list-import-errors", "--output", "json")
        errors = _json_or_none(out) or []
        if errors:
            add("no_import_errors", "BLOCKED",
                "; ".join(e.get("filepath", "?") for e in errors)[:200])
        else:
            add("no_import_errors", "PASS", "no import errors")

        # 5. Unpaused + next run.
        rc, out, _ = _airflow(runner, "dags", "details", dag_id, "--output", "json")
        details = _json_or_none(out)
        if isinstance(details, dict):
            paused = details.get("is_paused")
            add("dag_unpaused", "WARN" if paused else "PASS",
                "DAG is PAUSED — `airflow dags unpause` to schedule it" if paused
                else f"unpaused; next run {details.get('next_dagrun') or '?'}")
        else:
            add("dag_unpaused", "WARN", "could not read dag details")

        # 6. Last run state.
        rc, out, _ = _airflow(runner, "dags", "list-runs", "--dag-id", dag_id,
                              "--output", "json")
        runs = _json_or_none(out) or []
        if isinstance(runs, list) and runs:
            last = runs[0]
            st = last.get("state", "?")
            add("last_run", "PASS" if st in ("success", "running", "queued") else "WARN",
                f"{last.get('run_id', '?')}: {st}")
        else:
            add("last_run", "WARN", "no runs yet")

    blocked = [c["check"] for c in checks if c["status"] == "BLOCKED"]
    if blocked:
        status = "blocked"
    elif not reachable:
        status = "degraded"
    else:
        status = "pass"
    return {"status": status, "dag_id": dag_id, "reachable": reachable,
            "checks": checks, "blockers": blocked}


# ── report ────────────────────────────────────────────────────────────

def _parse_window(window: str) -> timedelta:
    window = window.strip().lower()
    n = int(window[:-1] or 0) if window[-1:] in "dh" else int(window)
    return timedelta(hours=n) if window.endswith("h") else timedelta(days=n)


def _run_dt(run: dict[str, Any]) -> datetime | None:
    for key in ("start_date", "logical_date", "execution_date"):
        v = run.get(key)
        if v:
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def run_report(*, runner: Runner | None = None, dag_id: str = DAG_ID,
               last: str = "7d", now: datetime | None = None) -> dict[str, Any]:
    """Recent DAG runs in a window: counts by state + the most recent runs."""
    runner = runner or _default_runner
    rc, out, err = _airflow(runner, "version")
    if rc != 0:
        return {"status": "degraded", "dag_id": dag_id,
                "blockers": ["airflow container not reachable — start it with `cc dag up`"],
                "runs": [], "by_state": {}}
    cutoff = (now or datetime.now(timezone.utc)) - _parse_window(last)
    rc, out, _ = _airflow(runner, "dags", "list-runs", "--dag-id", dag_id, "--output", "json")
    runs = _json_or_none(out) or []
    in_window = []
    for r in runs if isinstance(runs, list) else []:
        dt = _run_dt(r)
        if dt is None or dt >= cutoff:
            in_window.append(r)
    by_state: dict[str, int] = {}
    for r in in_window:
        by_state[r.get("state", "?")] = by_state.get(r.get("state", "?"), 0) + 1
    return {"status": "ok", "dag_id": dag_id, "window": last,
            "total": len(in_window), "by_state": by_state,
            "runs": [{"run_id": r.get("run_id"), "state": r.get("state"),
                      "start_date": r.get("start_date")} for r in in_window[:10]],
            "blockers": []}


# ── CLI ──────────────────────────────────────────────────────────────

def _print_doctor(result: dict[str, Any]) -> None:
    print(f"dag doctor [{result['dag_id']}]: {result['status'].upper()}")
    for c in result["checks"]:
        print(f"  {c['status']:<9} {c['check']:<20} {c['detail']}")


def _print_report(result: dict[str, Any]) -> None:
    print(f"dag report [{result['dag_id']}] last {result.get('window', '?')}: "
          f"{result['status'].upper()}")
    for b in result.get("blockers", []):
        print(f"  BLOCKED: {b}")
    if result.get("by_state"):
        print(f"  runs in window: {result['total']}  " +
              "  ".join(f"{k}={v}" for k, v in result["by_state"].items()))
    for r in result.get("runs", []):
        print(f"    {r['run_id']}  {r['state']}  {r.get('start_date') or ''}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="dag", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="start the airflow profile")
    sub.add_parser("down", help="stop the airflow service")
    sub.add_parser("doctor", help="airflow + DAG health")
    rep = sub.add_parser("report", help="recent DAG runs")
    rep.add_argument("--last", default="7d", help="window, e.g. 7d or 24h")
    rep.add_argument("--dag-id", default=DAG_ID)
    args = parser.parse_args()

    if args.cmd == "up":
        result = run_up()
    elif args.cmd == "down":
        result = run_down()
    elif args.cmd == "doctor":
        result = run_doctor()
        _print_doctor(result)
        return 0 if result["status"] in ("pass", "degraded") else 1
    else:  # report
        result = run_report(last=args.last, dag_id=args.dag_id)
        _print_report(result)
        return 0 if result["status"] in ("ok", "degraded") else 1

    print(f"dag {args.cmd}: {result['status'].upper()}")
    for b in result.get("blockers", []):
        print(f"  BLOCKED: {b}")
    if result.get("next"):
        print(f"  next: {result['next']}")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
