"""The governed action layer funnels through emit_event (one writer, all surfaces)."""
from __future__ import annotations

import pytest

from command_center.kanban_sync import EventLog, wrap_governed_dispatch


def _log(tmp_path):
    return EventLog(tmp_path / "kanban-events.jsonl")


def test_governed_verbs_emit_events_others_pass_through(tmp_path):
    log = _log(tmp_path)
    seen = []
    raw = {"stage_card": lambda title: seen.append(("stage", title)) or "ok",
           "finish_todo": lambda task: seen.append(("finish", task)) or "ok",
           "search": lambda q: q}
    d = wrap_governed_dispatch(raw, surface="discord", board_id="b1", log=log)

    assert d["stage_card"](title="Card A") == "ok"     # real verb still runs
    assert d["finish_todo"](task="Todo B") == "ok"
    assert d["search"]("hello") == "hello"             # non-governed untouched
    assert d["search"] is raw["search"]

    events = log.read()
    assert [(e.source_surface, e.action, e.card_id, e.status_after) for e in events] == [
        ("discord", "stage_card", "Card A", "Ready"),
        ("discord", "finish_todo", "Todo B", "Done"),
    ]
    assert seen == [("stage", "Card A"), ("finish", "Todo B")]  # the real verb ran too


def test_app_surface_maps_to_internal_ui(tmp_path):
    log = _log(tmp_path)
    d = wrap_governed_dispatch({"stage_card": lambda title: "ok"},
                               surface="app", board_id="b1", log=log)
    d["stage_card"](title="C")
    assert log.read()[0].source_surface == "internal_ui"


def test_unresolvable_surface_or_board_leaves_dispatch_untouched(tmp_path):
    log = _log(tmp_path)
    raw = {"stage_card": lambda title: "ok"}
    assert wrap_governed_dispatch(raw, surface="weird", board_id="b1", log=log) is raw
    assert wrap_governed_dispatch(raw, surface="discord", board_id=None, log=log) is raw
    assert log.read() == []  # nothing emitted when it can't be tagged honestly


def test_failed_verb_emits_nothing(tmp_path):
    log = _log(tmp_path)
    def boom(title):
        raise RuntimeError("verb failed")
    d = wrap_governed_dispatch({"stage_card": boom}, surface="discord",
                               board_id="b1", log=log)
    with pytest.raises(RuntimeError):
        d["stage_card"](title="C")
    assert log.read() == []  # no event for a failed action — failure is preserved
