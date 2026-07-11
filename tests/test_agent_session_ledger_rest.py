"""Ledger REST agent-session endpoints, exercised live via FastAPI's TestClient —
no Docker. Mirrors tests/test_ledger_rest.py's fixture pattern exactly.

Proves the running Ledger surface durably stores agent sessions/events in the one
ledger.db: sequence numbers are assigned by the server (never trusted from the
caller), events_since is exactly the reconnect gap, unknown sessions 404, and a
second app instance opened against the SAME db file recovers everything (restart
recovery — the actual production concern this whole layer exists for).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "services/ledger/app.py"


def _load_app(db_path):
    import os
    os.environ["LEDGER_DB"] = str(db_path)
    spec = importlib.util.spec_from_file_location("ledger_app_agent_sessions", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ledger(tmp_path):
    db = tmp_path / "ledger.db"
    mod = _load_app(db)
    from starlette.testclient import TestClient
    return TestClient(mod.app), mod, db


def _create(client, **overrides):
    body = {"harness": "fake", "conversation_id": "c1", "repo_id": "llm_station"}
    body.update(overrides)
    return client.post("/agent-session", json=body)


def test_create_and_get(ledger):
    client, _, _ = ledger
    r = _create(client)
    assert r.status_code == 200
    session_id = r.json()["session_id"]
    assert session_id.startswith("AS-")
    assert r.json()["status"] == "starting"

    g = client.get(f"/agent-session/{session_id}")
    assert g.status_code == 200
    assert g.json()["conversation_id"] == "c1"


def test_unknown_session_404s_on_every_route(ledger):
    client, _, _ = ledger
    assert client.get("/agent-session/AS-nope").status_code == 404
    assert client.post("/agent-session/AS-nope/event",
                       json={"type": "usage", "payload": {}}).status_code == 404
    assert client.get("/agent-session/AS-nope/events").status_code == 404
    assert client.post("/agent-session/AS-nope/status",
                       json={"status": "active"}).status_code == 404


def test_event_sequence_is_server_assigned_and_monotonic(ledger):
    client, _, _ = ledger
    session_id = _create(client).json()["session_id"]

    r1 = client.post(f"/agent-session/{session_id}/event",
                     json={"type": "session_started", "payload": {}})
    r2 = client.post(f"/agent-session/{session_id}/event",
                     json={"type": "assistant_message", "payload": {"text": "hi"}})
    assert r1.json()["sequence"] == 1
    assert r2.json()["sequence"] == 2

    session = client.get(f"/agent-session/{session_id}").json()
    assert session["last_event_sequence"] == 2


def test_events_since_reconnect_returns_only_the_gap(ledger):
    client, _, _ = ledger
    session_id = _create(client).json()["session_id"]
    client.post(f"/agent-session/{session_id}/event",
               json={"type": "session_started", "payload": {}})
    client.post(f"/agent-session/{session_id}/event",
               json={"type": "assistant_message", "payload": {}})
    client.post(f"/agent-session/{session_id}/event",
               json={"type": "session_idle", "payload": {}})

    all_events = client.get(f"/agent-session/{session_id}/events").json()
    assert [e["sequence"] for e in all_events] == [1, 2, 3]

    since_1 = client.get(f"/agent-session/{session_id}/events",
                         params={"after_sequence": 1}).json()
    assert [e["sequence"] for e in since_1] == [2, 3]


def test_event_payload_round_trips_as_a_real_object_not_a_json_string(ledger):
    client, _, _ = ledger
    session_id = _create(client).json()["session_id"]
    client.post(f"/agent-session/{session_id}/event",
               json={"type": "assistant_message",
                     "payload": {"text": "hello", "tokens": 3}})
    events = client.get(f"/agent-session/{session_id}/events").json()
    assert events[0]["payload"] == {"text": "hello", "tokens": 3}
    assert isinstance(events[0]["payload"], dict)   # not a double-encoded string


def test_status_update_persists(ledger):
    client, _, _ = ledger
    session_id = _create(client).json()["session_id"]
    r = client.post(f"/agent-session/{session_id}/status", json={"status": "active"})
    assert r.status_code == 200
    assert client.get(f"/agent-session/{session_id}").json()["status"] == "active"


def test_list_agent_sessions_filters_by_status(ledger):
    client, _, _ = ledger
    s1 = _create(client, conversation_id="c1").json()["session_id"]
    s2 = _create(client, conversation_id="c2").json()["session_id"]
    client.post(f"/agent-session/{s1}/status", json={"status": "active"})

    active = client.get("/agent-sessions", params={"status": "active"}).json()
    assert [s["session_id"] for s in active] == [s1]
    all_sessions = client.get("/agent-sessions").json()
    assert {s["session_id"] for s in all_sessions} == {s1, s2}


def test_restart_recovery_survives_a_new_app_instance_on_the_same_db(tmp_path):
    """The actual production concern: the worker process restarts, opens a NEW
    Ledger app instance against the SAME db file, and every session/event must
    still be there — including the correct next sequence number, not a reset."""
    db = tmp_path / "ledger.db"
    from starlette.testclient import TestClient

    mod1 = _load_app(db)
    client1 = TestClient(mod1.app)
    session_id = _create(client1).json()["session_id"]
    client1.post(f"/agent-session/{session_id}/event",
                json={"type": "session_started", "payload": {}})

    # simulate a full process restart: a brand new app import against the same file
    mod2 = _load_app(db)
    client2 = TestClient(mod2.app)
    recovered = client2.get(f"/agent-session/{session_id}").json()
    assert recovered["conversation_id"] == "c1"
    assert recovered["last_event_sequence"] == 1

    r2 = client2.post(f"/agent-session/{session_id}/event",
                      json={"type": "session_idle", "payload": {}})
    assert r2.json()["sequence"] == 2   # continues, does not reset to 1
