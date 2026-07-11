"""In-memory agent-session store: session records + a per-session, monotonically
sequenced event log. Phase 1 scope only — no persistence, no cross-process sharing.
A real deployment needs something durable before Phase 4 (cockpit integration) if
sessions must survive a service restart; this module's INTERFACE (not its backing
dict) is what later phases depend on, so swapping the storage later should not
require touching callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .events import AgentEvent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionRecord:
    session_id: str
    conversation_id: str
    harness: str
    provider_profile: str
    model: str | None
    external_session_id: str | None
    repo_id: str
    workspace_path: str | None
    worktree_path: str | None
    branch: str | None
    base_branch: str | None
    permission_profile: str
    worker_id: str | None
    status: str                     # starting | active | idle | interrupted | failed | closed
    created_at: str
    updated_at: str
    last_event_sequence: int = 0
    cost_usd: float = 0.0


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._events: dict[str, list[AgentEvent]] = {}
        self._next_id = 0

    def create_session(self, *, harness: str, conversation_id: str, repo_id: str,
                       provider_profile: str = "default", model: str | None = None,
                       permission_profile: str = "read_only") -> SessionRecord:
        self._next_id += 1
        session_id = f"agent-session-{self._next_id}"
        now = _now_iso()
        record = SessionRecord(
            session_id=session_id, conversation_id=conversation_id, harness=harness,
            provider_profile=provider_profile, model=model, external_session_id=None,
            repo_id=repo_id, workspace_path=None, worktree_path=None, branch=None,
            base_branch=None, permission_profile=permission_profile, worker_id=None,
            status="starting", created_at=now, updated_at=now)
        self._sessions[session_id] = record
        self._events[session_id] = []
        return record

    def get(self, session_id: str) -> SessionRecord:
        if session_id not in self._sessions:
            raise KeyError(f"no such agent session: {session_id!r}")
        return self._sessions[session_id]

    def append_event(self, session_id: str, event: AgentEvent) -> AgentEvent:
        """Assigns sequence/ts here (never trust a harness-supplied sequence — the
        store is the single serialization point per session)."""
        record = self.get(session_id)
        log = self._events[session_id]
        event.sequence = len(log) + 1
        event.ts = _now_iso()
        log.append(event)
        record.last_event_sequence = event.sequence
        record.updated_at = event.ts
        return event

    def events_since(self, session_id: str, after_sequence: int = 0) -> list[AgentEvent]:
        """The reconnect primitive: a client that last saw sequence N asks for
        events_since(id, N) and gets exactly the gap. Raises on an unknown session
        id rather than silently returning an empty list, so a typo'd/expired id
        fails loud instead of looking like "no new events"."""
        self.get(session_id)
        return [e for e in self._events[session_id] if (e.sequence or 0) > after_sequence]

    def set_status(self, session_id: str, status: str) -> None:
        record = self.get(session_id)
        record.status = status
        record.updated_at = _now_iso()
