"""
Delivery — how the daily scan reaches the human: an email digest (where you learn/triage), the
first-party Kanban board (where you act — board.py), and a chat ping (the nudge). All thin callers
over the tested pipeline; none of them can promote, merge, or deploy.
"""
from __future__ import annotations

from .digest import render_digest
from .email_smtp import SmtpConfig, deliver_email
from .ping import render_ping

__all__ = ["render_digest", "SmtpConfig", "deliver_email", "render_ping"]
