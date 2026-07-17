"""Phase 8 executor-ranking leaderboard — dimensions kept SEPARATE, evidence-
backed, never collapsed into one 'best' score, insufficient evidence never
guessed."""
from __future__ import annotations

from dataclasses import fields

from command_center.ranking import (
    DIMENSIONS,
    EvidenceSample,
    Leaderboard,
    build_leaderboard,
)


def _s(executor, dim, value, n=5, source="test"):
    return EvidenceSample(executor=executor, dimension_id=dim, value=value,
                          sample_size=n, source=source)


def test_never_collapses_into_a_single_best_score():
    # THE plan invariant: no overall/winner/best field exists anywhere.
    board_fields = {f.name for f in fields(Leaderboard)}
    assert board_fields == {"dimensions"}
    d = build_leaderboard([]).to_dict()
    assert "overall" not in d and "winner" not in d and "best" not in d
    assert "no single" in d["note"].lower()


def test_higher_better_dimension_ranks_descending():
    board = build_leaderboard([
        _s("codex_agent", "task_success", 0.9),
        _s("claude_code_local", "task_success", 0.7),
        _s("openrouter_agent", "task_success", 0.8),
    ])
    dim = next(d for d in board.dimensions if d.dimension.id == "task_success")
    ranked = [(c.executor, c.rank) for c in dim.cells]
    assert ranked[0] == ("codex_agent", 1)      # highest success ranks #1
    assert ("claude_code_local", 3) in ranked   # lowest ranks last


def test_lower_better_dimension_ranks_ascending():
    board = build_leaderboard([
        _s("codex_agent", "actual_cost", 0.50),
        _s("openrouter_agent", "actual_cost", 0.08),
        _s("claude_code_local", "actual_cost", 0.00),
    ])
    dim = next(d for d in board.dimensions if d.dimension.id == "actual_cost")
    top = dim.cells[0]
    assert top.executor == "claude_code_local" and top.rank == 1   # cheapest #1


def test_insufficient_evidence_is_marked_not_guessed():
    board = build_leaderboard(
        [_s("codex_agent", "quality", 0.9, n=10)],
        executors=["codex_agent", "claude_code_local"], min_sample_size=1)
    dim = next(d for d in board.dimensions if d.dimension.id == "quality")
    cells = {c.executor: c for c in dim.cells}
    assert cells["codex_agent"].rank == 1 and cells["codex_agent"].value == 0.9
    # the executor with NO evidence is insufficient — no value, no rank, not 0
    assert cells["claude_code_local"].insufficient is True
    assert cells["claude_code_local"].value is None
    assert cells["claude_code_local"].rank is None


def test_below_min_sample_size_is_insufficient():
    board = build_leaderboard([_s("codex_agent", "quality", 0.9, n=2)],
                              min_sample_size=5)
    dim = next(d for d in board.dimensions if d.dimension.id == "quality")
    assert dim.cells[0].insufficient is True and dim.cells[0].rank is None


def test_repeated_samples_are_sample_size_weighted():
    board = build_leaderboard([
        _s("codex_agent", "latency", 2.0, n=1),
        _s("codex_agent", "latency", 4.0, n=3),   # weighted mean = (2+12)/4 = 3.5
    ])
    dim = next(d for d in board.dimensions if d.dimension.id == "latency")
    cell = dim.cells[0]
    assert cell.value == 3.5 and cell.sample_size == 4


def test_ties_share_a_rank():
    board = build_leaderboard([
        _s("a", "safety", 1.0), _s("b", "safety", 1.0), _s("c", "safety", 0.5)])
    dim = next(d for d in board.dimensions if d.dimension.id == "safety")
    ranks = {c.executor: c.rank for c in dim.cells}
    assert ranks["a"] == 1 and ranks["b"] == 1 and ranks["c"] == 3


def test_all_dimensions_present_even_with_no_evidence():
    board = build_leaderboard([], executors=["codex_agent"])
    assert len(board.dimensions) == len(DIMENSIONS)
    # every cell insufficient, none ranked — honest empty state
    for d in board.dimensions:
        assert all(c.insufficient and c.rank is None for c in d.cells)
