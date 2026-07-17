"""The host-side agent worker: owns harness instances, the durable Ledger-backed
session store, and (once real adapters exist) local SDK/CLI authentication —
none of which the cockpit container should see directly, same reasoning as the
existing host.docker.internal pattern for Ollama/external board runtime in docker-compose.yml.
Exposes /api/agent-sessions/* over plain HTTP, gated by a bearer token the
cockpit is separately configured with; binds to localhost only by default (see
cli/agent_worker.py, the `cc agent-worker` entry point).

Wires the full `registry.default_registry()` — fake plus the REAL adapters:
`codex_agent` (ChatGPT-login), `claude_code_local` (Claude CLI subscription
login, the default Claude lane), and `claude_agent` (Agent SDK + API key). Each
harness's availability is computed live by its own probe() (registry.probes()),
so the cockpit's harness selector reflects real, per-host auth state.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .events import AgentEvent
from .protocol import ApprovalDecision, SessionStart
from .registry import default_registry
from .service import AgentSessionService
from .store import SessionStoreProtocol


logger = logging.getLogger(__name__)


class ModelCatalogEntry(BaseModel):
    """The ONE model-catalog shape the cockpit picker renders verbatim.
    Adapters normalize their SDK-native shapes to this; validating at the
    serving boundary turns silent contract drift (e.g. an SDK returning
    effort OBJECTS where strings are expected) into a legible catalog error
    instead of a blank browser panel (2026-07-16 incident)."""
    id: str
    display_name: str
    description: str = ""
    is_default: bool = False
    default_effort: str | None = None
    supported_efforts: list[str] = Field(default_factory=list)
    context_options: list[str] = Field(default_factory=list)
    available: bool = True


def _default_store() -> SessionStoreProtocol:
    """The real production store: always Ledger-backed, no in-memory fallback.
    A worker that silently degraded to non-durable storage because an env var
    was missing would be exactly the kind of defect the whole durable-store
    milestone exists to avoid. Tests inject an in-memory SessionStore via
    build_app(store=...) instead of going through this function."""
    ledger_base = os.environ.get("LEDGER_BASE_URL")
    if not ledger_base:
        raise RuntimeError(
            "LEDGER_BASE_URL is not set — the agent worker requires durable "
            "storage and will not silently fall back to an in-memory store")
    import httpx
    from .ledger_store import LedgerSessionStore
    return LedgerSessionStore(httpx.Client(base_url=ledger_base, timeout=30))


def _default_token() -> str:
    token = os.environ.get("AGENT_WORKER_TOKEN")
    if not token:
        raise RuntimeError(
            "AGENT_WORKER_TOKEN is not set — the agent worker refuses to start "
            "without an explicit token (no silently-generated default); set it "
            "in the host .env and configure the cockpit with the same value")
    return token


class SessionStartIn(BaseModel):
    harness_id: str = "fake"
    conversation_id: str
    repo_id: str
    mode: str
    provider_profile: str = "default"
    model: str | None = None
    effort: str | None = None
    context_mode: str | None = None
    permission_profile: str = "read_only"


class MessageIn(BaseModel):
    prompt: str


class ApprovalIn(BaseModel):
    approved: bool
    reason: str = ""


class HandoffIn(BaseModel):
    to_harness: str
    goal: str | None = None
    open_questions: list[str] = Field(default_factory=list)


class AttachmentRequestIn(BaseModel):
    attachment_id: str
    kind: str
    rel_path: str | None = None
    resource_id: str | None = None
    display_name: str


class AttachmentResolveIn(BaseModel):
    repo_id: str | None = None            # context to resolve path kinds against
    external_egress: bool = False         # is the target harness a paid external one?
    items: list[AttachmentRequestIn] = Field(default_factory=list)


_CLAUDE_HARNESSES = ("claude_code_local", "claude_agent")
_USAGE_HARNESSES = ("claude_code_local", "claude_agent", "codex_agent")


def _session_effort(store: SessionStoreProtocol, session_id: str) -> str | None:
    """Recover the session's requested effort from its durable session_started
    event (it's not on the SessionRecord). One store read per turn."""
    try:
        for ev in store.events_since(session_id, 0):
            if ev.type == "session_started" and "requested_effort" in ev.payload:
                return ev.payload.get("requested_effort")
    except Exception:
        pass
    return None


def _worker_feed_usage(usage: object, record: object, effort: str | None,
                       ev: AgentEvent) -> None:
    """Ingest a live agent event into the WORKER's own UsageService, so a
    session's usage is captured even with NO browser SSE attached (the headless
    gap the cockpit tee can't cover). `rate_limit` -> a provider-limit snapshot
    (Claude lanes only; Codex limits come from its own collector); `usage` -> an
    attributed UsageSample (all agent lanes) with model/effort/repo so "top
    model / top effort" is answered from recorded fact. Best-effort — a usage
    failure must never break the turn."""
    if usage is None or record is None:
        return
    harness = getattr(record, "harness", None)
    try:
        if ev.type == "rate_limit" and harness in _CLAUDE_HARNESSES:
            from command_center.usage.collectors.claude_agent import translate_rate_limit_info
            usage.ingest_collector_result(   # type: ignore[attr-defined]
                translate_rate_limit_info(ev.payload or {}, ev.ts or "", harness))
        elif ev.type == "usage" and harness in _USAGE_HARNESSES:
            from command_center.usage.agent_usage import agent_usage_sample
            sample = agent_usage_sample(
                ev.payload or {}, runtime_id=harness,
                session_id=getattr(record, "session_id", None),
                repo_id=getattr(record, "repo_id", None),
                conversation_id=getattr(record, "conversation_id", None),
                model=getattr(record, "model", None), effort=effort,
                observed_at=ev.ts)
            usage.store.ingest_sample(sample)   # type: ignore[attr-defined]
    except Exception:
        logger.exception(
            "agent usage ingestion failed for session=%s harness=%s event=%s",
            getattr(record, "session_id", None), harness, ev.type)


def _reconcile_orphaned_sessions(store: SessionStoreProtocol) -> None:
    """A fresh worker process always starts with an EMPTY active_runs registry
    — asyncio.Task objects never survive a process restart. Any session still
    marked "active" at startup is therefore, by definition, orphaned: nothing
    is actually running it anymore. Mark it failed with an honest reason
    rather than leaving a session permanently "active" that will never
    actually respond again (see the "active" vs "idle" distinction in
    fake_harness.py — this reconciliation is exactly why that distinction
    exists)."""
    for record in store.list_sessions(status="active"):
        store.append_event(record.session_id, AgentEvent(
            "session_failed",
            {"reason": "worker restarted while this session's turn was in "
                       "progress; the previous process's work is lost"}))
        store.set_status(record.session_id, "failed")


def build_app(*, store: SessionStoreProtocol | None = None,
             token: str | None = None, registry=None,
             usage_service: object | None = None,
             usage_collectors: list[tuple[object, str]] | None = None) -> FastAPI:
    store = store if store is not None else _default_store()
    token = token if token is not None else _default_token()
    service = AgentSessionService(
        store=store, registry=registry if registry is not None
        else default_registry(store))
    _reconcile_orphaned_sessions(store)

    # Optional WORKER-OWNED usage ingestion. The worker sees every AgentEvent as
    # the turn runs (see _run_turn), so feeding a UsageService here captures a
    # Claude rate_limit event even when NO browser SSE is attached — the
    # headless gap the cockpit-side tee can't cover. In-memory here; a
    # Ledger-backed worker store (restart-durable) + the cockpit reading THIS
    # (via proxy) instead of its own tee are the documented next steps.
    usage: Any = usage_service
    if usage is None and os.environ.get("AGENT_WORKER_USAGE", "") == "1":
        from command_center.usage.service import UsageService as _UsageService
        ledger_base = os.environ.get("LEDGER_BASE_URL")
        if ledger_base:
            # DURABLE: the worker writes provider-limit observations to the same
            # Ledger the cockpit reads (when KANBAN_UI_USAGE_LEDGER=1), so a
            # worker/cockpit restart preserves the latest known limits and there
            # is ONE authoritative store. Ingestion is idempotent by source_hash.
            import httpx
            from command_center.usage.ledger_store import LedgerUsageStore
            usage = _UsageService(
                LedgerUsageStore(httpx.Client(base_url=ledger_base, timeout=30)))
        else:
            from command_center.usage.store import UsageStore as _UsageStore
            usage = _UsageService(_UsageStore())

    # Provider collectors must run beside the host-owned SDK/CLI login. The
    # cockpit container deliberately has neither the Codex SDK nor the user's
    # ~/.codex credentials, so asking it to refresh provider limits produces a
    # false "SDK not installed" result even while real Codex turns work. Tests
    # may inject a deterministic collector list; production enables the Codex
    # collector whenever worker-owned usage is enabled.
    collectors = usage_collectors if usage_collectors is not None else []
    if (usage is not None and usage_collectors is None
            and os.environ.get("AGENT_WORKER_USAGE", "") == "1"):
        from command_center.usage.collectors.codex_app_server import (
            CODEX_COLLECTOR_ID, CodexAppServerCollector)
        collectors.append((CodexAppServerCollector(), CODEX_COLLECTOR_ID))

    # PROCESS-LOCAL only, same discipline as AgentSessionService's own
    # _active_harnesses cache: the single source of truth for "is a turn
    # genuinely in flight right now" is this dict, not the durable status
    # field (which a fresh process can't populate from nothing on restart —
    # see _reconcile_orphaned_sessions above).
    active_runs: dict[str, asyncio.Task] = {}

    async def _run_turn(session_id: str, prompt: str) -> None:
        """Drives one full turn to completion in the background. Events are
        already durably appended by the harness/store as they're produced
        (service.send_message -> harness.send -> store.append_event) — this
        coroutine's job is the STATUS bookkeeping a synchronous caller can't
        do for itself: active while genuinely running, idle on clean
        completion, failed (with a durable event naming what happened) on a
        real crash or on interrupt-triggered cancellation."""
        store.set_status(session_id, "active")
        # snapshot the attribution context ONCE (avoid a store read per event):
        # model/repo/conversation don't change mid-turn, effort is pinned.
        turn_record = store.get(session_id) if usage is not None else None
        turn_effort = _session_effort(store, session_id) if usage is not None else None
        try:
            async for ev in service.send_message(session_id, prompt):
                _worker_feed_usage(usage, turn_record, turn_effort, ev)
            store.set_status(session_id, "idle")
        except asyncio.CancelledError:
            store.append_event(session_id, AgentEvent(
                "session_failed", {"reason": "interrupted"}))
            store.set_status(session_id, "interrupted")
        except Exception as exc:
            store.append_event(session_id, AgentEvent(
                "session_failed", {"reason": f"unhandled error: {exc!r}"}))
            store.set_status(session_id, "failed")
        finally:
            active_runs.pop(session_id, None)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        for collector, _collector_id in collectors:
            close_fn = getattr(collector, "close", None)
            if close_fn is not None:
                result = close_fn()
                if hasattr(result, "__await__"):
                    await result
        # A real harness adapter (Codex) owns a live SDK client with its own
        # subprocess connection — see adapters/codex_agent.py's shutdown().
        # AgentSessionService caches one harness instance PER SESSION (not
        # one shared instance per harness type — see service.py's
        # _active_harnesses), so shutdown must walk every cached instance,
        # not just one. FakeHarness (and any harness that doesn't declare
        # shutdown()) is skipped — nothing to clean up.
        for harness in list(service._active_harnesses.values()):
            shutdown_fn = getattr(harness, "shutdown", None)
            if shutdown_fn is not None:
                await shutdown_fn()

    app = FastAPI(title="Command Center Agent Worker", version="0.1.0",
                 lifespan=_lifespan)

    async def _authed(authorization: str | None = Header(default=None)) -> None:
        if not secrets.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(401, "missing or invalid worker token")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/runtime-fingerprint", dependencies=[Depends(_authed)])
    def runtime_fingerprint() -> dict:
        """Read-only drift detector: this WORKER process's source root, git SHA,
        tracked-config SHA-256s, and whether its (in-memory) contract still
        validates the on-disk config. cc assistant-doctor compares this to the
        host so config/source drift is caught BEFORE a session fails (see the
        2026-07-17 AutonomyConfig incident)."""
        from .fingerprint import compute_fingerprint
        return compute_fingerprint()

    @app.get("/api/agent-harnesses", dependencies=[Depends(_authed)])
    async def list_harnesses() -> list[dict]:
        return await service.list_harnesses()

    @app.get("/api/agent-harnesses/{harness_id}/models",
            dependencies=[Depends(_authed)])
    async def list_models(harness_id: str) -> dict:
        """Runtime-discovered model catalog for the harness selector (Codex live
        SDK models incl. supported reasoning efforts; Claude validated aliases).
        A discovery failure (e.g. the SDK login expired) surfaces as an empty
        list + a reason, never a 500 that blanks the picker. Every entry is
        VALIDATED against the one catalog contract the cockpit renders
        verbatim — adapter/SDK shape drift becomes a legible error here, never
        an unrenderable object in the browser."""
        try:
            models = [ModelCatalogEntry(**m).model_dump()
                      for m in await service.list_models(harness_id)]
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            return {"harness_id": harness_id, "models": [],
                    "error": f"model discovery failed: {exc!r}"}
        return {"harness_id": harness_id, "models": models}

    if usage is not None:
        from command_center.usage import cockpit_views as _cv

        @app.get("/api/model-usage", dependencies=[Depends(_authed)])
        def model_usage() -> list:
            """Worker-owned usage view — captures headless sessions the
            cockpit-side SSE tee cannot. The cockpit can proxy this to become
            the single authoritative read path (documented next step)."""
            return _cv.usage_overview(usage)

        # Literal routes must precede /{runtime_id}; FastAPI matches in
        # declaration order.
        @app.get("/api/model-usage/collector-health",
                 dependencies=[Depends(_authed)])
        def model_usage_collector_health() -> list:
            return _cv.collector_health(
                usage, [collector_id for _, collector_id in collectors])

        @app.post("/api/model-usage/refresh", dependencies=[Depends(_authed)])
        async def model_usage_refresh() -> dict:
            return await _cv.refresh(usage, collectors)

        @app.get("/api/model-usage/{runtime_id}", dependencies=[Depends(_authed)])
        def model_usage_runtime(runtime_id: str) -> dict:
            return _cv.runtime_detail(usage, runtime_id)

    @app.get("/api/agent-sessions", dependencies=[Depends(_authed)])
    def list_sessions(conversation_id: str | None = None,
                      repo_id: str | None = None) -> list[dict]:
        """Lets a caller recover durable sessions by conversation_id/repo_id
        without relying exclusively on local browser storage — see WORKLOG.md
        "Agent-session chat integration"."""
        return [r.__dict__ for r in
                store.list_sessions(conversation_id=conversation_id, repo_id=repo_id)]

    @app.post("/api/agent-sessions", dependencies=[Depends(_authed)])
    async def create_session(body: SessionStartIn) -> dict:
        try:
            record = await service.start_session(SessionStart(**body.model_dump()))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return record.__dict__

    @app.get("/api/agent-sessions/{session_id}", dependencies=[Depends(_authed)])
    def get_session(session_id: str) -> dict:
        try:
            return service.get_session(session_id).__dict__
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/agent-sessions/{session_id}/messages", status_code=202,
             dependencies=[Depends(_authed)])
    async def send_message(session_id: str, body: MessageIn) -> dict:
        try:
            record = service.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        if record.status == "closed":
            raise HTTPException(400, f"session {session_id!r} is closed")
        if record.status in ("interrupted", "failed"):
            raise HTTPException(
                409, f"session {session_id!r} is {record.status!r} — call "
                    f"/resume before sending a new message")
        existing = active_runs.get(session_id)
        if existing is not None and not existing.done():
            raise HTTPException(
                409, f"session {session_id!r} already has an active turn")
        task = asyncio.create_task(_run_turn(session_id, body.prompt))
        active_runs[session_id] = task
        return {"session_id": session_id, "status": "accepted"}

    @app.get("/api/agent-sessions/{session_id}/events",
            dependencies=[Depends(_authed)])
    def get_events(session_id: str, after_sequence: int = 0) -> list[dict]:
        try:
            return [e.to_dict() for e in
                    service.get_events(session_id, after_sequence)]
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/agent-sessions/{session_id}/handoff",
             dependencies=[Depends(_authed)])
    def build_handoff(session_id: str, body: HandoffIn) -> dict:
        """Assemble a BOUNDED hand-off packet from this session's stored events
        (a briefing — never an unlimited transcript forward, per the plan §6)
        and record `handoff_started` on the SOURCE session as evidence. The
        caller seeds the target assistant with the returned `prompt`; the
        target resumes its own per-harness slot."""
        from .events import AgentEvent
        from .handoff import build_handoff_packet, render_handoff_prompt
        try:
            record = service.get_session(session_id)
            events = service.get_events(session_id, 0)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        packet = build_handoff_packet(
            source_record=record, events=events, to_harness=body.to_harness,
            goal=body.goal, open_questions=body.open_questions)
        store.append_event(session_id, AgentEvent(
            "handoff_started",
            {"to_harness": body.to_harness, "packet": packet.model_dump()}))
        return {"packet": packet.model_dump(),
                "prompt": render_handoff_prompt(packet)}

    @app.post("/api/attachments/resolve", dependencies=[Depends(_authed)])
    def resolve_attachments(body: AttachmentResolveIn) -> dict:
        """Resolve + safety-check the composer's typed attachments on the HOST
        (where the real context roots live). Path kinds are clamped to the
        selected context root and refused on secret/escape/oversize; blocked
        ones are REPORTED in the summary, never dropped."""
        from .attachments import resolve_attachment, summarize_attachments
        from .context_resolver import resolve_context_path
        root = None
        if body.repo_id:
            try:
                root = resolve_context_path(body.repo_id)
            except Exception:      # unresolved context -> path kinds refuse cleanly
                root = None
        resolutions = [
            resolve_attachment(
                attachment_id=it.attachment_id, kind=it.kind, rel_path=it.rel_path,
                resource_id=it.resource_id, display_name=it.display_name,
                context_root=root, external_egress=body.external_egress)
            for it in body.items]
        return {"resolutions": [r.model_dump() for r in resolutions],
                "summary": summarize_attachments(resolutions)}

    @app.post("/api/agent-sessions/{session_id}/approvals/{approval_id}",
             dependencies=[Depends(_authed)])
    async def resolve_approval(session_id: str, approval_id: str,
                               body: ApprovalIn) -> dict:
        try:
            await service.resolve_approval(session_id, ApprovalDecision(
                approval_id=approval_id, approved=body.approved,
                reason=body.reason))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"session_id": session_id, "approval_id": approval_id}

    @app.post("/api/agent-sessions/{session_id}/interrupt",
             dependencies=[Depends(_authed)])
    async def interrupt(session_id: str) -> dict:
        try:
            await service.interrupt(session_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        task = active_runs.get(session_id)
        if task is not None and not task.done():
            task.cancel()   # _run_turn's except CancelledError records why
        return {"session_id": session_id, "status": "interrupted"}

    @app.post("/api/agent-sessions/{session_id}/resume",
             dependencies=[Depends(_authed)])
    async def resume(session_id: str) -> dict:
        try:
            await service.resume(session_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"session_id": session_id, "status": "idle"}

    @app.delete("/api/agent-sessions/{session_id}", dependencies=[Depends(_authed)])
    async def close_session(session_id: str) -> dict:
        # cancel and WAIT for _run_turn's own cancellation handling to finish
        # first, so "closed" (set below) is always the final, authoritative
        # status rather than racing with _run_turn's "interrupted" write
        task = active_runs.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await service.close(session_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"session_id": session_id, "status": "closed"}

    return app
