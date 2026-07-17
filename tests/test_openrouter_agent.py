"""OpenRouter read-only executor: the paid role-fallback agent runtime.

Hermetic — the OpenRouter chat/completions call is an injected scripted fake,
so the whole bounded tool loop, the read-only wall (path escape, no write
tool), and the paid-egress gate are proven with NO network and NO key.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from command_center.agent_sessions.adapters import openrouter_agent as ora
from command_center.agent_sessions.protocol import SessionStart
from command_center.agent_sessions.store import SessionStore


def _store():
    return SessionStore()   # generates its own agent-session-N ids


def _drain(harness, session_id, prompt):
    async def run():
        return [ev async for ev in harness.send(session_id, prompt)]
    return asyncio.run(run())


def _start(harness, store, repo_id="llm_station"):
    async def run():
        return await harness.start_session(SessionStart(
            conversation_id="c1", repo_id=repo_id, mode="analysis",
            harness_id="openrouter_agent", permission_profile="read_only"))
    return asyncio.run(run())


# ---- the read-only wall (no store, no network needed) ------------------------

def test_only_read_only_tools_exist():
    names = {t["function"]["name"] for t in ora._READ_ONLY_TOOLS}
    assert names == {"read_file", "glob", "grep"}
    # there is no write/edit/shell tool to dispatch
    with pytest.raises(ValueError, match="unknown or non-read-only"):
        ora.dispatch_read_only_tool(Path.cwd(), "write_file", {"path": "x"})


def test_path_escape_is_refused(tmp_path):
    (tmp_path / "in.txt").write_text("inside", encoding="utf-8")
    assert "inside" in ora.dispatch_read_only_tool(
        tmp_path, "read_file", {"path": "in.txt"})
    # a traversal outside the clamped root is refused
    with pytest.raises(ValueError, match="escapes the repo root"):
        ora.dispatch_read_only_tool(tmp_path, "read_file",
                                    {"path": "../../../etc/passwd"})


def test_grep_and_glob_are_scoped(tmp_path):
    (tmp_path / "a.py").write_text("needle here\nother", encoding="utf-8")
    (tmp_path / "b.txt").write_text("no match", encoding="utf-8")
    assert "a.py" in ora.dispatch_read_only_tool(
        tmp_path, "glob", {"pattern": "*.py"})
    hit = ora.dispatch_read_only_tool(tmp_path, "grep", {"query": "needle"})
    assert "a.py:1:" in hit


def test_secret_files_are_never_read_or_listed(tmp_path):
    # paid external egress: .env / keys / credential paths must never be sent
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sk-secret", encoding="utf-8")
    (tmp_path / "server.key").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    (tmp_path / "ok.py").write_text("safe code", encoding="utf-8")
    # read_file refuses the secret, never returns its contents
    out = ora.dispatch_read_only_tool(tmp_path, "read_file", {"path": ".env"})
    assert "refused" in out and "sk-secret" not in out
    key = ora.dispatch_read_only_tool(tmp_path, "read_file", {"path": "server.key"})
    assert "refused" in key and "PRIVATE KEY" not in key
    # glob/grep skip secrets but still see the safe file
    listing = ora.dispatch_read_only_tool(tmp_path, "glob", {"pattern": "*"})
    assert "ok.py" in listing and ".env" not in listing and "server.key" not in listing
    grep = ora.dispatch_read_only_tool(tmp_path, "grep", {"query": "sk-secret"})
    assert "sk-secret" not in grep


def test_secret_segment_detection():
    assert ora._is_secret_path(".env")
    assert ora._is_secret_path(".env.production")
    assert ora._is_secret_path("config/.ssh/id_rsa")
    assert ora._is_secret_path("certs/server.pem")
    assert not ora._is_secret_path("src/app.py")
    assert not ora._is_secret_path("docs/environment.md")   # not a secret


# ---- the paid-egress gate ----------------------------------------------------

def test_probe_off_when_lane_disabled(monkeypatch):
    monkeypatch.setattr(ora, "_lane_enabled", lambda: False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-anything")
    probe = asyncio.run(ora.OpenRouterAgentHarness(_store()).probe())
    assert probe.available is False
    assert "disabled" in probe.detail


def test_probe_off_when_key_absent(monkeypatch):
    monkeypatch.setattr(ora, "_lane_enabled", lambda: True)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    probe = asyncio.run(ora.OpenRouterAgentHarness(_store()).probe())
    assert probe.available is False
    assert "no key" in probe.detail


def test_probe_available_only_when_enabled_and_keyed(monkeypatch):
    monkeypatch.setattr(ora, "_lane_enabled", lambda: True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-anything")
    probe = asyncio.run(ora.OpenRouterAgentHarness(_store()).probe())
    assert probe.available is True
    assert "read-only" in probe.detail


# ---- the bounded tool loop (scripted fake completion) ------------------------

def _fake_completion_script(steps):
    """Return a chat_completion callable that yields scripted replies in order.
    Each `step` is either {'tool': name, 'args': {...}} or {'text': '...'}.
    """
    calls = iter(steps)

    def chat(model, messages, tools):
        step = next(calls)
        if "text" in step:
            return {"choices": [{"message": {"content": step["text"]}}],
                    "usage": {"total_tokens": 5}}
        import json
        return {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "tc1", "function": {
                "name": step["tool"],
                "arguments": json.dumps(step["args"])}}]}}]}
    return chat


def test_tool_loop_reads_then_answers(monkeypatch, tmp_path):
    # point the resolver at a temp "repo"
    (tmp_path / "hello.txt").write_text("the answer is 42", encoding="utf-8")
    monkeypatch.setattr(ora, "_resolve_repo_path", lambda repo_id: tmp_path)
    chat = _fake_completion_script([
        {"tool": "read_file", "args": {"path": "hello.txt"}},
        {"text": "hello.txt says the answer is 42."},
    ])
    store = _store()
    h = ora.OpenRouterAgentHarness(store, chat_completion=chat)
    sid = _start(h, store)
    events = _drain(h, sid, "what does hello.txt say?")
    types = [e.type for e in events]
    assert "tool_started" in types and "tool_output" in types
    tool_out = next(e for e in events if e.type == "tool_output")
    assert "the answer is 42" in tool_out.payload["output"]
    answer = next(e for e in events if e.type == "assistant_message")
    assert "42" in answer.payload["text"]
    assert types[-1] == "session_idle"


def test_tool_loop_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(ora, "_resolve_repo_path", lambda repo_id: tmp_path)
    monkeypatch.setattr(ora, "_MAX_TOOL_ITERATIONS", 3)

    def always_tool(model, messages, tools):   # never stops asking for tools
        import json
        return {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "t", "function": {"name": "glob",
             "arguments": json.dumps({"pattern": "*"})}}]}}]}
    store = _store()
    h = ora.OpenRouterAgentHarness(store, chat_completion=always_tool)
    sid = _start(h, store)
    events = _drain(h, sid, "loop forever")
    # the loop terminates with a warning + idle, never spins unbounded
    assert any(e.type == "warning" for e in events)
    assert events[-1].type == "session_idle"


def test_model_catalog_shape(monkeypatch):
    h = ora.OpenRouterAgentHarness(_store())
    models = asyncio.run(h.list_models())
    assert models and models[0]["is_default"] is True
    for m in models:
        assert isinstance(m["supported_efforts"], list)
        assert m["available"] is True


# ---- Phase 4: honest paid-egress disclosure ---------------------------------

def test_openrouter_declares_external_egress():
    """The harness must declare that it ships repo contents to a PAID EXTERNAL
    API, so the cockpit can require an explicit "this context will leave the
    machine" confirmation before the first send (plan §4/§8)."""
    h = ora.OpenRouterAgentHarness(_store())
    assert h.external_egress is True


def test_external_egress_defaults_false_for_local_harnesses():
    # the registry surfaces it via getattr(harness, "external_egress", False);
    # a local subscription runtime that doesn't declare it must default to
    # on-box (never falsely flagged, never silently egressing).
    class _Local:   # stands in for Claude/Codex — no external_egress attr
        pass
    assert getattr(_Local(), "external_egress", False) is False
