"""WhatsApp transport adapter (Meta Cloud API webhook).

Unlike the other transports, WhatsApp is webhook-based: Meta POSTs inbound
messages to a public HTTPS endpoint, so this adapter runs a small FastAPI server
(uvicorn) and you must expose it (cloudflared/ngrok/own domain) and register the
URL in the Meta app. Thin wrapper over GatewayCore otherwise.

Env:
  WHATSAPP_VERIFY_TOKEN       (required; any secret you also paste into the Meta
                               webhook "Verify token" field)
  WHATSAPP_ACCESS_TOKEN       (required; Graph API token for the WhatsApp product)
  WHATSAPP_PHONE_NUMBER_ID    (required; the sending phone number id)
  WHATSAPP_ALLOWED_NUMBERS    (optional, comma-separated E.164 senders; empty = all)
  WHATSAPP_WEBHOOK_HOST        (default 0.0.0.0)
  WHATSAPP_WEBHOOK_PORT        (default 8080)
See docs/architecture/channels.md for the Meta app + webhook + tunnel steps.
"""
from __future__ import annotations

import httpx

from .core import GatewayConfig, GatewayCore, env

SURFACE = "WhatsApp"
GRAPH = "https://graph.facebook.com/v21.0"
MAX_MSG = 4000


async def run(spec) -> None:
    # Lazy import: the gateways extra carries fastapi + uvicorn.
    from fastapi import FastAPI, Request, Response
    import uvicorn

    e = env()
    verify_token = e.get("WHATSAPP_VERIFY_TOKEN", "")
    access_token = e.get("WHATSAPP_ACCESS_TOKEN", "")
    phone_id = e.get("WHATSAPP_PHONE_NUMBER_ID", "")
    missing = [n for n, v in (("WHATSAPP_VERIFY_TOKEN", verify_token),
                              ("WHATSAPP_ACCESS_TOKEN", access_token),
                              ("WHATSAPP_PHONE_NUMBER_ID", phone_id)) if not v]
    if missing:
        raise SystemExit(
            f"whatsapp: missing {', '.join(missing)} - set up a Meta app with the "
            "WhatsApp product and copy its tokens into .env. See docs/architecture/channels.md")
    raw = e.get("WHATSAPP_ALLOWED_NUMBERS", "")
    allowed = {n.strip() for n in raw.split(",") if n.strip()}
    host = e.get("WHATSAPP_WEBHOOK_HOST", "0.0.0.0")
    port = int(e.get("WHATSAPP_WEBHOOK_PORT", "8080"))

    cfg = GatewayConfig.build(surface=SURFACE, model=spec.model,
                              max_history=spec.max_history, max_rounds=spec.max_rounds)
    core = GatewayCore(cfg)
    app = FastAPI()

    @app.get("/webhook")
    async def verify(request: Request):
        params = request.query_params
        if params.get("hub.mode") == "subscribe" and \
                params.get("hub.verify_token") == verify_token:
            return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
        return Response(status_code=403)

    async def send(to: str, text: str) -> None:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            for i in range(0, len(text), MAX_MSG):
                r = await client.post(
                    f"{GRAPH}/{phone_id}/messages", headers=headers,
                    json={"messaging_product": "whatsapp", "to": to,
                          "text": {"body": text[i:i + MAX_MSG]}})
                r.raise_for_status()

    @app.post("/webhook")
    async def inbound(request: Request):
        body = await request.json()
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for msg in (change.get("value") or {}).get("messages", []):
                    sender = msg.get("from", "")
                    text = ((msg.get("text") or {}).get("body") or "").strip()
                    if not text or not sender:
                        continue
                    if allowed and sender not in allowed:
                        continue
                    reply = await core.run_turn(sender, text)
                    await send(sender, reply)
        return Response(status_code=200)

    print(f"whatsapp: webhook on {host}:{port}/webhook "
          f"(model {cfg.model} via {cfg.litellm_base}); expose it publicly + register in Meta")
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    await server.serve()
