"""KAN-2 STEP B: native agent sessions stay inside their resolved workspace."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from command_center.agent_sessions import workspace_scope
from command_center.agent_sessions.adapters import claude_code_local as ccl
from command_center.agent_sessions.adapters import codex_agent as codex
from command_center.agent_sessions.protocol import SessionStart
from command_center.agent_sessions.store import SessionStore


async def _drain(events):
    return [event async for event in events]


def _start(harness_id: str, repo_id: str) -> SessionStart:
    return SessionStart(
        conversation_id="scope-conversation",
        repo_id=repo_id,
        mode="analysis",
        harness_id=harness_id,
        permission_profile="read_only",
    )


def test_bounds_instruction_names_root_and_secret_path_contract():
    root = Path("C:/work/repo")

    instruction = workspace_scope.workspace_bounds_instruction(root, "repo-one")

    assert str(root) in instruction
    assert "ONLY search space" in instruction
    assert "do not read, glob, grep" in instruction.lower()
    assert "secret_paths.is_secret_path" in instruction
    assert "always off-limits" in instruction
    assert ".ssh" in instruction
    assert ".aws" in instruction
    assert ".env" in instruction
    assert ".gnupg" in instruction


def test_home_workspace_instruction_requires_targeted_reads_without_tree_scans():
    instruction = workspace_scope.workspace_bounds_instruction(
        Path("C:/Users/operator"), "home_workspace")

    assert "targeted reads" in instruction
    assert "Never enumerate the full home tree" in instruction
    assert "recursive scans" in instruction


def test_claude_help_without_documented_read_path_seam_adds_no_args(monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    def _run(args, **kwargs):
        calls.append((args, kwargs))
        return types.SimpleNamespace(
            stdout=(
                "--disallowedTools <tools...> list of tool names to deny\n"
                "--settings <file-or-json> load additional settings"
            ),
            stderr="",
        )

    workspace_scope._claude_help_output.cache_clear()
    monkeypatch.setattr(workspace_scope.subprocess, "run", _run)

    additions = workspace_scope.claude_cli_read_deny_args(
        "C:/fake/claude-current.exe", Path("C:/work/repo"))

    assert additions == []
    assert calls[0][0] == ["C:/fake/claude-current.exe", "--help"]
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True


def test_claude_args_snapshot_contains_no_invented_flags(monkeypatch):
    monkeypatch.setattr(ccl, "_max_turns", lambda: 20)
    monkeypatch.setattr(ccl, "claude_cli_read_deny_args", lambda *_: [])
    harness = ccl.ClaudeCodeLocalHarness(SessionStore())
    record = types.SimpleNamespace(
        session_id="scope-session",
        model=None,
        external_session_id=None,
    )
    repo_path = Path("C:/work/repo")

    args = harness._build_args("C:/bin/claude.exe", record, repo_path)

    assert args == [
        "C:/bin/claude.exe",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "plan",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--max-turns",
        "20",
        "--tools",
        "Read",
        "Glob",
        "Grep",
        "--disallowedTools",
        "Write",
        "Edit",
        "MultiEdit",
        "NotebookEdit",
        "Bash",
        "BashOutput",
        "KillShell",
        "WebSearch",
        "WebFetch",
        "Task",
        "--add-dir",
        str(repo_path),
    ]


@pytest.mark.parametrize(
    ("repo_id", "repo_path", "home_variant"),
    [
        ("repo-one", Path("C:/work/repo-one"), False),
        ("home_workspace", Path("C:/Users/operator"), True),
    ],
)
def test_claude_first_prompt_contains_workspace_bounds(
    monkeypatch,
    repo_id: str,
    repo_path: Path,
    home_variant: bool,
):
    captured_prompts: list[str] = []

    async def _stream(self, session_id, args, cwd, env, prompt):
        captured_prompts.append(prompt)
        yield {"type": "system", "session_id": "claude-scope-id"}
        yield {
            "type": "result",
            "session_id": "claude-scope-id",
            "is_error": False,
        }

    monkeypatch.setattr(ccl, "_claude_bin", lambda: "C:/bin/claude.exe")
    monkeypatch.setattr(ccl, "_resolve_repo_path", lambda _: repo_path)
    monkeypatch.setattr(ccl, "_load_model_prefs", lambda: {})
    monkeypatch.setattr(ccl, "claude_cli_read_deny_args", lambda *_: [])
    monkeypatch.setattr(ccl.ClaudeCodeLocalHarness, "_stream_cli", _stream)
    harness = ccl.ClaudeCodeLocalHarness(SessionStore())

    async def _run():
        session_id = await harness.start_session(_start("claude_code_local", repo_id))
        await _drain(harness.send(session_id, "inspect this repo"))
        await _drain(harness.send(session_id, "follow up"))

    asyncio.run(_run())

    first_prompt, second_prompt = captured_prompts
    assert first_prompt.startswith("[WORKSPACE BOUNDS — MANDATORY]")
    assert str(repo_path) in first_prompt
    assert "secret_paths.is_secret_path" in first_prompt
    assert first_prompt.endswith("inspect this repo")
    assert ("targeted reads" in first_prompt) is home_variant
    assert second_prompt == "follow up"


class _FakeSandbox:
    read_only = "read-only"


class _FakeApprovalMode:
    deny_all = "deny-all"


class _FakeCodexConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeCodexTurn:
    async def stream(self):
        for notification in ():
            yield notification


class _FakeCodexThread:
    id = "codex-scope-thread"

    def __init__(self):
        self.prompts: list[str] = []

    async def turn(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return _FakeCodexTurn()


class _FakeCodexClient:
    last_instance = None

    def __init__(self, config):
        type(self).last_instance = self
        self.thread = _FakeCodexThread()

    async def models(self):
        model = types.SimpleNamespace(id="gpt-scope", is_default=True)
        return types.SimpleNamespace(data=[model])

    async def thread_start(self, **kwargs):
        return self.thread


def test_codex_first_turn_contains_workspace_bounds(monkeypatch):
    fake_sdk = types.SimpleNamespace(
        AsyncCodex=_FakeCodexClient,
        CodexConfig=_FakeCodexConfig,
        Sandbox=_FakeSandbox,
        ApprovalMode=_FakeApprovalMode,
    )
    repo_path = Path("C:/work/codex-repo")
    monkeypatch.setitem(sys.modules, "openai_codex", fake_sdk)
    monkeypatch.setattr(codex, "_resolve_repo_path", lambda _: repo_path)
    monkeypatch.setattr(codex, "_load_model_prefs", lambda: {})
    harness = codex.CodexAgentHarness(SessionStore())

    async def _run():
        session_id = await harness.start_session(_start("codex_agent", "codex-repo"))
        await _drain(harness.send(session_id, "inspect with codex"))
        await _drain(harness.send(session_id, "codex follow up"))

    asyncio.run(_run())

    prompts = _FakeCodexClient.last_instance.thread.prompts
    assert prompts[0].startswith("[WORKSPACE BOUNDS — MANDATORY]")
    assert str(repo_path) in prompts[0]
    assert "secret_paths.is_secret_path" in prompts[0]
    assert prompts[0].endswith("inspect with codex")
    assert prompts[1] == "codex follow up"
