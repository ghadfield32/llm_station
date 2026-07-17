"""Structured board-FORMAT changes — a typed column edit, NOT browser-generated
YAML (plan §8 "No browser-generated YAML should be written directly").

The browser sends a STRUCTURED change (which columns a board should have); this
module computes the `after` domain-surfaces config server-side from the current
validated config, pruning anything the DomainSurfaceSpec contract would then
reject (a column_action for a removed column). The result is fed to the existing
board-change preview (before/after diff + contract validation) and, only on a
human-confirmed + token-gated apply, the audited atomic journal.

Pure functions over the config dict — no I/O — so the transform is hermetically
testable and never emits raw YAML.
"""
from __future__ import annotations

import copy
from typing import Any

from ..schemas.base import Strict


class BoardFormatChange(Strict):
    """A structured board-format change the browser can express without touching
    YAML: the exact column list a board's domain surface should have."""
    domain_id: str
    columns: list[str]


def _find_domain(domains_config: dict[str, Any], domain_id: str) -> dict[str, Any]:
    for domain in domains_config.get("domains", []):
        if domain.get("domain_id") == domain_id:
            return domain
    raise KeyError(f"domain {domain_id!r} is not in the domain-surfaces config")


def current_columns(domains_config: dict[str, Any], domain_id: str) -> list[str]:
    """The board's current columns (read-only helper for the card's editor)."""
    return list(_find_domain(domains_config, domain_id).get("columns", []))


def apply_columns_change(
    domains_config: dict[str, Any], change: BoardFormatChange,
) -> dict[str, Any]:
    """Return a DEEP COPY of `domains_config` with `change.domain_id`'s columns
    set to `change.columns`. Stale `column_actions` (mapped to a column that no
    longer exists) are pruned so the result still satisfies the DomainSurfaceSpec
    contract — the caller validates the whole doc before any write.

    Refuses duplicate columns here (the contract also would) so the card gets a
    clear error at plan time rather than a Pydantic message at preview time.
    """
    if len(change.columns) != len(set(change.columns)):
        dupes = sorted({c for c in change.columns if change.columns.count(c) > 1})
        raise ValueError(f"duplicate column(s): {dupes}")
    if not change.columns:
        raise ValueError("a board must keep at least one column")
    after = copy.deepcopy(domains_config)
    domain = _find_domain(after, change.domain_id)
    domain["columns"] = list(change.columns)
    # prune column_actions that reference a now-removed column (else the
    # DomainSurfaceSpec validator rejects the whole config)
    actions = domain.get("column_actions") or {}
    domain["column_actions"] = {
        col: verb for col, verb in actions.items() if col in change.columns}
    return after


def columns_diff(before: list[str], after: list[str]) -> dict[str, list[str]]:
    """A human-readable column delta for the card (added / removed / reordered)."""
    added = [c for c in after if c not in before]
    removed = [c for c in before if c not in after]
    kept_before = [c for c in before if c in after]
    kept_after = [c for c in after if c in before]
    reordered = kept_before != kept_after
    return {"added": added, "removed": removed,
            "reordered": [] if not reordered else kept_after}
