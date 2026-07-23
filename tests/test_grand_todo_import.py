"""Merge-only Betts GRAND TODO importer."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.write_locking import board_write_lock
from command_center.cli.grand_todo_import import (
    BOARD_ID,
    MASTER_PROFILE,
    GrandTodoImportError,
    edit_grand_todo_card,
    move_grand_todo_card,
    parse_grand_todo_bytes,
    run_import,
)
from command_center.kanban_sync.events import EventLog, emit_event

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _source(*, second: bool = True, first_note: str = "first note") -> str:
    second_block = """
#### DE-2 · Keep the final task bounded
`📋 PLANNED` · **Target:** _TBD_ · **Done:** _—_
The category-final task must stop before the next category.
**Notes:** second note

""" if second else ""
    return f"""# GRAND TODO LIST — Master Tracker

## DE — Data Engineering

#### DE-1 · Build the durable importer
`🚧 WIP` · **Target:** 2026-07-20 · **Done:** _—_
Keep every source revision.
**Notes:** {first_note}

{second_block}## MLB — Separate Sport

#### MLB-3 · Preserve the final tracked task
`💡 IDEA` · **Target:** _TBD_ · **Done:** _—_
This block must not absorb the Idea Bank.
**Notes:** final tracked note

## Idea Bank

### Framing

- **Raw idea one.** Keep this exact.
- **Raw idea two.** Keep this too.

## Change log

- Initial organization.
"""


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "GRAND_TODO_LIST.md"
    store = tmp_path / "boards"
    log = tmp_path / "events.jsonl"
    return source, store, log


def _run(tmp_path: Path, text: str, *, apply: bool, expected: int | None = 3):
    source, store, log = _paths(tmp_path)
    source.write_bytes(text.encode("utf-8"))
    return run_import(
        source_path=source, store_dir=store, event_log_path=log,
        apply=apply, expected_items=expected, now=NOW,
    )


def test_parser_is_heading_aware_and_preserves_exact_idea_bank():
    raw = _source().replace("\n", "\r\n").encode("utf-8")
    parsed = parse_grand_todo_bytes(raw, expected_items=3)
    by_id = {card.item_id: card for card in parsed.cards}

    assert parsed.tracked_count == 3
    assert "## MLB" not in by_id["DE-2"].raw_markdown
    assert "## Idea Bank" not in by_id["MLB-3"].raw_markdown
    assert by_id["IDEA-BANK"].raw_markdown == (
        "## Idea Bank\r\n\r\n### Framing\r\n\r\n"
        "- **Raw idea one.** Keep this exact.\r\n"
        "- **Raw idea two.** Keep this too.\r\n\r\n"
    )
    assert by_id["SOURCE"].raw_markdown == raw.decode("utf-8")


def test_parser_fails_closed_on_duplicate_ids_and_wrong_expected_count():
    duplicate = _source().replace("MLB-3", "DE-1")
    with pytest.raises(GrandTodoImportError, match="duplicate"):
        parse_grand_todo_bytes(duplicate.encode("utf-8"))
    with pytest.raises(GrandTodoImportError, match="expected 148"):
        parse_grand_todo_bytes(_source().encode("utf-8"), expected_items=148)


def test_dry_run_performs_no_runtime_writes(tmp_path):
    result = _run(tmp_path, _source(), apply=False)
    _, store, log = _paths(tmp_path)

    assert result["status"] == "dry_run"
    assert result["counts"]["create"] == 5
    assert result["counts"]["creation_events"] == 5
    assert not store.exists()
    assert not log.exists()


def test_apply_is_idempotent_and_creates_one_event_per_card(tmp_path):
    first = _run(tmp_path, _source(), apply=True)
    _, store, log = _paths(tmp_path)
    second = _run(tmp_path, _source(), apply=True)

    assert first["counts"]["create"] == 5
    assert second["counts"]["noop"] == 5
    assert second["counts"]["creation_events"] == 0
    assert len(EventLog(log).read()) == 5
    assert len(list((store / BOARD_ID).glob("*.json"))) == 5
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    assert all(card["source_revision_count"] == 1 for card in provider.list_cards())


def test_update_appends_revision_and_preserves_manual_fields_and_status(tmp_path):
    _run(tmp_path, _source(), apply=True)
    _, store, log = _paths(tmp_path)
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    provider.upsert_card("grand-todo-de-1", {"user_notes": "manual context"})
    result = _run(tmp_path, _source(first_note="updated source note"), apply=True)
    card = next(c for c in provider.list_cards() if c["card_id"] == "grand-todo-de-1")

    assert result["counts"]["update"] == 2  # changed item + full-source metadata card
    assert card["status"] == "In Progress"
    assert card["user_notes"] == "manual context"
    assert card["source_revision_count"] == 2
    assert len(card["source_revisions"]) == 2
    assert card["source_revisions"][1]["raw_markdown"] == card["description"]
    assert "first note" in card["source_revisions"][0]["raw_markdown"]
    assert "updated source note" in card["source_revisions"][1]["raw_markdown"]


def test_missing_source_item_blocks_all_writes_and_is_never_deleted(tmp_path):
    _run(tmp_path, _source(), apply=True)
    with pytest.raises(GrandTodoImportError, match="lost previously tracked"):
        _run(tmp_path, _source(second=False), apply=True, expected=None)
    _, store, log = _paths(tmp_path)
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)

    assert any(card["card_id"] == "grand-todo-de-2" for card in provider.list_cards())


def test_divergent_source_and_board_status_records_conflict_without_choosing(tmp_path):
    _run(tmp_path, _source(), apply=True)
    source, store, log = _paths(tmp_path)
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    emit_event(
        provider.log, action="stage_card", board_id=BOARD_ID,
        card_id="grand-todo-de-1", source_surface="internal_ui",
        actor_type="human", status_before="In Progress", status_after="Ready",
    )
    source.write_bytes(_source(first_note="divergent source note").encode("utf-8"))

    result = run_import(
        source_path=source, store_dir=store, event_log_path=log,
        apply=True, expected_items=3, now=NOW)
    card = next(c for c in provider.list_cards() if c["card_id"] == "grand-todo-de-1")

    assert result["counts"]["conflict"] == 1
    assert card["status"] == "Ready"
    assert "first note" in card["description"]
    assert card["sync_state"] == "conflict"
    assert card["active_sync_conflict"]["source_status"] == "In Progress"


def test_archive_move_updates_source_and_can_restore(tmp_path):
    _run(tmp_path, _source(), apply=True)
    source, store, log = _paths(tmp_path)
    archived = move_grand_todo_card(
        source_path=source, store_dir=store, event_log_path=log,
        card_id="grand-todo-de-1", status="Archived", now=NOW)
    assert archived["card"]["status"] == "Archived"
    assert "`📦 ARCHIVED`" in source.read_text(encoding="utf-8")
    assert "DE-1 · Build the durable importer" in source.read_text(encoding="utf-8")

    restored = move_grand_todo_card(
        source_path=source, store_dir=store, event_log_path=log,
        card_id="grand-todo-de-1", status="Backlog", now=NOW)
    assert restored["card"]["status"] == "Backlog"
    assert "`📋 PLANNED`" in source.read_text(encoding="utf-8")


def test_edit_rewrites_only_stable_block_and_preserves_all_ids(tmp_path):
    _run(tmp_path, _source(), apply=True)
    source, store, log = _paths(tmp_path)
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    card = next(c for c in provider.list_cards() if c["card_id"] == "grand-todo-de-1")
    replacement = str(card["description"]).replace("first note", "edited in cockpit")

    result = edit_grand_todo_card(
        source_path=source, store_dir=store, event_log_path=log,
        card_id="grand-todo-de-1", raw_markdown=replacement,
        expected_source_sha256=card["source_sha256"], now=NOW)

    assert result["status"] == "edited"
    assert "edited in cockpit" in source.read_text(encoding="utf-8")
    assert parse_grand_todo_bytes(source.read_bytes()).tracked_count == 3


def test_status_event_before_base_write_recovers_without_source_rollback(
    tmp_path, monkeypatch,
):
    _run(tmp_path, _source(), apply=True)
    source, store, log = _paths(tmp_path)
    source.write_bytes(
        _source().replace("`🚧 WIP`", "`✅ DONE`", 1).encode("utf-8"))
    original = CommandCenterBoardProvider.upsert_card

    def interrupt(self, card_id, fields, **kwargs):
        if card_id == "grand-todo-de-1" and fields.get("sync_board_status") == "Done":
            raise RuntimeError("interrupted after status event")
        return original(self, card_id, fields, **kwargs)

    monkeypatch.setattr(CommandCenterBoardProvider, "upsert_card", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        run_import(
            source_path=source, store_dir=store, event_log_path=log,
            apply=True, expected_items=3, now=NOW)
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    assert next(c for c in provider.list_cards()
                if c["card_id"] == "grand-todo-de-1")["status"] == "Done"
    assert "`✅ DONE`" in source.read_text(encoding="utf-8")

    monkeypatch.setattr(CommandCenterBoardProvider, "upsert_card", original)
    run_import(
        source_path=source, store_dir=store, event_log_path=log,
        apply=True, expected_items=3, now=NOW)
    repaired = next(c for c in provider.list_cards()
                    if c["card_id"] == "grand-todo-de-1")
    assert repaired["sync_board_status"] == "Done"
    assert "`✅ DONE`" in source.read_text(encoding="utf-8")


def test_statusless_partial_create_is_recovered_once(tmp_path):
    source, store, log = _paths(tmp_path)
    source.write_bytes(_source().encode("utf-8"))
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    provider.upsert_card(
        "grand-todo-de-1",
        {"title": "partial", "source_importer": "betts-grand-todo.v1"},
    )

    first = run_import(
        source_path=source, store_dir=store, event_log_path=log,
        apply=True, expected_items=3, now=NOW)
    second = run_import(
        source_path=source, store_dir=store, event_log_path=log,
        apply=True, expected_items=3, now=NOW)

    assert first["counts"]["creation_events"] == 5
    assert second["counts"]["creation_events"] == 0
    assert len(EventLog(log).read()) == 5


def test_unowned_card_id_collision_is_rejected_without_overwrite(tmp_path):
    source, store, log = _paths(tmp_path)
    source.write_bytes(_source().encode("utf-8"))
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    provider.upsert_card("grand-todo-de-1", {"title": "manual card"})

    with pytest.raises(GrandTodoImportError, match="collision"):
        run_import(
            source_path=source, store_dir=store, event_log_path=log,
            apply=False, expected_items=3, now=NOW)
    assert provider.list_cards()[0]["title"] == "manual card"


def test_invalid_revision_history_is_rejected_without_overwrite(tmp_path):
    _run(tmp_path, _source(), apply=True)
    source, store, log = _paths(tmp_path)
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    provider.upsert_card("grand-todo-de-1", {"source_revisions": ["broken"]})

    with pytest.raises(GrandTodoImportError, match=r"source_revisions\[0\]"):
        run_import(
            source_path=source, store_dir=store, event_log_path=log,
            apply=False, expected_items=3, now=NOW)


def test_shared_board_lock_serializes_import_and_manual_merge(tmp_path):
    _run(tmp_path, _source(), apply=True)
    source, store, log = _paths(tmp_path)
    source.write_bytes(_source(first_note="updated while locked").encode("utf-8"))
    manual_provider = CommandCenterBoardProvider(
        board_id=BOARD_ID, event_log=EventLog(log), store_dir=store)
    started = threading.Event()
    finished = threading.Event()

    def manual_write():
        started.set()
        manual_provider.upsert_card(
            "grand-todo-de-1", {"user_notes": "concurrent manual context"})
        finished.set()

    with board_write_lock(store, BOARD_ID):
        thread = threading.Thread(target=manual_write)
        thread.start()
        assert started.wait(timeout=1)
        run_import(
            source_path=source, store_dir=store, event_log_path=log,
            apply=True, expected_items=3, now=NOW)
        assert not finished.is_set()  # manual writer is serialized, not interleaved
    thread.join(timeout=2)
    assert finished.is_set()

    card = next(
        row for row in manual_provider.list_cards()
        if row["card_id"] == "grand-todo-de-1")
    assert "updated while locked" in card["description"]
    assert card["user_notes"] == "concurrent manual context"
    assert card["source_revision_count"] == 2


def test_import_fails_closed_when_another_process_holds_board_lock(tmp_path):
    source, store, log = _paths(tmp_path)
    source.write_bytes(_source().encode("utf-8"))

    with board_write_lock(store, BOARD_ID):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "command_center.cli.grand_todo_import",
                "--source",
                str(source),
                "--store-dir",
                str(store),
                "--event-log",
                str(log),
                "--apply",
                "--expected-items",
                "3",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    assert result.returncode == 1
    assert "another writer currently owns" in result.stdout
    assert not (store / BOARD_ID).exists()


def test_master_profile_projects_per_item_repo_designations(tmp_path):
    text = _source().replace(
        "`🚧 WIP` · **Target:** 2026-07-20 · **Done:** _—_",
        "`🚧 WIP` · **Target:** 2026-07-20 · **Done:** _—_\n"
        "**Repo:** `betts_basketball`",
    )
    source, store, log = _paths(tmp_path)
    source.write_bytes(text.encode("utf-8"))

    result = run_import(
        source_path=source, store_dir=store, event_log_path=log,
        apply=True, expected_items=3, now=NOW, profile=MASTER_PROFILE)

    assert result["board_id"] == "grand_todo"
    assert (store / "grand_todo").is_dir()
    assert not (store / BOARD_ID).exists()
    provider = CommandCenterBoardProvider(
        board_id="grand_todo", event_log=EventLog(log), store_dir=store)
    cards = {c["card_id"]: c for c in provider.list_cards()}
    # Explicit per-item designation wins; undesignated items inherit the
    # master profile default; provenance names the master importer/source.
    assert cards["grand-todo-de-1"]["repo_id"] == "betts_basketball"
    assert cards["grand-todo-de-2"]["repo_id"] == "llm_station"
    assert cards["grand-todo-de-1"]["source_importer"] == "master-grand-todo.v1"
    assert (cards["grand-todo-de-1"]["source_ref"]
            == "llm_station/docs/todos/GRAND_TODO_LIST.md")
    events = EventLog(log).read()
    assert {event.board_id for event in events} == {"grand_todo"}
    assert {event.repo_id for event in events} == {
        "betts_basketball", "llm_station"}
