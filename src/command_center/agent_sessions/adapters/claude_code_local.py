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
from ..protocol import ApprovalDecision, HarnessProbe, SessionStart
from ..store import SessionStoreProtocol

_REPO_ROOT = Path(__file__).resolve().parents[4]
_AUTONOMY_CONFIG = _REPO_ROOT / "configs" / "autonomy.yaml"
_MODEL_PREFS_CONFIG = _REPO_ROOT / "configs" / "agent-session-models.yaml"

_READ_ONLY_TOOLS = ("Read", "Glob", "Grep")
_DISALLOWED_TOOLS = (
    "Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "BashOutput",
    "KillShell", "WebSearch", "WebFetch", "Task")
_DEFAULT_MAX_TURNS = 20


def _claude_bin() -> str | None:
    return shutil.which("claude")


def _resolve_repo_path(repo_id: str) -> Path:
    from command_center.cli.repo_registry import load_autonomy_config, resolve_repo_local_path

    if not _AUTONOMY_CONFIG.is_file():
        raise RuntimeError(f"configs/autonomy.yaml not found at {_AUTONOMY_CONFIG}")
    cfg = load_autonomy_config(_AUTONOMY_CONFIG)
    manifest = next((m for m in cfg.repo_manifests if m.repo_id == repo_id), None)
    if manifest is None:
        raise RuntimeError(f"repo_id {repo_id!r} is not registered in configs/autonomy.yaml")
    path = resolve_repo_local_path(manifest, _REPO_ROOT, dict(os.environ))
    if path is None:
        raise RuntimeError(
            f"repo_id {repo_id!r} has no resolvable local_path_ref "
            f"(got {manifest.local_path_ref!r})")
    return path


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

    async def probe(self) -> HarnessProbe:
        bin_path = _claude_bin()
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
                   f"subscription session, no API key")

    def _build_args(self, bin_path: str, record: Any, prompt: str,
                    repo_path: Path) -> list[str]:
        args = [
            bin_path, "-p", prompt,
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "plan",          # planning mode: no edits
            "--strict-mcp-config",                # + no --mcp-config => zero MCP servers
            "--disable-slash-commands",
            "--max-turns", str(_max_turns()),
            "--tools", *_READ_ONLY_TOOLS,         # ACTUAL capability restriction
            "--disallowedTools", *_DISALLOWED_TOOLS,
            "--add-dir", str(repo_path),
        ]
        if record.model:
            args += ["--model", record.model]
        if record.external_session_id:
            args += ["--resume", record.external_session_id]  # follow-up / restart
        return args

    async def _stream_cli(self, session_id: str, args: list[str], cwd: Path,
                          env: dict[str, str]) -> AsyncIterator[dict[str, Any]]:
        """Spawn the CLI and yield parsed stream-json objects line by line. The
        single seam the hermetic tests override — translation stays pure."""
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self._active_procs[session_id] = proc
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
        self.store.append_event(record.session_id, AgentEvent(
            "session_started",
            {"mode": request.mode, "model": model,
             "model_selection_reason": model_reason,
             "permission_profile": "read_only", "auth": "subscription_oauth",
             "read_only_tools": list(_READ_ONLY_TOOLS)}))
        self.store.set_status(record.session_id, "idle")
        return record.session_id

    async def send(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        bin_path = _claude_bin()
        if bin_path is None:
            raise RuntimeError("claude CLI not found on PATH")
        record = self.store.get(session_id)
        repo_path = _resolve_repo_path(record.repo_id)
        args = self._build_args(bin_path, record, prompt, repo_path)
        async for obj in self._stream_cli(session_id, args, repo_path, _subprocess_env()):
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
