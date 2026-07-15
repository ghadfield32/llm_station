"""retention — keeps the auto-curated inboxes to a rolling window.

Policy (config/sources.yaml `retention:` block — no hardcoded thresholds):
rows in papers/repos/signals that are STILL `Inbox` after `days` days get
Status=Archived. Rows a human touched (Reading/Saved/Trying/...) are never
modified — triage decisions are permanent. Archived is the retirement state;
boards filter it out of sight while preserving audit history.

Stages:
  stage 1  load policy    sources.yaml retention: {days, databases: {db: date_field}}
  stage 2  scan           row details; candidates = Status==Inbox AND
                          date_field < today - days (undated rows skipped)
  stage 3  archive        upsert Status=Archived by the row's natural key
                          (papers: ArxivID, repos/signals: URL)

Run:  python -m growthos.retention      (daily in the curator container loop)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import yaml

from .actions import KEY_FIELD, client

log = logging.getLogger("growthos.retention")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    here = Path(__file__).resolve().parent.parent
    cfg = yaml.safe_load((here / "config/sources.yaml").read_text(encoding="utf-8"))
    pol = cfg.get("retention")
    if not pol:
        raise SystemExit("retention: no `retention:` block in config/sources.yaml")
    cutoff = date.today() - timedelta(days=int(pol["days"]))

    af = client()
    for db, date_field in pol["databases"].items():
        rows = af.row_details(db, af.list_row_ids(db))
        stale = []
        for d in rows:
            c = d["cells"]
            if not c.get("Name") or c.get("Status") != "Inbox":
                continue
            when = c.get(date_field)
            iso = when.get("pretty_start_date", "") if isinstance(when, dict) else ""
            if not iso or date.fromisoformat(iso) >= cutoff:
                continue
            key = c.get(KEY_FIELD[db], "")
            if key:
                stale.append({"pre_hash": key, "cells": {"Status": "Archived"}})
        wrote = af.upsert(db, stale) if stale else []
        log.info("%s: %d inbox rows older than %s archived",
                 db, len(wrote), cutoff.isoformat())


if __name__ == "__main__":
    main()
