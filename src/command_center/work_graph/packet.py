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

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Protocol

from pydantic import BaseModel, Field

from .planner import WorkPlanIn, summarize_plan
from .schemas import WorkGraphPlanSummary

_REVIEW_STATUSES = ("pending", "reviewed", "approved", "changes_requested", "error")
# Outcomes an AGENT reviewer may record — advisory only. "approved" is
# deliberately absent: an agent review can never satisfy the readiness gate;
# only a human may approve (plan §6 "an agent review can never approve work").
_AGENT_REVIEW_STATUSES = ("reviewed", "changes_requested", "error")
_PACKET_STATUSES = ("draft", "in_review", "ready", "committed")

# The reviewable plan-content a revision's content_digest covers. Reviews,
# status, timestamps, revision number, and committed work-item ids are
# DELIBERATELY EXCLUDED: a review must not mutate the digest (else every review
# would mint a new revision and a second reviewer of identical content would hit
# a spurious stale-revision conflict). See the Phase 2 plan-review reconciliation.
_DIGEST_FIELDS = frozenset(
    {"title", "plan", "plan_summary", "research", "runbook", "acceptance_criteria"})


def _content_digest(packet: ReadinessPacket) -> str:
    """Deterministic sha256 over the packet's reviewable plan-content only.

    Uses pydantic `mode="json"` so nested models serialize to JSON-native values,
    then canonical (sorted-key, no-whitespace) JSON so the digest is identical
    across the in-memory and Ledger reconstructions of the same packet."""
    payload = packet.model_dump(mode="json", include=set(_DIGEST_FIELDS))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RunbookStep(BaseModel):
    order: int
    text: str


class AcceptanceCriterion(BaseModel):
    text: str
    met: bool | None = None            # None = not yet evaluated


class ReviewSlot(BaseModel):
    """A slot for one independent review (by an agent role or a judge). Starts
    `pending`; filled by the review-orchestration slice or set manually by a
    human. `session_id` links to the agent-session/judge run that produced it.
    `reviewer_kind` records WHO last set it — an agent review is ADVISORY and can
    never be `approved` (only a human approval satisfies the readiness gate)."""
    role: str                          # e.g. claude_code_local | codex_agent | skeptic
    status: str = "pending"            # pending | reviewed | approved | changes_requested | error
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    session_id: str | None = None
    reviewer_kind: str | None = None   # agent | human (who last set the outcome)
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
    revision: int = 1                  # bumps on plan-content edits, NOT on reviews
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
    committed_at: str | None = None    # set once; a committed packet is frozen


class PacketRevision(BaseModel):
    """An immutable snapshot of one plan-content revision. `content_digest` is the
    canonical hash a reviewer's approval binds to."""
    packet_id: str
    revision: int
    content_digest: str
    created_at: str


class PacketError(ValueError):
    """A malformed packet request (unknown packet/role, empty plan)."""


class PacketNotReady(PacketError):
    """Commit was attempted while an error-level readiness check fails."""


class PacketRevisionConflict(PacketError):
    """A stale-revision write: the caller's expected_revision no longer matches the
    packet's current revision (mapped to HTTP 409)."""


class PacketStore(Protocol):
    """The persistence surface PacketService needs. Both InMemoryPacketStore and
    the durable LedgerPacketStore implement it identically, so PacketService runs
    unchanged over either backend (mirrors the work-graph store split)."""

    def add(self, packet: ReadinessPacket) -> None: ...
    def get(self, packet_id: str) -> ReadinessPacket: ...   # KeyError if absent
    def put(self, packet: ReadinessPacket) -> None: ...
    def list(self, *, status: str | None = None) -> list[ReadinessPacket]: ...
    def append_revision(self, packet_id: str, revision: int, content_digest: str,
                        snapshot_json: str, at: str) -> None: ...   # reject dup
    def list_revisions(self, packet_id: str) -> list[PacketRevision]: ...
    def record_review(self, packet_id: str, revision: int, role: str, status: str,
                     summary: str, findings: Sequence[str],
                     session_id: str | None, at: str) -> None: ...
    def add_work_links(self, packet_id: str, work_item_ids: Sequence[str]) -> None: ...
    def work_links(self, packet_id: str) -> list[str]: ...
    def commit(self, packet: ReadinessPacket,
               work_item_ids: Sequence[str]) -> None: ...   # atomic finalize


class InMemoryPacketStore:
    def __init__(self) -> None:
        self._by_id: dict[str, ReadinessPacket] = {}
        self._order: list[str] = []
        self._revisions: dict[str, list[PacketRevision]] = {}
        self._work_links: dict[str, list[str]] = {}

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

    def append_revision(self, packet_id: str, revision: int, content_digest: str,
                        snapshot_json: str, at: str) -> None:
        revs = self._revisions.setdefault(packet_id, [])
        if any(r.revision == revision for r in revs):
            raise PacketError(
                f"packet {packet_id} revision {revision} already exists (immutable)")
        revs.append(PacketRevision(packet_id=packet_id, revision=revision,
                                   content_digest=content_digest, created_at=at))

    def list_revisions(self, packet_id: str) -> list[PacketRevision]:
        return list(self._revisions.get(packet_id, []))

    def record_review(self, packet_id: str, revision: int, role: str, status: str,
                     summary: str, findings: Sequence[str],
                     session_id: str | None, at: str) -> None:
        # append-only audit; the CURRENT review lives on the packet row (reviews).
        self._reviews_audit().setdefault((packet_id, revision, role), []).append(
            {"status": status, "summary": summary, "findings": list(findings),
             "session_id": session_id, "reviewed_at": at})

    def _reviews_audit(self) -> dict:
        if not hasattr(self, "_audit"):
            self._audit: dict = {}
        return self._audit

    def add_work_links(self, packet_id: str, work_item_ids: Sequence[str]) -> None:
        links = self._work_links.setdefault(packet_id, [])
        for wid in work_item_ids:
            if wid not in links:
                links.append(wid)

    def work_links(self, packet_id: str) -> list[str]:
        return list(self._work_links.get(packet_id, []))

    def commit(self, packet: ReadinessPacket,
               work_item_ids: Sequence[str]) -> None:
        # Single-commit is enforced by PacketService (it re-reads committed_at
        # before mutating) and, durably, by the Ledger /commit endpoint. An
        # in-memory guard here can't distinguish the first commit from a repeat:
        # the store holds the SAME object the service just stamped committed_at on.
        self._by_id[packet.packet_id] = packet
        self.add_work_links(packet.packet_id, work_item_ids)


class PacketService:
    def __init__(self, store: PacketStore, *, clock: Callable[[], str],
                 id_factory: Callable[[], str]) -> None:
        self._store = store
        self._clock = clock
        self._id = id_factory

    def _record_revision(self, packet: ReadinessPacket) -> None:
        """Append the current plan-content as an immutable revision snapshot."""
        self._store.append_revision(
            packet.packet_id, packet.revision, _content_digest(packet),
            packet.model_dump_json(), packet.updated_at)

    def _require_open(self, packet: ReadinessPacket) -> None:
        if packet.committed_at is not None:
            raise PacketError(
                f"packet {packet.packet_id} is committed; it is frozen")

    def _check_revision(self, packet: ReadinessPacket,
                        expected_revision: int | None) -> None:
        if expected_revision is not None and expected_revision != packet.revision:
            raise PacketRevisionConflict(
                f"packet {packet.packet_id} is at revision {packet.revision}, "
                f"not {expected_revision} (the packet changed since you read it)")

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
        self._record_revision(packet)       # revision 1
        return packet

    def get(self, packet_id: str) -> ReadinessPacket:
        return self._store.get(packet_id)

    def list(self, *, status: str | None = None) -> list[ReadinessPacket]:
        return self._store.list(status=status)

    def revisions(self, packet_id: str) -> list[PacketRevision]:
        self._store.get(packet_id)          # 404 if unknown
        return self._store.list_revisions(packet_id)

    def revise(self, packet_id: str, *, expected_revision: int | None = None,
               title: str | None = None, research: str | None = None,
               runbook: Sequence[str] | None = None,
               acceptance_criteria: Sequence[str] | None = None) -> ReadinessPacket:
        """Edit a packet's plan-content, minting a NEW immutable revision. Rejects a
        committed packet (frozen) and a stale expected_revision (409). Reviews are
        NOT part of the content, so editing content does not touch review outcomes —
        but a reviewer's approval was bound to the OLD revision, so readiness is
        re-evaluated against the new one."""
        packet = self._store.get(packet_id)
        self._require_open(packet)
        self._check_revision(packet, expected_revision)
        if title is not None:
            packet.title = title
        if research is not None:
            packet.research = research
        if runbook is not None:
            packet.runbook = [RunbookStep(order=i + 1, text=t)
                              for i, t in enumerate(runbook)]
        if acceptance_criteria is not None:
            packet.acceptance_criteria = [AcceptanceCriterion(text=t)
                                          for t in acceptance_criteria]
        packet.revision += 1
        # a review approved the OLD revision; the content changed, so every slot
        # reverts to pending — a rev-1 approval cannot satisfy rev-2 (§19). The
        # prior outcome stays in the packet_reviews audit, bound to its revision.
        for slot in packet.reviews:
            slot.status = "pending"
            slot.summary = ""
            slot.findings = []
            slot.session_id = None
            slot.reviewed_at = None
        packet.updated_at = self._clock()
        packet.status = self._status_of(packet)
        self._store.put(packet)
        self._record_revision(packet)
        return packet

    def set_review(self, packet_id: str, role: str, *, status: str,
                   summary: str = "", findings: Sequence[str] = (),
                   session_id: str | None = None,
                   reviewer_kind: str = "human",
                   expected_revision: int | None = None) -> ReadinessPacket:
        """Set the outcome of a review slot, BOUND to the packet's current
        revision. Rejects unknown role/status, a committed packet (frozen), and a
        stale expected_revision (a review of an older revision — 409). Does NOT
        mint a new revision: reviews are not part of the content digest.

        THE INVARIANT (plan §6): an AGENT review is advisory and can never be
        `approved` — only a human approval satisfies the readiness gate, so an
        agent can never unlock commit by reviewing its own work."""
        if status not in _REVIEW_STATUSES:
            raise PacketError(f"unknown review status: {status!r}")
        if reviewer_kind not in ("agent", "human"):
            raise PacketError(f"unknown reviewer_kind: {reviewer_kind!r}")
        if reviewer_kind == "agent" and status not in _AGENT_REVIEW_STATUSES:
            raise PacketError(
                f"an agent review may not set status {status!r} — agent reviews "
                f"are advisory ({', '.join(_AGENT_REVIEW_STATUSES)}); only a "
                f"human may approve a packet")
        packet = self._store.get(packet_id)
        self._require_open(packet)
        self._check_revision(packet, expected_revision)
        slot = next((s for s in packet.reviews if s.role == role), None)
        if slot is None:
            raise PacketError(f"packet {packet_id} has no review slot {role!r}")
        now = self._clock()
        slot.status = status
        slot.summary = summary
        slot.findings = list(findings)
        slot.session_id = session_id
        slot.reviewer_kind = reviewer_kind
        slot.reviewed_at = now
        packet.updated_at = now
        packet.status = self._status_of(packet)
        self._store.put(packet)
        # append-only audit binding this outcome to the revision it reviewed
        self._store.record_review(packet_id, packet.revision, role, status,
                                  summary, findings, session_id, now)
        return packet

    def readiness(self, packet_id: str) -> list[ReadinessCheck]:
        return self._checks(self._store.get(packet_id))

    def is_ready(self, packet: ReadinessPacket) -> bool:
        return not any(c.level == "error" and not c.ok
                       for c in self._checks(packet))

    def commit(self, packet_id: str, planner, *,
               expected_revision: int | None = None,
               work_items_for_packet: Callable[[str], list[str]] | None = None,
               ) -> ReadinessPacket:
        """Create the work graph the packet describes — but only if it is ready —
        then freeze the packet (`committed_at`) and link every created WorkItem
        back to it (`WorkItem.packet_id` + `packet_work_links`).

        Idempotent across the cockpit→Ledger boundary: if a prior attempt already
        created the graph (crash between graph-create and packet-finalize), the
        already-created items are discovered via `work_items_for_packet` (they carry
        this packet_id) and REUSED — never a duplicate graph. `expected_revision`
        (409 on mismatch) stops committing a packet that changed under you."""
        packet = self._store.get(packet_id)
        if packet.committed_at is not None:
            raise PacketError(f"packet {packet_id} is already committed")
        self._check_revision(packet, expected_revision)
        failing = [c for c in self._checks(packet) if c.level == "error" and not c.ok]
        if failing:
            raise PacketNotReady(
                f"packet {packet_id} is not ready: "
                + "; ".join(f"{c.label}" for c in failing))
        # reconcile: reuse a graph a prior partial commit already created
        existing = list(work_items_for_packet(packet_id)) if work_items_for_packet \
            else []
        if existing:
            ids = existing
        else:
            plan = packet.plan.model_copy(update={"packet_id": packet.packet_id})
            receipt = planner.commit(plan)      # WorkGraphError/KeyError propagate
            ids = [r.work_item.work_item_id for r in receipt.created]
        now = self._clock()
        packet.work_item_ids = ids
        packet.status = "committed"
        packet.committed_at = now
        packet.updated_at = now
        # atomic finalize: committed_at + work-links in ONE store op (no
        # committed-but-unlinked window). Idempotent double-commit is rejected.
        self._store.commit(packet, ids)
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
        if packet.committed_at is not None:
            return "committed"
        if not packet.reviews:
            return "ready" if self.is_ready(packet) else "draft"
        if all(r.status == "approved" for r in packet.reviews):
            return "ready" if self.is_ready(packet) else "in_review"
        return "in_review"
