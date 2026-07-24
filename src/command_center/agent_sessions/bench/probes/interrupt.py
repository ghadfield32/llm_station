"""Interrupt probe: score the normalized lifecycle evidence it produces."""
from __future__ import annotations

from ...protocol import AgentHarness
from ...store import SessionStoreProtocol
from ..models import Dimension, ProbeResult, Verdict
from .common import start_analysis_session


async def probe_interrupt(
    harness: AgentHarness,
    store: SessionStoreProtocol,
    *,
    repo_id: str,
) -> ProbeResult:
    session_id = await start_analysis_session(harness, repo_id=repo_id)
    checkpoint = store.get(session_id).last_event_sequence
    await harness.interrupt(session_id)

    events = store.events_since(session_id, after_sequence=checkpoint)
    failed = any(event.type == "session_failed" for event in events)
    interrupted = store.get(session_id).status == "interrupted"
    if failed and interrupted:
        verdict = Verdict.PASS
        detail = "observed session_failed event and interrupted session status"
    elif failed or interrupted:
        verdict = Verdict.PARTIAL
        detail = (
            "observed incomplete interrupt lifecycle evidence: "
            f"session_failed={failed}, interrupted_status={interrupted}"
        )
    else:
        verdict = Verdict.FAIL
        detail = (
            "interrupt produced no session_failed event or interrupted "
            "session status"
        )
    return ProbeResult(
        dimension=Dimension.INTERRUPT,
        observed_verdict=verdict,
        detail=detail,
    )
