"""Board/card chat context — every card can open chat seeded with its full
context, on the assistant lane the user picks (GatewayCore / Claude / Codex).

Frontend-only (reuses the existing per-card chat_prompt from the progress
endpoint + the chat-handoff draft). Source-level guardrail over App.tsx: pins
the three per-card actions, that the seed comes from chat_prompt (not a guess),
and that "Ask Claude/Codex" preselect the real agent harness lanes.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"


def _src() -> str:
    return APP_TSX.read_text(encoding="utf-8")


def test_every_card_has_the_three_chat_actions():
    src = _src()
    assert "card-chat-actions" in src        # the per-card action cluster
    assert "Open in chat" in src
    assert "Ask Claude" in src
    assert "Ask Codex" in src


def test_card_chat_seed_comes_from_the_authoritative_chat_prompt():
    src = _src()
    # DomainCardTile seeds the chat from the card's chat_prompt (recorded context),
    # not a hand-built guess
    assert "async function chatAboutCard" in src
    assert "fetchDomainCardProgress(spec.domain_id" in src
    assert "prog.chat_prompt" in src


def test_ask_claude_and_codex_preselect_the_real_agent_lanes():
    src = _src()
    # the two coding-agent buttons target the actual harness ids (chat-first:
    # Claude/Codex are agent sessions, selectable directly — no mission needed)
    assert 'chatAboutCard("agent:claude_code_local")' in src
    assert 'chatAboutCard("agent:codex_agent")' in src


def test_chat_view_honors_a_preselected_assistant_from_the_draft():
    src = _src()
    # the draft carries an optional target and ChatView switches lanes to it
    assert "target?: string" in src
    assert "if (draft?.target) setTargetRaw(draft.target)" in src
    # an agent card-chat also seeds the agent panel's first message with the context
    assert "initialPrompt" in src
