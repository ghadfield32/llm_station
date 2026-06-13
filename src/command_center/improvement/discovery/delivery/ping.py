"""
The chat nudge — one plain line for Discord/Slack/Telegram so the human doesn't have to remember
to check. Links to the board/report; the channel layer does the actual send.
"""
from __future__ import annotations

from ..pipeline import ScanReport


def render_ping(report: ScanReport, *, board_url: str = "", report_url: str = "") -> str:
    shown = report.drafted_ids if report.applied else report.would_draft_ids
    top = ""
    if report.ranked:
        f, sc = report.ranked[0]
        top = f" · top: {f.title} ({report.method.upper()} {sc:.2f})"
    bits = [f"🛠 Daily self-improvement [{report.date}]: {len(shown)} proposals{top}",
            f"{report.n_failed} failed · {report.held} held · "
            f"{report.suppressed_negative} already-rejected"]
    link = board_url or report_url
    if link:
        bits.append(f"→ {link}")
    return " · ".join(bits)
