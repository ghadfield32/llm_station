"""Canonical board state, re-injected into the agent loop each turn.

The fix for "agents don't drive the board well": invert who owns board state.
The harness (this module) fetches the single source of truth and renders it into
the model's context every turn; the model emits *intent* and never has to call
`list_*` to remember what's on the board or hold its contents in its head. This
is the Cline focus-chain pattern — deterministic code owns the bookkeeping.

Linear flow (no hidden state):
  stage 1  collect_sections()  fetch each board's rows (per-source fail-loud)
  stage 2  _*_section()        group by column, cap per group, disclose overflow
  stage 3  render_board_state() one compact block, or an explicit ERROR line

Fail-loud contract: a source that can't be read renders an explicit
``ERROR: <reason>`` line for that board — never an empty group (which would read
as "no cards" and silently mislead the model). Nothing is swallowed.

The renderer is pure (testable with synthetic rows). `collect_board_state()` wires
the real growthos.actions + Ledger fetchers. Knobs come from
configs/agent_surface.yaml (BoardStateKnobs) — no inline literals here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..schemas import AgentSurfaceConfig, BoardStateKnobs

REPO_ROOT = Path(__file__).resolve().parents[3]   # src/command_center/channels/ -> repo root
_CONFIG_PATH = REPO_ROOT / "configs" / "agent_surface.yaml"


@lru_cache(maxsize=1)
def load_agent_surface_config() -> AgentSurfaceConfig:
    """The validated agent-surface knobs, by absolute repo path (robust to the
    gateway's chdir into the growth-os root). Missing file fails loud — the config
    is committed and required, never silently defaulted."""
    data = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    return AgentSurfaceConfig.model_validate(data)

# Columns shown per board, in order. Terminal columns are deliberately omitted so
# the block reflects *live* work; the omission is disclosed in the block header,
# not hidden. These are the canonical enums from growthos.actions.STATUSES and the
# Ledger Status literal — the single source, not a re-statement to drift from.
LIVE_COLUMNS: dict[str, list[str]] = {
    "mission_intake": ["Backlog", "Ready", "Approved", "In Progress", "Blocked"],
    "todos": ["Backlog", "Todo", "In Progress", "Blocked"],
    "missions": ["awaiting_approval", "open", "approved", "running", "blocked"],
}


@dataclass
class BoardGroup:
    column: str
    items: list[str]
    overflow: int = 0          # rows beyond the per-group cap (disclosed, not dropped silently)


@dataclass
class BoardSection:
    board: str
    groups: list[BoardGroup] = field(default_factory=list)
    error: str | None = None   # set iff the source could not be read — rendered loudly


def _group_rows(rows: list[dict], *, status_key: str, columns: list[str],
                fmt, knobs: BoardStateKnobs) -> list[BoardGroup]:
    """Bucket rows into the live columns, cap each at max_items_per_group, and
    record how many overflowed. Rows in terminal/unknown columns are not shown."""
    buckets: dict[str, list[str]] = {col: [] for col in columns}
    for row in rows:
        col = row.get(status_key, "")
        if col in buckets:
            buckets[col].append(fmt(row))
    cap = knobs.max_items_per_group
    out: list[BoardGroup] = []
    for col in columns:
        rendered = buckets[col]
        if not rendered:
            continue
        out.append(BoardGroup(column=col, items=rendered[:cap],
                              overflow=max(0, len(rendered) - cap)))
    return out


def _dep_marker(r: dict) -> str:
    """A deterministic '⛔blocked_by:X,Y' suffix when a row declares unresolved-looking
    dependencies. Additive: rows without a blocked_by field render exactly as before, so
    the harness surfaces mission dependency chains only when a board actually uses them."""
    raw = r.get("blocked_by")
    if not raw:
        return ""
    ids = raw.split(",") if isinstance(raw, str) else list(raw)
    ids = [str(i).strip() for i in ids if str(i).strip()]
    return f" ⛔blocked_by:{','.join(ids)}" if ids else ""


def _cards_section(rows: list[dict], knobs: BoardStateKnobs) -> BoardSection:
    def fmt(r: dict) -> str:
        meta = " · ".join(p for p in (r.get("risk", ""), r.get("section", "")) if p)
        return f"{r.get('title', '?')}" + (f" [{meta}]" if meta else "") + _dep_marker(r)
    return BoardSection("mission_intake",
                        _group_rows(rows, status_key="status",
                                    columns=LIVE_COLUMNS["mission_intake"],
                                    fmt=fmt, knobs=knobs))


def _todos_section(rows: list[dict], knobs: BoardStateKnobs) -> BoardSection:
    def fmt(r: dict) -> str:
        meta = " · ".join(p for p in (r.get("area", ""), r.get("priority", "")) if p)
        return f"{r.get('task', '?')}" + (f" [{meta}]" if meta else "")
    return BoardSection("todos",
                        _group_rows(rows, status_key="status",
                                    columns=LIVE_COLUMNS["todos"],
                                    fmt=fmt, knobs=knobs))


def _missions_section(rows: list[dict], knobs: BoardStateKnobs) -> BoardSection:
    def fmt(r: dict) -> str:
        action = (r.get("action", "") or "").splitlines()[0][:48]
        return f"{r.get('id', '?')}: {action} [{r.get('risk', '?')}]" + _dep_marker(r)
    return BoardSection("missions",
                        _group_rows(rows, status_key="status",
                                    columns=LIVE_COLUMNS["missions"],
                                    fmt=fmt, knobs=knobs))


_BUILDERS = {
    "mission_intake": _cards_section,
    "todos": _todos_section,
    "missions": _missions_section,
}


def collect_sections(knobs: BoardStateKnobs, *, cards_fn, todos_fn, missions_fn) -> list[BoardSection]:
    """Fetch + build one section per configured board. Each source is wrapped so a
    read failure becomes a loud ERROR section, not a missing/empty board."""
    fetchers = {"mission_intake": cards_fn, "todos": todos_fn, "missions": missions_fn}
    sections: list[BoardSection] = []
    for board in knobs.boards:
        try:
            rows = fetchers[board]()
            if not isinstance(rows, list):   # an action returned its error string
                raise RuntimeError(str(rows))
            sections.append(_BUILDERS[board](rows, knobs))
        except Exception as exc:
            sections.append(BoardSection(board, [], error=f"{type(exc).__name__}: {exc}"))
    return sections


def render_board_state(sections: list[BoardSection], knobs: BoardStateKnobs) -> str:
    """One compact block. Pure: same sections in → same string out."""
    lines = ["=== BOARD STATE (live, harness-provided — you do NOT need to call "
             "list_* to see this; terminal columns omitted) ==="]
    for sec in sections:
        if sec.error is not None:
            lines.append(f"{sec.board}: ERROR: {sec.error}")
            continue
        if not sec.groups:
            lines.append(f"{sec.board}: (no live items)")
            continue
        lines.append(f"{sec.board}:")
        for g in sec.groups:
            shown = "; ".join(g.items)
            more = f" (+{g.overflow} more)" if g.overflow else ""
            lines.append(f"  {g.column} ({len(g.items) + g.overflow}): {shown}{more}")
    lines.append("=== END BOARD STATE ===")
    return "\n".join(lines)


# The AppFlowy boards surfaced by the UI/snapshot, in display order. mission_intake
# (cards) + todos + dags are kanban-shaped; the research inboxes are triage lanes.
UI_BOARDS = ["mission_intake", "todos", "dags", "papers", "repos", "signals"]


def all_boards_json(boards: list[str] | None = None) -> list[dict]:
    """Structured read of each AppFlowy board for the UI snapshot — runs where
    growthos + AppFlowy creds live (the worker/curator), never in the UI container.
    Lazily imports growthos; per-board fail-loud: a board that can't be read returns
    {board, error}, never a silently-omitted board."""
    names = boards or UI_BOARDS
    try:
        from growthos import actions
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        return [{"board": b, "error": err} for b in names]
    out: list[dict] = []
    for b in names:
        try:
            out.append(actions.board_view(b))
        except Exception as exc:
            out.append({"board": b, "error": f"{type(exc).__name__}: {exc}"})
    return out


def collect_board_state(knobs: BoardStateKnobs) -> str:
    """Wire the real growthos.actions + Ledger fetchers and render. Imports growthos
    lazily (the gateway/assistant already put it on sys.path). Never raises: a
    whole-surface wiring failure (config/secrets) renders one loud ERROR line per
    board instead of an empty (misleading) block."""
    import httpx

    try:
        from growthos import actions
        from growthos.config import load_settings
        ledger = load_settings().ledger_base_url.rstrip("/")
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        return render_board_state(
            [BoardSection(b, [], error=err) for b in knobs.boards], knobs)

    def missions_fn() -> list[dict]:
        r = httpx.get(f"{ledger}/missions", timeout=15)
        r.raise_for_status()
        return r.json()

    sections = collect_sections(
        knobs,
        cards_fn=actions.list_cards,
        todos_fn=actions.list_todos,
        missions_fn=missions_fn,
    )
    return render_board_state(sections, knobs)
