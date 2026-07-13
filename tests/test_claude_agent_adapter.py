"""ClaudeAgentHarness — hermetic unit tests against a FAKE claude_agent_sdk
(installed into sys.modules, never the real package/network/API key). A live
end-to-end run is DEFERRED (needs ANTHROPIC_API_KEY + --allow-agent-session-egress,
neither on the build host) — see WORKLOG.md "Agent-session chat integration".

Covers: SDK-absent + key-absent probes, analysis-only / read_only-only rejection,
the THREE defense-in-depth read-only layers (allowed_tools + disallowed_tools + a
deny-by-default can_use_tool that actually allows Read/Glob/Grep and denies
Write/Bash) + isolation (setting_sources None, empty mcp/plugins), message->event
translation (text, tool-use, bash, result success/failure), RateLimitEvent ->
`rate_limit` event, unmapped type -> warning, external session id capture + reuse,
resume-after-restart via options.resume, interrupt reaching the client, cost
capture, no secret in probe output, and close() disconnecting.

asyncio.run() inside sync tests — the repo convention (no pytest-asyncio).
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from command_center.agent_sessions.adapters import claude_agent as cla
from command_center.agent_sessions.protocol import (
    AgentHarness,
    ApprovalDecision,
    SessionStart,
)
from command_center.agent_sessions.store import SessionStore


# ---- fake claude_agent_sdk (named classes: adapter dispatches on __name__) ----

class TextBlock:
    def __init__(self, text): self.text = text


class ToolUseBlock:
    def __init__(self, id, name, input): self.id = id; self.name = name; self.input = input


class ToolResultBlock:
    def __init__(self, tool_use_id, is_error=False):
        self.tool_use_id = tool_use_id; self.is_error = is_error


class ThinkingBlock:
    def __init__(self, thinking="..."): self.thinking = thinking


class AssistantMessage:
    def __init__(self, content, session_id="claude-sess-1"):
        self.content = content; self.session_id = session_id


class SystemMessage:
    def __init__(self, subtype="init", data=None, session_id="claude-sess-1"):
        self.subtype = subtype; self.data = data or {}; self.session_id = session_id


class UserMessage:
    def __init__(self, content=None): self.content = content


class ResultMessage:
    def __init__(self, is_error=False, session_id="claude-sess-1",
                 total_cost_usd=0.03, usage=None, errors=None, subtype="success"):
        self.is_error = is_error; self.session_id = session_id
        self.total_cost_usd = total_cost_usd; self.usage = usage or {"input_tokens": 10}
        self.errors = errors; self.subtype = subtype
        self.num_turns = 1; self.duration_ms = 100; self.model_usage = {}


class RateLimitInfo:
    def __init__(self, status="allowed_warning", rate_limit_type="five_hour",
                 utilization=0.8, resets_at=1783861277):
        self.status = status; self.rate_limit_type = rate_limit_type
        self.utilization = utilization; self.resets_at = resets_at
        self.overage_status = None; self.overage_resets_at = None
        self.overage_disabled_reason = None


class RateLimitEvent:
    def __init__(self, rate_limit_info=None, session_id="claude-sess-1"):
        self.rate_limit_info = rate_limit_info or RateLimitInfo()
        self.session_id = session_id; self.uuid = "u1"


class _Unmapped:
    """Deliberately not a known message type -> must become a `warning`."""


class PermissionResultAllow:
    def __init__(self, updated_input=None, updated_permissions=None):
        self.behavior = "allow"


class PermissionResultDeny:
    def __init__(self, message="", interrupt=False):
        self.behavior = "deny"; self.message = message; self.interrupt = interrupt


class ClaudeAgentOptions:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.kw = kw


class _FakeClient:
    # messages the next receive_response() will yield — set per test
    messages: list = []

    def __init__(self, options=None, transport=None):
        self.options = options
        self.connected = False
        self.disconnected = False
        self.interrupted = False
        self.queries: list[str] = []

    async def connect(self, prompt=None): self.connected = True

    async def query(self, prompt, session_id="default"): self.queries.append(prompt)

    async def receive_response(self):
        for m in type(self).messages:
            yield m

    async def interrupt(self): self.interrupted = True

    async def disconnect(self): self.disconnected = True


def _install_fake_sdk(monkeypatch, *, messages=None):
    _FakeClient.messages = messages or []
    fake = types.SimpleNamespace(
        ClaudeAgentOptions=ClaudeAgentOptions, ClaudeSDKClient=_FakeClient,
        PermissionResultAllow=PermissionResultAllow,
        PermissionResultDeny=PermissionResultDeny)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)
    return fake


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    _install_fake_sdk(monkeypatch)
    monkeypatch.setattr(cla, "_resolve_repo_path", lambda repo_id: Path("/tmp/fake-repo"))
    monkeypatch.setattr(cla, "_load_model_prefs", lambda: {})
    store = SessionStore()
    return cla.ClaudeAgentHarness(store), store


def _start(mode="analysis", permission_profile="read_only"):
    return SessionStart(conversation_id="c1", repo_id="r1", mode=mode,
                        harness_id="claude_agent", permission_profile=permission_profile)


async def _drain(gen):
    return [e async for e in gen]


# ---- protocol conformance ---------------------------------------------------

def test_satisfies_agent_harness_protocol(harness):
    h, _ = harness
    assert isinstance(h, AgentHarness)
    assert h.name == "claude_agent"
    assert h.interactive_approvals is False


# ---- probe ------------------------------------------------------------------

def test_probe_unavailable_when_sdk_absent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    h = cla.ClaudeAgentHarness(SessionStore())
    probe = asyncio.run(h.probe())
    assert probe.available is False
    assert "claude-agent-sdk" in probe.detail


def test_probe_unavailable_and_no_secret_when_key_absent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _install_fake_sdk(monkeypatch)
    h = cla.ClaudeAgentHarness(SessionStore())
    probe = asyncio.run(h.probe())
    assert probe.available is False
    assert "ANTHROPIC_API_KEY" in probe.detail


def test_probe_available_with_sdk_and_key_leaks_no_secret(harness):
    h, _ = harness
    probe = asyncio.run(h.probe())
    assert probe.available is True
    assert "sk-test-not-real" not in probe.detail


# ---- mode / permission gating -----------------------------------------------

def test_rejects_non_analysis_mode(harness):
    h, _ = harness
    with pytest.raises(RuntimeError, match="analysis"):
        asyncio.run(h.start_session(_start(mode="workspace")))


def test_rejects_non_read_only_permission(harness):
    h, _ = harness
    with pytest.raises(RuntimeError, match="read_only"):
        asyncio.run(h.start_session(_start(permission_profile="workspace_write")))


def test_start_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _install_fake_sdk(monkeypatch)
    monkeypatch.setattr(cla, "_resolve_repo_path", lambda repo_id: Path("/tmp/r"))
    h = cla.ClaudeAgentHarness(SessionStore())
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        asyncio.run(h.start_session(_start()))


# ---- defense-in-depth read-only config --------------------------------------

def test_start_builds_defense_in_depth_read_only_options(harness):
    h, store = harness
    sid = asyncio.run(h.start_session(_start()))
    client = h._clients[sid]
    opts = client.options
    assert set(opts.allowed_tools) == {"Read", "Glob", "Grep"}
    for w in ("Write", "Edit", "Bash", "WebFetch"):
        assert w in opts.disallowed_tools
    assert opts.can_use_tool is not None
    assert opts.setting_sources is None          # isolated
    assert opts.mcp_servers == {} and opts.plugins == []
    assert client.connected is True
    # session_started event records the read-only contract
    ev = store.events_since(sid)[0]
    assert ev.type == "session_started"
    assert ev.payload["permission_profile"] == "read_only"
    assert ev.payload["auth"] == "anthropic_api_key"
    assert store.get(sid).status == "idle"


def test_can_use_tool_allows_reads_and_denies_writes(harness):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    gate = h._clients[sid].options.can_use_tool
    allow = asyncio.run(gate("Read", {}, None))
    assert allow.behavior == "allow"
    deny = asyncio.run(gate("Bash", {"command": "rm -rf /"}, None))
    assert deny.behavior == "deny"
    assert "read-only" in deny.message
    assert asyncio.run(gate("Write", {}, None)).behavior == "deny"


# ---- send / translation -----------------------------------------------------

def _run_turn(h, sid, messages, monkeypatch):
    _FakeClient.messages = messages
    return asyncio.run(_drain(h.send(sid, "analyze the repo")))


def test_send_translates_text_tooluse_and_result(harness, monkeypatch):
    h, store = harness
    sid = asyncio.run(h.start_session(_start()))
    msgs = [
        AssistantMessage([TextBlock("Here is my analysis."),
                          ToolUseBlock("t1", "Read", {"file_path": "a.py"}),
                          ToolUseBlock("t2", "Bash", {"command": "ls"}),
                          ThinkingBlock("internal")]),
        ResultMessage(is_error=False, total_cost_usd=0.05),
    ]
    events = _run_turn(h, sid, msgs, monkeypatch)
    types_seen = [e.type for e in events]
    assert "assistant_message" in types_seen
    assert "tool_started" in types_seen        # Read
    assert "command_started" in types_seen      # Bash mapped to command
    assert types_seen[-1] == "session_idle"
    assert "usage" in types_seen
    # external session id + cost captured onto the record
    rec = store.get(sid)
    assert rec.external_session_id == "claude-sess-1"
    assert rec.cost_usd == 0.05


def test_send_failure_result_becomes_session_failed(harness, monkeypatch):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    events = _run_turn(h, sid, [ResultMessage(is_error=True, errors=["boom"])], monkeypatch)
    assert events[-1].type == "session_failed"
    assert "boom" in events[-1].payload["reason"]


def test_rate_limit_event_becomes_rate_limit_event(harness, monkeypatch):
    h, store = harness
    sid = asyncio.run(h.start_session(_start()))
    info = RateLimitInfo(status="allowed_warning", rate_limit_type="seven_day_sonnet",
                         utilization=0.83, resets_at=1783861277)
    events = _run_turn(h, sid, [RateLimitEvent(info), ResultMessage()], monkeypatch)
    rl = next(e for e in events if e.type == "rate_limit")
    assert rl.payload["status"] == "allowed_warning"
    assert rl.payload["rate_limit_type"] == "seven_day_sonnet"
    assert rl.payload["utilization"] == 0.83


def test_unmapped_message_becomes_warning(harness, monkeypatch):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    events = _run_turn(h, sid, [_Unmapped()], monkeypatch)
    assert events[0].type == "warning"
    assert events[0].payload["unmapped_type"] == "_Unmapped"


# ---- session reuse / resume / lifecycle -------------------------------------

def test_followup_reuses_the_same_client(harness, monkeypatch):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    first_client = h._clients[sid]
    _run_turn(h, sid, [ResultMessage()], monkeypatch)
    _run_turn(h, sid, [ResultMessage()], monkeypatch)
    assert h._clients[sid] is first_client       # same session, one client


def test_resume_after_restart_passes_external_id_to_options(harness, monkeypatch):
    h, store = harness
    sid = asyncio.run(h.start_session(_start()))
    _run_turn(h, sid, [ResultMessage(session_id="claude-sess-9")], monkeypatch)
    assert store.get(sid).external_session_id == "claude-sess-9"
    # a FRESH harness instance (simulated worker restart) rebuilds the client
    # with resume=external_session_id — never forks a new Claude session
    h2 = cla.ClaudeAgentHarness(store)
    client = asyncio.run(h2._ensure_client(sid))
    assert client.options.resume == "claude-sess-9"


def test_interrupt_reaches_the_client(harness):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    asyncio.run(h.interrupt(sid))
    assert h._clients[sid].interrupted is True


def test_close_disconnects_and_marks_closed(harness):
    h, store = harness
    sid = asyncio.run(h.start_session(_start()))
    client = h._clients[sid]
    asyncio.run(h.close(sid))
    assert client.disconnected is True
    assert store.get(sid).status == "closed"
    assert sid not in h._clients


def test_resolve_approval_is_recorded_as_informational_only(harness):
    h, store = harness
    sid = asyncio.run(h.start_session(_start()))
    approval = store.create_approval(sid, "some-write")
    asyncio.run(h.resolve_approval(sid, ApprovalDecision(approval.approval_id, True, "ok")))
    ev = store.events_since(sid)[-1]
    assert ev.type == "approval_resolved"
    assert ev.payload["effective"] is False
