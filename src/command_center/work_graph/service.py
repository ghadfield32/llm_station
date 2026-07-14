"""WorkGraphService — the canonical work-graph's logic: create items, project
them onto boards (one primary max), connect them with typed edges (blocking-style
relations kept acyclic), transition canonical status, resolve neighbourhoods, and
GENERATE navigation links (the backend owns hrefs; the browser never assembles
them). Clock + id factory injected → hermetic.

It never starts execution: creating a work item / placement / edge is planning,
not a mission. Write-capable execution stays behind the mission + lease + wall.
"""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

from .schemas import (
    ACYCLIC_RELATIONS,
    PermalinkResolution,
    ResourceLink,
    WorkEdge,
    WorkEvent,
    WorkGraph,
    WorkItem,
    WorkPlacement,
)
from .store import InMemoryWorkGraphStore


class WorkGraphError(ValueError):
    """A graph-integrity violation (cycle, duplicate primary, unknown ref)."""


class WorkGraphService:
    def __init__(self, store: InMemoryWorkGraphStore, *,
                 clock: Callable[[], str], id_factory: Callable[[str], str]) -> None:
        self._store = store
        self._clock = clock
        self._id = id_factory     # id_factory(prefix) -> id

    # ---- items -------------------------------------------------------------
    def create_item(self, title: str, **fields) -> WorkItem:
        title = (title or "").strip()
        if not title:
            raise WorkGraphError("work item title must not be empty")
        now = self._clock()
        fields.pop("primary_board_id", None)   # set only via a primary placement
        item = WorkItem(work_item_id=self._id("W"), title=title,
                        created_at=now, updated_at=now, **fields)
        self._store.add_item(item)
        self._event(item.work_item_id, "created", {"title": title, "kind": item.kind})
        return item

    def get_item(self, work_item_id: str) -> WorkItem:
        return self._store.get_item(work_item_id)

    def list_items(self) -> list[WorkItem]:
        return self._store.list_items()

    def set_status(self, work_item_id: str, status: str) -> WorkItem:
        """Transition the ONE canonical status. Every placement projects it — a
        secondary board can never hold a contradictory execution state."""
        item = self._store.get_item(work_item_id)
        updated = item.model_copy(update={"canonical_status": status,
                                          "updated_at": self._clock()})
        self._store.put_item(updated)
        self._event(work_item_id, "status", {"status": status})
        return updated

    # ---- placements --------------------------------------------------------
    def add_placement(self, work_item_id: str, board_id: str, domain_id: str, *,
                      is_primary: bool = False, **fields) -> WorkPlacement:
        item = self._store.get_item(work_item_id)
        if is_primary:
            existing_primary = [p for p in self._store.placements_for(work_item_id)
                                if p.is_primary]
            if existing_primary:
                raise WorkGraphError(
                    f"work item {work_item_id} already has a primary board "
                    f"({existing_primary[0].board_id}); demote it first")
        now = self._clock()
        placement = WorkPlacement(
            placement_id=self._id("P"), work_item_id=work_item_id, board_id=board_id,
            domain_id=domain_id, is_primary=is_primary, created_at=now, **fields)
        self._store.add_placement(placement)
        if is_primary:
            self._store.put_item(item.model_copy(
                update={"primary_board_id": board_id, "updated_at": now}))
        self._event(work_item_id, "placement_added",
                    {"board_id": board_id, "is_primary": is_primary})
        return placement

    def remove_placement(self, placement_id: str) -> None:
        """Remove a projection ONLY. The canonical work item + its history stay."""
        p = self._store.get_placement(placement_id)
        if p.removed_at is not None:
            return
        now = self._clock()
        self._store.put_placement(p.model_copy(update={"removed_at": now}))
        if p.is_primary:
            item = self._store.get_item(p.work_item_id)
            self._store.put_item(item.model_copy(
                update={"primary_board_id": None, "updated_at": now}))
        self._event(p.work_item_id, "placement_removed", {"board_id": p.board_id})

    # ---- edges -------------------------------------------------------------
    def add_edge(self, from_work_item_id: str, to_work_item_id: str,
                 relation: str, **fields) -> WorkEdge:
        self._store.get_item(from_work_item_id)      # both must exist
        self._store.get_item(to_work_item_id)
        if from_work_item_id == to_work_item_id and relation in ACYCLIC_RELATIONS:
            raise WorkGraphError(f"a {relation} edge cannot point an item at itself")
        if relation in ACYCLIC_RELATIONS and self._would_cycle(
                from_work_item_id, to_work_item_id):
            raise WorkGraphError(
                f"adding a {relation} edge {from_work_item_id} -> {to_work_item_id} "
                "would create a cycle among blocking/structural relations")
        now = self._clock()
        edge = WorkEdge(edge_id=self._id("E"), from_work_item_id=from_work_item_id,
                        to_work_item_id=to_work_item_id, relation=relation,
                        blocking=relation in ACYCLIC_RELATIONS, created_at=now, **fields)
        self._store.add_edge(edge)
        self._event(from_work_item_id, "edge_added",
                    {"to": to_work_item_id, "relation": relation})
        return edge

    def remove_edge(self, edge_id: str) -> None:
        e = self._store.get_edge(edge_id)
        if e.removed_at is None:
            self._store.put_edge(e.model_copy(update={"removed_at": self._clock()}))

    def _would_cycle(self, frm: str, to: str) -> bool:
        """True if a new acyclic edge frm->to would close a cycle: i.e. `to`
        already reaches `frm` through the existing acyclic-relation subgraph."""
        adj: dict[str, list[str]] = {}
        for e in self._store.edges():
            if e.relation in ACYCLIC_RELATIONS:
                adj.setdefault(e.from_work_item_id, []).append(e.to_work_item_id)
        seen, stack = set(), [to]
        while stack:
            node = stack.pop()
            if node == frm:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(adj.get(node, []))
        return False

    # ---- graph + links -----------------------------------------------------
    def graph(self, work_item_id: str | None = None, *, depth: int = 1) -> WorkGraph:
        if work_item_id is None:                      # whole graph
            return WorkGraph(items=self._store.list_items(),
                             placements=self._store.list_placements(),
                             edges=self._store.edges())
        self._store.get_item(work_item_id)
        active = self._store.edges()
        neigh = {work_item_id}
        frontier = {work_item_id}
        for _ in range(max(0, depth)):
            nxt: set[str] = set()
            for e in active:
                if e.from_work_item_id in frontier:
                    nxt.add(e.to_work_item_id)
                if e.to_work_item_id in frontier:
                    nxt.add(e.from_work_item_id)
            nxt -= neigh
            neigh |= nxt
            frontier = nxt
            if not frontier:
                break
        items = [self._store.get_item(i) for i in neigh]
        placements = [p for i in neigh for p in self._store.placements_for(i)]
        edges = [e for e in active
                 if e.from_work_item_id in neigh and e.to_work_item_id in neigh]
        return WorkGraph(root_work_item_id=work_item_id, items=items,
                         placements=placements, edges=edges)

    def links_for(self, work_item_id: str) -> list[ResourceLink]:
        """Backend-generated navigation receipts for a work item. hrefs are
        query-param routes the SPA already understands; the browser renders them
        verbatim and never assembles its own."""
        item = self._store.get_item(work_item_id)
        placements = self._store.placements_for(work_item_id)
        links: list[ResourceLink] = [ResourceLink(
            kind="graph", resource_id=work_item_id, label="Connected work",
            href=_href({"view": "work-map", "work": work_item_id}), relation="self")]
        for p in placements:
            links.append(ResourceLink(
                kind="board", resource_id=p.board_id,
                label=("Primary board" if p.is_primary else "Also on") + f": {p.board_id}",
                href=_href({"view": "domains", "domain": p.domain_id,
                            "work": work_item_id}),
                relation="primary" if p.is_primary else "secondary"))
        if item.conversation_id:
            links.append(ResourceLink(
                kind="chat", resource_id=item.conversation_id, label="Source chat",
                href=_href({"view": "chat", "thread": item.conversation_id})))
        if item.mission_id:
            links.append(ResourceLink(
                kind="mission", resource_id=item.mission_id, label="Mission",
                href=_href({"view": "missions", "mission": item.mission_id})))
        if item.packet_id:
            links.append(ResourceLink(
                kind="packet", resource_id=item.packet_id, label="Readiness packet",
                href=_href({"view": "packet", "packet": item.packet_id})))
        return links

    # ---- permalink ---------------------------------------------------------
    def resolve(self, work_item_id: str) -> PermalinkResolution:
        """Resolve a stable ``/work/<id>`` permalink: the ONE canonical place to
        land plus the full navigation receipt. The backend decides the target —
        the browser follows target.href verbatim, it never picks a destination."""
        item = self._store.get_item(work_item_id)     # KeyError if unknown
        return PermalinkResolution(
            work_item_id=work_item_id, title=item.title, kind=item.kind,
            canonical_status=item.canonical_status,
            target=self._canonical_target(item),
            links=self.links_for(work_item_id))

    def _canonical_target(self, item: WorkItem) -> ResourceLink:
        """Where opening the permalink lands: the primary board if there is one,
        else any active board, else the Work Map (an item with no placement yet
        still resolves — you land where you can act on it / give it a home)."""
        placements = self._store.placements_for(item.work_item_id)
        dest = next((p for p in placements if p.is_primary),
                    placements[0] if placements else None)
        if dest is not None:
            return ResourceLink(
                kind="board", resource_id=dest.board_id,
                label=f"Open on board: {dest.board_id}",
                href=_href({"view": "domains", "domain": dest.domain_id,
                            "work": item.work_item_id}),
                relation="primary" if dest.is_primary else "secondary")
        return ResourceLink(
            kind="graph", resource_id=item.work_item_id, label="Open in Work Map",
            href=_href({"view": "work-map", "work": item.work_item_id}),
            relation="self")

    def _event(self, work_item_id: str, kind: str, payload: dict) -> None:
        self._store.append_event(WorkEvent(
            work_item_id=work_item_id, ts=self._clock(), kind=kind, payload=payload))


def _href(params: dict[str, str]) -> str:
    return "?" + urlencode(params)
