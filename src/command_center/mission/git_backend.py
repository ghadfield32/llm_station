"""Real-git seams for the mission runner (Phase 7).

These fill the runner's injectable seams with actual git: a leased worktree via
`git worktree add`, a diff via `git diff`, and the repo's declared validation
commands. A deterministic executor is provided for the live acceptance (writes
via the gate core's guarded_write, no LLM, no quota).

The LIVE-LLM executor is a documented CONTRACT, not shipped here: a
`claude_code_executor(lease, task)` would run the Claude Code CLI with cwd set
to the leased worktree, in write mode scoped to that worktree. Its exact CLI
flags must be resolved against the installed Claude version at wiring time (per
the workflow standard: never hardcode a CLI/model invocation from memory). A
delegated CLI executor's writes do NOT pass through guarded_write, so the runner
independently re-verifies the resulting diff (secret/scope) after it runs.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

from .execution import WorktreeLease, guarded_write


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), check=False,
                          capture_output=True, text=True)


def git_worktree_factory(
    worktrees_root: Path,
) -> Callable[[Path, str, str], "tuple[Path, Callable[[], None]]"]:
    """Build a worktree_factory that creates leased worktrees UNDER
    `worktrees_root` (which MUST be outside the primary checkout, so a mission
    worktree can never be the primary tree). Returns (worktree_root, cleanup)."""
    def factory(repo_root: Path, branch: str, base_sha: str):
        worktrees_root.mkdir(parents=True, exist_ok=True)
        wt = worktrees_root / f"{branch.replace('/', '_')}-{base_sha[:8]}"
        # create the worktree on a NEW feature branch from base_sha
        res = _git(["worktree", "add", "-b", branch, str(wt), base_sha], repo_root)
        if res.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {res.stderr.strip()}")

        def cleanup() -> None:
            _git(["worktree", "remove", "--force", str(wt)], repo_root)
            _git(["branch", "-D", branch], repo_root)   # drop the throwaway branch
        return wt, cleanup
    return factory


def git_differ(worktree_root: Path) -> "tuple[str, Sequence[str]]":
    """The worktree diff (staged, so new files are included). Stages into the
    worktree's own index only — never touches the primary checkout."""
    _git(["add", "-A"], worktree_root)
    text = _git(["diff", "--cached"], worktree_root).stdout
    names = _git(["diff", "--cached", "--name-only"], worktree_root).stdout
    files = [ln.strip() for ln in names.splitlines() if ln.strip()]
    return text, files


def declared_validator(
    commands: Sequence[str],
) -> Callable[[Path], "list[dict[str, Any]]"]:
    """Build a validator that runs the repo's DECLARED commands in the worktree.
    Records exit code + a redacted evidence summary (not raw output)."""
    def validate(worktree_root: Path) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for cmd in commands:
            res = subprocess.run(cmd, cwd=str(worktree_root), shell=True,
                                 check=False, capture_output=True, text=True)
            out.append({"command": cmd, "exit_code": res.returncode,
                        "stdout_lines": len((res.stdout or "").splitlines()),
                        "stderr_lines": len((res.stderr or "").splitlines())})
        return out
    return validate


def deterministic_executor(
    writes: dict[str, str], *, now: float = 0.0,
) -> Callable[[WorktreeLease], None]:
    """A no-LLM executor for the live acceptance: writes the given
    {rel_path: content} via the gate core's guarded_write (so it is itself fully
    gated). This is what proves the real loop without quota."""
    def execute(lease: WorktreeLease) -> None:
        for rel, content in writes.items():
            guarded_write(lease, rel, content, now=now)
    return execute
