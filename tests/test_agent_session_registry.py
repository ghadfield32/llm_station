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


def test_probes_report_unbuilt_harness_with_exact_blocker_not_generic(registry):
    # codex_agent is a REAL adapter now (see adapters/codex_agent.py) — its
    # probe() result depends on the real environment (SDK installed? real
    # account authenticated?), which test_codex_agent_adapter.py covers
    # deterministically via a fake SDK. claude_agent remains a genuine
    # NotBuiltHarness placeholder, so it's the one this test can assert on
    # unconditionally.
    probes = {p["harness_id"]: p for p in asyncio.run(registry.probes())}
    p = probes["claude_agent"]
    assert p["available"] is False
    assert p["detail"] != "unavailable"
    assert len(p["detail"]) > 20   # a real, specific reason, not a stub string
    assert "no real adapter built yet" in p["detail"]


def test_probing_unbuilt_claude_harness_never_imports_its_sdk(registry):
    # codex_agent's probe() now legitimately imports openai_codex to give an
    # honest availability answer (see codex_agent.py's _import_sdk) — that's
    # expected, not a regression. claude_agent is still NotBuiltHarness, so
    # it alone keeps the "never imports just from listing" guarantee.
    sys.modules.pop("claude_agent_sdk", None)
    asyncio.run(registry.probes())
    assert "claude_agent_sdk" not in sys.modules


def test_unbuilt_harness_refuses_every_lifecycle_method_not_just_probe(registry):
    harness = registry.get("claude_agent").factory()
    from command_center.agent_sessions.protocol import ApprovalDecision, SessionStart

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
