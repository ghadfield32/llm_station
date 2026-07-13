"""Work-graph contracts: the canonical WorkItem, its per-board WorkPlacements,
the typed WorkEdges between items, and the ResourceLink navigation receipts.

Board membership is a WorkPlacement (WorkItem -> Board), NOT an edge. Edges are
WorkItem <-> WorkItem only, so the graph stays semantically clean.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WORK_ITEM_KINDS: tuple[str, ...] = (
    "note", "todo", "research", "post", "paper", "project", "bug", "feature",
    "decision", "maintenance")
WorkItemKind = Literal[
    "note", "todo", "research", "post", "paper", "project", "bug", "feature",
    "decision", "maintenance"]

# The canonical execution status — shared everywhere. A board move that means
# execution progresses updates THIS; a purely visual move updates only a
# placement's stage (see WorkPlacement.placement_stage).
CanonicalStatus = Literal[
    "backlog", "ready", "in_progress", "blocked", "awaiting_approval", "done",
    "rejected", "archived"]

WorkRelation = Literal[
    "parent_of", "blocks", "related_to", "implements", "informs",
    "derived_from", "duplicates", "supersedes", "supports"]

# Relations whose subgraph MUST stay acyclic — a cycle is semantically invalid
# (a project can't be its own ancestor; a blocker can't block itself; work can't
# supersede its own supersessor). Adding an edge that would close a cycle across
# these relations is rejected.
ACYCLIC_RELATIONS: frozenset[str] = frozenset({
    "blocks", "parent_of", "implements", "supersedes", "derived_from"})
# Relations that may cycle — they express association, not a DAG.
CYCLE_OK_RELATIONS: frozenset[str] = frozenset({
    "related_to", "informs", "supports", "duplicates"})


class WorkItem(BaseModel):
    work_item_id: str
    title: str
    description: str = ""
    kind: WorkItemKind = "todo"
    canonical_status: CanonicalStatus = "backlog"
    primary_board_id: str | None = None
    owner: str | None = None
    priority: str | None = None
    due_at: str | None = None
    # provenance links (set later by intake / chat / mission integration)
    capture_id: str | None = None
    capture_batch_id: str | None = None
    packet_id: str | None = None
    conversation_id: str | None = None
    mission_id: str | None = None
    created_at: str
    updated_at: str


class WorkPlacement(BaseModel):
    """A projection of one WorkItem onto one board. The card the user sees on a
    board is a placement, not a separate task."""
    placement_id: str
    work_item_id: str
    board_id: str
    domain_id: str
    is_primary: bool = False
    placement_stage: str | None = None      # board-local visual stage (NOT execution state)
    card_component: str = "generic_task"
    local_fields: dict = Field(default_factory=dict)
    created_at: str
    removed_at: str | None = None


class WorkEdge(BaseModel):
    edge_id: str
    from_work_item_id: str
    to_work_item_id: str
    relation: WorkRelation
    blocking: bool = False
    reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: str
    removed_at: str | None = None


class WorkEvent(BaseModel):
    event_seq: int | None = None
    work_item_id: str
    ts: str
    kind: str            # created | status | placement_added | placement_removed | edge_added | ...
    payload: dict = Field(default_factory=dict)


class ResourceLink(BaseModel):
    """A backend-generated navigation receipt. The frontend renders href verbatim
    and NEVER assembles route URLs from assumed formats."""
    kind: Literal[
        "work_item", "board", "placement", "chat", "mission", "packet",
        "graph", "evidence"]
    resource_id: str
    label: str
    href: str
    relation: str | None = None


class WorkGraph(BaseModel):
    """A resolved neighbourhood around a root work item (or the whole graph):
    the items, their placements, and the edges among them."""
    root_work_item_id: str | None = None
    items: list[WorkItem] = Field(default_factory=list)
    placements: list[WorkPlacement] = Field(default_factory=list)
    edges: list[WorkEdge] = Field(default_factory=list)
