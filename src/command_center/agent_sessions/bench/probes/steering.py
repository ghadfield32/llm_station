"""Steering probe: skip honestly when no mid-turn input surface exists."""
from __future__ import annotations

from ...protocol import AgentHarness
from ...store import SessionStoreProtocol
from ..models import Dimension, ProbeResult, Verdict


async def probe_steering(
    harness: AgentHarness,
    store: SessionStoreProtocol,
    *,
    repo_id: str,
) -> ProbeResult:
    del store, repo_id
    name = getattr(harness, "name", "harness")
    if name == "fake":
        reason = "fake harness has no mid-turn steering surface"
    else:
        reason = f"{name} exposes no mid-turn steering surface"
    return ProbeResult(
        dimension=Dimension.STEERING,
        observed_verdict=Verdict.SKIPPED,
        detail=reason,
    )
