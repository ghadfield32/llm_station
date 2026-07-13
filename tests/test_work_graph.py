"""Canonical work-graph correctness + safety. One durable WorkItem projected onto
many boards (never duplicated cards); typed edges with a cycle policy (blocking/
structural relations acyclic, informational relations may cycle); removing a
projection or completing from a secondary board never contradicts the ONE
canonical status; links are backend-generated. Planning only — never a mission.
"""
from __future__ import annotations

import itertools

import pytest

from command_center.work_graph import (
    InMemoryWorkGraphStore,
    WorkGraphError,
    WorkGraphService,
)


def _service() -> WorkGraphService:
    ticks = itertools.count(1)
    counters: dict[str, itertools.count] = {}

    def make_id(prefix: str) -> str:
        counters.setdefault(prefix, itertools.count(1))
        return f"{prefix}-{next(counters[prefix])}"

    return WorkGraphService(
        InMemoryWorkGraphStore(),
        clock=lambda: f"2026-07-13T00:00:{next(ticks):02d}+00:00",
        id_factory=make_id)


# ---- one item, many placements -------------------------------------------------

def test_one_work_item_multiple_placements():
    svc = _service()
    item = svc.create_item("CV feasibility", kind="research")
    svc.add_placement(item.work_item_id, "basketball_cv", "basketball_cv",
                      is_primary=True)
    svc.add_placement(item.work_item_id, "research", "research")
    placements = svc._store.placements_for(item.work_item_id)
    # ONE item, TWO placements — not two tasks
    assert len(placements) == 2
    assert {p.board_id for p in placements} == {"basketball_cv", "research"}
    assert svc.get_item(item.work_item_id).primary_board_id == "basketball_cv"


def test_primary_placement_is_unique():
    svc = _service()
    w = svc.create_item("x").work_item_id
    svc.add_placement(w, "a", "a", is_primary=True)
    with pytest.raises(WorkGraphError, match="already has a primary"):
        svc.add_placement(w, "b", "b", is_primary=True)


# ---- cycle policy --------------------------------------------------------------

def test_blocking_cycle_rejected():
    svc = _service()
    a, b, c = (svc.create_item(t).work_item_id for t in ("a", "b", "c"))
    svc.add_edge(a, b, "blocks")
    svc.add_edge(b, c, "blocks")
    with pytest.raises(WorkGraphError, match="cycle"):
        svc.add_edge(c, a, "blocks")           # A->B->C->A rejected


def test_parent_cycle_rejected():
    svc = _service()
    a, b = svc.create_item("proj").work_item_id, svc.create_item("child").work_item_id
    svc.add_edge(a, b, "parent_of")
    with pytest.raises(WorkGraphError, match="cycle"):
        svc.add_edge(b, a, "parent_of")


def test_self_blocking_edge_rejected():
    svc = _service()
    a = svc.create_item("a").work_item_id
    with pytest.raises(WorkGraphError, match="itself"):
        svc.add_edge(a, a, "blocks")


def test_related_cycle_allowed():
    svc = _service()
    a, b = svc.create_item("a").work_item_id, svc.create_item("b").work_item_id
    svc.add_edge(a, b, "related_to")
    svc.add_edge(b, a, "related_to")           # informational cycle is fine
    edges = svc._store.edges()
    assert len(edges) == 2
    assert all(e.blocking is False for e in edges)


def test_cross_relation_blocking_cycle_rejected():
    # a blocks b, b parent_of a would still close a structural cycle
    svc = _service()
    a, b = svc.create_item("a").work_item_id, svc.create_item("b").work_item_id
    svc.add_edge(a, b, "blocks")
    with pytest.raises(WorkGraphError, match="cycle"):
        svc.add_edge(b, a, "parent_of")


# ---- removing a projection / shared status -------------------------------------

def test_remove_projection_preserves_the_work_item():
    svc = _service()
    w = svc.create_item("keep me").work_item_id
    p = svc.add_placement(w, "a", "a", is_primary=True)
    svc.remove_placement(p.placement_id)
    # the placement is gone; the canonical item is NOT
    assert svc._store.placements_for(w) == []
    assert svc.get_item(w).title == "keep me"
    assert svc.get_item(w).primary_board_id is None   # primary cleared, item intact


def test_status_is_canonical_across_all_placements():
    svc = _service()
    w = svc.create_item("shared").work_item_id
    svc.add_placement(w, "posts", "posts", is_primary=True)
    svc.add_placement(w, "research", "research")
    # completing from ANY board transitions the ONE canonical status
    svc.set_status(w, "done")
    assert svc.get_item(w).canonical_status == "done"
    # placements carry no independent execution status to contradict it
    for p in svc._store.placements_for(w):
        assert not hasattr(p, "canonical_status")


# ---- backend-generated links + planning-only -----------------------------------

def test_links_are_backend_generated():
    svc = _service()
    item = svc.create_item("idea", conversation_id="chat-9", mission_id="T-1")
    svc.add_placement(item.work_item_id, "basketball_cv", "basketball_cv",
                      is_primary=True)
    links = svc.links_for(item.work_item_id)
    kinds = {lk.kind for lk in links}
    assert {"graph", "board", "chat", "mission"} <= kinds
    # every link has a backend href (the browser renders verbatim)
    assert all(lk.href.startswith("?") for lk in links)
    graph = next(lk for lk in links if lk.kind == "graph")
    assert f"work={item.work_item_id}" in graph.href


def test_creating_work_never_starts_a_mission():
    svc = _service()
    item = svc.create_item("do a thing")
    # a fresh work item is planning, not execution — no mission attached, backlog
    assert item.mission_id is None
    assert item.canonical_status == "backlog"


def test_graph_neighbourhood_by_depth():
    svc = _service()
    a, b, c = (svc.create_item(t).work_item_id for t in ("a", "b", "c"))
    svc.add_edge(a, b, "related_to")
    svc.add_edge(b, c, "related_to")
    one_hop = svc.graph(a, depth=1)
    assert {i.work_item_id for i in one_hop.items} == {a, b}
    two_hop = svc.graph(a, depth=2)
    assert {i.work_item_id for i in two_hop.items} == {a, b, c}
