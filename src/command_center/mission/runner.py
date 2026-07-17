"""Phase 7 mission RUNNER — orchestrate the reviewed gate core over a real
leased worktree and produce a LOCAL draft-PR artifact.

Approved first slice (signed off): local artifact only, NO push/PR/merge,
flag-gated (KANBAN_UI_MISSION_EXECUTION off by default), Claude Code implements /
Codex reviews. This module is thin orchestration over mission/execution.py (the
independently-reviewed gate core); every risky primitive lives there.

All the moving parts are INJECTABLE seams so the whole loop is testable with no
real git and no LLM, and a throwaway-git integration test can drive the real
loop:

  * worktree_factory(repo_root, branch, base_sha) -> (worktree_root, cleanup)
  * executor_fn(lease) -> None              # the bounded change
  * validator_fn(worktree_root) -> list     # the repo's DECLARED test commands
  * differ(worktree_root) -> (text, files)  # real: `git diff`
  * review_fn(implementer, reviewer, frozen) -> MissionReview
  * now() -> float

Post-execution verification is critical: a DELEGATED executor (a real Claude
Code CLI writing straight to the worktree) does not go through guarded_write, so
after it runs we independently verify the resulting diff touched only in-scope,
non-secret files and left the primary checkout unchanged. guarded_write remains
the path for our own direct writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..agent_sessions.secret_paths import is_secret_path
from ..kanban_sync.events import GovernanceViolation
from .execution import (
    DraftPRArtifact,
    MissionReview,
    WorktreeLease,
    assert_branch_allowed,
    assert_execution_enabled,
    build_draft_pr_artifact,
    freeze_diff,
)


@dataclass(frozen=True)
class MissionRequest:
    mission_id: str
    repo_root: Path                    # the PRIMARY checkout — never written
    branch: str                        # feature branch (validated)
    base_sha: str
    scope: tuple[str, ...]             # allowed write prefixes
    task: str                          # what the executor should do
    title: str
    implementer: str                   # e.g. claude_code_local
    reviewer: str                      # e.g. codex_agent (must differ)


@dataclass
class MissionResult:
    mission_id: str
    artifact: DraftPRArtifact | None = None
    validations: list[dict[str, Any]] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    refused: str | None = None         # gate/validation refusal (no artifact)

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id,
                "artifact": self.artifact.to_dict() if self.artifact else None,
                "validations": self.validations,
                "changed_files": self.changed_files, "refused": self.refused}


def _verify_diff_safe(files: Sequence[str], scope: tuple[str, ...]) -> None:
    """Post-execution gate — independent of how the executor wrote. Every changed
    file must be non-secret AND within the lease scope. Catches a delegated CLI
    executor that wrote a secret or an out-of-scope file (it bypassed
    guarded_write)."""
    prefixes = tuple(p.replace("\\", "/").rstrip("/") + "/" for p in scope)
    for f in files:
        rel = f.replace("\\", "/")
        if is_secret_path(rel):
            raise GovernanceViolation(
                f"refused: the change touched a secret/credential file {f!r}")
        if prefixes and not any(rel.startswith(p) for p in prefixes):
            raise GovernanceViolation(
                f"refused: the change touched {f!r} outside the lease scope {scope}")


ExecutorFn = Callable[[WorktreeLease], None]
ValidatorFn = Callable[[Path], "list[dict[str, Any]]"]
Differ = Callable[[Path], "tuple[str, Sequence[str]]"]
ReviewFn = Callable[[str, str, Any], MissionReview]
WorktreeFactory = Callable[[Path, str, str], "tuple[Path, Callable[[], None]]"]


def run_local_mission(
    req: MissionRequest, *,
    worktree_factory: WorktreeFactory,
    executor_fn: ExecutorFn,
    validator_fn: ValidatorFn,
    differ: Differ,
    review_fn: ReviewFn,
    now: Callable[[], float],
    lease_ttl_seconds: float = 900.0,
) -> MissionResult:
    """Run one governed mission to a LOCAL draft-PR artifact. Never pushes,
    opens a PR, or merges. Cleans up the worktree even on failure."""
    assert_execution_enabled()               # flag gate — fails closed
    assert_branch_allowed(req.branch)         # gate 2 — before any worktree
    worktree_root, cleanup = worktree_factory(req.repo_root, req.branch, req.base_sha)
    try:
        lease = WorktreeLease(
            mission_id=req.mission_id, worktree_root=worktree_root,
            branch=req.branch, base_sha=req.base_sha,
            primary_checkout_root=req.repo_root, scope=req.scope,
            expires_at=now() + lease_ttl_seconds)

        executor_fn(lease)                    # the bounded change (in the worktree)

        # freeze + post-execution verification (covers a delegated executor)
        frozen = freeze_diff(lease, differ=differ, created_at=_iso(now))
        _verify_diff_safe(frozen.files, req.scope)
        changed = list(frozen.files)

        # the repo's DECLARED tests, in the worktree; a failure blocks the artifact
        validations = validator_fn(worktree_root)
        if any(v.get("exit_code", 1) != 0 for v in validations):
            return MissionResult(mission_id=req.mission_id, validations=validations,
                                 changed_files=changed,
                                 refused="declared tests failed — no artifact")

        review = review_fn(req.implementer, req.reviewer, frozen)
        artifact = build_draft_pr_artifact(
            lease, frozen, review, differ=differ, title=req.title,
            body=_artifact_body(req, changed, validations))
        return MissionResult(mission_id=req.mission_id, artifact=artifact,
                             validations=validations, changed_files=changed)
    finally:
        cleanup()                             # git worktree remove — always


def _iso(now: Callable[[], float]) -> str:
    # a string stamp derived from the injected clock (no wall-clock import here)
    return f"t{int(now())}"


def _artifact_body(req: MissionRequest, changed: Sequence[str],
                   validations: Sequence[dict[str, Any]]) -> str:
    lines = [
        f"Mission {req.mission_id}: {req.task}",
        f"Branch: {req.branch}  (base {req.base_sha})",
        f"Implementer: {req.implementer}  ·  Reviewer: {req.reviewer}",
        "", "Changed files:", *[f"  - {f}" for f in changed],
        "", "Declared validations:",
        *[f"  - exit={v.get('exit_code')} {v.get('command', '')}" for v in validations],
        "", "This is a LOCAL draft-PR artifact — not pushed, not opened, not merged.",
    ]
    return "\n".join(lines)
