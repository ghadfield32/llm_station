"""Attachment probe."""
from __future__ import annotations

from ...protocol import AgentHarness
from ...store import SessionStoreProtocol
from ..models import Dimension, ProbeResult, Verdict


async def probe_attachments(
    harness: AgentHarness,
    store: SessionStoreProtocol,
    *,
    repo_id: str,
) -> ProbeResult:
    del harness, store, repo_id
    return ProbeResult(
        dimension=Dimension.ATTACHMENTS,
        observed_verdict=Verdict.SKIPPED,
        detail=(
            "AgentHarness.send accepts only (session_id, prompt); no attachment "
            "input or normalized attachment event exists to observe"
        ),
    )
