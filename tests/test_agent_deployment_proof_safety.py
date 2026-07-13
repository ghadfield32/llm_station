"""scripts/run_agent_deployment_proof.ps1 -- the ONLY sanctioned way to bring
up an isolated ledger+cockpit pair for a live agent-session deployment proof.
Exists because of a real incident (see WORKLOG.md "Agent-session chat
integration"): a wrong-directory `docker compose up` once recreated the
REAL production llm_station-ledger-1/llm_station-agent-kanban-ui-1
containers and overwrote the real .env with throwaway secrets.

Every test here runs the script with -DryRun, so NONE of them touch Docker
or the filesystem outside a pytest tmp_path -- the safety checks themselves
are proven without a running daemon and without any real side effect. Skips
cleanly if pwsh is not on PATH (e.g. a non-Windows CI runner).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_agent_deployment_proof.ps1"

PWSH = shutil.which("pwsh") or shutil.which("powershell")

# The script (deliberately) trusts nothing but `git branch --show-current` for
# its own branch invariant -- so on a detached HEAD (e.g. actions/checkout's
# default for pull_request-triggered runs, checked out at the merge commit)
# there is no real branch for either the script or this suite to name, and
# `-ExpectedBranch ""` doesn't even bind (PowerShell rejects an empty string
# for a Mandatory [string] parameter). Skip cleanly, same as the no-pwsh case
# -- these invariants are proven wherever there IS an attached branch (dev
# machines, push-triggered CI), which is every real invocation of this script.
_ON_DETACHED_HEAD = PWSH is not None and not subprocess.run(
    ["git", "-C", str(REPO_ROOT), "branch", "--show-current"],
    capture_output=True, text=True, check=True).stdout.strip()

pytestmark = pytest.mark.skipif(
    PWSH is None, reason="pwsh/powershell not on PATH")

needs_attached_branch = pytest.mark.skipif(
    _ON_DETACHED_HEAD,
    reason="HEAD is detached (e.g. a PR-triggered actions/checkout merge-commit "
           "checkout) -- there is no real branch for the script or this test to "
           "name, so the branch invariant can't be exercised here")


def run_script(**kwargs) -> subprocess.CompletedProcess:
    args = [PWSH, "-NoProfile", "-File", str(SCRIPT)]
    for key, value in kwargs.items():
        if value is True:
            args.append(f"-{key}")
        elif value is not False:
            args.extend([f"-{key}", str(value)])
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


@pytest.fixture
def in_worktree_proof_env():
    """The proof-env invariant requires the path to live INSIDE the
    worktree (see the script's own invariant list) -- pytest's tmp_path
    fixture lives elsewhere on disk, so tests that aren't specifically
    testing THAT invariant need a real in-worktree path instead. Cleaned up
    unconditionally, even if the script (incorrectly) wrote to it."""
    path = REPO_ROOT / ".env.agent-proof-pytest"
    if path.exists():
        path.unlink()
    yield path
    if path.exists():
        path.unlink()


def test_script_exists():
    assert SCRIPT.is_file()


@needs_attached_branch
def test_happy_path_dry_run_passes(in_worktree_proof_env):
    result = run_script(
        WorktreeRoot=str(REPO_ROOT), ExpectedBranch=_current_branch(),
        ProofEnv=str(in_worktree_proof_env), ProofProjectName="cc-agent-runtime-proof",
        GenerateEnv=True, DryRun=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All invariants PASSED" in result.stdout
    assert not in_worktree_proof_env.exists()   # -DryRun never writes the file


@needs_attached_branch
def test_refuses_llm_station_project_name(tmp_path):
    result = run_script(
        WorktreeRoot=str(REPO_ROOT), ExpectedBranch=_current_branch(),
        ProofEnv=str(tmp_path / ".env.agent-proof"),
        ProofProjectName="llm_station", DryRun=True)
    assert result.returncode != 0
    assert "REFUSED" in result.stdout
    assert "llm_station" in result.stdout


@needs_attached_branch
def test_refuses_project_name_without_proof_in_it(tmp_path):
    result = run_script(
        WorktreeRoot=str(REPO_ROOT), ExpectedBranch=_current_branch(),
        ProofEnv=str(tmp_path / ".env.agent-proof"),
        ProofProjectName="cc-agent-runtime", DryRun=True)
    assert result.returncode != 0
    assert "does not contain 'proof'" in result.stdout


@needs_attached_branch
def test_refuses_wrong_branch(tmp_path):
    result = run_script(
        WorktreeRoot=str(REPO_ROOT), ExpectedBranch="definitely-not-a-real-branch",
        ProofEnv=str(tmp_path / ".env.agent-proof"),
        ProofProjectName="cc-agent-runtime-proof", DryRun=True)
    assert result.returncode != 0
    assert "does not match ExpectedBranch" in result.stdout


@needs_attached_branch
def test_refuses_wrong_root_the_real_incident_scenario():
    """The actual incident: a cwd drift pointed Docker at a DIFFERENT real
    checkout entirely. That checkout is a real git repo (so root resolution
    "succeeds"), but its branch never matches what the caller expected --
    exactly what this test proves catches it, matching the real failure
    mode rather than a synthetic one."""
    other_repo = REPO_ROOT.parent  # any other real git-managed directory
    if not (other_repo / ".git").exists() and not (other_repo / ".git").is_file():
        pytest.skip("no second real git repo available at a fixed relative path")
    result = run_script(
        WorktreeRoot=str(other_repo), ExpectedBranch=_current_branch(),
        ProofEnv=str(other_repo / ".env.agent-proof-should-never-be-created"),
        ProofProjectName="cc-agent-runtime-proof", DryRun=True)
    assert result.returncode != 0
    assert "REFUSED" in result.stdout


@needs_attached_branch
def test_refuses_proof_env_named_dotenv(tmp_path):
    result = run_script(
        WorktreeRoot=str(REPO_ROOT), ExpectedBranch=_current_branch(),
        ProofEnv=str(REPO_ROOT / ".env"), ProofProjectName="cc-agent-runtime-proof",
        DryRun=True)
    assert result.returncode != 0
    assert "must not be named '.env'" in result.stdout


@needs_attached_branch
def test_refuses_proof_env_outside_worktree(tmp_path):
    outside = tmp_path / "outside" / ".env.agent-proof"
    result = run_script(
        WorktreeRoot=str(REPO_ROOT), ExpectedBranch=_current_branch(),
        ProofEnv=str(outside), ProofProjectName="cc-agent-runtime-proof", DryRun=True)
    assert result.returncode != 0
    assert "is not inside WorktreeRoot" in result.stdout


@needs_attached_branch
def test_refuses_missing_proof_env_without_generateenv(in_worktree_proof_env):
    result = run_script(
        WorktreeRoot=str(REPO_ROOT), ExpectedBranch=_current_branch(),
        ProofEnv=str(in_worktree_proof_env),
        ProofProjectName="cc-agent-runtime-proof", DryRun=True)
    assert result.returncode != 0
    assert "does not exist" in result.stdout
    assert "-GenerateEnv" in result.stdout


@needs_attached_branch
def test_no_clobber_existing_proof_env_is_never_regenerated(in_worktree_proof_env):
    in_worktree_proof_env.write_text("SENTINEL_MARKER=do-not-overwrite-me\n")

    result = run_script(
        WorktreeRoot=str(REPO_ROOT), ExpectedBranch=_current_branch(),
        ProofEnv=str(in_worktree_proof_env), ProofProjectName="cc-agent-runtime-proof",
        GenerateEnv=True, DryRun=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "no-clobber" in result.stdout
    assert in_worktree_proof_env.read_text() == "SENTINEL_MARKER=do-not-overwrite-me\n"


def _current_branch() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "branch", "--show-current"],
        capture_output=True, text=True, check=True).stdout.strip()
