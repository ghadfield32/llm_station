"""Chat-first UX guardrail — the cockpit must not tell the user to "start from a
mission" to reach Claude Code / Codex.

A mission is an optional governance/tracking layer, never a prerequisite for
talking to a coding agent. The old cockpit listed the executors a SECOND time as
disabled options inside the GatewayCore *model* selector with "start from a
mission, not this dropdown" — a dead-end that read as "Claude/Codex aren't
available for chat." These assertions fail if that regresses, and pin the
corrected shape: one "Assistant" chooser where Claude Code / Codex are directly
selectable, and an honest unavailable state (reason + repair), never a bare
"not available".

Source-level (reads App.tsx) — hermetic, no build, no browser. Complements the
MASTER runtime truth check (docs) with the UI contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"
WORKER_SCRIPT = ROOT / "scripts" / "start_agent_worker.ps1"


@pytest.fixture(scope="module")
def app_tsx() -> str:
    assert APP_TSX.is_file(), f"cockpit App.tsx not found at {APP_TSX}"
    return APP_TSX.read_text(encoding="utf-8")


# --- the dead-end must stay gone -------------------------------------------------

# phrases that made a mission look like a prerequisite for direct agent chat
FORBIDDEN_PHRASES = (
    "start from a mission, not this dropdown",
    "Executors — from missions, not here",
    "never a chat model",
)


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_mission_only_executor_phrasing_is_gone(app_tsx: str, phrase: str) -> None:
    assert phrase not in app_tsx, (
        f"mission-only executor phrasing reappeared in App.tsx: {phrase!r}. "
        "Claude Code / Codex are directly selectable from the Assistant chooser; "
        "a mission is optional governance, not a prerequisite for chat."
    )


def test_executors_are_not_a_disabled_gatewaycore_model_option(app_tsx: str) -> None:
    # the old dead-end rendered executors as disabled <option value="executor:..."> in
    # the GatewayCore model selector. They are not GatewayCore models — they must not
    # appear there at all.
    assert "value={`executor:${e.name}`}" not in app_tsx, (
        "Claude Code / Codex must not be listed as disabled options in the "
        "GatewayCore model selector — they are coding agents, not chat models."
    )


# --- the corrected shape must be present ----------------------------------------

def test_assistant_chooser_exposes_coding_agents_directly(app_tsx: str) -> None:
    # one primary chooser, relabelled "assistant", groups the coding agents so
    # Claude Code / Codex are selectable without touching a mission first.
    assert ">assistant<" in app_tsx, "primary chooser should be labelled 'assistant'"
    assert "Coding agents (Claude Code · Codex)" in app_tsx, (
        "the Assistant chooser should group Claude Code / Codex as directly "
        "selectable agent sessions"
    )
    # selecting an agent still renders the direct session panel (no mission gate)
    assert 'chatTarget.kind === "agent"' in app_tsx
    assert "<AgentSessionPanel" in app_tsx


def test_runtime_and_model_choosers_explain_their_distinct_jobs(app_tsx: str) -> None:
    assert "Growth OS (GatewayCore local chat)" in app_tsx
    assert ">chat model<" in app_tsx
    assert ">agent model<" in app_tsx


def test_selecting_an_available_agent_auto_starts_read_only_session(app_tsx: str) -> None:
    assert "autoStartAttemptedRef" in app_tsx
    assert "void createSession()" in app_tsx
    assert 'permission_profile: "read_only"' in app_tsx
    assert "conversation_id: conversationId" in app_tsx
    assert 'conversation_id: thread?.id ?? "agent"' not in app_tsx
    assert "start agent session" not in app_tsx, (
        "normal agent selection should auto-start; a button may be shown only "
        "as an explicit retry after a surfaced failure"
    )


def test_worker_launcher_uses_isolated_frozen_codex_environment() -> None:
    source = WORKER_SCRIPT.read_text(encoding="utf-8")
    assert '"run", "--isolated", "--frozen"' in source
    assert '"--extra", "gateways", "--extra", "agent-codex"' in source
    assert "Start-Process -FilePath $Uv" in source
    assert "command_center.cli.agent_worker" in source


def test_unavailable_agent_shows_reason_and_repair_not_bare_message(app_tsx: str) -> None:
    # "Never show only 'unavailable'": the panel must surface the specific reason
    # (harness.detail) and a concrete repair pointer, not a dead bare message.
    assert "This harness is not available in this deployment." not in app_tsx, (
        "the bare 'not available' message must be replaced by reason + repair"
    )
    assert "agent-sessions-activation.md" in app_tsx, (
        "the unavailable state should point at the activation runbook so the "
        "operator knows how to enable the runtime"
    )
