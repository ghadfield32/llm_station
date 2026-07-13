"""'Track as mission' promotion route — the OPTIONAL governance/tracking wrapper.

Contract under test (the whole point of the seam):
  - it records an EXISTING read-only agent session as a Ledger mission WITHOUT
    restarting it — it must never call create_session/start_session;
  - the mission it opens is INERT: L0 (read-only), requires_approval=False, and
    NO branch — so nothing executes it and no write capability is granted;
  - it links the session to the mission via the append-only event log;
  - it is feature-gated (503 when agent sessions are off) and surfaces a Ledger
    failure as 502.

Hermetic: a fake AgentWorkerClient supplies the durable session (no worker);
httpx.post is monkeypatched to capture the Ledger calls (no real Ledger).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"

SESSION = {"session_id": "AS-7", "repo_id": "llm_station",
           "conversation_id": "chat-123", "harness": "claude_code_local",
           "status": "idle"}


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


class _FakeWorker:
    """Only the surface the promote route touches. Records every call so the
    test can prove create_session was never reached."""

    def __init__(self, session):
        self._session = session
        self.calls: list[tuple] = []

    def get_session(self, session_id):
        self.calls.append(("get_session", session_id))
        return _Resp(200, self._session)

    def create_session(self, body):          # must NOT be called by promote
        self.calls.append(("create_session", body))
        raise AssertionError("promote restarted/duplicated the session")


def _load(monkeypatch, *, enabled=True):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_promote_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_promote_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "AGENT_SESSIONS_ENABLED", enabled)
    monkeypatch.setattr(mod, "AGENT_WORKER_TOKEN", "irrelevant")
    return mod, TestClient(mod.app)


def _capture_ledger(monkeypatch, mod, *, mission_id="T-abc12345", fail=False):
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


def test_promote_creates_inert_tracking_mission_and_links_session(monkeypatch):
    mod, tc = _load(monkeypatch)
    worker = _FakeWorker(SESSION)
    mod._agent_worker_client = worker
    captured = _capture_ledger(monkeypatch, mod)

    r = tc.post("/api/agent-sessions/AS-7/promote", json={"summary": "look into the flaky test"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mission_id"] == "T-abc12345"
    assert body["session_id"] == "AS-7"
    assert body["conversation_id"] == "chat-123"

    # the session was reused, never recreated/restarted
    assert ("get_session", "AS-7") in worker.calls
    assert not any(c[0] == "create_session" for c in worker.calls)

    # exactly two Ledger writes: open mission, then link event
    assert len(captured) == 2
    (mission_url, mission_body), (event_url, event_body) = captured

    # the mission is INERT: read-only, no approval wall, no branch to execute
    assert mission_url.endswith("/mission")
    assert mission_body["risk"] == "L0"
    assert mission_body["requires_approval"] is False
    assert mission_body["branch"] == ""
    assert mission_body["repo"] == "llm_station"
    assert "look into the flaky test" in mission_body["action"]

    # the link event ties the EXISTING session to the mission
    assert event_url.endswith("/mission/T-abc12345/event")
    assert event_body["kind"] == "note"
    assert event_body["payload"]["session_id"] == "AS-7"
    assert event_body["payload"]["conversation_id"] == "chat-123"
    assert event_body["payload"]["event"] == "agent_session_link"


def test_promote_default_summary_when_none_given(monkeypatch):
    mod, tc = _load(monkeypatch)
    mod._agent_worker_client = _FakeWorker(SESSION)
    captured = _capture_ledger(monkeypatch, mod)

    r = tc.post("/api/agent-sessions/AS-7/promote", json={})
    assert r.status_code == 200
    mission_body = captured[0][1]
    assert "AS-7" in mission_body["action"]      # falls back to a session-referencing action


def test_promote_is_503_when_agent_sessions_disabled(monkeypatch):
    mod, tc = _load(monkeypatch, enabled=False)
    # no Ledger patch needed — must 503 before any Ledger call
    r = tc.post("/api/agent-sessions/AS-7/promote", json={})
    assert r.status_code == 503


def test_promote_surfaces_ledger_failure_as_502(monkeypatch):
    mod, tc = _load(monkeypatch)
    mod._agent_worker_client = _FakeWorker(SESSION)
    _capture_ledger(monkeypatch, mod, fail=True)
    r = tc.post("/api/agent-sessions/AS-7/promote", json={})
    assert r.status_code == 502


# --- frontend guardrail (source-level) -------------------------------------------

APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"


def test_frontend_exposes_track_as_mission_reusing_the_session():
    src = APP_TSX.read_text(encoding="utf-8")
    # the button + the promote call exist in the agent session panel
    assert "track as mission" in src
    assert "promoteAgentSession(" in src
    # promotion records the mission id back on the thread (governance wrapper)
    assert "missionId" in src
    # there is a dedicated promote handler (distinct from session creation); the
    # backend test proves it never restarts the session — here we just pin the wiring
    assert "async function doPromote" in src
    # the promote handler calls promoteAgentSession, not the create path
    handler = src.split("async function doPromote", 1)[1][:400]
    assert "promoteAgentSession(" in handler
    assert "createSession(" not in handler
