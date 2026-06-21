"""Hermetic tests for the generic bounded-loop prover (no GitHub network)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from command_center.cli import repo_loop_proof

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.content = b"{}"

    def json(self):
        return self._p


class _FakeClient:
    """Simulates the GitHub REST calls the prover makes. Records writes."""

    def __init__(self, *, merged=False, check_conclusion="success", calls=None):
        self.merged = merged
        self.check_conclusion = check_conclusion
        self.calls = calls if calls is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, method, url, headers=None, json=None):
        path = url.split("github.com", 1)[-1] if "github.com" in url else url
        self.calls.append((method, path))
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            return _Resp(200, {"object": {"sha": "base123"}})
        if method == "GET" and "/git/commits/" in path:
            return _Resp(200, {"tree": {"sha": "tree123"}})
        if method == "POST" and path.endswith("/git/trees"):
            return _Resp(201, {"sha": "newtree"})
        if method == "POST" and path.endswith("/git/commits"):
            return _Resp(201, {"sha": "commit123"})
        if method == "POST" and path.endswith("/git/refs"):
            return _Resp(201, {})
        if method == "POST" and path.endswith("/pulls"):
            return _Resp(201, {"number": 7})
        if method == "GET" and re.search(r"/commits/.+/check-runs", path):
            return _Resp(200, {"check_runs": [
                {"name": "Unit Tests", "status": "completed",
                 "conclusion": self.check_conclusion}]})
        if method == "GET" and re.search(r"/pulls/7$", path):
            return _Resp(200, {"merged": self.merged})
        if method == "PATCH" and re.search(r"/pulls/7$", path):
            return _Resp(200, {})
        if method == "DELETE" and "/git/refs/heads/" in path:
            return _Resp(204, {})
        raise AssertionError(f"unexpected request {method} {path}")


def _cfg(tmp_path: Path) -> Path:
    raw = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "configs/autonomy.yaml").read_text(encoding="utf-8"))
    p = tmp_path / "autonomy.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return p


def _minter(*, env, auth, client_factory):
    return "fake-token", {}


def test_loop_proof_passes_when_checks_succeed_and_not_merged(tmp_path):
    calls: list = []
    out = tmp_path / "pr-check-loop.json"
    res = repo_loop_proof.run_repo_loop_proof(
        repo_id="betts_basketball", config_path=_cfg(tmp_path),
        dotenv_path=tmp_path / ".env", output=out, now=NOW, apply=True,
        client_factory=lambda **k: _FakeClient(merged=False, check_conclusion="success", calls=calls),
        token_minter=_minter, poll_interval=0, poll_timeout=0)
    assert res["status"] == "pass", res["blockers"]
    assert res["required_checks"] == ["Unit Tests"]      # betts's own check
    assert res["merge_performed"] is False
    # the proof PR is closed (never merged) and the branch deleted
    assert ("PATCH", "/repos/ghadfield32/betts_basketball/pulls/7") in calls
    assert any(m == "DELETE" for m, _ in calls)
    import json
    assert json.loads(out.read_text())["status"] == "pass"  # gate reads this


def test_loop_proof_blocks_when_required_check_fails(tmp_path):
    res = repo_loop_proof.run_repo_loop_proof(
        repo_id="betts_basketball", config_path=_cfg(tmp_path),
        dotenv_path=tmp_path / ".env", output=tmp_path / "o.json", now=NOW, apply=True,
        client_factory=lambda **k: _FakeClient(merged=False, check_conclusion="failure"),
        token_minter=_minter, poll_interval=0, poll_timeout=0)
    assert res["status"] == "blocked"
    assert "required_checks_did_not_succeed" in res["blockers"]


def test_loop_proof_flags_wall_breach_if_merged(tmp_path):
    res = repo_loop_proof.run_repo_loop_proof(
        repo_id="betts_basketball", config_path=_cfg(tmp_path),
        dotenv_path=tmp_path / ".env", output=tmp_path / "o.json", now=NOW, apply=True,
        client_factory=lambda **k: _FakeClient(merged=True, check_conclusion="success"),
        token_minter=_minter, poll_interval=0, poll_timeout=0)
    assert res["status"] == "blocked"
    assert "pull_request_was_merged_wall_breached" in res["blockers"]


def test_loop_proof_requires_apply(tmp_path):
    res = repo_loop_proof.run_repo_loop_proof(
        repo_id="betts_basketball", config_path=_cfg(tmp_path),
        dotenv_path=tmp_path / ".env", output=tmp_path / "o.json", now=NOW, apply=False,
        client_factory=lambda **k: _FakeClient(), token_minter=_minter)
    assert res["status"] == "blocked" and "apply_not_set" in res["blockers"]
