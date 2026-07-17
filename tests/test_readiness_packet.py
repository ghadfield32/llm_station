"""Readiness Packet (Phase H slice 1): assemble a reviewable packet from a plan,
gate commit on deterministic readiness, and link created items back via
packet_id. Assembling/committing is PLANNING (no wall verb); review slots start
pending and are set by a human here (the live review orchestration is a later
slice). Hermetic: in-memory packet + work-graph stores, injected clock/id.
"""
from __future__ import annotations

import itertools

import pytest

from command_center.work_graph import (
    ChatWorkPlanner,
    InMemoryPacketStore,
    InMemoryWorkGraphStore,
    PacketError,
    PacketNotReady,
    PacketService,
    PlanBoardRef,
    WorkGraphError,
    WorkGraphService,
    WorkPlanEdgeIn,
    WorkPlanIn,
    WorkPlanItemIn,
)


def _wg(tag: str) -> WorkGraphService:
    ticks = itertools.count(1)
    counters: dict[str, itertools.count] = {}

    def mkid(prefix: str) -> str:
        counters.setdefault(prefix, itertools.count(1))
        return f"{tag}-{prefix}-{next(counters[prefix])}"

    return WorkGraphService(InMemoryWorkGraphStore(),
                            clock=lambda: f"2026-07-14T00:00:{next(ticks):02d}+00:00",
                            id_factory=mkid)


def _planner():
    real = _wg("real")
    return ChatWorkPlanner(real, sandbox_factory=lambda: _wg("box")), real


def _packets() -> PacketService:
    ids = itertools.count(1)
    ticks = itertools.count(1)
    return PacketService(InMemoryPacketStore(),
                         clock=lambda: f"2026-07-14T01:00:{next(ticks):02d}+00:00",
                         id_factory=lambda: f"pkt-{next(ids)}")


def _plan() -> WorkPlanIn:
    return WorkPlanIn(conversation_id="chat-1", items=[
        WorkPlanItemIn(ref="a", title="Ship the packet feature", kind="feature",
                       primary_board=PlanBoardRef(board_id="eng", domain_id="eng"))])


def test_assemble_builds_a_packet_with_plan_summary_and_review_slots():
    svc = _packets()
    p = svc.assemble(_plan(), runbook=["build", "test"],
                     acceptance_criteria=["it works"], review_roles=["codex_agent"])
    assert p.title == "Ship the packet feature"
    assert p.plan_summary.item_count == 1
    assert [s.text for s in p.runbook] == ["build", "test"]
    assert [s.order for s in p.runbook] == [1, 2]
    assert [c.text for c in p.acceptance_criteria] == ["it works"]
    assert [r.role for r in p.reviews] == ["codex_agent"]
    assert p.reviews[0].status == "pending"
    assert p.status == "in_review"                 # a review is pending


def test_assemble_empty_plan_is_rejected():
    with pytest.raises(PacketError):
        _packets().assemble(WorkPlanIn(conversation_id="c", items=[]))


def test_readiness_flags_pending_reviews_as_blocking():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    checks = {c.id: c for c in svc.readiness(p.packet_id)}
    assert checks["has_items"].ok is True
    assert checks["reviews_approved"].ok is False and checks["reviews_approved"].level == "error"
    assert checks["has_runbook"].ok is False and checks["has_runbook"].level == "warning"
    assert not svc.is_ready(p)


def test_no_reviews_requested_is_ready():
    svc = _packets()
    p = svc.assemble(_plan())                       # no review_roles
    assert svc.is_ready(p) and p.status == "ready"


def test_set_review_updates_slot_and_readiness():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    p2 = svc.set_review(p.packet_id, "codex_agent", status="approved",
                        summary="looks good", findings=[])
    assert p2.reviews[0].status == "approved" and p2.reviews[0].reviewed_at
    assert svc.is_ready(p2) and p2.status == "ready"


def test_set_review_unknown_role_or_status_is_rejected():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    with pytest.raises(PacketError):
        svc.set_review(p.packet_id, "nobody", status="approved")
    with pytest.raises(PacketError):
        svc.set_review(p.packet_id, "codex_agent", status="lgtm")


def test_commit_refused_until_ready_then_links_items_back():
    svc = _packets()
    planner, wg = _planner()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    # pending review -> not ready -> commit refused, NOTHING created
    with pytest.raises(PacketNotReady):
        svc.commit(p.packet_id, planner)
    assert wg.list_items() == []
    # approve -> ready -> commit creates the graph and links items to the packet
    svc.set_review(p.packet_id, "codex_agent", status="approved")
    committed = svc.commit(p.packet_id, planner)
    assert committed.status == "committed"
    assert len(committed.work_item_ids) == 1
    item = wg.get_item(committed.work_item_ids[0])
    assert item.packet_id == p.packet_id           # the reserved seam is wired
    # a packet link is now emitted for the item
    assert any(lk.kind == "packet" and lk.resource_id == p.packet_id
               for lk in wg.links_for(item.work_item_id))


def test_double_commit_is_rejected():
    svc = _packets()
    planner, _ = _planner()
    p = svc.assemble(_plan())                       # no reviews -> ready
    svc.commit(p.packet_id, planner)
    with pytest.raises(PacketError):
        svc.commit(p.packet_id, planner)


def test_assemble_rejects_a_structurally_invalid_plan():
    # duplicate refs -> the planner would reject at commit; caught at assemble so
    # the packet can never be marked "ready" for a plan that cannot commit.
    with pytest.raises(PacketError):
        _packets().assemble(WorkPlanIn(conversation_id="c", items=[
            WorkPlanItemIn(ref="a", title="one"),
            WorkPlanItemIn(ref="a", title="two")]))


def test_commit_of_a_cyclic_plan_raises_and_creates_nothing():
    svc = _packets()
    planner, wg = _planner()
    p = svc.assemble(WorkPlanIn(conversation_id="c", items=[
        WorkPlanItemIn(ref="a", title="A"), WorkPlanItemIn(ref="b", title="B")],
        edges=[WorkPlanEdgeIn(from_ref="a", to_ref="b", relation="blocks"),
               WorkPlanEdgeIn(from_ref="b", to_ref="a", relation="blocks")]))
    with pytest.raises(WorkGraphError):
        svc.commit(p.packet_id, planner)
    assert wg.list_items() == []                       # atomic — nothing created
    assert svc.get(p.packet_id).status != "committed"


def test_reviews_are_frozen_after_commit():
    svc = _packets()
    planner, _ = _planner()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    svc.set_review(p.packet_id, "codex_agent", status="approved")
    svc.commit(p.packet_id, planner)
    with pytest.raises(PacketError):
        svc.set_review(p.packet_id, "codex_agent", status="changes_requested")


def test_changes_requested_then_approved_restores_readiness():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    svc.set_review(p.packet_id, "codex_agent", status="changes_requested")
    assert not svc.is_ready(svc.get(p.packet_id))
    p2 = svc.set_review(p.packet_id, "codex_agent", status="approved")
    assert svc.is_ready(p2)


def test_unknown_packet_is_keyerror():
    with pytest.raises(KeyError):
        _packets().get("never-seen")


# ── plan §6 invariant: an agent review can never approve/commit ──────────────

def test_agent_review_may_not_approve():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    with pytest.raises(PacketError, match="agent review may not set status"):
        svc.set_review(p.packet_id, "codex_agent", status="approved",
                       reviewer_kind="agent", summary="lgtm")
    # the slot is untouched — still pending, packet not ready
    assert svc.get(p.packet_id).reviews[0].status == "pending"
    assert not svc.is_ready(svc.get(p.packet_id))


def test_agent_review_records_advisory_findings():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    p2 = svc.set_review(p.packet_id, "codex_agent", status="reviewed",
                        reviewer_kind="agent", summary="read it, no blockers",
                        findings=["consider a test"])
    slot = p2.reviews[0]
    assert slot.status == "reviewed" and slot.reviewer_kind == "agent"
    assert slot.findings == ["consider a test"]
    # advisory-only: an agent 'reviewed' does NOT satisfy the readiness gate
    assert not svc.is_ready(p2)


def test_only_human_approval_unlocks_readiness():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    svc.set_review(p.packet_id, "codex_agent", status="reviewed",
                   reviewer_kind="agent")
    assert not svc.is_ready(svc.get(p.packet_id))         # agent advisory only
    p2 = svc.set_review(p.packet_id, "codex_agent", status="approved",
                        reviewer_kind="human", summary="approved by operator")
    assert p2.reviews[0].reviewer_kind == "human"
    assert svc.is_ready(p2) and p2.status == "ready"


def test_revise_stales_a_human_approval_back_to_pending():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    svc.set_review(p.packet_id, "codex_agent", status="approved",
                   reviewer_kind="human")
    assert svc.is_ready(svc.get(p.packet_id))
    revised = svc.revise(p.packet_id, research="new detail")
    assert revised.reviews[0].status == "pending"          # approval was rev-bound
    assert not svc.is_ready(revised)                       # commit re-gated


def test_unknown_reviewer_kind_rejected():
    svc = _packets()
    p = svc.assemble(_plan(), review_roles=["codex_agent"])
    with pytest.raises(PacketError, match="reviewer_kind"):
        svc.set_review(p.packet_id, "codex_agent", status="reviewed",
                       reviewer_kind="robot")
