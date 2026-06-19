"""Durable publication ledger + single-process lock for the LinkedIn publisher.

The publish path has a real failure window: LinkedIn can accept a post (a side
effect we cannot undo) and the AppFlowy writeback can then fail or the process
can die before the row is stamped Completed. Without a durable record, the next
scheduled run would see no PostURN and publish the SAME post again.

This ledger is the source of truth for "did we already post this Key", written
to a gitignored JSON under generated/ - exactly the role generated/kanban-
imported.json plays for the kanban bridge's dedupe. The ordering is:

    mark_publishing(key)  -> POST to LinkedIn  -> mark_published(key, urn)  -> stamp AppFlowy

so a crash anywhere leaves a state the next run reads, and never reposts:
  PUBLISHED          -> already live; only reconcile the AppFlowy stamp.
  PUBLISHING         -> an attempt was in flight and its outcome is unknown.
  RECONCILE_REQUIRED -> an ambiguous send (timeout/transport error).
The last two are surfaced LOUDLY for a human to resolve; they are NEVER
auto-retried (re-posting on an ambiguous outcome is the duplicate we're
preventing). Only None (never attempted) or FAILED (a definitive non-2xx, i.e.
LinkedIn rejected it and no post was created) are eligible to publish.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# States. PUBLISHED/PUBLISHING/RECONCILE_REQUIRED block a (re)post; FAILED/None allow one.
READY = "READY"
PUBLISHING = "PUBLISHING"
PUBLISHED = "PUBLISHED"
FAILED = "FAILED"
RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
BLOCKS_REPOST = {PUBLISHING, PUBLISHED, RECONCILE_REQUIRED}


def body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AlreadyRunning(RuntimeError):
    """Raised when another publisher instance holds the lock."""


class ProcessLock:
    """Cross-platform advisory file lock, released automatically when the
    process exits or dies (no stale-lock timeout to guess). Non-blocking: if
    another run holds it, acquisition raises AlreadyRunning."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")
        self._fh.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._fh.close()
            self._fh = None
            raise AlreadyRunning(
                f"another linkedin-publish run holds {self.path}") from exc
        return self

    def __exit__(self, *exc):
        if self._fh is None:
            return
        try:
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


class PublishLedger:
    """Per-Key publication records persisted to a gitignored JSON file. Every
    state transition flushes to disk immediately so a crash can't lose it."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.records: dict[str, dict] = {}
        if self.path.exists():
            self.records = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.records, indent=2, sort_keys=True),
                             encoding="utf-8")

    def state(self, key: str) -> str | None:
        rec = self.records.get(key)
        return rec.get("state") if rec else None

    def urn(self, key: str) -> str:
        return self.records.get(key, {}).get("urn", "")

    def blocks_repost(self, key: str) -> bool:
        return self.state(key) in BLOCKS_REPOST

    def mark_publishing(self, key: str, account: str, text: str) -> None:
        self.records[key] = {"account": account, "state": PUBLISHING,
                             "body_hash": body_hash(text), "started_at": _now(),
                             "completed_at": "", "urn": "", "error": ""}
        self._save()

    def mark_published(self, key: str, urn: str) -> None:
        rec = self.records.get(key, {})
        rec.update({"state": PUBLISHED, "urn": urn, "completed_at": _now(), "error": ""})
        self.records[key] = rec
        self._save()

    def mark_failed(self, key: str, error: str) -> None:
        rec = self.records.get(key, {})
        rec.update({"state": FAILED, "completed_at": _now(), "error": error})
        self.records[key] = rec
        self._save()

    def mark_reconcile(self, key: str, error: str) -> None:
        rec = self.records.get(key, {})
        rec.update({"state": RECONCILE_REQUIRED, "error": error})
        self.records[key] = rec
        self._save()
