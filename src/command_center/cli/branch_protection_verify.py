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
) -> tuple[int, Any]:
    response = client.request(method, f"{GITHUB_API}{path}", headers=headers)
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    return response.status_code, data


def _items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _summarize_active_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for rule in rules:
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        entry: dict[str, Any] = {
            "type": rule.get("type"),
            "ruleset_id": rule.get("ruleset_id"),
            "source": rule.get("source"),
            "source_type": rule.get("source_type"),
        }
        if rule.get("type") == "required_status_checks":
            entry["required_status_checks"] = _ruleset_status_checks([rule])
        elif rule.get("type") == "pull_request":
            entry["required_approving_review_count"] = parameters.get(
                "required_approving_review_count"
            )
            entry["require_code_owner_review"] = parameters.get("require_code_owner_review")
            entry["required_review_thread_resolution"] = parameters.get(
                "required_review_thread_resolution"
            )
        summary.append({key: value for key, value in entry.items() if value is not None})
    return summary


def _summarize_rulesets(rulesets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for ruleset in rulesets:
        rules = _items(ruleset.get("rules"))
        bypass_actors = _items(ruleset.get("bypass_actors"))
        conditions = ruleset.get("conditions")
        ref_name = conditions.get("ref_name") if isinstance(conditions, dict) else None
        entry: dict[str, Any] = {
            "id": ruleset.get("id"),
            "name": ruleset.get("name"),
            "target": ruleset.get("target"),
            "source_type": ruleset.get("source_type"),
            "enforcement": ruleset.get("enforcement"),
            "rule_types": sorted(str(rule.get("type")) for rule in rules if rule.get("type")),
            "bypass_actors_count": len(bypass_actors),
        }
        if isinstance(ref_name, dict):
            entry["ref_name_include"] = ref_name.get("include") or []
            entry["ref_name_exclude"] = ref_name.get("exclude") or []
        summary.append({key: value for key, value in entry.items() if value is not None})
    return summary


def _ruleset_status_checks(rules: list[dict[str, Any]]) -> list[str]:
    contexts: set[str] = set()
    for rule in rules:
        if rule.get("type") != "required_status_checks":
            continue
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for check in parameters.get("required_status_checks") or []:
            if isinstance(check, dict) and check.get("context"):
                contexts.add(str(check["context"]))
    return sorted(contexts)


def _pull_request_rule(rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("type") != "pull_request":
            continue
        parameters = rule.get("parameters")
        if isinstance(parameters, dict):
            candidates.append(parameters)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: int(item.get("required_approving_review_count") or 0),
    )


def _rule_types(rules: list[dict[str, Any]]) -> set[str]:
    return {str(rule["type"]) for rule in rules if rule.get("type")}


def _active_ruleset_bypass_count(
    *,
    rules: list[dict[str, Any]],
    rulesets: list[dict[str, Any]],
) -> int | None:
    active_ruleset_ids = {
        rule.get("ruleset_id")
        for rule in rules
        if rule.get("ruleset_id") is not None
    }
    if not active_ruleset_ids:
        return 0
    observed: set[Any] = set()
    bypass_count = 0
    for ruleset in rulesets:
        ruleset_id = ruleset.get("id")
        if ruleset_id not in active_ruleset_ids:
            continue
        observed.add(ruleset_id)
        bypass_count += len(_items(ruleset.get("bypass_actors")))
    if observed != active_ruleset_ids:
        return None
    return bypass_count


def _evaluate_active_rules(
    *,
    rules: list[dict[str, Any]],
    rulesets: list[dict[str, Any]],
    expected: Any,
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    rule_types = _rule_types(rules)
    status_checks = _ruleset_status_checks(rules)
    pull_request = _pull_request_rule(rules)
    bypass_count = _active_ruleset_bypass_count(rules=rules, rulesets=rulesets)
    review_count = (
        pull_request.get("required_approving_review_count")
        if isinstance(pull_request, dict)
        else None
    )
    code_owner_reviews = (
        bool(pull_request.get("require_code_owner_review"))
        if isinstance(pull_request, dict)
        else False
    )

    evaluation = {
        "active_rule_count": len(rules),
        "rule_types": sorted(rule_types),
        "required_status_checks": status_checks,
        "required_pull_request_rule_present": isinstance(pull_request, dict),
        "required_approving_review_count": review_count,
        "code_owner_reviews_required": code_owner_reviews,
        "non_fast_forward_required": "non_fast_forward" in rule_types,
        "deletion_restricted": "deletion" in rule_types,
        "linear_history_required": "required_linear_history" in rule_types,
        "active_ruleset_bypass_actors_count": bypass_count,
    }

    for context in expected.required_status_check_contexts:
        if context not in status_checks:
            blockers.append(f"branch_ruleset_missing_required_check_{context}")
    if not isinstance(pull_request, dict):
        blockers.append("branch_ruleset_missing_pull_request_rule")
    elif review_count is None or review_count < expected.required_approving_review_count:
        blockers.append("branch_ruleset_review_count_too_low")
    if expected.require_code_owner_reviews and not code_owner_reviews:
        blockers.append("branch_ruleset_missing_code_owner_reviews")
    if expected.require_force_pushes_disabled and "non_fast_forward" not in rule_types:
        blockers.append("branch_ruleset_missing_non_fast_forward")
    if expected.require_deletions_disabled and "deletion" not in rule_types:
        blockers.append("branch_ruleset_missing_deletion_restriction")
    if expected.require_linear_history and "required_linear_history" not in rule_types:
        blockers.append("branch_ruleset_missing_linear_history")
    if expected.require_ruleset_bypass_actors_absent:
        if bypass_count is None:
            blockers.append("branch_ruleset_bypass_actors_not_verified")
        elif bypass_count > 0:
            blockers.append("branch_ruleset_bypass_actors_present")
    return evaluation, blockers


def _ruleset_next_actions(*, repo: str, branch: str, rule_blockers: list[str]) -> list[str]:
    actions: list[str] = []
    if "branch_ruleset_missing_code_owner_reviews" in rule_blockers:
        actions.append(
            f"enable Require Code Owners on the active ruleset for {repo}:{branch}, "
            "or explicitly change configs/autonomy.yaml require_code_owner_reviews "
            "only after a human policy decision"
        )
    if "branch_ruleset_missing_required_check_validate" in rule_blockers:
        actions.append(f"add the real validate status check to the active ruleset for {repo}:{branch}")
    if "branch_ruleset_missing_required_check_lint-test" in rule_blockers:
        actions.append(f"add the real lint-test status check to the active ruleset for {repo}:{branch}")
    if "branch_ruleset_missing_pull_request_rule" in rule_blockers:
        actions.append(f"enable Require pull request before merging for {repo}:{branch}")
    if "branch_ruleset_review_count_too_low" in rule_blockers:
        actions.append(f"set required approving reviews to at least 1 for {repo}:{branch}")
    if "branch_ruleset_missing_non_fast_forward" in rule_blockers:
        actions.append(f"enable non-fast-forward/force-push blocking for {repo}:{branch}")
    if "branch_ruleset_missing_deletion_restriction" in rule_blockers:
        actions.append(f"enable deletion restriction for {repo}:{branch}")
    if "branch_ruleset_missing_linear_history" in rule_blockers:
        actions.append(f"enable Require linear history for {repo}:{branch}")
    if "branch_ruleset_bypass_actors_not_verified" in rule_blockers:
        actions.append(f"verify bypass actors for the active ruleset protecting {repo}:{branch}")
    if "branch_ruleset_bypass_actors_present" in rule_blockers:
        actions.append(f"remove bypass actors from the active ruleset protecting {repo}:{branch}")
    return actions


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
                    branch_status, branch_data = _request_json(
                        client,
                        "GET",
                        f"/repos/{owner}/{name}/branches/{branch}",
                        headers=headers,
                    )
                    protected_status, protected_data = _request_json(
                        client,
                        "GET",
                        f"/repos/{owner}/{name}/branches?protected=true&per_page=100",
                        headers=headers,
                    )
                    rules_status, rules_data = _request_json(
                        client,
                        "GET",
                        f"/repos/{owner}/{name}/rules/branches/{branch}",
                        headers=headers,
                    )
                    rulesets_status, rulesets_data = _request_json(
                        client,
                        "GET",
                        f"/repos/{owner}/{name}/rulesets?targets=branch&per_page=100",
                        headers=headers,
                    )
                    active_rules = _items(rules_data)
                    rulesets = _items(rulesets_data)
                    protected_branches = _items(protected_data)
                    branch_protected = (
                        branch_data.get("protected")
                        if isinstance(branch_data, dict) and "protected" in branch_data
                        else None
                    )
                    result.update({
                        "classic_branch_protection_verified": False,
                        "branch_status": branch_status,
                        "branch_protected": branch_protected,
                        "protected_branch_list_status": protected_status,
                        "protected_branch_names": sorted(
                            str(item["name"])
                            for item in protected_branches
                            if item.get("name")
                        ),
                        "active_branch_rules_status": rules_status,
                        "active_branch_rules": _summarize_active_rules(active_rules),
                        "rulesets_status": rulesets_status,
                        "rulesets": _summarize_rulesets(rulesets),
                    })
                    if rules_status != 200:
                        blockers.append(
                            f"branch_rules_not_verified_{repo}_{branch}_{rules_status}"
                        )
                        continue
                    if rulesets_status != 200:
                        blockers.append(
                            f"branch_rulesets_not_verified_{repo}_{branch}_{rulesets_status}"
                        )
                        continue
                    rule_evaluation, rule_blockers = _evaluate_active_rules(
                        rules=active_rules,
                        rulesets=rulesets,
                        expected=expected,
                    )
                    result["ruleset_evaluation"] = rule_evaluation
                    if not active_rules:
                        blockers.append(
                            f"branch_protection_not_configured_or_not_visible_"
                            f"{repo}_{branch}_{protection_status}"
                        )
                        next_actions.append(
                            f"configure protection for {repo}:{branch} using either classic branch "
                            "protection or an active ruleset with validate/lint-test checks, "
                            "pull-request review, CODEOWNERS review, force-push/deletion "
                            "restrictions, and linear history"
                        )
                        continue
                    for rule_blocker in rule_blockers:
                        blockers.append(f"{rule_blocker}_{repo}_{branch}")
                    if not rule_blockers:
                        result.update({
                            "verified": True,
                            "protection_mode": "active_branch_ruleset",
                        })
                    else:
                        next_actions.extend(
                            _ruleset_next_actions(
                                repo=repo,
                                branch=branch,
                                rule_blockers=rule_blockers,
                            )
                        )
                    continue

                result.update(
                    {
                        "classic_branch_protection_verified": True,
                        "protection_mode": "classic_branch_protection",
                    }
                )

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
