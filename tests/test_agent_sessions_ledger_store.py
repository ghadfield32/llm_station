"""LedgerSessionStore must be interchangeable with the in-memory store.SessionStore
— same FakeHarness, same lifecycle, backed by a real (test) Ledger instance instead
of a dict. This is the actual proof for "the public SessionStore interface stays
stable so adapters and UI code do not care which backend is used" (see
ledger_store.py's docstring) — not just an assertion, a real cross-backend run of
the exact same assertions as test_agent_sessions.py.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from command_center.agent_sessions.fake_harness import FakeHarness
from command_center.agent_sessions.ledger_store import LedgerSessionStore
from command_center.agent_sessions.protocol import ApprovalDecision, SessionStart

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


@pytest.fixture
def ledger_backed_harness(tmp_path):
    import os
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location(
        "ledger_app_under_store_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    client = TestClient(mod.app)
    store = LedgerSessionStore(client)
    return store, FakeHarness(store)


async def _drain(gen):
    return [e async for e in gen]


def test_full_lifecycle_against_the_real_ledger_backend(ledger_backed_harness):
    store, fh = ledger_backed_harness
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="llm_station", mode="analysis")))
    assert session_id.startswith("AS-")   # Ledger-assigned id, not agent-session-N

    record = store.get(session_id)
    assert record.status == "idle"
    assert record.conversation_id == "c1"

    events = asyncio.run(_drain(fh.send(session_id, "explain this repo")))
    assert [e.type for e in events] == ["assistant_message", "session_idle"]
    assert events[0].sequence == 2   # 1 was session_started from start_session


def test_events_since_reconnect_against_ledger(ledger_backed_harness):
    store, fh = ledger_backed_harness
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    checkpoint = store.events_since(session_id)[-1].sequence

    asyncio.run(_drain(fh.send(session_id, "more")))
    new_events = store.events_since(session_id, after_sequence=checkpoint)
    assert [e.type for e in new_events] == ["assistant_message", "session_idle"]


def test_approval_lifecycle_against_ledger(ledger_backed_harness):
    store, fh = ledger_backed_harness
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="workspace")))
    events = asyncio.run(_drain(fh.send(session_id, "write a new file")))
    approval_id = events[0].payload["approval_id"]

    asyncio.run(fh.resolve_approval(
        session_id, ApprovalDecision(approval_id=approval_id, approved=True)))
    resolved = store.events_since(session_id)[-1]
    assert resolved.type == "approval_resolved"
    assert resolved.payload["approved"] is True


def test_interrupt_and_resume_against_ledger(ledger_backed_harness):
    store, fh = ledger_backed_harness
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    asyncio.run(fh.interrupt(session_id))
    assert store.get(session_id).status == "interrupted"

    asyncio.run(fh.resume(session_id))
    assert store.get(session_id).status == "idle"
    events = asyncio.run(_drain(fh.send(session_id, "back")))
    assert events[0].type == "assistant_message"


def test_unknown_session_raises_key_error_same_as_in_memory_store(
        ledger_backed_harness):
    store, _ = ledger_backed_harness
    with pytest.raises(KeyError):
        store.get("AS-does-not-exist")
    with pytest.raises(KeyError):
        store.events_since("AS-does-not-exist")


def test_update_session_against_ledger(ledger_backed_harness):
    """Written by a real harness adapter once it has real vendor identity
    (external_session_id/worker_id/model/provider_profile/cost_usd) — see
    adapters/codex_agent.py. Proves the durable round-trip against the real
    Ledger backend, mirroring test_agent_sessions.py's in-memory version."""
    store, fh = ledger_backed_harness
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="llm_station", mode="analysis")))

    updated = store.update_session(
        session_id, external_session_id="thread-xyz", model="gpt-5.5")
    assert updated.external_session_id == "thread-xyz"
    assert updated.model == "gpt-5.5"

    # a fresh read (not the return value) proves it was actually persisted
    assert store.get(session_id).external_session_id == "thread-xyz"

    # a second, partial update leaves previously-set fields alone
    store.update_session(session_id, cost_usd=0.0042)
    record = store.get(session_id)
    assert record.cost_usd == 0.0042
    assert record.external_session_id == "thread-xyz"   # still there


def test_list_sessions_filters_against_ledger(ledger_backed_harness):
    store, fh = ledger_backed_harness
    s1 = asyncio.run(fh.start_session(
        SessionStart(conversation_id="conv-a", repo_id="llm_station", mode="analysis")))
    s2 = asyncio.run(fh.start_session(
        SessionStart(conversation_id="conv-b", repo_id="betts_basketball", mode="analysis")))

    assert [r.session_id for r in store.list_sessions(conversation_id="conv-a")] == [s1]
    assert [r.session_id for r in store.list_sessions(repo_id="betts_basketball")] == [s2]
