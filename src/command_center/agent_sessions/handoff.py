"""Bounded, typed hand-off packet for Claude ⇄ Codex ⇄ OpenRouter switching.

The plan (§6) is explicit: handing off must produce a *bounded artifact* — goal,
current state, a few selected messages, the workspace, relevant files, open
questions, permission mode, and evidence links — and must NOT "automatically
forward an unlimited private transcript." This module is the single source of
truth for that packet and its bounds, so every caller (the worker endpoint, the
cockpit) hands off the same shape, capped the same way.

Pure functions over the normalized AgentEvent stream — no network, no store
writes — so the bounds are hermetically testable (`test_handoff_is_bounded`).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bounds — the teeth behind "not an unlimited transcript". A hand-off is a
# briefing, not a copy of the whole session.
_MAX_GOAL = 400
_MAX_STATE = 1200
_MAX_MSG_CHARS = 800
_MAX_MESSAGES = 6
_MAX_FILES = 20
_MAX_QUESTIONS = 8


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class HandoffPacket(BaseModel):
    """A bounded briefing passed to the assistant taking over the work."""
    model_config = ConfigDict(extra="forbid")

    from_harness: str
    to_harness: str
    repo_id: str
    permission_profile: str
    source_session_id: str
    goal: str = ""
    latest_state: str = ""
    selected_messages: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    # The packet is self-enforcing: these validators are the ONE place the
    # bounds live, so a packet is bounded no matter how it was constructed (they
    # clip/cap rather than reject — a hand-off should degrade to a briefing, not
    # fail). mode="before" so clipping happens ahead of any type coercion.
    @field_validator("goal", mode="before")
    @classmethod
    def _clip_goal(cls, v: str) -> str:
        return _clip(str(v or ""), _MAX_GOAL)

    @field_validator("latest_state", mode="before")
    @classmethod
    def _clip_state(cls, v: str) -> str:
        return _clip(str(v or ""), _MAX_STATE)

    @field_validator("selected_messages", mode="before")
    @classmethod
    def _clip_messages(cls, v: list[str]) -> list[str]:
        return [_clip(str(s), _MAX_MSG_CHARS) for s in (v or [])][:_MAX_MESSAGES]

    @field_validator("open_questions", mode="before")
    @classmethod
    def _clip_questions(cls, v: list[str]) -> list[str]:
        return [_clip(str(s), _MAX_MSG_CHARS) for s in (v or [])][:_MAX_QUESTIONS]

    @field_validator("relevant_files", mode="before")
    @classmethod
    def _cap_files(cls, v: list[str]) -> list[str]:
        return [str(s) for s in (v or [])][:_MAX_FILES]


def _text(event: Any) -> str:
    """assistant_message / user_message carry their text under payload['text']."""
    payload = getattr(event, "payload", None) or {}
    return str(payload.get("text") or "").strip()


def _etype(event: Any) -> str:
    return str(getattr(event, "type", ""))


def build_handoff_packet(
    *,
    source_record: Any,
    events: list[Any],
    to_harness: str,
    goal: str | None = None,
    open_questions: list[str] | None = None,
) -> HandoffPacket:
    """Assemble a bounded packet from a session's record + normalized events.

    `source_record` is the AgentSessionRecord (harness, repo_id,
    permission_profile, session_id). Nothing here mutates the session or the
    store; the caller records handoff evidence separately.
    """
    assistant_msgs = [_text(e) for e in events
                      if _etype(e) == "assistant_message" and _text(e)]
    user_msgs = [_text(e) for e in events
                 if _etype(e) == "user_message" and _text(e)]

    # goal: caller-supplied, else the first thing the user asked for.
    resolved_goal = goal if goal is not None else (user_msgs[0] if user_msgs else "")

    # latest_state: the most recent assistant message = where the work stands.
    latest_state = assistant_msgs[-1] if assistant_msgs else ""

    # selected_messages: the tail of the exchange (bounded), NOT the whole log.
    tail: list[str] = []
    for u, a in zip(user_msgs[-_MAX_MESSAGES:], assistant_msgs[-_MAX_MESSAGES:]):
        tail.append(f"you: {u}")
        tail.append(f"{source_record.harness}: {a}")
    selected = tail[-_MAX_MESSAGES:]

    # relevant_files: distinct paths the source session actually read.
    files: list[str] = []
    for e in events:
        if _etype(e) != "tool_started":
            continue
        args = (getattr(e, "payload", None) or {}).get("args") or {}
        path = args.get("path") or args.get("pattern")
        if path and path not in files:
            files.append(str(path))

    return HandoffPacket(
        from_harness=source_record.harness,
        to_harness=to_harness,
        repo_id=source_record.repo_id,
        permission_profile=source_record.permission_profile,
        source_session_id=source_record.session_id,
        goal=resolved_goal,
        latest_state=latest_state,
        selected_messages=selected,
        relevant_files=files[:_MAX_FILES],
        open_questions=(open_questions or [])[:_MAX_QUESTIONS],
    )


def render_handoff_prompt(packet: HandoffPacket) -> str:
    """Render the packet as the bounded briefing seeded into the target
    assistant. Structured sections, capped by construction — this is the ONLY
    text that crosses the hand-off (never the raw transcript)."""
    lines = [
        f"Hand-off from {packet.from_harness} → {packet.to_harness} "
        f"(per the CLAUDE.md capability split).",
        f"Workspace: {packet.repo_id}  ·  permission: {packet.permission_profile}",
        f"Evidence: source session {packet.source_session_id}",
        "",
        f"Goal: {packet.goal or '(not stated)'}",
    ]
    if packet.latest_state:
        lines += ["", "Where it stands:", packet.latest_state]
    if packet.relevant_files:
        lines += ["", "Relevant files:",
                  *[f"  - {f}" for f in packet.relevant_files]]
    if packet.selected_messages:
        lines += ["", "Recent exchange:", *[f"  {m}" for m in packet.selected_messages]]
    if packet.open_questions:
        lines += ["", "Open questions:",
                  *[f"  - {q}" for q in packet.open_questions]]
    lines += ["", "Continue this work at your capability level."]
    return "\n".join(lines)
