"""Canary test from `cc pr-check-verify` proving the live PR/check loop.

Mission: llm_station-pr-check-20260619T122507591431Z
Branch:  mission/llm_station/pr-check/20260619T122507591431Z

Safe to delete after this PR has been reviewed.
"""
import tomllib
from pathlib import Path


def test_pr_check_canary_dev_extra_contains_fastapi():
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("fastapi>=") for dep in dev)
