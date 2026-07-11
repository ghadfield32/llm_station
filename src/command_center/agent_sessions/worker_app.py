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

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

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


def build_app(*, store: SessionStoreProtocol | None = None,
             token: str | None = None) -> FastAPI:
    store = store if store is not None else _default_store()
    token = token if token is not None else _default_token()
    service = AgentSessionService(store=store, registry=default_registry(store))

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

    @app.post("/api/agent-sessions/{session_id}/messages",
             dependencies=[Depends(_authed)])
    async def send_message(session_id: str, body: MessageIn) -> list[dict]:
        try:
            return [e.to_dict() async for e in
                    service.send_message(session_id, body.prompt)]
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

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
        return {"session_id": session_id, "status": "interrupted"}

    @app.post("/api/agent-sessions/{session_id}/resume",
             dependencies=[Depends(_authed)])
    async def resume(session_id: str) -> dict:
        try:
            await service.resume(session_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"session_id": session_id, "status": "active"}

    @app.delete("/api/agent-sessions/{session_id}", dependencies=[Depends(_authed)])
    async def close_session(session_id: str) -> dict:
        try:
            await service.close(session_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"session_id": session_id, "status": "closed"}

    return app
