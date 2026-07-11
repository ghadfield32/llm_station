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
from typing import Protocol, runtime_checkable

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


@dataclass
class ApprovalRecord:
    """A durable approval request. The store — not the harness — generates
    approval_id and owns resolution state, so a resumed/restarted harness never
    loses track of a pending approval (see fake_harness.py, which used to keep
    this in a local dict that a restart would silently drop)."""
    approval_id: str
    session_id: str
    action: str
    status: str                     # pending | resolved
    requested_at: str
    resolved_at: str | None = None
    approved: bool | None = None
    reason: str = ""


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._events: dict[str, list[AgentEvent]] = {}
        self._approvals: dict[str, ApprovalRecord] = {}
        self._next_id = 0
        self._next_approval_id = 0

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

    def create_approval(self, session_id: str, action: str) -> ApprovalRecord:
        self.get(session_id)   # raises loud on an unknown session
        self._next_approval_id += 1
        approval_id = f"approval-{self._next_approval_id}"
        record = ApprovalRecord(approval_id=approval_id, session_id=session_id,
                                action=action, status="pending",
                                requested_at=_now_iso())
        self._approvals[approval_id] = record
        return record

    def get_approval(self, approval_id: str) -> ApprovalRecord:
        if approval_id not in self._approvals:
            raise KeyError(f"no such approval: {approval_id!r}")
        return self._approvals[approval_id]

    def resolve_approval(self, session_id: str, approval_id: str, *,
                         approved: bool, reason: str = "") -> ApprovalRecord:
        """One-use: raises on replay (already resolved) and on a session that
        doesn't own this approval — an approval from one session can never be
        resolved by another."""
        record = self.get_approval(approval_id)
        if record.session_id != session_id:
            raise ValueError(
                f"approval {approval_id!r} does not belong to session "
                f"{session_id!r} (owner: {record.session_id!r})")
        if record.status == "resolved":
            raise ValueError(
                f"approval {approval_id!r} was already resolved — replay rejected")
        record.status = "resolved"
        record.resolved_at = _now_iso()
        record.approved = approved
        record.reason = reason
        return record


@runtime_checkable
class SessionStoreProtocol(Protocol):
    """What AgentSessionService and the harnesses actually depend on — satisfied
    structurally by both this in-memory SessionStore and the real
    ledger_store.LedgerSessionStore, so callers never care which backend they
    were handed."""

    def create_session(self, *, harness: str, conversation_id: str, repo_id: str,
                       provider_profile: str = "default", model: str | None = None,
                       permission_profile: str = "read_only") -> SessionRecord: ...

    def get(self, session_id: str) -> SessionRecord: ...

    def append_event(self, session_id: str, event: AgentEvent) -> AgentEvent: ...

    def events_since(self, session_id: str, after_sequence: int = 0) -> list[AgentEvent]: ...

    def set_status(self, session_id: str, status: str) -> None: ...

    def create_approval(self, session_id: str, action: str) -> ApprovalRecord: ...

    def get_approval(self, approval_id: str) -> ApprovalRecord: ...

    def resolve_approval(self, session_id: str, approval_id: str, *,
                         approved: bool, reason: str = "") -> ApprovalRecord: ...
