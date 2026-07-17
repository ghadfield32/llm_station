"""Phase 7 mission RUNNER — orchestration over the reviewed gate core.

Hermetic tests use fake seams; one integration test drives the REAL loop on a
throwaway git repo (real `git worktree add`, real diff, real deterministic code
change, real artifact) — the live acceptance, with zero risk to llm_station and
no LLM/quota. Every path stays behind the flag and stops at a LOCAL artifact.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from command_center.kanban_sync.events import GovernanceViolation
from command_center.mission import execution as ex
from command_center.mission.execution import guarded_write, record_review
from command_center.mission.git_backend import (
    declared_validator,
    deterministic_executor,
    git_differ,
    git_worktree_factory,
)
from command_center.mission.runner import MissionRequest, run_local_mission


def _req(tmp_path, **over):
    base = dict(mission_id="M-1", repo_root=tmp_path / "primary",
                branch="mission/M-1", base_sha="deadbeef", scope=("src/",),
                task="add a helper", title="Add helper",
                implementer="claude_code_local", reviewer="codex_agent")
    base.update(over)
    return MissionRequest(**base)


def _fake_worktree(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir(exist_ok=True)
    (tmp_path / "primary").mkdir(exist_ok=True)
    calls = {"cleaned": False}

    def factory(_repo, _branch, _base):
        def cleanup():
            calls["cleaned"] = True
        return wt, cleanup
    return factory, calls, wt


def _review(implementer, reviewer, _frozen):
    return record_review(implementer=implementer, reviewer=reviewer,
                         status="reviewed", summary="ok")


# ── flag gate ────────────────────────────────────────────────────────────────
def test_runner_refused_when_flag_off(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "MISSION_EXECUTION_ENABLED", False)
    factory, _calls, _wt = _fake_worktree(tmp_path)
    with pytest.raises(GovernanceViolation, match="disabled"):
        run_local_mission(_req(tmp_path), worktree_factory=factory,
                          executor_fn=lambda _l: None,
                          validator_fn=lambda _w: [], differ=lambda _w: ("d", []),
                          review_fn=_review, now=lambda: 0.0)


# ── happy path (fake seams) ──────────────────────────────────────────────────
def test_runner_produces_local_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "MISSION_EXECUTION_ENABLED", True)
    factory, calls, wt = _fake_worktree(tmp_path)

    def executor(lease):
        guarded_write(lease, "src/helper.py", "def h(): return 1\n", now=0.0)

    res = run_local_mission(
        _req(tmp_path), worktree_factory=factory, executor_fn=executor,
        validator_fn=lambda _w: [{"command": "pytest", "exit_code": 0}],
        differ=lambda _w: ("diff", ["src/helper.py"]),
        review_fn=_review, now=lambda: 0.0)
    assert res.artifact is not None
    assert res.artifact.pushed is False and res.artifact.merged is False
    assert res.changed_files == ["src/helper.py"]
    assert calls["cleaned"] is True             # worktree always cleaned up


# ── failed declared tests block the artifact ─────────────────────────────────
def test_failed_validation_blocks_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "MISSION_EXECUTION_ENABLED", True)
    factory, calls, _wt = _fake_worktree(tmp_path)
    res = run_local_mission(
        _req(tmp_path), worktree_factory=factory, executor_fn=lambda _l: None,
        validator_fn=lambda _w: [{"command": "pytest", "exit_code": 1}],
        differ=lambda _w: ("d", ["src/x.py"]), review_fn=_review, now=lambda: 0.0)
    assert res.artifact is None and "tests failed" in res.refused
    assert calls["cleaned"] is True


# ── post-execution verification (delegated executor bypassing guarded_write) ──
def test_secret_file_in_diff_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "MISSION_EXECUTION_ENABLED", True)
    factory, calls, _wt = _fake_worktree(tmp_path)
    with pytest.raises(GovernanceViolation, match="secret"):
        run_local_mission(
            _req(tmp_path), worktree_factory=factory, executor_fn=lambda _l: None,
            validator_fn=lambda _w: [], differ=lambda _w: ("d", ["src/app.py", ".env"]),
            review_fn=_review, now=lambda: 0.0)
    assert calls["cleaned"] is True             # cleaned up even on refusal


def test_out_of_scope_file_in_diff_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "MISSION_EXECUTION_ENABLED", True)
    factory, _calls, _wt = _fake_worktree(tmp_path)
    with pytest.raises(GovernanceViolation, match="outside the lease scope"):
        run_local_mission(
            _req(tmp_path, scope=("src/",)), worktree_factory=factory,
            executor_fn=lambda _l: None, validator_fn=lambda _w: [],
            differ=lambda _w: ("d", ["docs/leak.md"]), review_fn=_review,
            now=lambda: 0.0)


# ── LIVE ACCEPTANCE: the real loop on a throwaway git repo ───────────────────
@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_live_acceptance_real_git_worktree(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "MISSION_EXECUTION_ENABLED", True)
    # a throwaway repo (NOT llm_station) with an initial commit on a src/ tree
    repo = tmp_path / "repo"
    repo.mkdir()

    def g(*a):
        return subprocess.run(["git", *a], cwd=repo, check=True,
                              capture_output=True, text=True)

    g("init", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / "src").mkdir()
    (repo / "src" / "seed.py").write_text("x = 0\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "seed")
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()

    req = MissionRequest(
        mission_id="M-live", repo_root=repo, branch="mission/live",
        base_sha=base_sha, scope=("src/",), task="add a real helper",
        title="Add helper", implementer="claude_code_local", reviewer="codex_agent")
    res = run_local_mission(
        req,
        worktree_factory=git_worktree_factory(tmp_path / "worktrees"),
        executor_fn=deterministic_executor({"src/helper.py": "def h():\n    return 42\n"}),
        validator_fn=declared_validator(["python -c \"import sys; sys.exit(0)\""]),
        differ=git_differ, review_fn=_review, now=lambda: 1000.0)

    # a real artifact from a real diff, never pushed/merged
    assert res.artifact is not None, res.refused
    assert res.artifact.pushed is False and res.artifact.merged is False
    assert "src/helper.py" in res.changed_files
    assert res.validations[0]["exit_code"] == 0
    # PRIMARY checkout is unchanged — the change lived only in the worktree branch
    assert not (repo / "src" / "helper.py").exists()
    primary_status = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                                    capture_output=True, text=True).stdout.strip()
    assert primary_status == ""                 # primary tree clean
    # the leased worktree was removed on cleanup (nothing left under worktrees/)
    assert list((tmp_path / "worktrees").glob("mission_live-*")) == []
