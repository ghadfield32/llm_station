"""
The daily email digest — built for a 3-minute skim, in decision-priority order:
Start-Here top-3 → new-since-yesterday / aging → not-proposed (negative memory) → failed sources
→ weekly trend. Every line links to its Kanban card. Pure string building; deterministic.

The report file remains the full record; this is the human-facing summary that drives action.
"""
from __future__ import annotations

import html

from ..pipeline import ScanReport
from ..ranking import confidence_band
from ..triage import TriageDecision


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def _card_link(eid: str, board_url: str) -> str:
    label = _esc(eid)
    if board_url:
        return f'<a href="{_esc(board_url)}#{label}">{label}</a>'
    return f"<code>{label}</code>"


def _row(i, f, score, band, link, mark) -> str:
    return (f"<tr><td>{i}</td><td>{_esc(f.pillar.value)}</td><td>{score:.3f}</td>"
            f"<td>{_esc((f.suggested_target_type and f.suggested_target_type.value) or '')}</td>"
            f"<td>{_esc(f.suggested_risk.value)}</td><td>{band}</td>"
            f"<td>{_esc(f.title)}{mark}<br><small>{_esc(f.claim)}</small>"
            f"<br><small>{link}</small></td></tr>")


def render_digest(report: ScanReport, *, prev_ids: set[str] | None = None,
                  weekly: dict | None = None, board_url: str = "",
                  report_url: str = "", confidence_half_width: float = 0.15) -> tuple[str, str]:
    """Return (subject, html_body). `prev_ids` enables the new-since-yesterday framing; `weekly`
    (a metrics dict) adds the trend strip; URLs make each item one click from acting."""
    shown_ids = set(report.drafted_ids) if report.applied else set(report.would_draft_ids)
    new_ids = None if prev_ids is None else (shown_ids - prev_ids)
    failed = [o for o in report.outcomes if not o.ok]
    suppressed = [r for r in report.triage if r.decision is TriageDecision.NEGATIVE_MEMORY]
    n_new = len(new_ids) if new_ids is not None else len(shown_ids)
    verb = "drafted" if report.applied else "would draft"

    subject = (f"Self-improvement — {n_new} "
               f"{'new ' if new_ids is not None else ''}proposals · {len(failed)} failed "
               f"· {report.date}")

    p: list[str] = []
    a = p.append
    a('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px">')
    a(f"<h2>Daily self-improvement — {_esc(report.date)}"
      f"{'' if report.applied else ' (dry run)'}</h2>")
    a('<p style="color:#555">Observer-only scan. Every item is a <b>Proposed</b> card — '
      "nothing here is approved, promoted, merged, or deployed. Promotion stays human-only.</p>")

    # Start here — the top 3 by score
    a("<h3>▸ Start here (top 3)</h3>")
    if not report.ranked:
        a("<p><i>No new actionable findings.</i></p>")
    else:
        a('<table cellpadding="6" style="border-collapse:collapse;width:100%;font-size:14px" '
          'border="1"><tr style="background:#f2f2f2"><th>#</th><th>Pillar</th><th>Score</th>'
          "<th>Target</th><th>Risk</th><th>Conf.</th><th>Proposal</th></tr>")
        for i, (f, sc) in enumerate(report.ranked[:3], 1):
            lo, hi = confidence_band(f, half_width=confidence_half_width)
            mark = "" if f.experiment_id in shown_ids else " ⚠"
            a(_row(i, f, sc, f"{lo:.2f}–{hi:.2f}", _card_link(f.experiment_id, board_url), mark))
        a("</table>")

    # summary counts
    a(f"<p><b>{verb.title()}:</b> {len(shown_ids)} · "
      f"<b>suppressed (already rejected):</b> {report.suppressed_negative} · "
      f"<b>held:</b> {report.held} · <b>capped:</b> {report.n_capped} · "
      f"<b>findings:</b> {report.n_findings}</p>")

    if new_ids is not None and new_ids:
        a(f"<h3>▸ New since last run ({len(new_ids)})</h3><ul>")
        for f, _ in report.ranked:
            if f.experiment_id in new_ids:
                a(f"<li>{_esc(f.title)} — {_card_link(f.experiment_id, board_url)}</li>")
        a("</ul>")

    if suppressed:
        a(f"<h3>▸ Not proposed — already rejected ({len(suppressed)})</h3>")
        a("<p style='color:#777'><i>The system remembers; it won't re-propose these.</i></p><ul>")
        for r in suppressed:
            a(f"<li>{_esc(r.finding.title)} — {_esc(r.reason)}</li>")
        a("</ul>")

    if failed:
        a(f'<h3 style="color:#b00">⚠ Failed sources ({len(failed)})</h3><ul>')
        for o in failed:
            a(f"<li><b>{_esc(o.scanner)}</b>: {_esc(o.error)}</li>")
        a("</ul>")

    if weekly:
        a("<h3>▸ Weekly trend</h3><ul>")
        for k, v in weekly.items():
            a(f"<li>{_esc(k)}: <b>{_esc(v)}</b></li>")
        a("</ul>")

    links = []
    if board_url:
        links.append(f'<a href="{_esc(board_url)}">Open the board</a>')
    if report_url:
        links.append(f'<a href="{_esc(report_url)}">Full report</a>')
    if links:
        a("<p>" + " &nbsp;·&nbsp; ".join(links) + "</p>")
    a("</div>")
    return subject, "\n".join(p)
