"""In-memory WorkGraphStore. The durable Ledger-backed sibling is the immediate
follow-up (Phase C-2), implementing the same surface, so the service/API never
care which backend they hold (mirrors the intake/usage subsystems).

Placements and edges are soft-removed (removed_at set) — the canonical WorkItem
and its history are never destroyed by removing a projection or a link.
"""
from __future__ import annotations

from .schemas import WorkEdge, WorkEvent, WorkItem, WorkPlacement


class InMemoryWorkGraphStore:
    def __init__(self) -> None:
        self._items: dict[str, WorkItem] = {}
        self._placements: dict[str, WorkPlacement] = {}
        self._edges: dict[str, WorkEdge] = {}
        self._events: dict[str, list[WorkEvent]] = {}
        self._order: list[str] = []

    # ---- items ----
    def add_item(self, item: WorkItem) -> None:
        if item.work_item_id in self._items:
            raise KeyError(f"work item {item.work_item_id} already exists")
        self._items[item.work_item_id] = item
        self._events[item.work_item_id] = []
        self._order.append(item.work_item_id)

    def get_item(self, work_item_id: str) -> WorkItem:
        item = self._items.get(work_item_id)
        if item is None:
            raise KeyError(f"no such work item: {work_item_id}")
        return item

    def put_item(self, item: WorkItem) -> None:
        self._items[item.work_item_id] = item

    def list_items(self) -> list[WorkItem]:
        return [self._items[i] for i in self._order]

    # ---- placements ----
    def add_placement(self, placement: WorkPlacement) -> None:
        self._placements[placement.placement_id] = placement

    def get_placement(self, placement_id: str) -> WorkPlacement:
        p = self._placements.get(placement_id)
        if p is None:
            raise KeyError(f"no such placement: {placement_id}")
        return p

    def put_placement(self, placement: WorkPlacement) -> None:
        self._placements[placement.placement_id] = placement

    def placements_for(self, work_item_id: str, *, active_only: bool = True) -> list[WorkPlacement]:
        out = [p for p in self._placements.values() if p.work_item_id == work_item_id]
        if active_only:
            out = [p for p in out if p.removed_at is None]
        return out

    def placements_on_board(self, board_id: str, *, active_only: bool = True) -> list[WorkPlacement]:
        out = [p for p in self._placements.values() if p.board_id == board_id]
        if active_only:
            out = [p for p in out if p.removed_at is None]
        return out

    def list_placements(self, *, active_only: bool = True) -> list[WorkPlacement]:
        out = list(self._placements.values())
        if active_only:
            out = [p for p in out if p.removed_at is None]
        return out

    # ---- edges ----
    def add_edge(self, edge: WorkEdge) -> None:
        self._edges[edge.edge_id] = edge

    def get_edge(self, edge_id: str) -> WorkEdge:
        e = self._edges.get(edge_id)
        if e is None:
            raise KeyError(f"no such edge: {edge_id}")
        return e

    def put_edge(self, edge: WorkEdge) -> None:
        self._edges[edge.edge_id] = edge

    def edges(self, *, active_only: bool = True) -> list[WorkEdge]:
        out = list(self._edges.values())
        if active_only:
            out = [e for e in out if e.removed_at is None]
        return out

    # ---- events ----
    def append_event(self, event: WorkEvent) -> None:
        self._events.setdefault(event.work_item_id, []).append(event)

    def events(self, work_item_id: str) -> list[WorkEvent]:
        return list(self._events.get(work_item_id, []))
