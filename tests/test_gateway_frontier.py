"""GatewayCore's frontier-router branch: a frontier turn must route to the paid
lane instead of LiteLLM, carry no tools, and inject no board/growthos-memory
context — see channels/core.py is_frontier / _inject_context and
channels/frontier_client.py. Hermetic: frontier_chat_completion is monkeypatched,
so no key/network is needed.
"""
from __future__ import annotations

import asyncio
import sys

from command_center.channels import core
from command_center.schemas import AgentSurfaceConfig, BoardStateKnobs

sys.path.insert(0, str(core.GROWTHOS_ROOT))


def _frontier_gateway(monkeypatch, *, board_enabled: bool = True):
    monkeypatch.setattr(core, "load_tool_layer",
                        lambda surface="discord": (
                            [{"type": "function",
                             "function": {"name": "ping", "parameters": {}}}],
                            {"ping": lambda **kw: "pong"}))
    monkeypatch.setattr(
        core, "load_agent_surface_config",
        lambda: AgentSurfaceConfig(
            schema_version="test",
            board_state=BoardStateKnobs(enabled=board_enabled)))
    cfg = core.GatewayConfig(surface="Test", model="frontier:glm-5.2",
                             litellm_base="http://x", litellm_key="",
                             frontier_model_id="glm-5.2")
    return core.GatewayCore(cfg)


def test_is_frontier_and_context_injection_off(monkeypatch):
    gw = _frontier_gateway(monkeypatch, board_enabled=True)
    assert gw.is_frontier is True
    # board_state is enabled in config, but frontier mode must still suppress it
    assert gw._inject_context is False
    assert gw._memory_messages("anything") == []


def test_local_gateway_context_injection_follows_board_knobs(monkeypatch):
    monkeypatch.setattr(core, "load_tool_layer",
                        lambda surface="discord": ([], {}))
    monkeypatch.setattr(
        core, "load_agent_surface_config",
        lambda: AgentSurfaceConfig(schema_version="test",
                                   board_state=BoardStateKnobs(enabled=True)))
    cfg = core.GatewayConfig(surface="Test", model="chat",
                             litellm_base="http://x", litellm_key="")
    gw = core.GatewayCore(cfg)
    assert gw.is_frontier is False
    assert gw._inject_context is True


def test_completion_routes_to_frontier_client_not_litellm(monkeypatch):
    gw = _frontier_gateway(monkeypatch, board_enabled=False)
    calls = []

    async def fake_frontier(*, model_id, conversation_id, messages, http,
                            task_class="cockpit_chat_manual_select",
                            output_tokens_estimate=2000):
        calls.append({"model_id": model_id, "conversation_id": conversation_id,
                      "messages": messages})
        return {"role": "assistant", "content": "hello from frontier", "_usage": None}

    monkeypatch.setattr("command_center.channels.frontier_client.frontier_chat_completion",
                        fake_frontier)
    # if this ever tried to reach LiteLLM it would raise (bogus base url, no mock)
    result = asyncio.run(gw._completion(
        [{"role": "user", "content": "hi"}], with_tools=True))

    assert result["content"] == "hello from frontier"
    assert len(calls) == 1
    assert calls[0]["model_id"] == "glm-5.2"


def test_frontier_system_prompt_carries_no_tool_vocabulary(monkeypatch):
    """build_system's local variant deliberately enumerates every verb (e.g.
    project_status("betts_basketball")) so a LOCAL model — which gets a
    matching tools schema — actually uses its abilities. A frontier turn gets
    no schema, so that same prose only invites it to guess. Regression guard
    for the 2026-07-11 incident: this must stay tools-free."""
    gw = _frontier_gateway(monkeypatch)
    assert "project_status" not in gw.system
    assert "add_mission_card" not in gw.system
    assert "NO tools" in gw.system

    local_cfg = core.GatewayConfig(surface="Test", model="chat",
                                   litellm_base="http://x", litellm_key="")
    monkeypatch.setattr(core, "load_agent_surface_config",
                        lambda: AgentSurfaceConfig(
                            schema_version="test",
                            board_state=BoardStateKnobs(enabled=False)))
    local_gw = core.GatewayCore(local_cfg)
    assert "project_status" in local_gw.system


def test_frontier_response_with_tool_calls_is_never_dispatched(monkeypatch):
    """Regression test for the 2026-07-11 incident: deepseek-v4-pro returned a
    real, structured tool_calls entry for project_status even though
    frontier_chat_completion never sent a `tools` field in the request (see
    frontier_client.py body construction — no tools key, ever). GatewayCore
    must refuse to dispatch a tool_calls field it never offered, regardless of
    which provider or backend produced it."""
    gw = _frontier_gateway(monkeypatch, board_enabled=False)
    dispatched = []
    gw.dispatch["project_status"] = lambda **kw: dispatched.append(kw) or "should not run"

    async def fake_frontier_that_leaks_a_tool_call(
            *, model_id, conversation_id, messages, http,
            task_class="cockpit_chat_manual_select", output_tokens_estimate=2000):
        return {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "project_status",
                                        "arguments": '{"project_name": "betts_basketball"}'}}],
            "_usage": {"prompt_tokens": 760, "completion_tokens": 67},
        }

    monkeypatch.setattr("command_center.channels.frontier_client.frontier_chat_completion",
                        fake_frontier_that_leaks_a_tool_call)
    reply = asyncio.run(gw.run_turn("c1", "go over this jobs setup"))

    assert dispatched == []                          # the tool never actually ran
    assert "gateway safety stop" in reply
    assert "project_status" in reply


def test_run_turn_end_to_end_no_tools_no_board(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    gw = _frontier_gateway(monkeypatch, board_enabled=True)
    captured_messages = []

    async def fake_frontier(*, model_id, conversation_id, messages, http,
                            task_class="cockpit_chat_manual_select",
                            output_tokens_estimate=2000):
        captured_messages.extend(messages)
        return {"role": "assistant", "content": "plain answer, no tools",
                "_usage": {"prompt_tokens": 5, "completion_tokens": 5}}

    monkeypatch.setattr("command_center.channels.frontier_client.frontier_chat_completion",
                        fake_frontier)
    reply = asyncio.run(gw.run_turn("c1", "what's the weather like?"))

    assert reply == "plain answer, no tools"
    # exactly ONE system message (the static harness prompt) — no board-state
    # or growthos-memory block was injected on top of it
    system_msgs = [m for m in captured_messages if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == gw.system
