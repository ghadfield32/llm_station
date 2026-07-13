"""AgentSessionService — the sole lifecycle owner for agent sessions. FastAPI (and
later the host worker) call ONLY this, never a harness or the store directly, so
there is exactly one place that decides what's allowed and one place that keeps
the durable Ledger state and in-process harness objects consistent after a
restart.
"""
from __future__ import annotations

from typing import AsyncIterator

from .events import AgentEvent
from .protocol import AgentHarness, ApprovalDecision, SessionStart
from .registry import HarnessRegistry
from .store import SessionRecord, SessionStoreProtocol


class AgentSessionService:
    def __init__(self, *, store: SessionStoreProtocol, registry: HarnessRegistry) -> None:
        self.store = store
        self.registry = registry
        # PROCESS-LOCAL cache only — never the source of truth. A restart empties
        # this; every method below reconstructs a fresh harness instance for an
        # existing durable session rather than assuming this cache still holds
        # one, so a FakeHarness session (which keeps no state of its own — see
        # fake_harness.py) behaves identically before and after a restart. A
        # real SDK-backed harness with a genuinely dead subprocess is expected to
        # surface that itself (via probe()/its own methods raising), not have
        # this service fabricate a resumed connection.
        self._active_harnesses: dict[str, AgentHarness] = {}

    def _harness_for(self, record: SessionRecord) -> AgentHarness:
        cached = self._active_harnesses.get(record.session_id)
        if cached is not None:
            return cached
        harness = self.registry.get(record.harness).factory()
        self._active_harnesses[record.session_id] = harness
        return harness

    async def list_harnesses(self) -> list[dict]:
        return await self.registry.probes()

    async def start_session(self, request: SessionStart) -> SessionRecord:
        descriptor = self.registry.get(request.harness_id)
        if request.mode not in descriptor.supported_modes:
            raise ValueError(
                f"harness {request.harness_id!r} does not support mode "
                f"{request.mode!r} (supports: {list(descriptor.supported_modes)})")
        harness = descriptor.factory()
        probe = await harness.probe()
        if not probe.available:
            raise RuntimeError(
                f"harness {request.harness_id!r} is unavailable: {probe.detail}")
        session_id = await harness.start_session(request)
        self._active_harnesses[session_id] = harness
        return self.store.get(session_id)

    def get_session(self, session_id: str) -> SessionRecord:
        return self.store.get(session_id)

    async def send_message(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        record = self.store.get(session_id)
        if record.status == "closed":
            raise ValueError(f"session {session_id!r} is closed")
        harness = self._harness_for(record)
        async for event in harness.send(session_id, prompt):
            yield event

    def get_events(self, session_id: str, after_sequence: int = 0) -> list[AgentEvent]:
        return self.store.events_since(session_id, after_sequence)

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None:
        record = self.store.get(session_id)
        await self._harness_for(record).resolve_approval(session_id, decision)

    async def interrupt(self, session_id: str) -> None:
        record = self.store.get(session_id)
        await self._harness_for(record).interrupt(session_id)

    async def resume(self, session_id: str) -> None:
        record = self.store.get(session_id)
        await self._harness_for(record).resume(session_id)

    async def close(self, session_id: str) -> None:
        record = self.store.get(session_id)
        await self._harness_for(record).close(session_id)
        self._active_harnesses.pop(session_id, None)
