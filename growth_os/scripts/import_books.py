"""Import the Lineage reading curriculum (data/book-checklist.md) into the
`library` database. Idempotent: pre_hash = the same book slug add_book uses,
so re-imports update rows and never duplicate.

Stages:
  stage 1  parse()    markdown -> [BookRow]: bullet lines `- [ ]` / `- [x]`
                      under `## NN · Module` headers. Tier from the bracket
                      tag, hours from `~Nh`, medium (audio/page) -> Notes,
                      Section = the module's leading number (the sort key).
  stage 2  upsert()   library rows keyed book-{title slug}. EXISTING rows
                      only refresh curriculum facts (Author/Tier/Module/
                      Hours/Section); Status and Notes belong to the human
                      after first import and are NEVER overwritten.

Run:  PYTHONPATH=. .venv/Scripts/python.exe scripts/import_books.py [path.md]
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from growthos.actions import client, _slug

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "book-checklist.md"

TIERS = {"E": "Essential", "Opt": "Optional", "Fic": "Companion",
         "Fun": "Fun", "Ref": "Reference"}

MODULE_RE = re.compile(r"^##\s+(.+)$")
BULLET_RE = re.compile(
    r"^-\s+\[(?P<done>[ xX])\]\s+(?P<body>.+)$")
TAG_RE = re.compile(r"`\[(E|Opt|Fic|Fun|Ref)\]`")
HOURS_RE = re.compile(r"~\s*(\d+(?:\.\d+)?)\s*h")
MEDIUM_RE = re.compile(r"`(audio|page)`")


@dataclass
class BookRow:
    title: str
    author: str
    tier: str
    status: str
    module: str
    section: int
    hours: float
    notes: str


def parse(text: str) -> list[BookRow]:
    rows: list[BookRow] = []
    module = ""
    for raw in text.splitlines():
        line = raw.strip()
        m = MODULE_RE.match(line)
        if m:
            module = m.group(1).split(" — ")[0].strip()
            continue
        b = BULLET_RE.match(line)
        if not b:
            continue
        body = b.group("body")
        tag = TAG_RE.search(body)
        if not tag:                      # legend lines, research sprints, etc.
            continue
        head = body.split("·")[0].strip()
        title, author = (head.split(" — ", 1) + [""])[:2]
        title = title.replace("**", "").replace("★", "").strip()
        author = author.replace("**", "").strip()
        hours = HOURS_RE.search(body)
        medium = MEDIUM_RE.search(body)
        notes = []
        if medium:
            notes.append(medium.group(1))
        if "(book 1)" in body:
            notes.append("series: continue only if hooked")
        sec = re.match(r"(\d+)", module)
        rows.append(BookRow(
            title=title, author=author, tier=TIERS[tag.group(1)],
            status="Done" if b.group("done").lower() == "x" else "To read",
            module=module, section=int(sec.group(1)) if sec else -1,
            hours=float(hours.group(1)) if hours else 0.0,
            notes="; ".join(notes)))
    return rows


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    books = parse(path.read_text(encoding="utf-8"))
    af = client()
    existing = {c.get("Name", "") for d in
                af.row_details("library", af.list_row_ids("library"))
                if (c := d["cells"]).get("Name")}
    payload = []
    for bk in books:
        cells = {"Title": bk.title, "Author": bk.author, "Tier": bk.tier,
                 "Module": bk.module}
        if bk.section >= 0:
            cells["Section"] = bk.section
        if bk.hours:
            cells["Hours"] = bk.hours
        if bk.title not in existing:     # human owns Status+Notes after import
            cells["Status"] = bk.status
            cells["Notes"] = bk.notes
        payload.append({"pre_hash": _slug("book", bk.title), "cells": cells})
    wrote = af.upsert("library", payload)
    tiers = {}
    for bk in books:
        tiers[bk.tier] = tiers.get(bk.tier, 0) + 1
    print(f"parsed {len(books)} books from {path.name}: {tiers}")
    print(f"upserted {len(wrote)} rows into library")


if __name__ == "__main__":
    main()
