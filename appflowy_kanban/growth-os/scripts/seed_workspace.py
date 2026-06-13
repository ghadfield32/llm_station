"""Seed the `sources` database (mirror of config/sources.yaml, so the feed
list is visible from your phone) and the `todos` board (the real open items
from the setup sessions). Idempotent: everything upserts by stable keys.

Run:  PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_workspace.py
"""
from __future__ import annotations

from pathlib import Path

import yaml

from growthos.actions import client, add_todo

BACKUP_CMD = ("schtasks /create /tn \"GrowthOS backup\" /sc daily /st 02:00 /tr "
              "\"pwsh -NoProfile -File <repo>\\scripts\\backup.ps1\"")

TODOS = [
    ("Add GitHub PAT to growth-os/.env", "Growth OS", "P1",
     "Read-only classic PAT into GITHUB_TOKEN=, then `docker restart "
     "growthos-curator`. One repo search query rate-limits hourly without it."),
    ("Provide curriculum CSV for library import", "Learning", "P1",
     "Drop curriculum-appflowy.csv anywhere in appflowy_kanban/ and ask "
     "Claude to import it - the importer maps Tier/Status/Module."),
    ("Review imported DAG board statuses", "Betts Basketball", "P1",
     "dags DB was auto-imported from the betts_basketball repo with "
     "Active/Manual guesses - mark anything Paused/Broken/Retired."),
    ("Schedule nightly backup task", "Growth OS", "P2", BACKUP_CMD),
    ("Decide long-term host (revive betts-airflow-prod-01?)", "DAGs", "P2",
     "Offline since ~March. Runbook ready: growth-os/deploy/linux/MIGRATION.md."),
    ("Tidy AppFlowy grids: delete blank rows + Type/Done columns", "Growth OS",
     "P3", "Each grid ships with 3 blank rows and default Type/Done columns; "
     "no REST delete exists, so it is a quick UI sweep."),
    ("Gmail App Password for SMTP (password resets / magic links)", "Growth OS",
     "P3", "Google Account -> Security -> 2-Step Verification -> App passwords; "
     "then GOTRUE_SMTP_* in AppFlowy-Cloud/.env gets wired up."),
]


def seed_sources() -> int:
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))
    rows = []
    src = cfg["sources"]
    for q in src["arxiv"].get("queries", []):
        rows.append(("arxiv", q))
    rows.append(("arxiv", "categories: " + ", ".join(src["arxiv"].get("categories", []))))
    for q in src["github"].get("queries", []):
        rows.append(("github", q))
    for t in src["github"].get("topics", []):
        rows.append(("github", f"topic:{t}"))
    for f in src["signals"].get("feeds", []):
        rows.append(("rss", f))
    payload = [{"pre_hash": f"src-{kind}-{q[:70]}",
                "cells": {"Name": q if len(q) < 60 else q[:57] + "...",
                          "Kind": kind, "Query": q, "Enabled": True}}
               for kind, q in rows]
    return len(client().upsert("sources", payload))


def main() -> None:
    print(f"sources rows upserted: {seed_sources()}")
    for task, area, prio, notes in TODOS:
        print(add_todo(task, area=area, priority=prio, notes=notes))


if __name__ == "__main__":
    main()
