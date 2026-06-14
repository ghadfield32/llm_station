"""Seed the LinkedIn content boards with Claude-Code-authored drafts.

Reads config/content_seed/<account>.json (posts grounded in real repos/curriculum;
each carries its `Source` derivation) and upserts them as **In Queue** rows, one
post per day starting tomorrow.

Clobber-safe by design: a key already present on the board is SKIPPED, never
overwritten. So once you start reviewing - editing a draft, dragging it to In
Progress, setting a ScheduledFor - re-running this seed will not stomp your work.
Only genuinely new keys are inserted. (Same no-clobber rule as import_books.py.)

Run:  PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_content.py
      (--dry-run to preview without writing)
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from growthos.actions import client

GROWTHOS_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = GROWTHOS_ROOT / "config/content_seed"
# board name in databases.json -> seed file
BOARDS = {
    "geoffhadfield32_content": "geoffhadfield32.json",
    "world_model_sports_content": "world_model_sports.json",
}
STATUS_QUEUE = "In Queue"


def existing_keys(c, board: str) -> set[str]:
    """Keys already on the board (so we never overwrite a reviewed/approved row)."""
    ids = c.list_row_ids(board)
    if not ids:
        return set()
    keys = set()
    for row in c.row_details(board, ids):
        cells = row.get("cells", row)
        k = cells.get("Key")
        if k:
            keys.add(str(k))
    return keys


def build_rows(posts: list[dict], skip: set[str], start: date) -> list[dict]:
    rows = []
    for i, p in enumerate(posts):
        key = p["key"]
        if key in skip:
            continue
        scheduled = (start + timedelta(days=1 + i)).isoformat()  # 1/day from tomorrow
        rows.append({"pre_hash": key, "cells": {
            "Hook": p["hook"],
            "Body": p["body"],
            "Status": STATUS_QUEUE,
            "ScheduledFor": scheduled,
            "Pillar": p["pillar"],
            "Format": p["format"],
            "Source": p["source"],
            "Key": key,
            "Created": start.isoformat(),
        }})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be inserted, write nothing")
    args = ap.parse_args()
    today = date.today()
    c = client()
    for board, fname in BOARDS.items():
        posts = json.loads((SEED_DIR / fname).read_text(encoding="utf-8"))
        skip = existing_keys(c, board)
        rows = build_rows(posts, skip, today)
        print(f"{board}: {len(posts)} drafted, {len(skip)} already present, "
              f"{len(rows)} new to insert")
        if args.dry_run or not rows:
            for r in rows:
                print(f"  [{r['cells']['ScheduledFor']}] {r['cells']['Hook'][:70]}")
            continue
        written = c.upsert(board, rows)
        print(f"  inserted {len(written)} rows as '{STATUS_QUEUE}'")


if __name__ == "__main__":
    main()
