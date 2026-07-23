"""AgentSessionService: the sole lifecycle owner. Parameterized across both store
backends (in-memory + real Ledger) — the service must behave identically either
way, same discipline as the registry/FakeHarness tests. Covers the required gates:
unknown harness/unsupported mode/unavailable harness all fail with a specific
reason, message events get gapless Ledger sequences, a restart-simulated fresh
service (new store instance pointed at the same db, new in-process harness cache)
still serves history correctly, and GatewayCore structurally cannot satisfy
AgentHarness.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from command_center.agent_sessions.protocol import ApprovalDecision, SessionStart
from command_center.agent_sessions.registry import default_registry
from command_center.agent_sessions.service import AgentSessionService
from command_center.agent_sessions.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


def _in_memory_service():
    store = SessionStore()
    return AgentSessionService(store=store, registry=default_registry(store))


def _ledger_service(tmp_path):
    import os
    from starlette.testclient import TestClient
    from command_center.agent_sessions.ledger_store import LedgerSessionStore

    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location("ledger_app_service_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    store = LedgerSessionStore(TestClient(mod.app))
    return AgentSessionService(store=store, registry=default_registry(store))


@pytest.fixture(params=["in_memory", "ledger"])
def service(request, tmp_path):
    if request.param == "in_memory":
        return _in_memory_service()
    return _ledger_service(tmp_path)


async def _drain(gen):
    return [e async for e in gen]


def test_start_session_with_unknown_harness_fails(service):
    with pytest.raises(KeyError):
        asyncio.run(service.start_session(SessionStart(
            conversation_id="c1", repo_id="r", mode="analysis",
            harness_id="does-not-exist")))


def test_start_session_with_unsupported_mode_fails(service):
    with pytest.raises(ValueError, match="does not support mode"):
        asyncio.run(service.start_session(SessionStart(
            conversation_id="c1", repo_id="r", mode="mission",
            harness_id="fake")))


def test_start_session_with_unavailable_harness_reports_exact_blocker(service):
    # Both real adapters (codex_agent, claude_agent) probe the real environment.
    # On a test host without the optional SDK/auth, starting claude_agent fails
    # with its CONCRETE blocker (missing claude-agent-sdk OR ANTHROPIC_API_KEY),
    # never a generic "unavailable" — the service surfaces that reason verbatim.
    with pytest.raises(RuntimeError,
                       match="claude-agent-sdk|ANTHROPIC_API_KEY"):
        asyncio.run(service.start_session(SessionStart(
            conversation_id="c1", repo_id="r", mode="analysis",
            harness_id="claude_agent")))


def test_full_lifecycle_through_the_service(service):
    record = asyncio.run(service.start_session(SessionStart(
        conversation_id="c1", repo_id="llm_station", mode="analysis",
        harness_id="fake")))
    assert record.status == "idle"

    events = asyncio.run(_drain(service.send_message(record.session_id, "hello")))
    assert [e.type for e in events] == [
        "user_message", "assistant_message", "session_idle"]

    all_events = service.get_events(record.session_id)
    sequences = [e.sequence for e in all_events]
    assert sequences == list(range(1, len(sequences) + 1))   # gapless

    asyncio.run(service.interrupt(record.session_id))
    assert service.get_session(record.session_id).status == "interrupted"
    asyncio.run(service.resume(record.session_id))
    assert service.get_session(record.session_id).status == "idle"

    asyncio.run(service.close(record.session_id))
    assert service.get_session(record.session_id).status == "closed"


def test_send_message_to_a_closed_session_is_rejected(service):
    record = asyncio.run(service.start_session(SessionStart(
        conversation_id="c1", repo_id="r", mode="analysis", harness_id="fake")))
    asyncio.run(service.close(record.session_id))
    with pytest.raises(ValueError, match="is closed"):
        asyncio.run(_drain(service.send_message(record.session_id, "still there?")))


def test_approval_lifecycle_through_the_service(service):
    record = asyncio.run(service.start_session(SessionStart(
        conversation_id="c1", repo_id="r", mode="workspace", harness_id="fake")))
    events = asyncio.run(_drain(service.send_message(record.session_id, "write x")))
    assert [e.type for e in events] == ["user_message", "approval_required"]
    approval_id = events[1].payload["approval_id"]

    asyncio.run(service.resolve_approval(
        record.session_id, ApprovalDecision(approval_id=approval_id, approved=True)))
    resolved = service.get_events(record.session_id)[-1]
    assert resolved.type == "approval_resolved" and resolved.payload["approved"] is True


def test_list_harnesses_reports_fake_and_real_adapters(service):
    # codex_agent and claude_agent are both real adapters now; availability
    # depends on the real environment (optional SDK/auth). On this host
    # claude_agent is unavailable but with a concrete reason (SDK/key), covered
    # in test_claude_agent_adapter.py / test_agent_session_registry.py.
    harnesses = {h["harness_id"]: h for h in asyncio.run(service.list_harnesses())}
    assert harnesses["fake"]["available"] is True
    assert harnesses["claude_agent"]["available"] is False


def test_service_survives_a_fresh_instance_pointed_at_the_same_ledger(tmp_path):
    """The actual restart-recovery proof at the SERVICE layer (not just the
    store): a brand new AgentSessionService — fresh in-process harness cache,
    fresh registry, fresh store client — opened against the same Ledger db must
    still serve the full session/event history."""
    service1 = _ledger_service(tmp_path)
    record = asyncio.run(service1.start_session(SessionStart(
        conversation_id="c1", repo_id="r", mode="analysis", harness_id="fake")))
    asyncio.run(_drain(service1.send_message(record.session_id, "hello")))

    # simulate a full process restart: a brand new service, no shared Python state
    import os
    from starlette.testclient import TestClient
    from command_center.agent_sessions.ledger_store import LedgerSessionStore

    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location(
        "ledger_app_service_restart_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    store2 = LedgerSessionStore(TestClient(mod.app))
    service2 = AgentSessionService(store=store2, registry=default_registry(store2))

    recovered = service2.get_session(record.session_id)
    assert recovered.conversation_id == "c1"
    events = service2.get_events(record.session_id)
    assert [e.type for e in events] == [
        "session_started", "user_message", "assistant_message", "session_idle"]

    # and it's still a live, usable session — not just readable history
    more = asyncio.run(_drain(service2.send_message(record.session_id, "again")))
    assert [e.type for e in more] == [
        "user_message", "assistant_message", "session_idle"]
    assert more[0].sequence == 5   # continues, does not reset


def test_gateway_core_cannot_satisfy_the_agent_harness_protocol():
    """Structural guardrail: GatewayCore's chat-turn loop must never accidentally
    become registrable as an agent-session harness — these are different
    execution systems by design (see WORKLOG.md "untrusted tool_calls
    dispatch")."""
    from command_center.agent_sessions.protocol import AgentHarness
    from command_center.channels.core import GatewayCore
    assert not issubclass(GatewayCore, AgentHarness)
