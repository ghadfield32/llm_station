"""Hermetic tests for the live PR check-evidence loop verifier."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

import yaml

from command_center.cli.pr_check_verify import (
    parse_check_runs,
    run_pr_check_verify,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_TOKEN = "ghs_fake_installation_token_value"
NOW = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = b"x"

    def json(self):
        return self._payload


class _ClientFactory:
    def __init__(self, *, pr_status=201, pr_payload=None, check_payloads=None):
        self.pr_status = pr_status
        self.pr_payload = pr_payload or {
            "number": 7,
            "html_url": "https://github.com/ghadfield32/llm_station/pull/7",
            "state": "open",
        }
        self.check_payloads = list(check_payloads or [])
        self.requests: list[tuple[str, str, dict | None]] = []

    def __call__(self, *args, **kwargs):
        return _Client(self)


class _Client:
    def __init__(self, factory: _ClientFactory):
        self.factory = factory

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def request(self, method, url, headers=None, json=None):
        self.factory.requests.append((method, url, json))
        if method == "GET" and "/contents/pyproject.toml?ref=main" in url:
            content = "\n".join([
                "[project]",
                'name = "command-center"',
                "",
                "[project.optional-dependencies]",
                "dev = [",
                '  "ruff>=0.6",',
                '  "pytest>=8.0",',
                "]",
                "",
            ])
            return _Resp(
                200,
                {
                    "encoding": "base64",
                    "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                },
            )
        if method == "GET" and url.endswith("/git/ref/heads/main"):
            return _Resp(200, {"object": {"sha": "base-sha"}})
        if method == "GET" and url.endswith("/git/commits/base-sha"):
            return _Resp(200, {"tree": {"sha": "base-tree"}})
        if method == "POST" and url.endswith("/git/trees"):
            entries = {entry["path"]: entry["content"] for entry in json["tree"]}
            paths = set(entries)
            assert paths == {"pyproject.toml", "tests/test_pr_check_canary.py"}
            assert '"fastapi>=0.115"' in entries["pyproject.toml"]
            assert "ghs_fake" not in str(json)
            return _Resp(201, {"sha": "tree-sha"})
        if method == "POST" and url.endswith("/git/commits"):
            assert "ghs_fake" not in str(json)
            return _Resp(201, {"sha": "deadbeefcafe"})
        if method == "POST" and url.endswith("/git/refs"):
            return _Resp(201, {"ref": json["ref"], "object": {"sha": json["sha"]}})
        if method == "POST" and url.endswith("/pulls"):
            return _Resp(self.factory.pr_status, self.factory.pr_payload)
        if "check-runs" in url:
            payload = (
                self.factory.check_payloads.pop(0)
                if len(self.factory.check_payloads) > 1
                else self.factory.check_payloads[0]
            )
            return _Resp(200, payload)
        return _Resp(404, {})


def _fake_minter(**kwargs):
    return FAKE_TOKEN, {
        "permissions": {
            "contents": "write",
            "pull_requests": "write",
            "checks": "read",
            "statuses": "read",
        },
        "expires_at": "soon",
    }


def _checks_payload(validate, lint):
    return {
        "check_runs": [
            {
                "name": "validate",
                "status": "completed",
                "conclusion": validate,
                "html_url": "https://x/validate",
            },
            {
                "name": "lint-test",
                "status": "completed",
                "conclusion": lint,
                "html_url": "https://x/lint",
            },
        ]
    }


def test_parse_check_runs_requires_all_completed_and_successful():
    parsed = parse_check_runs(_checks_payload("success", "success"), ("validate", "lint-test"))
    assert parsed["complete"] and parsed["success"]

    parsed = parse_check_runs(_checks_payload("success", "failure"), ("validate", "lint-test"))
    assert parsed["complete"] and not parsed["success"]

    parsed = parse_check_runs(
        {"check_runs": [{"name": "validate", "status": "in_progress", "conclusion": None}]},
        ("validate", "lint-test"),
    )
    assert not parsed["complete"]


def test_pr_check_verify_requires_apply_before_writes(tmp_path):
    client = _ClientFactory(check_payloads=[_checks_payload("success", "success")])

    result = run_pr_check_verify(
        output=tmp_path / "pr-check-loop.json",
        now=NOW,
        client_factory=client,
        token_minter=_fake_minter,
    )

    assert result["status"] == "blocked"
    assert "apply_not_set" in result["blockers"]
    assert result["writes_performed"] is False
    assert client.requests == []


def test_pr_check_verify_pass_creates_branch_pr_and_verifies_configured_checks(tmp_path):
    client = _ClientFactory(check_payloads=[_checks_payload("success", "success")])
    output = tmp_path / "pr-check-loop.json"

    result = run_pr_check_verify(
        output=output,
        now=NOW,
        client_factory=client,
        token_minter=_fake_minter,
        apply=True,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
    )

    assert result["status"] == "pass"
    assert result["required_checks"] == ["validate", "lint-test"]
    assert result["required_checks_source"].startswith("configs/autonomy.yaml")
    assert result["github_policy"]["feature_branch_created"] is True
    assert result["github_policy"]["pr_created"] is True
    assert result["github_policy"]["merge_performed"] is False
    assert result["check_runs_success"] is True
    assert result["completion_verdict"]["status"] == "PASS"
    assert result["pull_request"]["number"] == 7
    assert result["changed_paths"] == ["pyproject.toml", "tests/test_pr_check_canary.py"]

    saved = output.read_text(encoding="utf-8")
    assert FAKE_TOKEN not in saved
    assert "x-access-token" not in saved
    assert any(url.endswith("/git/refs") for method, url, _ in client.requests if method == "POST")


def test_pr_check_verify_blocks_when_a_required_check_fails(tmp_path):
    client = _ClientFactory(check_payloads=[_checks_payload("success", "failure")])

    result = run_pr_check_verify(
        output=tmp_path / "pr-check-loop.json",
        now=NOW,
        client_factory=client,
        token_minter=_fake_minter,
        apply=True,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
    )

    assert result["status"] == "blocked"
    assert "required_checks_not_all_successful" in result["blockers"]
    assert result["github_policy"]["pr_created"] is True
    assert result["github_policy"]["merge_performed"] is False


def test_pr_check_verify_blocks_when_branch_protection_unverified(tmp_path):
    raw = yaml.safe_load((REPO_ROOT / "configs" / "autonomy.yaml").read_text(encoding="utf-8"))
    raw["branch_protection_verification"]["status"] = "blocked"
    config = tmp_path / "autonomy.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    client = _ClientFactory(check_payloads=[_checks_payload("success", "success")])

    result = run_pr_check_verify(
        config_path=config,
        output=tmp_path / "pr-check-loop.json",
        now=NOW,
        client_factory=client,
        token_minter=_fake_minter,
        apply=True,
    )

    assert result["status"] == "blocked"
    assert "branch_protection_not_verified" in result["blockers"]
    assert result["writes_performed"] is False
    assert client.requests == []
