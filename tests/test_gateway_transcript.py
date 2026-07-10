"""Gateway flight recorder (channels.transcript): the full story of a turn —
untruncated tool args/results, injected context blocks, final answer — must
be
written as one JSONL line per turn, joinable by conversation id, and recording
must be fail-open (a recorder error never breaks the turn).

Regression anchor: core.py once used TurnRecorder without importing it; only a
real run_turn() exercised the seam, so these tests run turns, not just units.

Hermetic — no AppFlowy/Ledger/Ollama/LiteLLM: tool layer, surface config, and
the model completion are injected (same harness as test_gateway_toolcall).
"""
import asyncio
import json
import sys

from command_center.channels import core, transcript
from command_center.schemas import AgentSurfaceConfig, BoardStateKnobs

sys.path.insert(0, str(core.GROWTHOS_ROOT))


# ---- transcript module units ------------------------------------------------

def test_transcript_path_sanitizes_conversation_id(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    path = transcript.transcript_path("discord/guild:1#chan 2")
    assert path.parent == tmp_path
    assert path.name == "discord_guild_1_chan_2.jsonl"


def test_recorder_roundtrip_and_corrupt_line_survival(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    rec = transcript.TurnRecorder(surface="Test", model="chat",
                                  conversation_id="c1", user_text="hello")
    rec.context("board_state")
    rec.tool("ping", '{"x": 1}')
    rec.tool_result("ping", "pong")
    rec.final("done")
    rec.flush()
    # a corrupt line must not sink the readable turns around it
    with transcript.transcript_path("c1").open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    turns = transcript.read_transcript("c1")
    assert len(turns) == 2
    assert turns[0]["user_text"] == "hello"
    assert turns[0]["final"] == "done"
    assert turns[0]["context_blocks"] == ["board_state"]
    assert "corrupt_line" in turns[1]


def test_missing_transcript_reads_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    assert transcript.read_transcript("never-spoken") == []


def test_kill_switch_stops_writes_but_keeps_join_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    monkeypatch.setenv("GATEWAY_TRANSCRIPTS", "0")
    assert transcript.transcripts_enabled() is False
    rec = transcript.TurnRecorder(surface="Test", model="chat",
                                  conversation_id="quiet", user_text="hi")
    # the contextvar join key stays active during the turn (carries no content)
    assert transcript.current_conversation.get() == "quiet"
    rec.final("done")
    rec.flush()
    assert not transcript.transcript_path("quiet").exists()
    assert transcript.current_conversation.get() is None    # reset after flush


# ---- run_turn integration (injected completion) -----------------------------

def _gateway(monkeypatch, dispatch=None):
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
    queue = list(messages)

    async def fake(_messages, with_tools):
        return queue.pop(0)
    return fake


def test_run_turn_records_full_tool_story(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    long_args = '{"query": "' + "x" * 500 + '"}'   # past the SSE 200-char cut
    gw = _gateway(monkeypatch,
                  dispatch={"ping": lambda **kw: "pong-" + "y" * 400})
    monkeypatch.setattr(gw, "_completion", _scripted(
        {"content": "", "tool_calls": [
            {"id": "1",
             "function": {"name": "ping", "arguments": long_args}}]},
        {"content": "all done", "tool_calls": []}))
    assert asyncio.run(gw.run_turn("story-conv", "ping please")) == "all done"

    turns = transcript.read_transcript("story-conv")
    assert len(turns) == 1
    turn = turns[0]
    assert turn["user_text"] == "ping please"
    assert turn["final"] == "all done"
    events = {e["type"] for e in turn["events"]}
    assert {"round", "tool", "tool_result"} <= events
    tool = next(e for e in turn["events"] if e["type"] == "tool")
    assert tool["args"] == long_args                      # FULL args, no cut
    result = next(e for e in turn["events"] if e["type"] == "tool_result")
    assert result["result"] == "pong-" + "y" * 400        # FULL result


def test_each_turn_appends_its_own_line(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    gw = _gateway(monkeypatch)

    async def fake(messages, with_tools):
        return {"content": "ok", "tool_calls": []}

    monkeypatch.setattr(gw, "_completion", fake)
    asyncio.run(gw.run_turn("c-multi", "first"))
    asyncio.run(gw.run_turn("c-multi", "second"))
    turns = transcript.read_transcript("c-multi")
    assert [t["user_text"] for t in turns] == ["first", "second"]
    assert all(t["final"] == "ok" for t in turns)


def test_recorder_failure_never_breaks_the_turn(tmp_path, monkeypatch):
    # point the recorder at a path that cannot be a dir (an existing FILE)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(blocker))
    gw = _gateway(monkeypatch)
    monkeypatch.setattr(gw, "_completion",
                        _scripted({"content": "still fine", "tool_calls": []}))
    before = transcript.write_failure_count()
    assert asyncio.run(gw.run_turn("c1", "hi")) == "still fine"   # fail-open
    # ...but not silently: the dropped turn is counted for the operator
    assert transcript.write_failure_count() == before + 1


def test_completion_carries_litellm_session_id(tmp_path, monkeypatch):
    """The proxy-side net (LiteLLM Session Logs) groups by the SAME key as the
    flight recorder: surface:conversation_id — and only during a turn."""
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    gw = _gateway(monkeypatch)
    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    async def fake_post(url, headers=None, json=None):
        captured["body"] = json
        return _FakeResp()

    monkeypatch.setattr(gw.http, "post", fake_post)
    rec = transcript.TurnRecorder(surface="Test", model="chat",
                                  conversation_id="sess-1", user_text="hi")
    asyncio.run(gw._completion([{"role": "user", "content": "hi"}],
                               with_tools=False))
    rec.flush()
    assert captured["body"]["litellm_session_id"] == "Test:sess-1"
    asyncio.run(gw._completion([{"role": "user", "content": "hi"}],
                               with_tools=False))
    assert "litellm_session_id" not in captured["body"]   # no turn, no key


# ---- agent-call log join key -------------------------------------------------

def test_agent_call_log_carries_conversation_join_key(tmp_path, monkeypatch):
    """During a turn, agent_calls.jsonl rows carry the conversation id (so tool
    metrics join to transcripts); after flush the key is gone — no stale
    attribution from a finished turn."""
    from growthos import observability

    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path))
    log = tmp_path / "agent_calls.jsonl"
    rec = transcript.TurnRecorder(surface="Test", model="chat",
                                  conversation_id="joined", user_text="hi")
    observability.record_call("app", "stage_card", {"card": "X"},
                              ok=True, ms=1.0, path=log)
    rec.flush()
    observability.record_call("app", "stage_card", {"card": "Y"},
                              ok=True, ms=1.0, path=log)
    rows = [json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["conversation_id"] == "joined"   # during a turn: joinable
    assert "conversation_id" not in rows[1]         # after flush: no stale key
