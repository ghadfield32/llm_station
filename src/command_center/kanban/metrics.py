"""Real agent-surface metrics, computed from the agent-call log spine.

No synthetic numbers: every figure is derived from `_export/agent_calls.jsonl`
(the same append-only log growthos.observability writes for every tool call on
every surface). If the log is absent the metrics are all zero AND the digest says
so with the resolved path — an empty log is disclosed, never masked.

These are the figures you watch when tuning the surface: redundant-call rate (did
re-injection stop the model re-reading the board?), intent-verb adoption (are
agents using the verbs instead of the dropped generic set_status?), and per-tool
error/latency.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_LOG = REPO_ROOT / "growth_os" / "_export" / "agent_calls.jsonl"

# The agent-facing board-transition verbs (Phase 2) and the canonical column each
# targets — the single declared contract. The validate gate asserts every target is
# a legal, non-Approved column; tests/test_actions_intent cross-checks that the
# growthos verbs actually produce these columns (so the two can't drift).
VERB_COLUMN: dict[str, tuple[str, str]] = {
    "stage_card": ("mission_intake", "Ready"),
    "block_card": ("mission_intake", "Blocked"),
    "reject_card": ("mission_intake", "Rejected"),
    "start_todo": ("todos", "In Progress"),
    "finish_todo": ("todos", "Done"),
    "block_todo": ("todos", "Blocked"),
}
INTENT_VERBS = frozenset(VERB_COLUMN)

# Full legal columns per board (mirrors growthos.actions.STATUSES — the live
# board view omits terminal columns, but verbs legitimately move TO them, so the
# gate validates against this full set; tests/test_actions_intent cross-checks it
# against the real STATUSES so the two cannot drift).
BOARD_STATUSES: dict[str, list[str]] = {
    "mission_intake": ["Backlog", "Ready", "Approved", "In Progress",
                       "Blocked", "Done", "Rejected"],
    "todos": ["Backlog", "Todo", "In Progress", "Blocked", "Done"],
}
# The pre-verb generic mutator: dropped from agent tools in Phase 2, so its share
# of agent status-changes should trend to zero — a measurable adoption signal.
GENERIC_MUTATORS = frozenset({"set_status"})
OTHER_MUTATORS = frozenset({"add_mission_card", "add_todo", "update_todo", "update_dag"})
MUTATORS = INTENT_VERBS | GENERIC_MUTATORS | OTHER_MUTATORS


def log_path() -> Path:
    env = os.environ.get("GROWTHOS_AGENT_LOG")
    return Path(env) if env else _DEFAULT_LOG


def load_calls(path: str | Path | None = None) -> list[dict]:
    """All recorded calls in order. Absent log → empty list (disclosed by the digest
    via total_calls + the path, not silently treated as healthy)."""
    p = Path(path) if path is not None else log_path()
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def recent_calls(limit: int = 25, path: str | Path | None = None) -> list[dict]:
    """The most recent agent calls (the log is append-only, newest last)."""
    return load_calls(path)[-limit:]


@dataclass
class Metrics:
    total_calls: int = 0
    by_surface: dict[str, int] = field(default_factory=dict)
    error_rate: float = 0.0
    redundant_rate: float = 0.0          # consecutive identical (surface, tool, args)
    board_mutations: int = 0
    intent_verb_calls: int = 0
    generic_mutator_calls: int = 0
    intent_verb_share: float | None = None   # None when there are no status-changes yet
    per_tool: list[dict] = field(default_factory=list)


def _rate(num: int, den: int) -> float:
    return round(num / den, 3) if den else 0.0


def compute_metrics(calls: list[dict]) -> Metrics:
    if not calls:
        return Metrics()
    errors = sum(1 for c in calls if not c.get("ok", True))

    # redundant = an immediate repeat of the previous call on the same surface
    redundant = 0
    last_by_surface: dict[str, tuple] = {}
    for c in calls:
        sig = (c.get("tool"), json.dumps(c.get("args", {}), sort_keys=True))
        s = c.get("surface", "?")
        if last_by_surface.get(s) == sig:
            redundant += 1
        last_by_surface[s] = sig

    intent = sum(1 for c in calls if c.get("tool") in INTENT_VERBS)
    generic = sum(1 for c in calls if c.get("tool") in GENERIC_MUTATORS)
    mutations = sum(1 for c in calls if c.get("tool") in MUTATORS)
    status_changes = intent + generic

    by_surface: dict[str, int] = {}
    for c in calls:
        by_surface[c.get("surface", "?")] = by_surface.get(c.get("surface", "?"), 0) + 1

    by_tool: dict[str, list[dict]] = {}
    for c in calls:
        by_tool.setdefault(c.get("tool", "?"), []).append(c)
    per_tool = []
    for tool, items in sorted(by_tool.items()):
        errs = sum(1 for i in items if not i.get("ok", True))
        per_tool.append({
            "tool": tool, "calls": len(items), "errors": errs,
            "error_rate": _rate(errs, len(items)),
            "p50_ms": round(median(i.get("ms", 0.0) for i in items), 1)})

    return Metrics(
        total_calls=len(calls),
        by_surface=by_surface,
        error_rate=_rate(errors, len(calls)),
        redundant_rate=_rate(redundant, len(calls)),
        board_mutations=mutations,
        intent_verb_calls=intent,
        generic_mutator_calls=generic,
        intent_verb_share=(_rate(intent, status_changes) if status_changes else None),
        per_tool=per_tool,
    )
