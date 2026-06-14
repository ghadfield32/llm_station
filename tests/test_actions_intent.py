"""Phase 2 of the agent kanban surface: intent verbs + title addressing.

Hermetic — `actions._rows` and `actions.client` are monkeypatched, so no live
AppFlowy. Verifies each verb maps to the right canonical column, fuzzy addressing
resolves close titles, a non-match returns candidates (never a silent best-guess),
and the generic `set_status` is no longer an agent-facing tool.
"""
import sys
from pathlib import Path

import pytest

GROWTHOS = Path(__file__).resolve().parents[1] / "appflowy_kanban" / "growth-os"
sys.path.insert(0, str(GROWTHOS))

from growthos import actions  # noqa: E402


class _FakeClient:
    def __init__(self):
        self.calls: list[tuple[str, list[dict]]] = []

    def upsert(self, db, rows):
        self.calls.append((db, rows))
        return rows


@pytest.fixture
def fake(monkeypatch):
    fc = _FakeClient()
    monkeypatch.setattr(actions, "client", lambda: fc)
    return fc


def _rows(monkeypatch, rows):
    monkeypatch.setattr(actions, "_rows", lambda db: rows)


def test_stage_card_maps_to_ready(fake, monkeypatch):
    _rows(monkeypatch, [{"Name": "Fix flaky test",
                         "CardKey": "card-fix flaky test", "Status": "Backlog"}])
    out = actions.stage_card("Fix flaky test")
    assert "-> Ready" in out
    db, rows = fake.calls[-1]
    assert db == "mission_intake"
    assert rows[0]["pre_hash"] == "card-fix flaky test"
    assert rows[0]["cells"]["Status"] == "Ready"


def test_block_card_records_reason_clobber_safe(fake, monkeypatch):
    _rows(monkeypatch, [{"Name": "Deploy", "CardKey": "card-deploy",
                         "Status": "Ready", "Notes": "prior note"}])
    out = actions.block_card("Deploy", reason="waiting on infra")
    cells = fake.calls[-1][1][0]["cells"]
    assert cells["Status"] == "Blocked"
    # appends, never clobbers the existing human note
    assert "prior note" in cells["Notes"] and "waiting on infra" in cells["Notes"]
    assert "noted:" in out


def test_fuzzy_resolves_a_close_title(fake, monkeypatch):
    _rows(monkeypatch, [{"Name": "Refactor the ledger",
                         "CardKey": "card-refactor the ledger", "Status": "Backlog"}])
    out = actions.stage_card("refactor ledger")   # close, not exact
    assert "-> Ready" in out


def test_no_match_returns_candidates_and_writes_nothing(fake, monkeypatch):
    _rows(monkeypatch, [
        {"Name": "Alpha one", "CardKey": "card-alpha one", "Status": "Backlog"},
        {"Name": "Zeta nine", "CardKey": "card-zeta nine", "Status": "Backlog"}])
    out = actions.stage_card("something completely unrelated")
    assert "no confident match" in out and "candidates:" in out
    assert fake.calls == []   # a non-match never mutates the board


def test_start_then_finish_todo(fake, monkeypatch):
    _rows(monkeypatch, [{"Name": "Write docs", "Status": "Todo"}])
    actions.start_todo("Write docs")
    last = fake.calls[-1][1][0]
    assert last["cells"]["Status"] == "In Progress"
    assert last["pre_hash"] == "todo-write docs"
    actions.finish_todo("Write docs")
    assert fake.calls[-1][1][0]["cells"]["Status"] == "Done"


def test_move_item_triages_an_inbox_by_title(fake, monkeypatch):
    """Restores the agent's ability to act on the long-tail boards (papers/repos/
    signals/library/lessons) that lost set_status — title-addressed, key owned by
    the harness (papers key = ArxivID)."""
    _rows(monkeypatch, [{"Name": "Attention paper", "ArxivID": "2401.00001",
                         "Status": "Inbox"}])
    actions.move_item("papers", "Attention paper", "Archived")
    db, rows = fake.calls[-1]
    assert db == "papers"
    assert rows[0]["pre_hash"] == "2401.00001"
    assert rows[0]["cells"]["Status"] == "Archived"


def test_move_item_rejects_invalid_status_loudly(fake, monkeypatch):
    _rows(monkeypatch, [{"Name": "X", "ArxivID": "1", "Status": "Inbox"}])
    out = actions.move_item("papers", "X", "Bogus")
    assert "invalid status" in out and fake.calls == []


def test_move_item_refuses_approved_and_unknown_board(fake):
    assert "human-only" in actions.move_item("mission_intake", "x", "Approved")
    assert "unknown board" in actions.move_item("nope", "x", "y")
    assert fake.calls == []


def test_board_view_groups_every_row_by_status(monkeypatch):
    _rows(monkeypatch, [
        {"Name": "p1", "Status": "Inbox", "Score": "9"},
        {"Name": "p2", "Status": "Read", "Score": "3"},
        {"Name": "p3", "Status": "Inbox", "Score": "5"}])
    view = actions.board_view("papers")
    assert view["board"] == "papers"
    cols = {c["name"]: c["cards"] for c in view["columns"]}
    assert len(cols["Inbox"]) == 2 and len(cols["Read"]) == 1
    assert cols["Inbox"][0]["meta"] == "9"   # Score is the papers meta


def test_board_view_unknown_board_is_error():
    assert "error" in actions.board_view("nope")


def test_all_boards_json_reads_each_and_is_per_board_failloud(monkeypatch):
    from command_center.channels.board_state import all_boards_json
    monkeypatch.setattr(actions, "_rows",
                        lambda db: [{"Name": "x", "Status": "Inbox"}])
    out = {b["board"]: b for b in all_boards_json(["papers", "todos"])}
    assert "columns" in out["papers"] and "columns" in out["todos"]


def test_set_status_dropped_from_agent_tools_but_verbs_present():
    from growthos.assistant import TOOL_FNS
    names = {f.__name__ for f in TOOL_FNS}
    assert "set_status" not in names
    assert {"stage_card", "block_card", "reject_card",
            "start_todo", "finish_todo", "block_todo"} <= names


def test_read_item_returns_full_nonempty_fields(monkeypatch):
    """read_item lets the bot actually understand a paper/repo: it returns every
    non-empty field of the matched row (abstract included, untruncated), drops
    blanks, and matches the title case-insensitively."""
    _rows(monkeypatch, [{
        "Name": "Attention Is All You Need", "Status": "Inbox",
        "Abstract": "We propose the Transformer, a model based on attention.",
        "Score": "9.1", "Suggested": "useful for betts_basketball",
        "URL": "http://arxiv.org/abs/1706.03762", "Notes": ""}])
    out = actions.read_item("papers", "attention is all you need")  # case-insensitive
    assert out["Abstract"].startswith("We propose the Transformer")
    assert out["Score"] == "9.1" and out["Suggested"].startswith("useful for")
    assert out["Name"] == "Attention Is All You Need"
    assert "Notes" not in out               # empty fields are dropped, not faked


def test_read_item_miss_returns_candidates_not_a_guess(monkeypatch):
    _rows(monkeypatch, [{"Name": "Graph neural networks", "Status": "Inbox"},
                        {"Name": "Diffusion models survey", "Status": "Inbox"}])
    out = actions.read_item("papers", "something entirely unrelated zzz")
    assert isinstance(out, str)
    assert "no item titled" in out and "closest:" in out


def test_read_item_unknown_board_is_loud(monkeypatch):
    out = actions.read_item("nope", "x")
    assert "unknown board" in out


def test_read_item_is_an_agent_tool():
    from growthos.assistant import TOOL_FNS
    assert "read_item" in {f.__name__ for f in TOOL_FNS}


def test_read_item_supports_notes_board(monkeypatch):
    """notes has rows but no Status workflow (so it's absent from STATUSES);
    read_item still reads it — its valid set is STATUSES + notes."""
    assert "notes" in actions.READABLE_DBS
    _rows(monkeypatch, [{"Name": "Standup ideas", "Tags": "work",
                         "Updated": "2026-06-13"}])
    out = actions.read_item("notes", "standup ideas")   # case-insensitive
    assert out["Name"] == "Standup ideas" and out["Tags"] == "work"


def test_declared_contract_matches_growthos_reality(fake, monkeypatch):
    """The command_center-side VERB_COLUMN / BOARD_STATUSES declarations (used by
    the kanban gate) must match what growthos.actions actually does — otherwise the
    gate would validate a fiction. This is the anti-drift cross-check."""
    from command_center.kanban.metrics import BOARD_STATUSES, VERB_COLUMN
    assert BOARD_STATUSES["mission_intake"] == actions.STATUSES["mission_intake"]
    assert BOARD_STATUSES["todos"] == actions.STATUSES["todos"]
    callers = {
        "stage_card": actions.stage_card, "block_card": actions.block_card,
        "reject_card": actions.reject_card, "start_todo": actions.start_todo,
        "finish_todo": actions.finish_todo, "block_todo": actions.block_todo,
    }
    for verb, (board, column) in VERB_COLUMN.items():
        _rows(monkeypatch, [{"Name": "Row", "CardKey": "card-row", "Status": "Backlog"}])
        callers[verb]("Row")
        db, rows = fake.calls[-1]
        assert db == board and rows[0]["cells"]["Status"] == column
