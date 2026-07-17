"""In-memory WorkGraphStore. The durable Ledger-backed sibling is the immediate
follow-up (Phase C-2), implementing the same surface, so the service/API never
care which backend they hold (mirrors the intake/usage subsystems).

Placements and edges are soft-removed (removed_at set) — the canonical WorkItem
and its history are never destroyed by removing a projection or a link.
"""
from __future__ import annotations

import threading

from .schemas import WorkEdge, WorkEvent, WorkItem, WorkPlacement


class ConcurrentWorkItemUpdate(RuntimeError):
    """The caller's compare-and-swap base is no longer current."""


class WorkGraphIntegrityConflict(RuntimeError):
    """An atomic store operation would violate a graph invariant."""


class InMemoryWorkGraphStore:
    def __init__(self) -> None:
        self._items: dict[str, WorkItem] = {}
        self._placements: dict[str, WorkPlacement] = {}
        self._edges: dict[str, WorkEdge] = {}
        self._events: dict[str, list[WorkEvent]] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    # ---- items ----
    def add_item(self, item: WorkItem) -> None:
        with self._lock:
            if item.work_item_id in self._items:
                raise KeyError(f"work item {item.work_item_id} already exists")
            self._items[item.work_item_id] = item
            self._events[item.work_item_id] = []
            self._order.append(item.work_item_id)

    def add_item_with_event(self, item: WorkItem, event: WorkEvent) -> None:
        """Create the canonical row and its first history event indivisibly."""
        if event.work_item_id != item.work_item_id:
            raise ValueError("WorkItem creation event belongs to another item")
        with self._lock:
            if item.work_item_id in self._items:
                raise KeyError(f"work item {item.work_item_id} already exists")
            self._items[item.work_item_id] = item
            self._events[item.work_item_id] = [event]
            self._order.append(item.work_item_id)

    def get_item(self, work_item_id: str) -> WorkItem:
        with self._lock:
            item = self._items.get(work_item_id)
            if item is None:
                raise KeyError(f"no such work item: {work_item_id}")
            return item

    def update_item_fields(
        self, work_item_id: str, *, fields: dict,
        event: WorkEvent | None = None,
    ) -> WorkItem:
        """Atomically update only named WorkItem fields and optionally its event.

        A caller can no longer replace a whole row copied from a stale read. That
        is the essential concurrency boundary: a status or placement update can
        never restore an older description committed by the description CAS.
        """
        forbidden = {"work_item_id", "created_at", "description"} & set(fields)
        if forbidden:
            raise ValueError(
                "immutable/audited WorkItem fields cannot be updated through "
                f"update_item_fields: {sorted(forbidden)}"
            )
        if event is None:
            raise ValueError("WorkItem field updates require an atomic audit event")
        if "canonical_status" in fields and (
            event.kind != "status"
            or event.payload.get("status") != fields["canonical_status"]
        ):
            raise ValueError("canonical status update and audit event must match")
        with self._lock:
            current = self.get_item(work_item_id)
            if event.work_item_id != work_item_id:
                # Validate the complete atomic request before either authority
                # changes. A bad audit event must never leave a row mutation.
                raise ValueError("WorkItem update event belongs to another item")
            updated = current.model_copy(update=fields)
            self._items[work_item_id] = updated
            self._events.setdefault(work_item_id, []).append(event)
            return updated

    def compare_and_set_description(
        self, work_item_id: str, *, expected_updated_at: str,
        expected_description: str, description: str, updated_at: str,
    ) -> tuple[WorkItem, bool]:
        """Atomically replace the organized description and append its story event.

        An exact retry is recognized from the stored event, not from a guessed
        value. Divergent stale writers fail without changing either authority.
        """
        with self._lock:
            current = self.get_item(work_item_id)
            payload = {
                "previous_description": expected_description,
                "description": description,
                "expected_updated_at": expected_updated_at,
            }
            if current.description == description:
                exact_retry = any(
                    event.kind == "description_edited" and event.payload == payload
                    for event in self._events.get(work_item_id, [])
                )
                if exact_retry or (
                    current.updated_at == expected_updated_at
                    and current.description == expected_description
                ):
                    return current, False
            if (
                current.updated_at != expected_updated_at
                or current.description != expected_description
            ):
                raise ConcurrentWorkItemUpdate(
                    "work item changed; refresh its story before editing the description"
                )
            updated = current.model_copy(update={
                "description": description,
                "updated_at": updated_at,
            })
            self._items[work_item_id] = updated
            self._events.setdefault(work_item_id, []).append(WorkEvent(
                work_item_id=work_item_id,
                ts=updated_at,
                kind="description_edited",
                payload=payload,
            ))
            return updated, True

    def list_items(self) -> list[WorkItem]:
        with self._lock:
            return [self._items[i] for i in self._order]

    # ---- placements ----
    def add_placement(self, placement: WorkPlacement) -> None:
        with self._lock:
            self._placements[placement.placement_id] = placement

    def add_placement_with_event(
        self, placement: WorkPlacement, event: WorkEvent,
    ) -> WorkPlacement:
        """Enforce target/primary uniqueness and commit projection + story together."""
        if event.work_item_id != placement.work_item_id:
            raise ValueError("placement event belongs to another item")
        with self._lock:
            item = self.get_item(placement.work_item_id)
            active = [
                candidate for candidate in self._placements.values()
                if candidate.work_item_id == placement.work_item_id
                and candidate.removed_at is None
            ]
            if any(
                candidate.board_id == placement.board_id
                and candidate.domain_id == placement.domain_id
                for candidate in active
            ):
                raise WorkGraphIntegrityConflict(
                    "work item already has an active placement on that board/domain"
                )
            if placement.is_primary and any(candidate.is_primary for candidate in active):
                raise WorkGraphIntegrityConflict(
                    "work item already has an active primary placement"
                )
            self._placements[placement.placement_id] = placement
            if placement.is_primary:
                self._items[item.work_item_id] = item.model_copy(update={
                    "primary_board_id": placement.board_id,
                    "updated_at": event.ts,
                })
            self._events.setdefault(item.work_item_id, []).append(event)
            return placement

    def remove_placement_with_event(
        self, placement_id: str, *, removed_at: str,
    ) -> WorkPlacement:
        """Soft-remove, repair canonical primary state, and retain one exact event."""
        with self._lock:
            placement = self.get_placement(placement_id)
            effective_at = placement.removed_at or removed_at
            if placement.removed_at is None:
                placement = placement.model_copy(update={"removed_at": effective_at})
                self._placements[placement_id] = placement
            item = self.get_item(placement.work_item_id)
            active_primary = next((
                candidate for candidate in self._placements.values()
                if candidate.work_item_id == placement.work_item_id
                and candidate.is_primary
                and candidate.removed_at is None
            ), None)
            expected_primary_board = (
                active_primary.board_id if active_primary is not None else None
            )
            if (
                placement.is_primary
                and item.primary_board_id != expected_primary_board
            ):
                self._items[item.work_item_id] = item.model_copy(update={
                    "primary_board_id": expected_primary_board,
                    "updated_at": effective_at,
                })
            payload = {
                "placement_id": placement.placement_id,
                "board_id": placement.board_id,
                "domain_id": placement.domain_id,
                "is_primary": placement.is_primary,
            }
            if not any(
                candidate.kind == "placement_removed"
                and candidate.payload.get("placement_id") == placement_id
                for candidate in self._events.get(placement.work_item_id, [])
            ):
                self._events.setdefault(placement.work_item_id, []).append(WorkEvent(
                    work_item_id=placement.work_item_id,
                    ts=effective_at,
                    kind="placement_removed",
                    payload=payload,
                ))
            return placement

    def repair_placement_with_event(
        self, placement: WorkPlacement, event: WorkEvent,
    ) -> WorkPlacement:
        """Reconcile a legacy active row with its canonical primary and add event."""
        if event.work_item_id != placement.work_item_id:
            raise ValueError("placement event belongs to another item")
        with self._lock:
            stored = self.get_placement(placement.placement_id)
            if stored != placement or stored.removed_at is not None:
                raise WorkGraphIntegrityConflict(
                    "placement changed while repairing its audit boundary"
                )
            item = self.get_item(stored.work_item_id)
            if stored.is_primary:
                other = next((
                    candidate for candidate in self._placements.values()
                    if candidate.work_item_id == stored.work_item_id
                    and candidate.is_primary and candidate.removed_at is None
                    and candidate.placement_id != stored.placement_id
                ), None)
                if other is not None:
                    raise WorkGraphIntegrityConflict(
                        "work item has conflicting active primary placements"
                    )
                if item.primary_board_id != stored.board_id:
                    self._items[item.work_item_id] = item.model_copy(update={
                        "primary_board_id": stored.board_id,
                        "updated_at": event.ts,
                    })
            if not any(
                candidate.kind == "placement_added"
                and candidate.payload.get("placement_id") == stored.placement_id
                for candidate in self._events.get(stored.work_item_id, [])
            ):
                self._events.setdefault(stored.work_item_id, []).append(event)
            return stored

    def get_placement(self, placement_id: str) -> WorkPlacement:
        with self._lock:
            p = self._placements.get(placement_id)
            if p is None:
                raise KeyError(f"no such placement: {placement_id}")
            return p

    def put_placement(self, placement: WorkPlacement) -> None:
        with self._lock:
            self._placements[placement.placement_id] = placement

    def placements_for(self, work_item_id: str, *, active_only: bool = True) -> list[WorkPlacement]:
        with self._lock:
            out = [p for p in self._placements.values() if p.work_item_id == work_item_id]
            if active_only:
                out = [p for p in out if p.removed_at is None]
            return out

    def placements_on_board(self, board_id: str, *, active_only: bool = True) -> list[WorkPlacement]:
        with self._lock:
            out = [p for p in self._placements.values() if p.board_id == board_id]
            if active_only:
                out = [p for p in out if p.removed_at is None]
            return out

    def list_placements(self, *, active_only: bool = True) -> list[WorkPlacement]:
        with self._lock:
            out = list(self._placements.values())
            if active_only:
                out = [p for p in out if p.removed_at is None]
            return out

    # ---- edges ----
    def add_edge(self, edge: WorkEdge) -> None:
        with self._lock:
            self._edges[edge.edge_id] = edge

    def add_edge_with_event(self, edge: WorkEdge, event: WorkEvent) -> WorkEdge:
        """Check the current graph and append an edge + source event under one lock."""
        if event.work_item_id != edge.from_work_item_id:
            raise ValueError("edge event belongs to another item")
        with self._lock:
            self.get_item(edge.from_work_item_id)
            self.get_item(edge.to_work_item_id)
            if edge.blocking and edge.from_work_item_id == edge.to_work_item_id:
                raise WorkGraphIntegrityConflict("a blocking edge cannot point at itself")
            if edge.blocking:
                adjacency: dict[str, list[str]] = {}
                for candidate in self._edges.values():
                    if candidate.removed_at is None and candidate.blocking:
                        adjacency.setdefault(candidate.from_work_item_id, []).append(
                            candidate.to_work_item_id
                        )
                seen: set[str] = set()
                stack = [edge.to_work_item_id]
                while stack:
                    node = stack.pop()
                    if node == edge.from_work_item_id:
                        raise WorkGraphIntegrityConflict(
                            "edge would create a cycle among blocking/structural relations"
                        )
                    if node in seen:
                        continue
                    seen.add(node)
                    stack.extend(adjacency.get(node, []))
            self._edges[edge.edge_id] = edge
            self._events.setdefault(edge.from_work_item_id, []).append(event)
            return edge

    def remove_edge_with_event(self, edge_id: str, *, removed_at: str) -> WorkEdge:
        with self._lock:
            edge = self.get_edge(edge_id)
            effective_at = edge.removed_at or removed_at
            if edge.removed_at is None:
                edge = edge.model_copy(update={"removed_at": effective_at})
                self._edges[edge_id] = edge
            if not any(
                candidate.kind == "edge_removed"
                and candidate.payload.get("edge_id") == edge_id
                for candidate in self._events.get(edge.from_work_item_id, [])
            ):
                self._events.setdefault(edge.from_work_item_id, []).append(WorkEvent(
                    work_item_id=edge.from_work_item_id,
                    ts=effective_at,
                    kind="edge_removed",
                    payload={
                        "edge_id": edge.edge_id,
                        "to": edge.to_work_item_id,
                        "relation": edge.relation,
                    },
                ))
            return edge

    def get_edge(self, edge_id: str) -> WorkEdge:
        with self._lock:
            e = self._edges.get(edge_id)
            if e is None:
                raise KeyError(f"no such edge: {edge_id}")
            return e

    def put_edge(self, edge: WorkEdge) -> None:
        with self._lock:
            self._edges[edge.edge_id] = edge

    def edges(self, *, active_only: bool = True) -> list[WorkEdge]:
        with self._lock:
            out = list(self._edges.values())
            if active_only:
                out = [e for e in out if e.removed_at is None]
            return out

    # ---- events ----
    def append_event(self, event: WorkEvent) -> None:
        with self._lock:
            self.get_item(event.work_item_id)
            self._events.setdefault(event.work_item_id, []).append(event)

    def events(self, work_item_id: str) -> list[WorkEvent]:
        with self._lock:
            self.get_item(work_item_id)
            return list(self._events.get(work_item_id, []))
