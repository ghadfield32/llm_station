"""The host-side agent worker: owns harness instances, the durable Ledger-backed
session store, and (once real adapters exist) local SDK/CLI authentication —
none of which the cockpit container should see directly, same reasoning as the
existing host.docker.internal pattern for Ollama/AppFlowy in docker-compose.yml.
Exposes /api/agent-sessions/* over plain HTTP, gated by a bearer token the
cockpit is separately configured with; binds to localhost only by default (see
cli/agent_worker.py, the `cc agent-worker` entry point).

Currently wires ONLY the FakeHarness (registry.default_registry()) — no real
Claude/Codex adapter exists yet (WORKLOG.md "Agent-session chat integration",
Phase 2/3, not started). This worker's job right now is proving the transport,
not running a real agent.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .events import AgentEvent
from .protocol import ApprovalDecision, SessionStart
from .registry import default_registry
from .service import AgentSessionService
from .store import SessionStoreProtocol


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
    permission_profile: str = "read_only"


class MessageIn(BaseModel):
    prompt: str


class ApprovalIn(BaseModel):
    approved: bool
    reason: str = ""


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
             token: str | None = None, registry=None) -> FastAPI:
    store = store if store is not None else _default_store()
    token = token if token is not None else _default_token()
    service = AgentSessionService(
        store=store, registry=registry if registry is not None
        else default_registry(store))
    _reconcile_orphaned_sessions(store)

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
        try:
            async for _ in service.send_message(session_id, prompt):
                pass
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

    app = FastAPI(title="Command Center Agent Worker", version="0.1.0")

    async def _authed(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {token}":
            raise HTTPException(401, "missing or invalid worker token")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/agent-harnesses", dependencies=[Depends(_authed)])
    async def list_harnesses() -> list[dict]:
        return await service.list_harnesses()

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
