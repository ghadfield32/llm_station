"""Hermetic tests for the first-party governed board layer."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from command_center.boards import (
    COMMAND_CENTER_CAPABILITIES,
    UnsupportedOperation,
    provider_for_board,
)
from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.kanban_sync import EventLog, GovernanceViolation, emit_event
from command_center.schemas.contracts import KanbanBoardSpec

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)

_STATUS_MAPPING = {
    "backlog": "Backlog", "ready": "Ready", "in_progress": "In Progress",
    "done": "Done", "blocked": "Blocked", "rejected": "Rejected",
    "awaiting_approval": "Awaiting Approval",
}


def _spec(board_id: str = "b1") -> KanbanBoardSpec:
    return KanbanBoardSpec(
        board_id=board_id, provider="command_center_ui",
        workspace_ref="self", board_ref=board_id, repo_ids=["llm_station"],
        status_mapping=dict(_STATUS_MAPPING), required_fields=["MissionID"],
        allowed_agent_verbs=["add_mission_card", "stage_card"],
        forbidden_agent_verbs=["approve_card", "merge", "deploy",
                               "delete_card", "delete_board"])

def _internal(tmp_path, board_id="b1") -> CommandCenterBoardProvider:
    return CommandCenterBoardProvider(
        board_id=board_id, event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards", status_mapping=dict(_STATUS_MAPPING))


# ---- concurrency: atomic card-store writes ---------------------------------

def test_upsert_is_atomic_under_concurrent_reads(tmp_path):
    """Regression: a writer rewriting a card file (background packet prep) must
    never expose a truncated/empty file to a concurrent list_cards()/_read_fields()
    reader. Before the fix, Path.write_text truncated first, so a reader in that
    window got '' -> json.loads('') -> JSONDecodeError (the CI flake). With the
    atomic temp+os.replace write, readers always see a complete file. This test
    fails reliably on the old code and passes on the fixed code."""
    import threading
    import time

    provider = _internal(tmp_path)
    provider.upsert_card("card-1", {"title": "seed", "notes": "n" * 300})
    errors: list[Exception] = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            provider.upsert_card("card-1", {"title": f"t{i}", "notes": "n" * 300})
            i += 1

    def reader():
        try:
            while not stop.is_set():
                for card in provider.list_cards():          # reads the store glob
                    assert isinstance(card, dict)
                provider._read_fields("card-1")
        except Exception as exc:            # capture a partial-read failure to assert on
            errors.append(exc)

    threads = [threading.Thread(target=writer)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.5)                          # let the writer + readers contend
    stop.set()
    for t in threads:
        t.join()
    assert not errors, f"concurrent read observed a partial write: {errors[:1]}"


def test_list_cards_cache_reuses_stable_projection_and_invalidates_on_write(
    tmp_path, monkeypatch,
):
    """Large board reads are cached, but field writes remain immediately live."""
    import command_center.boards.command_center_provider as provider_module

    provider = _internal(tmp_path)
    provider.upsert_card("card-1", {"title": "First"}, status="Backlog")
    original = provider_module._read_card_file
    reads = 0

    def counted_read(path):
        nonlocal reads
        reads += 1
        return original(path)

    monkeypatch.setattr(provider_module, "_read_card_file", counted_read)
    assert provider.list_cards()[0]["title"] == "First"
    cold_reads = reads
    assert cold_reads >= 1

    # A second provider instance (the normal API pattern) shares the stable
    # projection without touching the bind-mounted card files again.
    assert _internal(tmp_path).list_cards()[0]["title"] == "First"
    assert reads == cold_reads

    provider.upsert_card("card-1", {"title": "Updated"})
    assert _internal(tmp_path).list_cards()[0]["title"] == "Updated"
    assert reads > cold_reads


def test_list_cards_cold_scan_reads_each_consumed_artifact_once(tmp_path, monkeypatch):
    """The status fold and statusless-card pass must not parse one file twice."""
    import command_center.boards.command_center_provider as provider_module

    provider = _internal(tmp_path)
    provider.upsert_card("folded", {"title": "Folded"}, status="Backlog")
    provider.upsert_card("statusless", {"title": "Statusless"})
    provider._invalidate_list_cache()
    original = provider_module._read_card_file
    paths = []

    def recorded_read(path):
        paths.append(path)
        return original(path)

    monkeypatch.setattr(provider_module, "_read_card_file", recorded_read)
    assert {card["card_id"] for card in provider.list_cards()} == {
        "folded", "statusless",
    }
    assert len(paths) == len(set(paths)) == 2


def test_atomic_field_mutations_preserve_every_concurrent_append(tmp_path):
    """A read-before-upsert append loses updates; the board-locked mutation does not."""
    from concurrent.futures import ThreadPoolExecutor

    provider = _internal(tmp_path)
    provider.upsert_card("book-1", {"title": "Concurrency in Practice"})

    def append_note(index: int) -> None:
        def mutate(current, _cards):
            assert current is not None
            notes = list(current.get("book_notes", []))
            notes.append({"note_id": f"note-{index}", "sequence": len(notes) + 1})
            return {**current, "book_notes": notes}

        provider.mutate_card_fields("book-1", mutate)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append_note, range(24)))

    notes = provider._read_fields("book-1")["book_notes"]
    assert len(notes) == 24
    assert {note["note_id"] for note in notes} == {
        f"note-{index}" for index in range(24)
    }
    assert [note["sequence"] for note in notes] == list(range(1, 25))


def test_atomic_batch_field_mutation_scans_once_and_updates_exact_cards(
    tmp_path, monkeypatch,
):
    provider = _internal(tmp_path)
    for index in range(3):
        provider.upsert_card(f"book-{index}", {"title": f"Book {index}"})
    original_list_cards = provider.list_cards
    scans = 0

    def counted_list_cards():
        nonlocal scans
        scans += 1
        return original_list_cards()

    monkeypatch.setattr(provider, "list_cards", counted_list_cards)
    result = provider.mutate_card_fields_batch({
        "book-0": lambda current: {**current, "genre": "History"},
        "book-2": lambda current: {**current, "genre": "Science"},
    })

    assert scans == 1
    assert set(result) == {"book-0", "book-2"}
    assert provider._read_fields("book-0")["genre"] == "History"
    assert "genre" not in provider._read_fields("book-1")
    assert provider._read_fields("book-2")["genre"] == "Science"


def test_atomic_batch_field_mutation_validates_every_replacement_before_writing(
    tmp_path,
):
    provider = _internal(tmp_path)
    provider.upsert_card("book-0", {"title": "Book 0"})

    with pytest.raises(KeyError, match="missing"):
        provider.mutate_card_fields_batch({
            "book-0": lambda current: {**current, "genre": "History"},
            "missing": lambda current: current,
        })

    assert "genre" not in provider._read_fields("book-0")


def test_atomic_create_callback_sees_prior_concurrent_create(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    provider = _internal(tmp_path)

    def create(index: int) -> str:
        card_id = f"candidate-{index}"

        def mutate(_current, cards):
            if any(card.get("title") == "Same Book" for card in cards):
                raise ValueError("duplicate book")
            return {"title": "Same Book"}

        try:
            provider.mutate_card_fields(card_id, mutate, create=True)
        except ValueError:
            return "duplicate"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, range(2)))

    assert sorted(outcomes) == ["created", "duplicate"]
    assert [card["title"] for card in provider.list_cards()] == ["Same Book"]


def test_atomic_create_rolls_back_fields_when_governed_event_fails(tmp_path):
    provider = _internal(tmp_path)

    def fail_event() -> None:
        raise OSError("event log unavailable")

    with pytest.raises(OSError, match="event log unavailable"):
        provider.mutate_card_fields(
            "book-uncommitted",
            lambda _current, _cards: {"title": "Never Half Created"},
            create=True,
            after_write=fail_event,
        )

    assert provider.list_cards() == []
    assert not provider._card_path("book-uncommitted").exists()


def test_atomic_event_mutation_reads_only_the_locked_target_card(
    tmp_path, monkeypatch,
):
    """A one-card status write must not read every field document on the board."""
    provider = _internal(tmp_path)
    provider.upsert_card(
        "target", {"title": "Target", "private_marker": "preserved"},
        status="Backlog",
    )
    for index in range(40):
        provider.upsert_card(
            f"other-{index}", {"title": f"Other {index}"},
            status="Backlog",
        )

    def whole_board_read_is_a_regression():
        pytest.fail("status mutation materialized the complete board")

    monkeypatch.setattr(provider, "list_cards", whole_board_read_is_a_regression)
    observed = {}

    def mutate(card):
        observed.update(card)
        return card["status"]

    assert provider.mutate_card_event("target", mutate) == "Backlog"
    assert observed["card_id"] == "target"
    assert observed["private_marker"] == "preserved"
    assert observed["status"] == "Backlog"


# ---- factory ----------------------------------------------------------------

def test_factory_builds_first_party_provider(tmp_path):
    provider = provider_for_board(
        _spec(), event_log=EventLog(tmp_path / "e.jsonl"),
        store_dir=tmp_path / "boards")
    assert isinstance(provider, CommandCenterBoardProvider)
    assert provider.capabilities() is COMMAND_CENTER_CAPABILITIES


def test_capability_flags_preserve_governance_wall():
    assert not COMMAND_CENTER_CAPABILITIES.supports_delete_row
    assert COMMAND_CENTER_CAPABILITIES.supports_custom_card_rendering
    assert COMMAND_CENTER_CAPABILITIES.supports_live_sync

# ---- internal provider ---------------------------------------------------------
# ---- internal provider ---------------------------------------------------------

def test_internal_status_truth_is_the_event_fold(tmp_path):
    p = _internal(tmp_path)
    p.upsert_card("c1", {"company": "Acme", "fit_score": 91}, status="Backlog")
    emit_event(p.log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="internal_ui", status_after="Ready", now=NOW)
    cards = p.list_cards()
    assert len(cards) == 1
    card = cards[0]
    assert card["status"] == "Ready"          # fold wins
    assert card["company"] == "Acme" and card["fit_score"] == 91
    assert p.snapshot() == {"c1": p.snapshot()["c1"]}  # snapshot is the fold


def test_internal_store_never_overrides_status(tmp_path):
    p = _internal(tmp_path)
    p.upsert_card("c1", {"status": "Done", "company": "Acme"}, status="Backlog")
    card = p.list_cards()[0]
    assert card["status"] == "Backlog"        # sneaky field-status dropped


def test_internal_upsert_with_human_owned_status_refused(tmp_path):
    p = _internal(tmp_path)
    out = p.upsert_card("c1", {}, status="awaiting_approval")
    assert out["status"] == "refused"
    assert p.list_cards() == []               # nothing stored, nothing emitted


def test_internal_wall_verbs_still_governed(tmp_path):
    p = _internal(tmp_path)
    with pytest.raises(GovernanceViolation):
        emit_event(p.log, action="approve_card", board_id="b1", card_id="c1",
                   source_surface="internal_ui", now=NOW)
    with pytest.raises(UnsupportedOperation):
        p.delete_row("c1")


def test_internal_card_ids_cannot_traverse_paths(tmp_path):
    p = _internal(tmp_path)
    p.upsert_card("../../evil", {"company": "X"})
    store = (tmp_path / "boards" / "b1").resolve()
    stored = list(store.glob("*.json"))
    assert len(stored) == 1
    # separators are stripped, so the file cannot escape the board's store dir
    assert "/" not in stored[0].name and "\\" not in stored[0].name
    assert stored[0].resolve().parent == store


def test_internal_card_filenames_do_not_alias_distinct_exact_ids(tmp_path):
    p = _internal(tmp_path)
    ids = ["a/b", "a?b", "Card", "card"]
    for index, card_id in enumerate(ids):
        p.upsert_card(card_id, {"value": index})

    stored = list((tmp_path / "boards" / "b1").glob("*.json"))
    assert len(stored) == len(ids)
    assert len({path.name.casefold() for path in stored}) == len(ids)
    assert {card["card_id"] for card in p.list_cards()} == set(ids)


def test_internal_reads_legacy_card_path_without_deleting_it(tmp_path):
    p = _internal(tmp_path)
    p.store_dir.mkdir(parents=True)
    legacy = p.store_dir / "legacy_id.json"
    legacy.write_text(
        json.dumps({"card_id": "legacy/id", "value": "retained"}),
        encoding="utf-8",
    )

    assert p._read_fields("legacy/id")["value"] == "retained"
    p.upsert_card("legacy/id", {"new": True})
    assert legacy.is_file()
    assert p._read_fields("legacy/id") == {
        "card_id": "legacy/id", "value": "retained", "new": True,
    }


def test_internal_fieldless_card_surfaces_with_none_status(tmp_path):
    p = _internal(tmp_path)
    p.upsert_card("c-orphan", {"company": "NoEventsYet"})
    cards = p.list_cards()
    assert cards[0]["card_id"] == "c-orphan" and cards[0]["status"] is None
