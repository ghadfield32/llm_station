from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import yaml

from command_center.job_search.application_memory import mark_submitted
from command_center.job_search.achievement_bank import ensure_bank
from command_center.job_search.automation_policy import classify_automation
from command_center.job_search.board import (
    BOARD_COLUMNS,
    REQUIRED_CARD_FIELDS,
    board_schema,
    board_setup,
    board_snapshot,
    load_local_state,
    mark_submitted_on_board,
    process_selected,
    publish_suggestions,
    save_local_state,
)
from command_center.job_search.config import ensure_data_dirs, load_config
from command_center.job_search.resume_selection import select_resume
from command_center.job_search.scoring import normalize_job_from_text, score_job

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "job_search" / "examples"


def _write_suggestion(root: Path, name: str, *, score_override: int | None = None) -> dict:
    ensure_data_dirs(root)
    cfg = load_config()
    bank = ensure_bank(root / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text((EXAMPLES / name).read_text(encoding="utf-8"))
    fit = score_job(job, bank, cfg).model_dump(mode="json")
    if score_override is not None:
        fit["score"] = score_override
    suggestion = {
        "job": job.model_dump(mode="json"),
        "fit": fit,
        "automation": classify_automation(job, cfg).model_dump(mode="json"),
        "selection": select_resume(job, bank, cfg).model_dump(mode="json"),
    }
    out = root / "source_cache" / "suggestions" / f"{job.job_key}.json"
    out.write_text(json.dumps(suggestion, indent=2), encoding="utf-8")
    return suggestion


def _write_prepare_only_suggestion(root: Path) -> dict:
    ensure_data_dirs(root)
    cfg = load_config()
    bank = ensure_bank(root / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text(
        """---
company: Quiet Data Lab
role_title: Sports Research Data Scientist
location: Remote US
remote_type: remote
portal: company_site
apply_url: https://example.com/careers/quiet-data-lab
---
Python, SQL, basketball, NBA forecasting, graph analysis, product analytics, and stakeholder metrics.
""",
    )
    fit = score_job(job, bank, cfg).model_dump(mode="json")
    fit["score"] = 84
    suggestion = {
        "job": job.model_dump(mode="json"),
        "fit": fit,
        "automation": classify_automation(job, cfg).model_dump(mode="json"),
        "selection": select_resume(job, bank, cfg).model_dump(mode="json"),
    }
    out = root / "source_cache" / "suggestions" / f"{job.job_key}.json"
    out.write_text(json.dumps(suggestion, indent=2), encoding="utf-8")
    return suggestion


def _write_synthetic_suggestion(root: Path, job_key: str, *, score: int, automation: str) -> dict:
    ensure_data_dirs(root)
    suggestion = {
        "job": {
            "job_key": job_key,
            "company": f"Company {job_key}",
            "role_title": f"Role {job_key}",
            "location": "Remote",
            "remote_type": "remote",
            "source": "test",
            "portal": "company_site",
            "apply_url": f"https://example.com/jobs/{job_key}",
            "salary_text": None,
            "salary_min": None,
            "salary_max": None,
            "deadline": None,
            "last_seen_at": "2026-07-09T00:00:00Z",
        },
        "fit": {
            "score": score,
            "reasons": ["Synthetic fit reason"],
            "risks": [],
            "gaps": [],
            "company_tier": "none",
            "explanation": f"Fit score: {score}/100",
        },
        "automation": {
            "value": automation,
            "reason": "Synthetic automation class",
            "confidence": 0.9,
            "blockers": [] if automation == "bot_possible" else ["manual phrase: test"],
            "mvp_submit_disabled": True,
        },
        "selection": {
            "resume_variant": "analytics_engineer",
            "selected_bullet_ids": [],
            "rejected_claims": [],
        },
    }
    out = root / "source_cache" / "suggestions" / f"{job_key}.json"
    out.write_text(json.dumps(suggestion, indent=2), encoding="utf-8")
    return suggestion


def _setup_and_publish(root: Path, suggestion: dict) -> dict:
    board_setup(backend="local", apply=True, root=root)
    result = publish_suggestions(backend="local", apply=True, root=root)
    assert suggestion["job"]["job_key"] in result["would_create"]
    return load_local_state(root)


def _move_job(root: Path, job_key: str, column: str) -> None:
    state = load_local_state(root)
    card = next(c for c in state["cards"] if c["fields"]["job_key"] == job_key)
    card["column"] = column
    save_local_state(root, state)


def _selected_fixture(root: Path, name: str) -> dict:
    suggestion = _write_suggestion(root, name, score_override=90)
    _setup_and_publish(root, suggestion)
    _move_job(root, suggestion["job"]["job_key"], "Selected by Geoff")
    return suggestion


def test_board_schema_contains_all_required_columns():
    assert board_schema()["columns"] == BOARD_COLUMNS
    assert BOARD_COLUMNS == [
        "Suggested Jobs",
        "Selected by Geoff",
        "In Progress",
        "Needs Geoff",
        "Completed",
        "Interviewing",
        "Rejected / Skip",
        "Closed / Archived",
    ]


def test_board_schema_contains_all_required_fields():
    fields = set(board_schema()["required_fields"])
    assert fields == set(REQUIRED_CARD_FIELDS)
    assert {"job_key", "fit_score", "automation_class", "materials_path"} <= fields






def test_board_setup_dry_run_mutates_nothing(tmp_path):
    result = board_setup(backend="local", apply=False, root=tmp_path)
    assert result["status"] == "dry_run"
    assert result["writes_performed"] is False
    assert not Path(result["state_path"]).exists()


def test_publish_suggestions_creates_only_suggested_jobs_cards(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    state = load_local_state(tmp_path)
    assert len(state["cards"]) == 1
    assert state["cards"][0]["column"] == "Suggested Jobs"


def test_publish_suggestions_balances_bot_and_manual_daily_targets(tmp_path):
    for i in range(30):
        _write_synthetic_suggestion(
            tmp_path,
            f"manual_{i:02d}",
            score=100 - i,
            automation="manual_required",
        )
        _write_synthetic_suggestion(
            tmp_path,
            f"bot_{i:02d}",
            score=99 - i,
            automation="bot_possible",
        )
    board_setup(backend="local", apply=True, root=tmp_path)

    result = publish_suggestions(backend="local", apply=True, root=tmp_path)
    state = load_local_state(tmp_path)
    counts = {}
    for card in state["cards"]:
        value = card["fields"]["automation_class"]
        counts[value] = counts.get(value, 0) + 1

    assert len(state["cards"]) == 50
    assert counts == {"bot_possible": 25, "manual_required": 25}
    assert result["selected_suggestion_counts"] == {"bot_possible": 25, "manual_required": 25}
    assert result["daily_suggestion_targets"] == {
        "bot_possible": 25,
        "manual_required": 25,
        "total": 50,
    }


def test_publish_suggestions_is_idempotent_and_does_not_duplicate_job_key(tmp_path):
    _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    board_setup(backend="local", apply=True, root=tmp_path)
    publish_suggestions(backend="local", apply=True, root=tmp_path)
    publish_suggestions(backend="local", apply=True, root=tmp_path)
    state = load_local_state(tmp_path)
    assert len(state["cards"]) == 1


def test_publish_suggestions_does_not_create_duplicate_apply_url(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    duplicate = json.loads(json.dumps(suggestion))
    duplicate["job"]["job_key"] = "duplicatekey"
    path = tmp_path / "source_cache" / "suggestions" / "duplicatekey.json"
    path.write_text(json.dumps(duplicate, indent=2), encoding="utf-8")

    result = publish_suggestions(backend="local", apply=True, root=tmp_path)

    state = load_local_state(tmp_path)
    assert len(state["cards"]) == 1
    assert result["would_create"] == []
    assert result["skipped_existing_user_column"][0]["reason"] == "duplicate_apply_url"


def test_publish_suggestions_retires_existing_duplicate_apply_url_card(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    duplicate = json.loads(json.dumps(suggestion))
    duplicate["job"]["job_key"] = "duplicatekey"
    duplicate_path = tmp_path / "source_cache" / "suggestions" / "duplicatekey.json"
    duplicate_path.write_text(json.dumps(duplicate, indent=2), encoding="utf-8")
    state = load_local_state(tmp_path)
    duplicate_card = json.loads(json.dumps(state["cards"][0]))
    duplicate_card["card_id"] = "job_duplicatekey"
    duplicate_card["fields"]["job_key"] = "duplicatekey"
    state["cards"].append(duplicate_card)
    save_local_state(tmp_path, state)

    result = publish_suggestions(backend="local", apply=True, root=tmp_path)

    cards = {card["fields"]["job_key"]: card for card in load_local_state(tmp_path)["cards"]}
    assert cards["duplicatekey"]["column"] == "Rejected / Skip"
    assert result["retired_duplicate_apply_url"][0]["job_key"] == "duplicatekey"


def test_publish_suggestions_retires_untouched_card_that_rescores_below_threshold(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=69)

    result = publish_suggestions(backend="local", apply=True, root=tmp_path)

    state = load_local_state(tmp_path)
    assert state["cards"][0]["column"] == "Rejected / Skip"
    assert state["cards"][0]["fields"]["fit_score"] == 69
    assert result["retired_below_threshold"][0]["job_key"] == suggestion["job"]["job_key"]

    path = tmp_path / "source_cache" / "suggestions" / f"{suggestion['job']['job_key']}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["fit"]["reasons"] = ["Updated below-threshold reason"]
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    publish_suggestions(backend="local", apply=True, root=tmp_path)

    fields = load_local_state(tmp_path)["cards"][0]["fields"]
    assert load_local_state(tmp_path)["cards"][0]["column"] == "Rejected / Skip"
    assert fields["why_apply"] == "Updated below-threshold reason"


def test_publish_suggestions_does_not_retire_user_owned_card_below_threshold(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    _move_job(tmp_path, suggestion["job"]["job_key"], "Selected by Geoff")
    _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=69)

    result = publish_suggestions(backend="local", apply=True, root=tmp_path)

    state = load_local_state(tmp_path)
    assert state["cards"][0]["column"] == "Selected by Geoff"
    assert result["retired_below_threshold"] == []


def test_process_selected_ignores_cards_not_in_selected_by_geoff(tmp_path):
    _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    board_setup(backend="local", apply=True, root=tmp_path)
    publish_suggestions(backend="local", apply=True, root=tmp_path)
    result = process_selected(backend="local", apply=True, root=tmp_path)
    assert result["selected_count"] == 0
    assert not list((tmp_path / "applications_active").glob("*"))


def test_process_selected_dry_run_mutates_nothing(tmp_path):
    suggestion = _selected_fixture(tmp_path, "basketball_ai_data_scientist.md")
    before = json.dumps(load_local_state(tmp_path), sort_keys=True)
    result = process_selected(backend="local", apply=False, root=tmp_path)
    after = json.dumps(load_local_state(tmp_path), sort_keys=True)
    assert result["plans"][0]["job_key"] == suggestion["job"]["job_key"]
    assert before == after


def test_process_selected_apply_moves_selected_to_in_progress_first(tmp_path):
    suggestion = _selected_fixture(tmp_path, "basketball_ai_data_scientist.md")
    process_selected(backend="local", apply=True, root=tmp_path)
    card_id = f"job_{suggestion['job']['job_key']}"
    events = [e for e in load_local_state(tmp_path)["events"] if e["card_id"] == card_id]
    destinations = [event["to_column"] for event in events]
    assert "In Progress" in destinations
    assert destinations.index("In Progress") < destinations.index("Needs Geoff")


def test_process_selected_accepts_unprepared_in_progress_from_ui_drag(tmp_path):
    suggestion = _write_suggestion(tmp_path, "sportsbook_analytics_engineer.md", score_override=92)
    board_setup(backend="local", apply=True, root=tmp_path)
    publish_suggestions(backend="local", apply=True, root=tmp_path)
    _move_job(tmp_path, suggestion["job"]["job_key"], "In Progress")

    result = process_selected(backend="local", apply=True, root=tmp_path,
                              executor="codex")

    assert result["selected_count"] == 1
    assert result["plans"][0]["source_column"] == "In Progress"
    state = load_local_state(tmp_path)
    card = state["cards"][0]
    assert card["column"] == "Needs Geoff"
    assert card["fields"]["application_id"]
    assert card["fields"]["materials_path"]
    app_dir = tmp_path / "applications_active" / card["fields"]["application_id"]
    assert json.loads((app_dir / "executor.json").read_text())["requested_executor"] == "codex"


def test_manual_required_selected_card_ends_in_needs_geoff(tmp_path):
    _selected_fixture(tmp_path, "fintech_product_data_scientist.md")
    process_selected(backend="local", apply=True, root=tmp_path)
    state = load_local_state(tmp_path)
    assert state["cards"][0]["fields"]["automation_class"] == "manual_required"
    assert state["cards"][0]["column"] == "Needs Geoff"


def test_prepare_only_selected_card_ends_in_needs_geoff(tmp_path):
    suggestion = _write_prepare_only_suggestion(tmp_path)
    _setup_and_publish(tmp_path, suggestion)
    _move_job(tmp_path, suggestion["job"]["job_key"], "Selected by Geoff")
    process_selected(backend="local", apply=True, root=tmp_path)
    state = load_local_state(tmp_path)
    assert state["cards"][0]["fields"]["automation_class"] == "prepare_only"
    assert state["cards"][0]["column"] == "Needs Geoff"


def test_bot_possible_selected_card_still_ends_in_needs_geoff(tmp_path):
    _selected_fixture(tmp_path, "basketball_ai_data_scientist.md")
    process_selected(backend="local", apply=True, root=tmp_path)
    state = load_local_state(tmp_path)
    assert state["cards"][0]["fields"]["automation_class"] == "bot_possible"
    assert state["cards"][0]["column"] == "Needs Geoff"


def test_process_selected_cannot_set_completed(tmp_path):
    _selected_fixture(tmp_path, "basketball_ai_data_scientist.md")
    process_selected(backend="local", apply=True, root=tmp_path)
    assert load_local_state(tmp_path)["cards"][0]["column"] != "Completed"


def test_mark_submitted_is_the_mvp_path_to_completed(tmp_path):
    _selected_fixture(tmp_path, "basketball_ai_data_scientist.md")
    process_selected(backend="local", apply=True, root=tmp_path)
    card = load_local_state(tmp_path)["cards"][0]
    application_id = card["fields"]["application_id"]
    mark_submitted(application_id, root=tmp_path)
    result = mark_submitted_on_board(application_id, root=tmp_path)
    assert result["status"] == "updated"
    assert load_local_state(tmp_path)["cards"][0]["column"] == "Completed"


def test_publish_preserves_existing_user_notes_and_mixed_fields(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    state = load_local_state(tmp_path)
    state["cards"][0]["fields"]["notes"] = "keep Geoff note"
    state["cards"][0]["fields"]["salary_text"] = "Geoff-entered comp note"
    save_local_state(tmp_path, state)
    path = tmp_path / "source_cache" / "suggestions" / f"{suggestion['job']['job_key']}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["job"]["salary_text"] = "$10-$20"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    publish_suggestions(backend="local", apply=True, root=tmp_path)
    fields = load_local_state(tmp_path)["cards"][0]["fields"]
    assert fields["notes"] == "keep Geoff note"
    assert fields["salary_text"] == "Geoff-entered comp note"


def test_publish_updates_generated_reason_fields_on_suggested_cards(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    path = tmp_path / "source_cache" / "suggestions" / f"{suggestion['job']['job_key']}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["fit"]["reasons"] = ["Updated generated reason"]
    raw["fit"]["risks"] = ["Updated generated risk"]
    raw["automation"]["blockers"] = ["manual phrase: updated blocker"]
    raw["automation"]["value"] = "manual_required"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    publish_suggestions(backend="local", apply=True, root=tmp_path)

    fields = load_local_state(tmp_path)["cards"][0]["fields"]
    assert fields["why_apply"] == "Updated generated reason"
    assert fields["risks"] == "Updated generated risk"
    assert fields["manual_reason"] == "manual phrase: updated blocker"
    assert fields["automation_class"] == "manual_required"




def test_board_snapshot_detects_duplicate_job_keys(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    state = load_local_state(tmp_path)
    duplicate = json.loads(json.dumps(state["cards"][0]))
    duplicate["card_id"] = duplicate["card_id"] + "_duplicate"
    state["cards"].append(duplicate)
    save_local_state(tmp_path, state)
    snapshot = board_snapshot(backend="local", root=tmp_path)
    assert snapshot["duplicate_job_keys"][0]["job_key"] == suggestion["job"]["job_key"]


def test_board_snapshot_flags_completed_cards_missing_application_memory(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    _setup_and_publish(tmp_path, suggestion)
    state = load_local_state(tmp_path)
    state["cards"][0]["column"] = "Completed"
    state["cards"][0]["fields"]["application_id"] = "missing_application"
    save_local_state(tmp_path, state)
    snapshot = board_snapshot(backend="local", root=tmp_path)
    assert snapshot["completed_missing_application_memory"][0]["application_id"] == "missing_application"


def test_interviewing_cards_include_retention_status(tmp_path):
    _selected_fixture(tmp_path, "basketball_ai_data_scientist.md")
    process_selected(backend="local", apply=True, root=tmp_path)
    state = load_local_state(tmp_path)
    card = state["cards"][0]
    application_id = card["fields"]["application_id"]
    record_path = tmp_path / "applications_active" / application_id / "application.yml"
    raw = yaml.safe_load(record_path.read_text(encoding="utf-8"))
    raw["status"] = "interviewing"
    raw["stage"] = "interviewing"
    raw["applied_at"] = (date.today() - timedelta(days=31)).isoformat()
    raw["retention_until"] = (date.today() - timedelta(days=1)).isoformat()
    record_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    card["column"] = "Interviewing"
    save_local_state(tmp_path, state)
    snapshot = board_snapshot(backend="local", root=tmp_path)
    assert snapshot["active_retention"][0]["retention"]["action"] == "archive_compact"
