"""FakeHarness — a deterministic AgentHarness implementation with NO real SDK, NO
subprocess, NO network. It exists to prove the protocol/store/event-sequencing/
interrupt/approval lifecycle works BEFORE any real Claude/Codex SDK is wired in (see
WORKLOG.md "Agent-session chat integration", Phase 1 gate: "all lifecycle and
reconnect tests pass against the fake harness"). Its probe() reports itself honestly
as a test double — nothing should ever present its output to an operator as if a
real agent produced it.
"""
from __future__ import annotations

from typing import AsyncIterator

from .events import AgentEvent
from .protocol import ApprovalDecision, HarnessProbe, SessionStart
from .store import SessionStore


class FakeHarness:
    name = "fake"

    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self._interrupted: set[str] = set()
        self._pending_approvals: dict[str, str] = {}   # approval_id -> session_id

    async def probe(self) -> HarnessProbe:
        return HarnessProbe(
            available=True,
            detail="deterministic test double — never a real agent, for "
                   "protocol/store lifecycle testing only")

    async def start_session(self, request: SessionStart) -> str:
        record = self.store.create_session(
            harness=self.name, conversation_id=request.conversation_id,
            repo_id=request.repo_id, provider_profile=request.provider_profile,
            model=request.model, permission_profile=request.permission_profile)
        self.store.append_event(
            record.session_id, AgentEvent("session_started", {"mode": request.mode}))
        self.store.set_status(record.session_id, "active")
        return record.session_id

    async def send(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        if session_id in self._interrupted:
            yield self.store.append_event(
                session_id,
                AgentEvent("session_failed", {"reason": "session was interrupted"}))
            return
        if prompt.strip().lower().startswith("write "):
            # deterministically exercises the approval path without any real tool
            approval_id = f"{session_id}-approval-{len(self._pending_approvals) + 1}"
            self._pending_approvals[approval_id] = session_id
            yield self.store.append_event(
                session_id,
                AgentEvent("approval_required",
                          {"approval_id": approval_id, "action": prompt}))
            return
        yield self.store.append_event(
            session_id, AgentEvent("assistant_message",
                                   {"text": f"fake harness echo: {prompt}"}))
        yield self.store.append_event(session_id, AgentEvent("session_idle", {}))

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None:
        owner = self._pending_approvals.get(decision.approval_id)
        if owner != session_id:
            raise ValueError(
                f"approval {decision.approval_id!r} does not belong to session "
                f"{session_id!r} (owner: {owner!r})")
        del self._pending_approvals[decision.approval_id]
        self.store.append_event(
            session_id,
            AgentEvent("approval_resolved",
                      {"approval_id": decision.approval_id,
                       "approved": decision.approved, "reason": decision.reason}))

    async def interrupt(self, session_id: str) -> None:
        self._interrupted.add(session_id)
        self.store.append_event(session_id,
                                AgentEvent("session_failed", {"reason": "interrupted"}))
        self.store.set_status(session_id, "interrupted")

    async def resume(self, session_id: str) -> None:
        self._interrupted.discard(session_id)
        self.store.set_status(session_id, "active")
        self.store.append_event(session_id,
                                AgentEvent("session_started", {"resumed": True}))

    async def close(self, session_id: str) -> None:
        self.store.append_event(session_id, AgentEvent("session_closed", {}))
        self.store.set_status(session_id, "closed")
