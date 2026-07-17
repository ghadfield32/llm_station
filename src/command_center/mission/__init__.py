"""Governed mission execution (Phase 7).

The gate-enforced core that turns an approved task into a bounded code change in
a LEASED WORKTREE, freezes the diff, records an independent advisory review, and
produces a LOCAL draft-PR artifact — with zero primary-checkout writes, zero
protected-branch writes, zero unleased writes, zero agent merges, zero secret
leaks, and no silent permission widening. Off by default; see execution.py.
"""
from .execution import (
    MISSION_EXECUTION_ENABLED,
    DraftPRArtifact,
    FrozenDiff,
    MissionReview,
    WorktreeLease,
    assert_branch_allowed,
    assert_execution_enabled,
    build_draft_pr_artifact,
    freeze_diff,
    guarded_write,
    record_review,
    verify_diff_unchanged,
)

from .runner import MissionRequest, MissionResult, run_local_mission

__all__ = [
    "MISSION_EXECUTION_ENABLED", "DraftPRArtifact", "FrozenDiff", "MissionReview",
    "WorktreeLease", "assert_branch_allowed", "assert_execution_enabled",
    "build_draft_pr_artifact", "freeze_diff", "guarded_write", "record_review",
    "verify_diff_unchanged",
    "MissionRequest", "MissionResult", "run_local_mission",
]
