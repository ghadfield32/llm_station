"""Branch-protection verifier tests.

Hermetic: no GitHub network, no real tokens, no settings writes.
"""
from __future__ import annotations

from command_center.cli import branch_protection_verify


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    def json(self):
        return self._payload


def _write_workflow(root):
    path = root / ".github" / "workflows" / "contracts.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join([
            "name: contracts",
            "jobs:",
            "  validate:",
            "    runs-on: ubuntu-latest",
            "  lint-test:",
            "    runs-on: ubuntu-latest",
        ]) + "\n",
        encoding="utf-8",
    )
    codeowners = root / ".github" / "CODEOWNERS"
    codeowners.write_text("* @ghadfield32\n", encoding="utf-8")


class _FakeProtectedClient:
    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, method, url, headers=None):
        path = url.replace(branch_protection_verify.GITHUB_API, "")
        if method == "GET" and path == "/repos/ghadfield32/llm_station":
            return _Response(200, {"default_branch": "main"})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main/protection":
            return _Response(200, {
                "required_status_checks": {
                    "contexts": ["validate", "lint-test"],
                },
                "required_pull_request_reviews": {
                    "required_approving_review_count": 1,
                    "require_code_owner_reviews": True,
                },
                "allow_force_pushes": {"enabled": False},
                "allow_deletions": {"enabled": False},
                "required_linear_history": {"enabled": True},
            })
        raise AssertionError(f"unexpected fake GitHub request: {method} {path}")


class _FakeWeakProtectionClient(_FakeProtectedClient):
    def request(self, method, url, headers=None):
        path = url.replace(branch_protection_verify.GITHUB_API, "")
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main/protection":
            return _Response(200, {
                "required_status_checks": {"contexts": ["validate"]},
                "required_pull_request_reviews": {
                    "required_approving_review_count": 0,
                    "require_code_owner_reviews": False,
                },
                "allow_force_pushes": {"enabled": True},
                "allow_deletions": {"enabled": False},
                "required_linear_history": {"enabled": False},
            })
        return super().request(method, url, headers=headers)


class _FakeNoProtectionClient(_FakeProtectedClient):
    def request(self, method, url, headers=None):
        path = url.replace(branch_protection_verify.GITHUB_API, "")
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main/protection":
            return _Response(404, {"message": "Branch not protected"})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main":
            return _Response(200, {"name": "main", "protected": False})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches?protected=true&per_page=100":
            return _Response(200, [])
        if method == "GET" and path == "/repos/ghadfield32/llm_station/rules/branches/main":
            return _Response(200, [])
        if method == "GET" and path == "/repos/ghadfield32/llm_station/rulesets?targets=branch&per_page=100":
            return _Response(200, [])
        return super().request(method, url, headers=headers)


class _FakeRulesetProtectionClient(_FakeProtectedClient):
    def request(self, method, url, headers=None):
        path = url.replace(branch_protection_verify.GITHUB_API, "")
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main/protection":
            return _Response(404, {"message": "Branch not protected"})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches/main":
            return _Response(200, {"name": "main", "protected": True})
        if method == "GET" and path == "/repos/ghadfield32/llm_station/branches?protected=true&per_page=100":
            return _Response(200, [{"name": "main", "protected": True}])
        if method == "GET" and path == "/repos/ghadfield32/llm_station/rules/branches/main":
            return _Response(200, [
                {
                    "type": "required_status_checks",
                    "ruleset_id": 42,
                    "source_type": "Repository",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "validate"},
                            {"context": "lint-test"},
                        ],
                    },
                },
                {
                    "type": "pull_request",
                    "ruleset_id": 42,
                    "source_type": "Repository",
                    "parameters": {
                        "required_approving_review_count": 1,
                        "require_code_owner_review": True,
                        "required_review_thread_resolution": True,
                    },
                },
                {"type": "non_fast_forward", "ruleset_id": 42, "source_type": "Repository"},
                {"type": "deletion", "ruleset_id": 42, "source_type": "Repository"},
                {
                    "type": "required_linear_history",
                    "ruleset_id": 42,
                    "source_type": "Repository",
                },
            ])
        if method == "GET" and path == "/repos/ghadfield32/llm_station/rulesets?targets=branch&per_page=100":
            return _Response(200, [
                {
                    "id": 42,
                    "name": "main wall",
                    "target": "branch",
                    "source_type": "Repository",
                    "enforcement": "active",
                    "bypass_actors": [],
                    "conditions": {
                        "ref_name": {
                            "include": ["refs/heads/main"],
                            "exclude": [],
                        },
                    },
                    "rules": [
                        {"type": "required_status_checks"},
                        {"type": "pull_request"},
                        {"type": "non_fast_forward"},
                        {"type": "deletion"},
                        {"type": "required_linear_history"},
                    ],
                },
            ])
        return super().request(method, url, headers=headers)


class _FakeRulesetWithoutCodeOwnersClient(_FakeRulesetProtectionClient):
    def request(self, method, url, headers=None):
        response = super().request(method, url, headers=headers)
        path = url.replace(branch_protection_verify.GITHUB_API, "")
        if method == "GET" and path == "/repos/ghadfield32/llm_station/rules/branches/main":
            payload = response.json()
            for rule in payload:
                if rule.get("type") == "pull_request":
                    rule["parameters"]["require_code_owner_review"] = False
            return _Response(response.status_code, payload)
        return response


def test_branch_protection_verify_blocks_without_owner_admin_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OWNER_ADMIN_TOKEN", raising=False)
    _write_workflow(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("", encoding="utf-8")

    result = branch_protection_verify.verify_branch_protection(
        dotenv_path=dotenv,
        root=tmp_path,
        client_factory=_FakeProtectedClient,
    )

    assert result["status"] == "blocked"
    assert "missing_env_GITHUB_OWNER_ADMIN_TOKEN" in result["blockers"]
    assert result["workflow_jobs"] == ["lint-test", "validate"]
    assert result["repositories"] == []
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False


def test_branch_protection_verify_passes_with_matching_protection(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OWNER_ADMIN_TOKEN", raising=False)
    _write_workflow(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("GITHUB_OWNER_ADMIN_TOKEN=fake-token-not-saved\n", encoding="utf-8")
    output = tmp_path / "branch-protection-verify.json"

    result = branch_protection_verify.verify_branch_protection(
        dotenv_path=dotenv,
        root=tmp_path,
        output=output,
        client_factory=_FakeProtectedClient,
    )
    saved = output.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["repositories"][0]["required_status_checks"] == ["lint-test", "validate"]
    assert result["repositories"][0]["code_owner_reviews_required"] is True
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False
    assert "fake-token-not-saved" not in saved


def test_branch_protection_verify_blocks_weak_rules(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OWNER_ADMIN_TOKEN", raising=False)
    _write_workflow(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("GITHUB_OWNER_ADMIN_TOKEN=fake-token-not-saved\n", encoding="utf-8")

    result = branch_protection_verify.verify_branch_protection(
        dotenv_path=dotenv,
        root=tmp_path,
        client_factory=_FakeWeakProtectionClient,
    )

    assert result["status"] == "blocked"
    assert "branch_protection_missing_required_check_ghadfield32/llm_station_lint-test" in result["blockers"]
    assert "branch_protection_review_count_too_low_ghadfield32/llm_station" in result["blockers"]
    assert "branch_protection_missing_code_owner_reviews_ghadfield32/llm_station" in result["blockers"]
    assert "force_pushes_ghadfield32/llm_station_main_enabled" in result["blockers"]
    assert "linear_history_ghadfield32/llm_station_main_not_required" in result["blockers"]


def test_branch_protection_verify_diagnoses_missing_classic_and_ruleset_protection(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("GITHUB_OWNER_ADMIN_TOKEN", raising=False)
    _write_workflow(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("GITHUB_OWNER_ADMIN_TOKEN=fake-token-not-saved\n", encoding="utf-8")

    result = branch_protection_verify.verify_branch_protection(
        dotenv_path=dotenv,
        root=tmp_path,
        client_factory=_FakeNoProtectionClient,
    )

    assert result["status"] == "blocked"
    assert result["repositories"][0]["classic_branch_protection_verified"] is False
    assert result["repositories"][0]["branch_protected"] is False
    assert result["repositories"][0]["active_branch_rules"] == []
    assert (
        "branch_protection_not_configured_or_not_visible_"
        "ghadfield32/llm_station_main_404"
    ) in result["blockers"]
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False


def test_branch_protection_verify_accepts_ruleset_equivalent_protection(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("GITHUB_OWNER_ADMIN_TOKEN", raising=False)
    _write_workflow(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("GITHUB_OWNER_ADMIN_TOKEN=fake-token-not-saved\n", encoding="utf-8")

    result = branch_protection_verify.verify_branch_protection(
        dotenv_path=dotenv,
        root=tmp_path,
        client_factory=_FakeRulesetProtectionClient,
    )

    assert result["status"] == "pass"
    repo = result["repositories"][0]
    assert repo["protection_mode"] == "active_branch_ruleset"
    assert repo["ruleset_evaluation"]["required_status_checks"] == ["lint-test", "validate"]
    assert repo["ruleset_evaluation"]["active_ruleset_bypass_actors_count"] == 0
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False


def test_branch_protection_verify_blocks_ruleset_without_code_owner_review(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("GITHUB_OWNER_ADMIN_TOKEN", raising=False)
    _write_workflow(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("GITHUB_OWNER_ADMIN_TOKEN=fake-token-not-saved\n", encoding="utf-8")

    result = branch_protection_verify.verify_branch_protection(
        dotenv_path=dotenv,
        root=tmp_path,
        client_factory=_FakeRulesetWithoutCodeOwnersClient,
    )

    assert result["status"] == "blocked"
    assert (
        "branch_ruleset_missing_code_owner_reviews_ghadfield32/llm_station_main"
        in result["blockers"]
    )
    assert result["repositories"][0]["ruleset_evaluation"]["code_owner_reviews_required"] is False
    assert any("enable Require Code Owners" in action for action in result["next_actions"])
    assert result["writes_performed"] is False
    assert result["secrets_printed"] is False
