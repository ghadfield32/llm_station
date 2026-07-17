"""Audited AppFlowy history migration into first-party board stores."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.cli.appflowy_migrate import (
    SPECS,
    apply_plan,
    migrate,
    plan_database,
)
from command_center.kanban_sync.events import EventLog

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


class FakeSource:
    def __init__(self):
        self.data = {
            "papers": [self.row("p1", {"Title": "Paper", "ArxivID": "2607.1", "Status": "Inbox"})],
            "repos": [self.row("r1", {"Name": "Repo", "URL": "https://repo", "Status": "Trying"})],
            "dags": [self.row("d1", {"Name": "DAG", "DagID": "daily", "Status": "Active"})],
            "library": [self.row("b1", {"Name": "Book", "Author": "A", "Status": "To read"})],
            "geoffhadfield32_content": [
                self.row("g1", {"Hook": "Post one", "Key": "shared-post", "Status": "Draft"})],
            "world_model_sports_content": [
                self.row("w1", {"Hook": "Post two", "Key": "shared-post", "Status": "Published"})],
        }

    @staticmethod
    def row(row_id, cells):
        return {"id": row_id, "database_id": f"db-{row_id}", "cells": cells}

    def rows(self, db_name):
        return deepcopy(self.data[db_name])


def _migrate(tmp_path: Path, source: FakeSource, *, apply: bool):
    return migrate(
        source=source,
        store_dir=tmp_path / "boards",
        event_log_path=tmp_path / "events.jsonl",
        apply=apply,
        now=NOW,
    )


def test_dry_run_reads_all_sources_and_writes_nothing(tmp_path):
    result = _migrate(tmp_path, FakeSource(), apply=False)
    assert result["status"] == "dry_run"
    assert result["source_rows"] == 6
    assert result["identity_disambiguations"] == 1
    assert not (tmp_path / "boards").exists()
    assert not (tmp_path / "events.jsonl").exists()


def test_apply_is_idempotent_and_preserves_exact_provenance(tmp_path):
    source = FakeSource()
    first = _migrate(tmp_path, source, apply=True)
    second = _migrate(tmp_path, source, apply=True)
    assert first["source_rows"] == second["source_rows"] == 6
    assert all(db["noop"] == db["source_rows"] for db in second["databases"])
    assert len(EventLog(tmp_path / "events.jsonl").read()) == 6
    post_provider = CommandCenterBoardProvider(
        board_id="linkedin_content_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    assert {card["card_id"] for card in post_provider.list_cards()} == {
        "geoffhadfield32_content:shared-post", "shared-post"}

    provider = CommandCenterBoardProvider(
        board_id="research_papers",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    paper = provider.list_cards()[0]
    assert paper["card_id"] == "2607.1"
    assert paper["status"] == "Inbox"
    assert paper["appflowy_source_cells"] == source.data["papers"][0]["cells"]
    assert paper["appflowy_database_id"] == "db-p1"
    assert paper["appflowy_revision_count"] == 1
    books = CommandCenterBoardProvider(
        board_id="reading_library",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    ).list_cards()
    assert books[0]["title"] == "Book"
    assert all(db["status_initializations"] == 0 for db in second["databases"])
    assert all(db["changed_field_counts"] == {} for db in second["databases"])


def test_manual_divergence_is_preserved_and_recorded(tmp_path):
    source = FakeSource()
    _migrate(tmp_path, source, apply=True)
    provider = CommandCenterBoardProvider(
        board_id="research_papers",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card("2607.1", {"title": "First-party edited title"})
    source.data["papers"][0]["cells"]["Title"] = "Changed historical title"

    result = _migrate(tmp_path, source, apply=True)
    paper = provider.list_cards()[0]

    assert paper["title"] == "First-party edited title"
    assert paper["appflowy_migration_conflicts"]["title"]["appflowy_value"] == (
        "Changed historical title")
    papers = next(db for db in result["databases"] if db["source_db"] == "papers")
    assert papers["conflict_cards"] == 1
    assert paper["appflowy_revision_count"] == 2


def test_source_absence_never_deletes_a_first_party_card(tmp_path):
    source = FakeSource()
    _migrate(tmp_path, source, apply=True)
    source.data["repos"] = []
    _migrate(tmp_path, source, apply=True)
    provider = CommandCenterBoardProvider(
        board_id="research_repos",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    assert [card["card_id"] for card in provider.list_cards()] == ["https://repo"]


def test_book_title_aliases_prefer_title_over_name(tmp_path):
    source = FakeSource()
    source.data["library"][0]["cells"].update({
        "Title": "Canonical Title",
        "Name": "Legacy Name",
    })

    _migrate(tmp_path, source, apply=True)

    provider = CommandCenterBoardProvider(
        board_id="reading_library",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    assert provider.list_cards()[0]["title"] == "Canonical Title"


def test_paper_name_alias_repairs_missing_canonical_title(tmp_path):
    source = FakeSource()
    source.data["papers"][0]["cells"].pop("Title")
    source.data["papers"][0]["cells"]["Name"] = "Legacy paper name"

    _migrate(tmp_path, source, apply=True)

    provider = CommandCenterBoardProvider(
        board_id="research_papers",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    paper = provider.list_cards()[0]
    assert paper["title"] == "Legacy paper name"
    assert paper["appflowy_source_cells"]["Name"] == "Legacy paper name"


def test_book_rerun_repairs_missing_title_without_initializing_status(tmp_path):
    source = FakeSource()
    provider = CommandCenterBoardProvider(
        board_id="reading_library",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card(
        "book-book",
        {
            "author": "A",
            "appflowy_last_imported_fields": {"author": "A"},
        },
        status="To read",
    )

    dry_run = _migrate(tmp_path, source, apply=False)
    books = next(
        row for row in dry_run["databases"] if row["source_db"] == "library")
    assert books["create"] == 0
    assert books["update"] == 1
    assert books["status_initializations"] == 0
    assert books["changed_field_counts"]["title"] == 1

    _migrate(tmp_path, source, apply=True)
    assert provider.list_cards()[0]["title"] == "Book"
    audit = _migrate(tmp_path, source, apply=False)
    books = next(row for row in audit["databases"] if row["source_db"] == "library")
    assert books["update"] == 0
    assert books["changed_field_counts"] == {}


def test_book_rerun_preserves_divergent_first_party_title(tmp_path):
    source = FakeSource()
    _migrate(tmp_path, source, apply=True)
    provider = CommandCenterBoardProvider(
        board_id="reading_library",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card("book-book", {"title": "My edited title"})

    result = _migrate(tmp_path, source, apply=True)
    book = provider.list_cards()[0]

    assert book["title"] == "My edited title"
    assert book["appflowy_migration_conflicts"]["title"] == {
        "board_value": "My edited title",
        "appflowy_value": "Book",
        "last_imported_value": "Book",
    }
    books = next(row for row in result["databases"] if row["source_db"] == "library")
    assert books["conflict_cards"] == 1


def test_apply_replans_under_lock_and_preserves_edit_after_preview(tmp_path):
    source = FakeSource()
    spec = next(row for row in SPECS if row.source_db == "library")
    provider = CommandCenterBoardProvider(
        board_id="reading_library",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card(
        "book-book",
        {
            "author": "A",
            "appflowy_last_imported_fields": {"author": "A"},
        },
        status="To read",
    )
    rows = source.rows("library")
    preview = plan_database(
        spec=spec,
        rows=rows,
        provider=provider,
        imported_at=NOW.isoformat(),
    )
    assert preview["changed_field_counts"]["title"] == 1

    provider.upsert_card("book-book", {"title": "Operator edit after preview"})
    applied = apply_plan(
        spec=spec,
        rows=rows,
        provider=provider,
        store_dir=tmp_path / "boards",
        imported_at=NOW.isoformat(),
    )

    card = provider.list_cards()[0]
    assert card["title"] == "Operator edit after preview"
    assert card["appflowy_migration_conflicts"]["title"]["board_value"] == (
        "Operator edit after preview")
    assert applied["conflict_cards"] == 1
