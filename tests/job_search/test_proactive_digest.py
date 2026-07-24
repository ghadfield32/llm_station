"""Structured job digest + one-line notification, with submit-gate regression."""
from __future__ import annotations

import inspect
from pathlib import Path

from command_center.job_search.digest import build_digest_items
from command_center.job_search.proactive import render_job_digest_ping

ROOT = Path(__file__).resolve().parents[2]


def _cards() -> list[dict]:
    return [
        {
            "card_id": "suggested/one",
            "column": "Suggested Jobs",
            "fields": {
                "company": "Acme Analytics",
                "role_title": "Data Scientist",
                "fit_score": 91,
                "automation_class": "bot_possible",
                "apply_url": "https://jobs.example/acme",
            },
        },
        {
            "card_id": "needs geoff",
            "column": "Needs Geoff",
            "fields": {
                "company": "Hoops AI",
                "role_title": "Basketball ML Engineer",
                "fit_score": 96,
                "automation_class": "manual_required",
                "apply_url": "https://jobs.example/hoops",
            },
        },
        {
            "card_id": "completed",
            "column": "Completed",
            "fields": {
                "company": "Already Applied",
                "role_title": "Ignored",
                "fit_score": 100,
                "automation_class": "bot_possible",
                "apply_url": "https://jobs.example/done",
            },
        },
    ]


def test_build_digest_items_includes_apply_and_review_links_per_item():
    items = build_digest_items(_cards())

    assert len(items) == 2
    suggested = next(item for item in items if item["column"] == "Suggested Jobs")
    needs_geoff = next(item for item in items if item["column"] == "Needs Geoff")
    assert suggested["apply_url"] == "https://jobs.example/acme"
    assert suggested["review_href"] == suggested["apply_url"]
    assert needs_geoff["apply_url"] == "https://jobs.example/hoops"
    assert needs_geoff["review_href"] == (
        "/api/domain/job_application/card/needs%20geoff/packet"
    )
    assert set(suggested) == {
        "company",
        "role",
        "fit_score",
        "automation_class",
        "apply_url",
        "review_href",
        "column",
    }


def test_render_job_digest_ping_is_one_short_line():
    items = build_digest_items(_cards())

    line = render_job_digest_ping(items, "https://cockpit.example/jobs")

    assert line == (
        "2 new jobs to review · top: Acme Analytics — Data Scientist "
        "· → https://cockpit.example/jobs"
    )
    assert "\n" not in line


def test_empty_digest_has_no_push_message():
    assert render_job_digest_ping([], "https://cockpit.example/jobs") is None


def test_submit_gate_still_raises_finalize_blocked_and_endpoint_is_human_gated():
    from command_center.job_search.finalize import (
        FinalizeBlocked,
        finalize_application,
    )

    finalize_source = inspect.getsource(finalize_application)
    assert issubclass(FinalizeBlocked, RuntimeError)
    assert "raise FinalizeBlocked(validation)" in finalize_source

    app_source = (
        ROOT / "services" / "agent_kanban_ui" / "app.py"
    ).read_text(encoding="utf-8")
    start = app_source.index(
        '@app.post("/api/domain/{domain_id}/card/{card_id}/packet/submit")'
    )
    end = app_source.index("\n\n@app.", start + 1)
    submit_endpoint = app_source[start:end]
    assert "_require_chat()" in submit_endpoint
    assert "if not body.confirm:" in submit_endpoint
    assert '"Completed" not in _allowed_transitions(spec, previous)' in submit_endpoint
    assert "submit happens from 'Needs Geoff'" in submit_endpoint
    assert 'actor_type="human"' in submit_endpoint
