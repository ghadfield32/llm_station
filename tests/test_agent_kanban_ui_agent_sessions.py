"""Cockpit agent-session proxy: disabled-mode 503, worker-unreachable 502,
worker 404/409/400 preserved as-is, the worker token never appears in any
response, GatewayCore is never constructed by these routes, Fake Agent stays
filtered/blocked unless explicitly enabled, and the browser-facing SSE stream
emits ordered events with correct reconnect/heartbeat behavior.

Hermetic: every test injects a fake AgentWorkerClient (no real worker process,
no real network) via the module's _agent_worker_client cache slot.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location(
        "agent_kanban_ui_agent_sessions_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_agent_sessions_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "AGENT_SESSIONS_ENABLED", True)
    monkeypatch.setattr(mod, "AGENT_WORKER_TOKEN", "irrelevant-since-client-is-injected")
    return mod, TestClient(mod.app)


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class _FakeWorkerClient:
    """Stub satisfying AgentWorkerClient's public surface — no real worker
    process, no real network. `responses` maps method name -> _FakeResponse;
    a missing key falls back to a generic 200/{}."""

    def __init__(self, responses: dict | None = None, unavailable: bool = False):
        self._responses = responses or {}
        self._unavailable = unavailable
        self.calls: list[tuple] = []

    def _resp(self, key: str, *args):
        self.calls.append((key, *args))
        if self._unavailable:
            from agent_worker_client import AgentWorkerUnavailable
            raise AgentWorkerUnavailable("simulated: connection refused")
        return self._responses.get(key, _FakeResponse(200, {}))

    def list_harnesses(self):
        return self._resp("list_harnesses")

    def create_session(self, body):
        return self._resp("create_session", body)

    def get_session(self, session_id):
        return self._resp("get_session", session_id)

    def send_message(self, session_id, prompt):
        return self._resp("send_message", session_id, prompt)

    def get_events(self, session_id, after_sequence=0):
        return self._resp("get_events", session_id, after_sequence)

    def resolve_approval(self, session_id, approval_id, *, approved, reason=""):
        return self._resp("resolve_approval", session_id, approval_id, approved, reason)

    def interrupt(self, session_id):
        return self._resp("interrupt", session_id)

    def resume(self, session_id):
        return self._resp("resume", session_id)

    def close_session(self, session_id):
        return self._resp("close_session", session_id)


def _inject(mod, fake_client) -> None:
    mod._agent_worker_client = fake_client


# ── disabled / unreachable / status-preservation ────────────────────────────

def test_agent_sessions_disabled_by_default_is_503():
    """A SEPARATE client fixture that does NOT enable AGENT_SESSIONS_ENABLED —
    the real default-off behavior every write-capable surface in this cockpit
    follows."""
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location(
        "agent_kanban_ui_agent_sessions_disabled_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_agent_sessions_disabled_test"] = mod
    spec.loader.exec_module(mod)
    tc = TestClient(mod.app)

    assert tc.get("/api/agent-harnesses").status_code == 503
    assert tc.post("/api/agent-sessions", json={
        "conversation_id": "c1", "repo_id": "r", "mode": "analysis"}
    ).status_code == 503


def test_worker_unreachable_is_502(client):
    mod, tc = client
    _inject(mod, _FakeWorkerClient(unavailable=True))
    r = tc.get("/api/agent-sessions/AS-1")
    assert r.status_code == 502


def test_worker_404_is_preserved(client):
    mod, tc = client
    _inject(mod, _FakeWorkerClient({
        "get_session": _FakeResponse(404, {"detail": "no such agent session: 'AS-nope'"})}))
    r = tc.get("/api/agent-sessions/AS-nope")
    assert r.status_code == 404
    assert "no such agent session" in r.json()["detail"]


def test_worker_409_is_preserved(client):
    mod, tc = client
    _inject(mod, _FakeWorkerClient({
        "resolve_approval": _FakeResponse(409, {"detail": "already resolved"})}))
    r = tc.post("/api/agent-sessions/AS-1/approvals/APR-1",
               json={"approved": True})
    assert r.status_code == 409
    assert r.json()["detail"] == "already resolved"


def test_worker_400_is_preserved(client):
    mod, tc = client
    _inject(mod, _FakeWorkerClient({
        "send_message": _FakeResponse(400, {"detail": "session 'AS-1' is closed"})}))
    r = tc.post("/api/agent-sessions/AS-1/messages", json={"prompt": "hi"})
    assert r.status_code == 400
    assert "is closed" in r.json()["detail"]


def test_send_message_success_returns_202(client):
    mod, tc = client
    _inject(mod, _FakeWorkerClient({
        "send_message": _FakeResponse(202, {"session_id": "AS-1", "status": "accepted"})}))
    r = tc.post("/api/agent-sessions/AS-1/messages", json={"prompt": "hi"})
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"


# ── token never leaks ────────────────────────────────────────────────────────

def test_worker_token_never_appears_in_any_response(client, monkeypatch):
    mod, tc = client
    secret = "sk-agent-worker-super-secret-value"
    monkeypatch.setattr(mod, "AGENT_WORKER_TOKEN", secret)
    _inject(mod, _FakeWorkerClient({"list_harnesses": _FakeResponse(200, [])}))

    for r in (
        tc.get("/api/agent-harnesses"),
        tc.get("/api/debug/runtime"),
        tc.get("/api/status"),
    ):
        assert secret not in r.text


# ── Fake Agent gating ────────────────────────────────────────────────────────

def test_fake_harness_filtered_out_of_the_list_when_disabled(client):
    mod, tc = client
    _inject(mod, _FakeWorkerClient({"list_harnesses": _FakeResponse(200, [
        {"harness_id": "fake", "available": True},
        {"harness_id": "codex_agent", "available": False},
    ])}))
    r = tc.get("/api/agent-harnesses")
    ids = {h["harness_id"] for h in r.json()}
    assert ids == {"codex_agent"}


def test_fake_harness_visible_when_explicitly_enabled(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "FAKE_AGENT_ENABLED", True)
    _inject(mod, _FakeWorkerClient({"list_harnesses": _FakeResponse(200, [
        {"harness_id": "fake", "available": True},
    ])}))
    r = tc.get("/api/agent-harnesses")
    assert {h["harness_id"] for h in r.json()} == {"fake"}


def test_create_session_with_fake_harness_is_403_when_disabled(client):
    mod, tc = client
    _inject(mod, _FakeWorkerClient())
    r = tc.post("/api/agent-sessions", json={
        "harness_id": "fake", "conversation_id": "c1", "repo_id": "r",
        "mode": "analysis"})
    assert r.status_code == 403


def test_create_session_with_fake_harness_succeeds_when_enabled(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "FAKE_AGENT_ENABLED", True)
    _inject(mod, _FakeWorkerClient({
        "create_session": _FakeResponse(200, {"session_id": "AS-1"})}))
    r = tc.post("/api/agent-sessions", json={
        "harness_id": "fake", "conversation_id": "c1", "repo_id": "r",
        "mode": "analysis"})
    assert r.status_code == 200


# ── GatewayCore isolation ────────────────────────────────────────────────────

def test_gatewaycore_is_never_constructed_by_agent_routes(client, monkeypatch):
    mod, tc = client

    def _forbidden(*a, **k):
        raise AssertionError("GatewayCore must never be constructed by an "
                             "agent-session route")

    monkeypatch.setattr(mod, "_get_core", _forbidden)
    _inject(mod, _FakeWorkerClient({
        "list_harnesses": _FakeResponse(200, []),
        "create_session": _FakeResponse(200, {"session_id": "AS-1"}),
        "send_message": _FakeResponse(202, {"status": "accepted"}),
        "get_events": _FakeResponse(200, []),
    }))

    tc.get("/api/agent-harnesses")
    tc.post("/api/agent-sessions", json={
        "conversation_id": "c1", "repo_id": "r", "mode": "analysis"})
    tc.post("/api/agent-sessions/AS-1/messages", json={"prompt": "hi"})
    tc.get("/api/agent-sessions/AS-1/events")
    # no AssertionError raised above means _get_core was never called


# ── SSE stream ───────────────────────────────────────────────────────────────
# _agent_event_frames is tested DIRECTLY (asyncio.run + a bounded fake
# is_disconnected), never through TestClient's HTTP streaming — a genuinely
# long-lived generator driven via TestClient was found to hang indefinitely
# (the same class of TestClient portal/lifecycle limitation the worker's own
# concurrency test hit; see WORKLOG.md "Agent-session chat integration").
# The route itself (stream_agent_events) is a thin one-liner wiring
# request.is_disconnected into this generator — nothing left to test over HTTP.

def _parse_sse_frames(raw_text: str) -> list[dict]:
    frames: list[dict] = []
    current: dict = {}
    for line in raw_text.splitlines():
        if line.startswith("id: "):
            current["id"] = line[len("id: "):]
        elif line.startswith("event: "):
            current["event"] = line[len("event: "):]
        elif line.startswith("data: "):
            current["data"] = line[len("data: "):]
        elif line == "" and current:
            frames.append(current)
            current = {}
    return frames


def _disconnect_after(n: int):
    """A fake Starlette Request.is_disconnected: returns False for the first
    `n` calls (letting the generator keep polling), then True (stopping it) —
    the deterministic bound TestClient's real disconnect detection couldn't
    reliably provide."""
    state = {"calls": 0}

    async def _check() -> bool:
        state["calls"] += 1
        return state["calls"] > n

    return _check


async def _drain_frames(gen) -> list[dict]:
    return _parse_sse_frames(await _collect_raw(gen))


async def _collect_raw(gen) -> str:
    """Raw SSE text, unparsed — needed for heartbeat lines (`: heartbeat\\n\\n`),
    which are comment-only and have no id:/event:/data: fields for
    _parse_sse_frames to key off of."""
    text = ""
    async for chunk in gen:
        text += chunk
    return text


def test_sse_emits_ordered_events(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "_AGENT_EVENT_POLL_SECONDS", 0.0)
    events = [
        {"type": "session_started", "sequence": 1, "ts": "t1", "payload": {}},
        {"type": "assistant_message", "sequence": 2, "ts": "t2", "payload": {}},
    ]
    fake = _FakeWorkerClient()
    fake.get_events = lambda session_id, after_sequence=0: _FakeResponse(200, events)
    _inject(mod, fake)

    frames = asyncio.run(_drain_frames(
        mod._agent_event_frames(fake, "AS-1", 0, _disconnect_after(1))))
    agent_frames = [f for f in frames if f.get("event") == "agent_event"]
    assert [f["id"] for f in agent_frames] == ["1", "2"]
    assert json.loads(agent_frames[0]["data"])["type"] == "session_started"
    assert json.loads(agent_frames[1]["data"])["type"] == "assistant_message"


def test_sse_reconnect_via_last_event_id_has_no_duplicates(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "_AGENT_EVENT_POLL_SECONDS", 0.0)

    def get_events(session_id, after_sequence=0):
        # honor the checkpoint like the real worker does — only ever return
        # sequence 3, proving the stream started from checkpoint=2, not 0
        if after_sequence >= 2:
            return _FakeResponse(200, [
                {"type": "session_idle", "sequence": 3, "ts": "t3", "payload": {}}])
        return _FakeResponse(200, [])

    fake = _FakeWorkerClient()
    fake.get_events = get_events
    _inject(mod, fake)

    # checkpoint=2 mirrors what the route does with a Last-Event-ID: 2 header
    frames = asyncio.run(_drain_frames(
        mod._agent_event_frames(fake, "AS-1", 2, _disconnect_after(1))))
    agent_frames = [f for f in frames if f.get("event") == "agent_event"]
    assert [f["id"] for f in agent_frames] == ["3"]


def test_sse_last_event_id_header_wins_over_query_param(client):
    mod, tc = client
    assert mod._resolve_sse_checkpoint("5", 0) == 5
    assert mod._resolve_sse_checkpoint(None, 7) == 7
    assert mod._resolve_sse_checkpoint("not-a-number", 3) == 3
    assert mod._resolve_sse_checkpoint("-9", 0) == 0   # never negative


def test_sse_worker_error_becomes_transport_error_not_an_agent_event(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "_AGENT_EVENT_POLL_SECONDS", 0.0)
    fake = _FakeWorkerClient(unavailable=True)
    _inject(mod, fake)

    frames = asyncio.run(_drain_frames(
        mod._agent_event_frames(fake, "AS-1", 0, _disconnect_after(1))))
    assert any(f.get("event") == "transport_error" for f in frames)
    assert not any(f.get("event") == "agent_event" for f in frames)


def test_sse_worker_4xx_becomes_transport_error_not_an_agent_event(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "_AGENT_EVENT_POLL_SECONDS", 0.0)
    fake = _FakeWorkerClient()
    fake.get_events = lambda session_id, after_sequence=0: _FakeResponse(
        404, {"detail": "no such agent session"})
    _inject(mod, fake)

    frames = asyncio.run(_drain_frames(
        mod._agent_event_frames(fake, "AS-1", 0, _disconnect_after(1))))
    assert any(f.get("event") == "transport_error" for f in frames)
    assert not any(f.get("event") == "agent_event" for f in frames)
    err = json.loads(next(f for f in frames if f.get("event") == "transport_error")["data"])
    assert err["status_code"] == 404


def test_sse_heartbeat_fires_when_idle(client, monkeypatch):
    """No new events for >= _AGENT_EVENT_HEARTBEAT_SECONDS emits a comment-only
    ': heartbeat\\n\\n' line — never an agent_event, never a transport_error —
    so a dumb proxy/load-balancer doesn't time out an idle-but-alive stream."""
    mod, tc = client
    monkeypatch.setattr(mod, "_AGENT_EVENT_POLL_SECONDS", 0.0)
    monkeypatch.setattr(mod, "_AGENT_EVENT_HEARTBEAT_SECONDS", 0.0)
    fake = _FakeWorkerClient()
    fake.get_events = lambda session_id, after_sequence=0: _FakeResponse(200, [])
    _inject(mod, fake)

    raw = asyncio.run(_collect_raw(
        mod._agent_event_frames(fake, "AS-1", 0, _disconnect_after(3))))
    assert ": heartbeat" in raw
    frames = _parse_sse_frames(raw)
    assert not any(f.get("event") == "agent_event" for f in frames)
    assert not any(f.get("event") == "transport_error" for f in frames)
