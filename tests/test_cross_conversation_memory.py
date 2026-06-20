"""Hermetic tests for command_center cross-conversation memory.

Approval gating, repo namespacing, redaction, provenance, and staleness — for the
durable store in command_center.memory (distinct from growthos.memory).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from command_center.memory import MemoryStore, is_stale
from command_center.schemas import MemoryRecord

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def _rec(**over):
    base = dict(
        memory_id="m1", scope="project", subject="repo_a", value="a durable fact",
        source_ref="docs/MASTER.md", created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
        confidence=1.0, sensitivity="internal", redaction_status="not_required",
        approved_by_human=True, inject_policy="on_subject_match",
        retention_policy="keep_until_superseded",
    )
    base.update(over)
    return MemoryRecord(**base)


def _store(tmp_path):
    return MemoryStore(tmp_path / "memory" / "store.jsonl")


# ---- record contract --------------------------------------------------------
def test_source_ref_required():
    with pytest.raises(ValueError, match="requires a source_ref"):
        _rec(source_ref="")


def test_secret_value_rejected():
    with pytest.raises(ValueError, match="secret-bearing"):
        _rec(value="api_key=sk-abcdef-real-secret-value")


def test_confidential_must_be_redacted():
    with pytest.raises(ValueError, match="must be redaction_status=redacted"):
        _rec(sensitivity="confidential", redaction_status="not_required")


def test_project_subject_must_be_stable_id_namespace():
    with pytest.raises(ValueError, match="must be a stable id namespace"):
        _rec(scope="project", subject="not a namespace!!")


# ---- injection (cross-conversation recall) ----------------------------------
def test_inject_returns_only_approved(tmp_path):
    store = _store(tmp_path)
    store.add(_rec(memory_id="approved", approved_by_human=True))
    store.add(_rec(memory_id="pending", approved_by_human=False))
    got = store.inject(scope="project", subject="repo_a", now=NOW)
    assert {g["memory_id"] for g in got} == {"approved"}
    assert got[0]["source_ref"] == "docs/MASTER.md"  # provenance cited


def test_fresh_conversation_does_not_see_unapproved(tmp_path):
    store = _store(tmp_path)
    store.add(_rec(memory_id="pending", approved_by_human=False))
    assert store.inject(scope="project", subject="repo_a", now=NOW) == []


def test_repo_scoped_memory_does_not_leak_across_repos(tmp_path):
    store = _store(tmp_path)
    store.add(_rec(memory_id="a", subject="repo_a", approved_by_human=True))
    store.add(_rec(memory_id="b", subject="repo_b", approved_by_human=True))
    got = store.inject(scope="project", subject="repo_a", now=NOW)
    assert {g["memory_id"] for g in got} == {"a"}


def test_inject_excludes_never_policy(tmp_path):
    store = _store(tmp_path)
    store.add(_rec(memory_id="never", inject_policy="never", approved_by_human=True))
    assert store.inject(scope="project", subject="repo_a", now=NOW) == []


# ---- staleness --------------------------------------------------------------
def test_staleness_per_record_retention_policy():
    old = (NOW - timedelta(days=2)).isoformat()
    assert is_stale(_rec(updated_at=old, retention_policy="expire_after_days:1"), NOW) is True
    assert is_stale(_rec(updated_at=old, retention_policy="keep_until_superseded"), NOW) is False


def test_prune_removes_stale_and_inject_excludes_it(tmp_path):
    store = _store(tmp_path)
    old = (NOW - timedelta(days=5)).isoformat()
    store.add(_rec(memory_id="stale", updated_at=old, retention_policy="expire_after_days:2",
                   approved_by_human=True))
    store.add(_rec(memory_id="fresh", approved_by_human=True))
    recalled = {g["memory_id"] for g in store.inject(scope="project", subject="repo_a", now=NOW)}
    assert recalled == {"fresh"}  # stale excluded from recall even before prune
    pruned = store.prune(now=NOW, apply=True)
    assert pruned["stale_ids"] == ["stale"] and pruned["removed"] == 1
    assert {r.memory_id for r in store.load()} == {"fresh"}


def test_verify_passes_clean_and_flags_duplicate(tmp_path):
    store = _store(tmp_path)
    store.add(_rec(memory_id="m1"))
    assert store.verify()["status"] == "pass"
    store.path.write_text(store.path.read_text(encoding="utf-8") * 2, encoding="utf-8")
    out = store.verify()
    assert out["status"] == "blocked"
    assert any("duplicate_memory_id" in b for b in out["blockers"])
