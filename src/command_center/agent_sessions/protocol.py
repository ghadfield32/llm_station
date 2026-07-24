"""AgentHarness — the one interface every agent-session backend implements (Claude
Agent SDK, Codex SDK, and FakeHarness the test double). FastAPI/UI code must depend
only on THIS interface, never on a vendor SDK's own types — see
WORKLOG.md "Agent-session chat integration" for why that boundary is load-bearing:
GatewayCore already leaked a vendor response's tool_calls straight into local
dispatch once (fixed 2026-07-11, see "untrusted tool_calls dispatch"); an
agent-session harness has a MUCH bigger tool surface (real filesystem/shell access),
so nothing here may assume a vendor event is trustworthy just because it arrived.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

from .events import AgentEvent


@dataclass
class HarnessProbe:
    """What probe() reports — mirrors cli/agent_preflight.py's Probe shape so the
    backend/API/CLI report availability the same way, with the same discipline: no
    generic "unavailable", a concrete reason either way."""
    available: bool
    detail: str


@dataclass
class SessionStart:
    conversation_id: str
    repo_id: str
    mode: str                          # "analysis" | "workspace" | "mission"
    # Which registered harness to start (registry.py key, e.g. "fake",
    # "codex_agent"). A specific AgentHarness instance's own start_session()
    # doesn't need to inspect this — it already knows who it is — but
    # AgentSessionService needs it to pick the right harness in the first place.
    harness_id: str = "fake"
    provider_profile: str = "default"
    model: str | None = None
    # reasoning effort for this session (low|medium|high|xhigh|max|ultracode);
    # None = the runtime's own default. Pinned for the session — see each
    # adapter's use (Claude CLI --effort, Codex model_reasoning_effort).
    effort: str | None = None
    context_mode: str | None = None    # e.g. "1m" for a long-context model
    permission_profile: str = "read_only"
    # Populated only by the defaults-off agent-session-spec consumer.
    instructions: str | None = None
    spec_name: str | None = None


def session_spec_metadata(request: SessionStart) -> dict[str, str]:
    """Durable event metadata present only for a spec-derived session."""
    return {"spec_name": request.spec_name} if request.spec_name is not None else {}


@dataclass
class ApprovalDecision:
    approval_id: str
    approved: bool
    reason: str = ""


@runtime_checkable
class AgentHarness(Protocol):
    """Every method is async except `send`, which is an async-generator-returning
    method (call it without `await`, iterate with `async for`). No method raises for
    an EXPECTED condition (SDK not installed, approval pending) — those surface as
    HarnessProbe fields or events. A genuinely unexpected failure (a crashed
    subprocess) still raises; callers must not swallow it into a fabricated event."""

    async def probe(self) -> HarnessProbe: ...

    async def start_session(self, request: SessionStart) -> str:
        """Returns the new session_id."""
        ...

    def send(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]: ...

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None: ...

    async def interrupt(self, session_id: str) -> None: ...

    async def resume(self, session_id: str) -> None: ...

    async def close(self, session_id: str) -> None: ...
