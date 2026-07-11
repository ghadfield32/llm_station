"""Durable approval semantics at the store layer — both backends (the in-memory
SessionStore and the real Ledger-backed LedgerSessionStore) must agree: an approval
belongs to exactly one session, resolves exactly once (replay is rejected), and — the
actual reason this table exists instead of FakeHarness's old in-memory dict — a
PENDING approval survives a full process restart and can still be resolved
correctly afterward.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from command_center.agent_sessions.ledger_store import LedgerSessionStore
from command_center.agent_sessions.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


def _in_memory_store():
    store = SessionStore()
    session = store.create_session(harness="fake", conversation_id="c1", repo_id="r")
    return store, session.session_id


def _load_ledger_app(db_path):
    import os
    os.environ["LEDGER_DB"] = str(db_path)
    spec = importlib.util.spec_from_file_location(
        "ledger_app_approvals_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ledger_store(tmp_path):
    from starlette.testclient import TestClient
    db = tmp_path / "ledger.db"
    mod = _load_ledger_app(db)
    client = TestClient(mod.app)
    store = LedgerSessionStore(client)
    session = store.create_session(harness="fake", conversation_id="c1", repo_id="r")
    return store, session.session_id, db


@pytest.fixture(params=["in_memory", "ledger"])
def store_and_session(request, tmp_path):
    if request.param == "in_memory":
        store, session_id = _in_memory_store()
        return store, session_id
    store, session_id, _ = _ledger_store(tmp_path)
    return store, session_id


def test_create_approval_is_pending_with_a_generated_id(store_and_session):
    store, session_id = store_and_session
    approval = store.create_approval(session_id, action="write foo.py")
    assert approval.status == "pending"
    assert approval.approval_id
    assert approval.session_id == session_id
    assert approval.approved is None


def test_resolve_approval_happy_path(store_and_session):
    store, session_id = store_and_session
    approval = store.create_approval(session_id, action="write foo.py")
    resolved = store.resolve_approval(session_id, approval.approval_id,
                                      approved=True, reason="looks fine")
    assert resolved.status == "resolved"
    assert resolved.approved is True
    assert resolved.reason == "looks fine"
    assert store.get_approval(approval.approval_id).status == "resolved"


def test_resolve_approval_replay_is_rejected(store_and_session):
    store, session_id = store_and_session
    approval = store.create_approval(session_id, action="write foo.py")
    store.resolve_approval(session_id, approval.approval_id, approved=True)
    with pytest.raises(ValueError):
        store.resolve_approval(session_id, approval.approval_id, approved=False)


def test_approval_cannot_be_resolved_from_another_session(store_and_session):
    store, session_id = store_and_session
    other = store.create_session(harness="fake", conversation_id="c2", repo_id="r")
    approval = store.create_approval(session_id, action="write foo.py")
    with pytest.raises(ValueError):
        store.resolve_approval(other.session_id, approval.approval_id, approved=True)


def test_unknown_approval_raises_key_error(store_and_session):
    store, _ = store_and_session
    with pytest.raises(KeyError):
        store.get_approval("does-not-exist")


def test_pending_approval_survives_ledger_restart(tmp_path):
    """The actual production concern this whole table exists for: a pending
    approval must not be lost when the worker process restarts, and must still
    resolve correctly afterward."""
    from starlette.testclient import TestClient

    db = tmp_path / "ledger.db"
    mod1 = _load_ledger_app(db)
    store1 = LedgerSessionStore(TestClient(mod1.app))
    session = store1.create_session(harness="fake", conversation_id="c1", repo_id="r")
    approval = store1.create_approval(session.session_id, action="write foo.py")

    # simulate a full process restart: a brand new app import against the same file
    mod2 = _load_ledger_app(db)
    store2 = LedgerSessionStore(TestClient(mod2.app))
    recovered = store2.get_approval(approval.approval_id)
    assert recovered.status == "pending"

    resolved = store2.resolve_approval(session.session_id, approval.approval_id,
                                       approved=True, reason="reviewed post-restart")
    assert resolved.status == "resolved"
    assert resolved.approved is True
