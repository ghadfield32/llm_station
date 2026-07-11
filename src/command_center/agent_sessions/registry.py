"""HarnessRegistry — the single place agent-session harnesses are registered and
probed. FastAPI/CLI/UI code asks the registry "what's available and why", and never
imports a vendor SDK directly (see cli/agent_preflight.py for the same discipline
applied to the raw environment probe this registry's placeholders point back to).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, NoReturn

from .fake_harness import FakeHarness
from .protocol import AgentHarness, ApprovalDecision, HarnessProbe, SessionStart
from .store import SessionStore


@dataclass(frozen=True)
class HarnessDescriptor:
    harness_id: str
    label: str
    production: bool          # False ONLY for FakeHarness — never presented as real
    supported_modes: tuple[str, ...]
    factory: Callable[[], AgentHarness]


class HarnessRegistry:
    def __init__(self, descriptors: list[HarnessDescriptor]) -> None:
        self._descriptors = {d.harness_id: d for d in descriptors}

    def get(self, harness_id: str) -> HarnessDescriptor:
        if harness_id not in self._descriptors:
            raise KeyError(f"unknown agent harness: {harness_id!r}")
        return self._descriptors[harness_id]

    def __contains__(self, harness_id: str) -> bool:
        return harness_id in self._descriptors

    async def probes(self) -> list[dict]:
        """Every registered harness's live availability. A fresh instance per
        probe call, never cached, so this always reflects current reality (an
        SDK installed/uninstalled since the last check) — same discipline as
        cli/agent_preflight.py: no generic "unavailable", a concrete reason."""
        results = []
        for descriptor in self._descriptors.values():
            harness = descriptor.factory()
            probe = await harness.probe()
            results.append({
                "harness_id": descriptor.harness_id,
                "label": descriptor.label,
                "production": descriptor.production,
                "available": probe.available,
                "detail": probe.detail,
                "supported_modes": list(descriptor.supported_modes),
            })
        return results


class NotBuiltHarness:
    """Placeholder for a harness_id whose real adapter doesn't exist yet (Codex
    Agent / Claude Agent — see WORKLOG.md "Agent-session chat integration", Phase
    2/3, not started as of this registry). probe() is the ONLY method that should
    ever legitimately be called on one — AgentSessionService checks probe().
    available before doing anything else, so every other method here exists only
    to fail loudly (never silently) if that gate is ever bypassed."""

    def __init__(self, *, harness_id: str, blocker: str) -> None:
        self.harness_id = harness_id
        self._blocker = blocker

    async def probe(self) -> HarnessProbe:
        return HarnessProbe(available=False, detail=self._blocker)

    def _refuse(self) -> NoReturn:
        raise RuntimeError(f"{self.harness_id} has no real adapter yet: {self._blocker}")

    async def start_session(self, request: SessionStart) -> str:
        self._refuse()

    def send(self, session_id: str, prompt: str):
        self._refuse()

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None:
        self._refuse()

    async def interrupt(self, session_id: str) -> None:
        self._refuse()

    async def resume(self, session_id: str) -> None:
        self._refuse()

    async def close(self, session_id: str) -> None:
        self._refuse()


def default_registry(store: SessionStore) -> HarnessRegistry:
    """The registry every current caller (tests, and later the host worker) should
    actually use: FakeHarness wired to the given durable store, plus honest
    not-built placeholders for the two real harnesses. Swapping in a real Codex/
    Claude adapter later means adding one HarnessDescriptor here — nothing that
    depends on HarnessRegistry needs to change."""
    return HarnessRegistry([
        HarnessDescriptor(
            harness_id="fake", label="Fake (dev/test only)", production=False,
            supported_modes=("analysis", "workspace"),
            factory=lambda: FakeHarness(store)),
        HarnessDescriptor(
            harness_id="codex_agent", label="Codex Agent", production=True,
            supported_modes=("analysis", "workspace"),
            factory=lambda: NotBuiltHarness(
                harness_id="codex_agent",
                blocker="no real adapter built yet (see WORKLOG.md 'Agent-session "
                        "chat integration', Phase 3) — run `cc agent-preflight "
                        "--harness codex` for current SDK/auth status")),
        HarnessDescriptor(
            harness_id="claude_agent", label="Claude Agent", production=True,
            supported_modes=("analysis", "workspace"),
            factory=lambda: NotBuiltHarness(
                harness_id="claude_agent",
                blocker="no real adapter built yet (see WORKLOG.md 'Agent-session "
                        "chat integration', Phase 2) — requires the "
                        "--allow-agent-session-egress policy decision plus "
                        "ANTHROPIC_API_KEY before it can even be attempted; run "
                        "`cc agent-preflight --harness claude` for current status")),
    ])
