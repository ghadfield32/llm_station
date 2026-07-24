"""Streaming probe: score only normalized assistant events actually emitted."""
from __future__ import annotations

from ...protocol import AgentHarness
from ...store import SessionStoreProtocol
from ..models import Dimension, ProbeResult, Verdict
from .common import drain, start_analysis_session


async def probe_streaming(
    harness: AgentHarness,
    store: SessionStoreProtocol,
    *,
    repo_id: str,
) -> ProbeResult:
    session_id = await start_analysis_session(harness, repo_id=repo_id)
    checkpoint = store.get(session_id).last_event_sequence
    await drain(harness.send(session_id, "Adapter bench: reply with the word stream."))
    events = store.events_since(session_id, after_sequence=checkpoint)
    types = [event.type for event in events]
    if "assistant_delta" in types:
        verdict = Verdict.PASS
        detail = "observed assistant_delta in the normalized event stream"
    elif "assistant_message" in types:
        verdict = Verdict.PARTIAL
        detail = "observed complete assistant_message events but no assistant_delta"
    else:
        verdict = Verdict.FAIL
        detail = f"no assistant output event observed; event types={types}"
    return ProbeResult(
        dimension=Dimension.STREAMING,
        observed_verdict=verdict,
        detail=detail,
    )
