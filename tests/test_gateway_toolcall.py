"""Gateway tool-call handling (root cause: qwen3-coder's Ollama native parser
drops a tool call the model prefixes with prose, leaking raw `<function=..>` XML
to the user). These tests pin the gateway's contract regardless of model:

  - a thinking model's <think> scratchpad is stripped from the final answer
  - if a tool call ever lands in `content` unparsed (tool_calls empty), the
    gateway FAILS LOUD with a diagnostic and never forwards the raw markup
  - the normal parsed-tool-call loop still executes tools and answers

Hermetic — no AppFlowy/Ledger/Ollama/LiteLLM: the tool layer, surface config,
and the model completion are all injected.
"""
import asyncio

import pytest

from command_center.channels import core
from command_center.schemas import AgentSurfaceConfig, BoardStateKnobs


# ---- pure helpers ----------------------------------------------------------

def test_clean_strips_think_block():
    assert core._clean("<think>plan the answer</think>Hello!") == "Hello!"
    assert core._clean("no think here") == "no think here"
    assert core._clean("<think>multi\nline</think>  answer  ") == "answer"


def test_leaked_tool_call_detects_every_marker():
    assert core._leaked_tool_call("<function=search>") is True
    assert core._leaked_tool_call("<tool_call>{...}")  is True
    assert core._leaked_tool_call("text <parameter=x> text") is True
    assert core._leaked_tool_call("a normal sentence with no markup") is False
    assert core._leaked_tool_call("") is False


# ---- run_turn contract (injected completion) -------------------------------

def _gateway(monkeypatch, dispatch=None):
    """Construct a GatewayCore with the tool layer + surface config injected so
    __init__ touches no growthos/AppFlowy/yaml. Board state is disabled so no
    board fetch is attempted."""
    monkeypatch.setattr(core, "load_tool_layer",
                        lambda surface="discord": ([], dict(dispatch or {})))
    monkeypatch.setattr(
        core, "load_agent_surface_config",
        lambda: AgentSurfaceConfig(schema_version="test",
                                   board_state=BoardStateKnobs(enabled=False)))
    cfg = core.GatewayConfig(surface="Test", model="chat",
                             litellm_base="http://x", litellm_key="")
    return core.GatewayCore(cfg)


def _scripted(*messages):
    """An async _completion that returns the given messages in order."""
    queue = list(messages)

    async def fake(_messages, with_tools):
        return queue.pop(0)
    return fake


def test_unparsed_tool_call_fails_loud_and_hides_markup(monkeypatch):
    gw = _gateway(monkeypatch)
    leaked = ("I will search for the book.\n<function=search>\n"
              "<parameter=query>\nAlan Turing\n</parameter>\n</function>\n</tool_call>")
    monkeypatch.setattr(gw, "_completion",
                        _scripted({"content": leaked, "tool_calls": []}))
    out = asyncio.run(gw.run_turn("c1", "find the turing book"))
    assert "misconfiguration" in out            # named the cause
    assert "configs/models.yaml" in out         # named the fix
    assert "<function=" not in out              # raw markup NOT forwarded
    assert "</tool_call>" not in out


def test_final_answer_strips_thinking(monkeypatch):
    gw = _gateway(monkeypatch)
    monkeypatch.setattr(gw, "_completion", _scripted(
        {"content": "<think>the user wants a greeting</think>Hi there!",
         "tool_calls": []}))
    out = asyncio.run(gw.run_turn("c1", "hi"))
    assert out == "Hi there!"


def test_normal_tool_loop_executes_and_answers(monkeypatch):
    calls = []

    def ping(**kw):
        calls.append(kw)
        return "pong"

    gw = _gateway(monkeypatch, dispatch={"ping": ping})
    monkeypatch.setattr(gw, "_completion", _scripted(
        {"content": "", "tool_calls": [
            {"id": "1", "function": {"name": "ping", "arguments": "{}"}}]},
        {"content": "all done", "tool_calls": []}))
    out = asyncio.run(gw.run_turn("c1", "ping please"))
    assert calls == [{}]            # the tool actually ran
    assert out == "all done"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
