"""Hermetic tests for the local pre-push merge guard."""
from __future__ import annotations

import subprocess
from pathlib import Path

from command_center.cli import merge_guard


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_guard_hook_blocks_protected_branches_only():
    hook = merge_guard.guard_hook(["main", "release"])
    assert merge_guard.GUARD_MARKER in hook
    assert "refs/heads/main)" in hook and "refs/heads/release)" in hook
    # a feature branch is not named -> falls through to exit 0
    assert "refs/heads/feature" not in hook


def test_guard_hook_actually_rejects_main_and_allows_feature(tmp_path):
    import shutil
    sh = shutil.which("bash") or shutil.which("sh")
    if not sh:  # POSIX shell required to execute the hook (always present in CI)
        import pytest
        pytest.skip("no POSIX shell available to execute the pre-push hook")
    hook = tmp_path / "pre-push"
    hook.write_text(merge_guard.guard_hook(["main"]), encoding="utf-8")
    # forward-slash path so Git Bash on Windows resolves it (backslashes mangle)
    blocked = subprocess.run([sh, hook.as_posix(), "origin", "url"],
                             input="refs/heads/x abc refs/heads/main def\n",
                             capture_output=True, text=True)
    assert blocked.returncode == 1 and "blocked" in blocked.stderr
    allowed = subprocess.run([sh, hook.as_posix(), "origin", "url"],
                             input="refs/heads/x abc refs/heads/x def\n",
                             capture_output=True, text=True)
    assert allowed.returncode == 0


def test_verify_guard_states(tmp_path):
    # not a git repo
    ok, detail = merge_guard.verify_guard(tmp_path)
    assert not ok and "not_a_git_repo" in detail
    _git_init(tmp_path)
    # git repo, no hook
    ok, detail = merge_guard.verify_guard(tmp_path)
    assert not ok and detail == "pre_push_hook_absent"
    # a non-guard hook present
    merge_guard._hook_path(tmp_path).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ok, detail = merge_guard.verify_guard(tmp_path)
    assert not ok and detail == "pre_push_hook_present_but_not_merge_guard"
    # the real guard installed
    merge_guard._hook_path(tmp_path).write_text(
        merge_guard.guard_hook(["main"]), encoding="utf-8")
    ok, detail = merge_guard.verify_guard(tmp_path)
    assert ok and "merge_guard_installed" in detail


def test_verify_guard_unresolved_path():
    ok, detail = merge_guard.verify_guard(None)
    assert not ok and detail == "repo_path_unresolved"
