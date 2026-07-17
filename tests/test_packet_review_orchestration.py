"""Phase 6 live review ORCHESTRATION (advisory-only, judge synthesis).

The core safety property: running agent reviews into a packet can NEVER unlock
commit — every recorded review is advisory (`reviewer_kind='agent'`, never
'approved'), so a human approval is still required. Hermetic: the reviewer and
judge are injected fakes; the record sink is the real invariant-enforced
PacketService.set_review.
"""
from __future__ import annotations

import itertools

import pytest

from command_center.work_graph.packet import (
    InMemoryPacketStore,
    PacketService,
)
from command_center.work_graph.packet_review import (
    AgentReviewResult,
    OrchestrationReport,
    default_judge,
    orchestrate_reviews,
    review_input_from_packet,
    structural_reviewer,
)
from command_center.work_graph.planner import PlanBoardRef, WorkPlanItemIn, WorkPlanIn


def _packets() -> PacketService:
    ids, ticks = itertools.count(1), itertools.count(1)
    return PacketService(InMemoryPacketStore(),
                         clock=lambda: f"2026-07-17T02:00:{next(ticks):02d}+00:00",
                         id_factory=lambda: f"pkt-{next(ids)}")


def _plan():
    return WorkPlanIn(conversation_id="c", items=[
        WorkPlanItemIn(ref="a", title="Ship it", kind="feature",
                       primary_board=PlanBoardRef(board_id="eng", domain_id="eng"))])


def _assemble(svc, **kw):
    return svc.assemble(_plan(), review_roles=["codex_agent", "claude_code_local"], **kw)


def _record(svc, packet_id):
    def record(**kw):
        return svc.set_review(packet_id, kw["role"], status=kw["status"],
                              summary=kw["summary"], findings=kw["findings"],
                              reviewer_kind=kw["reviewer_kind"])
    return record


def test_orchestration_records_advisory_and_never_unlocks_commit():
    svc = _packets()
    p = _assemble(svc)                       # codex_agent + claude_code_local slots
    report = orchestrate_reviews(
        packet=p, review_roles=["codex_agent", "claude_code_local"],
        record=_record(svc, p.packet_id))
    after = svc.get(p.packet_id)
    # every review slot got an ADVISORY status, never "approved"
    statuses = {s.role: s.status for s in after.reviews}
    assert all(v != "approved" for v in statuses.values())
    assert all(s.reviewer_kind == "agent" for s in after.reviews)
    # the packet is NOT ready — a human must still approve
    assert not svc.is_ready(after)
    assert report.unlocked_commit is False


def test_a_reviewer_that_recommends_approve_is_still_advisory():
    svc = _packets()
    p = _assemble(svc)

    def eager(role, _ri):     # a buggy/overeager reviewer that wants to approve
        return AgentReviewResult(role=role, summary="LGTM approve!",
                                 recommendation="approve")   # not a valid advisory rec

    orchestrate_reviews(packet=p, review_roles=["codex_agent"],
                        record=_record(svc, p.packet_id), review_fn=eager,
                        include_judge=False)
    slot = next(s for s in svc.get(p.packet_id).reviews if s.role == "codex_agent")
    assert slot.status == "reviewed"          # unknown rec degraded to advisory
    assert slot.status != "approved"
    assert not svc.is_ready(svc.get(p.packet_id))


def test_direct_approve_attempt_by_orchestration_is_blocked_by_the_sink():
    # even if orchestration tried to record "approved" as an agent, set_review refuses
    from command_center.work_graph.packet import PacketError
    svc = _packets()
    p = _assemble(svc)
    with pytest.raises(PacketError, match="agent review may not"):
        _record(svc, p.packet_id)(role="codex_agent", status="approved",
                                  summary="x", findings=[], reviewer_kind="agent")


def test_judge_synthesizes_findings_across_reviewers():
    svc = _packets()
    p = _assemble(svc)
    report = orchestrate_reviews(
        packet=p, review_roles=["codex_agent", "claude_code_local"],
        record=_record(svc, p.packet_id))
    # a judge slot exists only if the packet had one; here we assert the report
    assert report.synthesis is not None
    assert report.synthesis["role"] == "judge"
    # the default structural reviewer flags the missing runbook/acceptance → changes
    assert report.synthesis["status"] == "changes_requested"
    assert any("runbook" in f for f in report.synthesis["findings"])


def test_structural_reviewer_passes_a_complete_packet():
    svc = _packets()
    p = _assemble(svc, runbook=["build", "test"],
                  acceptance_criteria=["works"], research="context here")
    ri = review_input_from_packet(p)
    result = structural_reviewer("codex_agent", ri)
    assert result.recommendation == "pass" and result.findings == ()


def test_judge_passes_when_no_reviewer_raised_findings():
    clean = [AgentReviewResult(role="codex_agent", summary="ok", recommendation="pass"),
             AgentReviewResult(role="claude_code_local", summary="ok", recommendation="pass")]
    verdict = default_judge(clean)
    assert verdict.recommendation == "pass"
    assert "advisory" in verdict.summary.lower()


def test_review_input_hides_prior_review_outcomes():
    # a reviewer must not see other reviews (independence) — ReviewInput has no
    # 'reviews'/'status' field at all
    svc = _packets()
    p = _assemble(svc)
    ri = review_input_from_packet(p)
    assert not hasattr(ri, "reviews") and not hasattr(ri, "status")
