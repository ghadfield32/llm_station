"""Executor ranking — the evidence-backed, multi-dimensional leaderboard.

Phase 8's rule (do NOT violate): keep the dimensions SEPARATE and never collapse
them into one unexplained "best assistant" score. This package ranks executors
WITHIN each dimension only, from real evidence, and marks a dimension
"insufficient evidence" rather than guessing.
"""
from .leaderboard import (
    DIMENSIONS,
    DimensionRanking,
    EvidenceSample,
    Leaderboard,
    LeaderboardCell,
    RankingDimension,
    build_leaderboard,
)

__all__ = [
    "DIMENSIONS", "DimensionRanking", "EvidenceSample", "Leaderboard",
    "LeaderboardCell", "RankingDimension", "build_leaderboard",
]
