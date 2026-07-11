"""Phase 1 of the agent-session plan (WORKLOG.md "Agent-session chat integration"):
protocol + event schema + store + FakeHarness. Gate: the full lifecycle (start ->
send -> approval -> interrupt -> resume -> close) and reconnect (events_since) work
against the fake harness, with no real SDK/subprocess/network anywhere in this file.
"""
from __future__ import annotations

import asyncio

import pytest

from command_center.agent_sessions.events import AgentEvent
from command_center.agent_sessions.fake_harness import FakeHarness
from command_center.agent_sessions.protocol import (
    AgentHarness,
    ApprovalDecision,
    SessionStart,
)
from command_center.agent_sessions.store import SessionStore


def _harness() -> tuple[SessionStore, FakeHarness]:
    store = SessionStore()
    return store, FakeHarness(store)


async def _drain(gen):
    return [e async for e in gen]


def test_fake_harness_satisfies_the_agent_harness_protocol():
    store, fh = _harness()
    assert isinstance(fh, AgentHarness)


def test_probe_reports_itself_honestly_as_a_fake():
    _, fh = _harness()
    probe = asyncio.run(fh.probe())
    assert probe.available is True
    assert "fake" in probe.detail or "test double" in probe.detail


def test_start_session_creates_record_and_session_started_event():
    store, fh = _harness()
    request = SessionStart(conversation_id="c1", repo_id="llm_station", mode="analysis")
    session_id = asyncio.run(fh.start_session(request))

    record = store.get(session_id)
    assert record.status == "idle"   # ready, not "a task is running" — see fake_harness.py
    assert record.conversation_id == "c1"
    assert record.repo_id == "llm_station"
    assert record.harness == "fake"

    events = store.events_since(session_id)
    assert len(events) == 1
    assert events[0].type == "session_started"
    assert events[0].sequence == 1


def test_send_emits_assistant_message_then_idle():
    store, fh = _harness()
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    events = asyncio.run(_drain(fh.send(session_id, "explain this repo")))
    assert [e.type for e in events] == ["assistant_message", "session_idle"]
    assert "explain this repo" in events[0].payload["text"]


def test_sequence_numbers_are_monotonic_and_gapless():
    store, fh = _harness()
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    asyncio.run(_drain(fh.send(session_id, "hello")))
    asyncio.run(_drain(fh.send(session_id, "again")))

    sequences = [e.sequence for e in store.events_since(session_id)]
    assert sequences == list(range(1, len(sequences) + 1))


def test_events_since_reconnect_returns_only_new_events():
    """The SSE-reconnect primitive: a client that already saw sequence N asks for
    events_since(id, N) and must get exactly the gap — no duplicates, no misses."""
    store, fh = _harness()
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    first_batch = store.events_since(session_id)
    last_seen = first_batch[-1].sequence

    asyncio.run(_drain(fh.send(session_id, "more")))
    new_events = store.events_since(session_id, after_sequence=last_seen)

    assert all(e.sequence > last_seen for e in new_events)
    assert [e.type for e in new_events] == ["assistant_message", "session_idle"]
    # nothing from before the checkpoint leaked back in
    assert not (set(e.sequence for e in new_events) & set(e.sequence for e in first_batch))


def test_events_since_unknown_session_raises():
    store, _ = _harness()
    with pytest.raises(KeyError):
        store.events_since("no-such-session")


def test_approval_lifecycle_required_then_resolved():
    store, fh = _harness()
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="workspace")))
    events = asyncio.run(_drain(fh.send(session_id, "write a new file")))
    assert events[0].type == "approval_required"
    approval_id = events[0].payload["approval_id"]

    asyncio.run(fh.resolve_approval(
        session_id, ApprovalDecision(approval_id=approval_id, approved=True)))

    types = [e.type for e in store.events_since(session_id)]
    assert types[-1] == "approval_resolved"
    resolved = store.events_since(session_id)[-1]
    assert resolved.payload["approved"] is True


def test_resolve_approval_rejects_mismatched_session():
    store, fh = _harness()
    s1 = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="workspace")))
    s2 = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c2", repo_id="r", mode="workspace")))
    events = asyncio.run(_drain(fh.send(s1, "write something")))
    approval_id = events[0].payload["approval_id"]

    with pytest.raises(ValueError):
        asyncio.run(fh.resolve_approval(
            s2, ApprovalDecision(approval_id=approval_id, approved=True)))


def test_interrupt_stops_further_sends():
    store, fh = _harness()
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    asyncio.run(fh.interrupt(session_id))

    assert store.get(session_id).status == "interrupted"
    events = asyncio.run(_drain(fh.send(session_id, "keep going")))
    assert [e.type for e in events] == ["session_failed"]


def test_resume_after_interrupt_reactivates_session():
    store, fh = _harness()
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    asyncio.run(fh.interrupt(session_id))
    asyncio.run(fh.resume(session_id))

    assert store.get(session_id).status == "idle"
    events = asyncio.run(_drain(fh.send(session_id, "back online")))
    assert events[0].type == "assistant_message"


def test_close_marks_session_closed():
    store, fh = _harness()
    session_id = asyncio.run(fh.start_session(
        SessionStart(conversation_id="c1", repo_id="r", mode="analysis")))
    asyncio.run(fh.close(session_id))
    assert store.get(session_id).status == "closed"
    assert store.events_since(session_id)[-1].type == "session_closed"


def test_agent_event_to_dict_round_trips_fields():
    ev = AgentEvent(type="usage", payload={"tokens": 10}, sequence=3, ts="2026-01-01T00:00:00Z")
    d = ev.to_dict()
    assert d == {"type": "usage", "sequence": 3, "ts": "2026-01-01T00:00:00Z",
                 "payload": {"tokens": 10}}
