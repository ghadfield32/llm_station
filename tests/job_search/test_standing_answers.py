"""Standing answers: covered questions auto-answer instead of blocking, the
salary rule follows the posting's range, and category add/remove works through
the profile-settings merge."""
from __future__ import annotations

from datetime import datetime, timezone

from command_center.job_search import automation_policy
from command_center.job_search.config import load_config, merge_profile_settings
from command_center.job_search.schemas import AutomationClass, CanonicalJob
from command_center.job_search.standing_answers import (
    render_application_answers,
    split_detected_phrases,
)

ANSWERS = [
    {"topic": "work_authorization", "question": "US work authorization?",
     "answer": "Yes (US). For any other country: No.",
     "covers": ["work authorization"]},
    {"topic": "disability", "question": "Disability?", "answer": "No",
     "covers": ["disability", "voluntary self identification"]},
    {"topic": "veteran_status", "question": "Protected veteran?",
     "answer": "Not a veteran", "covers": ["veteran"]},
    {"topic": "salary_expectation", "question": "Salary expectations?",
     "answer": "$120,000-$140,000",
     "answer_rule": "upper_end_of_posted_range_else_answer",
     "covers": ["salary expectation"]},
]


def _job(description: str) -> CanonicalJob:
    return CanonicalJob(
        job_key="k1", company="Acme", role_title="Data Scientist",
        normalized_company="acme", normalized_role="data scientist",
        location="Remote US", apply_url="https://acme.example/apply",
        description_text=description,
        last_seen_at=datetime(2026, 7, 10, tzinfo=timezone.utc))


def test_covered_questions_auto_answer_instead_of_blocking(monkeypatch):
    monkeypatch.setattr(automation_policy, "load_standing_answers",
                        lambda base: ANSWERS)
    cfg = load_config()
    job = _job("Apply now. We ask about disability and veteran status, "
               "work authorization, and salary expectation.")
    result = automation_policy.classify_automation(job, cfg)
    assert result.value == AutomationClass.BOT_POSSIBLE
    assert result.blockers == []
    assert set(result.auto_answered) == {
        "disability", "veteran", "work authorization", "salary expectation"}
    assert "standing answers" in result.reason


def test_uncovered_questions_still_block(monkeypatch):
    monkeypatch.setattr(automation_policy, "load_standing_answers",
                        lambda base: ANSWERS)
    cfg = load_config()
    job = _job("Apply now. Disability question plus a captcha and a "
               "security clearance requirement.")
    result = automation_policy.classify_automation(job, cfg)
    assert result.value == AutomationClass.MANUAL_REQUIRED
    assert "manual phrase: captcha" in result.blockers
    assert "manual phrase: security clearance" in result.blockers
    assert result.auto_answered == ["disability"]


def test_no_standing_answers_keeps_old_blocking_behavior():
    # conftest pins load_standing_answers to [] — the pre-feature behavior
    cfg = load_config()
    job = _job("Apply now. We ask about disability.")
    result = automation_policy.classify_automation(job, cfg)
    assert result.value == AutomationClass.MANUAL_REQUIRED
    assert result.blockers == ["manual phrase: disability"]


def test_render_marks_detected_questions_and_applies_salary_rule():
    detected, uncovered = split_detected_phrases(
        "salary expectation and disability info requested",
        ["salary expectation", "disability", "veteran"], ANSWERS)
    assert detected == ["disability", "salary expectation"]
    assert uncovered == []
    text = render_application_answers(
        ANSWERS, salary_max=185000, currency="USD",
        detected_phrases=detected)
    assert "## Salary expectations? **(asked in this posting)**" in text
    assert "upper end of the posted range (~$185,000)" in text
    assert "## Protected veteran?" in text          # rendered, not flagged
    assert "**(asked in this posting)**" not in text.split(
        "## Protected veteran?")[1].split("##")[0]


def test_salary_rule_falls_back_without_a_posted_range():
    text = render_application_answers(ANSWERS)
    assert "$120,000-$140,000" in text
    empty = render_application_answers([])
    assert "No standing answers on file" in empty


def test_profile_merge_adds_and_removes_categories():
    base = {
        "job_categories": [
            {"id": "a", "resume_variant": "v", "keywords": ["x"],
             "role_focus": "primary"},
            {"id": "b", "resume_variant": "v", "keywords": ["y"],
             "role_focus": "secondary"},
        ],
    }
    merged = merge_profile_settings(base, {"job_categories": [
        {"id": "b", "remove": True},
        {"id": "c", "resume_variant": "v", "keywords": ["z"],
         "role_focus": "secondary"},
        {"id": "a", "keywords": ["x", "x2"]},
    ]})
    cats = {c["id"]: c for c in merged["job_categories"]}
    assert "b" not in cats                       # removed
    assert cats["c"]["keywords"] == ["z"]        # added
    assert cats["a"]["keywords"] == ["x", "x2"]  # patched
