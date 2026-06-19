"""Observer-only GitHub App verification.

This command proves the production repo identity without printing secrets or
mutating GitHub. It reads env-var references from configs/autonomy.yaml, mints a
short-lived installation token in memory when the private key is available, and
checks selected-repo scope plus read-only GitHub wall evidence.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import time
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


def _env_status(env: dict[str, str], name: str, *, path: bool = False) -> dict[str, Any]:
    value = env.get(name, "")
    out: dict[str, Any] = {"name": name, "present": bool(value), "length": len(value)}
    if path and value:
        candidate = Path(value).expanduser()
        out["path_exists"] = candidate.is_file()
        try:
            candidate.resolve().relative_to(ROOT.resolve())
            out["inside_repo"] = True
        except ValueError:
            out["inside_repo"] = False
    return out


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _openssl_sign(signing_input: str, key_path: Path) -> bytes:
    completed = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(key_path)],
        input=signing_input.encode("ascii"),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"openssl failed to sign GitHub App JWT: {stderr}")
    return completed.stdout


def build_app_jwt(app_id: str, private_key_path: Path, now: int | None = None) -> str:
    issued_at = int(now or time.time()) - 60
    payload = {"iat": issued_at, "exp": issued_at + 600, "iss": app_id}
    header = {"alg": "RS256", "typ": "JWT"}
    signing_input = ".".join([
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ])
    signature = _openssl_sign(signing_input, private_key_path)
    return f"{signing_input}.{_b64url(signature)}"


def _headers(token: str) -> dict[str, str]:
    return {**API_HEADERS, "Authorization": f"Bearer {token}"}


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    response = client.request(method, f"{GITHUB_API}{path}", headers=headers, json=body)
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    return response.status_code, data


def _github_permission_value(config_value: str) -> str | None:
    if config_value == "read_write":
        return "write"
    if config_value == "read":
        return "read"
    if config_value == "none":
        return None
    raise ValueError(f"unknown permission value {config_value!r}")


def _compare_permissions(
    actual: dict[str, str],
    expected: dict[str, str],
    forbidden: dict[str, str],
) -> list[str]:
    blockers: list[str] = []
    for permission, expected_value in expected.items():
        github_expected = _github_permission_value(expected_value)
        actual_value = actual.get(permission)
        if github_expected is None:
            if actual_value not in (None, "none"):
                blockers.append(f"permission_{permission}_should_be_absent")
            continue
        if actual_value != github_expected:
            blockers.append(
                f"permission_{permission}_expected_{github_expected}_got_{actual_value or 'none'}"
            )
    for permission in forbidden:
        actual_value = actual.get(permission)
        if actual_value not in (None, "none"):
            blockers.append(f"forbidden_permission_{permission}_granted_{actual_value}")
    return blockers


def _append_next_action(next_actions: list[str], action: str) -> None:
    if action not in next_actions:
        next_actions.append(action)


def _append_permission_next_actions(next_actions: list[str], blockers: list[str]) -> None:
    for blocker in blockers:
        if blocker.startswith("permission_") and blocker.endswith("_should_be_absent"):
            permission = blocker.removeprefix("permission_").removesuffix("_should_be_absent")
            _append_next_action(
                next_actions,
                f"remove GitHub App {permission} permission or document an approved policy change, "
                "then rerun github-app-verify",
            )
        elif blocker.startswith("forbidden_permission_"):
            permission = blocker.removeprefix("forbidden_permission_").split("_granted_", 1)[0]
            _append_next_action(
                next_actions,
                f"remove forbidden GitHub App {permission} permission, then rerun github-app-verify",
            )


def mint_installation_token(
    *,
    env: dict[str, str],
    auth: Any,
    client_factory=httpx.Client,
    permissions: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Mint a short-lived GitHub App installation token for the selected repos.

    Reuses the App JWT and installation selection used by `verify_github_app`.
    Returns ``(token, info)`` where ``info`` carries only non-secret metadata
    (granted permissions, expiry, installation id). Never prints or returns
    secrets in error messages; raises ``RuntimeError`` with a token-free code on
    any failure so callers can record it as a blocker.
    """
    app_id = env.get(auth.app_id_env, "")
    installation_id = env.get(auth.installation_id_env, "")
    key_path_value = env.get(auth.private_key_path_env, "")
    if not app_id or not key_path_value:
        raise RuntimeError("github_app_token_env_missing")
    key_path = Path(key_path_value).expanduser()
    if not key_path.is_file():
        raise RuntimeError("github_app_private_key_not_found")

    app_jwt = build_app_jwt(app_id, key_path)
    jwt_headers = _headers(app_jwt)
    repo_names = [repo.split("/", 1)[1] for repo in auth.selected_repositories]
    requested = permissions or {
        name: _github_permission_value(value)
        for name, value in auth.allowed_repository_permissions.items()
        if _github_permission_value(value) is not None
    }

    with client_factory(timeout=30) as client:
        status, installations = _request_json(
            client, "GET", "/app/installations", headers=jwt_headers
        )
        if status != 200 or not isinstance(installations, list):
            raise RuntimeError(f"github_app_installations_request_failed_{status}")
        selected = None
        for installation in installations:
            account = installation.get("account") or {}
            if str(installation.get("id")) == installation_id:
                selected = installation
                break
            if account.get("login") == auth.owner:
                selected = installation
        if selected is None:
            raise RuntimeError("github_app_installation_not_found")
        status, token_data = _request_json(
            client,
            "POST",
            f"/app/installations/{selected['id']}/access_tokens",
            headers=jwt_headers,
            body={"repositories": repo_names, "permissions": requested},
        )
        if status != 201:
            raise RuntimeError(f"github_app_installation_token_request_failed_{status}")
        token = token_data.get("token")
        if not token:
            raise RuntimeError("github_app_installation_token_missing")
        return token, {
            "permissions": dict(sorted((token_data.get("permissions") or {}).items())),
            "expires_at": token_data.get("expires_at"),
            "installation_id": selected.get("id"),
        }


def verify_github_app(
    *,
    config_path: Path = ROOT / "configs" / "autonomy.yaml",
    dotenv_path: Path = ROOT / ".env",
    client_factory=httpx.Client,
) -> dict[str, Any]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    cfg = AutonomyConfig.model_validate(raw)
    auth = cfg.github_app_auth
    env = _merged_env(_read_dotenv(dotenv_path))

    env_checks = [
        _env_status(env, auth.app_id_env),
        _env_status(env, auth.client_id_env),
        _env_status(env, auth.installation_id_env),
        _env_status(env, auth.private_key_path_env, path=True),
    ]
    if auth.webhook_secret_env:
        env_checks.append(_env_status(env, auth.webhook_secret_env))

    blockers: list[str] = []
    next_actions: list[str] = []
    evidence: list[str] = [
        "read configs/autonomy.yaml github_app_auth",
        "read .env key presence without printing values",
    ]

    app_id = env.get(auth.app_id_env, "")
    client_id = env.get(auth.client_id_env, "")
    installation_id = env.get(auth.installation_id_env, "")
    key_path_value = env.get(auth.private_key_path_env, "")
    app_name_value = env.get("GITHUB_APP_NAME", "")

    if not app_id:
        blockers.append(f"missing_env_{auth.app_id_env}")
    elif not app_id.isdigit():
        blockers.append(f"env_{auth.app_id_env}_must_be_numeric")
    if not client_id:
        blockers.append(f"missing_env_{auth.client_id_env}")
    if app_name_value and app_name_value != auth.app_name:
        blockers.append("env_GITHUB_APP_NAME_does_not_match_config")
    if installation_id and not installation_id.isdigit():
        blockers.append(f"env_{auth.installation_id_env}_must_be_numeric")
    if not key_path_value:
        blockers.append(f"missing_env_{auth.private_key_path_env}")
        next_actions.append(
            f"set {auth.private_key_path_env} to the GitHub App PEM path outside the repository"
        )

    key_path = Path(key_path_value).expanduser() if key_path_value else None
    if key_path is not None:
        if not key_path.is_file():
            blockers.append(f"private_key_path_not_found_{auth.private_key_path_env}")
        try:
            key_path.resolve().relative_to(ROOT.resolve())
            blockers.append("private_key_path_must_not_be_inside_repo")
        except ValueError:
            pass

    if blockers:
        return {
            "status": "blocked",
            "env": env_checks,
            "evidence": evidence,
            "blockers": blockers,
            "next_actions": next_actions,
            "writes_performed": False,
            "secrets_printed": False,
        }

    app_jwt = build_app_jwt(app_id, key_path)  # type: ignore[arg-type]
    jwt_headers = _headers(app_jwt)
    repository_results: list[dict[str, Any]] = []
    branch_protection_results: list[dict[str, Any]] = []
    permission_results: dict[str, dict[str, str]] = {}

    with client_factory(timeout=30) as client:
        status, app_data = _request_json(client, "GET", "/app", headers=jwt_headers)
        if status != 200:
            blockers.append(f"github_app_metadata_request_failed_{status}")
        else:
            evidence.append("GitHub /app metadata returned 200")
            if app_data.get("name") != auth.app_name and app_data.get("slug") != auth.app_name:
                blockers.append("github_app_metadata_name_does_not_match_config")

        status, installations = _request_json(client, "GET", "/app/installations", headers=jwt_headers)
        if status != 200 or not isinstance(installations, list):
            blockers.append(f"github_app_installations_request_failed_{status}")
            installations = []
        else:
            evidence.append("GitHub /app/installations returned 200")
            if not installation_id:
                evidence.append(
                    "installation id env absent; selecting installation by configured owner"
                )

        selected_installation = None
        for installation in installations:
            account = installation.get("account") or {}
            if str(installation.get("id")) == installation_id:
                selected_installation = installation
                break
            if account.get("login") == auth.owner:
                selected_installation = installation

        if selected_installation is None:
            blockers.append("github_app_installation_not_found_for_owner_or_env_id")
            next_actions.append(
                f"install the app on selected repositories: "
                f"https://github.com/apps/{auth.app_name}/installations/new"
            )
        else:
            if selected_installation.get("repository_selection") != "selected":
                blockers.append("github_app_installation_must_use_selected_repositories")
            install_permissions = selected_installation.get("permissions") or {}
            permission_results["installation"] = dict(sorted(install_permissions.items()))
            permission_blockers = _compare_permissions(
                install_permissions,
                auth.allowed_repository_permissions,
                auth.forbidden_repository_permissions,
            )
            blockers.extend(permission_blockers)
            _append_permission_next_actions(next_actions, permission_blockers)

        if selected_installation is None:
            return {
                "status": "blocked",
                "env": env_checks,
                "evidence": evidence,
                "blockers": blockers,
                "next_actions": next_actions,
                "writes_performed": False,
                "secrets_printed": False,
            }

        repo_names = [repo.split("/", 1)[1] for repo in auth.selected_repositories]
        requested_permissions = {
            name: _github_permission_value(value)
            for name, value in auth.allowed_repository_permissions.items()
            if _github_permission_value(value) is not None
        }
        status, token_data = _request_json(
            client,
            "POST",
            f"/app/installations/{selected_installation['id']}/access_tokens",
            headers=jwt_headers,
            body={"repositories": repo_names, "permissions": requested_permissions},
        )
        if status != 201:
            blockers.append(f"github_app_installation_token_request_failed_{status}")
            token_data = {}
        else:
            evidence.append("GitHub installation access token request returned 201")
            token_permissions = token_data.get("permissions") or {}
            permission_results["installation_token"] = dict(sorted(token_permissions.items()))
            permission_blockers = _compare_permissions(
                token_permissions,
                auth.allowed_repository_permissions,
                auth.forbidden_repository_permissions,
            )
            blockers.extend(permission_blockers)
            _append_permission_next_actions(next_actions, permission_blockers)

        token = token_data.get("token")
        if not token:
            blockers.append("github_app_installation_token_missing")
            return {
                "status": "blocked",
                "env": env_checks,
                "evidence": evidence,
                "blockers": blockers,
                "next_actions": next_actions,
                "writes_performed": False,
                "secrets_printed": False,
            }

        install_headers = _headers(token)
        for repo in auth.selected_repositories:
            owner, name = repo.split("/", 1)
            repo_status, repo_data = _request_json(
                client, "GET", f"/repos/{owner}/{name}", headers=install_headers)
            repository_results.append({"repository": repo, "repo_status": repo_status})
            if repo_status != 200:
                blockers.append(f"selected_repository_{repo}_read_failed_{repo_status}")
                continue
            evidence.append(f"selected repository {repo} returned 200")
            default_branch = repo_data.get("default_branch") or "main"
            branch_status, branch_data = _request_json(
                client,
                "GET",
                f"/repos/{owner}/{name}/branches/{default_branch}",
                headers=install_headers,
            )
            repository_results[-1]["default_branch_status"] = branch_status
            if branch_status != 200:
                blockers.append(f"default_branch_{repo}_{default_branch}_read_failed_{branch_status}")
                continue
            sha = ((branch_data.get("commit") or {}).get("sha")) or ""
            if sha:
                checks_status, _ = _request_json(
                    client,
                    "GET",
                    f"/repos/{owner}/{name}/commits/{sha}/check-runs",
                    headers=install_headers,
                )
                status_status, _ = _request_json(
                    client,
                    "GET",
                    f"/repos/{owner}/{name}/commits/{sha}/status",
                    headers=install_headers,
                )
                repository_results[-1]["checks_status"] = checks_status
                repository_results[-1]["commit_status_status"] = status_status
                if checks_status != 200:
                    blockers.append(f"checks_read_failed_{repo}_{checks_status}")
                if status_status != 200:
                    blockers.append(f"commit_status_read_failed_{repo}_{status_status}")
            protection_status, protection_data = _request_json(
                client,
                "GET",
                f"/repos/{owner}/{name}/branches/{default_branch}/protection",
                headers=install_headers,
            )
            required_checks = protection_data.get("required_status_checks") or {}
            required_reviews = protection_data.get("required_pull_request_reviews") or {}
            status_checks_present = bool(
                required_checks.get("contexts") or required_checks.get("checks")
            ) if protection_status == 200 else False
            pull_request_reviews_present = bool(required_reviews) if protection_status == 200 else False
            code_owner_reviews_required = bool(
                required_reviews.get("require_code_owner_reviews")
            ) if protection_status == 200 else False
            branch_protection_results.append({
                "repository": repo,
                "branch": default_branch,
                "status": protection_status,
                "verified": protection_status == 200,
                "required_status_checks_present": status_checks_present,
                "required_pull_request_reviews_present": pull_request_reviews_present,
                "code_owner_reviews_required": code_owner_reviews_required,
            })
            if protection_status != 200:
                branch_protection_results[-1]["verification_source"] = (
                    "owner_admin_observer_required"
                )
                branch_protection_results[-1]["app_admin_visibility_required"] = False
                evidence.append(
                    "GitHub App branch-protection endpoint is not a blocker; "
                    "branch wall is verified by cc branch-protection-verify without "
                    "granting the app Administration permission"
                )
            else:
                if not status_checks_present:
                    blockers.append(f"branch_protection_missing_required_status_checks_{repo}")
                if not pull_request_reviews_present:
                    blockers.append(f"branch_protection_missing_pull_request_reviews_{repo}")
                if not code_owner_reviews_required:
                    blockers.append(f"branch_protection_missing_code_owner_reviews_{repo}")

    return {
        "status": "pass" if not blockers else "blocked",
        "env": env_checks,
        "evidence": evidence,
        "repositories": repository_results,
        "branch_protection": branch_protection_results,
        "permissions": permission_results,
        "blockers": blockers,
        "next_actions": next_actions,
        "writes_performed": False,
        "secrets_printed": False,
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="github-app-verify")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    result = verify_github_app(
        config_path=(ROOT / args.config).resolve(),
        dotenv_path=(ROOT / args.dotenv).resolve(),
    )
    if args.output:
        _write_json((ROOT / args.output).resolve(), result)
    print(f"github-app-verify: {result['status'].upper()}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    for action in result.get("next_actions", []):
        print(f"  NEXT: {action}")
    if args.output:
        print(f"evidence -> {args.output}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
