"""The internal (command_center_ui) job-search backend: cockpit-native board.

Full loop, hermetic: publish suggestions -> Geoff selects via a governed event
-> process_selected prepares materials and routes to Needs Geoff -> the cockpit
read path (CommandCenterBoardProvider / event fold) sees every step. The wall
holds: only governed events move cards, and the event log carries no
human-owned approval statuses.
"""
from __future__ import annotations

import json
from pathlib import Path

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.job_search.achievement_bank import ensure_bank
from command_center.job_search.automation_policy import classify_automation
from command_center.job_search.board import (
    INTERNAL_BOARD_ID,
    board_setup,
    board_snapshot,
    process_selected,
    publish_suggestions,
)
from command_center.job_search.config import ensure_data_dirs, load_config
from command_center.job_search.resume_selection import select_resume
from command_center.job_search.scoring import normalize_job_from_text, score_job
from command_center.kanban_sync import ALLOWED_EVENT_TYPES, EventLog, emit_event

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "job_search" / "examples"


def _env(tmp_path: Path) -> dict[str, str]:
    return {"KANBAN_EVENT_LOG": str(tmp_path / "events.jsonl"),
            "KANBAN_BOARD_STORE": str(tmp_path / "boards")}


def _provider(tmp_path: Path) -> CommandCenterBoardProvider:
    return CommandCenterBoardProvider(
        board_id=INTERNAL_BOARD_ID,
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")


def _write_suggestion(root: Path, name: str, *, score: int = 90) -> dict:
    ensure_data_dirs(root)
    cfg = load_config()
    bank = ensure_bank(root / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text((EXAMPLES / name).read_text(encoding="utf-8"))
    fit = score_job(job, bank, cfg).model_dump(mode="json")
    fit["score"] = score
    suggestion = {
        "job": job.model_dump(mode="json"),
        "fit": fit,
        "automation": classify_automation(job, cfg).model_dump(mode="json"),
        "selection": select_resume(job, bank, cfg).model_dump(mode="json"),
    }
    out = root / "source_cache" / "suggestions" / f"{job.job_key}.json"
    out.write_text(json.dumps(suggestion, indent=2), encoding="utf-8")
    return suggestion


def test_internal_setup_reports_store_and_event_log(tmp_path):
    out = board_setup(backend="internal", apply=True, root=tmp_path,
                      env=_env(tmp_path))
    assert out["backend"] == "internal"
    assert out["board_id"] == INTERNAL_BOARD_ID
    assert Path(out["card_store"]).is_dir()


def test_internal_publish_lands_cards_where_the_cockpit_reads(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md")
    out = publish_suggestions(backend="internal", apply=True, root=tmp_path,
                              env=_env(tmp_path))
    assert suggestion["job"]["job_key"] in out["would_create"]
    assert out["writes_performed"] is True
    # the cockpit "Jobs" domain reads exactly this provider
    cards = _provider(tmp_path).list_cards()
    assert len(cards) == 1
    assert cards[0]["status"] == "Suggested Jobs"
    assert cards[0]["company"] == suggestion["job"]["company"]
    assert cards[0]["fit_score"] == 90
    # idempotent: republishing does not duplicate
    publish_suggestions(backend="internal", apply=True, root=tmp_path,
                        env=_env(tmp_path))
    assert len(_provider(tmp_path).list_cards()) == 1


def test_internal_publish_skips_duplicate_apply_url(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md")
    publish_suggestions(backend="internal", apply=True, root=tmp_path,
                        env=_env(tmp_path))
    duplicate = json.loads(json.dumps(suggestion))
    duplicate["job"]["job_key"] = "duplicatekey"
    out = tmp_path / "source_cache" / "suggestions" / "duplicatekey.json"
    out.write_text(json.dumps(duplicate, indent=2), encoding="utf-8")

    result = publish_suggestions(backend="internal", apply=True, root=tmp_path,
                                 env=_env(tmp_path))

    assert len(_provider(tmp_path).list_cards()) == 1
    assert result["skipped_existing_user_column"][0]["reason"] == "duplicate_apply_url"


def test_internal_publish_retires_untouched_card_below_threshold(tmp_path):
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score=90)
    publish_suggestions(backend="internal", apply=True, root=tmp_path,
                        env=_env(tmp_path))
    _write_suggestion(tmp_path, "basketball_ai_data_scientist.md", score=69)

    out = publish_suggestions(backend="internal", apply=True, root=tmp_path,
                              env=_env(tmp_path))

    card = _provider(tmp_path).list_cards()[0]
    assert card["status"] == "Rejected / Skip"
    assert card["fit_score"] == 69
    assert out["retired_below_threshold"][0]["job_key"] == suggestion["job"]["job_key"]


def test_internal_full_loop_selection_gate_then_needs_geoff(tmp_path):
    _write_suggestion(tmp_path, "sportsbook_analytics_engineer.md")
    publish_suggestions(backend="internal", apply=True, root=tmp_path,
                        env=_env(tmp_path))
    provider = _provider(tmp_path)
    card_id = provider.list_cards()[0]["card_id"]

    # nothing selected yet -> process ignores everything (the gate)
    out = process_selected(backend="internal", apply=True, root=tmp_path,
                           env=_env(tmp_path))
    assert out["selected_count"] == 0 and out["ignored_count"] == 1

    # Geoff selects through a governed surface (stage_card event = the drag)
    emit_event(provider.log, action="stage_card", board_id=INTERNAL_BOARD_ID,
               card_id=card_id, source_surface="internal_ui",
               actor_type="human", status_before="Suggested Jobs",
               status_after="Selected by Geoff")

    out = process_selected(backend="internal", apply=True, root=tmp_path,
                           env=_env(tmp_path))
    assert out["selected_count"] == 1
    plan = out["plans"][0]
    assert plan["would_submit"] is False and plan["would_send_message"] is False
    # materials prepared on disk; card routed to the human queue
    assert (tmp_path / "applications_active" / plan["application_id"]).is_dir()
    card = provider.list_cards()[0]
    assert card["status"] == "Needs Geoff"
    assert card["application_id"] == plan["application_id"]
    assert card["materials_path"]

    snap = board_snapshot(backend="internal", root=tmp_path, env=_env(tmp_path))
    assert snap["counts_by_column"]["Needs Geoff"] == 1


def test_internal_processes_unprepared_in_progress_card_from_ui_drag(tmp_path):
    _write_suggestion(tmp_path, "sportsbook_analytics_engineer.md")
    publish_suggestions(backend="internal", apply=True, root=tmp_path,
                        env=_env(tmp_path))
    provider = _provider(tmp_path)
    card_id = provider.list_cards()[0]["card_id"]

    emit_event(provider.log, action="start_todo", board_id=INTERNAL_BOARD_ID,
               card_id=card_id, source_surface="internal_ui",
               actor_type="human", status_before="Suggested Jobs",
               status_after="In Progress")

    out = process_selected(backend="internal", apply=True, root=tmp_path,
                           env=_env(tmp_path), executor="codex")

    assert out["selected_count"] == 1
    assert out["plans"][0]["source_column"] == "In Progress"
    card = provider.list_cards()[0]
    assert card["status"] == "Needs Geoff"
    assert card["application_id"]
    assert card["materials_path"]
    assert (tmp_path / "applications_active" / card["application_id"] / "executor.json").is_file()


def test_internal_does_not_reprocess_prepared_in_progress_card(tmp_path):
    _write_suggestion(tmp_path, "sportsbook_analytics_engineer.md")
    publish_suggestions(backend="internal", apply=True, root=tmp_path,
                        env=_env(tmp_path))
    provider = _provider(tmp_path)
    card_id = provider.list_cards()[0]["card_id"]
    provider.upsert_card(card_id, {"application_id": "already_prepared",
                                   "materials_path": "data/job_search/applications_active/already_prepared"})
    emit_event(provider.log, action="start_todo", board_id=INTERNAL_BOARD_ID,
               card_id=card_id, source_surface="internal_ui",
               actor_type="human", status_before="Suggested Jobs",
               status_after="In Progress")

    out = process_selected(backend="internal", apply=True, root=tmp_path,
                           env=_env(tmp_path))

    assert out["selected_count"] == 0
    assert out["ignored_cards"] == [{"card_id": card_id, "column": "In Progress"}]


def test_internal_event_log_stays_governed(tmp_path):
    _write_suggestion(tmp_path, "fintech_product_data_scientist.md")
    publish_suggestions(backend="internal", apply=True, root=tmp_path,
                        env=_env(tmp_path))
    events = EventLog(tmp_path / "events.jsonl").read()
    assert events, "publish must be event-backed"
    assert all(e.event_type in ALLOWED_EVENT_TYPES for e in events)
    assert all((e.status_after or "").lower() not in
               {"approved", "awaiting approval", "awaiting_approval"}
               for e in events)


def test_live_publish_excludes_fixture_sources(tmp_path):
    """The daily DAG / CLI pass exclude_sources=("fixture",): example postings
    (docs/job_search/examples carry source: fixture) never land on a live
    board as real jobs, while direct/test publishes stay unchanged."""
    suggestion = _write_suggestion(tmp_path, "basketball_ai_data_scientist.md")
    out = publish_suggestions(backend="internal", apply=True, root=tmp_path,
                              env=_env(tmp_path), exclude_sources=("fixture",))
    assert suggestion["job"]["job_key"] not in out.get("would_create", [])
    assert _provider(tmp_path).list_cards() == []
