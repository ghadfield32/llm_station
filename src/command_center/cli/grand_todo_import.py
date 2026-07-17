"""Import the Betts Basketball GRAND TODO into a governed first-party board.

The Markdown file remains canonical.  This importer is a merge-only projection:

* stable tracker IDs become stable card IDs;
* the unnumbered Idea Bank is one stable, exact-snapshot card;
* the complete source document is retained in one metadata card;
* source revisions append exact Markdown snapshots instead of replacing history;
* existing status and fields outside the explicit importer-owned set survive;
* a source item disappearing never deletes or archives its existing card.

Dry-run is the default.  ``--apply`` takes the same exclusive board-write lock
as cockpit edits, validates the complete source before the first write, and
creates status events only for new/status-less cards.  A rerun therefore repairs
a card-field write that was interrupted before its creation event without
duplicating already-folded status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.write_locking import (
    BoardWriteLocked,
    board_write_lock,
    source_write_lock,
)
from command_center.kanban_sync.events import EventLog, emit_event

ROOT = Path(__file__).resolve().parents[3]
BOARD_ID = "betts_basketball_grand_todo"
SOURCE_REF = "betts_basketball/docs/backend/projects/GRAND_TODO_LIST.md"
IMPORTER_ID = "betts-grand-todo.v1"

_ITEM_HEADER_RE = re.compile(
    r"^####\s+(?P<item_id>[A-Z][A-Z0-9]*-\d+)\s+·\s+(?P<title>.+?)\s*$"
)
_BOUNDARY_RE = re.compile(r"^#{1,4}\s+")
_CATEGORY_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_TRACKING_RE = re.compile(
    r"^`(?P<status>[^`]+)`\s+·\s+\*\*Target:\*\*\s+(?P<target>.*?)\s+"
    r"·\s+\*\*Done:\*\*\s+(?P<done>.*?)\s*$"
)
_NOTES_RE = re.compile(r"\*\*Notes:\*\*\s*(?P<notes>.*)", re.DOTALL)

_INITIAL_STATUS = {
    "DONE": "Done",
    "SHIP-TAIL": "Ready",
    "WIP": "In Progress",
    "PLANNED": "Backlog",
    "IDEA": "Backlog",
    "RITUAL": "Ready",
    "BLOCKED": "Blocked",
    "ARCHIVED": "Archived",
}

_STATUS_BADGE = {
    "Backlog": "📋 PLANNED",
    "Ready": "🚀 SHIP-TAIL",
    "In Progress": "🚧 WIP",
    "Blocked": "⛔ BLOCKED",
    "Done": "✅ DONE",
    "Archived": "📦 ARCHIVED",
}


class GrandTodoImportError(RuntimeError):
    """The source or existing import state is unsafe to project."""


@dataclass(frozen=True)
class SourceCard:
    card_id: str
    item_id: str
    title: str
    category: str
    source_status: str
    target: str
    completed: str
    source_notes: str
    raw_markdown: str
    source_kind: str
    initial_status: str
    start_char: int
    end_char: int

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.raw_markdown.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ParsedGrandTodo:
    cards: tuple[SourceCard, ...]
    tracked_count: int
    source_text: str
    source_sha256: str


def _status_key(label: str) -> str:
    plain = label.replace("✅", "").replace("🚀", "").replace("🚧", "")
    plain = plain.replace("📋", "").replace("💡", "").replace("🔁", "")
    plain = plain.replace("⛔", "").replace("📦", "")
    return plain.replace("(verify)", "").strip()


def _initial_status(label: str) -> str:
    key = _status_key(label)
    try:
        return _INITIAL_STATUS[key]
    except KeyError as exc:
        raise GrandTodoImportError(f"unsupported GRAND TODO status badge {label!r}") from exc


def _card_id(item_id: str) -> str:
    return f"grand-todo-{item_id.casefold()}"


def _segment(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start:end])


def parse_grand_todo_bytes(raw: bytes, *, expected_items: int | None = None) -> ParsedGrandTodo:
    """Parse after decoding UTF-8 while preserving every original line ending.

    A task stops at the next heading of level 1-4.  This is intentionally
    heading-aware: stopping only at the next ``####`` would absorb category
    preambles and the complete Idea Bank into preceding tasks.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GrandTodoImportError("GRAND TODO must be valid UTF-8") from exc
    if text.encode("utf-8") != raw:
        raise GrandTodoImportError("GRAND TODO UTF-8 round-trip changed source bytes")

    lines = text.splitlines(keepends=True)
    char_offsets = [0]
    for line in lines:
        char_offsets.append(char_offsets[-1] + len(line))
    categories: dict[int, str] = {}
    current_category = ""
    for i, line in enumerate(lines):
        match = _CATEGORY_RE.match(line.rstrip("\r\n"))
        if match:
            current_category = match.group("title")
        categories[i] = current_category

    item_starts: list[tuple[int, re.Match[str]]] = []
    seen_ids: set[str] = set()
    for i, line in enumerate(lines):
        match = _ITEM_HEADER_RE.match(line.rstrip("\r\n"))
        if not match:
            continue
        item_id = match.group("item_id")
        if item_id in seen_ids:
            raise GrandTodoImportError(f"duplicate GRAND TODO item id {item_id!r}")
        seen_ids.add(item_id)
        item_starts.append((i, match))

    if not item_starts:
        raise GrandTodoImportError("GRAND TODO contains no stable item headings")
    if expected_items is not None and len(item_starts) != expected_items:
        raise GrandTodoImportError(
            f"GRAND TODO expected {expected_items} tracked items; found {len(item_starts)}"
        )

    cards: list[SourceCard] = []
    for start, header in item_starts:
        end = start + 1
        while end < len(lines) and not _BOUNDARY_RE.match(lines[end]):
            end += 1
        raw_block = _segment(lines, start, end)
        block_lines = raw_block.splitlines()
        tracking = next((_TRACKING_RE.match(line) for line in block_lines[1:]
                         if _TRACKING_RE.match(line)), None)
        if tracking is None:
            raise GrandTodoImportError(
                f"GRAND TODO item {header.group('item_id')} has no tracking line"
            )
        status = tracking.group("status")
        notes_match = _NOTES_RE.search(raw_block)
        item_id = header.group("item_id")
        cards.append(SourceCard(
            card_id=_card_id(item_id),
            item_id=item_id,
            title=header.group("title"),
            category=categories[start],
            source_status=status,
            target=tracking.group("target"),
            completed=tracking.group("done"),
            source_notes=notes_match.group("notes").strip() if notes_match else "",
            raw_markdown=raw_block,
            source_kind="tracked_item",
            initial_status=_initial_status(status),
            start_char=char_offsets[start], end_char=char_offsets[end],
        ))

    idea_start = next((i for i, line in enumerate(lines)
                       if line.rstrip("\r\n") == "## Idea Bank"), None)
    change_start = next((i for i, line in enumerate(lines)
                         if line.rstrip("\r\n") == "## Change log"), None)
    if idea_start is None or change_start is None or change_start <= idea_start:
        raise GrandTodoImportError("GRAND TODO needs ordered Idea Bank and Change log sections")
    idea_raw = _segment(lines, idea_start, change_start)
    cards.append(SourceCard(
        card_id=_card_id("IDEA-BANK"), item_id="IDEA-BANK",
        title="Idea Bank — raw, un-triaged concepts", category="Idea Bank",
        source_status="💡 IDEA", target="_TBD_", completed="_—_",
        source_notes="Preserved as one stable card because the raw bullets have no stable IDs.",
        raw_markdown=idea_raw, source_kind="idea_bank",
        initial_status="Backlog",
        start_char=char_offsets[idea_start], end_char=char_offsets[change_start],
    ))
    cards.append(SourceCard(
        card_id=_card_id("SOURCE"), item_id="SOURCE",
        title="GRAND TODO — guide and complete source snapshot",
        category="Tracker metadata", source_status="SOURCE", target="_ongoing_",
        completed="_—_", source_notes="Byte-exact canonical source snapshot.",
        raw_markdown=text, source_kind="source_document", initial_status="Backlog",
        start_char=0, end_char=len(text),
    ))

    return ParsedGrandTodo(
        cards=tuple(cards), tracked_count=len(item_starts), source_text=text,
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def parse_grand_todo(path: Path, *, expected_items: int | None = None) -> ParsedGrandTodo:
    if not path.is_file():
        raise GrandTodoImportError(f"GRAND TODO source not found: {path}")
    return parse_grand_todo_bytes(path.read_bytes(), expected_items=expected_items)


def _revision(card: SourceCard, captured_at: str) -> dict[str, Any]:
    return {
        "sha256": card.source_sha256,
        "captured_at": captured_at,
        "status": card.source_status,
        "raw_markdown": card.raw_markdown,
    }


def _source_fields(card: SourceCard, existing: dict[str, Any] | None,
                   captured_at: str) -> dict[str, Any]:
    prior = dict(existing or {})
    revisions = prior.get("source_revisions", [])
    if not isinstance(revisions, list):
        raise GrandTodoImportError(
            f"card {card.card_id!r} has non-list source_revisions; refusing to overwrite it"
        )
    for index, revision in enumerate(revisions):
        if (not isinstance(revision, dict)
                or not isinstance(revision.get("sha256"), str)
                or not revision["sha256"]):
            raise GrandTodoImportError(
                f"card {card.card_id!r} has invalid source_revisions[{index}]; "
                "refusing to overwrite it"
            )
    revisions = list(revisions)
    if not revisions or revisions[-1].get("sha256") != card.source_sha256:
        revisions.append(_revision(card, captured_at))
    return {
        "item_id": card.item_id,
        "title": card.title,
        "category": card.category,
        "source_status": card.source_status,
        "target": card.target,
        "completed": card.completed,
        "source_notes": card.source_notes,
        "description": card.raw_markdown,
        "source_kind": card.source_kind,
        "source_ref": SOURCE_REF,
        "source_anchor": card.item_id.casefold(),
        "source_sha256": card.source_sha256,
        "source_revision_count": len(revisions),
        "source_revisions": revisions,
        "source_importer": IMPORTER_ID,
        "repo_id": "betts_basketball",
    }


def _append_change_log(text: str, *, item_id: str, detail: str, at: datetime) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    suffix = "" if text.endswith(("\n", "\r")) else newline
    return (
        text + suffix
        + f"- {at.date().isoformat()} — Cockpit sync: {item_id} {detail}.{newline}"
    )


def _atomic_write_source(path: Path, text: str) -> None:
    encoded = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _replace_card_status(
    parsed: ParsedGrandTodo, card: SourceCard, status: str, *, at: datetime,
) -> str:
    try:
        badge = _STATUS_BADGE[status]
    except KeyError as exc:
        raise GrandTodoImportError(f"unsupported GRAND TODO board status {status!r}") from exc
    block, count = re.subn(
        r"(?m)^\x60[^\x60]+\x60(?=\s+·\s+\*\*Target:\*\*)",
        f"`{badge}`",
        card.raw_markdown,
        count=1,
    )
    if count != 1:
        raise GrandTodoImportError(
            f"card {card.item_id!r} tracking badge could not be replaced exactly once")
    text = parsed.source_text[:card.start_char] + block + parsed.source_text[card.end_char:]
    return _append_change_log(
        text, item_id=card.item_id, detail=f"moved to {status}", at=at)


def _tracked_ids(parsed: ParsedGrandTodo) -> list[str]:
    return sorted(card.item_id for card in parsed.cards if card.source_kind == "tracked_item")


def _assert_complete_projection(
    parsed: ParsedGrandTodo, existing: dict[str, dict[str, Any]],
) -> None:
    source_meta = existing.get(_card_id("SOURCE"))
    if not source_meta:
        return
    previous = source_meta.get("tracked_item_ids")
    if previous is None:
        return
    if not isinstance(previous, list) or not all(isinstance(v, str) for v in previous):
        raise GrandTodoImportError(
            "source metadata has invalid tracked_item_ids; refusing to overwrite it")
    missing = sorted(set(previous) - set(_tracked_ids(parsed)))
    if missing:
        raise GrandTodoImportError(
            "GRAND TODO lost previously tracked item IDs; no writes were made: "
            + ", ".join(missing))


def _conflict_fields(
    card: SourceCard, current: dict[str, Any], *, captured_at: str,
) -> dict[str, Any]:
    history = current.get("sync_conflicts", [])
    if not isinstance(history, list):
        raise GrandTodoImportError(
            f"card {card.card_id!r} has non-list sync_conflicts")
    entry = {
        "captured_at": captured_at,
        "source_sha256": card.source_sha256,
        "source_status": card.initial_status,
        "board_status": current.get("status"),
        "base_source_sha256": current.get("sync_source_sha256"),
        "base_board_status": current.get("sync_board_status"),
    }
    signature = {k: v for k, v in entry.items() if k != "captured_at"}
    if not history or {
        k: history[-1].get(k) for k in signature
    } != signature:
        history = [*history, entry]
    return {
        "sync_state": "conflict",
        "sync_conflicts": history,
        "active_sync_conflict": entry,
    }


def plan_import(parsed: ParsedGrandTodo, provider: CommandCenterBoardProvider, *,
                captured_at: str) -> dict[str, Any]:
    existing = {str(card["card_id"]): card for card in provider.list_cards()}
    _assert_complete_projection(parsed, existing)
    operations: list[dict[str, Any]] = []
    incoming_ids: set[str] = set()
    for card in parsed.cards:
        incoming_ids.add(card.card_id)
        current = existing.get(card.card_id)
        if current is not None and current.get("source_importer") != IMPORTER_ID:
            raise GrandTodoImportError(
                f"card id collision at {card.card_id!r}: existing card is not owned "
                f"by {IMPORTER_ID}; refusing to adopt or overwrite it"
            )
        desired_status = card.initial_status
        conflict = False
        needs_status_event = False
        if current is not None and card.source_kind == "tracked_item":
            base_sha = current.get("sync_source_sha256")
            base_status = current.get("sync_board_status")
            if isinstance(base_sha, str) and isinstance(base_status, str):
                source_changed = card.source_sha256 != base_sha
                board_changed = current.get("status") != base_status
                conflict = (
                    source_changed and board_changed
                    and current.get("status") != desired_status
                )
                needs_status_event = (
                    source_changed and not board_changed
                    and current.get("status") != desired_status
                )
        if conflict:
            assert current is not None
            fields = _conflict_fields(card, current, captured_at=captured_at)
        else:
            fields = _source_fields(card, current, captured_at)
            if card.source_kind == "tracked_item":
                fields.update({
                    "sync_source_sha256": card.source_sha256,
                    "sync_board_status": (
                        desired_status if needs_status_event
                        else current.get("status") if current else desired_status
                    ),
                    "sync_state": "synchronized",
                    "active_sync_conflict": None,
                })
            elif card.source_kind == "source_document":
                fields["tracked_item_ids"] = _tracked_ids(parsed)
        changed = current is None or any(current.get(k) != v for k, v in fields.items())
        needs_event = current is None or current.get("status") is None
        action = "conflict" if conflict else "create" if current is None else (
            "recover_status" if needs_event and not changed else "update" if changed else "noop"
        )
        operations.append({
            "action": action,
            "card_id": card.card_id,
            "fields": fields,
            "needs_creation_event": needs_event,
            "initial_status": card.initial_status,
            "status_after": desired_status if needs_status_event else None,
            "current_status": current.get("status") if current else None,
        })

    preserved_missing = sorted(
        card_id for card_id, card in existing.items()
        if card.get("source_importer") == IMPORTER_ID and card_id not in incoming_ids
    )
    counts = {
        name: sum(op["action"] == name for op in operations)
        for name in ("create", "update", "recover_status", "conflict", "noop")
    }
    counts["creation_events"] = sum(op["needs_creation_event"] for op in operations)
    counts["preserved_missing"] = len(preserved_missing)
    return {
        "board_id": BOARD_ID,
        "tracked_items": parsed.tracked_count,
        "source_cards": len(parsed.cards),
        "source_sha256": parsed.source_sha256,
        "counts": counts,
        "preserved_missing_card_ids": preserved_missing,
        "operations": operations,
    }


def _board_only_status_updates(
    parsed: ParsedGrandTodo, provider: CommandCenterBoardProvider,
) -> list[tuple[SourceCard, str]]:
    existing = {str(card["card_id"]): card for card in provider.list_cards()}
    updates: list[tuple[SourceCard, str]] = []
    for card in parsed.cards:
        if card.source_kind != "tracked_item":
            continue
        current = existing.get(card.card_id)
        if not current:
            continue
        base_sha = current.get("sync_source_sha256")
        base_status = current.get("sync_board_status")
        status = current.get("status")
        if (
            isinstance(base_sha, str)
            and isinstance(base_status, str)
            and isinstance(status, str)
            and card.source_sha256 == base_sha
            and status != base_status
        ):
            updates.append((card, status))
    return updates


def _apply_locked(
    *, source_path: Path, provider: CommandCenterBoardProvider,
    expected_items: int | None, captured_at: str, now: datetime,
) -> dict[str, Any]:
    parsed = parse_grand_todo(source_path, expected_items=expected_items)
    _assert_complete_projection(
        parsed, {str(c["card_id"]): c for c in provider.list_cards()})
    for _, status in _board_only_status_updates(parsed, provider):
        if status not in _STATUS_BADGE:
            raise GrandTodoImportError(
                f"board-only status {status!r} cannot be represented in GRAND TODO")
    # Reparse after every exact replacement because character offsets and the
    # full-document hash change on each appended change-log entry.
    for old_card, status in _board_only_status_updates(parsed, provider):
        card = next(c for c in parsed.cards if c.card_id == old_card.card_id)
        _atomic_write_source(
            source_path, _replace_card_status(parsed, card, status, at=now))
        parsed = parse_grand_todo(source_path, expected_items=expected_items)

    result = plan_import(parsed, provider, captured_at=captured_at)
    for operation in result["operations"]:
        status_after = operation.get("status_after")
        if status_after:
            # For an existing card, advance the governed status before updating
            # its three-way base. If the subsequent field write is interrupted,
            # the next run sees a board-only convergence to the same source
            # status. The inverse order could incorrectly roll source back.
            emit_event(
                provider.log, action="finish_todo" if status_after in {"Done", "Archived"}
                else "block_card" if status_after == "Blocked"
                else "start_todo" if status_after == "In Progress"
                else "stage_card" if status_after == "Ready"
                else "add_mission_card",
                board_id=BOARD_ID, card_id=operation["card_id"],
                source_surface="reconciler", actor_type="system",
                repo_id="betts_basketball",
                status_before=operation.get("current_status"),
                status_after=status_after, evidence_ref=SOURCE_REF,
            )
        if operation["action"] not in {"noop", "recover_status"}:
            provider.upsert_card(operation["card_id"], operation["fields"])
        if operation["needs_creation_event"]:
            emit_event(
                provider.log, action="add_mission_card", board_id=BOARD_ID,
                card_id=operation["card_id"], source_surface="reconciler",
                actor_type="system", repo_id="betts_basketball",
                status_after=operation["initial_status"], evidence_ref=SOURCE_REF,
            )
    result.update({"status": "applied", "writes_performed": True})
    return result


def run_import(*, source_path: Path, store_dir: Path, event_log_path: Path,
               apply: bool, expected_items: int | None = None,
               now: datetime | None = None) -> dict[str, Any]:
    effective_now = now or datetime.now(timezone.utc)
    captured_at = effective_now.isoformat()
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(event_log_path), store_dir=store_dir)

    if not apply:
        parsed = parse_grand_todo(source_path, expected_items=expected_items)
        result = plan_import(parsed, provider, captured_at=captured_at)
        result.update({"status": "dry_run", "writes_performed": False})
        return result

    with source_write_lock(source_path):
        with board_write_lock(store_dir, BOARD_ID):
            return _apply_locked(
                source_path=source_path, provider=provider,
                expected_items=expected_items, captured_at=captured_at,
                now=effective_now)


def move_grand_todo_card(
    *, source_path: Path, store_dir: Path, event_log_path: Path,
    card_id: str, status: str, expected_source_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or datetime.now(timezone.utc)
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(event_log_path), store_dir=store_dir)
    with source_write_lock(source_path):
        with board_write_lock(store_dir, BOARD_ID):
            parsed = parse_grand_todo(source_path)
            card = next((c for c in parsed.cards if c.card_id == card_id), None)
            if card is None:
                raise GrandTodoImportError(f"card {card_id!r} is not in GRAND TODO")
            if card.source_kind != "tracked_item":
                raise GrandTodoImportError("tracker metadata and Idea Bank cards are read-only")
            if expected_source_sha256 and card.source_sha256 != expected_source_sha256:
                raise GrandTodoImportError("source revision changed; refresh before moving this card")
            current = next(
                (c for c in provider.list_cards() if c.get("card_id") == card_id), None)
            if current is None:
                raise GrandTodoImportError(f"board card {card_id!r} is missing")
            previous = current.get("status")
            if previous == status:
                return {"status": "unchanged", "card": current}
            _atomic_write_source(
                source_path, _replace_card_status(parsed, card, status, at=effective_now))
            event = emit_event(
                provider.log,
                action="finish_todo" if status in {"Done", "Archived"}
                else "block_card" if status == "Blocked"
                else "start_todo" if status == "In Progress"
                else "stage_card" if status == "Ready"
                else "add_mission_card",
                board_id=BOARD_ID, card_id=card_id, source_surface="internal_ui",
                actor_type="human", status_before=previous, status_after=status,
                evidence_ref=SOURCE_REF,
            )
            _apply_locked(
                source_path=source_path, provider=provider, expected_items=None,
                captured_at=effective_now.isoformat(), now=effective_now)
            moved = next(c for c in provider.list_cards() if c.get("card_id") == card_id)
            return {
                "status": "moved", "card_id": card_id,
                "from_status": previous, "to_status": status,
                "event": event.model_dump(mode="json"), "card": moved,
            }


def edit_grand_todo_card(
    *, source_path: Path, store_dir: Path, event_log_path: Path,
    card_id: str, raw_markdown: str, expected_source_sha256: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or datetime.now(timezone.utc)
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(event_log_path), store_dir=store_dir)
    with source_write_lock(source_path):
        with board_write_lock(store_dir, BOARD_ID):
            parsed = parse_grand_todo(source_path)
            card = next((c for c in parsed.cards if c.card_id == card_id), None)
            if card is None or card.source_kind != "tracked_item":
                raise GrandTodoImportError("only stable tracked GRAND TODO items are editable")
            if card.source_sha256 != expected_source_sha256:
                raise GrandTodoImportError("source revision changed; refresh before saving")
            candidate = (
                parsed.source_text[:card.start_char] + raw_markdown
                + parsed.source_text[card.end_char:]
            )
            candidate = _append_change_log(
                candidate, item_id=card.item_id, detail="edited", at=effective_now)
            checked = parse_grand_todo_bytes(candidate.encode("utf-8"))
            replacement = next((c for c in checked.cards if c.card_id == card_id), None)
            if replacement is None or set(_tracked_ids(checked)) != set(_tracked_ids(parsed)):
                raise GrandTodoImportError(
                    "edit changed stable tracker IDs; no source or board data was changed")
            _assert_complete_projection(
                checked, {str(c["card_id"]): c for c in provider.list_cards()})
            _atomic_write_source(source_path, candidate)
            result = _apply_locked(
                source_path=source_path, provider=provider, expected_items=None,
                captured_at=effective_now.isoformat(), now=effective_now)
            updated = next(c for c in provider.list_cards() if c.get("card_id") == card_id)
            return {"status": "edited", "card": updated, "sync": result["counts"]}


def _default_source() -> Path:
    configured = os.environ.get("BETTS_BASKETBALL_LOCAL_PATH", "").strip()
    if configured:
        return Path(configured) / "docs/backend/projects/GRAND_TODO_LIST.md"
    sibling = ROOT.parent / "betts_basketball" / "docs/backend/projects/GRAND_TODO_LIST.md"
    if sibling.is_file():
        return sibling
    raise GrandTodoImportError(
        "cannot resolve Betts Basketball source; pass --source or set "
        "BETTS_BASKETBALL_LOCAL_PATH"
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="grand-todo-import")
    parser.add_argument("--source", default="")
    parser.add_argument("--store-dir", default="generated/boards")
    parser.add_argument("--event-log", default="generated/kanban-events.jsonl")
    parser.add_argument(
        "--expected-items", type=int, default=None,
        help="optional audited stable-item count; additions/removals are otherwise allowed")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        source = Path(args.source).resolve() if args.source else _default_source()
        store = (ROOT / args.store_dir).resolve() if not Path(args.store_dir).is_absolute() \
            else Path(args.store_dir)
        event_log = (ROOT / args.event_log).resolve() if not Path(args.event_log).is_absolute() \
            else Path(args.event_log)
        result = run_import(
            source_path=source, store_dir=store, event_log_path=event_log,
            apply=args.apply, expected_items=args.expected_items,
        )
    except (GrandTodoImportError, BoardWriteLocked) as exc:
        print(f"grand-todo-import: BLOCKED\n  {exc}")
        return 1
    if args.json:
        printable = {k: v for k, v in result.items() if k != "operations"}
        printable["operations"] = [
            {k: v for k, v in operation.items() if k != "fields"}
            for operation in result["operations"]
        ]
        print(json.dumps(printable, indent=2, ensure_ascii=False))
    else:
        counts = result["counts"]
        print(
            f"grand-todo-import: {result['status']} — tracked={result['tracked_items']} "
            f"cards={result['source_cards']} create={counts['create']} "
            f"update={counts['update']} recover={counts['recover_status']} "
            f"noop={counts['noop']} preserved_missing={counts['preserved_missing']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
