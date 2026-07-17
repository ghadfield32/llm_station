"""Phase 7 governed mission execution — the six zero-tolerance gates.

Each violating input must raise GovernanceViolation BEFORE any side effect. The
first slice terminates at a LOCAL draft-PR artifact — never push/PR/merge.
Hermetic: no real git, no real agent write; the diff is an injected `differ`.
"""
from __future__ import annotations

import pytest

from command_center.kanban_sync.events import GovernanceViolation
from command_center.mission import execution as ex
from command_center.mission.execution import (
    DraftPRArtifact,
    WorktreeLease,
    assert_branch_allowed,
    assert_execution_enabled,
    build_draft_pr_artifact,
    freeze_diff,
    guarded_write,
    record_review,
    verify_diff_unchanged,
)


def _lease(tmp_path, *, expires_at=1e12, scope=("src/", "tests/")):
    wt = tmp_path / "worktree"
    wt.mkdir(exist_ok=True)
    (tmp_path / "primary").mkdir(exist_ok=True)
    return WorktreeLease(
        mission_id="M-1", worktree_root=wt, branch="mission/M-1",
        base_sha="abc123", primary_checkout_root=tmp_path / "primary",
        scope=scope, expires_at=expires_at)


# ── fail-closed flag ─────────────────────────────────────────────────────────
def test_execution_disabled_by_default(monkeypatch):
    monkeypatch.setattr(ex, "MISSION_EXECUTION_ENABLED", False)
    with pytest.raises(GovernanceViolation, match="disabled"):
        assert_execution_enabled()
    monkeypatch.setattr(ex, "MISSION_EXECUTION_ENABLED", True)
    assert_execution_enabled()          # opted in -> passes


# ── gate 1: primary-checkout / worktree escape ───────────────────────────────
def test_write_happy_path_inside_worktree(tmp_path):
    lease = _lease(tmp_path)
    p = guarded_write(lease, "src/app.py", "print(1)", now=0.0)
    assert p.read_text() == "print(1)" and p.exists()


def test_write_refuses_escape_and_writes_nothing(tmp_path):
    lease = _lease(tmp_path)
    with pytest.raises(GovernanceViolation, match="escapes the leased worktree"):
        guarded_write(lease, "../primary/src/app.py", "x", now=0.0)
    assert not (tmp_path / "primary" / "src" / "app.py").exists()   # no side effect


def test_write_refuses_primary_checkout(tmp_path):
    # a lease whose worktree IS inside the primary checkout must still refuse
    prim = tmp_path / "primary"
    prim.mkdir(exist_ok=True)
    lease = WorktreeLease(mission_id="M", worktree_root=prim, branch="mission/x",
                          base_sha="s", primary_checkout_root=prim,
                          scope=("src/",), expires_at=1e12)
    with pytest.raises(GovernanceViolation, match="primary checkout"):
        guarded_write(lease, "src/app.py", "x", now=0.0)


# ── gate 3: unleased / expired ───────────────────────────────────────────────
def test_write_refuses_after_lease_expiry(tmp_path):
    lease = _lease(tmp_path, expires_at=100.0)
    with pytest.raises(GovernanceViolation, match="expired"):
        guarded_write(lease, "src/app.py", "x", now=100.0)   # now >= expiry
    assert not (lease.worktree_root / "src" / "app.py").exists()


# ── gate 5: secret paths ─────────────────────────────────────────────────────
@pytest.mark.parametrize("rel", ["src/.env", ".env", "src/id_rsa", "a/key.pem"])
def test_write_refuses_secret_paths(tmp_path, rel):
    lease = _lease(tmp_path, scope=())     # empty scope = no scope restriction
    with pytest.raises(GovernanceViolation, match="secret"):
        guarded_write(lease, rel, "x", now=0.0)


# ── gate 6: fixed lease scope / no silent widening ───────────────────────────
def test_write_refuses_outside_scope(tmp_path):
    lease = _lease(tmp_path, scope=("src/",))
    with pytest.raises(GovernanceViolation, match="outside the lease scope"):
        guarded_write(lease, "docs/secret_plan.md", "x", now=0.0)


def test_lease_scope_is_frozen(tmp_path):
    lease = _lease(tmp_path)
    with pytest.raises(Exception):     # frozen dataclass — cannot widen in place
        lease.scope = ("",)            # type: ignore[misc]


# ── gate 2: protected branches ───────────────────────────────────────────────
@pytest.mark.parametrize("b", ["main", "master", "release", "release/1.2", "PROD"])
def test_protected_branch_refused(b):
    with pytest.raises(GovernanceViolation, match="protected"):
        assert_branch_allowed(b)


def test_feature_branch_allowed():
    assert_branch_allowed("mission/M-1")   # no raise


# ── independent advisory review ──────────────────────────────────────────────
def test_review_must_differ_from_implementer():
    with pytest.raises(GovernanceViolation, match="DIFFERENT executor"):
        record_review(implementer="claude_code_local", reviewer="claude_code_local",
                      status="reviewed", summary="x")


@pytest.mark.parametrize("bad", ["approved", "merged", "committed", "deployed"])
def test_review_cannot_approve_or_merge(bad):
    with pytest.raises(GovernanceViolation, match="advisory"):
        record_review(implementer="claude_code_local", reviewer="codex_agent",
                      status=bad, summary="x")


def test_advisory_review_ok():
    r = record_review(implementer="claude_code_local", reviewer="codex_agent",
                      status="changes_requested", summary="fix the edge case",
                      findings=["null deref"])
    assert r.reviewer == "codex_agent" and r.status == "changes_requested"


# ── frozen diff ──────────────────────────────────────────────────────────────
def test_frozen_diff_detects_post_freeze_mutation(tmp_path):
    lease = _lease(tmp_path)
    state = {"diff": "diff v1"}
    differ = lambda _root: (state["diff"], ["src/app.py"])
    frozen = freeze_diff(lease, differ=differ, created_at="t")
    verify_diff_unchanged(lease, frozen, differ=differ)   # unchanged -> ok
    state["diff"] = "diff v2 (mutated after freeze)"
    with pytest.raises(GovernanceViolation, match="changed after freeze"):
        verify_diff_unchanged(lease, frozen, differ=differ)


# ── gate 4: draft PR artifact never pushes or merges ─────────────────────────
def test_draft_pr_artifact_is_never_pushed_or_merged(tmp_path):
    lease = _lease(tmp_path)
    differ = lambda _r: ("d", ["src/app.py"])
    frozen = freeze_diff(lease, differ=differ, created_at="t")
    review = record_review(implementer="claude_code_local", reviewer="codex_agent",
                           status="reviewed", summary="ok")
    art = build_draft_pr_artifact(lease, frozen, review, differ=differ,
                                  title="Fix", body="...")
    assert art.pushed is False and art.merged is False
    assert art.to_dict()["pushed"] is False and art.to_dict()["merged"] is False
    # the fields are init=False — you cannot construct a pushed/merged artifact
    with pytest.raises(TypeError):
        DraftPRArtifact(mission_id="M", branch="mission/x", base_sha="s",
                        title="t", body="b", diff_digest="d", review={},
                        pushed=True)   # type: ignore[call-arg]


def test_draft_pr_artifact_refuses_protected_branch(tmp_path):
    lease = WorktreeLease(mission_id="M", worktree_root=tmp_path, branch="main",
                          base_sha="s", primary_checkout_root=tmp_path / "p",
                          scope=("src/",), expires_at=1e12)
    frozen = freeze_diff(lease, differ=lambda _r: ("d", []), created_at="t")
    review = record_review(implementer="a", reviewer="b", status="reviewed", summary="x")
    with pytest.raises(GovernanceViolation, match="protected"):
        build_draft_pr_artifact(lease, frozen, review,
                                differ=lambda _r: ("d", []), title="t", body="b")


# ── review-FAIL fixes: locked so they can't regress ──────────────────────────
def test_artifact_rejects_post_freeze_mutation(tmp_path):
    # finding #1: build_draft_pr_artifact must re-verify the diff, so a mutation
    # after the review can't ride a stale "reviewed" artifact
    lease = _lease(tmp_path)
    state = {"diff": "clean v1"}
    differ = lambda _r: (state["diff"], ["src/app.py"])
    frozen = freeze_diff(lease, differ=differ, created_at="t")
    review = record_review(implementer="claude_code_local", reviewer="codex_agent",
                           status="reviewed", summary="LGTM")
    state["diff"] = "os.system('evil')  # injected after the review"
    with pytest.raises(GovernanceViolation, match="changed after freeze"):
        build_draft_pr_artifact(lease, frozen, review, differ=differ,
                                title="Fix", body="...")


@pytest.mark.parametrize("bad", ["Approved", "APPROVED", "Merged", " deployed ", "lgtm"])
def test_review_status_rejects_non_advisory_any_casing(bad):
    # finding #2: case/whitespace-insensitive + allowlist (only advisory pass)
    with pytest.raises(GovernanceViolation, match="advisory"):
        record_review(implementer="a", reviewer="b", status=bad, summary="x")


@pytest.mark.parametrize("branch", ["refs/heads/main", "heads/main", "Refs/Heads/Main",
                                    "refs/heads/release/1.2", "MASTER", "develop"])
def test_branch_ref_forms_are_protected(branch):
    # finding #3: ref-forms + casing + first-segment matching
    with pytest.raises(GovernanceViolation, match="protected"):
        assert_branch_allowed(branch)


@pytest.mark.parametrize("branch", ["origin/main", "refs/remotes/origin/main",
                                    "refs/remotes/upstream/master", "remotes/origin/main"])
def test_remote_tracking_refs_are_protected(branch):
    # re-review residual: remote-tracking ref forms must also be caught (leaf match)
    with pytest.raises(GovernanceViolation, match="protected"):
        assert_branch_allowed(branch)


def test_feature_branch_with_slash_still_allowed():
    assert_branch_allowed("mission/M-1")
    assert_branch_allowed("feature/attachments")   # leaf 'attachments' not protected


def test_scope_prefix_is_anchored(tmp_path):
    # finding #4: scope=('src/',) must NOT admit 'src-evil/...'
    lease = _lease(tmp_path, scope=("src/",))
    with pytest.raises(GovernanceViolation, match="outside the lease scope"):
        guarded_write(lease, "src-evil/pwn.py", "x", now=0.0)
    assert not (lease.worktree_root / "src-evil" / "pwn.py").exists()  # no write


def test_reviewer_casing_does_not_defeat_independence():
    with pytest.raises(GovernanceViolation, match="DIFFERENT executor"):
        record_review(implementer="codex_agent", reviewer="Codex_Agent",
                      status="reviewed", summary="x")


def test_empty_scope_grants_nothing(tmp_path):
    # a non-secret in-worktree path with empty scope is still refused
    lease = _lease(tmp_path, scope=())
    with pytest.raises(GovernanceViolation, match="no write scope"):
        guarded_write(lease, "src/app.py", "x", now=0.0)
