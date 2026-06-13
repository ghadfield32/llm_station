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
from pathlib import Path

import yaml

from command_center.schemas import ChannelsConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
CHANNELS_YAML = REPO_ROOT / "configs" / "channels.yaml"


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
    # trace. stderr is unbuffered, so connect/resume/error lines surface live.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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
