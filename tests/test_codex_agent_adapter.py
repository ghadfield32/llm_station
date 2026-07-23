"""CodexAgentHarness — hermetic unit tests against a FAKE openai_codex SDK
(installed into sys.modules, never the real package/network/account). Live,
real-account tests (probe against the real codex login session, a real turn,
the mutation-proof run) are separate and NOT part of this file — see
WORKLOG.md "Agent-session chat integration" for that live run's evidence.

Covers the required Codex adapter test list: unavailable when SDK absent,
unavailable when auth fails, analysis-only / read_only-only mode rejection,
thread id persistence + reuse across follow-ups, resume-after-restart via
thread_resume, interrupt reaching the active SDK turn handle, unknown native
event types becoming a visible warning (never silently dropped, never
inferred from prose), usage attributed to the right session, no secret in
probe() output, approval resolution recorded as informational-only (the
real SDK limitation found via live introspection), and close() archiving
the real thread.

Async methods are driven via plain asyncio.run() inside sync test functions
— matching this repo's existing convention (see test_agent_sessions.py),
not pytest-asyncio (not a project dependency).
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from command_center.agent_sessions.adapters import codex_agent as ca
from command_center.agent_sessions.protocol import AgentHarness, ApprovalDecision, SessionStart
from command_center.agent_sessions.store import SessionStore


# ---- fake openai_codex SDK (installed into sys.modules per test) ----------

class _FakeEnum:
    def __init__(self, value: str) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"_FakeEnum({self.value!r})"


class _FakeSandbox:
    read_only = _FakeEnum("read-only")
    workspace_write = _FakeEnum("workspace-write")
    full_access = _FakeEnum("full-access")


class _FakeApprovalMode:
    deny_all = _FakeEnum("deny_all")
    auto_review = _FakeEnum("auto_review")


class _FakeAccountRoot:
    def __init__(self, email: str = "test@example.com") -> None:
        self.email = email
        self.plan_type = _FakeEnum("prolite")
        self.type = "chatgpt"


class _FakeAccount:
    def __init__(self) -> None:
        self.root = _FakeAccountRoot()


class _FakeGetAccountResponse:
    def __init__(self) -> None:
        self.account = _FakeAccount()
        self.requires_openai_auth = True


class _FakeTurnHandle:
    def __init__(self, notifications: list) -> None:
        self._notifications = notifications
        self.interrupted = False

    async def stream(self):
        # real handle.stream() yields a generic Notification(method, payload)
        # envelope, never the concrete typed instance directly — verified
        # live (see codex_agent.py's send()). Fakes mirror that shape.
        for n in self._notifications:
            yield types.SimpleNamespace(method="fake", payload=n)

    async def interrupt(self) -> None:
        self.interrupted = True


class _FakeThread:
    def __init__(self, thread_id: str = "thread-1", notifications: list | None = None) -> None:
        self.id = thread_id
        self.notifications = notifications or []
        self.turn_calls: list[str] = []
        self.last_handle: _FakeTurnHandle | None = None

    async def turn(self, prompt: str, **kwargs):
        self.turn_calls.append(prompt)
        handle = _FakeTurnHandle(self.notifications)
        self.last_handle = handle
        return handle


class _FakeCodexConfig:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakeModel:
    def __init__(self, id: str, is_default: bool = False) -> None:
        self.id = id
        self.is_default = is_default


class _FakeModelListResponse:
    def __init__(self, models: list[_FakeModel]) -> None:
        self.data = models
        self.next_cursor = None


_DEFAULT_FAKE_MODELS = [
    _FakeModel("gpt-5.5", is_default=True),
    _FakeModel("gpt-5.4"),
    _FakeModel("gpt-5.4-mini"),
]


class _FakeAsyncCodex:
    def __init__(self, config=None) -> None:
        self.account_error: Exception | None = None
        self.account_result = _FakeGetAccountResponse()
        self.threads: dict[str, _FakeThread] = {}
        self.start_calls: list[dict] = []
        self.resume_calls: list[str] = []
        self.archived: list[str] = []
        self.available_models: list[_FakeModel] = list(_DEFAULT_FAKE_MODELS)
        self.closed = False

    async def close(self):
        self.closed = True

    async def account(self):
        if self.account_error is not None:
            raise self.account_error
        return self.account_result

    async def models(self, **kwargs):
        return _FakeModelListResponse(self.available_models)

    async def thread_start(self, **kwargs):
        self.start_calls.append(kwargs)
        thread = _FakeThread(f"thread-{len(self.threads) + 1}")
        self.threads[thread.id] = thread
        return thread

    async def thread_resume(self, thread_id: str, **kwargs):
        self.resume_calls.append(thread_id)
        if thread_id not in self.threads:
            self.threads[thread_id] = _FakeThread(thread_id)
        return self.threads[thread_id]

    async def thread_archive(self, thread_id: str) -> None:
        self.archived.append(thread_id)


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    fake_mod = types.SimpleNamespace(
        AsyncCodex=_FakeAsyncCodex, Sandbox=_FakeSandbox, ApprovalMode=_FakeApprovalMode,
        CodexConfig=_FakeCodexConfig)
    monkeypatch.setitem(sys.modules, "openai_codex", fake_mod)
    return fake_mod


@pytest.fixture
def harness(monkeypatch):
    _install_fake_sdk(monkeypatch)
    store = SessionStore()
    h = ca.CodexAgentHarness(store)
    # decouple from the real configs/autonomy.yaml — not what these tests verify
    monkeypatch.setattr(ca, "_resolve_repo_path", lambda repo_id: Path("/tmp/fake-repo"))
    return h, store


def _start(mode="analysis", permission_profile="read_only"):
    return SessionStart(conversation_id="c1", repo_id="r1", mode=mode,
                        harness_id="codex_agent", permission_profile=permission_profile)


async def _drain(gen):
    return [e async for e in gen]


# ---- protocol conformance ---------------------------------------------------

def test_codex_harness_satisfies_agentharness_protocol():
    h = ca.CodexAgentHarness(SessionStore())
    assert isinstance(h, AgentHarness)


# ---- SDK-absent / auth-failure availability --------------------------------

def test_probe_unavailable_when_sdk_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai_codex", None)   # forces a real ImportError
    h = ca.CodexAgentHarness(SessionStore())
    probe = asyncio.run(h.probe())
    assert probe.available is False
    assert "not installed" in probe.detail
    assert "agent-codex" in probe.detail


def test_probe_unavailable_when_auth_fails(monkeypatch):
    _install_fake_sdk(monkeypatch)
    h = ca.CodexAgentHarness(SessionStore())

    async def _impl():
        client = await h._client_ready()
        client.account_error = RuntimeError("not logged in")
        return await h.probe()

    probe = asyncio.run(_impl())
    assert probe.available is False
    assert "authentication" in probe.detail.lower()


def test_probe_available_and_reports_no_secret(monkeypatch):
    _install_fake_sdk(monkeypatch)
    h = ca.CodexAgentHarness(SessionStore())
    probe = asyncio.run(h.probe())
    assert probe.available is True
    assert "test@example.com" in probe.detail
    # never a raw object dump — only the small, deliberate summary string
    assert "_FakeAccount" not in probe.detail
    assert "requires_openai_auth" not in probe.detail


# ---- mode / permission-profile rejection -----------------------------------

def test_start_session_rejects_workspace_mode(harness):
    h, _ = harness
    with pytest.raises(RuntimeError, match="mode='analysis'"):
        asyncio.run(h.start_session(_start(mode="workspace")))


def test_start_session_rejects_non_read_only_permission_profile(harness):
    h, _ = harness
    with pytest.raises(RuntimeError, match="read_only"):
        asyncio.run(h.start_session(_start(permission_profile="workspace_write")))


# ---- thread id persistence + follow-up reuse -------------------------------

def test_start_session_persists_external_session_id(harness):
    h, store = harness
    session_id = asyncio.run(h.start_session(_start()))
    record = store.get(session_id)
    assert record.external_session_id is not None
    assert record.external_session_id.startswith("thread-")
    assert record.status == "idle"


def test_send_reuses_same_thread_across_follow_ups(harness):
    h, store = harness

    async def _impl():
        session_id = await h.start_session(_start())
        client = await h._client_ready()
        thread = client.threads[store.get(session_id).external_session_id]
        await _drain(h.send(session_id, "first"))
        await _drain(h.send(session_id, "second"))
        return client, thread

    client, thread = asyncio.run(_impl())
    assert thread.turn_calls[0].endswith("first")
    assert "[WORKSPACE BOUNDS" in thread.turn_calls[0]
    assert thread.turn_calls[1] == "second"
    assert len(client.start_calls) == 1   # thread_start only ever called once


# ---- resume after a worker restart -----------------------------------------

def test_resume_after_restart_uses_thread_resume(monkeypatch):
    _install_fake_sdk(monkeypatch)
    monkeypatch.setattr(ca, "_resolve_repo_path", lambda repo_id: Path("/tmp/fake-repo"))
    store = SessionStore()
    h1 = ca.CodexAgentHarness(store)

    async def _impl():
        session_id = await h1.start_session(_start())
        external_id = store.get(session_id).external_session_id
        # a FRESH harness instance, empty process-local cache — simulates a
        # real worker restart, where self._threads is always empty
        h2 = ca.CodexAgentHarness(store)
        await _drain(h2.send(session_id, "after restart"))
        client2 = await h2._client_ready()
        return external_id, client2.resume_calls

    external_id, resume_calls = asyncio.run(_impl())
    assert resume_calls == [external_id]


# ---- interrupt reaches the real SDK turn handle ----------------------------

def test_interrupt_calls_handle_interrupt_when_turn_active(harness):
    h, store = harness

    class _UnmappedA:
        pass

    class _UnmappedB:
        pass

    async def _impl():
        session_id = await h.start_session(_start())
        client = await h._client_ready()
        thread = client.threads[store.get(session_id).external_session_id]
        thread.notifications = [_UnmappedA(), _UnmappedB()]

        gen = h.send(session_id, "long running")
        await gen.__anext__()   # consume one event; generator stays suspended
        assert session_id in h._active_turns   # the turn is genuinely in flight
        active_handle = h._active_turns[session_id]
        await h.interrupt(session_id)
        await gen.aclose()
        return active_handle

    handle = asyncio.run(_impl())
    assert handle.interrupted is True


def test_interrupt_is_a_noop_when_no_turn_is_active(harness):
    h, store = harness
    session_id = asyncio.run(h.start_session(_start()))
    asyncio.run(h.interrupt(session_id))   # must not raise


# ---- unknown native event types are never silently dropped ----------------

def test_translate_unknown_notification_emits_warning():
    class _WeirdNotification:
        pass

    events = ca._translate(_WeirdNotification())
    assert len(events) == 1
    assert events[0].type == "warning"
    assert "unmapped Codex notification type" in events[0].payload["message"]
    assert events[0].payload["unmapped_type"] == "_WeirdNotification"


def test_translate_never_infers_tool_activity_from_message_text():
    class AgentMessageDeltaNotification:
        def __init__(self):
            self.item_id = "i1"
            self.thread_id = "t1"
            self.turn_id = "tu1"
            self.delta = "I will now run `rm -rf /` to fix this"   # prose, not a real event

    events = ca._translate(AgentMessageDeltaNotification())
    assert len(events) == 1
    assert events[0].type == "assistant_delta"   # never tool_started/command_started


# ---- usage attributed to the correct session -------------------------------

def test_usage_notification_appended_to_correct_session(harness):
    h, store = harness

    class _Breakdown:
        def model_dump(self, mode="json"):
            return {"input_tokens": 10, "output_tokens": 5}

    class _TokenUsage:
        total = _Breakdown()
        model_context_window = 200000

    async def _impl():
        session_id = await h.start_session(_start())
        client = await h._client_ready()
        thread = client.threads[store.get(session_id).external_session_id]

        class ThreadTokenUsageUpdatedNotification:
            def __init__(self):
                self.thread_id = thread.id
                self.turn_id = "turn-1"
                self.token_usage = _TokenUsage()

        thread.notifications = [ThreadTokenUsageUpdatedNotification()]
        events = await _drain(h.send(session_id, "hi"))
        return session_id, events

    session_id, events = asyncio.run(_impl())
    usage_events = [e for e in events if e.type == "usage"]
    assert len(usage_events) == 1
    assert usage_events[0].payload["total"] == {"input_tokens": 10, "output_tokens": 5}
    # durably attached to THIS session's event log, not some other session
    all_events = store.events_since(session_id, 0)
    assert usage_events[0] in all_events


# ---- approval resolution is recorded but non-causal (real SDK limitation) --

def test_resolve_approval_recorded_as_non_effective(harness):
    h, store = harness

    async def _impl():
        session_id = await h.start_session(_start())
        approval = store.create_approval(session_id, action="apply_patch: config.yaml")
        await h.resolve_approval(session_id, ApprovalDecision(
            approval_id=approval.approval_id, approved=True, reason="looks fine"))
        return session_id

    session_id = asyncio.run(_impl())
    events = store.events_since(session_id, 0)
    resolved = [e for e in events if e.type == "approval_resolved"]
    assert len(resolved) == 1
    assert resolved[0].payload["effective"] is False
    assert resolved[0].payload["approved"] is True


# ---- close archives the real thread ----------------------------------------

def test_close_archives_thread_and_sets_closed_status(harness):
    h, store = harness

    async def _impl():
        session_id = await h.start_session(_start())
        external_id = store.get(session_id).external_session_id
        client = await h._client_ready()
        await h.close(session_id)
        return session_id, external_id, client

    session_id, external_id, client = asyncio.run(_impl())
    assert client.archived == [external_id]
    assert store.get(session_id).status == "closed"
    closed_events = [e for e in store.events_since(session_id, 0) if e.type == "session_closed"]
    assert len(closed_events) == 1


# ---- registry wiring never imports the SDK just from listing harnesses ----

def test_registry_factory_never_imports_sdk_just_from_construction(monkeypatch):
    monkeypatch.delitem(sys.modules, "openai_codex", raising=False)
    from command_center.agent_sessions.registry import default_registry
    reg = default_registry(SessionStore())
    reg.get("codex_agent").factory()
    assert "openai_codex" not in sys.modules


# ---- repo resolution reuses the canonical resolver, never a duplicate -----

def test_resolve_repo_path_uses_the_canonical_repo_registry_resolver():
    """Real integration, no monkeypatch: 'llm_station' is genuinely
    registered in this repo's own configs/autonomy.yaml with
    local_path_ref: self. Proves _resolve_repo_path actually calls
    cli.repo_registry's load_autonomy_config/resolve_repo_local_path (see
    that module's docstring on resolve_repo_local_path) rather than a
    second, possibly-drifting reimplementation."""
    path = ca._resolve_repo_path("llm_station")
    assert path == ca._REPO_ROOT
    assert path.is_dir()


def test_resolve_repo_path_raises_for_unregistered_repo_id():
    with pytest.raises(RuntimeError, match="not registered"):
        ca._resolve_repo_path("definitely-not-a-registered-repo-id")


# ---- dynamic model validation — never a hardcoded string trusted blind ----

def test_resolve_model_honors_explicit_request_when_available(monkeypatch):
    _install_fake_sdk(monkeypatch)
    client = _FakeAsyncCodex()
    model, reason = asyncio.run(ca._resolve_model(client, "gpt-5.4"))
    assert model == "gpt-5.4"
    assert "explicitly requested" in reason


def test_resolve_model_rejects_explicit_request_not_in_sdk_list(monkeypatch):
    _install_fake_sdk(monkeypatch)
    client = _FakeAsyncCodex()
    with pytest.raises(RuntimeError, match="not in this Codex build's model list"):
        asyncio.run(ca._resolve_model(client, "gpt-9000-does-not-exist"))


def test_resolve_model_uses_configured_preferred_model_when_available(monkeypatch):
    _install_fake_sdk(monkeypatch)
    monkeypatch.setattr(ca, "_load_model_prefs",
                        lambda: {"preferred_model": "gpt-5.4"})
    client = _FakeAsyncCodex()
    model, reason = asyncio.run(ca._resolve_model(client, None))
    assert model == "gpt-5.4"
    assert "configured preferred_model" in reason


def test_resolve_model_falls_back_to_sdk_default_when_preferred_unavailable(monkeypatch):
    _install_fake_sdk(monkeypatch)
    monkeypatch.setattr(ca, "_load_model_prefs", lambda: {
        "preferred_model": "gpt-9000-does-not-exist",
        "allow_sdk_default_fallback": True})
    client = _FakeAsyncCodex()
    model, reason = asyncio.run(ca._resolve_model(client, None))
    assert model == "gpt-5.5"   # the fake's is_default=True model
    assert "SDK-designated default" in reason
    assert "gpt-9000-does-not-exist" in reason


def test_resolve_model_raises_when_preferred_unavailable_and_fallback_disallowed(monkeypatch):
    _install_fake_sdk(monkeypatch)
    monkeypatch.setattr(ca, "_load_model_prefs", lambda: {
        "preferred_model": "gpt-9000-does-not-exist",
        "allow_sdk_default_fallback": False})
    client = _FakeAsyncCodex()
    with pytest.raises(RuntimeError, match="allow_sdk_default_fallback is false"):
        asyncio.run(ca._resolve_model(client, None))


def test_resolve_model_uses_sdk_default_when_nothing_configured(monkeypatch):
    _install_fake_sdk(monkeypatch)
    monkeypatch.setattr(ca, "_load_model_prefs", lambda: {})
    client = _FakeAsyncCodex()
    model, reason = asyncio.run(ca._resolve_model(client, None))
    assert model == "gpt-5.5"
    assert "no preferred_model configured" in reason


def test_resolve_model_raises_when_sdk_reports_no_models(monkeypatch):
    _install_fake_sdk(monkeypatch)
    client = _FakeAsyncCodex()
    client.available_models = []
    with pytest.raises(RuntimeError, match="no models at all"):
        asyncio.run(ca._resolve_model(client, None))


def test_start_session_records_model_and_selection_reason(harness):
    h, store = harness
    session_id = asyncio.run(h.start_session(_start()))
    events = store.events_since(session_id, 0)
    started = next(e for e in events if e.type == "session_started")
    assert started.payload["model"] == "gpt-5.5"
    assert "model_selection_reason" in started.payload


# ---- no duplicate assistant output, no duplicate terminal failures --------
# Real bugs found by inspecting an actual live turn's event sequence: the
# SDK can emit both streaming deltas AND a completed item with the SAME full
# text for one message, and a failed turn can emit both ErrorNotification
# and TurnCompletedNotification(status=failed) for the SAME failure.

# NOTE: _translate() dispatches on type(notif).__name__ (a real, exact
# string match against the real SDK's class names — never on message text).
# These fakes are named to match EXACTLY for that reason; only the wrapper
# notification classes need the real name, the detail objects they carry
# (item/error/turn) are accessed by attribute, not by class name.

class AgentMessageDeltaNotification:
    def __init__(self, item_id, delta):
        self.item_id = item_id
        self.thread_id = "t1"
        self.turn_id = "tu1"
        self.delta = delta


class _FakeAgentMessageItem:
    type = "agentMessage"

    def __init__(self, item_id, text):
        self.id = item_id
        self.text = text


class ItemCompletedNotification:
    def __init__(self, item):
        self.item = item
        self.thread_id = "t1"
        self.turn_id = "tu1"
        self.completed_at_ms = 0


class _FakeTurnError:
    def __init__(self, message):
        self.message = message
        self.additional_details = None
        self.codex_error_info = None


class ErrorNotification:
    def __init__(self, message, will_retry):
        self.error = _FakeTurnError(message)
        self.thread_id = "t1"
        self.turn_id = "tu1"
        self.will_retry = will_retry


class _FakeTurn:
    def __init__(self, status):
        self.status = status


class TurnCompletedNotification:
    def __init__(self, status):
        self.turn = _FakeTurn(status)
        self.thread_id = "t1"


def test_assistant_message_not_duplicated_when_deltas_preceded_it():
    state = ca._TurnState()
    delta_events = ca._translate(AgentMessageDeltaNotification("m1", "Hello"), state)
    assert [e.type for e in delta_events] == ["assistant_delta"]

    completed_events = ca._translate(
        ItemCompletedNotification(_FakeAgentMessageItem("m1", "Hello")), state)
    assert completed_events == []   # never re-emitted — already streamed


def test_assistant_message_emitted_when_no_deltas_preceded_it():
    """A real possibility: not every response necessarily streams — the
    completed item may be the ONLY representation of that message, and
    must NOT be dropped."""
    state = ca._TurnState()
    completed_events = ca._translate(
        ItemCompletedNotification(_FakeAgentMessageItem("m2", "Hi there")), state)
    assert [e.type for e in completed_events] == ["assistant_message"]
    assert completed_events[0].payload["text"] == "Hi there"


def test_terminal_failure_emitted_once_when_error_and_turncompleted_both_fire():
    state = ca._TurnState()
    error_events = ca._translate(ErrorNotification("boom", will_retry=False), state)
    assert [e.type for e in error_events] == ["session_failed"]

    completed_events = ca._translate(TurnCompletedNotification("failed"), state)
    assert completed_events == []   # duplicate terminal event suppressed


def test_retryable_error_does_not_suppress_the_real_terminal_failure():
    state = ca._TurnState()
    error_events = ca._translate(ErrorNotification("transient", will_retry=True), state)
    assert [e.type for e in error_events] == ["warning"]
    assert state.terminal_emitted is False   # a retryable error is NOT terminal

    completed_events = ca._translate(TurnCompletedNotification("failed"), state)
    assert [e.type for e in completed_events] == ["session_failed"]


def test_translate_defaults_to_a_fresh_state_when_omitted():
    """Every single-notification test elsewhere in this file calls
    _translate(notif) with no state — proves that still works standalone
    (each call gets its own throwaway _TurnState, no cross-call dedup)."""
    first = ca._translate(ItemCompletedNotification(_FakeAgentMessageItem("m3", "one")))
    second = ca._translate(ItemCompletedNotification(_FakeAgentMessageItem("m3", "one")))
    assert [e.type for e in first] == ["assistant_message"]
    assert [e.type for e in second] == ["assistant_message"]   # NOT deduped — no shared state


# ---- truthful approval capability ------------------------------------------

def test_codex_declares_interactive_approvals_false():
    """A real, queryable capability (not a UI-only assumption) — the pinned
    SDK exposes no hook to causally resolve a Guardian review."""
    assert ca.CodexAgentHarness.interactive_approvals is False


def test_registry_surfaces_interactive_approvals_capability():
    from command_center.agent_sessions.registry import default_registry
    from command_center.agent_sessions.store import SessionStore as _Store
    import asyncio as _asyncio

    reg = default_registry(_Store())
    probes = {p["harness_id"]: p for p in _asyncio.run(reg.probes())}
    assert probes["codex_agent"]["interactive_approvals"] is False
    assert probes["fake"]["interactive_approvals"] is True   # genuinely does resolve


# ---- shutdown cleans up the real subprocess connection ---------------------

def test_shutdown_closes_the_client_and_clears_state(harness):
    h, store = harness

    async def _impl():
        await h.start_session(_start())
        client = await h._client_ready()
        await h.shutdown()
        return client

    client = asyncio.run(_impl())
    assert client.closed is True
    assert h._client is None
    assert h._active_turns == {}


def test_shutdown_interrupts_active_turns_before_closing(harness):
    h, store = harness

    async def _impl():
        session_id = await h.start_session(_start())
        client = await h._client_ready()
        thread = client.threads[store.get(session_id).external_session_id]
        thread.notifications = [_UnmappedForShutdownTest()]
        gen = h.send(session_id, "long running")
        await gen.__anext__()   # generator suspended, turn genuinely active
        handle = h._active_turns[session_id]
        await h.shutdown()
        await gen.aclose()
        return handle, client

    handle, client = asyncio.run(_impl())
    assert handle.interrupted is True
    assert client.closed is True


class _UnmappedForShutdownTest:
    pass


def test_shutdown_is_safe_when_no_client_was_ever_constructed():
    h = ca.CodexAgentHarness(SessionStore())
    asyncio.run(h.shutdown())   # must not raise


def test_shutdown_is_safe_when_client_close_raises(monkeypatch, harness):
    h, store = harness

    async def _impl():
        await h.start_session(_start())
        client = await h._client_ready()

        async def _broken_close():
            raise RuntimeError("subprocess already gone")
        client.close = _broken_close
        await h.shutdown()   # must not raise despite close() failing

    asyncio.run(_impl())
    assert h._client is None   # still cleared even though close() raised
