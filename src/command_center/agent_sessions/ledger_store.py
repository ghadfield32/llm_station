"""LedgerSessionStore — the durable sibling of store.SessionStore, backed by the
Ledger service's new /agent-session* endpoints (see ledger_schema.py) instead of an
in-process dict. Same public surface (create_session/get/append_event/
events_since/set_status) so FakeHarness, a future real adapter, and
AgentSessionService can use either interchangeably — see store.py's SessionRecord,
which this returns unmodified.

Deliberately SYNC, matching SessionStore's existing interface, not async: this is a
single local worker process talking to a local Ledger container over plain HTTP: a
blocking call here is a network round-trip on localhost, not a concern worth an
async rewrite of already-tested Phase 1 code. If a future caller needs this
off the event loop, wrap calls in asyncio.to_thread() at the call site.
"""
from __future__ import annotations

import httpx

from .store import SessionRecord

_SESSION_FIELDS = (
    "session_id", "conversation_id", "harness", "provider_profile", "model",
    "external_session_id", "repo_id", "workspace_path", "worktree_path",
    "branch", "base_branch", "permission_profile", "worker_id", "status",
    "created_at", "updated_at", "last_event_sequence", "cost_usd",
)


def _record_from_dict(data: dict) -> SessionRecord:
    return SessionRecord(**{k: data[k] for k in _SESSION_FIELDS})


class LedgerSessionStore:
    def __init__(self, client: httpx.Client) -> None:
        """`client` is an already-configured httpx.Client (base_url + any auth
        headers) — injected, not constructed here, so tests can pass one wired to
        an in-process TestClient's ASGI app instead of a real network base_url."""
        self._client = client

    def _raise_for_status(self, r: httpx.Response, *, not_found_msg: str) -> None:
        if r.status_code == 404:
            raise KeyError(not_found_msg)
        r.raise_for_status()

    def create_session(self, *, harness: str, conversation_id: str, repo_id: str,
                       provider_profile: str = "default", model: str | None = None,
                       permission_profile: str = "read_only") -> SessionRecord:
        r = self._client.post("/agent-session", json={
            "harness": harness, "conversation_id": conversation_id,
            "repo_id": repo_id, "provider_profile": provider_profile,
            "model": model, "permission_profile": permission_profile})
        r.raise_for_status()
        return _record_from_dict(r.json())

    def get(self, session_id: str) -> SessionRecord:
        r = self._client.get(f"/agent-session/{session_id}")
        self._raise_for_status(r, not_found_msg=f"no such agent session: {session_id!r}")
        return _record_from_dict(r.json())

    def append_event(self, session_id: str, event):
        r = self._client.post(f"/agent-session/{session_id}/event",
                              json={"type": event.type, "payload": event.payload})
        self._raise_for_status(r, not_found_msg=f"no such agent session: {session_id!r}")
        body = r.json()
        event.sequence = body["sequence"]
        event.ts = body["ts"]
        return event

    def events_since(self, session_id: str, after_sequence: int = 0):
        from .events import AgentEvent
        r = self._client.get(f"/agent-session/{session_id}/events",
                             params={"after_sequence": after_sequence})
        self._raise_for_status(r, not_found_msg=f"no such agent session: {session_id!r}")
        return [AgentEvent(type=row["type"], sequence=row["sequence"], ts=row["ts"],
                           payload=row["payload"]) for row in r.json()]

    def set_status(self, session_id: str, status: str) -> None:
        r = self._client.post(f"/agent-session/{session_id}/status",
                              json={"status": status})
        self._raise_for_status(r, not_found_msg=f"no such agent session: {session_id!r}")
