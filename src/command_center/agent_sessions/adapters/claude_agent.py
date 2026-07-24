"""ClaudeAgentHarness — the real Claude Agent adapter, backed by the
`claude-agent-sdk` package (pinned exactly under the `agent-claude` optional
dependency group; see pyproject.toml). Read-only ANALYSIS mode ONLY in this
milestone (workspace/mission modes are refused in start_session).

Every SDK type/field used here was verified by live introspection of the pinned
version (see WORKLOG.md "Agent-session chat integration", Claude adapter) — not
guessed from docs. What was NOT done: a live end-to-end acceptance run, because
that needs ANTHROPIC_API_KEY + the --allow-agent-session-egress policy decision,
neither present on the build host. This adapter is therefore built to the
verified surface and proven by hermetic tests (a fake SDK), with live acceptance
explicitly DEFERRED — the same discipline the Codex adapter used, minus the live
proof it was able to run against an existing `codex login` session.

Three deep-research corrections are baked in:

  1. NAMING + AUTH (Anthropic Agent-SDK docs): this is "Claude Agent", never
     "Claude Code", and embedded-product auth is ANTHROPIC_API_KEY (Anthropic
     forbids claude.ai-login for third-party products). probe() requires the key
     and the SDK; the egress of that key is separately gated by
     --allow-agent-session-egress (check_forbidden_providers.py), an operator
     decision this adapter does not make.
  2. DEFENSE IN DEPTH (SDK reference): `allowed_tools` is a PRE-APPROVE list, not
     a strict allowlist — an unlisted tool can still fall through to
     permission_mode / can_use_tool. So read-only mode layers THREE controls:
     allowed_tools={Read,Glob,Grep} + an explicit disallowed_tools writelist + a
     deny-by-default can_use_tool callback (the load-bearing gate: anything not
     in the read-only set is denied), plus setting_sources=None (isolated — no
     user/project/local settings leak) and empty mcp_servers/plugins.
  3. EVENT-DRIVEN LIMITS: a RateLimitEvent is emitted mid-session; it is
     normalized to a `rate_limit` AgentEvent whose payload the worker forwards to
     the usage layer's ClaudeRateLimitCollector. This adapter never infers quota.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator

from ..bench.models import BenchProfile, Verdict
from ..events import AgentEvent
from ..protocol import (
    ApprovalDecision, HarnessProbe, SessionStart, session_spec_metadata,
)
from ..store import SessionStoreProtocol

# src/command_center/agent_sessions/adapters/claude_agent.py -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MODEL_PREFS_CONFIG = _REPO_ROOT / "configs" / "agent-session-models.yaml"

# The read-only tool set. can_use_tool ALLOWS exactly these and denies everything
# else — the authoritative gate. allowed_tools/disallowed_tools are the belt-and-
# suspenders pre-approve/writelist layers on top.
_READ_ONLY_TOOLS = ("Read", "Glob", "Grep")
_DISALLOWED_TOOLS = (
    "Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "BashOutput",
    "KillShell", "WebSearch", "WebFetch", "Task")
# API-lane model aliases (the SDK resolves an alias to the account's model).
_MODEL_CATALOG = (
    ("default", "Auto — recommended", True),
    ("opus", "Opus", False),
    ("sonnet", "Sonnet", False),
    ("haiku", "Haiku", False),
    ("fable", "Fable", False),
)
_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _import_sdk() -> Any:
    """Deferred import — this module must import cleanly even when
    `claude-agent-sdk` (the OPTIONAL `agent-claude` extra) is absent, so
    registry.py can import it unconditionally and only fail inside probe()/other
    methods (same discipline as codex_agent.py / NotBuiltHarness)."""
    try:
        import claude_agent_sdk as sdk
    except ImportError as exc:
        raise ImportError(
            "claude-agent-sdk is not installed (optional dependency) — install "
            "with `uv sync --extra agent-claude` (or "
            "`uv pip install -e '.[agent-claude]'`)") from exc
    return sdk


def _resolve_repo_path(repo_id: str) -> Path:
    """Delegate to the ONE shared context resolver (registered autonomy
    manifests + the Home workspace special case)."""
    from ..context_resolver import resolve_context_path
    return resolve_context_path(repo_id)


def _load_model_prefs() -> dict[str, Any]:
    """claude_agent's block in configs/agent-session-models.yaml (which model, an
    optional per-session max_budget_usd). Missing = no preference, not an error."""
    import yaml
    if not _MODEL_PREFS_CONFIG.is_file():
        return {}
    data = yaml.safe_load(_MODEL_PREFS_CONFIG.read_text(encoding="utf-8")) or {}
    result = data.get("claude_agent", {})
    return result if isinstance(result, dict) else {}


def _resolve_model(requested: str | None) -> tuple[str | None, str]:
    """A caller-requested model wins; else the configured preferred_model; else
    None (the SDK's default). Unlike Codex there is no live model-list RPC to
    validate against, so an explicit model is passed through and the SDK will
    reject an unknown one at connect time (surfaced as a real error, not
    swallowed)."""
    if requested:
        return requested, "explicitly requested by the caller"
    prefs = _load_model_prefs()
    preferred = prefs.get("preferred_model")
    if preferred:
        return str(preferred), f"configured preferred_model ({preferred})"
    return None, "SDK default (no preferred_model configured)"


def _rate_limit_payload(info: Any) -> dict[str, Any]:
    """A RateLimitInfo -> a plain dict (the `rate_limit` AgentEvent payload). Kept
    a dict so the usage-layer collector consumes it WITHOUT importing the SDK
    type (mirrors RateLimitInfo's fields)."""
    return {
        "status": getattr(info, "status", None),
        "rate_limit_type": getattr(info, "rate_limit_type", None),
        "utilization": getattr(info, "utilization", None),
        "resets_at": getattr(info, "resets_at", None),
        "overage_status": getattr(info, "overage_status", None),
        "overage_resets_at": getattr(info, "overage_resets_at", None),
        "overage_disabled_reason": getattr(info, "overage_disabled_reason", None),
    }


def _usage_payload(msg: Any) -> dict[str, Any]:
    return {
        "usage": getattr(msg, "usage", None),
        "model_usage": getattr(msg, "model_usage", None),
        "cost_usd": getattr(msg, "total_cost_usd", None),
        "num_turns": getattr(msg, "num_turns", None),
        "duration_ms": getattr(msg, "duration_ms", None),
    }


def _blocks_to_events(msg: Any) -> list[AgentEvent]:
    """One AssistantMessage's content blocks -> AgentEvents. Dispatches on the
    block's class NAME (never on message text — tool activity is never inferred
    from prose, the load-bearing rule from the frontier tool_calls incident).
    Internal reasoning (ThinkingBlock) and server-side tool blocks are not part of
    the read-only contract and are dropped."""
    events: list[AgentEvent] = []
    for block in getattr(msg, "content", []) or []:
        bt = type(block).__name__
        if bt == "TextBlock":
            text = getattr(block, "text", "")
            if text.strip():
                events.append(AgentEvent("assistant_message", {"text": text}))
        elif bt == "ToolUseBlock":
            name = getattr(block, "name", "")
            tool_input = getattr(block, "input", {}) or {}
            item_id = getattr(block, "id", None)
            if name == "Bash":
                events.append(AgentEvent("command_started", {
                    "item_id": item_id, "command": tool_input.get("command", "")}))
            else:
                events.append(AgentEvent("tool_started", {
                    "item_id": item_id, "tool": name, "input": tool_input}))
        elif bt == "ToolResultBlock":
            events.append(AgentEvent("tool_finished", {
                "item_id": getattr(block, "tool_use_id", None),
                "is_error": getattr(block, "is_error", None)}))
        # ThinkingBlock / ServerToolUseBlock / ServerToolResultBlock: dropped
    return events


def _translate_message(msg: Any) -> list[AgentEvent]:
    """Translate ONE Claude SDK message into zero or more AgentEvents. Anything
    unmapped becomes a visible `warning` naming the exact type — never silently
    dropped, never fabricated. session_id/cost capture happens in send()'s loop
    (from message fields), not here."""
    t = type(msg).__name__
    if t == "AssistantMessage":
        return _blocks_to_events(msg)
    if t in ("UserMessage", "SystemMessage", "StreamEvent"):
        # UserMessage = injected tool results (already represented by the
        # assistant's tool_started/finished); SystemMessage = init/metadata
        # (session_id captured in send()); StreamEvent = partial (not enabled)
        return []
    if t == "RateLimitEvent":
        return [AgentEvent("rate_limit", _rate_limit_payload(
            getattr(msg, "rate_limit_info", None)))]
    if t == "ResultMessage":
        usage_ev = AgentEvent("usage", _usage_payload(msg))
        if getattr(msg, "is_error", False):
            reason = "; ".join(getattr(msg, "errors", None) or []) \
                or str(getattr(msg, "subtype", "error"))
            return [usage_ev, AgentEvent("session_failed", {"reason": reason})]
        return [usage_ev, AgentEvent("session_idle", {})]
    return [AgentEvent("warning", {
        "message": f"unmapped Claude message type: {t}", "unmapped_type": t})]


def _build_read_only_options(sdk: Any, *, repo_path: Path, model: str | None,
                             resume: str | None, max_budget_usd: float | None,
                             effort: str | None = None) -> Any:
    """The read-only ClaudeAgentOptions with all three defense-in-depth layers.
    The can_use_tool callback is the authoritative gate: ALLOW iff the tool is in
    the read-only set, else DENY (verified callback signature: (name, input,
    context) -> PermissionResultAllow | PermissionResultDeny)."""
    async def _deny_writes(tool_name: str, _tool_input: dict[str, Any],
                           _context: Any) -> Any:
        if tool_name in _READ_ONLY_TOOLS:
            return sdk.PermissionResultAllow()
        return sdk.PermissionResultDeny(
            message=(f"{tool_name} denied: claude_agent runs read-only analysis "
                     f"mode (only {', '.join(_READ_ONLY_TOOLS)} are permitted)"),
            interrupt=False)

    return sdk.ClaudeAgentOptions(
        allowed_tools=list(_READ_ONLY_TOOLS),
        disallowed_tools=list(_DISALLOWED_TOOLS),
        can_use_tool=_deny_writes,
        permission_mode="default",       # unlisted tools route to can_use_tool
        setting_sources=None,            # isolated — no user/project/local leak
        mcp_servers={},
        plugins=[],
        cwd=str(repo_path),
        model=model,
        effort=effort,                   # SDK-native reasoning effort (None = default)
        max_budget_usd=max_budget_usd,
        include_partial_messages=False,  # full messages only — no delta dedup needed
        resume=resume,
    )


class ClaudeAgentHarness:
    """Read-only, single-turn-at-a-time Claude Agent adapter. Holds a process-
    local cache of live ClaudeSDKClient objects keyed by session_id — same
    discipline as the Codex adapter/FakeHarness: NO session state that can't be
    reconstructed from the durable store, so a fresh instance (after a worker
    restart) recovers via resume=external_session_id."""

    name = "claude_agent"
    bench_profile = BenchProfile(
        adapter="claude_agent",
        streaming=Verdict.PARTIAL,
        resume=Verdict.PASS,
        write_mode_wall=Verdict.PASS,
        attachments=Verdict.FAIL,
        model_switch=Verdict.PASS,
        interrupt=Verdict.PASS,
        steering=Verdict.FAIL,
    )
    # can_use_tool denies writes automatically; there is no human-in-the-loop
    # approval hook mid-turn in read-only mode (a write is DENIED, not queued for
    # approval), so approvals are non-interactive for this harness — the same
    # honest capability signal codex_agent reports.
    interactive_approvals = False

    def __init__(self, store: SessionStoreProtocol) -> None:
        self.store = store
        self._clients: dict[str, Any] = {}
        self._effort: dict[str, str | None] = {}   # per-session, pinned at start

    def list_models(self) -> list[dict[str, Any]]:
        """API-lane model aliases (the SDK resolves them per account). Kept
        separate from the local-subscription lane's catalog on purpose."""
        return [{"id": mid, "display_name": disp, "is_default": is_def,
                 "description": "", "default_effort": None,
                 "supported_efforts": list(_EFFORTS), "context_options": [],
                 "available": True}
                for mid, disp, is_def in _MODEL_CATALOG]

    async def probe(self) -> HarnessProbe:
        try:
            _import_sdk()
        except ImportError as exc:
            return HarnessProbe(available=False, detail=str(exc))
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return HarnessProbe(
                available=False,
                detail="ANTHROPIC_API_KEY is not set — claude_agent uses API-key "
                       "auth (Anthropic forbids claude.ai-login for embedded "
                       "products) and requires --allow-agent-session-egress")
        return HarnessProbe(
            available=True,
            detail="claude-agent-sdk installed and ANTHROPIC_API_KEY present "
                   "(read-only analysis mode)")

    def _max_budget(self) -> float | None:
        prefs = _load_model_prefs()
        raw = prefs.get("max_budget_usd")
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    async def _ensure_client(self, session_id: str) -> Any:
        """Lazily (re)build the ClaudeSDKClient for a session. resume is the
        session's durable external_session_id (None on a fresh start), so a
        restarted worker continues the same Claude session instead of forking a
        new one."""
        client = self._clients.get(session_id)
        if client is not None:
            return client
        sdk = _import_sdk()
        record = self.store.get(session_id)
        repo_path = _resolve_repo_path(record.repo_id)
        options = _build_read_only_options(
            sdk, repo_path=repo_path, model=record.model,
            resume=record.external_session_id, max_budget_usd=self._max_budget(),
            effort=self._effort.get(session_id))
        client = sdk.ClaudeSDKClient(options)
        await client.connect()
        self._clients[session_id] = client
        return client

    async def start_session(self, request: SessionStart) -> str:
        if request.mode != "analysis":
            raise RuntimeError(
                f"claude_agent only supports mode='analysis' in this milestone "
                f"(got {request.mode!r}) — workspace/mission modes are not built yet")
        if request.permission_profile != "read_only":
            raise RuntimeError(
                f"claude_agent only supports permission_profile='read_only' in "
                f"this milestone (got {request.permission_profile!r})")
        _import_sdk()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "claude_agent requires ANTHROPIC_API_KEY (embedded-product auth) "
                "and --allow-agent-session-egress before a session can start")
        model, model_reason = _resolve_model(request.model)
        record = self.store.create_session(
            harness=self.name, conversation_id=request.conversation_id,
            repo_id=request.repo_id, provider_profile=request.provider_profile,
            model=model, permission_profile=request.permission_profile)
        self._effort[record.session_id] = request.effort   # pinned for the session
        # eager connect proves auth + the CLI subprocess before we claim "idle"
        await self._ensure_client(record.session_id)
        self.store.append_event(record.session_id, AgentEvent(
            "session_started",
            {"mode": request.mode, "model": model,
             "model_selection_reason": model_reason,
             "permission_profile": "read_only", "auth": "anthropic_api_key",
             "read_only_tools": list(_READ_ONLY_TOOLS),
             **session_spec_metadata(request)}))
        self.store.set_status(record.session_id, "idle")
        return record.session_id

    async def send(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        client = await self._ensure_client(session_id)
        await client.query(prompt)
        async for msg in client.receive_response():
            # capture the real Claude session id (for durable resume) + cost the
            # moment they appear, from the message's own fields
            sid = getattr(msg, "session_id", None)
            if sid and not self.store.get(session_id).external_session_id:
                self.store.update_session(session_id, external_session_id=sid)
            cost = getattr(msg, "total_cost_usd", None)
            if cost is not None:
                self.store.update_session(session_id, cost_usd=float(cost))
            for ev in _translate_message(msg):
                yield self.store.append_event(session_id, ev)

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None:
        """Read-only mode has no interactive approval flow: a write tool is DENIED
        by can_use_tool, never queued for a human decision. This records the
        operator's decision for audit ONLY (effective: False), the same honest
        signal codex_agent gives for its auto-resolved Guardian reviews."""
        approval = self.store.resolve_approval(
            session_id, decision.approval_id,
            approved=decision.approved, reason=decision.reason)
        self.store.append_event(session_id, AgentEvent("approval_resolved", {
            "approval_id": approval.approval_id, "approved": approval.approved,
            "reason": approval.reason, "effective": False,
            "note": "claude_agent read-only mode denies write tools automatically "
                    "(can_use_tool); this decision is recorded for audit only"}))

    async def interrupt(self, session_id: str) -> None:
        """Stop a genuinely in-flight turn. Durable interrupted/failed bookkeeping
        is the worker's job (cancelling the active run) — recording it here too
        would double the event."""
        client = self._clients.get(session_id)
        if client is not None:
            await client.interrupt()

    async def resume(self, session_id: str) -> None:
        self.store.set_status(session_id, "idle")
        self.store.append_event(session_id, AgentEvent("session_started", {"resumed": True}))

    async def close(self, session_id: str) -> None:
        client = self._clients.pop(session_id, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception as exc:
                self.store.append_event(session_id, AgentEvent(
                    "warning", {"message": f"claude disconnect failed: {exc!r}"}))
        self.store.append_event(session_id, AgentEvent("session_closed", {}))
        self.store.set_status(session_id, "closed")

    async def shutdown(self) -> None:
        """Worker-shutdown hook (not part of the AgentHarness Protocol) — closes
        every live ClaudeSDKClient so a worker restart never leaks a `claude` CLI
        subprocess. Best-effort; must not hang on a stuck client."""
        for client in list(self._clients.values()):
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()
