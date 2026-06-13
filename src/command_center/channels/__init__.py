"""Chat transports for the Growth OS / Command Center gateway.

One authority, many surfaces. Every transport (Discord, Slack, Telegram, WhatsApp)
is a thin adapter over `core.GatewayCore`, which runs the LiteLLM tool-call loop
against the shared growthos action layer. Adapters translate their platform's
events to `GatewayCore.run_turn(conversation_id, text) -> str` and send the reply
back; they hold no policy. Which transports run is declared in configs/channels.yaml
and launched by `python -m command_center.channels` (see __main__.py).
"""
from .core import GatewayCore, GatewayConfig, build_system

__all__ = ["GatewayCore", "GatewayConfig", "build_system"]
