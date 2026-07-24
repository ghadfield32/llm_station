"""ClaudeCodeLocalHarness — hermetic tests. The single subprocess seam
(`_stream_cli`) is overridden to yield fake stream-json objects (the EXACT
shapes captured live from `claude` v2.1.207 — system/rate_limit_event/assistant/
result), so translation, session capture, read-only flag construction, the
ANTHROPIC_API_KEY-stripping env, and honest subscription-cost handling are all
proven without spawning the real CLI or consuming quota. A separate LIVE proof
(real `claude -p`, zero-mutation) is recorded in WORKLOG.md.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from command_center.agent_sessions.adapters import claude_code_local as ccl
from command_center.agent_sessions.protocol import (
    AgentHarness,
    ApprovalDecision,
    SessionStart,
)
from command_center.agent_sessions.store import SessionStore


# real captured envelope shapes (v2.1.207)
_SYSTEM_INIT = {"type": "system", "subtype": "init", "session_id": "sess-abc",
                "apiKeySource": "none", "model": "claude-opus-4-8"}
_RATE_LIMIT = {"type": "rate_limit_event", "session_id": "sess-abc",
               "rate_limit_info": {"status": "allowed", "resetsAt": 1783896000,
                                   "rateLimitType": "five_hour",
                                   "overageStatus": "rejected"}}
_RESULT_OK = {"type": "result", "subtype": "success", "is_error": False,
              "session_id": "sess-abc", "total_cost_usd": 0.19, "num_turns": 1,
              "duration_ms": 1350, "usage": {"input_tokens": 2},
              "modelUsage": {}}


def _assistant(*blocks):
    return {"type": "assistant", "session_id": "sess-abc",
            "message": {"content": list(blocks)}}


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(ccl, "_claude_bin", lambda: "/usr/bin/claude")
    monkeypatch.setattr(ccl, "_resolve_repo_path", lambda repo_id: Path("/tmp/fake-repo"))
    monkeypatch.setattr(ccl, "_load_model_prefs", lambda: {})
    return ccl.ClaudeCodeLocalHarness(SessionStore()), SessionStore()


def _start(mode="analysis", permission_profile="read_only"):
    return SessionStart(conversation_id="c1", repo_id="r1", mode=mode,
                        harness_id="claude_code_local", permission_profile=permission_profile)


async def _drain(gen):
    return [e async for e in gen]


def _fake_stream(objs, captured=None):
    async def _gen(self, session_id, args, cwd, env, prompt):
        if captured is not None:
            captured["args"] = args
            captured["prompt"] = prompt
        for o in objs:
            yield o
    return _gen


# ---- protocol / pure translation --------------------------------------------

def test_satisfies_protocol_and_names_local_lane(harness):
    h, _ = harness
    assert isinstance(h, AgentHarness)
    assert h.name == "claude_code_local"
    assert h.interactive_approvals is False


def test_translate_system_init_is_silent():
    assert ccl._translate_line(_SYSTEM_INIT) == []


def test_translate_rate_limit_normalizes_camelcase_to_snake():
    evs = ccl._translate_line(_RATE_LIMIT)
    assert len(evs) == 1 and evs[0].type == "rate_limit"
    p = evs[0].payload
    assert p["status"] == "allowed"
    assert p["rate_limit_type"] == "five_hour"    # rateLimitType -> rate_limit_type
    assert p["resets_at"] == 1783896000            # resetsAt -> resets_at
    assert p["utilization"] is None                # CLI omits it


def test_translate_assistant_text_and_tools():
    evs = ccl._translate_line(_assistant(
        {"type": "text", "text": "analysis"},
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a"}},
        {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls"}}))
    kinds = [e.type for e in evs]
    assert kinds == ["assistant_message", "tool_started", "command_started"]


def test_translate_result_success_is_usage_then_idle_with_honest_cost():
    evs = ccl._translate_line(_RESULT_OK)
    assert [e.type for e in evs] == ["usage", "session_idle"]
    usage = evs[0].payload
    assert usage["cost_usd"] is None                         # subscription: no real $ spend
    assert usage["cost_source"] == "subscription_not_metered"
    assert usage["api_equivalent_cost_usd"] == 0.19          # reported cost kept, labeled


def test_translate_result_error_is_session_failed():
    evs = ccl._translate_line({"type": "result", "is_error": True,
                               "subtype": "error_max_turns", "total_cost_usd": 0.0})
    assert evs[-1].type == "session_failed"
    assert "error_max_turns" in evs[-1].payload["reason"]


def test_translate_exit_error_and_unmapped():
    ex = ccl._translate_line({"type": "_exit_error", "returncode": 2, "stderr": "boom"})
    assert ex[0].type == "session_failed" and "boom" in ex[0].payload["reason"]
    un = ccl._translate_line({"type": "mystery"})
    assert un[0].type == "warning" and un[0].payload["unmapped_type"] == "mystery"


# ---- read-only flag construction + env --------------------------------------

def test_build_args_is_defense_in_depth_read_only(harness):
    h, _ = harness
    rec = h.store.create_session(harness=h.name, conversation_id="c", repo_id="r",
                                 model="opus")
    args = h._build_args("/usr/bin/claude", rec, Path("/repo"))
    assert "-p" in args
    # capability restriction + writelist + planning mode + MCP isolation
    assert args[args.index("--tools") + 1:args.index("--tools") + 4] == ["Read", "Glob", "Grep"]
    for w in ("Write", "Edit", "Bash", "WebFetch"):
        assert w in args
    assert "--permission-mode" in args and args[args.index("--permission-mode") + 1] == "plan"
    assert "--strict-mcp-config" in args
    assert "--disable-slash-commands" in args
    assert "--bare" not in args                     # never — it forces API-key auth
    assert args[args.index("--model") + 1] == "opus"
    assert "--resume" not in args                   # fresh session, no external id yet


def test_build_args_resumes_when_external_session_id_present(harness):
    h, _ = harness
    rec = h.store.create_session(harness=h.name, conversation_id="c", repo_id="r")
    h.store.update_session(rec.session_id, external_session_id="sess-xyz")
    rec = h.store.get(rec.session_id)
    args = h._build_args("/usr/bin/claude", rec, Path("/repo"))
    assert args[args.index("--resume") + 1] == "sess-xyz"


def test_subprocess_env_strips_anthropic_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-removed")
    monkeypatch.setenv("PATH_SENTINEL", "keep-me")
    env = ccl._subprocess_env()
    assert "ANTHROPIC_API_KEY" not in env      # forces subscription, never metered API
    assert env.get("PATH_SENTINEL") == "keep-me"


# ---- probe ------------------------------------------------------------------

def test_probe_unavailable_when_cli_absent(monkeypatch):
    monkeypatch.setattr(ccl, "_claude_bin", lambda: None)
    p = asyncio.run(ccl.ClaudeCodeLocalHarness(SessionStore()).probe())
    assert p.available is False and "claude CLI not found" in p.detail


def test_probe_unavailable_when_not_logged_in(monkeypatch):
    monkeypatch.setattr(ccl, "_claude_bin", lambda: "/usr/bin/claude")
    monkeypatch.setattr(ccl.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": '{"loggedIn": false}'})())
    p = asyncio.run(ccl.ClaudeCodeLocalHarness(SessionStore()).probe())
    assert p.available is False and "not logged in" in p.detail


def test_probe_available_when_logged_in_no_secret(monkeypatch):
    monkeypatch.setattr(ccl, "_claude_bin", lambda: "/usr/bin/claude")
    out = '{"loggedIn": true, "authMethod": "claude.ai", "subscriptionType": "max", "email": "x@y.z"}'
    monkeypatch.setattr(ccl.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": out})())
    p = asyncio.run(ccl.ClaudeCodeLocalHarness(SessionStore()).probe())
    assert p.available is True
    assert "claude.ai" in p.detail and "max" in p.detail
    assert "x@y.z" not in p.detail          # email (PII) never surfaced


# ---- start / send / lifecycle -----------------------------------------------

def test_rejects_non_analysis_and_non_read_only(harness):
    h, _ = harness
    with pytest.raises(RuntimeError, match="analysis"):
        asyncio.run(h.start_session(_start(mode="workspace")))
    with pytest.raises(RuntimeError, match="read_only"):
        asyncio.run(h.start_session(_start(permission_profile="workspace_write")))


def test_start_session_records_subscription_auth_and_read_only(harness):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    ev = h.store.events_since(sid)[0]
    assert ev.type == "session_started"
    assert ev.payload["auth"] == "subscription_oauth"
    assert ev.payload["read_only_tools"] == ["Read", "Glob", "Grep"]
    assert h.store.get(sid).status == "idle"


def test_send_translates_stream_and_captures_session_id(harness, monkeypatch):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    stream = [_SYSTEM_INIT, _RATE_LIMIT,
              _assistant({"type": "text", "text": "done"}), _RESULT_OK]
    monkeypatch.setattr(ccl.ClaudeCodeLocalHarness, "_stream_cli", _fake_stream(stream))
    events = asyncio.run(_drain(h.send(sid, "analyze")))
    kinds = [e.type for e in events]
    assert "rate_limit" in kinds and "assistant_message" in kinds
    assert kinds[-1] == "session_idle"
    # external session id captured from the init event's session_id
    assert h.store.get(sid).external_session_id == "sess-abc"


def test_long_prompt_goes_to_stdin_not_argv(harness, monkeypatch):
    """Regression (2026-07-17): a ~40 KB paste as an argv element blew past the
    Windows 32,767-char command-line limit ('The command line is too long.').
    The prompt must ride stdin; argv must stay small and prompt-free."""
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    big = "SmartLine plan " * 3000            # ~45 KB, far over the Windows cap
    captured: dict = {}
    monkeypatch.setattr(ccl.ClaudeCodeLocalHarness, "_stream_cli",
                        _fake_stream([_RESULT_OK], captured))
    asyncio.run(_drain(h.send(sid, big)))
    assert captured["prompt"].endswith(big)                # full prompt via stdin
    assert "[WORKSPACE BOUNDS" in captured["prompt"]      # first-turn contract
    joined = "\x00".join(captured["args"])
    assert big not in joined                                # never in argv
    assert len("\x00".join(captured["args"])) < 4096        # argv stays small
    assert "-p" in captured["args"]


def test_interrupt_terminates_the_active_proc(harness):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))

    class _FakeProc:
        returncode = None
        def __init__(self): self.terminated = False
        def terminate(self): self.terminated = True

    proc = _FakeProc()
    h._active_procs[sid] = proc
    asyncio.run(h.interrupt(sid))
    assert proc.terminated is True


def test_resolve_approval_is_informational_only(harness):
    h, _ = harness
    sid = asyncio.run(h.start_session(_start()))
    ap = h.store.create_approval(sid, "write")
    asyncio.run(h.resolve_approval(sid, ApprovalDecision(ap.approval_id, True, "ok")))
    ev = h.store.events_since(sid)[-1]
    assert ev.type == "approval_resolved" and ev.payload["effective"] is False
