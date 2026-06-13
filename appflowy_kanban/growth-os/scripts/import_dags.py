"""Import Airflow DAGs from the betts_basketball project into the `dags`
database. Parses dag_id + schedule out of the DAG files (no Airflow API
needed) and upserts by dag_id, so re-runs refresh instead of duplicate.

Status mapping: schedule None -> Manual, otherwise Active. (Adjust real
operational status — Paused/Broken/Retired — on the board afterwards.)

Run:  PYTHONPATH=. .venv/Scripts/python.exe scripts/import_dags.py [dags_dir]
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

from growthos.actions import client

def default_dags_dir() -> Path:
    """First registry project with a dags_dir (config/projects.yaml)."""
    from growthos.config import load_projects
    for proj in load_projects().projects:
        if proj.dags_dir:
            return Path(proj.repo) / proj.dags_dir
    raise SystemExit("no project with dags_dir in config/projects.yaml")

DAG_ID_RE = re.compile(r"dag_id\s*=\s*[\"']([\w.\-]+)[\"']")
SCHED_RE = re.compile(r"schedule(?:_interval)?\s*=\s*(None|[\"'][^\"']*[\"'])")


def parse_file(path: Path) -> dict[str, str]:
    """Return {dag_id: schedule} for every DAG defined in the file."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    out: dict[str, str] = {}
    for m in DAG_ID_RE.finditer(text):
        dag_id = m.group(1)
        sched = out.get(dag_id, "")
        window = text[m.end():m.end() + 400]
        sm = SCHED_RE.search(window)
        if sm and not sched:
            raw = sm.group(1)
            sched = "" if raw == "None" else raw.strip("\"'")
        out.setdefault(dag_id, sched)
        if sched:
            out[dag_id] = sched
    return out


def main() -> None:
    dags_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dags_dir()
    rows = []
    today = date.today().isoformat()
    for f in sorted(dags_dir.rglob("*.py")):
        if f.name.startswith("_") or f.name == "exampledag.py":
            continue
        for dag_id, sched in parse_file(f).items():
            if dag_id in ("my_pipeline",):        # doc examples inside helpers
                continue
            rows.append({"pre_hash": dag_id, "cells": {
                "Name": dag_id,
                "DagID": dag_id,
                "Schedule": sched or "manual",
                "Status": "Manual" if not sched else "Active",
                "Path": str(f.relative_to(dags_dir)),
                "LastSeen": today,
            }})
    # dedupe by dag_id, last wins
    uniq = {r["pre_hash"]: r for r in rows}
    wrote = client().upsert("dags", list(uniq.values()))
    print(f"parsed {len(uniq)} dags, upserted {len(wrote)}")
    for r in sorted(uniq):
        print("  ", r)


if __name__ == "__main__":
    main()
