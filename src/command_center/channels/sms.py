"""SMS transport adapter (Twilio webhook).

Like WhatsApp, SMS is webhook-based: Twilio POSTs inbound messages (form-encoded
`From`/`Body`) to a public HTTPS endpoint, so this adapter runs a small FastAPI
server and you must expose it (cloudflared/own domain) and set it as the number's
"A message comes in" webhook in the Twilio console. The reply goes back through the
Twilio REST API. Thin wrapper over GatewayCore otherwise — one authority, one more
surface; it cannot approve cards (the action layer refuses).

Env:
  TWILIO_ACCOUNT_SID     (required)
  TWILIO_AUTH_TOKEN      (required)
  TWILIO_FROM_NUMBER     (required; your Twilio number, E.164)
  TWILIO_ALLOWED_NUMBERS (optional, comma-separated E.164 senders; empty = all)
  SMS_WEBHOOK_HOST       (default 0.0.0.0)
  SMS_WEBHOOK_PORT       (default 8081)
See docs/architecture/channels.md for the Twilio number + webhook + tunnel steps.
"""
from __future__ import annotations

import httpx

from .core import GatewayConfig, GatewayCore, env

SURFACE = "SMS"
TWILIO_API = "https://api.twilio.com/2010-04-01"
MAX_MSG = 1500          # SMS segments; keep replies tight


async def run(spec) -> None:
    # Lazy import: the gateways extra carries fastapi + uvicorn.
    from fastapi import FastAPI, Request, Response
    import uvicorn

    e = env()
    sid = e.get("TWILIO_ACCOUNT_SID", "")
    token = e.get("TWILIO_AUTH_TOKEN", "")
    from_number = e.get("TWILIO_FROM_NUMBER", "")
    missing = [n for n, v in (("TWILIO_ACCOUNT_SID", sid),
                              ("TWILIO_AUTH_TOKEN", token),
                              ("TWILIO_FROM_NUMBER", from_number)) if not v]
    if missing:
        raise SystemExit(
            f"sms: missing {', '.join(missing)} - create a Twilio number and copy "
            "its credentials into .env. See docs/architecture/channels.md")
    raw = e.get("TWILIO_ALLOWED_NUMBERS", "")
    allowed = {n.strip() for n in raw.split(",") if n.strip()}
    host = e.get("SMS_WEBHOOK_HOST", "0.0.0.0")
    port = int(e.get("SMS_WEBHOOK_PORT", "8081"))

    cfg = GatewayConfig.build(surface=SURFACE, model=spec.model,
                              max_history=spec.max_history, max_rounds=spec.max_rounds)
    core = GatewayCore(cfg)
    app = FastAPI()

    async def send(to: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            for i in range(0, len(text), MAX_MSG):
                r = await client.post(
                    f"{TWILIO_API}/Accounts/{sid}/Messages.json",
                    auth=(sid, token),
                    data={"From": from_number, "To": to,
                          "Body": text[i:i + MAX_MSG]})
                r.raise_for_status()

    @app.post("/sms")
    async def inbound(request: Request):
        form = await request.form()
        sender = (form.get("From") or "").strip()
        text = (form.get("Body") or "").strip()
        if not text or not sender:
            return Response(status_code=200)
        if allowed and sender not in allowed:
            return Response(status_code=200)
        reply = await core.run_turn(sender, text)
        await send(sender, reply)
        # empty TwiML — we already sent via REST (handles long turns past the
        # inline-reply window); 200 acknowledges receipt.
        return Response(content="<Response></Response>",
                        media_type="application/xml")

    print(f"sms: webhook on {host}:{port}/sms (model {cfg.model} via "
          f"{cfg.litellm_base}); expose it publicly + set as the Twilio number webhook")
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    await server.serve()
