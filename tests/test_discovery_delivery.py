"""
Delivery: the email digest (Start-Here / new-since-yesterday / failed / weekly), the stdlib SMTP
sender (dry-run writes HTML; real send is fail-loud on missing creds), and the chat ping.
"""
from __future__ import annotations

import pytest

from command_center.improvement.discovery import (
    Finding, ObserverCharter, Pillar, ScanPipeline,
)
from command_center.improvement.discovery.delivery import (
    deliver_email, render_digest, render_ping,
)
from command_center.improvement.discovery.delivery.email_smtp import SmtpConfig
from command_center.improvement.discovery.sources import Scanner
from command_center.improvement.registry import ExperimentRegistry

NOW = "2026-06-13T06:00:00+00:00"
ENV = {"DISCOVERY_SMTP_HOST": "smtp.example.com", "DISCOVERY_SMTP_USER": "u",
       "DISCOVERY_SMTP_PASSWORD": "p", "DISCOVERY_SMTP_FROM": "bot@example.com"}


class _Static(Scanner):
    name = "code_health"
    pillar = Pillar.CODE_QUALITY

    def __init__(self, findings):
        self._f = findings

    def scan(self):
        return list(self._f)


def _report(tmp_path, apply=False):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    charter = ObserverCharter(reg, report_path=tmp_path / "r.md")
    findings = [Finding(pillar=Pillar.CODE_QUALITY, source="t", title=f"fix {i}",
                        claim=f"claim {i}", evidence="e", impact=i / 5, confidence=0.8)
                for i in range(1, 5)]
    pipe = ScanPipeline(charter)
    return pipe.run([_Static(findings)], date="2026-06-13", now_iso=NOW, apply=apply)


# ----------------------------------------------------------------- digest

def test_digest_subject_and_start_here(tmp_path):
    subject, html = render_digest(_report(tmp_path), board_url="https://board")
    assert "Self-improvement" in subject and "2026-06-13" in subject
    assert "Start here" in html
    assert "Proposed" in html and "promoted, merged, or deployed" in html
    assert "https://board#" in html              # card links present


def test_digest_new_since_last_run(tmp_path):
    rep = _report(tmp_path)
    all_ids = set(rep.would_draft_ids)
    prev = set(list(all_ids)[:2])                # pretend 2 were seen last run
    _, html = render_digest(rep, prev_ids=prev)
    assert "New since last run" in html


def test_digest_shows_failed_and_weekly(tmp_path):
    from command_center.improvement.discovery.sources import ScanOutcome
    rep = _report(tmp_path)
    rep.outcomes.append(ScanOutcome("arxiv", Pillar.FULL_IDEA, [], error="ConnectionError: down"))
    _, html = render_digest(rep, weekly={"acceptance_rate": "38%", "deploy_freq_wk": 0.5})
    assert "Failed sources" in html and "down" in html
    assert "Weekly trend" in html and "acceptance_rate" in html


# ----------------------------------------------------------------- email transport

def test_email_dry_run_writes_html(tmp_path):
    out = tmp_path / "digest.html"
    status = deliver_email("subj", "<b>hi</b>", to="me@x.com", dry_run=True, out_path=out)
    assert "rendered" in status
    assert out.read_text(encoding="utf-8") == "<b>hi</b>"


def test_email_real_send_uses_injected_sender(tmp_path):
    captured = {}

    def fake_send(cfg, msg):
        captured["cfg"] = cfg
        captured["msg"] = msg

    status = deliver_email("subj", "<b>hi</b>", to="me@x.com", dry_run=False,
                           env=ENV, sender_fn=fake_send)
    assert status == "sent to me@x.com"
    msg = captured["msg"]
    assert msg["Subject"] == "subj" and msg["To"] == "me@x.com"
    assert msg["From"] == "bot@example.com"
    assert any(part.get_content_type() == "text/html" for part in msg.walk())
    assert captured["cfg"].host == "smtp.example.com" and captured["cfg"].port == 587


def test_email_real_send_fails_loud_without_creds():
    with pytest.raises(RuntimeError, match="missing SMTP env vars"):
        deliver_email("s", "h", to="x@y.com", dry_run=False, env={})


def test_email_real_send_requires_recipient():
    with pytest.raises(RuntimeError, match="no recipient"):
        deliver_email("s", "h", to="", dry_run=False, env=ENV, sender_fn=lambda c, m: None)


def test_smtpconfig_from_env_parses_port_and_tls():
    cfg = SmtpConfig.from_env({**ENV, "DISCOVERY_SMTP_PORT": "2525", "DISCOVERY_SMTP_TLS": "0"})
    assert cfg.port == 2525 and cfg.use_tls is False


# ----------------------------------------------------------------- ping

def test_ping_is_one_line_summary(tmp_path):
    line = render_ping(_report(tmp_path), board_url="https://board")
    assert "Daily self-improvement" in line and "2026-06-13" in line
    assert "proposals" in line and "https://board" in line
    assert "\n" not in line                       # genuinely one line
