"""Assistant Catalog aggregator: ONE normalized list joining GatewayCore
(completion) + Claude Code / Codex (agent harnesses) + Auto (dispatcher). Growth
OS/boards/repos are CONTEXT, never assistants. The backend owns every
availability verdict and reason string; the catalog survives an unreachable
worker. Hermetic: the pure builder + the real (worker-free) harness registry;
the endpoint is loaded by path with a monkeypatched worker.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from command_center.assistants import (
    build_assistant_catalog,
    declared_harness_descriptors,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"

_RUNTIME = {"enabled": True, "roles": [
    {"role": "chat", "label": "qwen3:30b"},
    {"role": "planner", "label": "devstral:24b"}]}


def _catalog(*, agent_enabled=True, probes=None, worker_error=None):
    return build_assistant_catalog(
        runtime=_RUNTIME, descriptors=declared_harness_descriptors(),
        probes=probes, agent_sessions_enabled=agent_enabled,
        worker_error=worker_error)


def _by_id(cat):
    return {o.assistant_id: o for o in cat.assistants}


# ── classification: the three concepts are distinct ─────────────────────────────
def test_growth_os_is_context_not_model():
    cat = _catalog()
    ids = {o.assistant_id.lower() for o in cat.assistants}
    names = {o.display_name.lower() for o in cat.assistants}
    assert "growth os" not in names and "growth_os" not in ids
    # no assistant advertises a model literally named growth os either
    for o in cat.assistants:
        assert all("growth" not in m.model_id.lower() for m in o.model_options)
    assert "context" in cat.context_note.lower()
    assert "growth os" in cat.context_note.lower()


def test_gateway_option_uses_chat_route():
    o = _by_id(_catalog())["gatewaycore"]
    assert o.kind == "completion" and o.route == "gateway"
    assert o.worker_required is False and o.auth_mode == "litellm"


def test_claude_option_uses_agent_session_route():
    o = _by_id(_catalog())["claude_code_local"]
    assert o.kind == "agent" and o.route == "agent_session"
    assert o.worker_required is True and o.requires_repo is True


def test_codex_option_uses_agent_session_route():
    o = _by_id(_catalog())["codex_agent"]
    assert o.kind == "agent" and o.route == "agent_session"


def test_auto_is_a_dispatcher_not_a_model():
    o = _by_id(_catalog())["auto"]
    assert o.kind == "auto" and o.route == "dispatch"
    assert o.model_options == [] and o.availability == "available"


# ── model settings are conditional on the assistant ─────────────────────────────
def test_model_field_is_conditional_on_assistant():
    by = _by_id(_catalog())
    # GatewayCore carries the completion model list; a default is marked
    assert by["gatewaycore"].model_options
    assert by["gatewaycore"].default_model == "chat"
    # agent lanes do NOT inline a universal model list — they carry a per-runtime
    # models_endpoint the UI queries only when that assistant is chosen
    assert by["codex_agent"].model_options == []
    assert by["codex_agent"].models_endpoint == "/api/agent-harnesses/codex_agent/models"


# ── availability + grounded reasons ─────────────────────────────────────────────
def test_unavailable_agent_has_grounded_reason():
    by = _by_id(_catalog(agent_enabled=False))
    for hid in ("claude_code_local", "codex_agent"):
        assert by[hid].availability == "unavailable"
        assert by[hid].unavailable_reason
        assert "KANBAN_UI_AGENT_SESSIONS_ENABLED" in by[hid].unavailable_reason


def test_assistant_catalog_survives_worker_down():
    # worker unreachable → the catalog still returns; gateway available; agents
    # unavailable with the grounded worker reason (never dropped, never faked).
    cat = _catalog(agent_enabled=True, probes=None, worker_error="connect timeout")
    by = _by_id(cat)
    assert by["gatewaycore"].availability == "available"
    assert by["auto"].availability == "available"
    for hid in ("claude_code_local", "codex_agent"):
        assert by[hid].availability == "unavailable"
        assert "connect timeout" in by[hid].unavailable_reason


def test_available_agent_when_probe_reports_available():
    probes = [{"harness_id": "codex_agent", "available": True, "detail": "ok"},
              {"harness_id": "claude_code_local", "available": False,
               "detail": "claude CLI not on PATH"}]
    by = _by_id(_catalog(probes=probes))
    assert by["codex_agent"].availability == "available"
    assert by["claude_code_local"].availability == "unavailable"
    assert by["claude_code_local"].unavailable_reason == "claude CLI not on PATH"


def test_gateway_unavailable_when_chat_disabled():
    cat = build_assistant_catalog(
        runtime={"enabled": False, "roles": []},
        descriptors=declared_harness_descriptors(), probes=None,
        agent_sessions_enabled=False)
    g = _by_id(cat)["gatewaycore"]
    assert g.availability == "unavailable"
    assert "KANBAN_UI_CHAT_ENABLED" in g.unavailable_reason


def test_no_fake_harness_in_catalog():
    assert all(o.assistant_id != "fake" for o in _catalog().assistants)


# ── endpoint: /api/assistants returns and survives agents-disabled ──────────────
def _load(monkeypatch, *, chat=True, agents=False):
    spec = importlib.util.spec_from_file_location("akui_assistants_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["akui_assistants_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CHAT_ENABLED", chat)
    monkeypatch.setattr(mod, "AGENT_SESSIONS_ENABLED", agents)
    # the model registry resolves from the container path; stub it so the endpoint
    # test exercises catalog wiring, not deployment file layout
    monkeypatch.setattr(mod, "models", lambda: {"roles": [{"role": "chat"}]})
    from fastapi.testclient import TestClient
    return mod, TestClient(mod.app)


def test_endpoint_returns_catalog_with_agents_disabled(monkeypatch):
    _mod, client = _load(monkeypatch, chat=True, agents=False)
    r = client.get("/api/assistants")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {o["assistant_id"] for o in body["assistants"]}
    assert {"auto", "gatewaycore", "codex_agent", "claude_code_local"} <= ids
    assert next(o for o in body["assistants"]
                if o["assistant_id"] == "gatewaycore")["availability"] == "available"
    agents = [o for o in body["assistants"] if o["kind"] == "agent"]
    assert agents and all(o["availability"] == "unavailable" for o in agents)
    assert all(o["unavailable_reason"] for o in agents)


def test_endpoint_survives_worker_unreachable_at_http_layer(monkeypatch):
    # agents ENABLED but the worker call raises — the HTTP layer must still 200
    # with agents listed unavailable and the grounded worker reason.
    from fastapi import HTTPException
    _mod, client = _load(monkeypatch, chat=True, agents=True)

    def _boom(*_a, **_k):
        raise HTTPException(status_code=503, detail="worker unreachable")

    monkeypatch.setattr(_mod, "_require_agent_sessions", lambda: object())
    monkeypatch.setattr(_mod, "_call_worker", _boom)
    r = client.get("/api/assistants")
    assert r.status_code == 200, r.text
    agents = [o for o in r.json()["assistants"] if o["kind"] == "agent"]
    assert agents and all(o["availability"] == "unavailable" for o in agents)
    assert all("worker unreachable" in o["unavailable_reason"] for o in agents)
