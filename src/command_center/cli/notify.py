#!/usr/bin/env python3
"""cc notify — push a proactive operational digest to Discord.

Every chat channel is reactive (it answers when messaged). This is the one job
that messages YOU: a compact digest of the daily curator brief headline + the
currently-active Ledger missions, sent to your Discord channel. Run it on a
schedule the same way the kanban bridge runs (host cron / Task Scheduler /
systemd timer) — e.g. once each morning.

Fail-loud, no fake all-clear: a missing token/channel or an unreachable Ledger
stops the run with a clear error rather than sending a half-empty digest that
hides a broken hop. "Active" is defined by the canonical live-mission columns
(board_state.LIVE_COLUMNS) — one source of truth, never a re-listed literal.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import httpx

from ..channels.board_state import LIVE_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"
GROWTHOS_EXPORT = REPO_ROOT / "growth_os" / "_export"
DISCORD_API = "https://discord.com/api/v10"
_LIVE_MISSION_STATES = set(LIVE_COLUMNS["missions"])   # the single source of truth


def read_env(path: Path = ENV_PATH) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def latest_brief_headline(export_dir: Path = GROWTHOS_EXPORT, max_lines: int = 8) -> str:
    """The first non-empty lines of the most recent curator brief (the daily
    research/ops summary). Empty string if no brief has been generated yet — the
    digest then simply omits the section rather than inventing content."""
    briefs = sorted(export_dir.glob("brief_*.md"))
    if not briefs:
        return ""
    lines = [ln for ln in briefs[-1].read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    return "\n".join(lines[:max_lines])


def filter_active(missions: list[dict]) -> list[dict]:
    """Missions in a live (non-terminal) column. Status set comes from
    board_state.LIVE_COLUMNS so it can never drift from the board's own definition."""
    return [m for m in missions
            if str(m.get("status", "")) in _LIVE_MISSION_STATES]


def fetch_active_missions(ledger_url: str) -> list[dict]:
    r = httpx.get(f"{ledger_url.rstrip('/')}/missions", timeout=15)
    r.raise_for_status()
    return filter_active(r.json())


def compose_digest(date_str: str, brief_headline: str, missions: list[dict]) -> str:
    """Pure: the digest text from already-gathered inputs (testable, no I/O)."""
    lines = [f"Growth OS update - {date_str}"]
    if missions:
        lines.append(f"\nActive missions ({len(missions)}):")
        for m in missions:
            action = (m.get("action", "") or "").splitlines()[0][:70]
            lines.append(f"- {m.get('id', '?')} [{m.get('status', '?')}] {action}")
    else:
        lines.append("\nNo active missions.")
    if brief_headline:
        lines.append(f"\nLatest brief:\n{brief_headline}")
    return "\n".join(lines)


def _chunks(text: str, size: int = 1990):
    for i in range(0, len(text), size):
        yield text[i:i + size]


def send_discord(channel_id: str, token: str, content: str) -> None:
    """Post to a Discord channel via the bot REST API, chunked to the 2000-char
    limit. Raises on any non-2xx so a failed push is loud, not silently dropped."""
    with httpx.Client(timeout=30) as client:
        for chunk in _chunks(content):
            r = client.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {token}"},
                json={"content": chunk})
            r.raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser(prog="cc notify")
    ap.add_argument("--dry-run", action="store_true",
                    help="compose and print the digest; do not send to Discord")
    args = ap.parse_args()

    env = read_env()
    ledger_url = env.get("LEDGER_BASE_URL") or "http://localhost:8091"
    missions = fetch_active_missions(ledger_url)     # fail-loud if Ledger is down
    digest = compose_digest(date.today().isoformat(),
                            latest_brief_headline(), missions)

    if args.dry_run:
        print(digest)
        return 0

    token = env.get("DISCORD_BOT_TOKEN", "")
    channel = env.get("DISCORD_CHANNEL_ID") or next(
        (c.strip() for c in env.get("DISCORD_ALLOWED_CHANNEL_IDS", "").split(",")
         if c.strip()), "")
    missing = [name for name, val in
               (("DISCORD_BOT_TOKEN", token),
                ("DISCORD_CHANNEL_ID (or DISCORD_ALLOWED_CHANNEL_IDS)", channel))
               if not val]
    if missing:
        raise SystemExit(f"cc notify: missing {', '.join(missing)} in .env - "
                         "needed to push the digest to Discord")

    send_discord(channel, token, digest)
    print(f"cc notify: pushed {len(digest)} chars to Discord channel {channel} "
          f"({len(missions)} active mission(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
