"""CodexAgentHarness — the real Codex Agent adapter, backed by the `openai-codex`
SDK (pinned exactly under the `agent-codex` optional dependency group; see
pyproject.toml). Read-only analysis mode ONLY in this milestone: workspace/
full-access sandboxes are explicitly refused (see start_session). Every SDK
type used here was verified by live introspection against the pinned
package, not guessed from docs — see WORKLOG.md "Agent-session chat
integration" for the session that did that introspection and what it found.

REAL FINDING (0.1.0b3, verified 2026-07-11): the SDK exposes no programmatic
hook to resolve a Guardian approval review — decisions are made automatically
by ApprovalMode.auto_review (Codex's own risk-based reviewer) or blanket-
denied by ApprovalMode.deny_all. There is no "wait for an external approve/
deny call" mode. This harness uses deny_all (nothing elevated is ever
silently allowed just because sandbox=read_only didn't block it outright);
resolve_approval() below is consequently a durable-record-only, non-causal
operation for this harness — see its docstring.

REAL FINDING: authentication reuses the existing `codex login` CLI session
automatically (AsyncCodex() with no config talks to the bundled codex_bin
subprocess, which reads ~/.codex/auth.json) — no ANTHROPIC_API_KEY/
OPENAI_API_KEY, no --allow-agent-session-egress gate needed for THIS harness
specifically (that gate exists for the vendor keys those forbidden-provider
scans look for; Codex's ChatGPT-session auth never sets one). Verified live:
a real account() call against Geoff's actual `codex login` session succeeded.
Real usage against this harness consumes that account's real subscription
quota (plan_type as reported by account()), not per-call API billing.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator

from ..events import AgentEvent
from ..protocol import ApprovalDecision, HarnessProbe, SessionStart
from ..store import SessionStoreProtocol

# Repo root: src/command_center/agent_sessions/adapters/codex_agent.py -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AUTONOMY_CONFIG = _REPO_ROOT / "configs" / "autonomy.yaml"
_MODEL_PREFS_CONFIG = _REPO_ROOT / "configs" / "agent-session-models.yaml"

# Two notification class names were found live for command-execution output
# deltas (CommandExecOutputDeltaNotification and
# CommandExecutionOutputDeltaNotification) — looks like an in-progress rename
# in the SDK. Both are handled identically rather than guessing which one a
# given build actually emits.
_COMMAND_OUTPUT_DELTA_TYPES = frozenset({
    "CommandExecOutputDeltaNotification", "CommandExecutionOutputDeltaNotification",
})


def _import_sdk() -> Any:
    """Deferred import — codex_agent.py itself must import cleanly even when
    `openai-codex` (an OPTIONAL dependency, pyproject.toml's `agent-codex`
    extra) is not installed, so registry.py can import this module
    unconditionally and only fail inside probe()/other methods, never just
    from being imported/listed (same discipline NotBuiltHarness documents)."""
    try:
        import openai_codex as oc
    except ImportError as exc:
        raise ImportError(
            "openai-codex is not installed (optional dependency) — install "
            "with `uv sync --extra agent-codex` (or "
            "`uv pip install -e '.[agent-codex]'`)") from exc
    return oc


def _resolve_repo_path(repo_id: str) -> Path:
    """Uses cli/repo_registry.py's OWN canonical resolver — not a
    reimplementation. A registered repo must resolve identically everywhere
    (this adapter, `cc repo-verify`, the cockpit) and path-boundary/symlink
    policy must live in exactly one place. Also eliminates this module's own
    direct `yaml` import (see the mypy note this used to carry)."""
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
    """codex_agent's own model-preference config (configs/agent-session-
    models.yaml) — kept separate from agent-session-budgets.yaml (that file
    is egress/enablement policy; this is "which model, and what to do if
    it's not available in this SDK build"). Missing file = no preference
    configured, not an error (the SDK default still applies)."""
    import yaml
    if not _MODEL_PREFS_CONFIG.is_file():
        return {}
    data = yaml.safe_load(_MODEL_PREFS_CONFIG.read_text(encoding="utf-8")) or {}
    result = data.get("codex_agent", {})
    return result if isinstance(result, dict) else {}


async def _resolve_model(client: Any, requested: str | None) -> tuple[str, str]:
    """REAL FINDING (2026-07-11): a hardcoded model string is not safe — the
    pinned openai-codex-cli-bin build can lag behind an operator's global
    ~/.codex/config.toml model preference (a real live turn failed:
    "'gpt-5.6-sol' requires a newer version of Codex"). Never trusts a
    caller-requested OR configured model blind — both are checked against
    the SDK's OWN live model list (client.models()) first. Returns
    (model_id, reason) so the caller can record WHY this model was picked,
    not just which one."""
    response = await client.models()
    available = {m.id: m for m in response.data}
    if not available:
        raise RuntimeError("Codex reported no models at all")

    if requested:
        if requested in available:
            return requested, "explicitly requested by the caller"
        raise RuntimeError(
            f"requested model {requested!r} is not in this Codex build's "
            f"model list: {sorted(available)}")

    prefs = _load_model_prefs()
    preferred = prefs.get("preferred_model")
    if preferred and preferred in available:
        return preferred, f"configured preferred_model ({preferred})"

    if preferred and not prefs.get("allow_sdk_default_fallback", True):
        raise RuntimeError(
            f"configured preferred_model {preferred!r} (configs/agent-session-"
            f"models.yaml) is not available in this Codex build "
            f"({sorted(available)}) and allow_sdk_default_fallback is false")

    default_model = next((m.id for m in response.data if m.is_default), None)
    if default_model:
        reason = (f"SDK-designated default (configured preferred_model "
                  f"{preferred!r} unavailable)" if preferred
                  else "SDK-designated default (no preferred_model configured)")
        return default_model, reason

    # no model flagged is_default at all — last resort, first one reported
    first = next(iter(available))
    return first, "no SDK-designated default; first available model"


def _account_label(acct: Any) -> str:
    try:
        root = acct.account.root
    except AttributeError:
        return "unknown account"
    email = getattr(root, "email", None)
    plan = getattr(root, "plan_type", None)
    if email:
        return f"{email}" + (f" ({plan.value if hasattr(plan, 'value') else plan})" if plan else "")
    return getattr(root, "type", "unknown account type")


def _unwrap(value: Any) -> Any:
    """Several Codex types (ThreadItem, GuardianApprovalReviewAction, ...) are
    pydantic RootModel wrappers around the real discriminated-union member —
    verified live: `p.item.type` raises AttributeError on the wrapper itself,
    the real fields live on `p.item.root`. Falls back to the value unchanged
    when there's no `.root` (e.g. this project's own fakes in
    test_codex_agent_adapter.py, which construct the concrete type directly)."""
    return getattr(value, "root", value)


def _item_started_events(item: Any) -> list[AgentEvent]:
    item = _unwrap(item)
    item_id = getattr(item, "id", None)
    item_type = getattr(item, "type", None)
    if item_type in ("agentMessage", "reasoning", "userMessage"):
        # covered by AgentMessageDeltaNotification streaming / not part of the
        # public event contract for this milestone (internal reasoning trace)
        return []
    if item_type == "commandExecution":
        return [AgentEvent("command_started",
                           {"item_id": item_id, "command": getattr(item, "command", "")})]
    if item_type == "fileChange":
        # should never actually happen under Sandbox.read_only — surfaced as a
        # visible tool_requested event rather than silently ignored so a real
        # mutation attempt is never invisible
        return [AgentEvent("tool_requested", {"item_id": item_id, "tool": "fileChange"})]
    return [AgentEvent("tool_started", {"item_id": item_id, "item_type": item_type})]


class _TurnState:
    """Per-turn state threaded through _translate() for exactly one
    real send() call — never shared across turns/sessions. Exists to fix
    two real duplication bugs found by inspecting a real live turn's actual
    event sequence (see WORKLOG.md "Agent-session chat integration"):
    (1) the SDK emits BOTH streaming AgentMessageDeltaNotification chunks
    AND a completed agentMessage item carrying the SAME full text — without
    tracking which item_ids were already streamed, a naive translator
    duplicates every assistant response; (2) a failed turn can emit BOTH
    ErrorNotification and TurnCompletedNotification(status=failed) for the
    SAME failure — without a terminal-emitted flag, that's two
    session_failed events for one real failure."""

    def __init__(self) -> None:
        self.delta_item_ids: set[str] = set()
        self.terminal_emitted = False


def _item_completed_events(item: Any, state: "_TurnState") -> list[AgentEvent]:
    item = _unwrap(item)
    item_id = getattr(item, "id", None)
    item_type = getattr(item, "type", None)
    if item_type == "agentMessage":
        if item_id in state.delta_item_ids:
            # already fully streamed via assistant_delta — re-emitting the
            # complete text here would duplicate it for any renderer that
            # doesn't itself coalesce by item_id (the shipped cockpit UI
            # does not — see WORKLOG.md for the real live turn that showed
            # this duplication).
            return []
        # no deltas were ever seen for this item_id — the ONLY
        # representation of this message is the completed item itself
        # (a real possibility: not every response necessarily streams),
        # so it must NOT be dropped.
        return [AgentEvent("assistant_message",
                           {"item_id": item_id, "text": getattr(item, "text", "")})]
    if item_type in ("reasoning", "userMessage"):
        return []
    if item_type == "commandExecution":
        return [AgentEvent("command_finished", {
            "item_id": item_id, "command": getattr(item, "command", ""),
            "exit_code": getattr(item, "exit_code", None),
            "output": getattr(item, "aggregated_output", None)})]
    if item_type == "fileChange":
        return [AgentEvent("file_changed",
                           {"item_id": item_id, "status": str(getattr(item, "status", ""))})]
    return [AgentEvent("tool_finished", {"item_id": item_id, "item_type": item_type})]


def _guardian_action_summary(action: Any) -> str:
    try:
        root = action.root
    except AttributeError:
        return str(action)
    return type(root).__name__


def _translate(notif: Any, state: "_TurnState | None" = None) -> list[AgentEvent]:
    """Translates ONE real Codex Notification into zero or more AgentEvents.
    Dispatches on the notification's own class name (never on message TEXT —
    tool activity is never inferred from prose). Anything not explicitly
    mapped becomes a visible `warning` event naming the exact unmapped type,
    never silently dropped and never fabricated into a fake event.

    `state` defaults to a fresh, throwaway _TurnState when omitted — every
    single-notification test in test_codex_agent_adapter.py calls this
    function directly with just one notification, where per-turn dedup
    doesn't apply. send() always passes ONE real _TurnState shared across
    an entire turn's notification stream."""
    if state is None:
        state = _TurnState()
    t = type(notif).__name__

    if t == "AgentMessageDeltaNotification":
        state.delta_item_ids.add(notif.item_id)
        return [AgentEvent("assistant_delta",
                           {"item_id": notif.item_id, "text": notif.delta})]
    if t == "ItemStartedNotification":
        return _item_started_events(notif.item)
    if t == "ItemCompletedNotification":
        return _item_completed_events(notif.item, state)
    if t in _COMMAND_OUTPUT_DELTA_TYPES:
        return [AgentEvent("tool_output", {"item_id": notif.item_id, "output": notif.delta})]
    if t == "FileChangePatchUpdatedNotification":
        try:
            changes = [c.model_dump(mode="json") for c in notif.changes]
        except Exception:
            changes = [str(c) for c in notif.changes]
        return [AgentEvent("file_changed", {"item_id": notif.item_id, "changes": changes})]
    if t == "ItemGuardianApprovalReviewStartedNotification":
        return [AgentEvent("approval_required", {
            "review_id": notif.review_id,
            "action": _guardian_action_summary(notif.action)})]
    if t == "ItemGuardianApprovalReviewCompletedNotification":
        # GuardianApprovalReview.status is a required (non-Optional)
        # GuardianApprovalReviewStatus enum — verified by live introspection,
        # not defensive guesswork.
        approved = notif.review.status.value == "approved"
        return [AgentEvent("approval_resolved", {
            "review_id": notif.review_id, "approved": approved,
            "decision_source": str(notif.decision_source)})]
    if t == "ThreadTokenUsageUpdatedNotification":
        u = notif.token_usage
        try:
            total = u.total.model_dump(mode="json")
        except Exception:
            total = str(u.total)
        return [AgentEvent("usage", {"total": total,
                                     "context_window": u.model_context_window})]
    if t == "ErrorNotification":
        if notif.will_retry:
            # transient, the SDK is retrying on its own — not a terminal
            # failure, must not set state.terminal_emitted
            return [AgentEvent("warning",
                               {"message": notif.error.message, "will_retry": True})]
        state.terminal_emitted = True
        return [AgentEvent("session_failed",
                           {"reason": notif.error.message, "will_retry": False})]
    if t == "WarningNotification":
        return [AgentEvent("warning", {"message": notif.message})]
    if t == "TurnCompletedNotification":
        status = str(notif.turn.status)
        if "fail" in status.lower() or "error" in status.lower():
            if state.terminal_emitted:
                # a prior non-retryable ErrorNotification already recorded
                # this SAME failure — this would be the second, duplicate
                # session_failed event for one real failure (see WORKLOG.md
                # "Agent-session chat integration" for the real event
                # sequence that showed this).
                return []
            state.terminal_emitted = True
            return [AgentEvent("session_failed", {"reason": f"turn status: {status}"})]
        return [AgentEvent("session_idle", {})]
    if t == "ThreadClosedNotification":
        return [AgentEvent("session_closed", {})]
    if t in ("ThreadStartedNotification", "TurnStartedNotification"):
        # session_started is emitted by start_session() itself; nothing extra
        # needed for the turn-level start here
        return []
    return [AgentEvent("warning", {
        "message": f"unmapped Codex notification type: {t}",
        "unmapped_type": t})]


class CodexAgentHarness:
    """Read-only, single-turn-at-a-time Codex Agent adapter. Holds a
    process-local cache of live AsyncThread/AsyncTurnHandle objects
    (self._threads/self._active_turns) — same discipline as FakeHarness: NO
    session-scoped state that can't be reconstructed from the durable store,
    so a fresh instance pointed at the same store (e.g. after a worker
    restart) recovers correctly via thread_resume()."""

    name = "codex_agent"
    # REAL FINDING: the pinned SDK exposes no programmatic hook to causally
    # resolve a Guardian approval review (see module docstring and
    # resolve_approval below) — surfaced as a real, queryable capability
    # (HarnessRegistry.probes() reads this) rather than a UI-only assumption,
    # so a caller can tell "does approve/deny here actually do anything"
    # without having read this adapter's source.
    interactive_approvals = False

    def __init__(self, store: SessionStoreProtocol) -> None:
        self.store = store
        self._client: Any = None
        self._threads: dict[str, Any] = {}
        self._active_turns: dict[str, Any] = {}

    async def _client_ready(self) -> Any:
        if self._client is None:
            oc = _import_sdk()
            # REAL FINDING (2026-07-11): a global ~/.codex/config.toml value
            # this harness doesn't control (e.g. model_reasoning_effort set to
            # a tier newer than the pinned openai-codex-cli-bin build
            # recognizes) can make thread_start fail with a JSON-RPC config-
            # parse error even though account() succeeds — the app-server
            # apparently only validates the full config on thread setup, not
            # at process start. Overridden per-session here (--config
            # key=value, the SDK's own mechanism) rather than editing the
            # user's global CLI config, which is used for things beyond this
            # harness. "medium" is a safe, always-valid choice for a
            # read-only analysis session regardless of the operator's
            # personal interactive-CLI preference.
            self._client = oc.AsyncCodex(oc.CodexConfig(
                config_overrides=("model_reasoning_effort=medium",)))
        return self._client

    async def probe(self) -> HarnessProbe:
        try:
            _import_sdk()
        except ImportError as exc:
            return HarnessProbe(available=False, detail=str(exc))
        try:
            client = await self._client_ready()
            acct = await client.account()
        except Exception as exc:
            return HarnessProbe(
                available=False,
                detail=f"codex authentication probe failed: {exc!r} — run "
                       f"`codex login` on this host")
        return HarnessProbe(
            available=True,
            detail=f"authenticated as {_account_label(acct)} via the existing "
                   f"codex login session (openai-codex SDK)")

    async def _resolve_thread(self, session_id: str, oc: Any) -> Any:
        thread = self._threads.get(session_id)
        if thread is not None:
            return thread
        record = self.store.get(session_id)
        if not record.external_session_id:
            raise RuntimeError(
                f"session {session_id!r} has no external_session_id to resume")
        client = await self._client_ready()
        thread = await client.thread_resume(
            record.external_session_id, sandbox=oc.Sandbox.read_only,
            approval_mode=oc.ApprovalMode.deny_all)
        self._threads[session_id] = thread
        return thread

    async def start_session(self, request: SessionStart) -> str:
        if request.mode != "analysis":
            raise RuntimeError(
                f"codex_agent only supports mode='analysis' in this milestone "
                f"(got {request.mode!r}) — workspace/mission modes are not built yet")
        if request.permission_profile != "read_only":
            raise RuntimeError(
                f"codex_agent only supports permission_profile='read_only' in "
                f"this milestone (got {request.permission_profile!r})")
        oc = _import_sdk()
        repo_path = _resolve_repo_path(request.repo_id)
        client = await self._client_ready()
        model, model_reason = await _resolve_model(client, request.model)
        thread = await client.thread_start(
            sandbox=oc.Sandbox.read_only, approval_mode=oc.ApprovalMode.deny_all,
            cwd=str(repo_path), model=model)
        record = self.store.create_session(
            harness=self.name, conversation_id=request.conversation_id,
            repo_id=request.repo_id, provider_profile=request.provider_profile,
            model=model, permission_profile=request.permission_profile)
        self.store.update_session(record.session_id, external_session_id=thread.id)
        self._threads[record.session_id] = thread
        self.store.append_event(record.session_id, AgentEvent(
            "session_started",
            {"mode": request.mode, "external_session_id": thread.id,
             "model": model, "model_selection_reason": model_reason}))
        # "idle" = ready, no turn running yet — matches FakeHarness/worker_app's
        # status vocabulary exactly (see worker_app.py's async-execution note)
        self.store.set_status(record.session_id, "idle")
        return record.session_id

    async def send(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        oc = _import_sdk()
        thread = await self._resolve_thread(session_id, oc)
        handle = await thread.turn(
            prompt, sandbox=oc.Sandbox.read_only, approval_mode=oc.ApprovalMode.deny_all)
        self._active_turns[session_id] = handle
        # ONE state for this entire turn — never shared across turns/
        # sessions — so delta-coalescing and terminal-failure dedup (see
        # _TurnState's docstring) work across the whole notification stream.
        state = _TurnState()
        try:
            async for notif in handle.stream():
                # handle.stream() yields a generic Notification(method,
                # payload) envelope — verified live: the concrete typed
                # instance (TurnStartedNotification, ItemCompletedNotification,
                # ...) is `.payload`, never the envelope itself.
                for ev in _translate(notif.payload, state):
                    yield self.store.append_event(session_id, ev)
        finally:
            self._active_turns.pop(session_id, None)

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None:
        """REAL LIMITATION (see module docstring): the SDK exposes no hook to
        cause a real Guardian review to resolve differently — this harness
        runs deny_all, so nothing elevated is ever silently approved
        regardless of what's recorded here. This durably records the
        operator's decision for audit/visibility ONLY; it has no causal
        effect on Codex. `effective: False` in the event payload makes that
        explicit to any UI rendering it, rather than implying a real approval
        flow that doesn't exist in this SDK version."""
        approval = self.store.resolve_approval(
            session_id, decision.approval_id,
            approved=decision.approved, reason=decision.reason)
        self.store.append_event(session_id, AgentEvent("approval_resolved", {
            "approval_id": approval.approval_id, "approved": approval.approved,
            "reason": approval.reason, "effective": False,
            "note": "codex_agent's Guardian approval reviews are resolved "
                    "automatically by the SDK (deny_all in read-only mode); "
                    "this decision is recorded for audit only"}))

    async def interrupt(self, session_id: str) -> None:
        """Only tells a genuinely in-flight real Codex turn to stop. Durable
        session_failed/interrupted bookkeeping is the WORKER's job
        (_run_turn's CancelledError handler, triggered by cancelling the
        active_runs task right after this call returns — see
        worker_app.py) — recording it here too would double the event."""
        handle = self._active_turns.get(session_id)
        if handle is not None:
            await handle.interrupt()

    async def resume(self, session_id: str) -> None:
        self.store.set_status(session_id, "idle")
        self.store.append_event(session_id, AgentEvent("session_started", {"resumed": True}))

    async def close(self, session_id: str) -> None:
        record = self.store.get(session_id)
        if record.external_session_id:
            try:
                client = await self._client_ready()
                await client.thread_archive(record.external_session_id)
            except Exception as exc:
                # best-effort: closing the LOCAL session record must not fail
                # just because the remote archive call failed (e.g. already gone)
                self.store.append_event(session_id, AgentEvent(
                    "warning", {"message": f"codex thread_archive failed: {exc!r}"}))
        self.store.append_event(session_id, AgentEvent("session_closed", {}))
        self.store.set_status(session_id, "closed")
        self._active_turns.pop(session_id, None)
        self._threads.pop(session_id, None)

    async def shutdown(self) -> None:
        """Called by the worker on process shutdown (see worker_app.py's
        _shutdown_harnesses) — NOT part of the AgentHarness Protocol (close()
        above closes one SESSION; this closes the whole harness instance's
        real subprocess connection). Interrupts any turns still active on
        THIS instance and closes the SDK client, so a worker restart never
        leaves an orphan codex_bin app-server process behind. Safe to call
        even if no client was ever constructed (probe()-only usage)."""
        for handle in list(self._active_turns.values()):
            try:
                await handle.interrupt()
            except Exception:
                pass   # best-effort — shutdown must not hang on a stuck turn
        self._active_turns.clear()
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass   # best-effort — a broken client has nothing left to leak
            self._client = None
