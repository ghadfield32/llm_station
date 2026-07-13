"""Feed the reference index + preview from the LIVE AppFlowy boards.

This is what actually fixes "can't find the library / book / note / post without
the exact name": instead of a static config, it indexes every database in
databases.json (library, papers, repos, signals, notes, lessons, the LinkedIn
content boards, ...) so a fuzzy/semantic query resolves to a real card.

Two halves:
  - pure mappers (records_from_rows, posts_from_rows) - take already-fetched rows
    and produce IndexRecords / LinkedInPosts. Deterministic, unit-tested offline.
  - thin IO fetchers (fetch_all, fetch_posts) - reuse the content engine's AppFlowy
    auth (content.sources) to pull rows, preserving each row's id so a note write
    can address the exact card.

Read-only. Writing a note goes through the governed event path (cli/content_note),
never a raw board mutation here.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx

from command_center.cli.kanban_bridge import merged_env
from .post_model import LinkedInPost
from .reference_index import IndexRecord
from .sources import _appflowy, _cell

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

_TITLE_FIELDS = ("Title", "Name", "Hook", "Headline", "Topic", "Question")
_BODY_FIELDS = ("Body", "Abstract", "Why", "Notes", "Summary", "Detail",
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
        hook = _cell(cells, "Hook", "Title", "Headline")
        body = _cell(cells, "Body", "Content", "Text")
        if not (hook or body):
            continue
        full = f"{hook}\n\n{body}".strip() if (hook and body) else (hook or body)
        out.append(LinkedInPost(
            author_name=author_name, body=full,
            id=row.get("id") or _cell(cells, "Key") or hook[:24]))
    return out


# ── thin IO fetchers (reuse content.sources AppFlowy auth) ────────────────
def _rows_with_ids(base: str, ws: str, token: str, db_id: str) -> list[dict]:
    """GET a database's rows preserving each row id (sources._read_rows drops it,
    but a note write needs the card id)."""
    h = {"Authorization": f"Bearer {token}"}
    ids = [x["id"] for x in httpx.get(
        f"{base}/api/workspace/{ws}/database/{db_id}/row",
        headers=h, timeout=30).json()["data"]]
    out: list[dict] = []
    for i in range(0, len(ids), 40):
        d = httpx.get(f"{base}/api/workspace/{ws}/database/{db_id}/row/detail",
                      headers=h, params={"ids": ",".join(ids[i:i + 40])}, timeout=30)
        for row in d.json()["data"]:
            out.append({"id": row.get("id", ""), "cells": row.get("cells", row)})
    return out


def _env_for(source, env: dict | None):
    return env or merged_env(Path(".env"), Path(source.growthos_root) / ".env")


def fetch_all(source, env: dict | None = None,
              only: list[str] | None = None) -> dict[str, list[dict]]:
    """Pull rows from every database in databases.json (or just `only`)."""
    env = _env_for(source, env)
    base, ws, token, db_map = _appflowy(source, env)
    return {db: _rows_with_ids(base, ws, token, entry["database_id"])
            for db, entry in db_map.items()
            if not only or db in only}


def fetch_posts(source, env: dict | None = None,
                boards: tuple[str, ...] = CONTENT_BOARDS) -> list[LinkedInPost]:
    """Pull the LinkedIn content-board cards as LinkedInPosts (author = board)."""
    rows_by_db = fetch_all(source, env, only=list(boards))
    posts: list[LinkedInPost] = []
    for board, rows in rows_by_db.items():
        posts += posts_from_rows(rows, author_name=board)
    return posts
