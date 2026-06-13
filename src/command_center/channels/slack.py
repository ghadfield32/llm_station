"""Slack transport adapter (Socket Mode).

Socket Mode means no public webhook is needed — the app dials out to Slack over a
WebSocket. Thin wrapper over GatewayCore: a non-bot message in an allowlisted
channel (or any channel if the allowlist is empty) -> run_turn -> reply.

Env:
  SLACK_BOT_TOKEN            (required, xoxb-...; Bot Token Scopes: app_mentions:read,
                             chat:write, channels:history / im:history)
  SLACK_APP_TOKEN            (required, xapp-...; App-Level Token with connections:write)
  SLACK_ALLOWED_CHANNEL_IDS  (optional, comma-separated channel IDs; empty = all)
Create the app at https://api.slack.com/apps, enable Socket Mode + Event
Subscriptions (message.channels / message.im). See docs/channels.md.
"""
from __future__ import annotations

from .core import GatewayConfig, GatewayCore, env

SURFACE = "Slack"


async def run(spec) -> None:
    # Lazy import: the gateways extra carries slack-bolt; core import must not need it.
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    e = env()
    bot_token = e.get("SLACK_BOT_TOKEN", "")
    app_token = e.get("SLACK_APP_TOKEN", "")
    missing = [n for n, v in (("SLACK_BOT_TOKEN", bot_token),
                              ("SLACK_APP_TOKEN", app_token)) if not v]
    if missing:
        raise SystemExit(
            f"slack: missing {', '.join(missing)} - create the app at "
            "https://api.slack.com/apps, enable Socket Mode, and copy the bot "
            "(xoxb-) + app-level (xapp-) tokens into .env. See docs/channels.md")
    raw = e.get("SLACK_ALLOWED_CHANNEL_IDS", "")
    allowed = {c.strip() for c in raw.split(",") if c.strip()}

    cfg = GatewayConfig.build(surface=SURFACE, model=spec.model,
                              max_history=spec.max_history, max_rounds=spec.max_rounds)
    core = GatewayCore(cfg)
    app = AsyncApp(token=bot_token)

    @app.event("message")
    async def on_message(event, say):
        # ignore bot/edit/system messages; only handle a human's plain text
        if event.get("bot_id") or event.get("subtype"):
            return
        text = (event.get("text") or "").strip()
        channel = event.get("channel", "")
        if not text:
            return
        if allowed and channel not in allowed:
            return
        reply = await core.run_turn(channel, text)
        await say(reply)

    print(f"slack: starting socket mode (model {cfg.model} via {cfg.litellm_base})")
    await AsyncSocketModeHandler(app, app_token).start_async()
