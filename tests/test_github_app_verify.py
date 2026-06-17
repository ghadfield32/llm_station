"""GitHub App verifier tests.

These are hermetic: no GitHub network, no private key, no token material.
"""
from __future__ import annotations

from pathlib import Path

from command_center.cli import github_app_verify


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    def json(self):
        return self._payload


class _FakeGitHubClient:
    def __init__(self, *_, **__):
        self.permissions = {
            "metadata": "read",
            "contents": "write",
            "pull_requests": "write",
            "checks": "read",
            "statuses": "read",
            "issues": "read",
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, method, url, headers=None, json=None):
        path = url.replace(github_app_verify.GITHUB_API, "")
        if method == "GET" and path == "/app":
            return _Response(200, {"name": "llm-station-command-center"})
        if method == "GET" and path == "/app/installations":
            return _Response(200, [{
                "id": 123,
                "account": {"login": "ghadfield32"},
                "repository_selection": "selected",
                "permissions": self.permissions,
            }])
        if method == "POST" and path == "/app/installations/123/access_tokens":
            return _Response(201, {"token": "not-returned-to-user", "permissions": self.permissions})
        if method == "GET" and path == "/repos/ghadfield32/llm_station":
            return _Response(200, {"default_branch": "main"})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main":
            return _Response(200, {"commit": {"sha": "abc123"}})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/commits/abc123/check-runs":
            return _Response(200, {})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/commits/abc123/status":
            return _Response(200, {})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main/protection":
            return _Response(200, {
                "required_status_checks": {"contexts": ["contracts"]},
                "required_pull_request_reviews": {
                    "required_approving_review_count": 1,
                    "require_code_owner_reviews": True,
                },
            })
        raise AssertionError(f"unexpected fake GitHub request: {method} {path}")


class _FakeGitHubClientWithBlockedProtection(_FakeGitHubClient):
    def request(self, method, url, headers=None, json=None):
        path = url.replace(github_app_verify.GITHUB_API, "")
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main/protection":
            return _Response(403, {})
        return super().request(method, url, headers=headers, json=json)


def test_github_app_verify_blocks_without_private_key_and_installation_env(monkeypatch, tmp_path):
    for key in (
        "GITHUB_APP_ID",
        "GITHUB_CLIENT_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "GITHUB_APP_NAME",
    ):
        monkeypatch.delenv(key, raising=False)

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join([
            "GITHUB_APP_ID=1234567",
            "GITHUB_CLIENT_ID=Iv1.exampleclientid",
            "GITHUB_APP_NAME=llm-station-command-center",
        ]) + "\n",
        encoding="utf-8",
    )

    result = github_app_verify.verify_github_app(dotenv_path=dotenv)

    assert result["status"] == "blocked"
    assert "missing_env_GITHUB_APP_INSTALLATION_ID" not in result["blockers"]
    assert "missing_env_GITHUB_APP_PRIVATE_KEY_PATH" in result["blockers"]
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False
    private_key_ref = next(
        item for item in result["env"] if item["name"] == "GITHUB_APP_PRIVATE_KEY_PATH"
    )
    assert private_key_ref["present"] is False


def test_github_app_verify_rejects_private_key_inside_repo(monkeypatch, tmp_path):
    for key in (
        "GITHUB_APP_ID",
        "GITHUB_CLIENT_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "GITHUB_APP_NAME",
    ):
        monkeypatch.delenv(key, raising=False)

    key_path = Path.cwd() / "tmp-test-github-app.pem"
    key_path.write_text("not a real key", encoding="utf-8")
    try:
        dotenv = tmp_path / ".env"
        dotenv.write_text(
            "\n".join([
                "GITHUB_APP_ID=1234567",
                "GITHUB_CLIENT_ID=Iv1.exampleclientid",
                "GITHUB_APP_INSTALLATION_ID=7654321",
                f"GITHUB_APP_PRIVATE_KEY_PATH={key_path}",
                "GITHUB_APP_NAME=llm-station-command-center",
            ]) + "\n",
            encoding="utf-8",
        )

        result = github_app_verify.verify_github_app(dotenv_path=dotenv)
    finally:
        key_path.unlink(missing_ok=True)

    assert result["status"] == "blocked"
    assert "private_key_path_must_not_be_inside_repo" in result["blockers"]


def test_github_permission_compare_blocks_forbidden_permissions():
    blockers = github_app_verify._compare_permissions(
        {
            "metadata": "read",
            "contents": "write",
            "pull_requests": "write",
            "checks": "read",
            "statuses": "read",
            "administration": "read",
        },
        {
            "metadata": "read",
            "contents": "read_write",
            "pull_requests": "read_write",
            "checks": "read",
            "statuses": "read",
        },
        {"administration": "any"},
    )

    assert "forbidden_permission_administration_granted_read" in blockers


def test_github_permission_compare_blocks_unapproved_issues_permission():
    blockers = github_app_verify._compare_permissions(
        {
            "metadata": "read",
            "contents": "write",
            "pull_requests": "write",
            "checks": "read",
            "statuses": "read",
            "issues": "read",
        },
        {
            "metadata": "read",
            "contents": "read_write",
            "pull_requests": "read_write",
            "checks": "read",
            "statuses": "read",
            "issues": "none",
        },
        {},
    )

    assert "permission_issues_should_be_absent" in blockers


def test_github_app_verify_can_discover_installation_by_owner(monkeypatch, tmp_path):
    for key in (
        "GITHUB_APP_ID",
        "GITHUB_CLIENT_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "GITHUB_APP_NAME",
    ):
        monkeypatch.delenv(key, raising=False)

    key_path = tmp_path / "llm-station-command-center.pem"
    key_path.write_text("not used because JWT signing is monkeypatched", encoding="utf-8")
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join([
            "GITHUB_APP_ID=1234567",
            "GITHUB_CLIENT_ID=Iv1.exampleclientid",
            f"GITHUB_APP_PRIVATE_KEY_PATH={key_path}",
            "GITHUB_APP_NAME=llm-station-command-center",
        ]) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(github_app_verify, "build_app_jwt", lambda *_, **__: "jwt")

    result = github_app_verify.verify_github_app(
        dotenv_path=dotenv,
        client_factory=_FakeGitHubClient,
    )

    assert result["status"] == "pass"
    assert "installation id env absent; selecting installation by configured owner" in result["evidence"]
    assert result["permissions"]["installation"]["contents"] == "write"
    assert result["permissions"]["installation_token"]["pull_requests"] == "write"
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False


def test_github_app_verify_records_branch_next_action(monkeypatch, tmp_path):
    for key in (
        "GITHUB_APP_ID",
        "GITHUB_CLIENT_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "GITHUB_APP_NAME",
    ):
        monkeypatch.delenv(key, raising=False)

    key_path = tmp_path / "llm-station-command-center.pem"
    key_path.write_text("not used because JWT signing is monkeypatched", encoding="utf-8")
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join([
            "GITHUB_APP_ID=1234567",
            "GITHUB_CLIENT_ID=Iv1.exampleclientid",
            f"GITHUB_APP_PRIVATE_KEY_PATH={key_path}",
            "GITHUB_APP_NAME=llm-station-command-center",
        ]) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(github_app_verify, "build_app_jwt", lambda *_, **__: "jwt")

    result = github_app_verify.verify_github_app(
        dotenv_path=dotenv,
        client_factory=_FakeGitHubClientWithBlockedProtection,
    )

    assert result["status"] == "blocked"
    assert "branch_protection_not_verified_ghadfield32/llm_station_403" in result["blockers"]
    assert result["permissions"]["installation"]["issues"] == "read"
    assert any("owner/admin authenticated path" in action for action in result["next_actions"])
