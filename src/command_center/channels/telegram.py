"""Telegram transport adapter (long-poll).

Uses Telegram's getUpdates long-poll over httpx — no extra dependency, no public
webhook. Thin wrapper over GatewayCore: an allowlisted chat's text message ->
run_turn -> reply chunked to Telegram's 4096-char limit.

Env:
  TELEGRAM_BOT_TOKEN          (required; from @BotFather)
  TELEGRAM_ALLOWED_CHAT_IDS   (optional, comma-separated chat IDs; empty = all)
See docs/architecture/channels.md for the BotFather steps and how to find your chat id.
"""
from __future__ import annotations

import httpx

from .core import GatewayConfig, GatewayCore, env

SURFACE = "Telegram"
POLL_TIMEOUT = 50          # seconds Telegram holds the long-poll open
MAX_MSG = 4000             # stay under Telegram's 4096 hard limit


async def run(spec) -> None:
    e = env()
    token = e.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit(
            "telegram: missing TELEGRAM_BOT_TOKEN - talk to @BotFather to create a "
            "bot and copy its token into .env. See docs/architecture/channels.md")
    raw = e.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
    allowed = {c.strip() for c in raw.split(",") if c.strip()}

    cfg = GatewayConfig.build(surface=SURFACE, model=spec.model,
                              max_history=spec.max_history, max_rounds=spec.max_rounds)
    core = GatewayCore(cfg)
    base = f"https://api.telegram.org/bot{token}"
    print(f"telegram: long-polling (model {cfg.model} via {cfg.litellm_base})")

    async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 15) as client:
        offset: int | None = None
        while True:
            resp = await client.get(f"{base}/getUpdates",
                                    params={"timeout": POLL_TIMEOUT,
                                            **({"offset": offset} if offset else {})})
            resp.raise_for_status()
            for upd in resp.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat = (msg.get("chat") or {}).get("id")
                if not text or chat is None:
                    continue
                if allowed and str(chat) not in allowed:
                    continue
                reply = await core.run_turn(chat, text)
                for i in range(0, len(reply), MAX_MSG):
                    await client.post(f"{base}/sendMessage",
                                      json={"chat_id": chat, "text": reply[i:i + MAX_MSG]})
