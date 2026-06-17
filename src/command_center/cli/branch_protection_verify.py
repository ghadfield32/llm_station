"""Observer-only branch-protection verification.

This command uses an owner/admin observer token only when explicitly provided by
env ref in configs/autonomy.yaml. It performs no settings writes, pushes, branch
updates, PR operations, or merge/deploy actions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx
import yaml

from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]
GITHUB_API = "https://api.github.com"
API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _merged_env(dotenv: dict[str, str]) -> dict[str, str]:
    return {**dotenv, **os.environ}


def _env_status(env: dict[str, str], name: str) -> dict[str, Any]:
    value = env.get(name, "")
    return {"name": name, "present": bool(value), "length": len(value)}


def _headers(token: str) -> dict[str, str]:
    return {**API_HEADERS, "Authorization": f"Bearer {token}"}


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
) -> tuple[int, dict[str, Any]]:
    response = client.request(method, f"{GITHUB_API}{path}", headers=headers)
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    return response.status_code, data


def _workflow_jobs(path: Path) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    if not path.is_file():
        return [], [f"workflow_source_missing_{path.as_posix()}"]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    jobs = raw.get("jobs")
    if not isinstance(jobs, dict):
        return [], [f"workflow_source_has_no_jobs_{path.as_posix()}"]
    return sorted(str(name) for name in jobs), blockers


def _protection_status_checks(protection: dict[str, Any]) -> list[str]:
    required = protection.get("required_status_checks") or {}
    contexts = set(required.get("contexts") or [])
    for check in required.get("checks") or []:
        if isinstance(check, dict):
            context = check.get("context") or check.get("name")
            if context:
                contexts.add(str(context))
    return sorted(str(item) for item in contexts if item)


def _enabled_field(protection: dict[str, Any], key: str) -> bool | None:
    value = protection.get(key)
    if isinstance(value, dict) and "enabled" in value:
        return bool(value["enabled"])
    if isinstance(value, bool):
        return value
    return None


def _blocked_if_missing_or_enabled(
    *,
    protection: dict[str, Any],
    key: str,
    blocker_name: str,
) -> str | None:
    enabled = _enabled_field(protection, key)
    if enabled is None:
        return f"{blocker_name}_not_verified"
    if enabled:
        return f"{blocker_name}_enabled"
    return None


def verify_branch_protection(
    *,
    config_path: Path = ROOT / "configs" / "autonomy.yaml",
    dotenv_path: Path = ROOT / ".env",
    output: Path | None = None,
    root: Path = ROOT,
    client_factory=httpx.Client,
) -> dict[str, Any]:
    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    expected = cfg.branch_protection_verification
    env = _merged_env(_read_dotenv(dotenv_path))
    token = env.get(expected.owner_admin_token_env, "")
    env_checks = [_env_status(env, expected.owner_admin_token_env)]
    blockers: list[str] = []
    next_actions: list[str] = []
    evidence = [
        "read configs/autonomy.yaml branch_protection_verification",
        "read owner/admin token env presence without printing value",
    ]

    source_path = Path(expected.required_status_check_source_path)
    if not source_path.is_absolute():
        source_path = root / source_path
    workflow_jobs, workflow_blockers = _workflow_jobs(source_path)
    blockers.extend(workflow_blockers)
    missing_workflow_jobs = [
        context
        for context in expected.required_status_check_contexts
        if context not in workflow_jobs
    ]
    for context in missing_workflow_jobs:
        blockers.append(f"required_status_check_context_not_in_workflow_{context}")

    if not (root / expected.codeowners_path).is_file():
        blockers.append(f"codeowners_path_missing_{expected.codeowners_path}")

    repositories: list[dict[str, Any]] = []
    if not token:
        blockers.append(f"missing_env_{expected.owner_admin_token_env}")
        next_actions.append(
            f"set {expected.owner_admin_token_env} to an owner/admin read-only observer token "
            "for one verification run; do not commit or print it"
        )
    else:
        with client_factory(timeout=30) as client:
            headers = _headers(token)
            for repo in expected.selected_repositories:
                owner, name = repo.split("/", 1)
                repo_status, repo_data = _request_json(
                    client, "GET", f"/repos/{owner}/{name}", headers=headers
                )
                result: dict[str, Any] = {
                    "repository": repo,
                    "repo_status": repo_status,
                }
                repositories.append(result)
                if repo_status != 200:
                    blockers.append(f"repository_read_failed_{repo}_{repo_status}")
                    continue
                branch = repo_data.get("default_branch") or "main"
                result["branch"] = branch
                protection_status, protection = _request_json(
                    client,
                    "GET",
                    f"/repos/{owner}/{name}/branches/{branch}/protection",
                    headers=headers,
                )
                result["protection_status"] = protection_status
                if protection_status != 200:
                    blockers.append(
                        f"branch_protection_not_verified_{repo}_{branch}_{protection_status}"
                    )
                    continue

                observed_checks = _protection_status_checks(protection)
                reviews = protection.get("required_pull_request_reviews")
                review_count = (
                    reviews.get("required_approving_review_count")
                    if isinstance(reviews, dict)
                    else None
                )
                code_owner_reviews = (
                    bool(reviews.get("require_code_owner_reviews"))
                    if isinstance(reviews, dict)
                    else False
                )
                force_push_blocker = _blocked_if_missing_or_enabled(
                    protection=protection,
                    key="allow_force_pushes",
                    blocker_name=f"force_pushes_{repo}_{branch}",
                )
                deletion_blocker = _blocked_if_missing_or_enabled(
                    protection=protection,
                    key="allow_deletions",
                    blocker_name=f"deletions_{repo}_{branch}",
                )
                linear_history = _enabled_field(protection, "required_linear_history")

                result.update({
                    "verified": True,
                    "required_status_checks": observed_checks,
                    "required_pull_request_reviews_present": isinstance(reviews, dict),
                    "required_approving_review_count": review_count,
                    "code_owner_reviews_required": code_owner_reviews,
                    "force_pushes_disabled": force_push_blocker is None,
                    "deletions_disabled": deletion_blocker is None,
                    "linear_history_required": linear_history,
                })

                for context in expected.required_status_check_contexts:
                    if context not in observed_checks:
                        blockers.append(f"branch_protection_missing_required_check_{repo}_{context}")
                if not isinstance(reviews, dict):
                    blockers.append(f"branch_protection_missing_pull_request_reviews_{repo}")
                elif review_count is None or review_count < expected.required_approving_review_count:
                    blockers.append(f"branch_protection_review_count_too_low_{repo}")
                if expected.require_code_owner_reviews and not code_owner_reviews:
                    blockers.append(f"branch_protection_missing_code_owner_reviews_{repo}")
                if expected.require_force_pushes_disabled and force_push_blocker:
                    blockers.append(force_push_blocker)
                if expected.require_deletions_disabled and deletion_blocker:
                    blockers.append(deletion_blocker)
                if expected.require_linear_history and linear_history is not True:
                    blockers.append(f"linear_history_{repo}_{branch}_not_required")

    result = {
        "status": "pass" if not blockers else "blocked",
        "env": env_checks,
        "evidence": evidence,
        "workflow_source": expected.required_status_check_source_path,
        "workflow_jobs": workflow_jobs,
        "required_status_check_contexts": expected.required_status_check_contexts,
        "codeowners_path": expected.codeowners_path,
        "repositories": repositories,
        "blockers": blockers,
        "next_actions": next_actions,
        "writes_performed": False,
        "secrets_printed": False,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="branch-protection-verify")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument(
        "--output",
        default="evaluation/system-validation/20260616-autonomy-contracts/branch-protection-verify.json",
    )
    args = parser.parse_args()

    result = verify_branch_protection(
        config_path=(ROOT / args.config).resolve(),
        dotenv_path=(ROOT / args.dotenv).resolve(),
        output=(ROOT / args.output).resolve(),
    )
    print(f"branch-protection-verify: {result['status'].upper()}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    for action in result.get("next_actions", []):
        print(f"  NEXT: {action}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
