"""Typed domain surfaces: registry endpoint + per-source card serving.

Hermetic: the app module is loaded with CONFIGS_DIR pointed at the real
configs/ (the registry is the artifact under test) but the board store, event
log, and fixtures live in tmp. Ledger-backed domains are stubbed. Origin
honesty is the core assertion — fixture data must always say so.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"
EXAMPLES = ROOT / "docs" / "job_search" / "examples"


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("domain_surfaces_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["domain_surfaces_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")
    monkeypatch.setattr(mod, "KANBAN_EVENT_LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(mod, "BOARD_STORE_DIR", tmp_path / "boards")
    return mod, TestClient(mod.app), tmp_path


def _prepared_application(tmp_path: Path) -> Path:
    from command_center.job_search.achievement_bank import ensure_bank
    from command_center.job_search.application_memory import create_prepared_application
    from command_center.job_search.automation_policy import classify_automation
    from command_center.job_search.config import load_config
    from command_center.job_search.resume_selection import select_resume
    from command_center.job_search.scoring import normalize_job_from_text, score_job

    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text(
        (EXAMPLES / "basketball_ai_data_scientist.md").read_text(encoding="utf-8"))
    return create_prepared_application(
        job,
        score_job(job, bank, cfg),
        classify_automation(job, cfg),
        select_resume(job, bank, cfg),
        root=tmp_path,
        executor="codex",
        bank=bank,
    )


def _board_env(tmp_path: Path) -> dict[str, str]:
    return {
        "KANBAN_EVENT_LOG": str(tmp_path / "events.jsonl"),
        "KANBAN_BOARD_STORE": str(tmp_path / "boards"),
    }


def _write_suggestion(tmp_path: Path, name: str) -> dict:
    from command_center.job_search.achievement_bank import ensure_bank
    from command_center.job_search.automation_policy import classify_automation
    from command_center.job_search.config import ensure_data_dirs, load_config
    from command_center.job_search.resume_selection import select_resume
    from command_center.job_search.scoring import normalize_job_from_text, score_job

    ensure_data_dirs(tmp_path)
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text((EXAMPLES / name).read_text(encoding="utf-8"))
    suggestion = {
        "job": job.model_dump(mode="json"),
        "fit": score_job(job, bank, cfg).model_dump(mode="json"),
        "automation": classify_automation(job, cfg).model_dump(mode="json"),
        "selection": select_resume(job, bank, cfg).model_dump(mode="json"),
    }
    out = tmp_path / "source_cache" / "suggestions" / f"{job.job_key}.json"
    out.write_text(json.dumps(suggestion, indent=2), encoding="utf-8")
    return suggestion


def test_domain_registry_lists_all_nine_domains(client):
    _, tc, _ = client
    body = tc.get("/api/domains").json()
    ids = {d["domain_id"] for d in body["domains"]}
    assert ids == {"job_application", "linkedin_post", "book", "paper", "repo",
                   "dag", "machine_upkeep", "mission", "generic_task"}
    # every domain ships a designed empty state, not a blank screen
    assert all(d["empty_state"]["title"] for d in body["domains"])


def test_no_domain_offers_wall_verbs(client):
    _, tc, _ = client
    wall = {"approve_card", "merge", "deploy", "delete_card", "delete_board"}
    for d in tc.get("/api/domains").json()["domains"]:
        assert not wall & set(d.get("allowed_actions", [])), d["domain_id"]


def test_fixture_domain_declares_fixture_origin(client):
    _, tc, _ = client
    body = tc.get("/api/domain/linkedin_post/cards").json()
    assert body["origin"] == "fixtures"
    assert body["cards"], "committed fixtures must render on a fresh install"
    post = body["cards"][0]
    assert post["account"] and post["body"] and "hook" in post


def test_board_store_domain_serves_real_cards_not_fixtures(client):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card("job-1", {"company": "Acme Hoops", "role_title": "DS",
                                   "fit_score": 91}, status="Suggested Jobs")
    body = tc.get("/api/domain/job_application/cards").json()
    assert body["origin"] == "board_store"
    assert body["board_id"] == "job_search_pipeline_internal"
    assert body["cards"][0]["company"] == "Acme Hoops"
    assert body["cards"][0]["status"] == "Suggested Jobs"
    assert body["columns"][:4] == [
        "Suggested Jobs", "Selected by Geoff", "In Progress", "Needs Geoff"]


def test_board_store_domain_empty_is_empty_plus_designed_state(client):
    _, tc, _ = client
    body = tc.get("/api/domain/job_application/cards").json()
    assert body["cards"] == []                      # no fixture smuggling
    assert body["empty_state"]["command"].startswith("uv run cc job-search")


def test_card_detail_and_404(client):
    # linkedin_post is the remaining fixture-backed domain (paper/repo/dag/book
    # now read the AppFlowy board snapshot)
    _, tc, _ = client
    detail = tc.get("/api/domain/linkedin_post/card/post-fixture-1").json()
    assert detail["card"]["card_id"] == "post-fixture-1"
    assert detail["drawer_fields"]                  # drawer grammar travels along
    assert tc.get("/api/domain/linkedin_post/card/nope").status_code == 404
    assert tc.get("/api/domain/nope/cards").status_code == 404


def test_actions_endpoint_reports_dispatch_gate(client):
    _, tc, _ = client
    body = tc.get("/api/domain/job_application/actions").json()
    assert set(body["allowed_actions"]) == {"stage_card", "start_todo",
                                            "block_card", "reject_card",
                                            "finish_todo"}
    assert body["dispatch_enabled"] is False        # chat off in tests
    assert body["write_ready"] is True
    assert body["write_blockers"] == []


def test_domain_move_requires_write_enabled(client):
    _, tc, _ = client
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-1", "status": "Selected by Geoff"})
    assert resp.status_code == 503
    assert "chat/writes not enabled" in resp.json()["detail"]


def test_domain_move_emits_governed_event(client, monkeypatch):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card("job-1", {"company": "Acme Hoops", "role_title": "DS",
                                   "fit_score": 91}, status="Suggested Jobs")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    body = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-1", "status": "Selected by Geoff"}).json()

    assert body["status"] == "moved"
    assert body["event"]["action"] == "stage_card"
    assert body["event"]["status_before"] == "Suggested Jobs"
    assert body["event"]["status_after"] == "Selected by Geoff"
    assert provider.list_cards()[0]["status"] == "Selected by Geoff"
    progress = tc.get("/api/domain/job_application/card/job-1/progress").json()
    assert progress["status"] == "Selected by Geoff"
    assert any(e["action"] == "stage_card" for e in progress["events"])
    assert any(s["id"] == "selected" and s["state"] == "done"
               for s in progress["steps"])
    assert "Acme Hoops" in progress["chat_prompt"]


def test_job_move_to_in_progress_prepares_packet_immediately(client, monkeypatch):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.job_search.board import publish_suggestions
    from command_center.job_search.config import load_config
    from command_center.kanban_sync import EventLog

    suggestion = _write_suggestion(tmp_path, "sportsbook_analytics_engineer.md")
    publish_suggestions(backend="internal", apply=True, root=tmp_path,
                        env=_board_env(tmp_path))
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    card_id = provider.list_cards()[0]["card_id"]
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(
        mod, "_job_search_config_and_root", lambda: (load_config(), tmp_path))

    # gate 1 of the 3-step flow: found -> Selected by Geoff. The selection
    # drag triggers packet prep; the pipeline advances the card to Needs
    # Geoff (agent complete) on its own — Geoff never touches In Progress.
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": card_id, "status": "Selected by Geoff"})

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["event"]["status_after"] == "Selected by Geoff"
    assert body["side_effect"]["operation"] == "process_selected"
    assert body["side_effect"]["selected_count"] == 1
    assert body["side_effect"]["plans"][0]["card_id"] == card_id
    assert body["side_effect"]["plans"][0]["job_key"] == suggestion["job"]["job_key"]
    assert body["card"]["status"] == "Needs Geoff"
    assert body["card"]["application_id"]
    app_dir = tmp_path / "applications_active" / body["card"]["application_id"]
    assert app_dir.is_dir()
    assert (app_dir / "executor.json").is_file()
    assert body["card"]["company"] == suggestion["job"]["company"]


def test_domain_move_reports_write_preflight_failure(client, monkeypatch):
    mod, tc, _ = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(
        mod, "_domain_write_blockers",
        lambda spec: ["kanban event log is not writable: /snapshot/kanban-events.jsonl"])

    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-1", "status": "Selected by Geoff"})

    assert resp.status_code == 503
    assert "domain writes are not available" in resp.json()["detail"]
    body = tc.get("/api/domain/job_application/actions").json()
    assert body["dispatch_enabled"] is False
    assert body["write_ready"] is False


def test_job_domain_move_accepts_each_pipeline_stage(client, monkeypatch):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card(
        "job-validation-sportsbook",
        {"company": "Fixture Sportsbook Analytics",
         "role_title": "Senior Analytics Engineer",
         "fit_score": 91,
         "salary_text": "$150k-$190k",
         "resume_variant": "analytics_engineering"},
        status="Suggested Jobs")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    # a stage skip is refused, and the error NAMES the legal next steps
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-validation-sportsbook",
                         "status": "Needs Geoff"})
    assert resp.status_code == 409
    assert "one step at a time" in resp.json()["detail"]
    assert "Selected by Geoff" in resp.json()["detail"]

    # the legal path: found -> selected -> in progress -> agent complete
    for stage in ["Selected by Geoff", "In Progress", "Needs Geoff"]:
        resp = tc.post("/api/domain/job_application/move",
                       json={"card_id": "job-validation-sportsbook",
                             "status": stage})
        assert resp.status_code == 200, (stage, resp.json())
        assert resp.json()["card"]["status"] == stage

    # one step backward (send back for regeneration) is allowed
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-validation-sportsbook",
                         "status": "In Progress"})
    assert resp.status_code == 200
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-validation-sportsbook",
                         "status": "Needs Geoff"})
    assert resp.status_code == 200

    progress = tc.get(
        "/api/domain/job_application/card/job-validation-sportsbook/progress").json()
    event_actions = {event["action"] for event in progress["events"]}
    assert {"stage_card", "start_todo", "block_card"} <= event_actions

    # Completed is adjacent from Needs Geoff, but still demands the packet
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-validation-sportsbook",
                         "status": "Completed"})
    assert resp.status_code == 400
    assert "no application_id" in resp.json()["detail"]

    # the one-step map travels with the cards payload for the UI dropdowns
    pack = tc.get("/api/domain/job_application/cards").json()
    assert pack["transitions"]["Needs Geoff"] == ["Completed", "In Progress"]
    assert pack["transitions"]["Suggested Jobs"] == [
        "Selected by Geoff", "Rejected / Skip"]
    assert pack["transitions"]["Closed / Archived"] == []


def test_job_domain_completed_marks_application_submitted(client, monkeypatch):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.job_search.config import load_config
    from command_center.kanban_sync import EventLog

    app_dir = _prepared_application(tmp_path)
    app_id = app_dir.name
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card(
        "job-ready-to-submit",
        {"company": "Basketball AI Lab",
         "role_title": "Basketball AI Data Scientist",
         "application_id": app_id,
         "materials_path": str(app_dir)},
        status="Needs Geoff")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(
        mod, "_job_search_config_and_root", lambda: (load_config(), tmp_path))

    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-ready-to-submit",
                         "status": "Completed"})

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["card"]["status"] == "Completed"
    assert body["side_effect"]["application_status"] == "applied"
    record = yaml.safe_load((app_dir / "application.yml").read_text(encoding="utf-8"))
    assert record["status"] == "applied"
    assert record["stage"] == "completed"
    assert record["applied_at"]
    assert "Wait 5 business days" in record["followup"]["next_action"]
    progress = tc.get(
        "/api/domain/job_application/card/job-ready-to-submit/progress").json()
    assert progress["application"]["status"] == "applied"
    assert progress["application"]["stage"] == "completed"


def test_job_domain_card_note_updates_memory_and_interviewing(client, monkeypatch):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.job_search.config import load_config
    from command_center.kanban_sync import EventLog

    app_dir = _prepared_application(tmp_path)
    app_id = app_dir.name
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card(
        "job-recruiter-reached-out",
        {"company": "Basketball AI Lab",
         "role_title": "Basketball AI Data Scientist",
         "application_id": app_id,
         "materials_path": str(app_dir)},
        status="Completed")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(
        mod, "_job_search_config_and_root", lambda: (load_config(), tmp_path))

    resp = tc.post(
        "/api/domain/job_application/card/job-recruiter-reached-out/note",
        json={
            "type": "recruiter_email",
            "source": "email",
            "text": "Recruiter asked for availability next week and salary range.",
        })

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "noted"
    assert body["card"]["status"] == "Interviewing"
    assert body["progress"]["application"]["communications_count"] == 1
    assert body["progress"]["application"]["latest_communication"]["source"] == "email"
    comms = (app_dir / "communications.jsonl").read_text(encoding="utf-8")
    assert "Recruiter asked for availability next week" in comms
    followup = (app_dir / "followups.md").read_text(encoding="utf-8")
    assert "Recruiter asked for availability next week" in followup


def test_domain_move_rejects_unconfigured_status(client, monkeypatch):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card("job-1", {"company": "Acme Hoops"}, status="Suggested Jobs")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-1", "status": "Approved"})
    assert resp.status_code == 400
    assert "not a configured column" in resp.json()["detail"]
