"""Readiness Packet (Phase H, slice 1) — assemble everything needed to REVIEW a
proposed unit of work BEFORE the graph is created: the Work Graph Plan (reusing
`summarize_plan`), a runbook, research notes, acceptance criteria, and per-role
independent-review slots. A deterministic readiness gate says whether the packet
is complete; `commit` refuses unless it is, then creates the work graph and links
every created item back to the packet (`WorkItem.packet_id`).

Boundaries this slice keeps deliberately clean:
  * It is PLANNING, not execution — assembling/committing a packet creates work
    items (no mission, no wall verb). Human confirmation is the readiness gate +
    the existing preview/commit split, not the mission-approval HMAC wall.
  * Review slots start `pending` and are filled by a LATER slice (the live
    Claude/Codex / judge_gate review orchestration) or set manually by a human
    here. This module runs NO agent and invents no verdict.
  * Deterministic + hermetic: readiness is presence + review-status checks with
    no invented thresholds; clock + id injected.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import BaseModel, Field

from .planner import WorkPlanIn, summarize_plan
from .schemas import WorkGraphPlanSummary

_REVIEW_STATUSES = ("pending", "approved", "changes_requested", "error")
_PACKET_STATUSES = ("draft", "in_review", "ready", "committed")


class RunbookStep(BaseModel):
    order: int
    text: str


class AcceptanceCriterion(BaseModel):
    text: str
    met: bool | None = None            # None = not yet evaluated


class ReviewSlot(BaseModel):
    """A slot for one independent review (by an agent role or a judge). Starts
    `pending`; filled by the review-orchestration slice or set manually by a
    human. `session_id` links to the agent-session/judge run that produced it."""
    role: str                          # e.g. claude_code_local | codex_agent | skeptic
    status: str = "pending"            # pending | approved | changes_requested | error
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    session_id: str | None = None
    reviewed_at: str | None = None


class ReadinessCheck(BaseModel):
    """One readiness row (the job-search validation idiom). `level="error"` blocks
    commit; `level="warning"` is advisory."""
    id: str
    label: str
    ok: bool
    level: str = "error"               # error | warning
    detail: str = ""


class ReadinessPacket(BaseModel):
    packet_id: str
    title: str
    status: str = "draft"
    capture_id: str | None = None
    conversation_id: str | None = None
    work_item_ids: list[str] = Field(default_factory=list)   # set after commit
    plan: WorkPlanIn
    plan_summary: WorkGraphPlanSummary
    research: str = ""
    runbook: list[RunbookStep] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    reviews: list[ReviewSlot] = Field(default_factory=list)
    created_at: str
    updated_at: str


class PacketError(ValueError):
    """A malformed packet request (unknown packet/role, empty plan)."""


class PacketNotReady(PacketError):
    """Commit was attempted while an error-level readiness check fails."""


class InMemoryPacketStore:
    def __init__(self) -> None:
        self._by_id: dict[str, ReadinessPacket] = {}
        self._order: list[str] = []

    def add(self, packet: ReadinessPacket) -> None:
        if packet.packet_id not in self._by_id:
            self._order.append(packet.packet_id)
        self._by_id[packet.packet_id] = packet

    def get(self, packet_id: str) -> ReadinessPacket:
        p = self._by_id.get(packet_id)
        if p is None:
            raise KeyError(f"no such packet: {packet_id}")
        return p

    def put(self, packet: ReadinessPacket) -> None:
        self._by_id[packet.packet_id] = packet

    def list(self, *, status: str | None = None) -> list[ReadinessPacket]:
        out = [self._by_id[i] for i in self._order]
        if status is not None:
            out = [p for p in out if p.status == status]
        return out


class PacketService:
    def __init__(self, store: InMemoryPacketStore, *, clock: Callable[[], str],
                 id_factory: Callable[[], str]) -> None:
        self._store = store
        self._clock = clock
        self._id = id_factory

    def assemble(self, plan: WorkPlanIn, *, title: str | None = None,
                 capture_id: str | None = None, conversation_id: str | None = None,
                 research: str = "", runbook: Sequence[str] = (),
                 acceptance_criteria: Sequence[str] = (),
                 review_roles: Sequence[str] = ()) -> ReadinessPacket:
        """Build a packet from a plan: compute its Work Graph Plan summary, seed
        runbook/research/acceptance from the caller, and open a PENDING review
        slot per requested role. Persists nothing beyond the packet itself."""
        if not plan.items:
            raise PacketError("a packet's plan must contain at least one item")
        refs = [it.ref for it in plan.items]
        if len(set(refs)) != len(refs):
            # the planner would reject this at commit; catch it here so a packet is
            # never assembled (and marked "ready") for a plan that cannot commit.
            raise PacketError("duplicate item ref in the plan")
        now = self._clock()
        packet = ReadinessPacket(
            packet_id=self._id(),
            title=title or plan.items[0].title,
            capture_id=capture_id or plan.capture_id,
            conversation_id=conversation_id or plan.conversation_id,
            plan=plan, plan_summary=summarize_plan(plan), research=research,
            runbook=[RunbookStep(order=i + 1, text=t)
                     for i, t in enumerate(runbook)],
            acceptance_criteria=[AcceptanceCriterion(text=t)
                                 for t in acceptance_criteria],
            reviews=[ReviewSlot(role=r) for r in review_roles],
            created_at=now, updated_at=now)
        packet.status = self._status_of(packet)
        self._store.add(packet)
        return packet

    def get(self, packet_id: str) -> ReadinessPacket:
        return self._store.get(packet_id)

    def list(self, *, status: str | None = None) -> list[ReadinessPacket]:
        return self._store.list(status=status)

    def set_review(self, packet_id: str, role: str, *, status: str,
                   summary: str = "",
                   findings: Sequence[str] = ()) -> ReadinessPacket:
        """Set the outcome of a review slot (a human override now; the review
        orchestration will use the same path later). Raises on unknown role."""
        if status not in _REVIEW_STATUSES:
            raise PacketError(f"unknown review status: {status!r}")
        packet = self._store.get(packet_id)
        if packet.status == "committed":
            raise PacketError(
                f"packet {packet_id} is committed; its reviews are frozen")
        slot = next((s for s in packet.reviews if s.role == role), None)
        if slot is None:
            raise PacketError(f"packet {packet_id} has no review slot {role!r}")
        slot.status = status
        slot.summary = summary
        slot.findings = list(findings)
        slot.reviewed_at = self._clock()
        packet.updated_at = self._clock()
        packet.status = self._status_of(packet)
        self._store.put(packet)
        return packet

    def readiness(self, packet_id: str) -> list[ReadinessCheck]:
        return self._checks(self._store.get(packet_id))

    def is_ready(self, packet: ReadinessPacket) -> bool:
        return not any(c.level == "error" and not c.ok
                       for c in self._checks(packet))

    def commit(self, packet_id: str, planner) -> ReadinessPacket:
        """Create the work graph the packet describes — but only if it is ready.
        Threads packet_id onto every created WorkItem (via the plan) so the items
        link back to the packet, records their ids, and marks it committed."""
        packet = self._store.get(packet_id)
        if packet.status == "committed":
            raise PacketError(f"packet {packet_id} is already committed")
        failing = [c for c in self._checks(packet) if c.level == "error" and not c.ok]
        if failing:
            raise PacketNotReady(
                f"packet {packet_id} is not ready: "
                + "; ".join(f"{c.label}" for c in failing))
        plan = packet.plan.model_copy(update={"packet_id": packet.packet_id})
        receipt = planner.commit(plan)          # WorkGraphError/KeyError propagate
        ids = [r.work_item.work_item_id for r in receipt.created]
        packet.work_item_ids = ids
        packet.status = "committed"
        packet.updated_at = self._clock()
        self._store.put(packet)
        return packet

    # ---- deterministic readiness (presence + review status; no thresholds) --
    def _checks(self, packet: ReadinessPacket) -> list[ReadinessCheck]:
        s = packet.plan_summary
        reviews_done = all(r.status == "approved" for r in packet.reviews)
        pending = [r.role for r in packet.reviews if r.status != "approved"]
        return [
            ReadinessCheck(
                id="has_items", label="plan has at least one work item",
                ok=s.item_count > 0, level="error",
                detail=f"{s.item_count} item(s)"),
            ReadinessCheck(
                id="reviews_approved",
                label="every requested review is approved",
                ok=reviews_done, level="error",
                detail=("all approved" if reviews_done
                        else f"awaiting: {', '.join(pending)}")),
            ReadinessCheck(
                id="has_runbook", label="a runbook is provided",
                ok=bool(packet.runbook), level="warning",
                detail=f"{len(packet.runbook)} step(s)"),
            ReadinessCheck(
                id="has_acceptance", label="acceptance criteria are provided",
                ok=bool(packet.acceptance_criteria), level="warning",
                detail=f"{len(packet.acceptance_criteria)} criterion(s)"),
            ReadinessCheck(
                id="all_items_boarded",
                label="no item will land board-less in the Inbox",
                ok=s.items_without_board == 0, level="warning",
                detail=f"{s.items_without_board} without a board"),
        ]

    def _status_of(self, packet: ReadinessPacket) -> str:
        if packet.status == "committed":
            return "committed"
        if not packet.reviews:
            return "ready" if self.is_ready(packet) else "draft"
        if all(r.status == "approved" for r in packet.reviews):
            return "ready" if self.is_ready(packet) else "in_review"
        return "in_review"
