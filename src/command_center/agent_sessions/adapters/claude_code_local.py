"""ClaudeCodeLocalHarness — the DEFAULT Claude lane for a local, single-user
Command Center. Drives the installed **Claude Code CLI** (`claude`) as a
host-side subprocess authenticated by the operator's existing **`claude auth
login`** subscription session — NO `ANTHROPIC_API_KEY`, no Agent-SDK product
lane. This is the sibling of the SDK adapter (`claude_agent.py`), which stays as
the optional API/provider lane; both satisfy the same `AgentHarness` contract.

Why two Claude harnesses (see WORKLOG.md "Agent-session chat integration"):
Anthropic's Agent-SDK product lane requires an API key and forbids claude.ai-login
for embedded third-party products — correct for a hosted/shared deployment. But a
private, single-user Command Center automating *its own* locally-installed Claude
Code session is a different category: it may reuse the subscription OAuth the CLI
already holds. This adapter is that lane.

Every CLI flag + the stream-json event shape here was verified LIVE against the
installed CLI (v2.1.207) — not guessed from docs (docs' `--tools`/`--safe-mode`
differ across versions). The live probe proved auth with `apiKeySource: "none"` /
`apiProvider: "firstParty"` and captured the real envelope: newline-delimited
`{"type": ...}` objects — `system`(subtype=init, carries session_id) →
`rate_limit_event`(rate_limit_info: status/resetsAt/rateLimitType/overageStatus,
camelCase, no utilization) → `assistant`(message.content blocks) →
`result`(session_id, is_error, total_cost_usd = API-EQUIVALENT, not real spend).

Read-only is DEFENSE IN DEPTH (same discipline as the SDK adapter): `--tools`
restricts the built-in set to Read/Glob/Grep (the actual capability limit, not
just a pre-approve), a `--disallowedTools` writelist, `--permission-mode plan`
(planning mode — no edits), `--strict-mcp-config` with no --mcp-config (zero MCP
servers), `--disable-slash-commands`, and the subprocess env has
`ANTHROPIC_API_KEY` stripped so a stray key can never silently switch this lane to
metered API billing. NEVER `--bare` (it forces API-key auth, skipping OAuth).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, AsyncIterator

from ..events import AgentEvent
from ..protocol import (
    ApprovalDecision, HarnessProbe, SessionStart, session_spec_metadata,
)
from ..store import SessionStoreProtocol
from ..workspace_scope import claude_cli_read_deny_args, prepend_workspace_bounds

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MODEL_PREFS_CONFIG = _REPO_ROOT / "configs" / "agent-session-models.yaml"

_READ_ONLY_TOOLS = ("Read", "Glob", "Grep")
_DISALLOWED_TOOLS = (
    "Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "BashOutput",
    "KillShell", "WebSearch", "WebFetch", "Task")
_DEFAULT_MAX_TURNS = 20

# Validated Claude Code CLI model-alias catalog for the picker. The CLI has no
# models() RPC, so this is a curated alias list (verified against `claude --help`
# and the init event's model list); the RESOLVED concrete model is captured from
# the stream-json at run time. Aliases update to the account's recommended model;
# the [1m] variants pin the 1M-context build (a distinct model id, not a flag).
_MODEL_CATALOG = (
    # (id, display_name, is_default)
    ("default", "Auto — recommended", True),
    ("opus", "Opus", False),
    ("opus[1m]", "Opus (1M context)", False),
    ("opusplan", "Opus Plan (opus plans, sonnet executes)", False),
    ("sonnet", "Sonnet", False),
    ("sonnet[1m]", "Sonnet (1M context)", False),
    ("haiku", "Haiku", False),
    ("fable", "Fable", False),
)
# effort levels the CLI accepts (--effort); not every model supports every level,
# so the picker should let the CLI clamp and the session records requested vs
# applied (the applied value is echoed back in the stream's init metadata).
_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def list_models_catalog() -> list[dict[str, Any]]:
    return [{"id": mid, "display_name": disp, "is_default": is_def,
             "description": "", "default_effort": None,
             "supported_efforts": list(_EFFORTS), "context_options": [],
             "available": True}
            for mid, disp, is_def in _MODEL_CATALOG]


def _claude_bin() -> str | None:
    return shutil.which("claude")


def _resolve_repo_path(repo_id: str) -> Path:
    """Delegate to the ONE shared context resolver (registered autonomy
    manifests + the Home workspace special case)."""
    from ..context_resolver import resolve_context_path
    return resolve_context_path(repo_id)


def _load_model_prefs() -> dict[str, Any]:
    import yaml
    if not _MODEL_PREFS_CONFIG.is_file():
        return {}
    data = yaml.safe_load(_MODEL_PREFS_CONFIG.read_text(encoding="utf-8")) or {}
    result = data.get("claude_code_local", {})
    return result if isinstance(result, dict) else {}


def _resolve_model(requested: str | None) -> tuple[str | None, str]:
    if requested:
        return requested, "explicitly requested by the caller"
    prefs = _load_model_prefs()
    preferred = prefs.get("preferred_model")
    if preferred:
        return str(preferred), f"configured preferred_model ({preferred})"
    return None, "CLI default (no preferred_model configured)"


def _max_turns() -> int:
    prefs = _load_model_prefs()
    try:
        return int(prefs.get("max_turns", _DEFAULT_MAX_TURNS))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_TURNS


# Surfaced in the probe detail -> cockpit assistant dropdown tooltip: this
# lane carries the repo CLAUDE.md, which encodes the Claude<->Codex
# AI-assistance protocol (see docs/engineering/
# AI_ASSISTED_DEVELOPMENT_WORKFLOW.md). Sessions launch with cwd=repo, so the
# CLI auto-loads that project context; the installed skill-codex plugin gives
# DIRECT Claude Code sessions /codex handoffs, while cockpit sessions stay
# read-only and hand off via the assistant switcher instead.
_PROTOCOL_NOTE = (
    "runs with the repo CLAUDE.md protocol — Claude plans/reviews, deep-code "
    "work hands off to Codex (skill-codex plugin in direct sessions; the "
    "assistant switcher here)")


def _subprocess_env() -> dict[str, str]:
    """The CLI subprocess env with ANTHROPIC_API_KEY stripped, so a stray key in
    the operator's environment can never silently switch this subscription lane
    to metered API billing (the whole point of this harness is NO API key)."""
    return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}


def _normalize_cli_rate_limit(info: dict[str, Any]) -> dict[str, Any]:
    """The CLI's rate_limit_event uses camelCase and omits utilization; map it to
    the snake-case dict ClaudeRateLimitCollector.feed() consumes."""
    return {
        "status": info.get("status"),
        "rate_limit_type": info.get("rateLimitType"),
        "utilization": info.get("utilization"),      # absent from the CLI -> None
        "resets_at": info.get("resetsAt"),
        "overage_status": info.get("overageStatus"),
        "overage_resets_at": info.get("overageResetsAt"),
        "overage_disabled_reason": info.get("overageDisabledReason"),
    }


def _assistant_events(message: dict[str, Any]) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    for block in message.get("content", []) or []:
        bt = block.get("type")
        if bt == "text":
            text = block.get("text", "")
            if text.strip():
                events.append(AgentEvent("assistant_message", {"text": text}))
        elif bt == "tool_use":
            name = block.get("name", "")
            tool_input = block.get("input", {}) or {}
            if name == "Bash":
                events.append(AgentEvent("command_started", {
                    "item_id": block.get("id"), "command": tool_input.get("command", "")}))
            else:
                events.append(AgentEvent("tool_started", {
                    "item_id": block.get("id"), "tool": name, "input": tool_input}))
        elif bt == "tool_result":
            events.append(AgentEvent("tool_finished", {
                "item_id": block.get("tool_use_id"), "is_error": block.get("is_error")}))
    return events


def _translate_line(obj: dict[str, Any]) -> list[AgentEvent]:
    """One parsed stream-json object -> zero or more AgentEvents. Dispatches on
    the object's `type` field (structured JSON, never prose). session_id capture
    happens in send()."""
    t = obj.get("type")
    if t == "system":
        return []          # init/metadata; session_id captured in send()
    if t == "rate_limit_event":
        return [AgentEvent("rate_limit", _normalize_cli_rate_limit(
            obj.get("rate_limit_info", {}) or {}))]
    if t == "assistant":
        return _assistant_events(obj.get("message", {}) or {})
    if t == "user":
        return []          # tool results echoed back (already shown via tool_started)
    if t == "result":
        # total_cost_usd is API-EQUIVALENT under a subscription (apiKeySource
        # none), NOT real spend — recorded as such, never as actual dollars.
        usage_ev = AgentEvent("usage", {
            "cost_usd": None, "cost_source": "subscription_not_metered",
            "api_equivalent_cost_usd": obj.get("total_cost_usd"),
            "usage": obj.get("usage"), "model_usage": obj.get("modelUsage"),
            "num_turns": obj.get("num_turns"), "duration_ms": obj.get("duration_ms")})
        if obj.get("is_error"):
            reason = str(obj.get("subtype") or obj.get("result") or "error")
            return [usage_ev, AgentEvent("session_failed", {"reason": reason})]
        return [usage_ev, AgentEvent("session_idle", {})]
    if t == "stream_event":
        return []          # partial chunks (not enabled without --include-partial-messages)
    if t == "_exit_error":
        return [AgentEvent("session_failed", {
            "reason": f"claude CLI exited {obj.get('returncode')}: {obj.get('stderr', '')}"})]
    if t == "_nonjson":
        return [AgentEvent("warning", {"message": obj.get("message", "non-JSON line")})]
    return [AgentEvent("warning", {
        "message": f"unmapped claude stream type: {t}", "unmapped_type": t})]


class ClaudeCodeLocalHarness:
    """Local subscription-login Claude harness. Each turn is a fresh `claude -p`
    subprocess; session continuity is via the CLI's own persisted sessions
    (`--resume <external_session_id>`), NOT a long-lived process — so a worker
    restart recovers purely from the durable store, same discipline as the Codex
    adapter."""

    name = "claude_code_local"
    interactive_approvals = False

    def __init__(self, store: SessionStoreProtocol) -> None:
        self.store = store
        self._active_procs: dict[str, asyncio.subprocess.Process] = {}
        # per-session reasoning effort, pinned at start_session. Kept here (not
        # on the durable SessionRecord) for this milestone — a worker restart
        # resets a resumed turn to the CLI default effort; the requested value
        # is durably recorded in the session_started event either way.
        self._effort: dict[str, str | None] = {}

    def list_models(self) -> list[dict[str, Any]]:
        return list_models_catalog()

    async def probe(self) -> HarnessProbe:
        bin_path = _claude_bin()
        # (see _PROTOCOL_NOTE below for the availability detail's second half)
        if bin_path is None:
            return HarnessProbe(
                available=False,
                detail="claude CLI not found on PATH — install Claude Code and run "
                       "`claude auth login` (this lane uses your subscription, no API key)")
        try:
            status = await asyncio.to_thread(
                subprocess.run, [bin_path, "auth", "status"],
                capture_output=True, text=True, timeout=20)
        except Exception as exc:
            return HarnessProbe(available=False,
                                detail=f"`claude auth status` failed: {exc!r}")
        try:
            data = json.loads(status.stdout or "{}")
        except json.JSONDecodeError:
            data = {}
        if not data.get("loggedIn"):
            return HarnessProbe(
                available=False,
                detail="claude CLI is not logged in — run `claude auth login` "
                       "(no ANTHROPIC_API_KEY needed for the subscription lane)")
        # record only non-secret identity facts (never credential contents/email)
        method = data.get("authMethod")
        sub = data.get("subscriptionType") or data.get("apiProvider")
        return HarnessProbe(
            available=True,
            detail=f"authenticated via {method} ({sub}) — local Claude Code "
                   f"subscription session, no API key; {_PROTOCOL_NOTE}")

    def _build_args(self, bin_path: str, record: Any,
                    repo_path: Path) -> list[str]:
        # The prompt is NOT an argv element: it is fed on stdin (--input-format
        # text, the default) by _stream_cli. Passing a user-sized prompt in argv
        # blew past the Windows 32,767-char CreateProcess command-line limit and
        # failed the whole turn with "The command line is too long." (2026-07-17).
        args = [
            bin_path, "-p",
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "plan",          # planning mode: no edits
            "--strict-mcp-config",                # + no --mcp-config => zero MCP servers
            "--disable-slash-commands",
            "--max-turns", str(_max_turns()),
            "--tools", *_READ_ONLY_TOOLS,         # ACTUAL capability restriction
            "--disallowedTools", *_DISALLOWED_TOOLS,
            "--add-dir", str(repo_path),
        ]
        # Only additions supported by THIS installed CLI's live --help belong
        # here. The shared helper deliberately returns no args when the help
        # lacks a documented read-path deny grammar.
        args += claude_cli_read_deny_args(bin_path, repo_path)
        if record.model:
            args += ["--model", record.model]
        effort = self._effort.get(record.session_id)
        if effort:
            args += ["--effort", effort]      # CLI clamps an unsupported level
        if record.external_session_id:
            args += ["--resume", record.external_session_id]  # follow-up / restart
        return args

    async def _stream_cli(self, session_id: str, args: list[str], cwd: Path,
                          env: dict[str, str],
                          prompt: str) -> AsyncIterator[dict[str, Any]]:
        """Spawn the CLI, feed `prompt` on stdin, and yield parsed stream-json
        objects line by line. The single seam the hermetic tests override —
        translation stays pure."""
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd), env=env,
            # prompt goes in on stdin, not argv (see _build_args): sidesteps the
            # Windows 32,767-char command-line limit for arbitrarily long pastes.
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            # one stream-json line can carry an ENTIRE Read tool result;
            # asyncio's default 64 KiB readline limit raised
            # ValueError('Separator is found, but chunk is longer than
            # limit') and killed a live session mid-answer (2026-07-17)
            limit=16 * 1024 * 1024)
        self._active_procs[session_id] = proc

        async def _feed_stdin() -> None:
            # Write concurrently with the stdout read below: a prompt larger than
            # the OS pipe buffer would block a serial write until the CLI drains
            # it, so we never gate stdout on the write completing. A broken pipe
            # (CLI exited early) is swallowed — the non-zero exit is reported via
            # the _exit_error path below, never masked here.
            assert proc.stdin is not None
            try:
                proc.stdin.write(prompt.encode("utf-8"))
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        feeder = asyncio.create_task(_feed_stdin())
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    yield {"type": "_nonjson", "message": f"non-JSON line: {line[:200]}"}
            await proc.wait()
            if proc.returncode:
                err = ""
                if proc.stderr is not None:
                    err = (await proc.stderr.read()).decode("utf-8", "replace")[:500]
                yield {"type": "_exit_error", "returncode": proc.returncode, "stderr": err}
        finally:
            if not feeder.done():
                feeder.cancel()
            try:
                await feeder
            except (asyncio.CancelledError, Exception):
                pass
            self._active_procs.pop(session_id, None)

    async def start_session(self, request: SessionStart) -> str:
        if request.mode != "analysis":
            raise RuntimeError(
                f"claude_code_local only supports mode='analysis' in this milestone "
                f"(got {request.mode!r}) — workspace/mission modes are not built yet")
        if request.permission_profile != "read_only":
            raise RuntimeError(
                f"claude_code_local only supports permission_profile='read_only' "
                f"(got {request.permission_profile!r})")
        if _claude_bin() is None:
            raise RuntimeError(
                "claude CLI not found on PATH — install Claude Code + `claude auth login`")
        model, model_reason = _resolve_model(request.model)
        record = self.store.create_session(
            harness=self.name, conversation_id=request.conversation_id,
            repo_id=request.repo_id, provider_profile=request.provider_profile,
            model=model, permission_profile=request.permission_profile)
        self._effort[record.session_id] = request.effort   # pinned for the session
        self.store.append_event(record.session_id, AgentEvent(
            "session_started",
            {"mode": request.mode, "model": model,
             "model_selection_reason": model_reason,
             "requested_effort": request.effort, "context_mode": request.context_mode,
             "permission_profile": "read_only", "auth": "subscription_oauth",
             "read_only_tools": list(_READ_ONLY_TOOLS),
             **session_spec_metadata(request)}))
        self.store.set_status(record.session_id, "idle")
        return record.session_id

    async def send(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        bin_path = _claude_bin()
        if bin_path is None:
            raise RuntimeError("claude CLI not found on PATH")
        record = self.store.get(session_id)
        repo_path = _resolve_repo_path(record.repo_id)
        args = self._build_args(bin_path, record, repo_path)
        session_prompt = prompt
        if not record.external_session_id:
            session_prompt = prepend_workspace_bounds(
                prompt, repo_path, record.repo_id)
        async for obj in self._stream_cli(
                session_id, args, repo_path, _subprocess_env(), session_prompt):
            sid = obj.get("session_id")
            if sid and not self.store.get(session_id).external_session_id:
                self.store.update_session(session_id, external_session_id=sid)
            for ev in _translate_line(obj):
                yield self.store.append_event(session_id, ev)

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None:
        """Read-only mode denies writes at the CLI (plan mode + --tools + deny
        list); there is no interactive approval hook. Recorded for audit only."""
        approval = self.store.resolve_approval(
            session_id, decision.approval_id,
            approved=decision.approved, reason=decision.reason)
        self.store.append_event(session_id, AgentEvent("approval_resolved", {
            "approval_id": approval.approval_id, "approved": approval.approved,
            "reason": approval.reason, "effective": False,
            "note": "claude_code_local read-only mode denies write tools at the CLI "
                    "(plan mode); this decision is recorded for audit only"}))

    async def interrupt(self, session_id: str) -> None:
        proc = self._active_procs.get(session_id)
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    async def resume(self, session_id: str) -> None:
        self.store.set_status(session_id, "idle")
        self.store.append_event(session_id, AgentEvent("session_started", {"resumed": True}))

    async def close(self, session_id: str) -> None:
        proc = self._active_procs.pop(session_id, None)
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        self.store.append_event(session_id, AgentEvent("session_closed", {}))
        self.store.set_status(session_id, "closed")

    async def shutdown(self) -> None:
        for proc in list(self._active_procs.values()):
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
        self._active_procs.clear()
