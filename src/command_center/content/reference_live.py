"""Feed the reference index and preview from first-party cockpit boards.

This is what actually fixes "can't find the library / book / note / post without
the exact name": instead of a static config, it indexes every database in
databases.json (library, papers, repos, signals, notes, lessons, the LinkedIn
content boards, ...) so a fuzzy/semantic query resolves to a real card.

Two halves:
  - pure mappers (records_from_rows, posts_from_rows) - take already-fetched rows
    and produce IndexRecords / LinkedInPosts. Deterministic, unit-tested offline.
  - thin IO fetchers (fetch_all, fetch_posts) - reuse the content engine's local
    board readers (content.sources) to pull rows, preserving each row's id so a note write
    can address the exact card.

Read-only. Writing a note goes through the governed event path (cli/content_note),
never a raw board mutation here.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


from .post_model import LinkedInPost
from .reference_index import IndexRecord
from .sources import _cell

# database name -> the kind label shown in search results. Unknown databases use
# their own name as the kind (so a future "books" db just works).
DEFAULT_KIND_MAP = {
    "papers": "paper", "repos": "repo", "signals": "signal", "notes": "note",
    "lessons": "lesson", "library": "library", "sources": "source",
    "review": "review", "todos": "todo", "guidelines": "guideline",
    "packages": "package", "dags": "dag", "mission_intake": "mission",
    "geoffhadfield32_content": "post", "world_model_sports_content": "post",
    "betts_basketball_board": "card",
}
# The LinkedIn content boards (post cards live here).
CONTENT_BOARDS = ("geoffhadfield32_content", "world_model_sports_content")

_TITLE_FIELDS = ("title", "hook", "Title", "Name", "Hook", "Headline", "Topic", "Question")
_BODY_FIELDS = ("body", "abstract", "notes", "Body", "Abstract", "Why", "Notes", "Summary", "Detail",
                "Answer", "Content", "Text")
_TAG_FIELDS = ("Topics", "Category", "Tags", "Pillar", "Section")


def _split_tags(value: str) -> list[str]:
    return [t for t in re.split(r"[,/|]| {2,}", value) if t.strip()][:8]


# ── pure mappers ──────────────────────────────────────────────────────────
def records_from_rows(rows_by_db: dict[str, list[dict]],
                      kind_map: dict[str, str] | None = None) -> list[IndexRecord]:
    """Map {database_name: [row, ...]} into IndexRecords. A row with no usable
    title is skipped (nothing to match on)."""
    kinds = {**DEFAULT_KIND_MAP, **(kind_map or {})}
    out: list[IndexRecord] = []
    for db, rows in rows_by_db.items():
        kind = kinds.get(db, db)
        for row in rows:
            cells = row.get("cells", row)
            title = _cell(cells, *_TITLE_FIELDS)
            if not title:
                continue
            summary = _cell(cells, *_BODY_FIELDS)
            tags_raw = " ".join(_cell(cells, f) for f in _TAG_FIELDS)
            rid = row.get("id") or ("live-" + hashlib.sha256(
                f"{db}|{title}".encode()).hexdigest()[:12])
            out.append(IndexRecord(
                id=rid, kind=kind, title=title[:120], aliases=[],
                tags=_split_tags(tags_raw) + [db], summary=summary[:200],
                source_path="", text=" ".join([title, summary, tags_raw]),
                board=db))
    return out


def posts_from_rows(rows: list[dict], author_name: str = "") -> list[LinkedInPost]:
    """Map LinkedIn content-board cards into render-ready LinkedInPosts. Hook +
    Body become the post body (hook is the above-the-fold first line)."""
    out: list[LinkedInPost] = []
    for row in rows:
        cells = row.get("cells", row)
        hook = _cell(cells, "hook", "Hook", "Title", "Headline")
        body = _cell(cells, "body", "Body", "Content", "Text")
        if not (hook or body):
            continue
        full = f"{hook}\n\n{body}".strip() if (hook and body) else (hook or body)
        out.append(LinkedInPost(
            author_name=author_name, body=full,
            id=row.get("id") or _cell(cells, "card_id", "Key") or hook[:24]))
    return out


# ── thin IO fetchers over the governed local board store ─────────────────
_BOARD_IDS = {
    "papers": "research_papers",
    "repos": "research_repos",
    "signals": "research_signals",
    "library": "reading_library",
    "notes": "knowledge_notes",
    "lessons": "learning_lessons",
    "todos": "personal_tasks",
    "dags": "dag_operations",
    "mission_intake": "llm_station_command_center",
}


def _provider_rows(source, board_id: str) -> list[dict]:
    from command_center.boards.command_center_provider import CommandCenterBoardProvider
    from command_center.kanban_sync.events import EventLog

    provider = CommandCenterBoardProvider(
        board_id=board_id,
        event_log=EventLog(source.event_log_path),
        store_dir=Path(source.board_store_dir),
    )
    return [{"id": row.get("card_id", ""), "cells": row}
            for row in provider.list_cards()]


def fetch_all(source, env: dict | None = None,
              only: list[str] | None = None) -> dict[str, list[dict]]:
    """Read known first-party boards (or just ``only``) without network auth."""
    names = list(only) if only else list(_BOARD_IDS)
    out: dict[str, list[dict]] = {}
    post_rows: list[dict] | None = None
    for name in names:
        if name in CONTENT_BOARDS:
            if post_rows is None:
                post_rows = _provider_rows(source, source.board_id)
            out[name] = [
                row for row in post_rows
                if str(row.get("cells", {}).get("account", "")) == name
            ]
            continue
        board_id = _BOARD_IDS.get(name)
        if board_id:
            out[name] = _provider_rows(source, board_id)
    return out


def fetch_posts(source, env: dict | None = None,
                boards: tuple[str, ...] = CONTENT_BOARDS) -> list[LinkedInPost]:
    """Read local Posts cards as LinkedInPosts (author = configured account)."""
    rows_by_db = fetch_all(source, only=list(boards))
    posts: list[LinkedInPost] = []
    for board, rows in rows_by_db.items():
        posts += posts_from_rows(rows, author_name=board)
    return posts