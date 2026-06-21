"""Kanban event emission is the STANDARD path: on by default, opt-out via =0."""
from __future__ import annotations

import pytest

from command_center.channels import core


@pytest.fixture
def board(monkeypatch):
    """Force a resolvable single board, isolating the flag logic from the registry."""
    monkeypatch.setattr(core, "_resolve_primary_board",
                        lambda env: env.get("KANBAN_PRIMARY_BOARD_ID") or "the_board")
    return "the_board"


@pytest.fixture
def no_board(monkeypatch):
    monkeypatch.setattr(core, "_resolve_primary_board",
                        lambda env: env.get("KANBAN_PRIMARY_BOARD_ID") or None)


def test_emission_on_by_default_when_board_resolves(board):
    st = core.kanban_emission_status({})          # no flag at all
    assert st["active"] is True and st["board_id"] == "the_board"


def test_explicit_opt_out_disables(board):
    st = core.kanban_emission_status({"KANBAN_EMIT_EVENTS": "0"})
    assert st["active"] is False and "KANBAN_EMIT_EVENTS=0" in st["reason"]


def test_default_inactive_when_no_board_but_does_not_crash(no_board):
    st = core.kanban_emission_status({})          # default + ambiguous board
    assert st["active"] is False
    assert "KANBAN_PRIMARY_BOARD_ID" in st["reason"]
    assert not st.get("explicit_unsatisfiable")   # default never forces a raise


def test_explicit_on_without_board_is_loud(no_board):
    st = core.kanban_emission_status({"KANBAN_EMIT_EVENTS": "1"})
    assert st["active"] is False and st["explicit_unsatisfiable"] is True


def test_wire_dispatch_emits_by_default(board, monkeypatch, tmp_path):
    # _wire_kanban_events wraps governed verbs with NO flag set (default-on)
    monkeypatch.setattr(core, "env", lambda: {"KANBAN_EVENT_LOG": str(tmp_path / "e.jsonl")})
    raw = {"stage_card": lambda title: "ok", "search": lambda q: q}
    wired = core._wire_kanban_events(dict(raw), surface="discord")
    assert wired["stage_card"] is not raw["stage_card"]   # governed verb wrapped
    assert wired["search"] is raw["search"]               # non-governed untouched


def test_wire_dispatch_off_when_opted_out(board, monkeypatch):
    monkeypatch.setattr(core, "env", lambda: {"KANBAN_EMIT_EVENTS": "0"})
    raw = {"stage_card": lambda title: "ok"}
    assert core._wire_kanban_events(dict(raw), surface="discord")["stage_card"] is raw["stage_card"]
