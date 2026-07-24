"""AgentSessionService — the sole lifecycle owner for agent sessions. FastAPI (and
later the host worker) call ONLY this, never a harness or the store directly, so
there is exactly one place that decides what's allowed and one place that keeps
the durable Ledger state and in-process harness objects consistent after a
restart.
"""
from __future__ import annotations

from dataclasses import replace
import os
from typing import AsyncIterator

from .events import AgentEvent
from .protocol import AgentHarness, ApprovalDecision, SessionStart
from .registry import HarnessRegistry
from .store import SessionRecord, SessionStoreProtocol


class PolicyRefusal(RuntimeError):
    """A typed, durably-recorded refusal from the declarative policy stack."""

    def __init__(self, decision, action, event: AgentEvent | None = None) -> None:
        self.decision = decision
        self.action = action
        self.event = event
        super().__init__(
            f"policy {decision.policy_set!r} denied tool {action.tool_name!r}")


class AgentSessionService:
    def __init__(self, *, store: SessionStoreProtocol, registry: HarnessRegistry,
                 usage_service: object | None = None) -> None:
        self.store = store
        self.registry = registry
        self.usage_service = usage_service
        # PROCESS-LOCAL cache only — never the source of truth. A restart empties
        # this; every method below reconstructs a fresh harness instance for an
        # existing durable session rather than assuming this cache still holds
        # one, so a FakeHarness session (which keeps no state of its own — see
        # fake_harness.py) behaves identically before and after a restart. A
        # real SDK-backed harness with a genuinely dead subprocess is expected to
        # surface that itself (via probe()/its own methods raising), not have
        # this service fabricate a resumed connection.
        self._active_harnesses: dict[str, AgentHarness] = {}

    def _harness_for(self, record: SessionRecord) -> AgentHarness:
        cached = self._active_harnesses.get(record.session_id)
        if cached is not None:
            return cached
        harness = self.registry.get(record.harness).factory()
        self._active_harnesses[record.session_id] = harness
        return harness

    async def list_harnesses(self) -> list[dict]:
        return await self.registry.probes()

    async def list_models(self, harness_id: str) -> list[dict]:
        """Runtime-discovered model catalog for one harness — Codex from the
        live SDK model list, Claude from a validated CLI/API alias catalog, and
        an empty list for a harness that exposes none (e.g. the fake). A fresh
        instance per call, same discipline as probes(). `list_models` is an
        OPTIONAL harness method discovered via getattr, so no adapter is forced
        to implement it (mirrors how `interactive_approvals`/`shutdown` are
        optional)."""
        import inspect
        harness = self.registry.get(harness_id).factory()  # KeyError on unknown
        fn = getattr(harness, "list_models", None)
        if fn is None:
            return []
        result = fn()
        if inspect.isawaitable(result):
            result = await result
        return list(result)

    async def start_session(self, request: SessionStart) -> SessionRecord:
        if os.environ.get("AGENT_SESSION_SPEC_ENABLED", "") == "1" and request.spec_name:
            # Import and lookup stay inside the call: no import-time config scan
            # or cached lookup can hide a changed/monkeypatched spec directory.
            from .spec_bridge import load_spec, resolve_spec
            spec, instructions = load_spec(request.spec_name)
            descriptor = resolve_spec(spec, self.registry)
            request = replace(
                request, harness_id=descriptor.harness_id, mode=spec.mode,
                provider_profile=spec.capability_profile.value,
                model=None, effort=spec.effort.value if spec.effort else None,
                instructions=instructions, spec_name=spec.name)
        else:
            # A supplied spec_name is deliberately ignored while the flag is
            # off, preserving the pre-AGT-16 boot request byte for byte.
            request = replace(request, instructions=None, spec_name=None)
            descriptor = self.registry.get(request.harness_id)
        if request.mode not in descriptor.supported_modes:
            raise ValueError(
                f"harness {request.harness_id!r} does not support mode "
                f"{request.mode!r} (supports: {list(descriptor.supported_modes)})")
        harness = descriptor.factory()
        probe = await harness.probe()
        if not probe.available:
            raise RuntimeError(
                f"harness {request.harness_id!r} is unavailable: {probe.detail}")
        session_id = await harness.start_session(request)
        self._active_harnesses[session_id] = harness
        return self.store.get(session_id)

    def get_session(self, session_id: str) -> SessionRecord:
        return self.store.get(session_id)

    def _policy_sets_for_session(self, session_id: str):
        spec_name = None
        for event in self.store.events_since(session_id, 0):
            if event.type == "session_started" and event.payload.get("spec_name"):
                spec_name = event.payload["spec_name"]
                break
        if spec_name is None:
            return []

        # Both imports and both config reads stay action-local: tests and live
        # operators can change the policy/spec roots without an import-time scan
        # or stale cache masking the new contract.
        from . import policy_engine
        from .spec_bridge import load_spec

        spec, _instructions = load_spec(spec_name)
        if not spec.policy_refs:
            return []
        config = policy_engine.load_policy_config()
        return policy_engine.select_policy_sets(config, spec.policy_refs)

    def _session_cost_usd(self, session_id: str) -> float | None:
        if self.usage_service is None:
            return None
        reader = getattr(self.usage_service, "session_cost_usd", None)
        if reader is None:
            raise TypeError("usage_service does not expose session_cost_usd")
        return reader(session_id)

    def _session_tool_call_count(self, session_id: str) -> int:
        action_types = {
            "tool_requested", "tool_started", "command_started",
            "approval_required",
        }
        return sum(
            event.type in action_types
            and not event.payload.get("policy_generated", False)
            for event in self.store.events_since(session_id, 0))

    @staticmethod
    def _is_tool_action_event(event: AgentEvent) -> bool:
        return event.type in {
            "tool_requested", "tool_started", "command_started",
            "approval_required",
        }

    @staticmethod
    def _tool_name(event: AgentEvent) -> str:
        for key in ("tool", "name", "item_type"):
            value = event.payload.get(key)
            if value:
                return str(value)
        if event.type == "command_started":
            return "os.command"
        if event.type == "approval_required":
            return str(event.payload.get("action") or "approval_action")
        return "unknown_tool"

    @classmethod
    def _is_os_tool(cls, event: AgentEvent) -> bool:
        if event.type in {"command_started", "approval_required"}:
            return True
        return cls._tool_name(event).casefold() in {
            "bash", "bashoutput", "cmd", "commandexecution", "edit",
            "filechange", "killshell", "multiedit", "notebookedit",
            "powershell", "shell", "write",
        }

    def _evaluate_policy(self, session_id: str, event: AgentEvent):
        from .policy_engine import ToolAction, resolve

        action = ToolAction(
            tool_name=self._tool_name(event),
            is_os_tool=self._is_os_tool(event),
            estimated_cost_usd=self._session_cost_usd(session_id),
            session_tool_call_count=self._session_tool_call_count(session_id),
        )
        return action, resolve(self._policy_sets_for_session(session_id), action)

    def evaluate_board_change_policy(
        self, session_id: str, *, author_harness: str, kind: str,
    ):
        """Evaluate an agent proposal before the cockpit creates it.

        A board-policy ASK records that the request must continue through the
        board wall that already exists; it never creates or resolves a generic
        agent-session approval. The board wall remains authoritative.
        """
        from command_center.schemas.session_policy import PolicyVerdict

        from .policy_engine import ToolAction, resolve

        record = self.store.get(session_id)
        if record.harness != author_harness:
            raise ValueError(
                f"session {session_id!r} belongs to harness {record.harness!r}, "
                f"not proposal author {author_harness!r}")
        action = ToolAction(
            tool_name=f"board_change:{kind}",
            is_os_tool=False,
            estimated_cost_usd=self._session_cost_usd(session_id),
            # Tool events are already appended when packet-1 evaluates them.
            # Count this not-yet-created proposal action explicitly so the
            # existing call-cap builtin has identical semantics here.
            session_tool_call_count=self._session_tool_call_count(session_id) + 1,
            author_harness=author_harness,
            session_id=session_id,
        )
        decision = resolve(self._policy_sets_for_session(session_id), action)
        if decision.verdict == PolicyVerdict.DENY:
            denial = self._record_policy_denial(session_id, decision, action)
            raise PolicyRefusal(decision, action, denial)
        if decision.verdict == PolicyVerdict.ASK:
            # This is a durable routing marker, not a second approval record:
            # there is deliberately no approval_id and no create_approval().
            self.store.append_event(session_id, AgentEvent(
                "approval_required", {
                    "action": action.tool_name,
                    "policy_generated": True,
                    "policy_set": decision.policy_set,
                    "approval_surface": "board_change_human_wall",
                    "requires_human_token": True,
                }))
        return action, decision

    def _record_policy_denial(self, session_id: str, decision, action) -> AgentEvent:
        return self.store.append_event(session_id, AgentEvent("policy_denied", {
            "verdict": decision.verdict.value,
            "tool": action.tool_name,
            "level": decision.level.value if decision.level else None,
            "policy_set": decision.policy_set,
            "handler": decision.handler.value if decision.handler else None,
            "note": decision.note,
        }))

    async def send_message(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        record = self.store.get(session_id)
        if record.status == "closed":
            raise ValueError(f"session {session_id!r} is closed")
        harness = self._harness_for(record)
        # The durable transcript must include what the HUMAN said. Without
        # this, replay after a refresh shows only the agent's half of the
        # conversation (2026-07-16: "none of our own messages" in the chat).
        yield self.store.append_event(
            session_id, AgentEvent("user_message", {"text": prompt}))
        async for event in harness.send(session_id, prompt):
            if (os.environ.get("AGENT_SESSION_POLICIES_ENABLED", "") == "1"
                    and self._is_tool_action_event(event)):
                from command_center.schemas.session_policy import PolicyVerdict

                action, decision = self._evaluate_policy(session_id, event)
                if decision.verdict == PolicyVerdict.DENY:
                    denial = self._record_policy_denial(
                        session_id, decision, action)
                    raise PolicyRefusal(decision, action, denial)
                if decision.verdict == PolicyVerdict.ASK:
                    # A harness-native approval is already the existing wall.
                    # Otherwise create the same durable approval/event shape and
                    # stop consuming the harness generator before dispatch.
                    if event.type == "approval_required":
                        yield event
                    else:
                        yield event
                        approval = self.store.create_approval(
                            session_id, action=action.tool_name)
                        yield self.store.append_event(session_id, AgentEvent(
                            "approval_required", {
                                "approval_id": approval.approval_id,
                                "action": action.tool_name,
                                "policy_generated": True,
                                "policy_set": decision.policy_set,
                            }))
                    return
            yield event

    def get_events(self, session_id: str, after_sequence: int = 0) -> list[AgentEvent]:
        return self.store.events_since(session_id, after_sequence)

    async def resolve_approval(self, session_id: str, decision: ApprovalDecision) -> None:
        record = self.store.get(session_id)
        await self._harness_for(record).resolve_approval(session_id, decision)

    async def interrupt(self, session_id: str) -> None:
        record = self.store.get(session_id)
        await self._harness_for(record).interrupt(session_id)

    async def resume(self, session_id: str) -> None:
        record = self.store.get(session_id)
        await self._harness_for(record).resume(session_id)

    async def close(self, session_id: str) -> None:
        record = self.store.get(session_id)
        await self._harness_for(record).close(session_id)
        self._active_harnesses.pop(session_id, None)
