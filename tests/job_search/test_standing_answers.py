"""Standing answers: covered questions auto-answer instead of blocking, the
salary rule follows the posting's range, and category add/remove works through
the profile-settings merge."""
from __future__ import annotations

from datetime import datetime, timezone

from command_center.job_search import automation_policy
from command_center.job_search.config import (
    load_config,
    merge_profile_settings,
)
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


def test_never_auto_topics_stay_blocked_despite_standing_answers(monkeypatch):
    monkeypatch.setattr(automation_policy, "load_standing_answers",
                        lambda base: ANSWERS)
    cfg = load_config()
    job = _job("Apply now. We ask about disability and veteran status, "
               "work authorization, and salary expectation.")
    result = automation_policy.classify_automation(job, cfg)
    assert result.value == AutomationClass.MANUAL_REQUIRED
    assert set(result.blockers) == {
        "manual phrase: disability", "manual phrase: veteran",
        "manual phrase: work authorization",
    }
    assert result.auto_answered == ["salary expectation"]
    # auto-answered questions live ONLY on the structured field — never mixed
    # into `reason` (which would make them read as blockers in the UI)
    assert "disability" not in result.reason
    assert "standing answers" not in result.reason


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
    assert result.auto_answered == []
    assert "manual phrase: disability" in result.blockers


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
    assert "## Protected veteran?" not in text
    assert "## Disability?" not in text
    assert "## US work authorization?" not in text
    assert "Protected questions are omitted" in text


def test_salary_rule_falls_back_without_a_posted_range():
    text = render_application_answers(ANSWERS)
    assert "$120,000-$140,000" in text
    empty = render_application_answers([])
    assert "No non-sensitive standing answers" in empty


def test_bare_sensitive_values_are_never_reusable_or_rendered():
    protected = load_config().application_questions.never_auto_answer
    for value in (
        "123-45-6789",
        "4111-1111-1111-1111",
        "sk-proj-abcdefghijklmnopqrstuvwx",
    ):
        assert automation_policy.is_never_auto_question(value, protected)
        rendered = render_application_answers([{
            "topic": "ordinary_question", "question": "Anything else?",
            "answer": value, "covers": ["anything else"],
        }])
        assert value not in rendered
        assert "No non-sensitive standing answers" in rendered


def test_reclassify_flips_a_card_when_ordinary_question_is_now_answered(
        tmp_path, monkeypatch):
    """A packet prepared while salary expectation still blocked should re-sort
    to bot_possible once a standing answer covers it — the repeatable catch-up
    for cards already on the board."""
    from command_center.job_search.achievement_bank import ensure_bank
    from command_center.job_search.application_memory import (
        create_prepared_application,
        load_application,
        reclassify_application,
    )
    from command_center.job_search.automation_policy import classify_automation
    from command_center.job_search.config import ensure_data_dirs, load_config
    from command_center.job_search.resume_selection import select_resume
    from command_center.job_search.scoring import normalize_job_from_text, score_job
    from command_center.job_search.standing_answers import save_standing_answers

    ensure_data_dirs(tmp_path)
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text(
        "Company: Acme\nRole: Data Scientist\n"
        "Apply at https://acme.example/apply now.\n"
        "Please provide your salary expectation.")
    # conftest pins the loader to [] → prepared as manual_required
    app_dir = create_prepared_application(
        job, score_job(job, bank, cfg), classify_automation(job, cfg),
        select_resume(job, bank, cfg), root=tmp_path, bank=bank)
    _, before = load_application(app_dir.name, root=tmp_path)
    assert before.automation_class.value == "manual_required"

    # now Geoff provides the standing answer and reclassifies
    save_standing_answers(tmp_path, [
        {"topic": "salary_expectation", "question": "Salary?", "answer": "$140k",
         "covers": ["salary expectation"]}])
    monkeypatch.setattr(automation_policy, "load_standing_answers",
                        lambda base: [
                            {"topic": "salary_expectation", "answer": "$140k",
                             "covers": ["salary expectation"]}])
    result = reclassify_application(app_dir.name, root=tmp_path)
    assert result["changed"] is True
    assert result["before"] == "manual_required"
    assert result["after"] == "bot_possible"
    _, after = load_application(app_dir.name, root=tmp_path)
    assert after.automation_class.value == "bot_possible"
    assert after.manual_required is False


def test_reclassify_suggestion_from_cached_jd(tmp_path, monkeypatch):
    """A SUGGESTED card (no packet) reclassifies from its cached posting — so
    cards published before the standing answers existed catch up. This is why
    the Bot Board showed 0: 33 suggested cards were classified pre-answers."""
    import json as _json
    from command_center.job_search.application_memory import reclassify_suggestion
    from command_center.job_search.config import ensure_data_dirs

    ensure_data_dirs(tmp_path)
    cache = tmp_path / "source_cache" / "suggestions"
    cache.mkdir(parents=True, exist_ok=True)
    job = _job("Apply now. Please provide your salary expectation.")
    (cache / "jk1.json").write_text(_json.dumps({
        "job": _json.loads(job.model_dump_json())}), encoding="utf-8")

    # ordinary salary question is now covered → card should read bot_possible
    monkeypatch.setattr(automation_policy, "load_standing_answers",
                        lambda base: [{"topic": "salary_expectation",
                                       "answer": "$140k",
                                       "covers": ["salary expectation"]}])
    result = reclassify_suggestion("jk1", "manual_required", root=tmp_path)
    assert result is not None
    assert result["after"] == "bot_possible"
    assert result["changed"] is True
    # a missing cache file leaves the card untouched (returns None)
    assert reclassify_suggestion("nope", "manual_required", root=tmp_path) is None


def test_reclassify_leaves_applied_cards_untouched(tmp_path, monkeypatch):
    from command_center.job_search.achievement_bank import ensure_bank
    from command_center.job_search.application_memory import (
        create_prepared_application,
        mark_submitted,
        reclassify_application,
    )
    from command_center.job_search.automation_policy import classify_automation
    from command_center.job_search.config import ensure_data_dirs, load_config
    from command_center.job_search.resume_selection import select_resume
    from command_center.job_search.scoring import normalize_job_from_text, score_job

    ensure_data_dirs(tmp_path)
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text(
        "Company: Acme\nRole: DS\nApply at https://acme.example/apply now.")
    app_dir = create_prepared_application(
        job, score_job(job, bank, cfg), classify_automation(job, cfg),
        select_resume(job, bank, cfg), root=tmp_path, bank=bank)
    monkeypatch.setattr("command_center.job_search.application_memory."
                        "load_config", lambda: cfg)
    mark_submitted(app_dir.name, root=tmp_path)
    result = reclassify_application(app_dir.name, root=tmp_path)
    assert result["changed"] is False
    assert result["skipped"] == "already_applied"


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


def test_profile_merge_whitelists_company_targets_and_retention_days():
    base = {
        "company_targets": {
            "faang": ["Meta"], "sports_teams_keywords": ["NBA"],
            "sports_tech_companies": ["Hudl"], "major_other": ["Stripe"],
        },
        "retention": {
            "rich_application_cache_days": 30,
            "extend_when_active": True,
            "purge_rich_files": False,
        },
    }
    merged = merge_profile_settings(base, {
        "company_targets": {"faang": ["Google"], "unexpected": ["ignored"]},
        "retention": {
            "rich_application_cache_days": 45,
            "extend_when_active": False,
            "purge_rich_files": True,
        },
    })
    assert merged["company_targets"]["faang"] == ["Google"]
    assert "unexpected" not in merged["company_targets"]
    assert merged["retention"] == {
        "rich_application_cache_days": 45,
        "extend_when_active": True,
        "purge_rich_files": False,
    }
