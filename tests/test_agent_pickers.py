"""Runtime→model→effort picker plumbing + the Claude collector runtime-id fix.
Hermetic: fake SDKs in sys.modules, no real CLI/network.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from command_center.agent_sessions.adapters import claude_agent as cla
from command_center.agent_sessions.adapters import claude_code_local as ccl
from command_center.agent_sessions.adapters import codex_agent as cx
from command_center.agent_sessions.protocol import SessionStart
from command_center.agent_sessions.store import SessionStore
from command_center.usage.collectors.claude_agent import ClaudeRateLimitCollector


def _start(harness_id, **kw):
    return SessionStart(conversation_id="c1", repo_id="r1", mode="analysis",
                        harness_id=harness_id, permission_profile="read_only", **kw)


# ── Claude collector runtime-id parametrization (the misattribution fix) ──────

def test_collector_attributes_to_the_local_lane_when_asked():
    c = ClaudeRateLimitCollector("claude_code_local")
    assert c.runtime_ids() == ["claude_code_local"]
    c.feed({"status": "allowed_warning", "rate_limit_type": "five_hour",
            "utilization": None, "resets_at": 1783896000})
    r = asyncio.run(c.collect())
    assert r.limits[0].runtime_id == "claude_code_local"
    assert r.availability[0].runtime_id == "claude_code_local"


def test_collector_default_runtime_id_is_unchanged():
    # back-compat: default lane stays claude_agent so existing tests hold
    c = ClaudeRateLimitCollector()
    assert c.runtime_ids() == ["claude_agent"]


# ── claude_code_local: catalog + per-session effort ──────────────────────────

def test_claude_local_model_catalog_has_aliases_and_efforts():
    models = ccl.list_models_catalog()
    ids = {m["id"] for m in models}
    assert {"opus", "sonnet", "haiku"} <= ids
    assert all("low" in m["supported_efforts"] for m in models)
    assert any(m["is_default"] for m in models)


def test_claude_local_effort_reaches_build_args_and_event(monkeypatch):
    monkeypatch.setattr(ccl, "_claude_bin", lambda: "/usr/bin/claude")
    monkeypatch.setattr(ccl, "_resolve_repo_path", lambda repo_id: Path("/tmp/r"))
    monkeypatch.setattr(ccl, "_load_model_prefs", lambda: {})
    h = ccl.ClaudeCodeLocalHarness(SessionStore())
    sid = asyncio.run(h.start_session(_start("claude_code_local", model="opus",
                                             effort="high")))
    rec = h.store.get(sid)
    prompt = "prompt-must-travel-on-stdin"
    args = h._build_args("/usr/bin/claude", rec, Path("/repo"))
    assert prompt not in args
    assert args[args.index("--effort") + 1] == "high"
    ev = h.store.events_since(sid)[0]
    assert ev.payload["requested_effort"] == "high"


# ── codex_agent: catalog (live models() incl. effort) + per-session effort ───

class _FakeModel:
    def __init__(self, mid, is_default=False, hidden=False,
                 supported=("low", "medium", "high"), default="medium"):
        self.id = mid
        self.display_name = mid.upper()
        self.description = "desc"
        self.is_default = is_default
        self.hidden = hidden
        self.supported_reasoning_efforts = [types.SimpleNamespace(value=e) for e in supported]
        self.default_reasoning_effort = types.SimpleNamespace(value=default)


class _FakeModels:
    def __init__(self, models):
        self.data = models


class _FakeCodexConfig:
    def __init__(self, **kw):
        self.kw = kw


class _FakeAsyncCodex:
    last_config = None

    def __init__(self, config=None):
        type(self).last_config = config
        self._models = _FakeModels([
            _FakeModel("gpt-5.5", is_default=True),
            _FakeModel("gpt-5.4"),
            _FakeModel("secret", hidden=True)])

    async def models(self, **kw):
        return self._models

    async def account(self):
        return types.SimpleNamespace(
            account=types.SimpleNamespace(root=types.SimpleNamespace(
                email="x@y.z", plan_type=types.SimpleNamespace(value="prolite"),
                type="chatgpt")))

    async def close(self):
        pass


def _install_codex(monkeypatch):
    fake = types.SimpleNamespace(
        AsyncCodex=_FakeAsyncCodex, CodexConfig=_FakeCodexConfig,
        Sandbox=types.SimpleNamespace(read_only="ro"),
        ApprovalMode=types.SimpleNamespace(deny_all="deny"))
    monkeypatch.setitem(sys.modules, "openai_codex", fake)


def test_codex_model_catalog_drops_hidden_and_carries_efforts(monkeypatch):
    _install_codex(monkeypatch)
    h = cx.CodexAgentHarness(SessionStore())
    models = asyncio.run(h.list_models())
    ids = {m["id"] for m in models}
    assert ids == {"gpt-5.5", "gpt-5.4"}          # hidden dropped
    gpt55 = next(m for m in models if m["id"] == "gpt-5.5")
    assert gpt55["is_default"] is True
    assert gpt55["default_effort"] == "medium"
    assert gpt55["supported_efforts"] == ["low", "medium", "high"]


def test_codex_effort_is_baked_into_client_config(monkeypatch):
    _install_codex(monkeypatch)
    _FakeAsyncCodex.last_config = None
    h = cx.CodexAgentHarness(SessionStore())
    h._effort = "high"
    asyncio.run(h._client_ready())
    overrides = _FakeAsyncCodex.last_config.kw["config_overrides"]
    assert "model_reasoning_effort=high" in overrides


# ── claude_agent (API lane) catalog ──────────────────────────────────────────

def test_claude_api_lane_has_its_own_catalog():
    h = cla.ClaudeAgentHarness(SessionStore())
    models = h.list_models()
    assert {"opus", "sonnet"} <= {m["id"] for m in models}


# ── service delegation ───────────────────────────────────────────────────────

def test_service_list_models_delegates_and_handles_missing(monkeypatch):
    from command_center.agent_sessions.registry import default_registry
    from command_center.agent_sessions.service import AgentSessionService
    store = SessionStore()
    svc = AgentSessionService(store=store, registry=default_registry(store))
    # fake harness has no list_models -> empty
    assert asyncio.run(svc.list_models("fake")) == []
    with pytest.raises(KeyError):
        asyncio.run(svc.list_models("does-not-exist"))
