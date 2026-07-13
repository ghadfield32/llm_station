"""Stable work-item permalinks: WorkGraphService.resolve() picks the ONE
canonical landing target (primary board > any active board > Work Map) and
returns it alongside the full navigation receipt. The backend owns the
destination — the browser follows target.href verbatim. Planning only, no mission.
"""
from __future__ import annotations

import itertools

import pytest

from command_center.work_graph import (
    InMemoryWorkGraphStore,
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


def test_resolve_targets_the_primary_board():
    svc = _service()
    item = svc.create_item("ship the resolver", kind="feature")
    svc.add_placement(item.work_item_id, "board-eng", "engineering")   # secondary
    svc.add_placement(item.work_item_id, "board-home", "life", is_primary=True)
    res = svc.resolve(item.work_item_id)
    assert res.work_item_id == item.work_item_id
    assert res.title == "ship the resolver"
    assert res.target.kind == "board"
    assert res.target.resource_id == "board-home"      # the PRIMARY, not the first
    assert res.target.relation == "primary"
    assert res.target.href == "?view=domains&domain=life&work=" + item.work_item_id


def test_resolve_falls_back_to_any_active_board_when_no_primary():
    svc = _service()
    item = svc.create_item("no primary yet")
    svc.add_placement(item.work_item_id, "board-eng", "engineering")   # secondary only
    res = svc.resolve(item.work_item_id)
    assert res.target.kind == "board"
    assert res.target.resource_id == "board-eng"
    assert res.target.relation == "secondary"


def test_resolve_falls_back_to_work_map_when_no_placements():
    svc = _service()
    item = svc.create_item("homeless item", conversation_id="chat-3")
    res = svc.resolve(item.work_item_id)
    assert res.target.kind == "graph"                  # the Work Map
    assert res.target.href == "?view=work-map&work=" + item.work_item_id
    # the full receipt still travels (graph self-link + the source chat)
    assert {lk.kind for lk in res.links} >= {"graph", "chat"}


def test_resolve_ignores_a_soft_removed_primary_placement():
    svc = _service()
    item = svc.create_item("re-homed")
    p = svc.add_placement(item.work_item_id, "board-x", "x", is_primary=True)
    svc.remove_placement(p.placement_id)               # primary projection removed
    res = svc.resolve(item.work_item_id)
    # no ACTIVE placement remains → the permalink resolves to the Work Map, not a
    # dead board reference
    assert res.target.kind == "graph"
    assert res.target.href == "?view=work-map&work=" + item.work_item_id


def test_resolve_unknown_item_is_keyerror():
    with pytest.raises(KeyError):
        _service().resolve("never-seen")
