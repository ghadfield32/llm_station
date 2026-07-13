"""GatewayCore 'Track as mission' — promote a plain conversation (no agent
session) to a Ledger tracking mission so the conversation becomes monitorable,
without losing context and without granting writes.

Same INERT mission contract as the agent-session promote (L0 / no approval / no
branch). Hermetic: httpx.post is monkeypatched to capture the Ledger calls; no
worker, no real Ledger.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("ledger error", request=None, response=None)


def _load(monkeypatch):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_chatpromote_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_chatpromote_test"] = mod
    spec.loader.exec_module(mod)
    return mod, TestClient(mod.app)


def _capture_ledger(monkeypatch, mod, *, mission_id="T-def67890", fail=False):
    captured: list[tuple] = []

    def fake_post(url, json=None, timeout=None):        # noqa: A002 (mirror httpx sig)
        captured.append((url, json))
        if fail:
            raise httpx.ConnectError("simulated: ledger unreachable")
        if url.endswith("/mission"):
            return _Resp(200, {"id": mission_id, "status": "open"})
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    return captured


def test_gateway_promote_creates_inert_mission_and_links_conversation(monkeypatch):
    mod, tc = _load(monkeypatch)
    captured = _capture_ledger(monkeypatch, mod)

    r = tc.post("/api/chat/promote",
                json={"conversation_id": "chat-abc", "summary": "why did the DAG fail?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mission_id"] == "T-def67890"
    assert body["conversation_id"] == "chat-abc"

    assert len(captured) == 2
    (mission_url, mission_body), (event_url, event_body) = captured
    # inert: read-only, no approval wall, no branch to execute
    assert mission_url.endswith("/mission")
    assert mission_body["risk"] == "L0"
    assert mission_body["requires_approval"] is False
    assert mission_body["branch"] == ""
    assert "why did the DAG fail?" in mission_body["action"]
    # link event carries the conversation, not a session
    assert event_url.endswith("/mission/T-def67890/event")
    assert event_body["payload"]["conversation_id"] == "chat-abc"
    assert event_body["payload"]["event"] == "chat_conversation_link"


def test_gateway_promote_requires_conversation_id(monkeypatch):
    mod, tc = _load(monkeypatch)
    _capture_ledger(monkeypatch, mod)
    r = tc.post("/api/chat/promote", json={"conversation_id": "  "})
    assert r.status_code == 400


def test_gateway_promote_surfaces_ledger_failure_as_502(monkeypatch):
    mod, tc = _load(monkeypatch)
    _capture_ledger(monkeypatch, mod, fail=True)
    r = tc.post("/api/chat/promote", json={"conversation_id": "chat-abc"})
    assert r.status_code == 502


# --- frontend guardrail (source-level) -------------------------------------------

APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"


def test_frontend_shows_mission_journey_inline_and_gateway_promote():
    src = APP_TSX.read_text(encoding="utf-8")
    # the shared "conversation is the mission journey" strip exists and is used
    assert "function MissionProgressStrip" in src
    assert "<MissionProgressStrip" in src
    # GatewayCore chats can be promoted (reusing the thread) via promoteChat
    assert "promoteChat(" in src
    assert "async function promoteGatewayChat" in src
