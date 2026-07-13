"""HarnessRegistry: unknown harnesses fail loudly, FakeHarness is clearly marked
non-production, unbuilt harnesses report their exact blocker (never a generic
"unavailable"), and listing harnesses never imports a vendor SDK — the whole point
of the registry existing is that FastAPI/CLI/UI can ask "what's available and why"
without ever risking an import-time side effect from an SDK that may not even be
installed.
"""
from __future__ import annotations

import asyncio
import sys

import pytest

from command_center.agent_sessions.registry import default_registry
from command_center.agent_sessions.store import SessionStore


@pytest.fixture
def registry():
    return default_registry(SessionStore())


def test_unknown_harness_id_raises_key_error(registry):
    with pytest.raises(KeyError):
        registry.get("does-not-exist")


def test_contains_reflects_registered_harnesses(registry):
    assert "fake" in registry
    assert "codex_agent" in registry
    assert "claude_agent" in registry
    assert "does-not-exist" not in registry


def test_fake_harness_is_marked_non_production(registry):
    descriptor = registry.get("fake")
    assert descriptor.production is False


def test_codex_and_claude_are_marked_production(registry):
    assert registry.get("codex_agent").production is True
    assert registry.get("claude_agent").production is True


def test_probes_report_fake_as_available(registry):
    probes = {p["harness_id"]: p for p in asyncio.run(registry.probes())}
    assert probes["fake"]["available"] is True
    assert probes["fake"]["production"] is False


def test_probes_report_real_harness_blocker_concretely_not_generic(registry):
    # BOTH real adapters (codex_agent, claude_agent) now give an honest,
    # environment-dependent probe. On a test host without the optional SDK/auth
    # they are unavailable, but with a CONCRETE reason (missing SDK or missing
    # key), never a generic "unavailable" — the load-bearing discipline. claude
    # is asserted here because its blocker is deterministic (SDK not installed
    # OR ANTHROPIC_API_KEY absent), unlike codex's live-account probe.
    probes = {p["harness_id"]: p for p in asyncio.run(registry.probes())}
    p = probes["claude_agent"]
    assert p["available"] is False
    assert p["detail"] != "unavailable"
    assert len(p["detail"]) > 20   # a real, specific reason, not a stub string
    assert ("claude-agent-sdk" in p["detail"]) or ("ANTHROPIC_API_KEY" in p["detail"])


def test_constructing_claude_harness_never_imports_its_sdk(registry):
    # The deferred-import guarantee: building the harness instance (factory())
    # must NOT import claude_agent_sdk — only probe()/start_session do (see
    # claude_agent.py's _import_sdk), so a deployment without the agent-claude
    # extra can still construct/list harnesses without an import-time failure.
    sys.modules.pop("claude_agent_sdk", None)
    registry.get("claude_agent").factory()
    assert "claude_agent_sdk" not in sys.modules


def test_not_built_harness_refuses_every_lifecycle_method_not_just_probe():
    # NotBuiltHarness is no longer wired for codex/claude (both are real now),
    # but the CLASS is still the contract for any future harness_id — test it
    # directly so the "probe() answers, everything else fails loud" guarantee
    # stays covered.
    from command_center.agent_sessions.protocol import ApprovalDecision, SessionStart
    from command_center.agent_sessions.registry import NotBuiltHarness

    harness = NotBuiltHarness(harness_id="future_agent", blocker="not built yet")
    assert asyncio.run(harness.probe()).available is False
    with pytest.raises(RuntimeError):
        asyncio.run(harness.start_session(
            SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    with pytest.raises(RuntimeError):
        harness.send("s1", "hello")
    with pytest.raises(RuntimeError):
        asyncio.run(harness.resolve_approval(
            "s1", ApprovalDecision(approval_id="a1", approved=True)))
    with pytest.raises(RuntimeError):
        asyncio.run(harness.interrupt("s1"))
    with pytest.raises(RuntimeError):
        asyncio.run(harness.resume("s1"))
    with pytest.raises(RuntimeError):
        asyncio.run(harness.close("s1"))
