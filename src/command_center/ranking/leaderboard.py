"""Evidence-backed executor ranking leaderboard (Phase 8).

Compares executors (Claude Code, Codex, OpenRouter model/harness pairs,
GatewayCore roles) across DISTINCT dimensions. The plan is emphatic: "Do not
collapse these into one unexplained 'best assistant' score." So:

  * Each dimension is ranked INDEPENDENTLY — there is no cross-dimension total,
    no "winner", no single scalar. `Leaderboard` has no such field by design.
  * Every ranked cell is backed by evidence (a value + sample_size + source).
    A cell with no evidence (or below the minimum sample size) is marked
    `insufficient` and is NOT given a rank — it is never guessed or zero-filled.
  * Direction is per-dimension (latency/cost are lower-better; quality/success
    are higher-better), so ranking is meaningful within each.

Pure functions over evidence samples — no network, no store. The endpoint
gathers the samples from whatever real evidence exists today (usage cost, probe
availability) and passes the rest through as "insufficient".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

Direction = Literal["higher_better", "lower_better"]


@dataclass(frozen=True)
class RankingDimension:
    id: str
    label: str
    direction: Direction
    unit: str


# The plan's dimensions — kept SEPARATE, never summed.
DIMENSIONS: tuple[RankingDimension, ...] = (
    RankingDimension("quality", "Quality", "higher_better", "score"),
    RankingDimension("serving_reliability", "Serving reliability", "higher_better", "%"),
    RankingDimension("tool_correctness", "Tool correctness", "higher_better", "%"),
    RankingDimension("task_success", "Repo-task success", "higher_better", "%"),
    RankingDimension("safety", "Safety", "higher_better", "score"),
    RankingDimension("latency", "Latency", "lower_better", "s"),
    RankingDimension("actual_cost", "Actual cost", "lower_better", "$"),
    RankingDimension("api_equivalent_cost", "API-equivalent cost", "lower_better", "$"),
    RankingDimension("usage_window_impact", "Usage-window impact", "lower_better", "%"),
    RankingDimension("review_quality", "Review quality", "higher_better", "score"),
    RankingDimension("post_merge_defects", "Post-merge defects", "lower_better", "count"),
)
_DIM_BY_ID = {d.id: d for d in DIMENSIONS}


@dataclass(frozen=True)
class EvidenceSample:
    """One observed measurement for an executor on a dimension."""
    executor: str
    dimension_id: str
    value: float
    sample_size: int
    source: str


@dataclass
class LeaderboardCell:
    executor: str
    value: float | None
    sample_size: int
    source: str | None
    rank: int | None            # None ⟺ insufficient (never guessed)
    insufficient: bool

    def to_dict(self) -> dict[str, Any]:
        return {"executor": self.executor, "value": self.value,
                "sample_size": self.sample_size, "source": self.source,
                "rank": self.rank, "insufficient": self.insufficient}


@dataclass
class DimensionRanking:
    dimension: RankingDimension
    cells: list[LeaderboardCell] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.dimension.id, "label": self.dimension.label,
                "direction": self.dimension.direction, "unit": self.dimension.unit,
                "cells": [c.to_dict() for c in self.cells]}


@dataclass
class Leaderboard:
    """Per-dimension rankings ONLY. There is deliberately no `overall`,
    `winner`, or `best` — collapsing the dimensions is forbidden."""
    dimensions: list[DimensionRanking] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"dimensions": [d.to_dict() for d in self.dimensions],
                "note": "dimensions are ranked independently; there is no single "
                        "'best executor' score — compare per dimension."}


def _aggregate(samples: Sequence[EvidenceSample]) -> tuple[float, int]:
    """Combine repeated samples for one executor+dimension: sample-size-weighted
    mean value, total sample size."""
    total_n = sum(max(s.sample_size, 0) for s in samples)
    if total_n <= 0:
        return (0.0, 0)
    weighted = sum(s.value * max(s.sample_size, 0) for s in samples)
    return (weighted / total_n, total_n)


def build_leaderboard(
    samples: Sequence[EvidenceSample],
    *,
    executors: Sequence[str] | None = None,
    min_sample_size: int = 1,
) -> Leaderboard:
    """Rank executors within each dimension from evidence. Executors with no
    (or too-little) evidence for a dimension appear as `insufficient` with no
    rank. Dimensions are never combined."""
    # the executor universe: explicit list, else everyone who has any evidence
    universe = list(executors) if executors is not None else sorted(
        {s.executor for s in samples})

    board = Leaderboard()
    for dim in DIMENSIONS:
        by_exec: dict[str, list[EvidenceSample]] = {}
        for s in samples:
            if s.dimension_id == dim.id:
                by_exec.setdefault(s.executor, []).append(s)

        cells: list[LeaderboardCell] = []
        rankable: list[LeaderboardCell] = []
        for executor in universe:
            ev = by_exec.get(executor, [])
            value, n = _aggregate(ev) if ev else (None, 0)
            insufficient = (not ev) or n < min_sample_size or value is None
            cell = LeaderboardCell(
                executor=executor,
                value=None if insufficient else round(value, 6),
                sample_size=n,
                source=(ev[0].source if ev else None),
                rank=None, insufficient=insufficient)
            cells.append(cell)
            if not insufficient:
                rankable.append(cell)

        # rank ONLY the cells with evidence, by this dimension's direction
        reverse = dim.direction == "higher_better"
        rankable.sort(key=lambda c: c.value, reverse=reverse)  # type: ignore[arg-type,return-value]
        prev_value: float | None = None
        prev_rank = 0
        for i, cell in enumerate(rankable, start=1):
            if prev_value is not None and cell.value == prev_value:
                cell.rank = prev_rank            # ties share a rank
            else:
                cell.rank = i
                prev_rank = i
            prev_value = cell.value

        # stable display order: ranked first (by rank), then insufficient
        cells.sort(key=lambda c: (c.rank is None, c.rank or 0, c.executor))
        board.dimensions.append(DimensionRanking(dimension=dim, cells=cells))
    return board
