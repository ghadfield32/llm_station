"""Bounded branch-only repo mission tests."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from command_center.cli.branch_mission import execute_branch_mission

REPO_ROOT = Path(__file__).resolve().parents[1]


def _raw_config(ci_commands: list[str]) -> dict:
    raw = yaml.safe_load((REPO_ROOT / "configs" / "autonomy.yaml").read_text(encoding="utf-8"))
    raw["repo_manifests"][0]["ci_commands"] = ci_commands
    return raw


def _git(root: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def _write_repo(root: Path, raw: dict) -> Path:
    (root / "configs").mkdir(parents=True)
    (root / ".devcontainer").mkdir()
    (root / ".github").mkdir()
    (root / "docs").mkdir()
    (root / "scripts").mkdir()
    (root / "configs" / "autonomy.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )
    (root / ".devcontainer" / "devcontainer.json").write_text("{}", encoding="utf-8")
    (root / ".github" / "CODEOWNERS").write_text("* @ghadfield32\n", encoding="utf-8")
    (root / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")
    (root / "scripts" / "assert_no_secret_env.py").write_text(
        "\n".join([
            "import os",
            "assert 'GITHUB_OWNER_ADMIN_TOKEN' not in os.environ",
        ]),
        encoding="utf-8",
    )
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Branch Mission Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    return root / "configs" / "autonomy.yaml"


def test_branch_mission_creates_docs_only_worktree_and_strips_secret_env(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    config = _write_repo(root, _raw_config(["python scripts/assert_no_secret_env.py"]))
    output = tmp_path / "evidence" / "branch-mission.json"
    monkeypatch.setenv("GITHUB_OWNER_ADMIN_TOKEN", "super-secret-value")

    result = execute_branch_mission(
        root=root,
        config_path=config,
        output=output,
        worktree_root=tmp_path / "worktrees",
        mission_id="mission-test-pass",
        now=datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc),
    )
    saved = output.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["docs_only"] is True
    assert result["changed_paths"] == ["docs/branch-mission-smoke.md"]
    assert result["github_policy"]["push_performed"] is False
    assert result["github_policy"]["pr_created"] is False
    assert result["github_policy"]["merge_performed"] is False
    assert result["privacy"]["secret_values_retained"] is False
    assert "GITHUB_OWNER_ADMIN_TOKEN" in result["privacy"]["secret_env_var_names_removed"]
    assert "super-secret-value" not in saved
    assert "mission.forecast" in saved
    assert "mission.verification" in saved


def test_branch_mission_blocks_when_declared_validation_command_fails(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    config = _write_repo(root, _raw_config(["git not-a-real-subcommand"]))

    result = execute_branch_mission(
        root=root,
        config_path=config,
        output=tmp_path / "branch-mission.json",
        worktree_root=tmp_path / "worktrees",
        mission_id="mission-test-blocked",
        now=datetime(2026, 6, 18, 12, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "blocked"
    assert result["ci_results"][0]["status"] == "blocked"
    assert "declared_validation_command_failed_1" in result["blockers"]
    assert result["completion_verdict"]["status"] == "BLOCKED"
    assert result["github_policy"]["push_performed"] is False
    assert result["github_policy"]["pr_created"] is False
    assert result["github_policy"]["merge_performed"] is False
