"""
Gateway log hygiene: the channels gateway must own a size-bounded, rotating gateway.log
(the fix for the 391 MB unrotated file), be idempotent (re-config must not leak file handles
— a leaked handle blocks the Windows rotation rename), and stay quiet on stderr when not a TTY
(so the supervised service does not duplicate the high-volume stream into its marker file).
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from command_center.channels.__main__ import configure_logging


@pytest.fixture(autouse=True)
def _clean_root_logger():
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in list(root.handlers):
        if getattr(h, "_cc_gateway_handler", False):
            root.removeHandler(h)
            h.close()
    yield
    for h in list(root.handlers):
        if getattr(h, "_cc_gateway_handler", False):
            root.removeHandler(h)
            h.close()
    root.handlers[:] = [h for h in saved if h in root.handlers] or root.handlers


def _tagged(root):
    return [h for h in root.handlers if getattr(h, "_cc_gateway_handler", False)]


def test_attaches_bounded_rotating_handler(tmp_path, monkeypatch):
    log = tmp_path / "gateway.log"
    monkeypatch.setenv("GATEWAY_LOG_PATH", str(log))
    monkeypatch.setenv("GATEWAY_LOG_MAX_MB", "1")
    monkeypatch.setenv("GATEWAY_LOG_BACKUPS", "3")
    root = configure_logging()
    rot = [h for h in _tagged(root) if isinstance(h, RotatingFileHandler)]
    assert len(rot) == 1
    assert rot[0].maxBytes == 1 * 1024 * 1024
    assert rot[0].backupCount == 3


def test_reconfigure_is_idempotent_and_closes_old_handler(tmp_path, monkeypatch):
    log = tmp_path / "gateway.log"
    monkeypatch.setenv("GATEWAY_LOG_PATH", str(log))
    configure_logging()
    configure_logging()
    root = logging.getLogger()
    assert len(_tagged(root)) == 1          # no stacking, no leaked handler


def test_rotation_actually_bounds_the_file(tmp_path, monkeypatch):
    log = tmp_path / "gateway.log"
    monkeypatch.setenv("GATEWAY_LOG_PATH", str(log))
    monkeypatch.setenv("GATEWAY_LOG_MAX_MB", "1")
    monkeypatch.setenv("GATEWAY_LOG_BACKUPS", "2")
    configure_logging()
    lg = logging.getLogger("cc.test.rotate")
    for _ in range(30000):
        lg.info("x" * 80)
    backups = sorted(p.name for p in tmp_path.glob("gateway.log*"))
    assert "gateway.log.1" in backups          # it rolled over
    assert log.stat().st_size < 1_100_000      # the live file stays under the cap
    assert not (tmp_path / "gateway.log.3").exists()   # backupCount respected


def test_bad_env_falls_back_to_default(tmp_path, monkeypatch):
    log = tmp_path / "gateway.log"
    monkeypatch.setenv("GATEWAY_LOG_PATH", str(log))
    monkeypatch.setenv("GATEWAY_LOG_MAX_MB", "not-a-number")
    monkeypatch.setenv("GATEWAY_LOG_BACKUPS", "-4")
    root = configure_logging()
    rot = [h for h in _tagged(root) if isinstance(h, RotatingFileHandler)][0]
    assert rot.maxBytes == 25 * 1024 * 1024    # default, not a crash
    assert rot.backupCount == 5


def test_no_stream_handler_when_not_a_tty(tmp_path, monkeypatch):
    # pytest captures stdio, so stderr is not a TTY here — the supervised-service case.
    log = tmp_path / "gateway.log"
    monkeypatch.setenv("GATEWAY_LOG_PATH", str(log))
    root = configure_logging()
    streams = [h for h in _tagged(root)
               if type(h) is logging.StreamHandler]
    assert streams == []
