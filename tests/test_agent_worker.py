"""The host agent worker's HTTP surface: token auth is enforced on every /api/*
route (never /health), the full FakeHarness lifecycle works end to end through
real HTTP calls (not direct service calls), and store-layer errors map to the
right HTTP status codes. Uses an injected in-memory SessionStore (build_app's
test-only path) — worker_app.py's default store path (LEDGER_BASE_URL required,
no silent fallback) is exercised separately below.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from command_center.agent_sessions.store import SessionStore
from command_center.agent_sessions.worker_app import build_app

TOKEN = "test-worker-token"


@pytest.fixture
def client():
    app = build_app(store=SessionStore(), token=TOKEN)
    return TestClient(app)


def _auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health_needs_no_token(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_api_routes_reject_missing_token(client):
    assert client.get("/api/agent-harnesses").status_code == 401


def test_api_routes_reject_wrong_token(client):
    r = client.get("/api/agent-harnesses",
                   headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_list_harnesses_reports_fake_and_placeholders(client):
    r = client.get("/api/agent-harnesses", headers=_auth())
    assert r.status_code == 200
    harnesses = {h["harness_id"]: h for h in r.json()}
    assert harnesses["fake"]["available"] is True
    assert harnesses["codex_agent"]["available"] is False
    assert "no real adapter built yet" in harnesses["codex_agent"]["detail"]


def test_create_session_with_unknown_harness_404s(client):
    r = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "does-not-exist", "conversation_id": "c1",
        "repo_id": "r", "mode": "analysis"})
    assert r.status_code == 404


def test_create_session_with_unavailable_harness_400s_with_exact_blocker(client):
    r = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "codex_agent", "conversation_id": "c1",
        "repo_id": "r", "mode": "analysis"})
    assert r.status_code == 400
    assert "no real adapter built yet" in r.json()["detail"]


def test_full_lifecycle_over_real_http(client):
    created = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "c1",
        "repo_id": "llm_station", "mode": "analysis"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    assert created.json()["status"] == "active"

    got = client.get(f"/api/agent-sessions/{session_id}", headers=_auth())
    assert got.status_code == 200 and got.json()["conversation_id"] == "c1"

    sent = client.post(f"/api/agent-sessions/{session_id}/messages",
                       headers=_auth(), json={"prompt": "hello"})
    assert sent.status_code == 200
    assert [e["type"] for e in sent.json()] == ["assistant_message", "session_idle"]

    events = client.get(f"/api/agent-sessions/{session_id}/events", headers=_auth())
    sequences = [e["sequence"] for e in events.json()]
    assert sequences == list(range(1, len(sequences) + 1))

    interrupted = client.post(f"/api/agent-sessions/{session_id}/interrupt",
                              headers=_auth())
    assert interrupted.status_code == 200
    assert client.get(f"/api/agent-sessions/{session_id}", headers=_auth()
                      ).json()["status"] == "interrupted"

    resumed = client.post(f"/api/agent-sessions/{session_id}/resume", headers=_auth())
    assert resumed.status_code == 200

    closed = client.delete(f"/api/agent-sessions/{session_id}", headers=_auth())
    assert closed.status_code == 200
    assert client.get(f"/api/agent-sessions/{session_id}", headers=_auth()
                      ).json()["status"] == "closed"


def test_approval_lifecycle_over_real_http(client):
    session_id = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "c1", "repo_id": "r",
        "mode": "workspace"}).json()["session_id"]
    sent = client.post(f"/api/agent-sessions/{session_id}/messages",
                       headers=_auth(), json={"prompt": "write a file"})
    approval_id = sent.json()[0]["payload"]["approval_id"]

    resolved = client.post(
        f"/api/agent-sessions/{session_id}/approvals/{approval_id}",
        headers=_auth(), json={"approved": True, "reason": "fine"})
    assert resolved.status_code == 200

    replay = client.post(
        f"/api/agent-sessions/{session_id}/approvals/{approval_id}",
        headers=_auth(), json={"approved": False})
    assert replay.status_code == 409


def test_unknown_session_404s_on_every_route(client):
    assert client.get("/api/agent-sessions/nope", headers=_auth()).status_code == 404
    assert client.post("/api/agent-sessions/nope/messages", headers=_auth(),
                       json={"prompt": "x"}).status_code == 404
    assert client.get("/api/agent-sessions/nope/events", headers=_auth()).status_code == 404
    assert client.post("/api/agent-sessions/nope/interrupt",
                       headers=_auth()).status_code == 404
    assert client.post("/api/agent-sessions/nope/resume",
                       headers=_auth()).status_code == 404
    assert client.delete("/api/agent-sessions/nope", headers=_auth()).status_code == 404


def test_build_app_requires_ledger_base_url_when_no_store_injected(monkeypatch):
    monkeypatch.delenv("LEDGER_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="LEDGER_BASE_URL"):
        build_app(token=TOKEN)


def test_build_app_requires_a_worker_token_when_none_injected(monkeypatch):
    monkeypatch.delenv("AGENT_WORKER_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="AGENT_WORKER_TOKEN"):
        build_app(store=SessionStore())
