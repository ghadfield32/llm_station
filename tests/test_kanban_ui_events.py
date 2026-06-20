"""Internal UI receives board events from the same event log (live sync, Level 1)."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from command_center.kanban_sync import EventLog, emit_event

APP = Path(__file__).resolve().parents[1] / "services" / "agent_kanban_ui" / "app.py"
NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ui(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    log_path = tmp_path / "kanban-events.jsonl"
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_events_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_events_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "KANBAN_EVENT_LOG", log_path)
    return mod, TestClient(mod.app), EventLog(log_path)


def _sse_data(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in text.splitlines()
            if line.startswith("data: ")]


def test_discord_staged_card_shows_in_ui_snapshot_and_stream(ui):
    _mod, tc, log = ui
    # a governed action on Discord emits ONE event into the shared log
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="discord", status_before="Backlog",
               status_after="Ready", now=NOW)

    # the internal UI renders it from the same log — no separate authority
    snap = tc.get("/api/events/kanban/snapshot").json()
    assert snap["cards"]["c1"]["status"] == "Ready"

    stream = tc.get("/api/events/kanban?since=0")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    events = _sse_data(stream.text)
    staged = [e for e in events if e.get("event_type") == "kanban.card.staged"]
    assert staged and staged[0]["source_surface"] == "discord"
    # a cursor is emitted so the EventSource reconnects for the next batch
    assert any(e.get("next") == 1 for e in events)


def test_stream_since_cursor_only_returns_new_events(ui):
    _mod, tc, log = ui
    emit_event(log, action="add_mission_card", board_id="b1", card_id="c1",
               source_surface="internal_ui", status_after="Backlog", now=NOW)
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="sms", status_after="Ready", now=NOW)
    # subscribing from cursor 1 returns only the second (SMS) event
    events = _sse_data(tc.get("/api/events/kanban?since=1").text)
    card_events = [e for e in events if "event_type" in e]
    assert len(card_events) == 1
    assert card_events[0]["source_surface"] == "sms"


def _sse_ids(text: str) -> list[str]:
    return [line[len("id: "):] for line in text.splitlines() if line.startswith("id: ")]


def test_eventsource_resumes_via_last_event_id_no_replay(ui):
    """Each frame carries id:<offset>; reconnect with Last-Event-ID gets only new."""
    _mod, tc, log = ui
    emit_event(log, action="add_mission_card", board_id="b1", card_id="c1",
               source_surface="internal_ui", status_after="Backlog", now=NOW)
    first = tc.get("/api/events/kanban")
    ids = _sse_ids(first.text)
    assert ids[0] == "1"  # resume-after offset for the first event

    # a new event arrives; the browser reconnects with its Last-Event-ID
    emit_event(log, action="stage_card", board_id="b1", card_id="c1",
               source_surface="sms", status_after="Ready", now=NOW)
    again = tc.get("/api/events/kanban", headers={"Last-Event-ID": ids[0]})
    card_events = [e for e in _sse_data(again.text) if "event_type" in e]
    assert len(card_events) == 1 and card_events[0]["source_surface"] == "sms"
