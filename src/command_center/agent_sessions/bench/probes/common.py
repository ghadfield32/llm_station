"""Shared mechanics for event-stream capability probes."""
from __future__ import annotations

from typing import AsyncIterator

from ...events import AgentEvent
from ...protocol import AgentHarness, SessionStart


async def drain(events: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    return [event async for event in events]


async def start_analysis_session(
    harness: AgentHarness,
    *,
    repo_id: str,
    model: str | None = None,
) -> str:
    return await harness.start_session(SessionStart(
        conversation_id="adapter-bench",
        repo_id=repo_id,
        mode="analysis",
        harness_id=getattr(harness, "name", "unknown"),
        model=model,
        permission_profile="read_only",
    ))


def assistant_text(events: list[AgentEvent]) -> str:
    return "".join(
        str(event.payload.get("text", ""))
        for event in events
        if event.type in ("assistant_delta", "assistant_message")
    )
