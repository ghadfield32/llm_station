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
from .protocol import ApprovalDecision, HarnessProbe, SessionStart, session_spec_metadata
from .store import SessionStoreProtocol


class FakeHarness:
    """Holds NO session-scoped state of its own — interrupted/active status and
    pending approvals both live in the store, so a FakeHarness instance recreated
    after a restart (or a fresh one pointed at the same durable store) behaves
    identically to the original. This is deliberate: it's the same recovery
    contract a real Claude/Codex adapter must satisfy."""

    name = "fake"

    def __init__(self, store: SessionStoreProtocol) -> None:
        self.store = store

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
            record.session_id, AgentEvent(
                "session_started", {"mode": request.mode, **session_spec_metadata(request)}))
        # "idle" = ready, no turn in progress. "active" is reserved EXCLUSIVELY
        # for "a background task is genuinely running this session right now"
        # (set only by the worker's task wrapper — see worker_app.py). Keeping
        # these distinct is what makes restart reconciliation unambiguous: any
        # session found "active" at worker startup is, by definition, orphaned
        # (a fresh process's task registry is always empty), never a session
        # that's merely ready and waiting.
        self.store.set_status(record.session_id, "idle")
        return record.session_id

    async def send(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        if self.store.get(session_id).status == "interrupted":
            yield self.store.append_event(
                session_id,
                AgentEvent("session_failed", {"reason": "session was interrupted"}))
            return
        if prompt.strip().lower().startswith("write "):
            # deterministically exercises the approval path without any real tool
            approval = self.store.create_approval(session_id, action=prompt)
            yield self.store.append_event(
                session_id,
                AgentEvent("approval_required",
                          {"approval_id": approval.approval_id, "action": prompt}))
            return
        yield self.store.append_event(
            session_id, AgentEvent("assistant_message",
                                   {"text": f"fake harness echo: {prompt}"}))
        yield self.store.append_event(session_id, AgentEvent("session_idle", {}))

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None:
        approval = self.store.resolve_approval(
            session_id, decision.approval_id,
            approved=decision.approved, reason=decision.reason)
        self.store.append_event(
            session_id,
            AgentEvent("approval_resolved",
                      {"approval_id": approval.approval_id,
                       "approved": approval.approved, "reason": approval.reason}))

    async def interrupt(self, session_id: str) -> None:
        self.store.append_event(session_id,
                                AgentEvent("session_failed", {"reason": "interrupted"}))
        self.store.set_status(session_id, "interrupted")

    async def resume(self, session_id: str) -> None:
        self.store.set_status(session_id, "idle")   # ready, not "a task is running"
        self.store.append_event(session_id,
                                AgentEvent("session_started", {"resumed": True}))

    async def close(self, session_id: str) -> None:
        self.store.append_event(session_id, AgentEvent("session_closed", {}))
        self.store.set_status(session_id, "closed")
