"""Board/card chat context — every card can open chat seeded with its full
context, on the assistant lane the user picks (GatewayCore / Claude / Codex).

Frontend-only (reuses the existing per-card chat_prompt from the progress
endpoint + the chat-handoff draft). Source-level guardrail over App.tsx: pins
the per-card action cluster, that the seed comes from chat_prompt (not a
guess), and that the lane choice reaches the real agent harnesses.

KAN-8 (2026-07-23) changed the MECHANISM, not the invariant: the two
hardcoded "Ask Claude"/"Ask Codex" buttons became one "Open in chat" plus a
runtime picker built from the LIVE harness list. The assertions below moved
with it and are now stricter — a hardcoded harness id in the card actions is
itself a failure, because it can point at a runtime that is not installed or
not available.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"


def _src() -> str:
    return APP_TSX.read_text(encoding="utf-8")


def test_every_card_has_one_open_in_chat_action_plus_a_runtime_picker():
    src = _src()
    assert "card-chat-actions" in src        # the per-card action cluster
    assert "Open in chat" in src
    # one action + a picker, not one button per runtime
    assert "card-runtime-select" in src
    assert "Ask Claude" not in src and "Ask Codex" not in src


def test_card_chat_seed_comes_from_the_authoritative_chat_prompt():
    src = _src()
    # DomainCardTile seeds the chat from the card's chat_prompt (recorded context),
    # not a hand-built guess
    assert "async function chatAboutCard" in src
    assert "fetchDomainCardProgress(spec.domain_id" in src
    assert "prog.chat_prompt" in src


def test_card_runtime_picker_is_built_from_the_live_harness_list():
    src = _src()
    # the picker enumerates the harnesses the app actually fetched, so an
    # unavailable/uninstalled runtime can never be offered as a live choice
    assert "chatHarnesses" in src
    assert "runtimeLabel(harness)" in src
    assert "disabled={!harness.available}" in src
    # GatewayCore stays available even when no agent harness is reachable
    assert '<option value="GatewayCore">' in src


def test_card_actions_never_hardcode_an_agent_harness_id():
    """A card action must not name a harness the runtime may not have.

    Regression guard for KAN-8: the old buttons shipped literal
    `agent:claude_code_local` / `agent:codex_agent` targets that were never
    checked against the live harness list.
    """
    src = _src()
    tile_start = src.index("function DomainCardTile")
    tile_end = src.index("function ", tile_start + 1)
    card_tile_src = src[tile_start:tile_end]
    assert "agent:claude_code_local" not in card_tile_src
    assert "agent:codex_agent" not in card_tile_src


def test_chat_view_honors_a_preselected_assistant_from_the_draft():
    src = _src()
    # the draft carries an optional target and ChatView switches lanes to it
    assert "target?: string" in src
    assert "if (draft?.target) setTargetRaw(draft.target)" in src
    # an agent card-chat also seeds the agent panel's first message with the context
    assert "initialPrompt" in src
