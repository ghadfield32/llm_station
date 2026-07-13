"""The host agent worker's HTTP surface: token auth is enforced on every /api/*
route (never /health), the full FakeHarness lifecycle works end to end through
real HTTP calls (not direct service calls), and store-layer errors map to the
right HTTP status codes. Uses an injected in-memory SessionStore (build_app's
test-only path) — worker_app.py's default store path (LEDGER_BASE_URL required,
no silent fallback) is exercised separately below.
"""
from __future__ import annotations

import time

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


def test_worker_owned_usage_captures_a_rate_limit_headlessly():
    # the worker's own UsageService ingests a live rate_limit event with NO
    # browser attached (the headless gap the cockpit tee can't cover), and
    # exposes it for the cockpit to proxy. Codex rate limits come from the Codex
    # provider collector, so a codex_agent rate_limit is ignored here.
    import types

    from command_center.agent_sessions import worker_app as wa
    from command_center.agent_sessions.events import AgentEvent
    from command_center.usage.service import UsageService
    from command_center.usage.store import UsageStore

    usage = UsageService(UsageStore())
    ev = AgentEvent("rate_limit", {"status": "allowed_warning",
                    "rate_limit_type": "five_hour", "utilization": None,
                    "resets_at": 1783896000})
    ev.ts = "2026-07-12T00:00:00+00:00"
    claude = types.SimpleNamespace(harness="claude_code_local", session_id="s1",
                                   repo_id="r", conversation_id="c", model="opus")
    codex = types.SimpleNamespace(harness="codex_agent", session_id="s2",
                                  repo_id="r", conversation_id="c", model="gpt-5.5")
    wa._worker_feed_usage(usage, claude, None, ev)
    wa._worker_feed_usage(usage, codex, None, ev)        # ignored (own collector)
    app = wa.build_app(store=SessionStore(), token=TOKEN, usage_service=usage)
    client = TestClient(app)
    rows = client.get("/api/model-usage", headers=_auth()).json()
    assert {r["runtime_id"] for r in rows} == {"claude_code_local"}
    detail = client.get("/api/model-usage/claude_code_local", headers=_auth()).json()
    assert detail["availability"] == "near_limit"


def _wait_for_events(client, session_id, *, min_count, after_sequence=0, timeout=2.0):
    """POST /messages is fire-and-forget (202 Accepted, a background task —
    see worker_app.py's async execution-model correction), so a caller that
    wants the resulting events back must poll /events rather than read them
    off the POST response. FakeHarness's own work is effectively instant, but
    this still polls rather than assuming zero scheduling delay. Defaults to
    after_sequence=0, i.e. ALL events for the session — callers that only
    want events from a specific message (not the session_started event from
    creation) must pass the checkpoint explicitly."""
    deadline = time.monotonic() + timeout
    events: list[dict] = []
    while time.monotonic() < deadline:
        events = client.get(f"/api/agent-sessions/{session_id}/events",
                            headers=_auth(),
                            params={"after_sequence": after_sequence}).json()
        if len(events) >= min_count:
            return events
        time.sleep(0.02)
    raise AssertionError(
        f"timed out waiting for >= {min_count} events, got {len(events)}: {events}")


def test_health_needs_no_token(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_api_routes_reject_missing_token(client):
    assert client.get("/api/agent-harnesses").status_code == 401


def test_api_routes_reject_wrong_token(client):
    r = client.get("/api/agent-harnesses",
                   headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_list_harnesses_reports_fake_and_real_adapters(client):
    # Both codex_agent and claude_agent are real adapters now; their
    # availability depends on the real environment (optional SDK/auth), covered
    # deterministically in the per-adapter tests. On this host claude_agent is
    # unavailable with a CONCRETE blocker, never a generic "unavailable".
    r = client.get("/api/agent-harnesses", headers=_auth())
    assert r.status_code == 200
    harnesses = {h["harness_id"]: h for h in r.json()}
    assert harnesses["fake"]["available"] is True
    assert harnesses["claude_agent"]["available"] is False
    detail = harnesses["claude_agent"]["detail"]
    assert ("claude-agent-sdk" in detail) or ("ANTHROPIC_API_KEY" in detail)


def test_create_session_with_unknown_harness_404s(client):
    r = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "does-not-exist", "conversation_id": "c1",
        "repo_id": "r", "mode": "analysis"})
    assert r.status_code == 404


def test_create_session_with_unavailable_harness_400s_with_exact_blocker(client):
    r = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "claude_agent", "conversation_id": "c1",
        "repo_id": "r", "mode": "analysis"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert ("claude-agent-sdk" in detail) or ("ANTHROPIC_API_KEY" in detail)


def test_list_sessions_filters_by_conversation_id_and_repo_id(client):
    """Lets a caller (the cockpit) recover a durable session by
    conversation_id/repo_id without relying exclusively on local browser
    storage — see WORKLOG.md "Agent-session chat integration"."""
    s1 = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "conv-a",
        "repo_id": "llm_station", "mode": "analysis"}).json()["session_id"]
    client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "conv-b",
        "repo_id": "betts_basketball", "mode": "analysis"})

    r = client.get("/api/agent-sessions", headers=_auth(),
                   params={"conversation_id": "conv-a"})
    assert r.status_code == 200
    assert [s["session_id"] for s in r.json()] == [s1]


def test_full_lifecycle_over_real_http(client):
    created = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "c1",
        "repo_id": "llm_station", "mode": "analysis"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    assert created.json()["status"] == "idle"   # ready, not "a task is running"

    got = client.get(f"/api/agent-sessions/{session_id}", headers=_auth())
    assert got.status_code == 200 and got.json()["conversation_id"] == "c1"

    sent = client.post(f"/api/agent-sessions/{session_id}/messages",
                       headers=_auth(), json={"prompt": "hello"})
    assert sent.status_code == 202   # fire-and-forget background run
    assert sent.json()["status"] == "accepted"

    events = _wait_for_events(client, session_id, min_count=2, after_sequence=1)
    assert [e["type"] for e in events] == ["assistant_message", "session_idle"]
    all_events = client.get(f"/api/agent-sessions/{session_id}/events",
                            headers=_auth()).json()
    sequences = [e["sequence"] for e in all_events]
    assert sequences == list(range(1, len(sequences) + 1))
    assert client.get(f"/api/agent-sessions/{session_id}", headers=_auth()
                      ).json()["status"] == "idle"   # the background run completed

    interrupted = client.post(f"/api/agent-sessions/{session_id}/interrupt",
                              headers=_auth())
    assert interrupted.status_code == 200
    assert client.get(f"/api/agent-sessions/{session_id}", headers=_auth()
                      ).json()["status"] == "interrupted"

    resumed = client.post(f"/api/agent-sessions/{session_id}/resume", headers=_auth())
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "idle"

    closed = client.delete(f"/api/agent-sessions/{session_id}", headers=_auth())
    assert closed.status_code == 200
    assert client.get(f"/api/agent-sessions/{session_id}", headers=_auth()
                      ).json()["status"] == "closed"


class _SlowHarness:
    """A controllable AgentHarness whose send() blocks on an asyncio.Event
    until the test releases it — the only way to deterministically prove the
    409-concurrent-turn rejection without racing against FakeHarness's
    effectively-instant completion."""

    name = "slow"

    def __init__(self, store):
        from command_center.agent_sessions.protocol import HarnessProbe
        self.store = store
        self.gate = None   # set per-instance by the test via the registry factory
        self._HarnessProbe = HarnessProbe

    async def probe(self):
        return self._HarnessProbe(available=True, detail="slow test double")

    async def start_session(self, request):
        record = self.store.create_session(
            harness=self.name, conversation_id=request.conversation_id,
            repo_id=request.repo_id, provider_profile=request.provider_profile,
            model=request.model, permission_profile=request.permission_profile)
        self.store.set_status(record.session_id, "idle")
        return record.session_id

    async def send(self, session_id, prompt):
        import asyncio

        from command_center.agent_sessions.events import AgentEvent
        # threading.Event, not asyncio.Event: TestClient's portal runs the
        # ASGI app in its own thread, so the test's gate.set() call happens
        # on a DIFFERENT thread than this coroutine — asyncio.Event.set() is
        # not documented safe to call cross-thread (empirically it corrupted
        # the wait and the task came back "interrupted" instead of
        # completing); a plain polled threading.Event is unambiguously safe.
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        yield self.store.append_event(session_id, AgentEvent(
            "assistant_message", {"text": "done waiting"}))
        yield self.store.append_event(session_id, AgentEvent("session_idle", {}))

    async def resolve_approval(self, session_id, decision):
        raise RuntimeError("not used in this test")

    async def interrupt(self, session_id):
        pass

    async def resume(self, session_id):
        pass

    async def close(self, session_id):
        pass


def test_concurrent_message_to_the_same_session_is_rejected():
    """Uses httpx.AsyncClient(transport=ASGITransport(...)) instead of
    starlette.testclient.TestClient — deliberately. TestClient bridges sync
    test code to the async app via a portal running in its own thread, and a
    task spawned via asyncio.create_task() during one .post() call was
    empirically found NOT to reliably survive to a later .post() call on that
    portal (it came back "interrupted"/cancelled even with a thread-safe
    gate) — a TestClient-specific artifact, not a bug in the worker: a real
    uvicorn process has no such per-call task-group boundary. Running
    everything on ONE event loop (no thread/portal boundary at all) is what
    actually proves the 409-concurrent-turn behavior deterministically."""
    import asyncio

    import httpx

    from command_center.agent_sessions.registry import HarnessDescriptor, HarnessRegistry

    async def _run() -> None:
        store = SessionStore()
        gate = asyncio.Event()   # safe here: everything runs on one loop
        harness = _SlowHarness(store)
        harness.gate = gate
        registry = HarnessRegistry([HarnessDescriptor(
            harness_id="slow", label="Slow", production=False,
            supported_modes=("analysis",), factory=lambda: harness)])
        app = build_app(store=store, token=TOKEN, registry=registry)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://worker") as client:
            created = await client.post("/api/agent-sessions", headers=_auth(), json={
                "harness_id": "slow", "conversation_id": "c1", "repo_id": "r",
                "mode": "analysis"})
            session_id = created.json()["session_id"]

            first = await client.post(f"/api/agent-sessions/{session_id}/messages",
                                      headers=_auth(), json={"prompt": "hello"})
            assert first.status_code == 202
            await asyncio.sleep(0)   # let the background task actually start and hit the gate

            second = await client.post(f"/api/agent-sessions/{session_id}/messages",
                                       headers=_auth(), json={"prompt": "again"})
            assert second.status_code == 409

            gate.set()
            deadline = asyncio.get_event_loop().time() + 2.0
            events: list[dict] = []
            while asyncio.get_event_loop().time() < deadline:
                r = await client.get(f"/api/agent-sessions/{session_id}/events",
                                     headers=_auth())
                events = r.json()
                if len(events) >= 2:
                    break
                await asyncio.sleep(0.01)
            assert [e["type"] for e in events] == ["assistant_message", "session_idle"]

    asyncio.run(_run())


def test_message_to_an_interrupted_session_is_rejected_until_resumed(client):
    session_id = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "c1", "repo_id": "r",
        "mode": "analysis"}).json()["session_id"]
    client.post(f"/api/agent-sessions/{session_id}/interrupt", headers=_auth())

    blocked = client.post(f"/api/agent-sessions/{session_id}/messages",
                          headers=_auth(), json={"prompt": "hello"})
    assert blocked.status_code == 409

    client.post(f"/api/agent-sessions/{session_id}/resume", headers=_auth())
    allowed = client.post(f"/api/agent-sessions/{session_id}/messages",
                          headers=_auth(), json={"prompt": "hello"})
    assert allowed.status_code == 202


def test_message_to_a_closed_session_is_rejected(client):
    session_id = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "c1", "repo_id": "r",
        "mode": "analysis"}).json()["session_id"]
    client.delete(f"/api/agent-sessions/{session_id}", headers=_auth())
    r = client.post(f"/api/agent-sessions/{session_id}/messages",
                    headers=_auth(), json={"prompt": "hello"})
    assert r.status_code == 400


def test_approval_lifecycle_over_real_http(client):
    session_id = client.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "c1", "repo_id": "r",
        "mode": "workspace"}).json()["session_id"]
    client.post(f"/api/agent-sessions/{session_id}/messages",
               headers=_auth(), json={"prompt": "write a file"})
    events = _wait_for_events(client, session_id, min_count=1, after_sequence=1)
    approval_id = events[0]["payload"]["approval_id"]

    resolved = client.post(
        f"/api/agent-sessions/{session_id}/approvals/{approval_id}",
        headers=_auth(), json={"approved": True, "reason": "fine"})
    assert resolved.status_code == 200

    replay = client.post(
        f"/api/agent-sessions/{session_id}/approvals/{approval_id}",
        headers=_auth(), json={"approved": False})
    assert replay.status_code == 409


def test_worker_restart_marks_orphaned_active_sessions_failed(tmp_path):
    """The actual reason "active" vs "idle" are distinct statuses: a fresh
    worker process's active_runs registry is always empty, so any session
    still reading "active" from a PREVIOUS process is unambiguously orphaned
    — reconciliation must mark it failed, never leave it claiming a task is
    still running when nothing is."""
    store = SessionStore()
    app1 = build_app(store=store, token=TOKEN)
    client1 = TestClient(app1)
    session_id = client1.post("/api/agent-sessions", headers=_auth(), json={
        "harness_id": "fake", "conversation_id": "c1", "repo_id": "r",
        "mode": "analysis"}).json()["session_id"]
    # simulate a crash mid-turn: force the status to "active" without a real
    # background task behind it (exactly what a real crash would leave behind)
    store.set_status(session_id, "active")

    # simulate a full process restart: a brand new app, same durable store
    app2 = build_app(store=store, token=TOKEN)
    client2 = TestClient(app2)
    recovered = client2.get(f"/api/agent-sessions/{session_id}", headers=_auth())
    assert recovered.json()["status"] == "failed"
    events = client2.get(f"/api/agent-sessions/{session_id}/events",
                         headers=_auth()).json()
    assert events[-1]["type"] == "session_failed"
    assert "worker restarted" in events[-1]["payload"]["reason"]


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


class _HarnessWithShutdown:
    """A controllable AgentHarness that also declares the OPTIONAL
    shutdown() hook (not part of the Protocol — see adapters/codex_agent.py
    and worker_app.py's _shutdown_harnesses) — real adapters that own a
    subprocess connection (Codex) declare it; FakeHarness does not."""

    name = "with-shutdown"

    def __init__(self, store):
        from command_center.agent_sessions.protocol import HarnessProbe
        self.store = store
        self.shutdown_called = False
        self._HarnessProbe = HarnessProbe

    async def probe(self):
        return self._HarnessProbe(available=True, detail="test double")

    async def start_session(self, request):
        record = self.store.create_session(
            harness=self.name, conversation_id=request.conversation_id,
            repo_id=request.repo_id, provider_profile=request.provider_profile,
            model=request.model, permission_profile=request.permission_profile)
        self.store.set_status(record.session_id, "idle")
        return record.session_id

    async def send(self, session_id, prompt):
        from command_center.agent_sessions.events import AgentEvent
        yield self.store.append_event(session_id, AgentEvent("session_idle", {}))

    async def resolve_approval(self, session_id, decision):
        raise RuntimeError("not used in this test")

    async def interrupt(self, session_id):
        pass

    async def resume(self, session_id):
        pass

    async def close(self, session_id):
        pass

    async def shutdown(self):
        self.shutdown_called = True


def test_worker_shutdown_calls_shutdown_on_every_cached_harness_instance():
    """AgentSessionService caches one harness instance PER SESSION (not one
    shared instance per harness type), so a real Codex worker with multiple
    active sessions would own multiple live SDK clients — this proves the
    shutdown handler walks all of them, not just one."""
    from command_center.agent_sessions.registry import HarnessDescriptor, HarnessRegistry

    store = SessionStore()
    harness = _HarnessWithShutdown(store)
    registry = HarnessRegistry([HarnessDescriptor(
        harness_id="with-shutdown", label="With Shutdown", production=False,
        supported_modes=("analysis",), factory=lambda: harness)])
    app = build_app(store=store, token=TOKEN, registry=registry)

    # TestClient's `with` context manager reliably drives the real ASGI
    # startup/shutdown lifecycle (unlike cross-request background-task
    # survival, which this repo's own tests found unreliable on the same
    # portal — this is a single, simple lifecycle event, not that).
    with TestClient(app) as client:
        created = client.post("/api/agent-sessions", headers=_auth(), json={
            "harness_id": "with-shutdown", "conversation_id": "c1",
            "repo_id": "r", "mode": "analysis"})
        assert created.status_code == 200
        assert harness.shutdown_called is False

    assert harness.shutdown_called is True


def test_worker_shutdown_skips_harnesses_without_the_optional_hook():
    """FakeHarness declares no shutdown() — the handler must not raise just
    because a harness doesn't opt into the optional cleanup hook."""
    with TestClient(build_app(store=SessionStore(), token=TOKEN)) as client:
        created = client.post("/api/agent-sessions", headers=_auth(), json={
            "harness_id": "fake", "conversation_id": "c1",
            "repo_id": "r", "mode": "analysis"})
        assert created.status_code == 200
    # no exception on exit == pass
