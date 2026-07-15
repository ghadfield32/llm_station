"""First-party board-store client used by Growth OS actions.

The interface preserves the old idempotent row API while storing cards in the
Command Center's governed event log and per-board JSON stores. It has no network
authentication and no external board dependency.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.kanban_sync.events import EventLog, emit_event, is_human_owned_status

from .models import CuratedItem

BOARD_IDS = {
    "mission_intake": "llm_station_command_center",
    "todos": "personal_tasks",
    "papers": "research_papers",
    "repos": "research_repos",
    "signals": "research_signals",
    "library": "reading_library",
    "lessons": "learning_lessons",
    "notes": "knowledge_notes",
    "dags": "dag_operations",
}

FIELD_MAP = {
    "papers": lambda i: {
        "Title": i.title, "Authors": i.authors, "ArxivID": i.external_id,
        "Abstract": i.summary, "Suggested": i.extra.get("suggested", ""),
        "URL": i.url, "Topics": i.topics, "Score": i.score, "Status": "Inbox",
        "Published": i.published.isoformat() if i.published else "",
    },
    "repos": lambda i: {
        "Name": i.title, "Owner": i.extra.get("owner", ""), "URL": i.url,
        "Stars": i.extra.get("stars", 0), "Language": i.extra.get("language", ""),
        "Why": i.summary, "Suggested": i.extra.get("suggested", ""),
        "Topics": i.topics, "Score": i.score, "Status": "Inbox",
        "Updated": i.published.isoformat() if i.published else "",
    },
    "signals": lambda i: {
        "Headline": i.title, "Source": i.source, "URL": i.url,
        "Suggested": i.extra.get("suggested", ""),
        "Category": i.extra.get("category", "Other"), "Score": i.score,
        "Status": "Inbox",
        "Published": i.published.isoformat() if i.published else "",
    },
}
KIND_TO_DB = {"paper": "papers", "repo": "repos", "signal": "signals"}

_CANONICAL_FIELDS = {
    "Name": "title", "Title": "title", "Task": "title", "Headline": "title",
    "Authors": "authors", "Abstract": "abstract", "URL": "url",
    "Topics": "useful_for", "Score": "score", "ArxivID": "arxiv_id",
    "Owner": "owner", "Stars": "stars", "Language": "language", "Why": "why",
    "DagID": "dag_id", "LastRun": "last_run", "NextRun": "next_run",
    "Schedule": "schedule", "Notes": "notes", "Author": "author",
    "Tier": "tier", "Type": "type", "Section": "section", "Module": "module",
    "Hours": "hours", "Area": "area", "Priority": "priority", "Due": "due",
}


def _action_for_status(status: str) -> str:
    lowered = status.casefold()
    if lowered in {"blocked", "needs geoff", "broken"}:
        return "block_card"
    if lowered in {"rejected", "rejected / skip"}:
        return "reject_card"
    if lowered in {"in progress", "scheduled", "reading", "trying", "using"}:
        return "start_todo"
    if lowered in {"done", "completed", "published", "read", "archived", "retired", "internalized"}:
        return "finish_todo"
    if lowered in {"ready", "in queue", "saved", "review"}:
        return "stage_card"
    return "add_mission_card"


class InternalBoardClient:
    """Idempotent row facade over first-party board stores."""

    def __init__(self, *, store_dir: str | Path | None = None,
                 event_log: str | Path | None = None, dry_run: bool = False,
                 out_dir: str | Path = "./_export"):
        self.store_dir = Path(store_dir or os.environ.get(
            "GROWTHOS_BOARD_STORE", "../generated/boards"))
        self.event_log = Path(event_log or os.environ.get(
            "GROWTHOS_KANBAN_EVENT_LOG", "../generated/kanban-events.jsonl"))
        self.dry_run = dry_run
        self.out = Path(out_dir)

    def _provider(self, db_name: str) -> CommandCenterBoardProvider:
        board_id = BOARD_IDS.get(db_name, db_name)
        return CommandCenterBoardProvider(
            board_id=board_id,
            event_log=EventLog(self.event_log),
            store_dir=self.store_dir,
        )

    @staticmethod
    def _canonicalize(cells: dict[str, Any]) -> dict[str, Any]:
        out = dict(cells)
        title = out.get("Name") or out.get("Title") or out.get("Task") or out.get("Headline")
        if title:
            out.setdefault("Name", title)
        for legacy, canonical in _CANONICAL_FIELDS.items():
            value = out.get(legacy)
            if value not in (None, ""):
                out.setdefault(canonical, value)
        return out

    def list_row_ids(self, db_name: str) -> list[str]:
        return [str(row["card_id"]) for row in self._provider(db_name).list_cards()]

    def row_details(self, db_name: str, row_ids: list[str], chunk: int = 40) -> list[dict]:
        wanted = set(row_ids)
        out: list[dict] = []
        for row in self._provider(db_name).list_cards():
            card_id = str(row.get("card_id", ""))
            if card_id not in wanted:
                continue
            cells = {
                key: value for key, value in row.items()
                if key not in {"card_id", "board_id", "status", "last_event_id"}
            }
            if row.get("status") is not None:
                cells["Status"] = row["status"]
            out.append({"id": card_id, "cells": cells})
        return out

    def rows_updated_since(self, db_name: str, after_iso: str) -> list[str]:
        after = datetime.fromisoformat(after_iso.replace("Z", "+00:00")).timestamp()
        provider = self._provider(db_name)
        if not provider.store_dir.is_dir():
            return []
        return [path.stem for path in provider.store_dir.glob("*.json")
                if path.stat().st_mtime >= after]

    def upsert(self, db_name: str, rows: list[dict]) -> list[str]:
        if self.dry_run:
            return self._write_csv(db_name, rows)
        provider = self._provider(db_name)
        written: list[str] = []
        for row in rows:
            card_id = str(row["pre_hash"])
            cells = self._canonicalize(dict(row.get("cells") or {}))
            status = cells.pop("Status", None)
            if is_human_owned_status(status):
                continue
            provider.upsert_card(card_id, cells)
            current = (provider.snapshot() or {}).get(card_id, {}).get("status")
            if status not in (None, "") and current != status:
                emit_event(
                    provider.log,
                    action=_action_for_status(str(status)),
                    board_id=provider.board_id,
                    card_id=card_id,
                    source_surface="growth_os",
                    actor_type="agent",
                    status_before=current,
                    status_after=str(status),
                )
            written.append(card_id)
        return written

    def _write_csv(self, db_name: str, rows: list[dict]) -> list[str]:
        if not rows:
            return []
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / f"{db_name}.csv"
        fields = list(rows[0]["cells"].keys())
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            if new:
                writer.writeheader()
            for row in rows:
                writer.writerow(row["cells"])
        return [str(row["pre_hash"]) for row in rows]


def items_to_cells(items: list[CuratedItem]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for item in items:
        db_name = KIND_TO_DB[item.kind]
        out.setdefault(db_name, []).append({
            "pre_hash": item.external_id,
            "cells": FIELD_MAP[db_name](item),
        })
    return out