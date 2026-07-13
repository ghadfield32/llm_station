"""Completion email record: everything done for a job, in one message.

On finalize we ALWAYS write submission_email.html into the packet directory (the
durable record exists even with no mailer configured), then attempt a real SMTP
send using the repo's existing DISCOVERY_SMTP_* convention (email_smtp.SmtpConfig)
with the packet markdown files attached. Recipient: JOB_SEARCH_EMAIL_TO, falling
back to DISCOVERY_SMTP_TO. A missing configuration is reported as a structured
status naming the exact env vars — never a silent skip, never a fake "sent".
"""
from __future__ import annotations

import html
import smtplib
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from pathlib import Path

from command_center.improvement.discovery.delivery.email_smtp import SmtpConfig
from command_center.job_search.agent_writer import writer_env
from command_center.job_search.application_memory import read_job_description
from command_center.job_search.schemas import ApplicationRecord

EMAIL_RECORD_FILENAME = "submission_email.html"

_REQUIRED_SMTP_VARS = (
    "DISCOVERY_SMTP_HOST", "DISCOVERY_SMTP_USER",
    "DISCOVERY_SMTP_PASSWORD", "DISCOVERY_SMTP_FROM",
)

_ATTACHMENTS = (
    ("generated_resume.md", "resume"),
    ("cover_letter.md", "cover letter"),
    ("answer_bank.md", "answer bank"),
    ("recruiter_message.md", "recruiter message"),
    ("followups.md", "follow-up pack"),
    ("manual_checklist.md", "manual checklist"),
)


def email_config_status(env: Mapping[str, str] | None = None) -> dict:
    """Which SMTP vars are set / missing and who the record would go to — the
    diagnostics block the cockpit shows (same pattern as the external chat URLs)."""
    e = env if env is not None else writer_env()
    missing = [var for var in _REQUIRED_SMTP_VARS if not e.get(var)]
    to = e.get("JOB_SEARCH_EMAIL_TO") or e.get("DISCOVERY_SMTP_TO") or ""
    if not to:
        missing.append("JOB_SEARCH_EMAIL_TO (or DISCOVERY_SMTP_TO)")
    return {"configured": not missing, "missing": missing, "to": to or None}


def _section(title: str, body: str) -> str:
    return (
        f"<h2>{html.escape(title)}</h2>"
        f"<pre style=\"white-space:pre-wrap;font-family:inherit\">{html.escape(body.strip())}</pre>"
    )


def build_email_html(app_dir: Path, record: ApplicationRecord) -> str:
    parts = [
        f"<h1>Application record: {html.escape(record.company)} — "
        f"{html.escape(record.role_title)}</h1>",
        "<ul>",
        f"<li>application_id: {html.escape(record.application_id)}</li>",
        f"<li>apply URL: <a href=\"{html.escape(record.apply_url)}\">"
        f"{html.escape(record.apply_url)}</a></li>",
        f"<li>fit score: {record.fit.score}/100 ({html.escape(record.resume_variant)})</li>",
        f"<li>status: {html.escape(record.status)} / {html.escape(record.stage)}"
        f" · applied_at: {html.escape(record.applied_at or '-')}</li>",
        f"<li>generation: {html.escape(str(record.generation.get('mode') or 'unknown'))}"
        f" · revision {record.revision}</li>",
        "</ul>",
    ]
    for filename, label in _ATTACHMENTS:
        path = app_dir / filename
        if path.is_file():
            # errors="replace": a stray non-UTF-8 byte degrades one character
            # of the email body, it must not sink the whole record
            parts.append(_section(
                label.title(), path.read_text(encoding="utf-8", errors="replace")))
    try:
        description = read_job_description(app_dir)
    except (OSError, EOFError) as exc:
        description = f"(job description unreadable: {type(exc).__name__}: {exc})"
    if description.strip():
        parts.append(_section("Job Description", description))
    return "\n".join(parts)


def _build_message(
    subject: str, html_body: str, sender: str, to: str, app_dir: Path,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(
        "This is the HTML application record; enable HTML to view it. "
        "The packet files are attached as markdown.")
    msg.add_alternative(html_body, subtype="html")
    for filename, _ in _ATTACHMENTS:
        path = app_dir / filename
        if path.is_file():
            msg.add_attachment(
                path.read_bytes(), maintype="text", subtype="markdown",
                filename=filename)
    return msg


def _smtp_send(config: SmtpConfig, msg: EmailMessage) -> None:
    with smtplib.SMTP(config.host, config.port, timeout=30) as s:
        if config.use_tls:
            s.starttls()
        s.login(config.user, config.password)
        s.send_message(msg)


def send_application_record(
    app_dir: Path,
    record: ApplicationRecord,
    *,
    env: Mapping[str, str] | None = None,
    sender_fn: Callable[[SmtpConfig, EmailMessage], None] | None = None,
) -> dict:
    """Write the durable HTML record, then send it when SMTP is configured.
    Returns {status: recorded_only|sent|error, record_path, to, missing?, error?}."""
    e = env if env is not None else writer_env()
    record_path = app_dir / EMAIL_RECORD_FILENAME
    status = email_config_status(e)
    result = {"record_path": str(record_path), "to": status["to"]}
    try:
        html_body = build_email_html(app_dir, record)
        record_path.write_text(html_body, encoding="utf-8")
    except Exception as exc:  # the email step must never sink a finalize —
        # the failure is reported verbatim in the result and evidence file
        return {**result, "status": "error",
                "error": f"building/writing the record failed: "
                         f"{type(exc).__name__}: {exc}"}
    if not status["configured"]:
        return {
            **result,
            "status": "recorded_only",
            "missing": status["missing"],
            "detail": (
                "email record written to disk; real send skipped — set "
                + ", ".join(status["missing"]) + " to enable delivery"),
        }
    subject = f"Application record: {record.company} — {record.role_title}"
    try:
        cfg = SmtpConfig.from_env(e)
        msg = _build_message(subject, html_body, cfg.sender, status["to"], app_dir)
        (sender_fn or _smtp_send)(cfg, msg)
    except Exception as exc:  # send failure must reach Geoff, not crash finalize
        return {**result, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return {**result, "status": "sent", "subject": subject}
