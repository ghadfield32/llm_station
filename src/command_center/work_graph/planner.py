"""ChatWorkPlanner — turn a STRUCTURED work plan (items + board placements +
typed edges) into canonical work, returning navigable TaskBatchReceipts.

Two operations over the same routine:
  * preview(plan) — side-effect-free. Runs the plan against a sandbox seeded with
    a read-only snapshot of the real graph, so cycle/edge checks are faithful,
    then throws the sandbox away. Nothing is persisted; ids are provisional.
  * commit(plan)  — validates in a sandbox FIRST (so an invalid plan writes
    NOTHING — atomic), then applies to the durable service and returns real ids.

This is deterministic: it takes an explicit plan and never infers structure from
free text. Natural-language deliverable-splitting / board-routing / dedup is a
later phase (no evidence-backed calibration → no silent auto-routing). Creating
work items/placements/edges is PLANNING, never a mission — it starts no
execution and touches no wall verb.
"""
from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from .schemas import (
    ACYCLIC_RELATIONS,
    TaskBatchReceipt,
    TaskCreationReceipt,
    WorkEdgeSummary,
    WorkGraphPlanSummary,
    WorkItemSummary,
    WorkPlacement,
    WorkPlacementSummary,
)
from .service import WorkGraphService


class ChatPlanError(ValueError):
    """The plan itself is malformed (no items, duplicate refs, empty title)."""


class PlanBoardRef(BaseModel):
    board_id: str
    domain_id: str
    card_component: str = "generic_task"
    placement_stage: str | None = None


class WorkPlanItemIn(BaseModel):
    ref: str                         # caller-local handle used to wire edges
    title: str
    kind: str = "todo"
    description: str = ""
    primary_board: PlanBoardRef | None = None
    secondary_boards: list[PlanBoardRef] = Field(default_factory=list)
    owner: str | None = None
    priority: str | None = None
    due_at: str | None = None


class WorkPlanEdgeIn(BaseModel):
    from_ref: str                    # a plan item ref OR an existing work_item_id
    to_ref: str
    relation: str
    reason: str | None = None


class WorkPlanIn(BaseModel):
    # a plan may originate from chat (conversation_id set), a capture, or the
    # daily intake DAG (no conversation) — so conversation_id is optional.
    conversation_id: str | None = None
    capture_id: str | None = None            # the originating capture, if any
    capture_batch_id: str | None = None
    items: list[WorkPlanItemIn] = Field(default_factory=list)
    edges: list[WorkPlanEdgeIn] = Field(default_factory=list)


class ChatWorkPlanner:
    def __init__(self, service: WorkGraphService, *,
                 sandbox_factory: Callable[[], WorkGraphService]) -> None:
        self._service = service
        self._sandbox_factory = sandbox_factory   # () -> fresh in-memory service

    def preview(self, plan: WorkPlanIn) -> TaskBatchReceipt:
        receipt = self._apply(self._seeded_sandbox(), plan)
        receipt.preview = True
        return receipt

    def commit(self, plan: WorkPlanIn) -> TaskBatchReceipt:
        # dry-run the WHOLE plan first: an invalid plan (cycle, unknown edge ref)
        # raises here and the durable graph is never touched — commit is atomic.
        self._apply(self._seeded_sandbox(), plan)
        receipt = self._apply(self._service, plan)
        receipt.preview = False
        return receipt

    def _seeded_sandbox(self) -> WorkGraphService:
        """A throwaway service holding a snapshot of the real items + edges, so
        cycle checks and edges that reference EXISTING work items validate
        faithfully without touching the durable store."""
        sandbox = self._sandbox_factory()
        for item in self._service.list_items():
            sandbox._store.add_item(item)
        for edge in self._service._store.edges():
            sandbox._store.add_edge(edge)
        return sandbox

    def _apply(self, service: WorkGraphService,
               plan: WorkPlanIn) -> TaskBatchReceipt:
        if not plan.items:
            raise ChatPlanError("a work plan must contain at least one item")
        refs = [it.ref for it in plan.items]
        if len(set(refs)) != len(refs):
            raise ChatPlanError("duplicate item ref in plan")

        ref_to_id: dict[str, str] = {}
        receipts: dict[str, TaskCreationReceipt] = {}

        # 1) items + their board placements
        for it in plan.items:
            item = service.create_item(
                it.title, kind=it.kind, description=it.description,
                owner=it.owner, priority=it.priority, due_at=it.due_at,
                conversation_id=plan.conversation_id,
                capture_id=plan.capture_id,
                capture_batch_id=plan.capture_batch_id)
            ref_to_id[it.ref] = item.work_item_id

            primary: WorkPlacementSummary | None = None
            secondary: list[WorkPlacementSummary] = []
            if it.primary_board is not None:
                primary = _placement_summary(_place(service, item.work_item_id,
                                                     it.primary_board, is_primary=True))
            for board in it.secondary_boards:
                secondary.append(_placement_summary(
                    _place(service, item.work_item_id, board, is_primary=False)))

            warnings: list[str] = []
            if it.primary_board is None and not it.secondary_boards:
                warnings.append("created with no board placement — it lives only "
                                "in the Universal Inbox until given a home")
            receipts[it.ref] = TaskCreationReceipt(
                work_item=_item_summary(service.get_item(item.work_item_id)),
                primary_placement=primary, secondary_placements=secondary,
                links=service.links_for(item.work_item_id), warnings=warnings)

        # 2) typed edges — refs resolve to a plan item OR an existing work_item_id
        for e in plan.edges:
            frm = ref_to_id.get(e.from_ref, e.from_ref)
            to = ref_to_id.get(e.to_ref, e.to_ref)
            edge = service.add_edge(frm, to, e.relation, reason=e.reason)
            summary = _edge_summary(edge)
            if e.from_ref in receipts:
                receipts[e.from_ref].outgoing_edges.append(summary)
            if e.to_ref in receipts:
                receipts[e.to_ref].incoming_edges.append(summary)

        # 3) refresh each item summary + links (a primary placement set
        #    primary_board_id; edges added navigation) so the receipt is final
        created: list[TaskCreationReceipt] = []
        for it in plan.items:
            wid = ref_to_id[it.ref]
            receipts[it.ref].work_item = _item_summary(service.get_item(wid))
            receipts[it.ref].links = service.links_for(wid)
            created.append(receipts[it.ref])

        return TaskBatchReceipt(conversation_id=plan.conversation_id,
                                capture_id=plan.capture_id,
                                capture_batch_id=plan.capture_batch_id,
                                created=created)


def _place(service: WorkGraphService, work_item_id: str, board: PlanBoardRef, *,
           is_primary: bool) -> WorkPlacement:
    return service.add_placement(
        work_item_id, board.board_id, board.domain_id, is_primary=is_primary,
        card_component=board.card_component, placement_stage=board.placement_stage)


def _item_summary(item) -> WorkItemSummary:
    return WorkItemSummary(
        work_item_id=item.work_item_id, title=item.title, kind=item.kind,
        canonical_status=item.canonical_status,
        primary_board_id=item.primary_board_id)


def _placement_summary(p: WorkPlacement) -> WorkPlacementSummary:
    return WorkPlacementSummary(placement_id=p.placement_id, board_id=p.board_id,
                                domain_id=p.domain_id, is_primary=p.is_primary)


def _edge_summary(e) -> WorkEdgeSummary:
    return WorkEdgeSummary(edge_id=e.edge_id, from_work_item_id=e.from_work_item_id,
                           to_work_item_id=e.to_work_item_id, relation=e.relation,
                           blocking=e.blocking, reason=e.reason)


def summarize_plan(plan: WorkPlanIn) -> WorkGraphPlanSummary:
    """A deterministic "this will create …" count of a proposed plan — the human
    confirmation gate before anything is created. Pure counting, no side effects:
    items by kind, primary/secondary placements, distinct boards, items with no
    board (→ Inbox), and edges by relation (with the blocking subset called out)."""
    items_by_kind: dict[str, int] = {}
    boards: list[str] = []
    primary = secondary = no_board = 0
    for it in plan.items:
        items_by_kind[it.kind] = items_by_kind.get(it.kind, 0) + 1
        if it.primary_board is not None:
            primary += 1
            if it.primary_board.board_id not in boards:
                boards.append(it.primary_board.board_id)
        for b in it.secondary_boards:
            secondary += 1
            if b.board_id not in boards:
                boards.append(b.board_id)
        if it.primary_board is None and not it.secondary_boards:
            no_board += 1

    edges_by_relation: dict[str, int] = {}
    blocking = 0
    for e in plan.edges:
        edges_by_relation[e.relation] = edges_by_relation.get(e.relation, 0) + 1
        if e.relation in ACYCLIC_RELATIONS:
            blocking += 1

    warnings: list[str] = []
    if no_board:
        warnings.append(f"{no_board} item(s) have no board and will land in the "
                        "Universal Inbox until given a home")
    return WorkGraphPlanSummary(
        item_count=len(plan.items), items_by_kind=items_by_kind,
        placement_count=primary + secondary, primary_placement_count=primary,
        secondary_placement_count=secondary, boards=boards,
        items_without_board=no_board, edge_count=len(plan.edges),
        edges_by_relation=edges_by_relation, blocking_edge_count=blocking,
        warnings=warnings)
