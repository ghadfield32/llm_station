"""Normalized agent-session event vocabulary — the SAME shape regardless of which
harness (Claude Agent SDK, Codex SDK, or FakeHarness) produced it. A harness adapter's
job is translating its own native message/event shape into these; nothing upstream
(store, API, UI) should ever need to know which vendor produced an event. This is
deliberately a different vocabulary from GatewayCore's `{type: round|tool|tool_result|
final}` chat events (see channels/core.py) — an agent session is a longer-lived,
richer-grained thing than one model turn, and the two must never be conflated (see
WORKLOG.md "Frontier-router chat lane — untrusted tool_calls dispatch" for why treating
one thing as if it were the other is exactly how that bug happened).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EventType = Literal[
    "session_started", "assistant_delta", "assistant_message",
    "tool_requested", "approval_required", "approval_resolved",
    "tool_started", "tool_output", "tool_finished",
    "file_changed", "command_started", "command_finished",
    "usage", "warning", "session_idle", "session_failed", "session_closed",
]


@dataclass
class AgentEvent:
    """One normalized event a harness adapter emits. `sequence` and `ts` are assigned
    by SessionStore.append_event — the store is the single source of truth for
    per-session ordering, not the harness, so a reconnecting client can ask for
    "everything after sequence N" and get exactly the gap, no more, no less."""
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int | None = None
    ts: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "sequence": self.sequence, "ts": self.ts,
                "payload": self.payload}
