"""Phase 7 governed mission execution — the gate-enforced core.

Approved (per PHASE7_MISSION_EXECUTION_GATE_DESIGN.md, signed off): first slice
is a bounded CODE change in a leased worktree + frozen diff + independent
advisory review + a LOCAL draft-PR artifact — NO push, NO PR creation, NO merge.
Off by default (KANBAN_UI_MISSION_EXECUTION), fails closed.

Every function here is pure/injectable so the six zero-tolerance gates are
hermetically testable with no real git and no real agent write:

  1. primary-checkout writes = 0   — guarded_write clamps to the leased worktree
                                      and denies the primary checkout root.
  2. protected-branch writes = 0   — assert_branch_allowed rejects main/protected.
  3. unleased writes = 0           — guarded_write refuses once the lease expires.
  4. agent merges = 0              — the artifact is always pushed=False,
                                      merged=False; no push/merge function exists.
  5. secret leaks = 0              — is_secret_path denies .env/keys on write.
  6. silent permission widening=0  — the lease (and its scope) is frozen; no code
                                      broadens it in place.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..agent_sessions.secret_paths import is_secret_path
from ..kanban_sync.events import GovernanceViolation

# Third opt-in (on top of the existing autonomy switches). OFF by default.
MISSION_EXECUTION_ENABLED = os.environ.get("KANBAN_UI_MISSION_EXECUTION", "") == "1"

# Branches a mission may never write (first path segment matched after
# normalization, so release/* is covered).
_PROTECTED_BRANCHES = frozenset(
    {"main", "master", "trunk", "prod", "production", "release", "develop"})

# The ONLY advisory statuses a mission review may carry. Approve/merge/etc. are
# not representable — a human merges, an agent never does.
_ADVISORY_REVIEW_STATUSES = frozenset({"reviewed", "changes_requested"})


def _normalize_branch(branch: str) -> str:
    """Lowercase, strip, and drop ref prefixes so 'refs/heads/main' and 'Main'
    both normalize to 'main' (review finding #3)."""
    b = (branch or "").strip().lower()
    for prefix in ("refs/heads/", "refs/remotes/", "refs/", "heads/", "remotes/"):
        if b.startswith(prefix):
            b = b[len(prefix):]
            break
    return b


def assert_execution_enabled() -> None:
    """The fail-closed gate: mission execution is refused unless the operator
    opted in. Callers MUST invoke this before any lease/write."""
    if not MISSION_EXECUTION_ENABLED:
        raise GovernanceViolation(
            "mission execution is disabled — set KANBAN_UI_MISSION_EXECUTION=1 "
            "to enable (fails closed by design)")


def assert_branch_allowed(branch: str) -> None:
    """Gate 2: a mission branch is a feature branch, never a protected one.
    Normalizes ref-forms + matches the FIRST path segment, so 'refs/heads/main',
    'Main', 'release/1.2' are all caught (review finding #3)."""
    norm = _normalize_branch(branch)
    if not norm:
        raise GovernanceViolation("mission branch is required")
    segments = norm.split("/")
    # match the whole name, the FIRST segment (release/1.2), AND the LAST segment
    # (origin/main, refs/remotes/upstream/master → leaf 'main'/'master'). The
    # leaf check closes the remote-tracking-ref class (re-review residual #3).
    if (norm in _PROTECTED_BRANCHES or segments[0] in _PROTECTED_BRANCHES
            or segments[-1] in _PROTECTED_BRANCHES):
        raise GovernanceViolation(
            f"branch {branch!r} is protected — missions write feature branches only")


@dataclass(frozen=True)
class WorktreeLease:
    """A time-boxed, fixed-scope write grant for one mission. Frozen: no code
    path can broaden it in place (gate 6) — a wider scope needs a new lease from
    a new human-approved mission."""
    mission_id: str
    worktree_root: Path
    branch: str
    base_sha: str
    primary_checkout_root: Path       # the root a mission may NEVER write
    scope: tuple[str, ...]            # allowed repo-relative write prefixes
    expires_at: float                 # epoch seconds; write refused once passed


def guarded_write(
    lease: WorktreeLease, rel_path: str, content: str, *, now: float,
) -> Path:
    """The ONE write primitive. Enforces gates 1/3/5/6 before touching disk;
    raises GovernanceViolation (never writes) on any violation."""
    # gate 3 — the lease must be live
    if now >= lease.expires_at:
        raise GovernanceViolation(
            f"lease for {lease.mission_id} expired — no unleased writes")
    # gate 5 — never a secret path (by relative form)
    if is_secret_path(rel_path):
        raise GovernanceViolation(f"refused: secret/credential path {rel_path!r}")
    # gate 1 — clamp inside the leased worktree (no .. / symlink escape)
    root = lease.worktree_root.resolve()
    target = (lease.worktree_root / rel_path).resolve()
    if target != root and root not in target.parents:
        raise GovernanceViolation(f"path {rel_path!r} escapes the leased worktree")
    # gate 1 — and never the primary checkout, even if the worktree nests oddly
    primary = lease.primary_checkout_root.resolve()
    if target == primary or primary in target.parents:
        raise GovernanceViolation("refused: would write the primary checkout")
    # gate 5 — the resolved absolute path is not a secret either
    if is_secret_path(str(target)):
        raise GovernanceViolation("refused: secret/credential path (resolved)")
    # gate 6 — within the lease's fixed scope. Check the CLAMPED/resolved relative
    # path (not the raw input, which '..' already can't escape past above), and
    # anchor each prefix with a trailing '/', so scope=('src',) can't leak into
    # 'src-evil/' (review finding #4). An empty scope grants nothing.
    if not lease.scope:
        raise GovernanceViolation("lease has no write scope — nothing is writable")
    rel_resolved = target.relative_to(root).as_posix()
    prefixes = tuple(p.replace("\\", "/").rstrip("/") + "/" for p in lease.scope)
    if not any(rel_resolved.startswith(p) for p in prefixes):
        raise GovernanceViolation(
            f"path {rel_resolved!r} is outside the lease scope {lease.scope}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


Differ = Callable[[Path], "tuple[str, Sequence[str]]"]


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrozenDiff:
    mission_id: str
    diff_digest: str
    files: tuple[str, ...]
    created_at: str


def freeze_diff(lease: WorktreeLease, *, differ: Differ, created_at: str) -> FrozenDiff:
    """Hash + freeze the worktree diff. `differ(worktree_root) -> (text, files)`
    is injected (real: `git diff` in the worktree). The digest is what the
    reviewer and artifact bind to."""
    diff_text, files = differ(lease.worktree_root)
    return FrozenDiff(mission_id=lease.mission_id, diff_digest=_sha256(diff_text),
                      files=tuple(files), created_at=created_at)


def verify_diff_unchanged(lease: WorktreeLease, frozen: FrozenDiff, *,
                          differ: Differ) -> None:
    """Refuse if the worktree diff changed after the freeze — a post-freeze
    mutation must trigger a fresh review, never ride the old approval."""
    diff_text, _ = differ(lease.worktree_root)
    if _sha256(diff_text) != frozen.diff_digest:
        raise GovernanceViolation(
            "diff changed after freeze — re-freeze and re-review before a PR")


@dataclass(frozen=True)
class MissionReview:
    reviewer: str
    status: str                       # advisory: reviewed | changes_requested
    summary: str
    findings: tuple[str, ...] = ()


def record_review(*, implementer: str, reviewer: str, status: str, summary: str,
                  findings: Sequence[str] = ()) -> MissionReview:
    """Record an INDEPENDENT advisory review of the frozen diff. The reviewer
    must differ from the implementer (case-insensitively), and the status must be
    one of the advisory set — approve/merge/etc. are not accepted in ANY casing
    (review findings #2, reviewer-casing)."""
    if not reviewer.strip() or reviewer.strip().casefold() == implementer.strip().casefold():
        raise GovernanceViolation(
            "mission review must be by a DIFFERENT executor than the implementer")
    status_norm = (status or "").strip().casefold()
    if status_norm not in _ADVISORY_REVIEW_STATUSES:
        raise GovernanceViolation(
            f"mission review status must be advisory "
            f"({', '.join(sorted(_ADVISORY_REVIEW_STATUSES))}) — {status!r} is not "
            f"accepted; reviews never approve/merge, a human does")
    return MissionReview(reviewer=reviewer, status=status_norm, summary=summary,
                         findings=tuple(findings))


@dataclass(frozen=True)
class DraftPRArtifact:
    """A LOCAL draft-PR artifact — the terminus of the first slice. It is never
    pushed, opened, or merged (gate 4): pushed/merged are hard-wired False."""
    mission_id: str
    branch: str
    base_sha: str
    title: str
    body: str
    diff_digest: str
    review: dict[str, Any]
    pushed: bool = field(default=False, init=False)
    merged: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "branch": self.branch,
                "base_sha": self.base_sha, "title": self.title, "body": self.body,
                "diff_digest": self.diff_digest, "review": self.review,
                "pushed": self.pushed, "merged": self.merged}


def build_draft_pr_artifact(
    lease: WorktreeLease, frozen: FrozenDiff, review: MissionReview, *,
    differ: Differ, title: str, body: str,
) -> DraftPRArtifact:
    """Assemble the local draft-PR artifact. Gate 4: this never pushes, opens a
    PR, or merges — there is no such capability in this module. Before building
    it RE-VERIFIES the worktree diff still matches the frozen digest (review
    finding #1), so a post-freeze mutation can never ride a stale review into a
    'clean, reviewed' artifact. Binds the frozen digest + advisory review for a
    human to act on."""
    assert_branch_allowed(lease.branch)                 # defense-in-depth
    verify_diff_unchanged(lease, frozen, differ=differ)  # no stale review rides
    return DraftPRArtifact(
        mission_id=lease.mission_id, branch=lease.branch, base_sha=lease.base_sha,
        title=title, body=body, diff_digest=frozen.diff_digest,
        review={"reviewer": review.reviewer, "status": review.status,
                "summary": review.summary, "findings": list(review.findings)})
