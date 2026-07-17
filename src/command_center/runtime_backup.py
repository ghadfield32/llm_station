"""Loss-aware snapshots for Command Center runtime state.

Snapshots are immutable, content-addressed directories.  File sources are
fingerprinted before and after copying; SQLite is copied with its online backup
API and integrity-checked.  This deliberately promises *stable per-source
snapshots plus a source-set watermark*, not an impossible cross-store ACID
transaction.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Literal, cast

import yaml

SCHEMA_VERSION = "command-center.runtime-backup.v1"
EXCLUDED_NAMES = frozenset({
    ".locks", "__pycache__", ".DS_Store", "Thumbs.db", "uv-cache",
    "pytest-tmp", "tmp_env", "source_cache", "job_search_memory.sqlite", "memory.db",
    "watcher_status.json",
})
EXCLUDED_PREFIXES = ("pt-", "pt_", "ptboards", "ptdiag", "ptdomains", "ptdrag",
                     "ptj", "ptjob", "pytest-")
EXCLUDED_SUFFIXES = (".lock", ".tmp", ".swp", "~", ".log")


class BackupError(RuntimeError):
    """A snapshot could not be proven complete and stable."""


@dataclass(frozen=True)
class BackupSource:
    name: str
    path: Path
    kind: Literal["file", "tree", "sqlite"]
    required: bool = True
    sensitive: bool = True


def _native_io_path(path: Path) -> Path:
    """Return a Windows extended-length path for filesystem IO.

    Snapshot paths legitimately include source URLs.  Once those paths are
    nested beneath a timestamped snapshot directory they can exceed the
    legacy Win32 MAX_PATH limit even though the files are healthy.  Prefixing
    absolute paths for IO keeps host-side create/verify/restore behavior in
    parity with the Linux containers.  Manifest paths remain portable POSIX
    relative paths and never contain this platform-specific prefix.
    """
    if os.name != "nt":
        return path
    raw = str(path.resolve(strict=False))
    if raw.startswith("\\\\?\\"):
        return Path(raw)
    if raw.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + raw[2:])
    return Path("\\\\?\\" + raw)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _native_io_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _included_files(path: Path) -> list[Path]:
    root = _native_io_path(path)
    if root.is_symlink():
        raise BackupError(f"backup source must not be a symlink: {path}")
    rows: list[Path] = []
    for candidate in root.rglob("*"):
        rel = candidate.relative_to(root)
        if any(
            part in EXCLUDED_NAMES or part.startswith(EXCLUDED_PREFIXES)
            for part in rel.parts
        ):
            continue
        if candidate.is_symlink():
            raise BackupError(f"backup source contains a symlink: {candidate}")
        if candidate.is_file() and not candidate.name.endswith(EXCLUDED_SUFFIXES):
            rows.append(candidate)
    return sorted(rows, key=lambda item: item.relative_to(root).as_posix())


def _inventory(path: Path, kind: str) -> list[dict[str, object]]:
    native = _native_io_path(path)
    files = [native] if kind in {"file", "sqlite"} else _included_files(native)
    base = native.parent if kind in {"file", "sqlite"} else native
    return [
        {
            "path": file.relative_to(base).as_posix(),
            "bytes": file.stat().st_size,
            "sha256": _sha256_file(file),
        }
        for file in files
    ]


def _fingerprint(path: Path, kind: str) -> str:
    if kind == "sqlite":
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as src, closing(
            sqlite3.connect(":memory:")
        ) as logical:
            src.backup(logical)
            result = logical.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupError(f"SQLite integrity check failed for {path}: {result}")
            metadata = {
                name: logical.execute(f"PRAGMA {name}").fetchone()[0]
                for name in ("user_version", "application_id", "encoding")
            }
            normalized = json.dumps(
                {"metadata": metadata, "sql": list(logical.iterdump())},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            return hashlib.sha256(normalized).hexdigest()
    if kind == "file":
        return _sha256_file(path)
    rows = _inventory(path, kind)
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _source_state(source: BackupSource) -> dict[str, object]:
    if not source.path.exists():
        if source.required:
            raise BackupError(f"required backup source is missing: {source.name} ({source.path})")
        return {"name": source.name, "present": False, "required": False}
    if source.path.is_symlink():
        raise BackupError(f"backup source must not be a symlink: {source.path}")
    expected = source.path.is_file() if source.kind != "tree" else source.path.is_dir()
    if not expected:
        raise BackupError(f"backup source has wrong type: {source.name} ({source.path})")
    return {
        "name": source.name,
        "present": True,
        "required": source.required,
        "kind": source.kind,
        "sensitive": source.sensitive,
        "source_path": str(source.path),
        "source_fingerprint": _fingerprint(source.path, source.kind),
    }


def source_set_watermark(sources: Iterable[BackupSource]) -> tuple[str, list[dict[str, object]]]:
    states = [_source_state(source) for source in sources]
    payload = [
        {key: row.get(key) for key in ("name", "present", "kind", "source_fingerprint")}
        for row in states
    ]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return digest, states


def _copy_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as src, closing(
        sqlite3.connect(target)
    ) as dst:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError(f"SQLite integrity check failed for {source}: {result}")
        dst.commit()


def _copy_source(source: BackupSource, root: Path) -> dict[str, object]:
    target = root / "data" / source.name
    if source.kind == "sqlite":
        target = target.with_suffix(".sqlite3")
        _copy_sqlite(source.path, target)
        copied_kind = "file"
    elif source.kind == "file":
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_native_io_path(source.path), _native_io_path(target))
        copied_kind = "file"
    else:
        target.mkdir(parents=True, exist_ok=False)
        source_root = _native_io_path(source.path)
        for item in _included_files(source.path):
            destination = target / item.relative_to(source_root)
            _native_io_path(destination.parent).mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, _native_io_path(destination))
        copied_kind = "tree"
    inventory = _inventory(target, copied_kind)
    return {
        "snapshot_path": target.relative_to(root).as_posix(),
        "files": inventory,
        "file_count": len(inventory),
        "bytes": sum(int(str(row["bytes"])) for row in inventory),
        "copied_source_fingerprint": _fingerprint(target, source.kind),
    }


def _fsync_tree(root: Path) -> None:
    for path in sorted(_native_io_path(root).rglob("*")):
        if path.is_file():
            # Windows rejects fsync on a read-only descriptor; r+b is used only
            # to obtain a flush-capable handle and never writes file content.
            with path.open("r+b") as handle:
                os.fsync(handle.fileno())
    try:
        fd = os.open(root, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _validate_copied_semantics(snapshot_root: Path, entries: list[dict[str, object]]) -> None:
    by_name = {str(row["name"]): row for row in entries if row.get("present")}
    for name in ("kanban_events", "maintenance_events", "config_audit"):
        row = by_name.get(name)
        if not row:
            continue
        path = snapshot_root / str(row["snapshot_path"])
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if raw.strip():
                try:
                    json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise BackupError(f"invalid {name} JSONL line {line_number}: {exc}") from exc
    intent = by_name.get("config_intent")
    if intent:
        path = snapshot_root / str(intent["snapshot_path"])
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BackupError(f"invalid board config transaction intent: {exc}") from exc
        raise BackupError(
            "board config transaction intent is pending; reconcile configs before backup"
        )
    for name in ("kanban_config", "domain_config", "autonomy_config"):
        row = by_name.get(name)
        if row:
            parsed = yaml.safe_load(
                (snapshot_root / str(row["snapshot_path"])).read_text(encoding="utf-8")
            )
            if not isinstance(parsed, dict) or "schema_version" not in parsed:
                raise BackupError(f"snapshotted {name} is not a versioned config")
            if name == "autonomy_config":
                from command_center.schemas.contracts import AutonomyConfig
                try:
                    AutonomyConfig.model_validate(parsed)
                except ValueError as exc:
                    raise BackupError(
                        f"snapshotted autonomy_config is invalid: {exc}") from exc


def create_snapshot(backup_root: Path, sources: list[BackupSource], *,
                    now: datetime | None = None) -> dict[str, object]:
    """Create or exactly reconcile one immutable snapshot of the current watermark."""
    if not sources or len({source.name for source in sources}) != len(sources):
        raise BackupError("backup sources must be non-empty and uniquely named")
    backup_root.mkdir(parents=True, exist_ok=True)
    if backup_root.is_symlink():
        raise BackupError("backup root must not be a symlink")
    backup_root = backup_root.resolve()
    root_resolved = backup_root
    for source in sources:
        source_resolved = source.path.resolve(strict=False)
        if source_resolved == root_resolved or root_resolved in source_resolved.parents:
            raise BackupError(f"backup root recursion is forbidden: {source.name}")

    watermark, initial = source_set_watermark(sources)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # Exact content reuse is safe: the gate has just recomputed the complete
    # current watermark, and the immutable candidate is fully re-verified.
    for candidate in sorted(
        (path for path in backup_root.iterdir()
         if path.is_dir() and not path.name.startswith(".")),
        reverse=True,
    ):
        try:
            # Reading the small receipt first avoids re-hashing every historical
            # snapshot when its declared source watermark cannot possibly match.
            # An apparent exact match is still fully verified below before reuse.
            candidate_manifest = json.loads(
                (candidate / "manifest.json").read_text(encoding="utf-8")
            )
            if (
                candidate_manifest.get("schema_version") != SCHEMA_VERSION
                or candidate_manifest.get("source_set_watermark") != watermark
            ):
                continue
            existing = verify_snapshot(candidate)
        except (BackupError, OSError, ValueError, json.JSONDecodeError):
            continue
        receipt = dict(existing)
        receipt["gate_checked_at"] = stamp.isoformat()
        receipt["reused_exact_watermark"] = True
        return receipt
    snapshot_id = f"{stamp.strftime('%Y%m%dT%H%M%S.%fZ')}-{watermark[:12]}"
    destination = backup_root / snapshot_id
    if destination.exists():
        existing_manifest = verify_snapshot(destination)
        if existing_manifest["source_set_watermark"] != watermark:
            raise BackupError(f"snapshot id collision at {destination}")
        return existing_manifest

    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=backup_root))
    try:
        entries: list[dict[str, object]] = []
        state_by_name = {str(row["name"]): row for row in initial}
        for source in sources:
            state = dict(state_by_name[source.name])
            if state.get("present"):
                copied = _copy_source(source, staging)
                if copied["copied_source_fingerprint"] != state["source_fingerprint"]:
                    raise BackupError(
                        f"backup source changed while copying: {source.name}")
                state.update(copied)
            entries.append(state)
        final_watermark, final = source_set_watermark(sources)
        if final_watermark != watermark:
            raise BackupError("a backup source changed while the snapshot was being created")
        if [row.get("source_fingerprint") for row in final] != [
            row.get("source_fingerprint") for row in initial
        ]:
            raise BackupError("backup source fingerprints changed during snapshot")
        _validate_copied_semantics(staging, entries)
        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": stamp.isoformat(),
            "source_set_watermark": watermark,
            "consistency": "stable-per-source-with-final-source-set-watermark",
            "retention": "forever-no-automatic-delete",
            "protection": "local-layer; external-or-off-host-root-required-for-disaster-recovery",
            "sources": entries,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _fsync_tree(staging)
        os.replace(staging, destination)
        try:
            root_fd = os.open(backup_root, os.O_RDONLY)
        except OSError:
            root_fd = None
        if root_fd is not None:
            try:
                os.fsync(root_fd)
            except OSError:
                pass
            finally:
                os.close(root_fd)
        return verify_snapshot(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_snapshot(snapshot_root: Path) -> dict[str, object]:
    snapshot_root = snapshot_root.resolve()
    manifest_path = snapshot_root / "manifest.json"
    if not manifest_path.is_file():
        raise BackupError(f"snapshot manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BackupError(f"unsupported snapshot schema: {manifest.get('schema_version')!r}")
    entries = list(manifest.get("sources") or [])
    for entry in entries:
        if not entry.get("present"):
            continue
        target = _safe_manifest_child(snapshot_root, entry.get("snapshot_path"))
        if target.is_symlink() or not target.exists():
            raise BackupError(f"snapshot source is missing or unsafe: {target}")
        kind = "tree" if target.is_dir() else "file"
        actual = _inventory(target, kind)
        if actual != entry.get("files"):
            raise BackupError(f"snapshot hash mismatch: {entry['name']}")
        if str(entry.get("kind")) == "sqlite":
            with closing(sqlite3.connect(
                f"file:{target.resolve().as_posix()}?mode=ro", uri=True
            )) as db:
                result = db.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise BackupError(f"restored SQLite integrity check failed: {entry['name']}")
    _validate_copied_semantics(snapshot_root, entries)
    return manifest


def verify_snapshot_authorities(
    snapshot_root: Path, sources: list[BackupSource],
) -> dict[str, object]:
    """Verify small authority sources without rehashing unrelated large trees.

    A long-running refresh may reuse its pre-mutation snapshot across batches,
    but only while the configs that ground that refresh are still identical.
    """
    snapshot_root = snapshot_root.resolve()
    manifest_path = snapshot_root / "manifest.json"
    if not manifest_path.is_file():
        raise BackupError(f"snapshot manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BackupError(
            f"unsupported snapshot schema: {manifest.get('schema_version')!r}")
    entries = {
        str(entry.get("name")): entry
        for entry in list(manifest.get("sources") or [])
        if isinstance(entry, dict)
    }
    verified_entries: list[dict[str, object]] = []
    for source in sources:
        current = _source_state(source)
        entry = entries.get(source.name)
        if entry is None:
            raise BackupError(
                f"snapshot is missing required authority: {source.name}")
        if (
            entry.get("present") != current.get("present")
            or entry.get("kind") != current.get("kind")
            or entry.get("source_fingerprint")
            != current.get("source_fingerprint")
        ):
            raise BackupError(
                f"snapshot authority is stale: {source.name}")
        if entry.get("present"):
            target = _safe_manifest_child(
                snapshot_root, entry.get("snapshot_path"))
            actual = _inventory(target, "tree" if target.is_dir() else "file")
            if actual != entry.get("files"):
                raise BackupError(
                    f"snapshot authority hash mismatch: {source.name}")
        verified_entries.append(cast(dict[str, object], entry))
    _validate_copied_semantics(snapshot_root, verified_entries)
    return manifest


def restore_to_empty(snapshot_root: Path, target: Path) -> dict[str, object]:
    """Verify then copy into an empty staging directory; never touch live paths."""
    manifest = verify_snapshot(snapshot_root)
    if target.exists():
        if not target.is_dir() or any(target.iterdir()):
            raise BackupError("restore target must be an empty directory")
    else:
        target.mkdir(parents=True)
    if target.is_symlink():
        raise BackupError("restore target must not be a symlink")
    entries = cast(list[dict[str, object]], manifest["sources"])
    for entry in entries:
        if not entry.get("present"):
            continue
        source = _safe_manifest_child(snapshot_root.resolve(), entry.get("snapshot_path"))
        destination = _safe_manifest_child(target.resolve(), entry.get("snapshot_path"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            _native_io_path(destination).mkdir(parents=True, exist_ok=False)
            source_root = _native_io_path(source)
            for item in _included_files(source_root):
                restored = destination / item.relative_to(source_root)
                _native_io_path(restored.parent).mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, _native_io_path(restored))
        else:
            shutil.copy2(_native_io_path(source), _native_io_path(destination))
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _safe_manifest_child(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise BackupError("snapshot_path must be a non-empty relative POSIX path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise BackupError(f"unsafe snapshot_path in manifest: {value!r}")
    candidate = (root / Path(*relative.parts)).resolve()
    if candidate == root or root not in candidate.parents:
        raise BackupError(f"snapshot_path escapes its root: {value!r}")
    return candidate


def default_sources() -> list[BackupSource]:
    """Explicit allowlist. Optional sources are recorded as absent, never guessed."""
    def path(env: str, default: str) -> Path:
        return Path(os.environ.get(env, default))

    ledger_value = os.environ.get("KANBAN_BACKUP_LEDGER_DB")
    if not ledger_value:
        raise BackupError(
            "KANBAN_BACKUP_LEDGER_DB is required; point it at the live Ledger SQLite "
            "database (the watcher and Airflow containers set this explicitly)"
        )

    return [
        BackupSource("ledger", Path(ledger_value), "sqlite"),
        BackupSource("boards", path("GROWTHOS_BOARD_STORE", "generated/boards"), "tree"),
        BackupSource("kanban_events", path("GROWTHOS_KANBAN_EVENT_LOG", "generated/kanban-events.jsonl"), "file"),
        BackupSource("kanban_config", path("KANBAN_BACKUP_BOARD_CONFIG", "configs/kanban_boards.yaml"), "file", sensitive=False),
        BackupSource("domain_config", path("KANBAN_BACKUP_DOMAIN_CONFIG", "configs/domain_surfaces.yaml"), "file", sensitive=False),
        BackupSource("autonomy_config", path("KANBAN_BACKUP_AUTONOMY_CONFIG", "configs/autonomy.yaml"), "file", sensitive=False),
        BackupSource("config_intent", path("KANBAN_BACKUP_CONFIG_INTENT", "configs/.transactions/board-module.json"), "file", required=False, sensitive=False),
        BackupSource("config_audit", path("KANBAN_BACKUP_CONFIG_AUDIT", "configs/config_audit.jsonl"), "file", required=False, sensitive=False),
        BackupSource("job_search", path("KANBAN_BACKUP_JOB_SEARCH", "data/job_search"), "tree"),
        BackupSource("job_search_memory", path("KANBAN_BACKUP_JOB_SEARCH_MEMORY", "data/job_search/job_search_memory.sqlite"), "sqlite", required=False),
        BackupSource("growth_state", path("GROWTHOS_STATE_DIR", "growth_os/_state"), "tree"),
        BackupSource("growth_memory", path("KANBAN_BACKUP_GROWTH_MEMORY", "growth_os/_state/memory.db"), "sqlite", required=False),
        BackupSource("growth_export", path("KANBAN_BACKUP_GROWTH_EXPORT", "growth_os/_export"), "tree"),
        BackupSource("grand_todo", path("KANBAN_BACKUP_GRAND_TODO", "../betts_basketball/docs/backend/projects/GRAND_TODO_LIST.md"), "file"),
        BackupSource("chat_threads", path("KANBAN_BACKUP_CHAT_THREADS", "generated/chat-threads.json"), "file", required=False),
        BackupSource("chat_transcripts", path("KANBAN_BACKUP_CHAT_TRANSCRIPTS", "generated/chat-transcripts"), "tree", required=False),
        BackupSource("memory", path("KANBAN_BACKUP_MEMORY", "generated/memory"), "tree", required=False),
        BackupSource("maintenance_events", path("KANBAN_BACKUP_MAINTENANCE_EVENTS", "generated/kanban-maintenance-events.jsonl"), "file", required=False),
        BackupSource("appflowy_recovery", path("KANBAN_BACKUP_APPFLOWY_RECOVERY", "archive/appflowy/legacy-growth-os"), "tree", required=False),
    ]


def create_default_snapshot() -> dict[str, object]:
    root = Path(os.environ.get("KANBAN_BACKUP_ROOT", "backups/kanban"))
    return create_snapshot(root, default_sources())
