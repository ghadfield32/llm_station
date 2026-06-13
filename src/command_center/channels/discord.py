"""Discord transport adapter.

Thin wrapper over GatewayCore: allowlisted channel/DM message -> run_turn ->
reply chunked to Discord's 2000-char limit. No authority of its own.

Env:
  DISCORD_BOT_TOKEN            (required)
  DISCORD_ALLOWED_CHANNEL_IDS  (required, comma-separated ints; falls back to
                                DISCORD_CHANNEL_ID. DMs from the owner are always allowed)
Create the bot at https://discord.com/developers/applications (Bot -> token,
enable MESSAGE CONTENT intent), then invite it. See docs/channels.md.
"""
from __future__ import annotations

import discord

from .core import GatewayConfig, GatewayCore, env

SURFACE = "Discord"


def _config(spec) -> tuple[str, set[int], GatewayConfig]:
    e = env()
    token = e.get("DISCORD_BOT_TOKEN", "")
    raw = e.get("DISCORD_ALLOWED_CHANNEL_IDS") or e.get("DISCORD_CHANNEL_ID", "")
    missing = [n for n, v in (("DISCORD_BOT_TOKEN", token),
                              ("DISCORD_ALLOWED_CHANNEL_IDS", raw)) if not v]
    if missing:
        raise SystemExit(
            f"discord: missing {', '.join(missing)} - create the bot at "
            "https://discord.com/developers/applications (Bot -> token, enable "
            "MESSAGE CONTENT intent), put both values in .env, and invite it. "
            "See docs/channels.md")
    bad = [c for c in raw.split(",") if c.strip() and not c.strip().isdigit()]
    if bad:
        raise SystemExit(
            f"discord: {bad[0]!r} is not a channel ID. Channel IDs are long numbers "
            "(Settings -> Advanced -> Developer Mode, then right-click channel -> "
            "Copy Channel ID).")
    allowed = {int(c) for c in raw.split(",") if c.strip()}
    cfg = GatewayConfig.build(surface=SURFACE, model=spec.model,
                              max_history=spec.max_history, max_rounds=spec.max_rounds)
    return token, allowed, cfg


class _Client(discord.Client):
    def __init__(self, allowed: set[int], core: GatewayCore):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.allowed = allowed
        self.core = core

    async def on_ready(self):
        print(f"discord: logged in as {self.user} "
              f"(model {self.core.cfg.model} via {self.core.cfg.litellm_base})")

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        is_dm = message.guild is None
        if not is_dm and message.channel.id not in self.allowed:
            return
        async with message.channel.typing():
            reply = await self.core.run_turn(message.channel.id, message.content)
        for i in range(0, len(reply), 1990):
            await message.channel.send(reply[i:i + 1990])


async def run(spec) -> None:
    token, allowed, cfg = _config(spec)
    client = _Client(allowed, GatewayCore(cfg))
    await client.start(token)
