"""
Email transport — stdlib `smtplib`, no new dependencies.

`dry_run=True` writes the HTML digest to disk and sends nothing (no credentials needed) — the
default, safe for previews and CI. A real send reads SMTP credentials from the environment and
FAILS LOUD if any are missing (no silent skip that pretends a mail went out). A `sender_fn` seam
lets tests exercise the send path without opening a socket.

Env vars (real send): DISCOVERY_SMTP_HOST, DISCOVERY_SMTP_PORT (default 587), DISCOVERY_SMTP_USER,
DISCOVERY_SMTP_PASSWORD, DISCOVERY_SMTP_FROM, DISCOVERY_SMTP_TLS (default 1).
"""
from __future__ import annotations

import os
import smtplib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

_DEFAULT_OUT = "generated/self-improvement-digest.html"


@dataclass
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    use_tls: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SmtpConfig:
        e = env if env is not None else os.environ
        required = {"host": "DISCOVERY_SMTP_HOST", "user": "DISCOVERY_SMTP_USER",
                    "password": "DISCOVERY_SMTP_PASSWORD", "sender": "DISCOVERY_SMTP_FROM"}
        missing = [var for var in required.values() if not e.get(var)]
        if missing:
            raise RuntimeError(
                f"cannot send email — missing SMTP env vars: {missing}. "
                "Set them or use --dry-run (writes the digest to disk instead).")
        return cls(host=e["DISCOVERY_SMTP_HOST"], port=int(e.get("DISCOVERY_SMTP_PORT", "587")),
                   user=e["DISCOVERY_SMTP_USER"], password=e["DISCOVERY_SMTP_PASSWORD"],
                   sender=e["DISCOVERY_SMTP_FROM"], use_tls=e.get("DISCOVERY_SMTP_TLS", "1") != "0")


def _build_message(subject: str, html: str, sender: str, to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content("This is the HTML self-improvement digest; enable HTML to view it.")
    msg.add_alternative(html, subtype="html")
    return msg


def _smtp_send(config: SmtpConfig, msg: EmailMessage) -> None:
    with smtplib.SMTP(config.host, config.port, timeout=30) as s:
        if config.use_tls:
            s.starttls()
        s.login(config.user, config.password)
        s.send_message(msg)


def deliver_email(subject: str, html: str, *, to: str, dry_run: bool = True,
                  out_path: str | Path = _DEFAULT_OUT, config: SmtpConfig | None = None,
                  env: Mapping[str, str] | None = None,
                  sender_fn: Callable[[SmtpConfig, EmailMessage], None] | None = None) -> str:
    """Send the digest, or (dry-run) write it to disk. Returns a one-line status string."""
    if dry_run:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
        return f"rendered (dry-run) -> {p}"
    if not to:
        raise RuntimeError("cannot send email — no recipient (--to / DISCOVERY_SMTP_TO)")
    cfg = config or SmtpConfig.from_env(env)
    msg = _build_message(subject, html, cfg.sender, to)
    (sender_fn or _smtp_send)(cfg, msg)
    return f"sent to {to}"
