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
    CANONICAL_STATUSES,
    PermalinkResolution,
    ResourceLink,
    WorkEdge,
    WorkEvent,
    WorkGraph,
    WorkItem,
    WorkPlacement,
    WorkRelation,
)
from .store import (
    ConcurrentWorkItemUpdate,
    InMemoryWorkGraphStore,
    WorkGraphIntegrityConflict,
)


class WorkGraphError(ValueError):
    """A graph-integrity violation (cycle, duplicate primary, unknown ref)."""


class WorkGraphService:
    def __init__(self, store: InMemoryWorkGraphStore, *,
                 clock: Callable[[], str], id_factory: Callable[[str], str]) -> None:
        self._store = store
        self._clock = clock
        self._id = id_factory     # id_factory(prefix) -> id

    # ---- items -------------------------------------------------------------
    def reserve_work_item_id(self) -> str:
        """Allocate an identity before a cross-store intent records it."""
        return self._id("W")

    def create_item(
        self, title: str, *, work_item_id: str | None = None, **fields,
    ) -> WorkItem:
        title = (title or "").strip()
        if not title:
            raise WorkGraphError("work item title must not be empty")
        now = self._clock()
        fields.pop("primary_board_id", None)   # set only via a primary placement
        item = WorkItem(work_item_id=work_item_id or self._id("W"), title=title,
                        created_at=now, updated_at=now, **fields)
        event = WorkEvent(
            work_item_id=item.work_item_id,
            ts=now,
            kind="created",
            payload={"title": title, "kind": item.kind},
        )
        try:
            self._store.add_item_with_event(item, event)
        except (KeyError, WorkGraphIntegrityConflict) as exc:
            if work_item_id is None:
                raise
            existing = self._store.get_item(work_item_id)
            stable_exclusions = {
                "created_at", "updated_at", "primary_board_id", "canonical_status",
            }
            if existing.model_dump(exclude=stable_exclusions) != item.model_dump(
                exclude=stable_exclusions,
            ):
                raise WorkGraphError(
                    f"reserved WorkItem identity {work_item_id} has divergent fields"
                ) from exc
            return existing
        return item

    def get_item(self, work_item_id: str) -> WorkItem:
        return self._store.get_item(work_item_id)

    def list_items(self) -> list[WorkItem]:
        return self._store.list_items()

    def update_description(
        self, work_item_id: str, description: str, *,
        expected_updated_at: str, expected_description: str,
    ) -> WorkItem:
        """Edit only the organized WorkItem description with an atomic story event.

        Immutable capture text and source-card text are separate authorities and
        are deliberately unreachable from this operation.
        """
        try:
            updated, _event_appended = self._store.compare_and_set_description(
                work_item_id,
                expected_updated_at=expected_updated_at,
                expected_description=expected_description,
                description=description,
                updated_at=self._clock(),
            )
        except ConcurrentWorkItemUpdate as exc:
            raise WorkGraphError(str(exc)) from exc
        return updated

    def set_status(self, work_item_id: str, status: str) -> WorkItem:
        """Transition the ONE canonical status. Every placement projects it — a
        secondary board can never hold a contradictory execution state."""
        item = self._store.get_item(work_item_id)
        if status not in CANONICAL_STATUSES:
            raise WorkGraphError(
                f"canonical status must be one of {list(CANONICAL_STATUSES)}"
            )
        if item.canonical_status == status:
            return item
        now = self._clock()
        return self._store.update_item_fields(
            work_item_id,
            fields={"canonical_status": status, "updated_at": now},
            event=WorkEvent(
                work_item_id=work_item_id, ts=now,
                kind="status", payload={"status": status},
            ),
        )

    # ---- occurrences: repeated progress, NOT new tasks -----------------------
    def add_occurrence(self, work_item_id: str, *, note: str | None = None,
                       quantity: int | None = None, unit: str | None = None,
                       source_capture_id: str | None = None) -> WorkEvent:
        """Append repeated-progress evidence ("applied to jobs again") to the
        ONE canonical item. Rides the durable event stream — no second task,
        no second source of truth. Never changes canonical status."""
        item = self._store.get_item(work_item_id)      # KeyError if unknown
        if quantity is not None and quantity <= 0:
            raise WorkGraphError("occurrence quantity must be positive")
        payload: dict = {}
        if note:
            payload["note"] = note
        if quantity is not None:
            payload["quantity"] = quantity
        if unit:
            payload["unit"] = unit
        if source_capture_id:
            payload["source_capture_id"] = source_capture_id
            prior = [
                event for event in self._store.events(work_item_id)
                if event.kind == "occurrence"
                and event.payload.get("source_capture_id") == source_capture_id
            ]
            exact = next((event for event in prior if event.payload == payload), None)
            if exact is not None:
                return exact
            if prior:
                raise WorkGraphError(
                    "capture retry differs from its recorded occurrence"
                )
        event = WorkEvent(work_item_id=item.work_item_id, ts=self._clock(),
                          kind="occurrence", payload=payload)
        self._store.update_item_fields(
            item.work_item_id, fields={"updated_at": event.ts}, event=event)
        return event

    def occurrences(self, work_item_id: str) -> list[WorkEvent]:
        self._store.get_item(work_item_id)             # KeyError if unknown
        return [e for e in self._store.events(work_item_id)
                if e.kind == "occurrence"]

    def occurrence_count(self, work_item_id: str) -> int:
        return len(self.occurrences(work_item_id))

    # ---- duplicate decisions: append-only human ground truth ----------------
    def record_duplicate_decision(self, work_item_id: str, *, resolution: str,
                                  capture_id: str | None = None,
                                  match_class: str | None = None,
                                  evidence_kinds: list[str] | None = None,
                                  note: str | None = None) -> WorkEvent:
        """Record what a HUMAN chose for a duplicate candidate against this
        item. Append-only calibration evidence — recording never merges,
        discards, or deletes anything itself."""
        self._store.get_item(work_item_id)             # KeyError if unknown
        resolution = (resolution or "").strip()
        if not resolution:
            raise WorkGraphError("duplicate decision resolution required")
        payload: dict = {"resolution": resolution}
        if capture_id:
            payload["capture_id"] = capture_id
        if match_class:
            payload["match_class"] = match_class
        if evidence_kinds:
            payload["evidence_kinds"] = list(evidence_kinds)
        if note:
            payload["note"] = note
        event = WorkEvent(work_item_id=work_item_id, ts=self._clock(),
                          kind="duplicate_decision", payload=payload)
        if capture_id:
            prior = [
                candidate for candidate in self._store.events(work_item_id)
                if candidate.kind == "duplicate_decision"
                and candidate.payload.get("capture_id") == capture_id
            ]
            exact = next((candidate for candidate in prior
                          if candidate.payload == payload), None)
            if exact is not None:
                return exact
            if prior:
                raise WorkGraphError(
                    "capture retry differs from its recorded duplicate decision"
                )
        self._store.append_event(event)
        return event

    def duplicate_decisions(self, work_item_id: str) -> list[WorkEvent]:
        self._store.get_item(work_item_id)
        return [e for e in self._store.events(work_item_id)
                if e.kind == "duplicate_decision"]

    # ---- expansions: append selected new details, never rewrite -------------
    def record_expansion(self, work_item_id: str, *, deltas: list[dict],
                         source_capture_id: str | None = None) -> WorkEvent:
        """Append HUMAN-SELECTED expansion deltas to the ONE canonical item.
        Append-only: the existing title and description are never replaced —
        the event stream carries the additions."""
        item = self._store.get_item(work_item_id)      # KeyError if unknown
        if not deltas:
            raise WorkGraphError("an expansion needs at least one delta")
        payload: dict = {"deltas": deltas}
        if source_capture_id:
            payload["source_capture_id"] = source_capture_id
            prior = [
                event for event in self._store.events(work_item_id)
                if event.kind == "expansion"
                and event.payload.get("source_capture_id") == source_capture_id
            ]
            exact = next((event for event in prior if event.payload == payload), None)
            if exact is not None:
                return exact
            if prior:
                raise WorkGraphError(
                    "capture retry differs from its recorded expansion"
                )
        event = WorkEvent(work_item_id=item.work_item_id, ts=self._clock(),
                          kind="expansion", payload=payload)
        self._store.update_item_fields(
            item.work_item_id, fields={"updated_at": event.ts}, event=event)
        return event

    def expansions(self, work_item_id: str) -> list[WorkEvent]:
        self._store.get_item(work_item_id)
        return [e for e in self._store.events(work_item_id)
                if e.kind == "expansion"]

    # ---- placements --------------------------------------------------------
    def add_placement(self, work_item_id: str, board_id: str, domain_id: str, *,
                      is_primary: bool = False, **fields) -> WorkPlacement:
        self._store.get_item(work_item_id)
        same_target = [
            p for p in self._store.placements_for(work_item_id)
            if p.board_id == board_id and p.domain_id == domain_id
        ]
        if same_target:
            existing = same_target[0]
            fields_match = all(
                getattr(existing, key, None) == value
                for key, value in fields.items()
            )
            if existing.is_primary == is_primary and fields_match:
                recovery_event = WorkEvent(
                    work_item_id=work_item_id, ts=self._clock(),
                    kind="placement_added",
                    payload={
                        "placement_id": existing.placement_id,
                        "board_id": existing.board_id,
                        "domain_id": existing.domain_id,
                        "is_primary": existing.is_primary,
                        "recovered": True,
                    },
                )
                try:
                    return self._store.repair_placement_with_event(
                        existing, recovery_event,
                    )
                except WorkGraphIntegrityConflict as exc:
                    raise WorkGraphError(str(exc)) from exc
            raise WorkGraphError(
                f"work item {work_item_id} already has a different active "
                f"placement on {board_id}/{domain_id}")
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
        placement_event = WorkEvent(
            work_item_id=work_item_id, ts=now, kind="placement_added",
            payload={
                "placement_id": placement.placement_id,
                "board_id": board_id,
                "domain_id": domain_id,
                "is_primary": is_primary,
            },
        )
        try:
            return self._store.add_placement_with_event(placement, placement_event)
        except WorkGraphIntegrityConflict as exc:
            raise WorkGraphError(str(exc)) from exc

    def remove_placement(self, placement_id: str) -> None:
        """Remove a projection ONLY. The canonical work item + its history stay."""
        try:
            self._store.remove_placement_with_event(
                placement_id, removed_at=self._clock(),
            )
        except WorkGraphIntegrityConflict as exc:
            raise WorkGraphError(str(exc)) from exc

    # ---- edges -------------------------------------------------------------
    def add_edge(self, from_work_item_id: str, to_work_item_id: str,
                 relation: WorkRelation, **fields) -> WorkEdge:
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
        event = WorkEvent(
            work_item_id=from_work_item_id,
            ts=now,
            kind="edge_added",
            payload={"edge_id": edge.edge_id, "to": to_work_item_id, "relation": relation},
        )
        try:
            return self._store.add_edge_with_event(edge, event)
        except WorkGraphIntegrityConflict as exc:
            raise WorkGraphError(str(exc)) from exc

    def remove_edge(self, edge_id: str) -> None:
        try:
            self._store.remove_edge_with_event(edge_id, removed_at=self._clock())
        except WorkGraphIntegrityConflict as exc:
            raise WorkGraphError(str(exc)) from exc

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
