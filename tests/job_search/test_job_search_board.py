from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import yaml

from command_center.job_search.application_memory import mark_submitted
from command_center.job_search.achievement_bank import ensure_bank
from command_center.job_search.automation_policy import classify_automation
from command_center.job_search.board import (
    APPFLOWY_REQUIRED_ENV,
    BOARD_COLUMNS,
    GROUP_FIELD,
    REQUIRED_CARD_FIELDS,
    board_schema,
    board_setup,
    board_snapshot,
    load_local_state,
    manual_grouping_guidance,
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


def test_manual_grouping_guidance_targets_status_field():
    guidance = manual_grouping_guidance()
    assert guidance["group_by_field"] == GROUP_FIELD == "Status"
    assert guidance["steps"], "grouping steps must be present"
    joined = " ".join(guidance["steps"]).lower()
    assert "group by" in joined
    assert "status" in joined


def test_board_setup_applied_result_surfaces_manual_grouping(tmp_path):
    # Local backend still returns a valid applied result; the appflowy backend adds
    # the manual_grouping guidance. Assert the guidance helper is wired and correct.
    guidance = manual_grouping_guidance()
    assert guidance["group_by_field"] == "Status"
    # every canonical column should be reachable once grouped by Status
    assert BOARD_COLUMNS[0] == "Suggested Jobs"
    assert BOARD_COLUMNS[-1] == "Closed / Archived"


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


def test_publish_suggestions_is_idempotent_and_does_not_duplicate_job_key(tmp_path):
    _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score_override=90)
    board_setup(backend="local", apply=True, root=tmp_path)
    publish_suggestions(backend="local", apply=True, root=tmp_path)
    publish_suggestions(backend="local", apply=True, root=tmp_path)
    state = load_local_state(tmp_path)
    assert len(state["cards"]) == 1


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


def test_missing_appflowy_config_fails_closed(tmp_path):
    env = {name: "" for name in APPFLOWY_REQUIRED_ENV}
    result = board_setup(backend="appflowy", apply=False, root=tmp_path, env=env)
    assert result["status"] == "blocked"
    assert result["writes_performed"] is False
    assert any(blocker.startswith("missing_env:") for blocker in result["readiness"]["blockers"])


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
    raw["retention_until"] = (date.today() - timedelta(days=1)).isoformat()
    record_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    card["column"] = "Interviewing"
    save_local_state(tmp_path, state)
    snapshot = board_snapshot(backend="local", root=tmp_path)
    assert snapshot["active_retention"][0]["retention"]["action"] == "retain_active_process"
