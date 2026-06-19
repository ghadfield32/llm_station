"""Canary test from `cc pr-check-verify` proving the live PR check loop.

Mission: llm_station-pr-check-20260619T030156513059Z
Branch:  mission/llm_station/pr-check/20260619T030156513059Z

Re-asserts that the llm_station repo manifest stays feature-branch-only.
Safe to delete after this PR has been reviewed.
"""
from pathlib import Path

import yaml

from command_center.schemas import AutonomyConfig


def test_pr_check_canary_repo_manifest_feature_branch_only():
    root = Path(__file__).resolve().parents[1]
    cfg = AutonomyConfig.model_validate(
        yaml.safe_load(
            (root / "configs" / "autonomy.yaml").read_text(encoding="utf-8")
        )
    )
    repo = next(r for r in cfg.repo_manifests if r.repo_id == "llm_station")
    assert repo.branch_write_policy == "feature_branch_only"
    assert repo.default_branch in repo.allowed_base_branches
