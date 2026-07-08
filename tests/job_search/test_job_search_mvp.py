from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from command_center.job_search.achievement_bank import (
    default_bank,
    ensure_bank,
    save_bank,
    validate_claim_ids,
)
from command_center.job_search.application_memory import (
    append_note,
    create_prepared_application,
    mark_submitted,
)
from command_center.job_search.cli import main as job_search_main
from command_center.job_search.automation_policy import can_submit, classify_automation
from command_center.job_search.config import load_config
from command_center.job_search.interview_prep import render_answer_bank, select_stories
from command_center.job_search.resume_selection import select_resume
from command_center.job_search.retention import apply_retention, plan_retention
from command_center.job_search.scoring import classify_company_tier, normalize_job_from_text, score_job
from command_center.job_search.schemas import AutomationClass, JobSearchConfig, ProjectType

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "job_search" / "examples"


def _job(name: str):
    return normalize_job_from_text((EXAMPLES / name).read_text(encoding="utf-8"))


def test_config_validates_and_auto_submit_is_disabled():
    cfg = load_config()
    assert not cfg.job_search.auto_submit_enabled
    assert not cfg.job_search.submit_without_geoff_selection
    assert cfg.job_search.require_geoff_selection
    assert not can_submit(cfg)


def test_config_rejects_auto_submit_enabled():
    raw = yaml.safe_load((ROOT / "configs" / "job_search.yaml").read_text(encoding="utf-8"))
    raw["job_search"]["auto_submit_enabled"] = True
    with pytest.raises(ValueError, match="auto_submit_enabled"):
        JobSearchConfig.model_validate(raw)


def test_data_job_search_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/job_search/" in gitignore


def test_default_bank_contains_world_model_sports_with_evidence():
    bank = default_bank()
    wms = [a for a in bank.achievements if a.company == "World Model Sports LLC"]
    assert len(wms) >= 2
    assert all("evidence/world_model_sports.md" in a.evidence_files for a in wms)
    assert any("founder_operator_product_ai" in a.role_families for a in wms)


def test_claim_validation_rejects_unknown_and_low_confidence(tmp_path):
    bank = default_bank()
    errors = validate_claim_ids(bank, ["missing_claim"])
    assert errors and "unknown achievement id" in errors[0]
    data = bank.model_dump(mode="json")
    data["achievements"][0]["confidence"] = "low"
    low_bank = type(bank).model_validate(data)
    errors = validate_claim_ids(low_bank, [data["achievements"][0]["id"]])
    assert "low-confidence" in errors[0]


def test_scoring_is_deterministic_for_fixture_job():
    cfg = load_config()
    bank = default_bank()
    job = _job("sportsbook_analytics_engineer.md")
    first = score_job(job, bank, cfg)
    second = score_job(job, bank, cfg)
    assert first == second
    assert first.score >= cfg.ranking.min_score_to_show
    assert "jpmc_snowflake_dbt_elt" in first.evidence_achievement_ids


def test_manual_blocker_classification_for_workday_and_eeo():
    cfg = load_config()
    job = _job("fintech_product_data_scientist.md")
    result = classify_automation(job, cfg)
    assert result.value == AutomationClass.MANUAL_REQUIRED
    assert any("Workday" in blocker for blocker in result.blockers)
    assert any("work authorization" in blocker for blocker in result.blockers)
    assert result.mvp_submit_disabled


def test_bot_possible_still_has_mvp_submit_disabled():
    cfg = load_config()
    job = _job("basketball_ai_data_scientist.md")
    result = classify_automation(job, cfg)
    assert result.value == AutomationClass.BOT_POSSIBLE
    assert result.mvp_submit_disabled
    assert not can_submit(cfg)


def test_resume_selection_uses_wms_for_basketball_fixture():
    cfg = load_config()
    bank = default_bank()
    job = _job("basketball_ai_data_scientist.md")
    selection = select_resume(job, bank, cfg)
    assert selection.resume_variant in {"sports_data_scientist", "founder_operator_product_ai"}
    assert any(aid.startswith("wms_") for aid in selection.selected_achievement_ids)
    assert "World Model Sports" not in "\n".join(selection.rejected_claims)


def test_application_memory_and_followup_roundtrip(tmp_path):
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = _job("basketball_ai_data_scientist.md")
    fit = score_job(job, bank, cfg)
    automation = classify_automation(job, cfg)
    selection = select_resume(job, bank, cfg)
    app_dir = create_prepared_application(
        job, fit, automation, selection, root=tmp_path, executor="codex"
    )
    assert (app_dir / "application.yml").exists()
    assert (app_dir / "job_description.md.gz").exists()
    assert (app_dir / "generated_resume.md").exists()
    assert (app_dir / "resume_selection_report.md").exists()
    assert (app_dir / "manual_checklist.md").exists()
    assert (app_dir / "executor.json").exists()
    assert (app_dir / "followups.md").exists()
    assert (app_dir / "answer_bank.md").exists()
    executor = json.loads((app_dir / "executor.json").read_text(encoding="utf-8"))
    assert executor["requested_executor"] == "codex"
    assert executor["auto_submit_enabled"] is False
    record = yaml.safe_load((app_dir / "application.yml").read_text(encoding="utf-8"))
    assert record["stage"] == "needs_geoff"
    submitted = mark_submitted(record["application_id"], root=tmp_path)
    assert submitted.status == "applied"
    note_file = tmp_path / "note.md"
    note_file.write_text("Recruiter asked for availability next week.", encoding="utf-8")
    event = append_note(submitted.application_id, "recruiter_call", note_file, root=tmp_path)
    assert event["type"] == "recruiter_call"
    followup = (app_dir / "followups.md").read_text(encoding="utf-8")
    assert "Recruiter asked for availability" in followup


def test_regenerating_materials_does_not_wipe_existing_communications(tmp_path):
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = _job("basketball_ai_data_scientist.md")
    fit = score_job(job, bank, cfg)
    automation = classify_automation(job, cfg)
    selection = select_resume(job, bank, cfg)
    app_dir = create_prepared_application(job, fit, automation, selection, root=tmp_path)
    note_file = tmp_path / "note.md"
    note_file.write_text("Recruiter called about scheduling.", encoding="utf-8")
    record_id = yaml.safe_load((app_dir / "application.yml").read_text(encoding="utf-8"))["application_id"]
    append_note(record_id, "recruiter_call", note_file, root=tmp_path)
    append_note(record_id, "phone_screen", note_file, root=tmp_path)

    # Simulate Geoff re-triggering material generation for the same job/day
    # (e.g. re-running process-selected after editing the profile).
    create_prepared_application(job, fit, automation, selection, root=tmp_path)

    comms = (app_dir / "communications.jsonl").read_text(encoding="utf-8")
    assert comms.count("recruiter_call") == 1
    assert comms.count("phone_screen") == 1


def test_retention_dry_run_mutates_nothing_and_apply_archives_stale(tmp_path):
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = _job("basketball_ai_data_scientist.md")
    fit = score_job(job, bank, cfg)
    automation = classify_automation(job, cfg)
    selection = select_resume(job, bank, cfg)
    app_dir = create_prepared_application(job, fit, automation, selection, root=tmp_path)
    record_path = app_dir / "application.yml"
    raw = yaml.safe_load(record_path.read_text(encoding="utf-8"))
    raw["status"] = "applied"
    raw["stage"] = "completed"
    raw["applied_at"] = "2026-01-01"
    raw["last_activity_at"] = "2026-01-01"
    raw["retention_until"] = "2026-01-31"
    record_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    before = record_path.read_text(encoding="utf-8")
    dry = plan_retention(root=tmp_path, today=date(2026, 2, 5))
    assert dry["records"][0]["action"] == "archive_compact"
    assert record_path.read_text(encoding="utf-8") == before

    result = apply_retention(root=tmp_path, today=date(2026, 2, 5))
    assert raw["application_id"] in result["archived"]
    assert (app_dir / "ARCHIVED_MINIMAL_LEDGER_WRITTEN.txt").exists()
    db_path = tmp_path / "applications_archive" / "outcomes.sqlite"
    with sqlite3.connect(db_path) as db:
        count = db.execute("SELECT count(*) FROM outcomes").fetchone()[0]
    assert count == 1


def test_active_process_extends_retention_plan(tmp_path):
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = _job("basketball_ai_data_scientist.md")
    app_dir = create_prepared_application(
        job,
        score_job(job, bank, cfg),
        classify_automation(job, cfg),
        select_resume(job, bank, cfg),
        root=tmp_path,
    )
    record_path = app_dir / "application.yml"
    raw = yaml.safe_load(record_path.read_text(encoding="utf-8"))
    raw["status"] = "interviewing"
    raw["stage"] = "interviewing"
    raw["retention_until"] = (date(2026, 1, 1) - timedelta(days=1)).isoformat()
    record_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    plan = plan_retention(root=tmp_path, today=date(2026, 2, 5))
    assert plan["records"][0]["action"] == "retain_active_process"


def test_example_validation_summary_has_three_jobs():
    rows = []
    cfg = load_config()
    bank = default_bank()
    for path in sorted(EXAMPLES.glob("*.md")):
        job = normalize_job_from_text(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "job_key": job.job_key,
                "score": score_job(job, bank, cfg).score,
                "automation": classify_automation(job, cfg).value,
            }
        )
    assert len(rows) == 3
    assert {row["automation"] for row in rows} >= {
        AutomationClass.BOT_POSSIBLE,
        AutomationClass.MANUAL_REQUIRED,
    }


def test_classify_company_tier_matches_faang_sports_tech_and_league_keyword():
    cfg = load_config()
    faang_job = normalize_job_from_text(
        "---\ncompany: Meta\nrole_title: Data Scientist\nlocation: Remote\n---\nWork on ads ranking.\n"
    )
    assert classify_company_tier(faang_job, cfg) == "faang"

    sports_tech_job = normalize_job_from_text(
        "---\ncompany: Second Spectrum\nrole_title: Data Scientist\nlocation: Remote\n---\n"
        "Computer vision for sports.\n"
    )
    assert classify_company_tier(sports_tech_job, cfg) == "sports_tech"

    league_job = normalize_job_from_text(
        "---\ncompany: Acme Sports Co\nrole_title: Data Scientist\nlocation: Remote\n---\n"
        "Support NBA front office analytics.\n"
    )
    assert classify_company_tier(league_job, cfg) == "sports_team"

    unrelated_job = normalize_job_from_text(
        "---\ncompany: Acme Corp\nrole_title: Data Scientist\nlocation: Remote\n---\n"
        "General analytics work.\n"
    )
    assert classify_company_tier(unrelated_job, cfg) == "none"


def test_target_company_bonus_raises_score_and_sets_company_tier(tmp_path):
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    template = (
        "---\ncompany: {company}\nrole_title: Data Scientist\nlocation: Remote\n"
        'salary_text: "$150,000-$160,000"\nsalary_min: 150000\nsalary_max: 160000\n---\n'
        "Python, SQL, experimentation.\n"
    )
    control = normalize_job_from_text(template.format(company="Acme Corp"))
    target = normalize_job_from_text(template.format(company="Second Spectrum"))
    control_fit = score_job(control, bank, cfg)
    target_fit = score_job(target, bank, cfg)
    assert target_fit.company_tier == "sports_tech"
    assert control_fit.company_tier == "none"
    assert target_fit.score == control_fit.score + cfg.ranking.target_company_bonus
    assert "Target company bonus" in target_fit.explanation


def test_default_bank_achievements_have_project_type_and_full_story():
    bank = default_bank()
    for achievement in bank.achievements:
        assert achievement.project_type is not None, achievement.id
        assert achievement.full_story, achievement.id


def test_ensure_bank_backfills_project_type_and_full_story_on_old_bank(tmp_path):
    bank_path = tmp_path / "achievement_bank.yml"
    old_bank = default_bank()
    for achievement in old_bank.achievements:
        achievement.project_type = None
        achievement.full_story = None
    save_bank(bank_path, old_bank)
    refreshed = ensure_bank(bank_path)
    for achievement in refreshed.achievements:
        assert achievement.project_type is not None
        assert achievement.full_story


def test_select_stories_picks_best_achievement_per_project_type():
    bank = default_bank()
    picks = select_stories(bank, {"python", "sql", "bayesian"})
    assert ProjectType.PYTHON_PROJECT in picks
    assert picks[ProjectType.PYTHON_PROJECT].id in {
        "driveline_biomechanics_pipeline",
        "marlins_bayesian_hackathon",
        "nba_player_value_platform",
    }


def test_render_answer_bank_includes_star_stories_and_package_index(tmp_path):
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = _job("basketball_ai_data_scientist.md")
    selection = select_resume(job, bank, cfg)
    text = render_answer_bank(job, bank, selection)
    assert "Answer Bank" in text
    assert "Package / tool index" in text
    assert "Situation:" in text


def test_generate_materials_requires_explicit_geoff_selection():
    with pytest.raises(SystemExit, match="selected-by-geoff"):
        job_search_main(
            [
                "generate-materials",
                "--from-file",
                str(EXAMPLES / "basketball_ai_data_scientist.md"),
            ]
        )


def test_codex_fallback_writes_selection_report_and_cannot_submit(tmp_path):
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = _job("basketball_ai_data_scientist.md")
    app_dir = create_prepared_application(
        job,
        score_job(job, bank, cfg),
        classify_automation(job, cfg),
        select_resume(job, bank, cfg),
        root=tmp_path,
        executor="codex",
    )
    assert (app_dir / "resume_selection_report.md").exists()
    executor = json.loads((app_dir / "executor.json").read_text(encoding="utf-8"))
    assert executor["requested_executor"] == "codex"
    assert executor["auto_submit_enabled"] is False
    assert not can_submit(cfg)
