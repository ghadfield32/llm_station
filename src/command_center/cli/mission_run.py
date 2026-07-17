"""cc mission-run — flag-gated governed mission execution (Phase 7, first slice).

Default `--self-check`: proves the ENTIRE governed loop end-to-end on the
operator's own machine, safely — it stands up a THROWAWAY git repo, leases a
worktree, makes a bounded code change (deterministic, no LLM/quota), runs a
declared check, freezes the diff, records an independent advisory review, and
emits a LOCAL draft-PR artifact — then cleans up. Nothing is pushed, opened, or
merged; the primary checkout is untouched (it's a throwaway repo anyway).

Fails closed: refuses unless KANBAN_UI_MISSION_EXECUTION=1.

A real mission (a real repo + a real Claude Code executor) is the documented
next step: swap the deterministic executor for a `claude_code_executor(lease,
task)` adapter (resolve the Claude CLI invocation against the installed version
at wiring time — never hardcode it), keeping every gate + the post-execution
verification the runner already enforces.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _self_check() -> int:
    from command_center.mission.execution import record_review
    from command_center.mission.git_backend import (
        declared_validator,
        deterministic_executor,
        git_differ,
        git_worktree_factory,
    )
    from command_center.mission.runner import MissionRequest, run_local_mission

    if shutil.which("git") is None:
        print("mission-run: FAIL — git is not on PATH")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="cc-mission-selfcheck-"))
    try:
        repo = tmp / "repo"
        repo.mkdir()

        def g(*a: str) -> None:
            subprocess.run(["git", *a], cwd=repo, check=True,
                           capture_output=True, text=True)

        g("init", "-b", "main")
        g("config", "user.email", "selfcheck@local")
        g("config", "user.name", "selfcheck")
        (repo / "src").mkdir()
        (repo / "src" / "seed.py").write_text("x = 0\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-m", "seed")
        base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                  capture_output=True, text=True).stdout.strip()

        req = MissionRequest(
            mission_id="M-selfcheck", repo_root=repo, branch="mission/selfcheck",
            base_sha=base_sha, scope=("src/",),
            task="add a helper (self-check, deterministic)", title="Self-check",
            implementer="claude_code_local", reviewer="codex_agent")

        def review(implementer: str, reviewer: str, _frozen: object):
            return record_review(implementer=implementer, reviewer=reviewer,
                                 status="reviewed", summary="self-check advisory")

        result = run_local_mission(
            req,
            worktree_factory=git_worktree_factory(tmp / "worktrees"),
            executor_fn=deterministic_executor(
                {"src/helper.py": "def helper():\n    return 42\n"}),
            validator_fn=declared_validator(['python -c "import sys; sys.exit(0)"']),
            differ=git_differ, review_fn=review, now=time.time)

        primary_clean = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo,
            capture_output=True, text=True).stdout.strip() == ""
        ok = (result.artifact is not None and primary_clean
              and not (repo / "src" / "helper.py").exists())
        print(json.dumps({
            "self_check": "pass" if ok else "fail",
            "artifact_produced": result.artifact is not None,
            "changed_files": result.changed_files,
            "validations": result.validations,
            "pushed": result.artifact.pushed if result.artifact else None,
            "merged": result.artifact.merged if result.artifact else None,
            "primary_checkout_clean": primary_clean,
            "refused": result.refused,
        }, indent=2))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", default=True,
                        help="run the throwaway-repo governed-loop proof (default)")
    parser.parse_args(argv)

    from command_center.mission.execution import assert_execution_enabled
    from command_center.kanban_sync.events import GovernanceViolation
    try:
        assert_execution_enabled()
    except GovernanceViolation as exc:
        print(f"mission-run: DISABLED — {exc}")
        return 1
    return _self_check()


if __name__ == "__main__":
    sys.exit(run())
