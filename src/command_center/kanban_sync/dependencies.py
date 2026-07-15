"""Per-card mission dependencies (Cline-style dependency chains).

A card may declare `blocked_by` (mission ids that must finish first) and `unblocks`
(the inverse edge, for surfacing). This is deliberately a small, pure primitive — a
typed shape plus one blocked-computation — not a scheduler. It carries NO approval
authority: a resolved blocker only means a card is eligible to start; a human still
approves anything past L2, exactly as before. The board opts in via
KanbanBoardSpec.dependency_fields; a board with none has no dependency chains.
"""
from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field, field_validator, model_validator

from command_center.schemas import Strict


class CardDependencies(Strict):
    """The dependency edges declared on one card. Both lists are optional; a card with
    neither is a normal, independent mission."""
    blocked_by: list[str] = Field(default_factory=list)
    unblocks: list[str] = Field(default_factory=list)

    @field_validator("blocked_by", "unblocks")
    @classmethod
    def _clean_ids(cls, v: list[str]) -> list[str]:
        ids = [s.strip() for s in v]
        if any(not s for s in ids):
            raise ValueError("dependency ids must be non-empty")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate dependency ids")
        return ids

    @model_validator(mode="after")
    def _no_overlap(self):
        overlap = set(self.blocked_by) & set(self.unblocks)
        if overlap:
            raise ValueError(
                f"a card cannot both be blocked_by and unblock the same id(s): {sorted(overlap)}"
            )
        return self


def parse_card_dependencies(row: dict) -> CardDependencies:
    """Read dependency edges off a raw card row dict (board store/Ledger). A field may be a
    list, a comma/space-separated string, or absent — all normalise to a clean id list."""
    def _as_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [p for p in value.replace(",", " ").split() if p]
        if isinstance(value, (list, tuple)):
            return [str(p).strip() for p in value if str(p).strip()]
        return []
    return CardDependencies(blocked_by=_as_list(row.get("blocked_by")),
                            unblocks=_as_list(row.get("unblocks")))


def unmet_blockers(blocked_by: Iterable[str], resolved_ids: Iterable[str]) -> list[str]:
    """The blockers that are NOT yet resolved (done). Empty => the card is eligible to
    start. `resolved_ids` is the set of mission/card ids that have reached a done state."""
    resolved = set(resolved_ids)
    return [b for b in blocked_by if b not in resolved]


def is_card_blocked(row: dict, resolved_ids: Iterable[str]) -> bool:
    """True iff the card has at least one unresolved blocker. Independent cards (no
    blocked_by) are never blocked by this rule."""
    deps = parse_card_dependencies(row)
    return bool(unmet_blockers(deps.blocked_by, resolved_ids))
