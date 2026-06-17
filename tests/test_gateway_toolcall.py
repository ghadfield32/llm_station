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
import sys

import pytest

from command_center.channels import core
from command_center.schemas import AgentSurfaceConfig, BoardStateKnobs

sys.path.insert(0, str(core.GROWTHOS_ROOT))


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


def test_history_is_multi_turn_and_scoped_by_conversation(monkeypatch):
    gw = _gateway(monkeypatch)
    seen_messages = []

    async def fake(messages, with_tools):
        seen_messages.append([m.get("content", "") for m in messages])
        return {"content": "ok", "tool_calls": []}

    monkeypatch.setattr(gw, "_completion", fake)

    assert asyncio.run(gw.run_turn("same", "remember marker ALPHA")) == "ok"
    assert asyncio.run(gw.run_turn("same", "what marker did I give you?")) == "ok"
    assert any("remember marker ALPHA" in c for c in seen_messages[-1])

    assert asyncio.run(gw.run_turn("fresh", "what marker did I give you?")) == "ok"
    assert not any("remember marker ALPHA" in c for c in seen_messages[-1])


def test_memory_block_is_injected_across_fresh_conversations(monkeypatch):
    from growthos import memory

    class _MemoryCfg:
        enabled = True
        refresh_every_rounds = 99

    monkeypatch.setattr(memory, "load_memory_config", lambda: _MemoryCfg())
    monkeypatch.setattr(
        memory,
        "collect_memory_state",
        lambda query, cfg: "=== REMEMBERED ===\n- durable marker BETA\n=== END REMEMBERED ===",
    )
    gw = _gateway(monkeypatch)
    seen_messages = []

    async def fake(messages, with_tools):
        seen_messages.append([m.get("content", "") for m in messages])
        return {"content": "BETA", "tool_calls": []}

    monkeypatch.setattr(gw, "_completion", fake)

    assert asyncio.run(gw.run_turn("fresh-memory-conversation", "what is durable marker?")) == "BETA"
    assert any("durable marker BETA" in c for c in seen_messages[-1])


def test_repeated_identical_tool_call_is_suppressed(monkeypatch):
    calls = []

    def ping(**kw):
        calls.append(kw)
        return "pong"

    gw = _gateway(monkeypatch, dispatch={"ping": ping})
    same_call = {"id": "1", "function": {"name": "ping", "arguments": "{\"x\": 1}"}}
    monkeypatch.setattr(gw, "_completion", _scripted(
        {"content": "", "tool_calls": [same_call]},
        {"content": "", "tool_calls": [same_call]},
        {"content": "done", "tool_calls": []},
    ))

    out = asyncio.run(gw.run_turn("c1", "repeat tool"))

    assert out == "done"
    assert calls == [{"x": 1}]


def test_conversation_busy_rule_rejects_overlapping_turn(monkeypatch):
    gw = _gateway(monkeypatch)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake(messages, with_tools):
            started.set()
            await release.wait()
            return {"content": "first done", "tool_calls": []}

        monkeypatch.setattr(gw, "_completion", fake)
        first = asyncio.create_task(gw.run_turn("same", "start long turn"))
        await started.wait()
        second = await gw.run_turn("same", "overlap")
        release.set()
        first_out = await first
        return first_out, second

    first_out, second = asyncio.run(scenario())

    assert first_out == "first done"
    assert "still working" in second


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
