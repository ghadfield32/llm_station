"""The Claude<->Codex AI-assistance protocol wiring: the repo CLAUDE.md must
exist and encode the handoff contract (every Claude Code session — terminal
or cockpit — loads it via the session cwd), and the claude_code_local lane
must surface that protocol in its availability detail so the cockpit
dropdown describes it."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repo_claude_md_encodes_the_protocol():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    # the division of work and both handoff mechanics must be stated
    assert "Claude ⇄ Codex" in text or "Claude <-> Codex" in text
    assert "/codex" in text                       # direct-session handoff
    assert "skill-codex" in text                  # the installed plugin
    assert "assistant switcher" in text           # cockpit-session handoff
    assert "AI_ASSISTED_DEVELOPMENT_WORKFLOW.md" in text
    # the walls travel with every session
    assert "read-only" in text
    assert "Never approve mission cards" in text


def test_claude_lane_detail_mentions_the_protocol():
    from command_center.agent_sessions.adapters.claude_code_local import (
        _PROTOCOL_NOTE,
    )
    assert "CLAUDE.md" in _PROTOCOL_NOTE
    assert "Codex" in _PROTOCOL_NOTE
    # and the probe actually uses it (source-level wiring check)
    src = (ROOT / "src" / "command_center" / "agent_sessions" / "adapters"
           / "claude_code_local.py").read_text(encoding="utf-8")
    assert src.count("_PROTOCOL_NOTE") >= 3       # def + comment + probe use


def test_cockpit_sessions_inherit_repo_context_via_cwd():
    """The adapter must keep launching with cwd=repo — that is HOW the
    project CLAUDE.md reaches hardened cockpit sessions (slash commands and
    MCP stay disabled there; the protocol arrives as project context)."""
    src = (ROOT / "src" / "command_center" / "agent_sessions" / "adapters"
           / "claude_code_local.py").read_text(encoding="utf-8")
    assert "cwd=str(cwd)" in src
    assert "--disable-slash-commands" in src      # the wall stays intact
