"""Phase 2 — Home sandboxed workspace + the shared secret-path denylist.

The plan's rule: Home is a read-only WORKSPACE, not a fake repo with recursive
access. These tests pin the three guarantees — read-only, single canonical
root, and credential/secret locations denied — plus the single-source-of-truth
denylist shared with the OpenRouter egress wall.
"""
from __future__ import annotations

import pytest

from command_center.agent_sessions.context_resolver import resolve_context_path
from command_center.agent_sessions.home_workspace import (
    HOME_WORKSPACE_ID,
    home_workspace_descriptor,
    load_home_workspace,
    resolve_home_root,
)
from command_center.agent_sessions.secret_paths import is_secret_path


# ── the shared denylist (single source of truth) ────────────────────────────
@pytest.mark.parametrize("path", [
    ".ssh/id_rsa", ".aws/credentials", ".azure/accessTokens.json",
    ".gnupg/secring.gpg", "project/.env", "project/.env.production",
    "a/b/server.pem", "certs/private.key", "vault.kdbx",
    ".mozilla/firefox/profile/logins.json",
])
def test_secret_paths_denied(path):
    assert is_secret_path(path) is True


@pytest.mark.parametrize("path", [
    "src/app.py", "README.md", "docs/MASTER.md", "configs/autonomy.yaml",
    "environment.yml",  # NOT a .env file — must not false-positive
])
def test_non_secret_paths_allowed(path):
    assert is_secret_path(path) is False


def test_secret_denylist_is_shared_with_openrouter():
    # the OpenRouter egress wall must use the SAME function object, so a path
    # that is secret for the Home sandbox is secret for the paid lane too.
    from command_center.agent_sessions.adapters import openrouter_agent
    assert openrouter_agent._is_secret_path is is_secret_path


# ── Home workspace policy ───────────────────────────────────────────────────
def test_home_workspace_is_read_only():
    ws = load_home_workspace({"USERPROFILE": r"C:\Users\ghadf"})
    assert ws.read_only is True


def test_home_denies_secret_paths(tmp_path):
    ws = load_home_workspace({"USERPROFILE": str(tmp_path)})
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("KEY", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    assert ws.is_readable("notes.txt") is True
    assert ws.is_readable(".ssh/id_rsa") is False
    assert ws.is_readable(".env") is False


def test_home_invalid_path_rejected(tmp_path):
    # a `..` escape out of the workspace root must be refused
    ws = load_home_workspace({"USERPROFILE": str(tmp_path)})
    assert ws.is_readable("../outside.txt") is False
    assert ws.is_readable("../../Windows/System32/config/SAM") is False


def test_home_root_requires_env():
    with pytest.raises(RuntimeError):
        resolve_home_root({})   # neither USERPROFILE nor HOME set


def test_home_descriptor_shape():
    d = home_workspace_descriptor({"HOME": "/home/user"})
    assert d["context_id"] == HOME_WORKSPACE_ID
    assert d["read_only"] is True
    assert d["root"]
    assert "credential" in d["denied_summary"].lower()


# ── shared context resolver ─────────────────────────────────────────────────
def test_resolver_special_cases_home():
    got = resolve_context_path(HOME_WORKSPACE_ID, env={"USERPROFILE": r"C:\Users\ghadf"})
    assert got == resolve_home_root({"USERPROFILE": r"C:\Users\ghadf"})


def test_resolver_unknown_repo_raises():
    with pytest.raises(RuntimeError, match="not registered"):
        resolve_context_path("no_such_repo_xyz", env={})


def test_resolver_resolves_registered_repo():
    # llm_station is registered out of the box and resolves to the checkout
    got = resolve_context_path("llm_station")
    assert got.is_dir()
