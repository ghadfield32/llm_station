"""ChatWorkPlanner: turn a structured plan into connected canonical work with
navigable receipts. preview is side-effect-free; commit is atomic (an invalid
plan writes nothing) and produces one WorkItem per plan item — never duplicate
cards across boards. Planning only: no mission is ever created.
"""
from __future__ import annotations

import itertools

import pytest

from command_center.work_graph import (
    ChatPlanError,
    ChatWorkPlanner,
    InMemoryWorkGraphStore,
    PlanBoardRef,
    WorkGraphError,
    WorkGraphService,
    WorkPlanEdgeIn,
    WorkPlanIn,
    WorkPlanItemIn,
)


def _service(tag: str) -> WorkGraphService:
    ticks = itertools.count(1)
    counters: dict[str, itertools.count] = {}

    def make_id(prefix: str) -> str:
        counters.setdefault(prefix, itertools.count(1))
        return f"{tag}-{prefix}-{next(counters[prefix])}"

    return WorkGraphService(
        InMemoryWorkGraphStore(),
        clock=lambda: f"2026-07-13T00:00:{next(ticks):02d}+00:00",
        id_factory=make_id)


def _planner() -> tuple[ChatWorkPlanner, WorkGraphService]:
    real = _service("real")
    return ChatWorkPlanner(real, sandbox_factory=lambda: _service("box")), real


# a plan mirroring the plan doc's §18: a parent project, a shared prerequisite
# that BLOCKS the feasibility work, and a post that is INFORMED by it.
def _sample_plan() -> WorkPlanIn:
    return WorkPlanIn(
        conversation_id="chat-42",
        capture_batch_id="batch-7",
        items=[
            WorkPlanItemIn(ref="proj", title="Historical biomechanics project",
                           kind="project"),
            WorkPlanItemIn(
                ref="feas", title="CV feasibility", kind="research",
                primary_board=PlanBoardRef(board_id="basketball_cv",
                                           domain_id="basketball_cv"),
                secondary_boards=[PlanBoardRef(board_id="research",
                                               domain_id="research")]),
            WorkPlanItemIn(
                ref="lic", title="Footage licensing assessment", kind="research",
                primary_board=PlanBoardRef(board_id="research", domain_id="research")),
            WorkPlanItemIn(
                ref="post", title="Historical metrics post", kind="post",
                primary_board=PlanBoardRef(board_id="posts", domain_id="posts")),
        ],
        edges=[
            WorkPlanEdgeIn(from_ref="proj", to_ref="feas", relation="parent_of"),
            WorkPlanEdgeIn(from_ref="proj", to_ref="lic", relation="parent_of"),
            WorkPlanEdgeIn(from_ref="proj", to_ref="post", relation="parent_of"),
            WorkPlanEdgeIn(from_ref="lic", to_ref="feas", relation="blocks",
                           reason="confirm rights before implementation"),
            WorkPlanEdgeIn(from_ref="feas", to_ref="post", relation="informs"),
        ])


def test_preview_has_zero_side_effects():
    planner, real = _planner()
    receipt = planner.preview(_sample_plan())
    assert receipt.preview is True
    assert len(receipt.created) == 4
    # NOTHING was persisted to the durable graph
    assert real.list_items() == []
    assert real.graph().edges == []
    # provisional ids signal not-yet-real
    assert all(r.work_item.work_item_id.startswith("box-")
               for r in receipt.created)


def test_commit_creates_one_item_per_plan_item_with_placements_and_edges():
    planner, real = _planner()
    receipt = planner.commit(_sample_plan())
    assert receipt.preview is False
    assert len(receipt.created) == 4
    # exactly four canonical items — NOT one-per-board
    assert len(real.list_items()) == 4

    by_title = {r.work_item.title: r for r in receipt.created}
    feas = by_title["CV feasibility"]
    # same deliverable, two boards → one item, primary + secondary placement
    assert feas.primary_placement.board_id == "basketball_cv"
    assert feas.primary_placement.is_primary is True
    assert [p.board_id for p in feas.secondary_placements] == ["research"]
    assert feas.work_item.primary_board_id == "basketball_cv"
    # feasibility has two incoming edges (parent_of from proj, blocks from lic)
    # and one outgoing (informs the post)
    assert {e.relation for e in feas.incoming_edges} == {"parent_of", "blocks"}
    assert {e.relation for e in feas.outgoing_edges} == {"informs"}


def test_commit_receipt_links_are_backend_generated_and_navigable():
    planner, _ = _planner()
    receipt = planner.commit(_sample_plan())
    feas = next(r for r in receipt.created if r.work_item.title == "CV feasibility")
    kinds = {lk.kind for lk in feas.links}
    # every created task carries a graph link + a board link + its source chat
    assert {"graph", "board", "chat"} <= kinds
    graph_link = next(lk for lk in feas.links if lk.kind == "graph")
    assert graph_link.href == f"?view=work-map&work={feas.work_item.work_item_id}"


def test_commit_is_atomic_on_a_blocking_cycle():
    planner, real = _planner()
    bad = WorkPlanIn(conversation_id="c1", items=[
        WorkPlanItemIn(ref="a", title="A"),
        WorkPlanItemIn(ref="b", title="B")],
        edges=[
            WorkPlanEdgeIn(from_ref="a", to_ref="b", relation="blocks"),
            WorkPlanEdgeIn(from_ref="b", to_ref="a", relation="blocks")])  # cycle
    with pytest.raises(WorkGraphError, match="cycle"):
        planner.commit(bad)
    # the whole commit rolled forward nothing — no partial A/B written
    assert real.list_items() == []


def test_commit_can_reference_an_existing_work_item_in_an_edge():
    planner, real = _planner()
    existing = real.create_item("already here", kind="feature")
    plan = WorkPlanIn(conversation_id="c1", items=[
        WorkPlanItemIn(ref="new", title="depends on existing")],
        edges=[WorkPlanEdgeIn(from_ref="new", to_ref=existing.work_item_id,
                              relation="blocks")])
    receipt = planner.commit(plan)
    edge = receipt.created[0].outgoing_edges[0]
    assert edge.to_work_item_id == existing.work_item_id
    assert len(real.list_items()) == 2


def test_commit_unknown_edge_ref_is_keyerror_and_writes_nothing():
    planner, real = _planner()
    plan = WorkPlanIn(conversation_id="c1", items=[
        WorkPlanItemIn(ref="a", title="A")],
        edges=[WorkPlanEdgeIn(from_ref="a", to_ref="ghost-id", relation="blocks")])
    with pytest.raises(KeyError):
        planner.commit(plan)
    assert real.list_items() == []          # atomic: sandbox caught it first


def test_item_with_no_board_warns_but_still_creates():
    planner, real = _planner()
    plan = WorkPlanIn(conversation_id="c1", items=[
        WorkPlanItemIn(ref="a", title="homeless idea")])
    receipt = planner.commit(plan)
    assert receipt.created[0].primary_placement is None
    assert any("Universal Inbox" in w for w in receipt.created[0].warnings)
    assert len(real.list_items()) == 1


def test_planning_creates_no_mission():
    planner, real = _planner()
    planner.commit(_sample_plan())
    # planning never touches missions — the wall stays intact
    assert all(i.mission_id is None for i in real.list_items())


def test_empty_and_duplicate_ref_plans_are_rejected():
    planner, _ = _planner()
    with pytest.raises(ChatPlanError, match="at least one item"):
        planner.commit(WorkPlanIn(conversation_id="c1", items=[]))
    with pytest.raises(ChatPlanError, match="duplicate item ref"):
        planner.commit(WorkPlanIn(conversation_id="c1", items=[
            WorkPlanItemIn(ref="a", title="one"),
            WorkPlanItemIn(ref="a", title="two")]))
