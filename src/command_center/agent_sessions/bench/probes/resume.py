"""Resume probe: distinguish lifecycle recovery from conversation continuity."""
from __future__ import annotations

from uuid import uuid4

from ...protocol import AgentHarness
from ...store import SessionStoreProtocol
from ..models import Dimension, ProbeResult, Verdict
from .common import assistant_text, drain, start_analysis_session


async def probe_resume(
    harness: AgentHarness,
    store: SessionStoreProtocol,
    *,
    repo_id: str,
) -> ProbeResult:
    token = f"AGT15-{uuid4().hex}"
    session_id = await start_analysis_session(harness, repo_id=repo_id)
    await drain(harness.send(
        session_id,
        f"Remember this adapter-bench token for the next turn: {token}. Reply ACK.",
    ))
    checkpoint = store.get(session_id).last_event_sequence
    await harness.resume(session_id)
    await drain(harness.send(
        session_id,
        "Return the exact adapter-bench token from the previous turn.",
    ))
    events = store.events_since(session_id, after_sequence=checkpoint)
    resumed = any(
        event.type == "session_started" and event.payload.get("resumed") is True
        for event in events
    )
    has_output = any(
        event.type in ("assistant_delta", "assistant_message") for event in events)
    retained = token in assistant_text(events)
    if resumed and retained:
        verdict = Verdict.PASS
        detail = "observed resumed lifecycle event and retained cross-turn token"
    elif resumed and has_output:
        verdict = Verdict.PARTIAL
        detail = (
            "observed resumed lifecycle event and post-resume output, but not "
            "cross-turn token retention")
    else:
        verdict = Verdict.FAIL
        detail = (
            f"resume evidence incomplete: resumed_event={resumed}, "
            f"post_resume_output={has_output}")
    return ProbeResult(
        dimension=Dimension.RESUME,
        observed_verdict=verdict,
        detail=detail,
    )
