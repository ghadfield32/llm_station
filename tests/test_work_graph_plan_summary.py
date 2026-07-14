"""summarize_plan — the deterministic "this will create …" confirmation gate.
Pure counting over a proposed plan: items by kind, primary/secondary placements,
distinct boards, items with no board, and edges by relation (blocking subset
called out). No side effects, no thresholds.
"""
from __future__ import annotations

from command_center.work_graph import (
    PlanBoardRef,
    WorkPlanEdgeIn,
    WorkPlanIn,
    WorkPlanItemIn,
    summarize_plan,
)


def _sample() -> WorkPlanIn:
    cv = PlanBoardRef(board_id="basketball_cv", domain_id="basketball_cv")
    research = PlanBoardRef(board_id="research", domain_id="research")
    posts = PlanBoardRef(board_id="posts", domain_id="posts")
    return WorkPlanIn(
        conversation_id="c1",
        items=[
            WorkPlanItemIn(ref="proj", title="Project", kind="project"),
            WorkPlanItemIn(ref="feas", title="Feasibility", kind="research",
                           primary_board=cv, secondary_boards=[research]),
            WorkPlanItemIn(ref="lic", title="Licensing", kind="research",
                           primary_board=research),
            WorkPlanItemIn(ref="post", title="Post", kind="post",
                           primary_board=posts),
        ],
        edges=[
            WorkPlanEdgeIn(from_ref="proj", to_ref="feas", relation="parent_of"),
            WorkPlanEdgeIn(from_ref="proj", to_ref="lic", relation="parent_of"),
            WorkPlanEdgeIn(from_ref="proj", to_ref="post", relation="parent_of"),
            WorkPlanEdgeIn(from_ref="lic", to_ref="feas", relation="blocks"),
            WorkPlanEdgeIn(from_ref="feas", to_ref="post", relation="informs"),
        ])


def test_summary_counts_items_placements_and_edges():
    s = summarize_plan(_sample())
    assert s.item_count == 4
    assert s.items_by_kind == {"project": 1, "research": 2, "post": 1}
    # placements: feas(primary+1 secondary), lic(primary), post(primary); proj none
    assert s.primary_placement_count == 3
    assert s.secondary_placement_count == 1
    assert s.placement_count == 4
    assert set(s.boards) == {"basketball_cv", "research", "posts"}
    assert s.items_without_board == 1                       # the project
    assert any("Universal Inbox" in w for w in s.warnings)


def test_summary_edges_by_relation_and_blocking_subset():
    s = summarize_plan(_sample())
    assert s.edge_count == 5
    assert s.edges_by_relation == {"parent_of": 3, "blocks": 1, "informs": 1}
    # parent_of + blocks are acyclic/blocking; informs is not
    assert s.blocking_edge_count == 4


def test_empty_plan_is_all_zero_no_warnings():
    s = summarize_plan(WorkPlanIn(conversation_id="c1", items=[]))
    assert s.item_count == 0 and s.placement_count == 0 and s.edge_count == 0
    assert s.items_by_kind == {} and s.edges_by_relation == {}
    assert s.warnings == []


def test_router_proposal_carries_a_summary():
    from command_center.intake import split_bulk_list
    from command_center.work_graph import WorkRouter
    prop = WorkRouter(split=split_bulk_list).route("- a\n- b\n- c")
    assert prop.summary is not None
    assert prop.summary.item_count == 3
    # no calibrated boards → all three land board-less (Inbox) in the summary
    assert prop.summary.items_without_board == 3
