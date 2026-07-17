"""Cross-process locks for first-party board and event-log writes.

This module deliberately lives at the command_center package root. Keeping it
outside command_center.boards avoids importing that package's provider registry
while the event-log module itself is still being initialized.

The cockpit runs in Docker while operator CLIs run on the Windows host, so an
in-process threading lock alone cannot protect their shared bind-mounted files.
These locks use atomic lock-file creation, which both sides observe. They are
re-entrant in one thread, serialize threads in one process, and fail loudly
across processes instead of guessing that an existing lock is stale.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class BoardWriteLocked(RuntimeError):
    """Another process owns the requested board/event write lock."""


_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
_THREAD_STATE = threading.local()


def _owner() -> dict[str, object]:
    return {
        "token": uuid.uuid4().hex,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at_epoch": time.time(),
    }


def _read_owner(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_owner_fd(fd: int) -> dict[str, object] | None:
    """Read ownership through an already locked descriptor.

    Windows byte-range locks prevent a second handle from reading byte zero, so
    stale-lock adoption must validate metadata through the descriptor that owns
    the advisory lock.
    """
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while chunk := os.read(fd, 4096):
            chunks.append(chunk)
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a reliable existence probe on Windows: a dead
        # PID can surface as SystemError(WinError 87). Querying the process
        # handle gives an explicit STILL_ACTIVE result without signalling it.
        import ctypes

        query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(query_limited_information, False, pid)
        if not handle:
            # Access denied still proves a live protected process. Invalid
            # parameter proves that no process currently owns this PID.
            return ctypes.get_last_error() != 87
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _try_advisory_lock(fd: int) -> bool:
    """Take a nonblocking OS lock on byte zero of an open lock file."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(  # type: ignore[attr-defined]
                fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
    except OSError:
        return False
    return True


def _wait_for_advisory_lock(
    fd: int, *, attempts: int = 100, delay_seconds: float = 0.005,
) -> bool:
    """Retry a short-lived sharing race without turning contention into a hang."""
    for attempt in range(attempts):
        if _try_advisory_lock(fd):
            return True
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    return False


def _write_owner(fd: int, owner: dict[str, object]) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(owner, sort_keys=True).encode("utf-8"))
    os.fsync(fd)


def _release_owned_lock(
    path: Path, fd: int, owner: dict[str, object],
) -> None:
    """Release and remove an owned lock without an unlocked token-read window.

    The token is validated through the still-locked descriptor. After close,
    contenders can only inspect the live owner and release their advisory lock;
    they cannot adopt or rewrite it. Windows unlink is retried across that brief
    sharing interval. If deletion remains unavailable, a released tombstone is
    written under a reacquired advisory lock so future writers can recover it
    instead of receiving 423 forever.
    """
    current = _read_owner_fd(fd)
    owns_path = current is not None and current.get("token") == owner.get("token")
    os.close(fd)
    if not owns_path:
        return
    for attempt in range(200):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt + 1 < 200:
                time.sleep(0.005)
    # Bounded fallback: make the retained artifact explicitly recoverable.
    try:
        fallback_fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return
    try:
        if not _wait_for_advisory_lock(fallback_fd):
            return
        current = _read_owner_fd(fallback_fd)
        if current is not None and current.get("token") == owner.get("token"):
            released = dict(owner)
            released["pid"] = 0
            released["released"] = True
            _write_owner(fallback_fd, released)
    finally:
        os.close(fallback_fd)


def _adopt_dead_local_owner(
    path: Path, new_owner: dict[str, object],
) -> int | None:
    """Atomically adopt a demonstrably dead same-host lock.

    The advisory lock stays held on the same inode while ownership metadata is
    replaced in place. Competing recoverers therefore cannot both pass a
    check-then-unlink window. Foreign owners remain fail-closed because Docker
    Desktop does not interoperate between Linux flock and Windows msvcrt locks.
    """
    # Publication uses O_EXCL, then writes live-owner metadata, then takes the
    # advisory lock. A contender must inspect that metadata *before* attempting
    # advisory ownership; otherwise it can steal the advisory byte during the
    # creator's tiny publication window and strand a live-PID lock.
    # Pin the inode before the optimistic read. Reading by pathname and opening
    # later permits an unlink/recreate ABA where dead metadata from the old file
    # authorizes advisory locking of a newly published live-owner file.
    try:
        fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return None
    observed = _read_owner_fd(fd)
    observed_pid = observed.get("pid") if observed else None
    if (
        not observed
        or observed.get("hostname") != socket.gethostname()
        or not isinstance(observed.get("token"), str)
        or not isinstance(observed_pid, int)
        or _pid_is_alive(observed_pid)
    ):
        os.close(fd)
        return None
    if not _try_advisory_lock(fd):
        os.close(fd)
        return None
    # Re-read under the lock: another stale recoverer may have adopted between
    # the optimistic read and this acquisition.
    owner = _read_owner_fd(fd)
    pid = owner.get("pid") if owner else None
    if (
        not owner
        or owner.get("hostname") != socket.gethostname()
        or not isinstance(owner.get("token"), str)
        or not isinstance(pid, int)
        or _pid_is_alive(pid)
    ):
        os.close(fd)
        return None
    _write_owner(fd, new_owner)
    return fd


def _process_lock(path: Path) -> threading.RLock:
    key = os.path.abspath(str(path))
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


def _thread_counts() -> dict[str, int]:
    counts = getattr(_THREAD_STATE, "counts", None)
    if counts is None:
        counts = {}
        _THREAD_STATE.counts = counts
    return counts


@contextmanager
def exclusive_write_lock(path: Path) -> Iterator[None]:
    """Hold one cross-process lock, re-entrant only in the owning thread."""
    path = Path(path)
    key = os.path.abspath(str(path))
    process_lock = _process_lock(path)
    process_lock.acquire()
    counts = _thread_counts()
    outermost = counts.get(key, 0) == 0
    fd: int | None = None
    owner: dict[str, object] | None = None
    try:
        if outermost:
            path.parent.mkdir(parents=True, exist_ok=True)
            owner = _owner()
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError as exc:
                fd = _adopt_dead_local_owner(path, owner)
                if fd is None:
                    raise BoardWriteLocked(
                        "another writer currently owns this resource; retry after "
                        "that write finishes"
                    ) from exc
            else:
                _write_owner(fd, owner)
                if not _wait_for_advisory_lock(fd):
                    _release_owned_lock(path, fd, owner)
                    fd = None
                    raise BoardWriteLocked(
                        "could not establish exclusive ownership; retry this write")
        counts[key] = counts.get(key, 0) + 1
        yield
    finally:
        held = counts.get(key, 0)
        if held:
            if held == 1:
                counts.pop(key, None)
                if fd is not None:
                    _release_owned_lock(path, fd, owner or {})
                    fd = None
            else:
                counts[key] = held - 1
        elif fd is not None:
            _release_owned_lock(path, fd, owner or {})
        process_lock.release()


def board_write_lock(store_dir: Path, board_id: str):
    return exclusive_write_lock(
        Path(store_dir) / ".locks" / f"{board_id}.write.lock"
    )


def event_log_write_lock(event_log_path: Path):
    path = Path(event_log_path)
    return exclusive_write_lock(
        path.parent / ".locks" / f"{path.name}.write.lock"
    )


def source_write_lock(source_path: Path):
    """Lock a canonical source next to the file (source-before-board order)."""
    path = Path(source_path)
    return exclusive_write_lock(path.parent / f".{path.name}.write.lock")


def application_memory_write_lock(data_root: Path, application_id: str):
    """Serialize one application's YAML, notes, follow-ups, and retention row.

    The lock lives beside (rather than inside) the application directory so it
    also protects first creation/reactivation and remains visible to both the
    host CLI and the bind-mounted cockpit process.
    """
    return exclusive_write_lock(
        Path(data_root)
        / "applications_active"
        / ".locks"
        / f"{application_id}.write.lock"
    )
