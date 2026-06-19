"""Live PR check-evidence loop verifier.

This is the remote gate after the bounded local `cc branch-mission` smoke. It
uses the configured GitHub App identity to create one feature branch commit,
open one draft pull request, and verify the required GitHub checks named in
`configs/autonomy.yaml`.

The command never merges, deploys, changes repo settings, changes secrets, or
uses the owner/admin observer token. The installation token is held in memory
only and is never written to the evidence artifact.
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import yaml

from command_center.autonomy.events import CanonicalEvent
from command_center.autonomy.verifier import verify_completion
from command_center.cli.github_app_verify import (
    API_HEADERS,
    GITHUB_API,
    _merged_env,
    _read_dotenv,
    mint_installation_token,
)
from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]
ORDERED_WORK = "verify_pr_check_evidence_loop_before_autonomous_edits"
COMPLETED_BRANCH_MISSION = "tiny_branch_only_repo_mission_passed"
COMPLETED_PR_CHECK = "pr_check_evidence_loop_verified"
EXPECTED_STATE = "feature_branch_pr_open_required_checks_succeeded"
CANARY_PATH = "tests/test_pr_check_canary.py"
PYPROJECT_PATH = "pyproject.toml"


def _owner_repo(remote_url: str) -> tuple[str, str]:
    tail = remote_url.rstrip("/")
    if tail.endswith(".git"):
        tail = tail[:-4]
    owner, repo = tail.split("/")[-2:]
    return owner, repo


def _request_json(
    client: Any,
    method: str,
    path: str,
    *,
    token: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    response = client.request(
        method,
        f"{GITHUB_API}{path}",
        headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
        json=body,
    )
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    return response.status_code, data


def _canary_test_source(*, mission_id: str, branch: str) -> str:
    return f'''\
"""Canary test from `cc pr-check-verify` proving the live PR/check loop.

Mission: {mission_id}
Branch:  {branch}

Safe to delete after this PR has been reviewed.
"""
import tomllib
from pathlib import Path


def test_pr_check_canary_dev_extra_contains_fastapi():
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("fastapi>=") for dep in dev)
'''


def _pyproject_with_fastapi_dev(pyproject_text: str) -> str:
    """Make full pytest runnable under the base workflow's `.[dev]` install.

    The branch protection rule requires the `lint-test` job. On the protected
    base branch that job installs `.[dev]` and then runs the full test suite.
    Existing tests import FastAPI-backed service modules, so `fastapi` must be a
    test dependency. This edits the PR branch content; it does not change the
    workflow file, because the GitHub App intentionally has no workflow write
    permission.
    """
    if '"fastapi>=0.115"' in pyproject_text:
        return pyproject_text
    marker = '  "pytest>=8.0",\n'
    if marker not in pyproject_text:
        raise ValueError("pyproject dev extra does not contain pytest marker")
    return pyproject_text.replace(marker, marker + '  "fastapi>=0.115",\n', 1)


def read_repo_file(
    *,
    client_factory,
    token: str,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> dict[str, Any]:
    encoded_path = quote(path, safe="/")
    encoded_ref = quote(ref, safe="")
    with client_factory(timeout=30) as client:
        status, data = _request_json(
            client,
            "GET",
            f"/repos/{owner}/{repo}/contents/{encoded_path}?ref={encoded_ref}",
            token=token,
        )
    if status != 200:
        return {"status": status, "error": "repo_file_read_failed", "path": path}
    if data.get("encoding") != "base64":
        return {"status": status, "error": "repo_file_not_base64", "path": path}
    try:
        content = base64.b64decode(str(data.get("content", "")).encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        return {"status": status, "error": f"repo_file_decode_failed_{type(exc).__name__}", "path": path}
    return {"status": status, "path": path, "content": content}


def _event(
    *,
    kind: str,
    event_id: str,
    mission_id: str,
    timestamp: str,
    result: str,
    risk_tier,
    detail: dict[str, Any],
) -> CanonicalEvent:
    return CanonicalEvent(
        kind=kind,
        event_id=event_id,
        mission_id=mission_id,
        timestamp=timestamp,
        actor="cc.pr-check-verify",
        source_authority="configs/autonomy.yaml",
        risk_tier=risk_tier,
        privacy_classification="internal",
        result=result,
        input_artifact_hashes=[],
        output_artifact_hashes=[],
        trace_id=mission_id,
        approval_id=None,
        rollback_id=None,
        detail=detail,
    )


def parse_check_runs(data: dict[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    for run in data.get("check_runs", []) or []:
        name = run.get("name")
        if name in required:
            runs[name] = {
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "html_url": run.get("html_url"),
            }
    complete = all(name in runs and runs[name]["status"] == "completed" for name in required)
    success = complete and all(runs[name]["conclusion"] == "success" for name in required)
    return {"runs": runs, "complete": complete, "success": success}


def create_branch_commit(
    *,
    client_factory,
    token: str,
    owner: str,
    repo: str,
    base: str,
    branch: str,
    files: dict[str, str],
    message: str,
) -> dict[str, Any]:
    with client_factory(timeout=30) as client:
        status, ref = _request_json(
            client,
            "GET",
            f"/repos/{owner}/{repo}/git/ref/heads/{base}",
            token=token,
        )
        if status != 200:
            return {"status": status, "error": "base_ref_read_failed"}
        base_sha = ((ref.get("object") or {}).get("sha")) or ""
        if not base_sha:
            return {"status": status, "error": "base_ref_missing_sha"}

        status, commit = _request_json(
            client,
            "GET",
            f"/repos/{owner}/{repo}/git/commits/{base_sha}",
            token=token,
        )
        if status != 200:
            return {"status": status, "error": "base_commit_read_failed"}
        base_tree = ((commit.get("tree") or {}).get("sha")) or ""
        if not base_tree:
            return {"status": status, "error": "base_commit_missing_tree"}

        tree_entries = [
            {"path": path, "mode": "100644", "type": "blob", "content": content}
            for path, content in sorted(files.items())
        ]
        status, tree = _request_json(
            client,
            "POST",
            f"/repos/{owner}/{repo}/git/trees",
            token=token,
            body={"base_tree": base_tree, "tree": tree_entries},
        )
        if status != 201:
            return {"status": status, "error": "tree_create_failed", "message": tree.get("message")}
        tree_sha = tree.get("sha")

        status, new_commit = _request_json(
            client,
            "POST",
            f"/repos/{owner}/{repo}/git/commits",
            token=token,
            body={
                "message": message,
                "tree": tree_sha,
                "parents": [base_sha],
                "author": {
                    "name": "command-center pr-check",
                    "email": "command-center@users.noreply.github.com",
                },
            },
        )
        if status != 201:
            return {
                "status": status,
                "error": "commit_create_failed",
                "message": new_commit.get("message"),
            }
        commit_sha = new_commit.get("sha")

        status, created_ref = _request_json(
            client,
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            token=token,
            body={"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )
        if status != 201:
            return {
                "status": status,
                "error": "branch_ref_create_failed",
                "message": created_ref.get("message"),
            }
        return {
            "status": status,
            "base_sha": base_sha,
            "commit_sha": commit_sha,
            "changed_paths": sorted(files),
        }


def open_pull_request(
    *,
    client_factory,
    token: str,
    owner: str,
    repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    with client_factory(timeout=30) as client:
        status, data = _request_json(
            client,
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            token=token,
            body={"title": title, "head": head, "base": base, "body": body, "draft": True},
        )
    return {"status": status, "data": data}


def poll_check_runs(
    *,
    client_factory,
    token: str,
    owner: str,
    repo: str,
    sha: str,
    required: tuple[str, ...],
    poll_interval: float,
    poll_timeout: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    deadline = clock() + poll_timeout
    last = {"runs": {}, "complete": False, "success": False, "polls": 0}
    with client_factory(timeout=30) as client:
        while True:
            status, data = _request_json(
                client,
                "GET",
                f"/repos/{owner}/{repo}/commits/{sha}/check-runs",
                token=token,
            )
            parsed = parse_check_runs(data if status == 200 else {}, required)
            parsed["polls"] = last["polls"] + 1
            parsed["status_code"] = status
            last = parsed
            if last["complete"] or clock() >= deadline:
                break
            sleep(poll_interval)
    return last


def _write_output(output: Path | None, result: dict[str, Any]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_pr_check_verify(
    *,
    repo_id: str = "llm_station",
    root: Path = ROOT,
    config_path: Path | None = None,
    dotenv_path: Path | None = None,
    output: Path | None = None,
    now: datetime | None = None,
    client_factory=None,
    token_minter=mint_installation_token,
    poll_interval: float = 0.0,
    poll_timeout: float = 0.0,
    apply: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if client_factory is None:
        import httpx

        client_factory = httpx.Client

    config_path = config_path or root / "configs" / "autonomy.yaml"
    dotenv_path = dotenv_path or root / ".env"
    now = now or datetime.now(timezone.utc)
    created_at = now.isoformat()
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    mission_id = f"{repo_id}-pr-check-{stamp}"
    branch = f"mission/{repo_id}/pr-check/{stamp}"

    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    manifest = next((repo for repo in cfg.repo_manifests if repo.repo_id == repo_id), None)
    required_checks = tuple(cfg.branch_protection_verification.required_status_check_contexts)
    result: dict[str, Any] = {
        "status": "blocked",
        "mission_id": mission_id,
        "repo_id": repo_id,
        "branch": branch,
        "created_at": created_at,
        "required_checks": list(required_checks),
        "required_checks_source": "configs/autonomy.yaml:branch_protection_verification.required_status_check_contexts",
        "poll_interval_seconds": poll_interval,
        "poll_timeout_seconds": poll_timeout,
        "poll_budget_source": "operator_cli_args",
        "evidence": [],
        "blockers": [],
        "next_actions": [],
        "secrets_printed": False,
        "writes_performed": False,
        "github_policy": {
            "feature_branch_created": False,
            "pr_created": False,
            "merge_performed": False,
            "settings_changed": False,
            "secrets_changed": False,
        },
    }

    if manifest is None:
        result["blockers"].append(f"repo_manifest_not_found_{repo_id}")
    elif manifest.auth_mode != "github_app":
        result["blockers"].append("repo_auth_mode_not_github_app")
    if ORDERED_WORK not in cfg.ordered_work and COMPLETED_PR_CHECK not in cfg.completed_work:
        result["blockers"].append(f"ordered_or_completed_work_missing_{ORDERED_WORK}")
    if COMPLETED_BRANCH_MISSION not in cfg.completed_work:
        result["blockers"].append("tiny_branch_only_repo_mission_not_completed")
    if cfg.github_app_auth.status != "verified":
        result["blockers"].append("github_app_auth_not_verified")
    if cfg.branch_protection_verification.status != "verified":
        result["blockers"].append("branch_protection_not_verified")
    if not required_checks:
        result["blockers"].append("required_checks_not_configured")
    if not apply:
        result["blockers"].append("apply_not_set")
        result["next_actions"].append("rerun with --apply to create the bounded PR")
    if poll_interval < 0 or poll_timeout < 0:
        result["blockers"].append("poll_values_must_be_non_negative")

    if result["blockers"]:
        _write_output(output, result)
        return result

    assert manifest is not None
    owner, repo = _owner_repo(manifest.remote_url)
    base = manifest.default_branch
    result["repository"] = f"{owner}/{repo}"
    result["base_branch"] = base
    risk = manifest.risk_ceiling

    forecast = _event(
        kind="mission.forecast",
        event_id=f"{mission_id}:forecast",
        mission_id=mission_id,
        timestamp=created_at,
        result="planned",
        risk_tier=risk,
        detail={
            "expected_state_before": "protected_base_branch_without_canary_pr",
            "expected_state_after": EXPECTED_STATE,
            "expected_events": ["repo.action", "mission.verification"],
            "expected_no_change": "no merge, no deploy, no settings, no secret write",
            "privacy_boundary": "installation token in memory only; no token in git remote or evidence",
            "rollback_or_revert_plan": "close the PR; retain the feature branch unless human cleanup is approved",
        },
    )
    actions: list[CanonicalEvent] = []

    try:
        env = _merged_env(_read_dotenv(dotenv_path))
        token, token_info = token_minter(
            env=env,
            auth=cfg.github_app_auth,
            client_factory=client_factory,
            permissions={
                "metadata": "read",
                "contents": "write",
                "pull_requests": "write",
                "checks": "read",
                "statuses": "read",
            },
        )
        result["token_permissions"] = token_info.get("permissions")
        result["token_expires_at"] = token_info.get("expires_at")

        base_pyproject = read_repo_file(
            client_factory=client_factory,
            token=token,
            owner=owner,
            repo=repo,
            path=PYPROJECT_PATH,
            ref=base,
        )
        if base_pyproject.get("status") != 200:
            result["blockers"].append(str(base_pyproject.get("error", "base_pyproject_read_failed")))
            return result
        pyproject = _pyproject_with_fastapi_dev(str(base_pyproject["content"]))
        files = {
            PYPROJECT_PATH: pyproject,
            CANARY_PATH: _canary_test_source(mission_id=mission_id, branch=branch),
        }
        branch_commit = create_branch_commit(
            client_factory=client_factory,
            token=token,
            owner=owner,
            repo=repo,
            base=base,
            branch=branch,
            files=files,
            message=(
                f"test: pr-check-evidence-loop smoke ({stamp})\n\n"
                "Bounded PR proving branch -> PR -> required-check evidence."
            ),
        )
        result["writes_performed"] = True
        if branch_commit.get("status") != 201:
            result["blockers"].append(branch_commit.get("error", "branch_commit_failed"))
            if branch_commit.get("message"):
                result["evidence"].append(str(branch_commit["message"])[:300])
            return result

        sha = str(branch_commit["commit_sha"])
        result["commit"] = sha
        result["changed_paths"] = branch_commit["changed_paths"]
        result["github_policy"]["feature_branch_created"] = True
        result["evidence"].append(f"feature branch created through GitHub Git API: {branch}")
        actions.append(_event(
            kind="repo.action",
            event_id=f"{mission_id}:repo-action:branch-commit",
            mission_id=mission_id,
            timestamp=created_at,
            result="verified",
            risk_tier=risk,
            detail={
                "repo_id": repo_id,
                "branch": branch,
                "worktree_ref": f"github-api:{owner}/{repo}:{branch}",
                "command": "github-git-api:create-ref",
                "exit_code": 0,
            },
        ))

        pr = open_pull_request(
            client_factory=client_factory,
            token=token,
            owner=owner,
            repo=repo,
            head=branch,
            base=base,
            title=f"pr-check-evidence-loop smoke ({stamp})",
            body=(
                "Automated bounded PR proving the live branch -> PR -> "
                "required-check evidence loop. The agent opened this PR and "
                "**cannot merge it**; CODEOWNERS review plus branch protection "
                "remain the merge wall.\n\nSafe to close after evidence is recorded."
            ),
        )
        if pr["status"] not in (200, 201):
            result["blockers"].append(f"pull_request_create_failed_{pr['status']}")
            message = str((pr.get("data") or {}).get("message", ""))
            if message:
                result["evidence"].append(message[:300])
            return result
        pr_data = pr["data"]
        result["github_policy"]["pr_created"] = True
        result["pull_request"] = {
            "number": pr_data.get("number"),
            "html_url": pr_data.get("html_url"),
            "state": pr_data.get("state"),
            "merged": False,
        }
        result["evidence"].append(f"pull request opened: #{pr_data.get('number')}")

        checks = poll_check_runs(
            client_factory=client_factory,
            token=token,
            owner=owner,
            repo=repo,
            sha=sha,
            required=required_checks,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            sleep=sleep,
            clock=clock,
        )
        result["check_runs"] = checks["runs"]
        result["check_runs_complete"] = checks["complete"]
        result["check_runs_success"] = checks["success"]
        result["check_run_polls"] = checks.get("polls")
        result["check_runs_status_code"] = checks.get("status_code")

        check_exit = 0 if checks["success"] else 1
        actions.append(_event(
            kind="repo.action",
            event_id=f"{mission_id}:repo-action:checks",
            mission_id=mission_id,
            timestamp=created_at,
            result="verified" if check_exit == 0 else "failed",
            risk_tier=risk,
            detail={
                "repo_id": repo_id,
                "branch": branch,
                "worktree_ref": f"github-api:{owner}/{repo}:{branch}",
                "command": "github-actions-required-checks",
                "exit_code": check_exit,
            },
        ))

        observed = EXPECTED_STATE if checks["success"] else "required_checks_not_green"
        verification = _event(
            kind="mission.verification",
            event_id=f"{mission_id}:verification",
            mission_id=mission_id,
            timestamp=created_at,
            result="verified" if checks["success"] else "blocked",
            risk_tier=risk,
            detail={
                "observed_state_after": observed,
                "evidence_refs": [
                    f"commit:{sha}",
                    f"pr:{pr_data.get('html_url')}",
                    *[f"check:{name}:{run.get('conclusion')}"
                      for name, run in checks["runs"].items()],
                ],
                "verifier_result": "PASS" if checks["success"] else "BLOCKED",
            },
        )
        verdict = verify_completion(forecast, verification, actions, cfg)
        result["completion_verdict"] = {
            "status": verdict.status,
            "reasons": verdict.reasons,
        }
        result["events"] = [
            event.model_dump(mode="json")
            for event in [forecast, *actions, verification]
        ]

        if not checks["complete"]:
            result["blockers"].append("required_checks_did_not_report_in_time")
            result["next_actions"].append(
                "inspect the PR checks tab; rerun with a larger --poll-timeout"
            )
            return result
        if not checks["success"]:
            result["blockers"].append("required_checks_not_all_successful")
            result["next_actions"].append("fix the failing required check on the branch, then rerun")
            return result
        if not verdict.passed:
            result["blockers"].extend(
                reason for reason in verdict.reasons if reason not in result["blockers"]
            )
            return result

        result["status"] = "pass"
        result["evidence"].append(
            "PR/check-evidence loop verified: all configured required checks succeeded"
        )
        result["next_actions"].append(
            "human review + CODEOWNERS approval is still required to merge"
        )
        return result
    except RuntimeError as exc:
        result["blockers"].append(str(exc))
        return result
    except ValueError as exc:
        result["blockers"].append(str(exc))
        return result
    finally:
        _write_output(output, result)


def main() -> int:
    parser = argparse.ArgumentParser(prog="pr-check-verify")
    parser.add_argument("--repo-id", default="llm_station")
    parser.add_argument(
        "--output",
        default="evaluation/system-validation/20260616-autonomy-contracts/pr-check-loop.json",
    )
    parser.add_argument("--poll-interval", type=float, default=0.0)
    parser.add_argument("--poll-timeout", type=float, default=0.0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    result = run_pr_check_verify(
        repo_id=args.repo_id,
        output=(ROOT / args.output).resolve(),
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
        apply=args.apply,
    )
    print(f"pr-check-verify: {result['status'].upper()}")
    if result.get("pull_request"):
        print(f"  PR: {result['pull_request'].get('html_url')}")
    for name, run in (result.get("check_runs") or {}).items():
        print(f"  check {name}: {run.get('status')}/{run.get('conclusion')}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    for action in result.get("next_actions", []):
        print(f"  NEXT: {action}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
