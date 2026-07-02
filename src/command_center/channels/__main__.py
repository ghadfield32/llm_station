"""Multi-channel gateway runner.

  python -m command_center.channels               # run every enabled channel
  python -m command_center.channels --channels slack,telegram   # subset
  python -m command_center.channels --dry-run     # list enabled channels, connect to nothing

Reads configs/channels.yaml (validated by the ChannelsConfig contract), then
launches each enabled transport adapter concurrently. --dry-run imports no
transport SDK, so it works with only the base install; running a channel needs
the gateways extra (`uv pip install -e ".[gateways]"`).
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

from command_center.schemas import ChannelsConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
CHANNELS_YAML = REPO_ROOT / "configs" / "channels.yaml"
DEFAULT_LOG_PATH = REPO_ROOT / "gateway.log"


def _env_int(name: str, default: int) -> int:
    """Read a positive int env override, ignoring blanks/garbage (fail to the default)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return val if val > 0 else default


def configure_logging() -> logging.Logger:
    """Bound, rotating gateway log — the fix for the 391 MB unrotated gateway.log.

    The SDKs (discord.py et al.) emit via the stdlib root logger; before this that stream
    was funneled through the CMD supervisor's `>> gateway.log 2>&1` with no size bound. Now
    a RotatingFileHandler OWNS gateway.log (default 25 MB x 5 backups = ~150 MB ceiling), so
    the supervisor no longer needs to write the high-volume stream to that file.

    A stderr handler is added ONLY when stderr is a TTY (an interactive `python -m ...` run),
    so the hidden supervised service does not ALSO stream the same INFO lines into its marker
    file and re-grow the problem. Sizes/path are env-overridable:
    GATEWAY_LOG_PATH, GATEWAY_LOG_MAX_MB, GATEWAY_LOG_BACKUPS."""
    log_path = Path(os.environ.get("GATEWAY_LOG_PATH", "").strip() or DEFAULT_LOG_PATH)
    max_bytes = _env_int("GATEWAY_LOG_MAX_MB", 25) * 1024 * 1024
    backups = _env_int("GATEWAY_LOG_BACKUPS", 5)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Idempotent: our own handlers are tagged so a re-entry does not stack duplicates.
    # Close on removal — a leaked open file descriptor on Windows blocks the rotation
    # rename (WinError 32) the next handler attempts.
    for h in list(root.handlers):
        if getattr(h, "_cc_gateway_handler", False):
            root.removeHandler(h)
            h.close()

    file_handler = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler._cc_gateway_handler = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    if sys.stderr is not None and sys.stderr.isatty():
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        stream_handler._cc_gateway_handler = True  # type: ignore[attr-defined]
        root.addHandler(stream_handler)

    return root


def load_config() -> ChannelsConfig:
    return ChannelsConfig.model_validate(yaml.safe_load(CHANNELS_YAML.read_text(encoding="utf-8")))


def select(cfg: ChannelsConfig, only: set[str]) -> list:
    chosen = []
    for ch in cfg.channels:
        if not ch.enabled:
            continue
        if only and ch.name not in only and ch.transport not in only:
            continue
        chosen.append(ch)
    return chosen


async def _run(channels: list) -> None:
    tasks = []
    for spec in channels:
        adapter = importlib.import_module(f"command_center.channels.{spec.transport}")
        tasks.append(adapter.run(spec))
    await asyncio.gather(*tasks)


def main() -> int:
    parser = argparse.ArgumentParser(prog="command_center.channels")
    parser.add_argument("--channels", default="",
                        help="comma-separated channel names or transports to run (default: all enabled)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list enabled channels and exit without connecting")
    args = parser.parse_args()

    # Configure logging BEFORE any adapter starts. discord.py (and the other
    # SDKs) emit via the stdlib logging module but only auto-install a handler
    # under client.run(); the adapters use `await client.start()`, so without
    # this the gateway runs completely silent — a dead or failing bot leaves no
    # trace. The handler writes to a size-bounded, rotating gateway.log (and to
    # stderr too when interactive), so the log can never silently balloon again.
    configure_logging()

    cfg = load_config()
    only = {c.strip() for c in args.channels.split(",") if c.strip()}
    channels = select(cfg, only)

    if not channels:
        print("no enabled channels match — edit configs/channels.yaml (enabled: true) "
              "or pass --channels")
        return 0

    if args.dry_run:
        print(f"{cfg.surface_label} - {len(channels)} channel(s) would start:")
        for ch in channels:
            print(f"  - {ch.name:16s} transport={ch.transport:9s} model={ch.model}")
        return 0

    asyncio.run(_run(channels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
