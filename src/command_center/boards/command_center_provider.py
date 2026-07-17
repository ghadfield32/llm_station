"""Internal (command_center_ui) board provider over the kanban event log.

Status truth = the fold of governed events (project_cards); rich card fields
live in a per-board JSON card store (per-deployment runtime state under
generated/boards/, like the event log itself). Status changes go ONLY through
emit_event, so the wall (no approve/merge/delete, no human-owned statuses)
holds identically on the internal surface. Field upserts never carry status.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from command_center.boards.provider import BoardProvider
from command_center.write_locking import board_write_lock
from command_center.boards.types import (
    COMMAND_CENTER_CAPABILITIES, BoardCapabilities, UnsupportedOperation,
)
from command_center.kanban_sync.events import (
    EventLog, KanbanEvent, emit_event, is_human_owned_status,
)
from command_center.kanban_sync.projection import project_cards

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]")


def _legacy_safe_name(card_id: str) -> str:
    return _SAFE_ID_RE.sub("_", card_id) or "_"


def _safe_name(card_id: str) -> str:
    """Return a path-safe, collision-resistant name for an exact card ID.

    Sanitizing alone is many-to-one, and case-only names alias on Windows.
    The full exact-ID digest keeps them distinct while a short sanitized prefix
    keeps stores inspectable.
    """
    prefix = _legacy_safe_name(card_id)[:48]
    digest = hashlib.sha256(card_id.encode("utf-8")).hexdigest()
    return f"{prefix}--{digest}"


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically so a CONCURRENT reader never sees a
    truncated/empty file. ``Path.write_text`` opens with mode ``'w'``, which
    truncates the target to 0 bytes before writing — a reader landing in that
    window reads ``''`` and ``json.loads('')`` raises. Card field files are read
    (``list_cards``/``_read_fields``) while the background packet-prep worker
    writes them, so the write must be atomic: write a sibling temp file in the
    SAME directory, then ``os.replace`` it in (an atomic rename on POSIX and
    Windows for same-filesystem moves). The reader then always sees the old OR
    the new complete file — never a partial one."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# One lock per card-file path, shared across every provider instance in this
# process. The card store is mutable state read (list_cards / _read_fields) and
# written (upsert_card, incl. the background packet-prep worker) by concurrent
# threads; serialising per-file access is the root-cause fix for the read/write
# race. It also lets the atomic replace run with no reader holding the file open
# (on Windows, os.replace fails with a PermissionError against an open target).
_CARD_FILE_LOCKS: dict[str, threading.Lock] = {}
_CARD_FILE_LOCKS_GUARD = threading.Lock()

# ``list_cards`` is the hot read path for both the domain API and Growth OS. A
# research board can contain thousands of retained card artifacts (modern files
# plus immutable legacy copies), and the Docker cockpit reads them through a
# Windows bind mount. Re-reading every JSON file on each five-second UI poll is
# both slow and self-amplifying: requests overlap while the watcher is also
# scanning the same board. Cache only a fully stable projection, keyed by the
# authoritative store-directory and event-log signatures. All first-party card
# writes use atomic replace (which changes the directory entry signature), and
# status writes append to the event log, so cross-process changes invalidate the
# cache without making the cache authoritative. Per-key locks also coalesce
# simultaneous cold reads in the API process.
_LIST_CARDS_CACHE: dict[
    tuple[str, str, str],
    tuple[tuple[tuple[int, int], tuple[int, int]], list[dict[str, Any]]],
] = {}
_LIST_CARDS_CACHE_LOCKS: dict[tuple[str, str, str], threading.Lock] = {}
_LIST_CARDS_CACHE_GUARD = threading.Lock()


def _card_file_lock(path: Path) -> threading.Lock:
    key = os.path.abspath(str(path))          # normalise so one file → one lock
    with _CARD_FILE_LOCKS_GUARD:
        lock = _CARD_FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _CARD_FILE_LOCKS[key] = lock
        return lock


def _list_cards_cache_lock(key: tuple[str, str, str]) -> threading.Lock:
    with _LIST_CARDS_CACHE_GUARD:
        lock = _LIST_CARDS_CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LIST_CARDS_CACHE_LOCKS[key] = lock
        return lock


def _path_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


def _read_card_file(path: Path) -> dict[str, Any]:
    """Read+parse a card file under its lock, so a concurrent write is never
    observed mid-flight (no empty/partial read, no open-vs-replace contention)."""
    with _card_file_lock(path):
        return json.loads(path.read_text(encoding="utf-8"))


def _write_card_file(path: Path, obj: dict[str, Any]) -> None:
    """Atomically write a card file under its lock (see _read_card_file)."""
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    with _card_file_lock(path):
        _atomic_write_text(path, text)


class CommandCenterBoardProvider(BoardProvider):
    def __init__(self, *, board_id: str, event_log: EventLog, store_dir: Path,
                 status_mapping: dict[str, str] | None = None):
        self.board_id = board_id
        self.log = event_log
        self.store_dir = Path(store_dir) / board_id
        self.status_mapping = status_mapping or {}

    def capabilities(self) -> BoardCapabilities:
        return COMMAND_CENTER_CAPABILITIES

    # -- card field store (runtime state; status never lives here) ----------
    def _card_path(self, card_id: str) -> Path:
        return self.store_dir / f"{_safe_name(card_id)}.json"

    def _legacy_card_path(self, card_id: str) -> Path:
        return self.store_dir / f"{_legacy_safe_name(card_id)}.json"

    def _cache_key(self) -> tuple[str, str, str]:
        return (
            os.path.abspath(str(self.store_dir)),
            os.path.abspath(str(self.log.path)),
            self.board_id,
        )

    def _list_signature(self) -> tuple[tuple[int, int], tuple[int, int]]:
        return (_path_signature(self.store_dir), _path_signature(self.log.path))

    def _invalidate_list_cache(self) -> None:
        key = self._cache_key()
        with _LIST_CARDS_CACHE_GUARD:
            _LIST_CARDS_CACHE.pop(key, None)

    def _read_fields_with_source(
        self, card_id: str,
    ) -> tuple[dict[str, Any], Path | None]:
        """Read fields and identify the artifact already consumed by this read."""
        path = self._card_path(card_id)
        if path.is_file():
            return _read_card_file(path), path
        legacy_path = self._legacy_card_path(card_id)
        if legacy_path.is_file():
            legacy = _read_card_file(legacy_path)
            if legacy.get("card_id") == card_id:
                return legacy, legacy_path
        return {}, None

    def _read_fields(self, card_id: str) -> dict[str, Any]:
        # Read old stores in place. Never trust a legacy many-to-one filename
        # unless the embedded exact ID matches; the next upsert writes the new
        # digest path while retaining the legacy artifact for audit/recovery.
        fields, _source = self._read_fields_with_source(card_id)
        return fields

    def _list_cards_uncached(self) -> list[dict[str, Any]]:
        folded = self._fold()
        out = []
        seen_card_ids = set(folded)
        consumed_paths: set[str] = set()
        for card_id, card in folded.items():
            fields, source_path = self._read_fields_with_source(card_id)
            if source_path is not None:
                consumed_paths.add(os.path.abspath(str(source_path)))
            fields.pop("status", None)  # status truth is the fold, not the store
            out.append({**fields, **card})
        # stored cards that predate any status event still exist (created via
        # upsert only) — surface them with status None rather than hiding them
        if self.store_dir.is_dir():
            for path in sorted(self.store_dir.glob("*.json")):
                # A folded card already consumed this exact artifact above. The
                # old loop parsed every modern/legacy file a second time.
                if os.path.abspath(str(path)) in consumed_paths:
                    continue
                fields = _read_card_file(path)
                stored_card_id = fields.get("card_id")
                if isinstance(stored_card_id, str) and stored_card_id not in seen_card_ids:
                    fields.pop("status", None)
                    out.append({"status": None, "board_id": self.board_id,
                                **fields, "card_id": stored_card_id})
                    seen_card_ids.add(stored_card_id)
        return out

    def list_cards(self) -> list[dict[str, Any]]:
        key = self._cache_key()
        with _list_cards_cache_lock(key):
            signature = self._list_signature()
            cached = _LIST_CARDS_CACHE.get(key)
            if cached is not None and cached[0] == signature:
                return copy.deepcopy(cached[1])

            # A different process can atomically replace card files while this
            # process scans. Cache only when the before/after watermarks match;
            # otherwise retry once and return the second coherent-or-best-effort
            # read uncached if writes remain continuously active.
            rows: list[dict[str, Any]] = []
            for _attempt in range(2):
                before = self._list_signature()
                rows = self._list_cards_uncached()
                after = self._list_signature()
                if before == after:
                    _LIST_CARDS_CACHE[key] = (after, copy.deepcopy(rows))
                    break
            else:
                _LIST_CARDS_CACHE.pop(key, None)
            return copy.deepcopy(rows)

    def _fold(self) -> dict[str, dict[str, Any]]:
        events = [e for e in self.log.read() if e.board_id == self.board_id]
        return project_cards(events)

    def snapshot(self) -> dict[str, dict[str, Any]] | None:
        return self._fold()

    def upsert_card(self, card_id: str, fields: dict[str, Any], *,
                    status: str | None = None) -> dict[str, Any]:
        if is_human_owned_status(status):
            return {"status": "refused", "card_id": card_id,
                    "reason": "refuse_to_write_human_owned_status", "wrote": False}
        # The board-level lock spans the COMPLETE read/merge/write, including the
        # optional creation event. It is shared across host CLIs and the Docker
        # cockpit, so neither process can clobber fields read before the other's
        # atomic replace. The per-file lock still protects readers in this process.
        with board_write_lock(self.store_dir.parent, self.board_id):
            stored = self._read_fields(card_id)
            stored.update(fields)
            stored["card_id"] = card_id
            stored.pop("status", None)
            self.store_dir.mkdir(parents=True, exist_ok=True)
            _write_card_file(self._card_path(card_id), stored)
            self._invalidate_list_cache()
            result: dict[str, Any] = {
                "status": "written", "card_id": card_id, "wrote": True}
            if status is not None:
                # a status on upsert is a card creation — route through the governed
                # writer so the wall applies (raises GovernanceViolation on abuse)
                emit_event(self.log, action="add_mission_card", board_id=self.board_id,
                           card_id=card_id, source_surface="internal_ui",
                           actor_type="agent", status_after=status)
                result["status_label"] = status
            return result

    def mutate_card_fields(
        self,
        card_id: str,
        mutate: Callable[
            [dict[str, Any] | None, list[dict[str, Any]]],
            dict[str, Any],
        ],
        *,
        create: bool = False,
        after_write: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically validate and replace one card's field document.

        The callback runs while the board's cross-process write lock is held and
        receives copies of both the current stored fields and the complete board
        snapshot. This is the narrow seam for mutations whose correctness depends
        on board-wide state, such as duplicate rejection, or on the latest version
        of one field, such as an ordered append. The callback must return the full
        replacement field document; status remains event-log-owned. When a
        governed creation also needs its first status event, ``after_write`` is
        executed before this lock is released. A callback failure restores the
        exact prior field document (or removes the uncommitted new document), so
        ordinary event-log failures cannot strand a statusless card.
        """
        with board_write_lock(self.store_dir.parent, self.board_id):
            cards = self.list_cards()
            current_card = next(
                (card for card in cards if card.get("card_id") == card_id),
                None,
            )
            if create and current_card is not None:
                raise FileExistsError(f"card {card_id!r} already exists")
            if not create and current_card is None:
                raise KeyError(card_id)

            current_fields = None if current_card is None else self._read_fields(card_id)
            replacement = mutate(
                None if current_fields is None else dict(current_fields),
                [dict(card) for card in cards],
            )
            if not isinstance(replacement, dict):
                raise TypeError("card field mutation must return a dictionary")
            replacement = dict(replacement)
            replacement.pop("status", None)
            replacement["card_id"] = card_id
            self.store_dir.mkdir(parents=True, exist_ok=True)
            path = self._card_path(card_id)
            modern_path_existed = path.is_file()
            _write_card_file(path, replacement)
            self._invalidate_list_cache()
            try:
                if after_write is not None:
                    after_write()
            except BaseException:
                if modern_path_existed and current_fields is not None:
                    _write_card_file(path, current_fields)
                else:
                    with _card_file_lock(path):
                        path.unlink(missing_ok=True)
                self._invalidate_list_cache()
                raise
            return dict(replacement)

    def mutate_card_fields_batch(
        self,
        mutations: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        """Validate and replace many existing cards under one board scan/lock.

        Every callback runs and every replacement is validated before the first
        file changes. If a later atomic replace fails, earlier replacements are
        restored to their exact prior modern file (or removed when the card was
        read from a retained legacy path).
        """
        if not mutations:
            return {}
        with board_write_lock(self.store_dir.parent, self.board_id):
            existing_ids = {
                str(card.get("card_id")) for card in self.list_cards()
                if card.get("card_id") is not None
            }
            missing = sorted(set(mutations) - existing_ids)
            if missing:
                raise KeyError(", ".join(missing))

            originals: dict[str, dict[str, Any]] = {}
            replacements: dict[str, dict[str, Any]] = {}
            modern_existed: dict[str, bool] = {}
            for card_id, mutate in mutations.items():
                current = self._read_fields(card_id)
                replacement = mutate(dict(current))
                if not isinstance(replacement, dict):
                    raise TypeError(
                        "batch card field mutation must return a dictionary")
                replacement = dict(replacement)
                replacement.pop("status", None)
                replacement["card_id"] = card_id
                originals[card_id] = current
                replacements[card_id] = replacement
                modern_existed[card_id] = self._card_path(card_id).is_file()

            self.store_dir.mkdir(parents=True, exist_ok=True)
            written: list[str] = []
            try:
                for card_id, replacement in replacements.items():
                    _write_card_file(self._card_path(card_id), replacement)
                    written.append(card_id)
            except BaseException:
                for card_id in reversed(written):
                    path = self._card_path(card_id)
                    if modern_existed[card_id]:
                        _write_card_file(path, originals[card_id])
                    else:
                        with _card_file_lock(path):
                            path.unlink(missing_ok=True)
                self._invalidate_list_cache()
                raise
            self._invalidate_list_cache()
            return copy.deepcopy(replacements)

    def mutate_card_event(
        self,
        card_id: str,
        mutate: Callable[[dict[str, Any]], Any],
    ) -> Any:
        """Validate and emit an event against one locked, current card.

        Status transitions depend on the target card's latest event fold and
        fields, not every other field document on the board. Reading only that
        card keeps the linearizable board lock while avoiding O(board size)
        disk reads for a one-card move.
        """
        with board_write_lock(self.store_dir.parent, self.board_id):
            folded = self._fold().get(card_id)
            fields = self._read_fields(card_id)
            if folded is None and not fields:
                raise KeyError(card_id)
            projected = folded or {
                "card_id": card_id,
                "board_id": self.board_id,
                "repo_id": None,
                "status": None,
                "last_event_id": None,
                "last_actor": None,
            }
            fields.pop("status", None)
            return mutate({**fields, **projected})

    def write_status(self, event: KanbanEvent, *,
                     status_label: str | None = None) -> dict[str, Any]:
        # the event log IS this provider's surface: an already-emitted event is
        # already projected; nothing further to write. Refuse human-owned labels
        # for parity with the external projection contract.
        label = status_label or event.status_after
        if is_human_owned_status(label):
            return {"status": "refused", "card_id": event.card_id,
                    "reason": "refuse_to_write_human_owned_status", "wrote": False}
        return {"status": "written", "card_id": event.card_id,
                "status_label": label, "wrote": True,
                "note": "event log is the internal surface; fold reflects it"}

    def delete_row(self, card_id: str) -> dict[str, Any]:
        raise UnsupportedOperation(
            "delete_row",
            "delete_card is a wall verb on every provider (human-only)",
            "move the card to its configured archive lane; card-store files and "
            "history must never be removed")

    def set_group_by(self, field_name: str) -> dict[str, Any]:
        return {"status": "written", "group_by": field_name, "wrote": True}

    def create_select_option(self, field_name: str, option: str) -> dict[str, Any]:
        return {"status": "written", "field": field_name, "option": option, "wrote": True}

    def validate(self) -> dict[str, Any]:
        out = super().validate()
        out["board_id"] = self.board_id
        out["event_log"] = str(self.log.path)
        out["card_store"] = str(self.store_dir)
        out["n_cards"] = len(self._fold())
        return out
