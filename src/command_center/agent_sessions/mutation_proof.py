"""Repository mutation-proof snapshot — captures git HEAD/branch/status/worktree
state plus tracked+untracked file hashes, so a real harness run against a real
repo can be PROVEN to have made zero filesystem changes, not just assumed. Used
by the Codex Agent (and later Claude Agent) live acceptance runs — see
WORKLOG.md "Agent-session chat integration".
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepoSnapshot:
    head: str
    branch: str
    status_porcelain: str
    worktree_list: str
    file_hashes: dict[str, str]

    def diff(self, other: "RepoSnapshot") -> list[str]:
        """Human-readable problems, empty list = proven no mutation."""
        problems: list[str] = []
        if self.head != other.head:
            problems.append(f"HEAD changed: {self.head} -> {other.head}")
        if self.branch != other.branch:
            problems.append(f"branch changed: {self.branch!r} -> {other.branch!r}")
        if self.status_porcelain != other.status_porcelain:
            problems.append(
                "git status changed:\n"
                f"  before: {self.status_porcelain!r}\n"
                f"  after:  {other.status_porcelain!r}")
        if self.worktree_list != other.worktree_list:
            problems.append("git worktree list changed")
        before_files, after_files = set(self.file_hashes), set(other.file_hashes)
        added = after_files - before_files
        removed = before_files - after_files
        changed = {f for f in (before_files & after_files)
                  if self.file_hashes[f] != other.file_hashes[f]}
        if added:
            problems.append(f"new files: {sorted(added)}")
        if removed:
            problems.append(f"removed files: {sorted(removed)}")
        if changed:
            problems.append(f"changed files: {sorted(changed)}")
        return problems


def _run(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def snapshot(repo_root: Path) -> RepoSnapshot:
    """Real git state + real file content hashes — never assumed, always
    freshly computed. Deliberately hashes both tracked AND untracked files
    (an agent creating a new untracked file is still a mutation)."""
    head = _run(["git", "rev-parse", "HEAD"], repo_root)
    branch = _run(["git", "branch", "--show-current"], repo_root)
    status = _run(["git", "status", "--porcelain=v1"], repo_root)
    worktrees = _run(["git", "worktree", "list"], repo_root)
    tracked = _run(["git", "ls-files"], repo_root).splitlines()
    untracked = _run(
        ["git", "ls-files", "--others", "--exclude-standard"], repo_root).splitlines()
    hashes: dict[str, str] = {}
    for rel in (*tracked, *untracked):
        path = repo_root / rel
        if not path.is_file():
            continue
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return RepoSnapshot(head=head, branch=branch, status_porcelain=status,
                        worktree_list=worktrees, file_hashes=hashes)
