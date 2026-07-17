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
from .store import SessionStoreProtocol


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

    def descriptors(self) -> list[HarnessDescriptor]:
        """Static harness metadata (id/label/production/modes) — worker- and
        probe-independent, so a caller can list the harnesses (and later say WHY
        one is unavailable) without a live SDK. Availability comes from probes()."""
        return list(self._descriptors.values())

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
                # False for a harness whose SDK exposes no programmatic hook
                # to causally resolve a pending approval (e.g. codex_agent —
                # see adapters/codex_agent.py's resolve_approval docstring).
                # Defaults True: FakeHarness (and any future harness that
                # doesn't explicitly declare otherwise) genuinely does
                # resolve approvals interactively.
                "interactive_approvals": getattr(harness, "interactive_approvals", True),
                # True for a harness that sends repo contents to a PAID EXTERNAL
                # API (openrouter_agent). The UI must show an explicit "this
                # context will leave the machine" confirmation before the first
                # send. Defaults False: local subscription runtimes keep content
                # on-box (Claude/Codex).
                "external_egress": getattr(harness, "external_egress", False),
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


def default_registry(store: SessionStoreProtocol) -> HarnessRegistry:
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
            # analysis (read-only) only in this milestone — workspace/mission
            # modes are refused by CodexAgentHarness.start_session itself
            supported_modes=("analysis",),
            # Deferred import (see codex_agent.py's own _import_sdk): this
            # module is only imported when a Codex session is actually probed/
            # started, never just from importing registry.py or listing
            # harnesses in a deployment without the optional `agent-codex`
            # extra installed.
            factory=lambda: __import__(
                "command_center.agent_sessions.adapters.codex_agent",
                fromlist=["CodexAgentHarness"]).CodexAgentHarness(store)),
        # TWO Claude lanes behind the same contract (see WORKLOG.md): the DEFAULT
        # local lane drives the installed Claude Code CLI with the operator's
        # existing `claude auth login` subscription (NO API key); the optional
        # API lane uses the Agent SDK + ANTHROPIC_API_KEY (for hosted/shared
        # deployments). Both refuse anything but read-only analysis this milestone.
        HarnessDescriptor(
            harness_id="claude_code_local",
            label="Claude Agent (local subscription)", production=True,
            supported_modes=("analysis",),
            # Deferred import: constructing the harness must not import anything
            # heavy; it only shells out to the `claude` CLI at probe/send time.
            factory=lambda: __import__(
                "command_center.agent_sessions.adapters.claude_code_local",
                fromlist=["ClaudeCodeLocalHarness"]).ClaudeCodeLocalHarness(store)),
        HarnessDescriptor(
            harness_id="claude_agent", label="Claude Agent (API key)",
            production=True, supported_modes=("analysis",),
            # Deferred import (see claude_agent.py's own _import_sdk): only
            # imported when a Claude API session is probed/started, so a
            # deployment without the optional `agent-claude` extra can still
            # import registry.py and list harnesses. probe() reports the real
            # blocker (SDK missing / ANTHROPIC_API_KEY absent) honestly.
            factory=lambda: __import__(
                "command_center.agent_sessions.adapters.claude_agent",
                fromlist=["ClaudeAgentHarness"]).ClaudeAgentHarness(store)),
        # OpenRouter read-only EXECUTOR: the paid fallback for the Claude/Codex
        # ROLES when their subscription is exhausted. probe() is off unless the
        # frontier lane is explicitly enabled + a key is present (the same paid-
        # egress opt-in the frontier CHAT lane uses) — never available by import.
        HarnessDescriptor(
            harness_id="openrouter_agent",
            label="OpenRouter Agent (paid role fallback)", production=True,
            supported_modes=("analysis",),
            factory=lambda: __import__(
                "command_center.agent_sessions.adapters.openrouter_agent",
                fromlist=["OpenRouterAgentHarness"]).OpenRouterAgentHarness(
                    store)),
    ])
