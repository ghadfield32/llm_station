"""Phase 3 — bounded, typed hand-off packet (Claude ⇄ Codex ⇄ OpenRouter).

The plan's rule: a hand-off is a bounded briefing, never an unlimited transcript
forward. These pin the caps, the strict typing, and that context (repo /
permission / evidence) is carried across the switch.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from command_center.agent_sessions.events import AgentEvent
from command_center.agent_sessions.handoff import (
    HandoffPacket,
    build_handoff_packet,
    render_handoff_prompt,
)


@dataclass
class _Rec:
    harness: str = "codex_agent"
    repo_id: str = "llm_station"
    permission_profile: str = "read_only"
    session_id: str = "AS-abc123"


def _msg(kind: str, text: str) -> AgentEvent:
    return AgentEvent(kind, {"text": text})


def test_handoff_is_bounded():
    # 40 exchanges + 40 file reads + a giant assistant message
    events: list[AgentEvent] = []
    for i in range(40):
        events.append(_msg("user_message", f"question {i}"))
        events.append(AgentEvent("tool_started",
                                 {"name": "read_file", "args": {"path": f"src/f{i}.py"}}))
        events.append(_msg("assistant_message", f"answer {i} " + "x" * 5000))
    packet = build_handoff_packet(source_record=_Rec(), events=events,
                                  to_harness="claude_code_local")
    assert len(packet.selected_messages) <= 6          # not the whole log
    assert len(packet.relevant_files) <= 20
    assert len(packet.latest_state) <= 1200            # giant msg clipped
    assert all(len(m) <= 800 for m in packet.selected_messages)


def test_handoff_packet_is_strict():
    with pytest.raises(ValidationError):
        HandoffPacket(from_harness="a", to_harness="b", repo_id="r",
                      permission_profile="read_only", source_session_id="s",
                      surprise_field="nope")   # extra=forbid


def test_handoff_carries_context_and_evidence():
    events = [_msg("user_message", "review the drift"),
              _msg("assistant_message", "found the schema mismatch")]
    packet = build_handoff_packet(source_record=_Rec(), events=events,
                                  to_harness="claude_code_local")
    # switching must not change the context or drop the trail
    assert packet.repo_id == "llm_station"
    assert packet.permission_profile == "read_only"
    assert packet.source_session_id == "AS-abc123"
    assert packet.from_harness == "codex_agent"
    assert packet.to_harness == "claude_code_local"
    assert packet.goal == "review the drift"
    assert "schema mismatch" in packet.latest_state


def test_handoff_extracts_read_files():
    events = [
        AgentEvent("tool_started", {"name": "read_file", "args": {"path": "a.py"}}),
        AgentEvent("tool_started", {"name": "read_file", "args": {"path": "a.py"}}),  # dup
        AgentEvent("tool_started", {"name": "grep", "args": {"pattern": "b/**"}}),
    ]
    packet = build_handoff_packet(source_record=_Rec(), events=events,
                                  to_harness="claude_code_local")
    assert packet.relevant_files == ["a.py", "b/**"]   # deduped, ordered


def test_render_prompt_is_bounded_and_structured():
    events = [_msg("user_message", "goal here"),
              _msg("assistant_message", "state here")]
    packet = build_handoff_packet(source_record=_Rec(), events=events,
                                  to_harness="claude_code_local",
                                  open_questions=["is X true?"])
    prompt = render_handoff_prompt(packet)
    assert "Hand-off from codex_agent → claude_code_local" in prompt
    assert "Workspace: llm_station" in prompt
    assert "read_only" in prompt
    assert "goal here" in prompt and "state here" in prompt
    assert "is X true?" in prompt
    # the raw transcript is never dumped: bounded prompt stays small
    assert len(prompt) < 4000


def test_explicit_goal_overrides_first_user_message():
    events = [_msg("user_message", "original ask")]
    packet = build_handoff_packet(source_record=_Rec(), events=events,
                                  to_harness="claude_code_local",
                                  goal="the refined goal")
    assert packet.goal == "the refined goal"
