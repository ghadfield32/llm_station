"""airflow_sync — live DAG health on the `dags` board with root-cause-first
error summaries. Deterministic end to end: log parsing, no LLM in the loop.

For every registered project with an `airflow:` block (config/projects.yaml),
the latest run state of every DAG lands on the board, and a FAILED run gets a
summary built to shorten root-causing: the exception line, the deepest
*project-code* traceback frame (file:line — library frames are skipped on
purpose), the failed task + try number, and the direct Airflow-UI log URL.

Module tree / stages (linear; each function independently callable):
  stage 1  load_registry()      projects.yaml -> [(project, AirflowCfg, auth)]
                                env-named secrets resolved; missing -> loud exit
  stage 2  fetch_dags()         GET /api/v1/dags (paginated) -> id, paused,
                                schedule per DAG
  stage 3  latest_run()         GET /dags/{id}/dagRuns?limit=1 desc -> state,
                                run_id, end date
  stage 4  failed_summary()     failed taskInstances -> log text ->
                                extract_error(): exception line + deepest
                                /workspace frame + task/try + UI log URL
  stage 5  sync_board()         upsert dags rows: Status Active|Paused|Broken
                                (human-set Retired is never overwritten),
                                Notes = summary, LastSeen = today
  stage 6  draft_cards()        newly-Broken DAGs -> Backlog mission card
                                (drafting only; dispatch = your Approved drag)

Run:  python -m growthos.airflow_sync          (hourly in the curator loop)
Tool: actions.dag_health() reuses stages 2-4 for live one-off checks.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date

import httpx
from dotenv import load_dotenv

from .actions import add_mission_card, client
from .config import AirflowCfg, ProjectCfg, load_projects

log = logging.getLogger("growthos.airflow_sync")

TRACEBACK_START = "Traceback (most recent call last):"
FRAME_RE = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<fn>\S+)')
EXC_RE = re.compile(r"^(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Failed|Timeout|Interrupt))\b.*")


# stage 1 ------------------------------------------------------------------

def load_registry() -> list[tuple[ProjectCfg, AirflowCfg, tuple[str, str, str]]]:
    load_dotenv(".env")
    out = []
    for proj in load_projects().projects:
        if not proj.airflow:
            continue
        af = proj.airflow
        base = os.environ.get(af.base_url_env, "")
        user = os.environ.get(af.username_env, "")
        pwd = os.environ.get(af.password_env, "")
        missing = [k for k, v in ((af.base_url_env, base), (af.username_env, user),
                                  (af.password_env, pwd)) if not v]
        if missing:
            raise SystemExit(
                f"airflow_sync: {proj.name} needs {', '.join(missing)} in .env")
        out.append((proj, af, (base.rstrip("/"), user, pwd)))
    return out


def _api(auth: tuple[str, str, str]) -> httpx.Client:
    base, user, pwd = auth
    return httpx.Client(base_url=f"{base}/api/v1", auth=(user, pwd), timeout=30)


# stage 2 ------------------------------------------------------------------

def fetch_dags(api: httpx.Client) -> list[dict]:
    dags, offset = [], 0
    while True:
        r = api.get("/dags", params={"limit": 100, "offset": offset,
                                     "only_active": True})
        r.raise_for_status()
        page = r.json()
        dags += page["dags"]
        offset += 100
        if offset >= page["total_entries"]:
            return dags


# stage 3 ------------------------------------------------------------------

def latest_run(api: httpx.Client, dag_id: str) -> dict | None:
    r = api.get(f"/dags/{dag_id}/dagRuns",
                params={"limit": 1, "order_by": "-execution_date"})
    r.raise_for_status()
    runs = r.json()["dag_runs"]
    return runs[0] if runs else None


# stage 4 ------------------------------------------------------------------

def extract_error(log_text: str) -> str:
    """Exception line + deepest project-code frame from the LAST traceback.
    Library frames (site-packages/dist-packages) are skipped so the pointer
    lands in code you can actually edit; falls back to the deepest frame,
    then to the last ERROR-level line."""
    tb_at = log_text.rfind(TRACEBACK_START)
    if tb_at >= 0:
        block = log_text[tb_at:tb_at + 6000]
        frames = list(FRAME_RE.finditer(block))
        own = [f for f in frames if "site-packages" not in f["file"]
               and "dist-packages" not in f["file"]]
        frame = (own or frames)[-1] if frames else None
        exc = ""
        for line in block.splitlines():
            m = EXC_RE.match(line.strip())
            if m:
                exc = line.strip()[:240]
        parts = [exc or "unrecognized exception (see log)"]
        if frame:
            parts.append(f"{frame['file']}:{frame['line']} in {frame['fn']}")
        return " | ".join(parts)
    err_lines = [ln for ln in log_text.splitlines() if " ERROR " in ln or
                 ln.startswith("ERROR")]
    if err_lines:
        return err_lines[-1][:300]
    return "failed without traceback or ERROR lines (see log)"


def failed_summary(api: httpx.Client, ui_url: str, dag_id: str,
                   run: dict) -> str:
    run_id = run["dag_run_id"]
    r = api.get(f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances",
                params={"state": ["failed"]})
    r.raise_for_status()
    tasks = r.json()["task_instances"]
    if not tasks:
        return f"run {run_id} failed with no failed task instances (see UI)"
    ti = tasks[0]
    task_id, try_n = ti["task_id"], max(ti["try_number"], 1)
    lr = api.get(f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances/"
                 f"{task_id}/logs/{try_n}", params={"full_content": True})
    error = extract_error(lr.text if lr.status_code == 200 else "")
    log_url = (f"{ui_url}/dags/{dag_id}/grid?dag_run_id={run_id}"
               f"&task_id={task_id}&tab=logs")
    more = f" (+{len(tasks) - 1} more failed tasks)" if len(tasks) > 1 else ""
    return (f"FAILED {run['end_date'] or run['execution_date']}: {error} | "
            f"task={task_id} try={try_n}{more} | logs: {log_url}")


# stages 5+6 -----------------------------------------------------------------

def sync_project(proj: ProjectCfg, afcfg: AirflowCfg,
                 auth: tuple[str, str, str]) -> dict[str, int]:
    af = client()
    board = {}
    for d in af.row_details("dags", af.list_row_ids("dags")):
        c = d["cells"]
        if c.get("DagID"):
            board[c["DagID"]] = c.get("Status", "")
    stats = {"active": 0, "paused": 0, "broken": 0, "cards": 0}
    today = date.today().isoformat()
    rows = []
    with _api(auth) as api:
        for dag in fetch_dags(api):
            dag_id = dag["dag_id"]
            if board.get(dag_id) == "Retired":   # human decision is permanent
                continue
            run = latest_run(api, dag_id)
            state = (run or {}).get("state", "")
            if state == "failed":
                status = "Broken"
                notes = failed_summary(api, afcfg.ui_url, dag_id, run)
                stats["broken"] += 1
            elif dag["is_paused"]:
                status, notes = "Paused", ""
                stats["paused"] += 1
            else:
                status = "Active"
                when = (run or {}).get("end_date") or ""
                notes = f"last run {state or 'none yet'} {when[:16]}"
                stats["active"] += 1
            sched = dag.get("schedule_interval")
            cells = {"Name": dag_id, "DagID": dag_id, "Status": status,
                     "Schedule": sched if isinstance(sched, str)
                     else (sched or {}).get("value", "manual"),
                     "Description": (dag.get("description") or "")[:500],
                     "Owners": ", ".join(dag.get("owners") or []),
                     "Tags": ", ".join(t["name"] for t in dag.get("tags") or []),
                     "Notes": notes, "LastSeen": today}
            if dag.get("next_dagrun"):
                cells["NextRun"] = dag["next_dagrun"][:10]
            rows.append({"pre_hash": dag_id, "cells": cells})
            if (status == "Broken" and board.get(dag_id) != "Broken"
                    and afcfg.draft_cards_on_failure):
                add_mission_card(
                    f"Fix failing DAG {dag_id}", section=afcfg.card_section,
                    risk="L2", repo=proj.name, target=dag_id,
                    action=f"Latest run failed. {notes}",
                    acceptance="The DAG's next scheduled run completes; the "
                               "root cause is fixed, not retried around.")
                stats["cards"] += 1
    wrote = af.upsert("dags", rows)
    log.info("%s: %d dags synced (%s), %d cards drafted",
             proj.name, len(wrote), stats, stats["cards"])
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for proj, afcfg, auth in load_registry():
        sync_project(proj, afcfg, auth)


if __name__ == "__main__":
    main()
