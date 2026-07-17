"""Cross-process lock recovery and fail-closed ownership tests."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from command_center.write_locking import BoardWriteLocked, exclusive_write_lock
import command_center.write_locking as locking


def test_dead_same_host_writer_is_recovered(tmp_path: Path):
    lock = tmp_path / "resource.lock"
    code = (
        "import os,sys;"
        "from pathlib import Path;"
        "from command_center.write_locking import exclusive_write_lock;"
        "p=Path(sys.argv[1]);"
        "ctx=exclusive_write_lock(p);ctx.__enter__();"
        "os._exit(0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(lock)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert lock.is_file()

    with exclusive_write_lock(lock):
        # Acquiring this context proves the dead same-host owner was adopted.
        # Windows correctly prevents a second handle from reading byte zero
        # while the advisory lock is held.
        assert lock.is_file()
    assert not lock.exists()


def test_unknown_host_lock_is_never_guessed_stale(tmp_path: Path):
    lock = tmp_path / "resource.lock"
    lock.write_text(
        json.dumps({"token": "external", "pid": 99999999, "hostname": "other-host"}),
        encoding="utf-8",
    )
    with pytest.raises(BoardWriteLocked, match="another writer"):
        with exclusive_write_lock(lock):
            pass
    assert json.loads(lock.read_text(encoding="utf-8"))["token"] == "external"


def test_simultaneous_recoverers_cannot_both_adopt_dead_lock(tmp_path: Path):
    lock = tmp_path / "resource.lock"
    lock.write_text(
        json.dumps({
            "token": "dead", "pid": 99999999, "hostname": socket.gethostname(),
        }),
        encoding="utf-8",
    )
    gate = tmp_path / "go"
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    code = (
        "import os,sys,time;"
        "from pathlib import Path;"
        "from command_center.write_locking import BoardWriteLocked,exclusive_write_lock;"
        "lock,gate,ready=map(Path,sys.argv[1:]);"
        "(ready/str(os.getpid())).write_text('ready');"
        "\nwhile not gate.exists(): time.sleep(.01)\n"
        "try:\n"
        " with exclusive_write_lock(lock): time.sleep(1)\n"
        "except BoardWriteLocked: sys.exit(2)\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(lock), str(gate), str(ready_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    deadline = time.monotonic() + 10
    while len(list(ready_dir.iterdir())) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(list(ready_dir.iterdir())) == 2
    gate.write_text("go", encoding="utf-8")
    results = [process.wait(timeout=10) for process in processes]
    errors = [process.stderr.read() for process in processes]

    assert sorted(results) == [0, 2], errors


def test_new_owner_retries_transient_advisory_race(monkeypatch, tmp_path: Path):
    lock = tmp_path / "resource.lock"
    original = locking._try_advisory_lock
    attempts = 0

    def transient(fd: int) -> bool:
        nonlocal attempts
        attempts += 1
        return False if attempts == 1 else original(fd)

    monkeypatch.setattr(locking, "_try_advisory_lock", transient)
    with exclusive_write_lock(lock):
        assert lock.is_file()

    assert attempts >= 2
    assert not lock.exists()


def test_live_published_owner_is_rejected_before_advisory_lock(
    monkeypatch, tmp_path: Path,
):
    lock = tmp_path / "resource.lock"
    lock.write_text(
        json.dumps({
            "token": "live",
            "pid": __import__("os").getpid(),
            "hostname": socket.gethostname(),
        }),
        encoding="utf-8",
    )

    def must_not_lock(_fd: int) -> bool:
        raise AssertionError("live-owner contender attempted advisory lock")

    monkeypatch.setattr(locking, "_try_advisory_lock", must_not_lock)
    with pytest.raises(BoardWriteLocked):
        with exclusive_write_lock(lock):
            pass
    assert json.loads(lock.read_text(encoding="utf-8"))["token"] == "live"


def test_cleanup_retries_windows_sharing_contention(monkeypatch, tmp_path: Path):
    lock = tmp_path / "resource.lock"
    original = Path.unlink
    attempts = 0

    def transient(path: Path, *args, **kwargs):
        nonlocal attempts
        if path == lock and attempts < 3:
            attempts += 1
            raise PermissionError("simulated Windows sharing contention")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", transient)
    with exclusive_write_lock(lock):
        assert lock.is_file()

    assert attempts == 3
    assert not lock.exists()
