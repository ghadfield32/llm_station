"""Canonical work-graph correctness + safety. One durable WorkItem projected onto
many boards (never duplicated cards); typed edges with a cycle policy (blocking/
structural relations acyclic, informational relations may cycle); removing a
projection or completing from a secondary board never contradicts the ONE
canonical status; links are backend-generated. Planning only — never a mission.
"""
from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor

import pytest

from command_center.work_graph import (
    InMemoryWorkGraphStore,
    WorkEvent,
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


def test_exact_placement_retry_is_idempotent_but_conflicting_retry_is_blocked():
    svc = _service()
    w = svc.create_item("x").work_item_id
    first = svc.add_placement(
        w, "tasks", "tasks", is_primary=True, card_component="generic_task")
    replay = svc.add_placement(
        w, "tasks", "tasks", is_primary=True, card_component="generic_task")
    assert replay.placement_id == first.placement_id
    assert len(svc._store.placements_for(w)) == 1
    with pytest.raises(WorkGraphError, match="different active placement"):
        svc.add_placement(
            w, "tasks", "tasks", is_primary=False,
            card_component="generic_task")


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


def test_old_primary_removal_retry_keeps_new_same_board_domain_primary():
    svc = _service()
    work_item_id = svc.create_item("same board replacement").work_item_id
    old = svc.add_placement(
        work_item_id, "shared-board", "domain-one", is_primary=True,
    )
    svc.remove_placement(old.placement_id)
    current = svc.add_placement(
        work_item_id, "shared-board", "domain-two", is_primary=True,
    )

    svc.remove_placement(old.placement_id)

    assert svc.get_item(work_item_id).primary_board_id == "shared-board"
    assert svc._store.get_placement(current.placement_id).removed_at is None


def test_invalid_canonical_status_is_rejected_before_mutation():
    svc = _service()
    item = svc.create_item("valid status only")
    before = list(svc._store.events(item.work_item_id))
    with pytest.raises(WorkGraphError, match="canonical status"):
        svc.set_status(item.work_item_id, "invented")
    assert svc.get_item(item.work_item_id).canonical_status == "backlog"
    assert svc._store.events(item.work_item_id) == before


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


def test_description_edit_is_atomic_audited_and_exact_retry_is_idempotent():
    svc = _service()
    item = svc.create_item("organize me", description="first")
    updated = svc.update_description(
        item.work_item_id, "organized",
        expected_updated_at=item.updated_at,
        expected_description="first",
    )
    replay = svc.update_description(
        item.work_item_id, "organized",
        expected_updated_at=item.updated_at,
        expected_description="first",
    )
    assert replay == updated
    events = [event for event in svc._store.events(item.work_item_id)
              if event.kind == "description_edited"]
    assert len(events) == 1
    assert events[0].payload == {
        "previous_description": "first",
        "description": "organized",
        "expected_updated_at": item.updated_at,
    }


def test_description_edit_rejects_divergent_stale_writer_without_event():
    svc = _service()
    item = svc.create_item("organize me", description="first")
    svc.update_description(
        item.work_item_id, "winner",
        expected_updated_at=item.updated_at,
        expected_description="first",
    )
    with pytest.raises(WorkGraphError, match="refresh its story"):
        svc.update_description(
            item.work_item_id, "loser",
            expected_updated_at=item.updated_at,
            expected_description="first",
        )
    assert svc.get_item(item.work_item_id).description == "winner"
    assert len([event for event in svc._store.events(item.work_item_id)
                if event.kind == "description_edited"]) == 1


def test_generic_field_update_cannot_bypass_description_audit_boundary():
    svc = _service()
    item = svc.create_item("audit boundary", description="before")
    with pytest.raises(ValueError, match="description"):
        svc._store.update_item_fields(
            item.work_item_id, fields={"description": "unaudited"},
        )
    assert svc.get_item(item.work_item_id).description == "before"


def test_invalid_atomic_event_is_rejected_before_item_mutation():
    svc = _service()
    item = svc.create_item("validate before write")
    with pytest.raises(ValueError, match="another item"):
        svc._store.update_item_fields(
            item.work_item_id,
            fields={"canonical_status": "in_progress"},
            event=WorkEvent(
                work_item_id="W-other",
                ts="2026-07-13T00:00:30+00:00",
                kind="status",
                payload={"status": "in_progress"},
            ),
        )
    assert svc.get_item(item.work_item_id).canonical_status == "backlog"


def test_concurrent_identical_description_retries_append_one_event():
    svc = _service()
    item = svc.create_item("organize me", description="first")

    def update():
        return svc.update_description(
            item.work_item_id, "same",
            expected_updated_at=item.updated_at,
            expected_description="first",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _index: update(), range(4)))
    assert {result.description for result in results} == {"same"}
    assert len([event for event in svc._store.events(item.work_item_id)
                if event.kind == "description_edited"]) == 1


def test_description_status_race_never_reverts_an_audited_edit():
    svc = _service()
    for index in range(20):
        item = svc.create_item(f"race status {index}", description="before")

        def edit():
            try:
                svc.update_description(
                    item.work_item_id, "after",
                    expected_updated_at=item.updated_at,
                    expected_description="before",
                )
            except WorkGraphError:
                pass

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda fn: fn(), (edit, lambda: svc.set_status(
                item.work_item_id, "in_progress"))))
        current = svc.get_item(item.work_item_id)
        edited = any(
            event.kind == "description_edited"
            for event in svc._store.events(item.work_item_id)
        )
        assert current.canonical_status == "in_progress"
        assert current.description == ("after" if edited else "before")


def test_description_primary_placement_race_never_reverts_an_audited_edit():
    svc = _service()
    for index in range(20):
        item = svc.create_item(f"race placement {index}", description="before")

        def edit():
            try:
                svc.update_description(
                    item.work_item_id, "after",
                    expected_updated_at=item.updated_at,
                    expected_description="before",
                )
            except WorkGraphError:
                pass

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda fn: fn(), (
                edit,
                lambda: svc.add_placement(
                    item.work_item_id, f"board-{index}", f"domain-{index}",
                    is_primary=True,
                ),
            )))
        current = svc.get_item(item.work_item_id)
        edited = any(
            event.kind == "description_edited"
            for event in svc._store.events(item.work_item_id)
        )
        assert current.primary_board_id == f"board-{index}"
        assert current.description == ("after" if edited else "before")


def test_graph_neighbourhood_by_depth():
    svc = _service()
    a, b, c = (svc.create_item(t).work_item_id for t in ("a", "b", "c"))
    svc.add_edge(a, b, "related_to")
    svc.add_edge(b, c, "related_to")
    one_hop = svc.graph(a, depth=1)
    assert {i.work_item_id for i in one_hop.items} == {a, b}
    two_hop = svc.graph(a, depth=2)
    assert {i.work_item_id for i in two_hop.items} == {a, b, c}
