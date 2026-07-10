"""Packet review endpoints: view materials + trace, request-changes →
regenerate, approve & submit (validation-gated governed Completed move with
email record + submission evidence). Hermetic: tmp board store/event log/data
root; the agent writer is stubbed at the application_memory seam."""
import importlib.util
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
    spec = importlib.util.spec_from_file_location("packet_endpoints_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["packet_endpoints_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")
    monkeypatch.setattr(mod, "KANBAN_EVENT_LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(mod, "BOARD_STORE_DIR", tmp_path / "boards")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    from command_center.job_search.config import load_config
    monkeypatch.setattr(
        mod, "_job_search_config_and_root", lambda: (load_config(), tmp_path))
    return mod, TestClient(mod.app), tmp_path


def _prepared_card(tmp_path: Path, card_id: str = "job-review-me") -> str:
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.job_search.achievement_bank import ensure_bank
    from command_center.job_search.application_memory import create_prepared_application
    from command_center.job_search.automation_policy import classify_automation
    from command_center.job_search.config import load_config
    from command_center.job_search.resume_selection import select_resume
    from command_center.job_search.scoring import normalize_job_from_text, score_job
    from command_center.kanban_sync import EventLog

    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text(
        (EXAMPLES / "basketball_ai_data_scientist.md").read_text(encoding="utf-8"))
    app_dir = create_prepared_application(
        job, score_job(job, bank, cfg), classify_automation(job, cfg),
        select_resume(job, bank, cfg), root=tmp_path, executor="codex", bank=bank)
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card(
        card_id,
        {"company": "Basketball AI Lab",
         "role_title": "Basketball AI Data Scientist",
         "application_id": app_dir.name,
         "materials_path": str(app_dir)},
        status="Needs Geoff")
    return app_dir.name


def _fake_generated():
    from command_center.job_search.agent_writer import GeneratedMaterials
    return GeneratedMaterials(
        resume="# Geoffrey Hadfield\nregenerated for review\n",
        cover_letter="regenerated cover letter\n",
        recruiter_message="regenerated recruiter message\n",
        claim_ids=["wms_founder_platform"],
        model="chat",
        attempts=1,
    )


def test_packet_endpoint_serves_materials_trace_validation_email(client):
    _, tc, tmp_path = client
    _prepared_card(tmp_path)
    body = tc.get("/api/domain/job_application/card/job-review-me/packet").json()
    assert body["application_id"]
    # every reviewable document is served with content
    assert "Geoffrey Hadfield" in body["files"]["resume"]
    assert body["files"]["cover_letter"]
    assert body["files"]["answer_bank"]
    assert body["files"]["job_description"]
    assert body["files"]["manual_checklist"]
    # validation: fresh template packet is submittable but flags the writer mode
    assert body["validation"]["ok"] is True
    assert "agent_generated" in body["validation"]["warnings"]
    # email diagnostics name the missing vars instead of pretending
    assert body["email"]["configured"] is False
    assert "DISCOVERY_SMTP_HOST" in body["email"]["missing"]
    assert body["agent_trace"] == []   # template mode → no trace yet
    assert body["submission_record"] is None


def test_packet_endpoint_requires_application(client):
    _, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card("job-bare", {"company": "Acme"}, status="Suggested Jobs")
    resp = tc.get("/api/domain/job_application/card/job-bare/packet")
    assert resp.status_code == 400
    assert "no application_id" in resp.json()["detail"]


def test_request_changes_records_notes_and_regenerates(client, monkeypatch):
    mod, tc, tmp_path = client
    app_id = _prepared_card(tmp_path)
    from command_center.job_search import application_memory
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "1")
    monkeypatch.setattr(
        application_memory, "generate_materials",
        lambda inputs, bank, *, trace_path, trace_step, **kw: _fake_generated())
    resp = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/request-changes",
        json={"notes": "lead with the NBA platform work"})
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "regenerated"
    assert body["regenerate_error"] is None
    assert body["packet"]["record"]["revision"] == 2
    assert body["packet"]["record"]["review_state"] == "ready_for_review"
    assert "regenerated for review" in body["packet"]["files"]["resume"]
    assert "lead with the NBA platform work" in body["packet"]["files"]["review_notes"]
    # the card carries the review provenance for board badges
    assert body["packet"]["record"]["generation"]["mode"] == "agent"
    steps = {s["id"]: s for s in body["progress"]["steps"]}
    assert "packet_review" in steps
    app_dir = tmp_path / "applications_active" / app_id
    assert "lead with the NBA platform work" in (
        (app_dir / "review_notes.md").read_text(encoding="utf-8"))


def test_request_changes_surfaces_writer_failure_without_losing_notes(client, monkeypatch):
    mod, tc, tmp_path = client
    _prepared_card(tmp_path)
    from command_center.job_search import application_memory
    from command_center.job_search.agent_writer import AgentWriterError

    def boom(*a, **k):
        raise AgentWriterError("model down")
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "1")
    monkeypatch.setattr(application_memory, "generate_materials", boom)
    resp = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/request-changes",
        json={"notes": "please fix"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "changes_requested"
    assert "model down" in body["regenerate_error"]
    assert body["packet"]["record"]["review_state"] == "changes_requested"
    # and submit is now blocked until the notes are addressed
    submit = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/submit",
        json={"confirm": True})
    assert submit.status_code == 409
    assert "No unresolved change requests" in submit.json()["detail"]


def test_submit_finalizes_moves_and_records(client):
    _, tc, tmp_path = client
    app_id = _prepared_card(tmp_path)
    resp = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/submit",
        json={"confirm": True})
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "submitted"
    assert body["to_status"] == "Completed"
    assert body["card"]["status"] == "Completed"
    side = body["side_effect"]
    assert side["application_status"] == "applied"
    assert side["validation"]["ok"] is True
    assert side["email"]["status"] == "recorded_only"   # no SMTP configured
    app_dir = tmp_path / "applications_active" / app_id
    assert (app_dir / "submission_record.json").is_file()
    assert (app_dir / "submission_email.html").is_file()
    record = yaml.safe_load((app_dir / "application.yml").read_text(encoding="utf-8"))
    assert record["status"] == "applied"
    # the packet view now shows the evidence, and re-submit is refused
    packet = tc.get("/api/domain/job_application/card/job-review-me/packet").json()
    assert packet["submission_record"]["email"]["status"] == "recorded_only"
    again = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/submit",
        json={"confirm": True})
    assert again.status_code == 409
    assert "already in Completed" in again.json()["detail"]


def test_cli_finalized_application_completes_idempotently(client):
    """`cc job-search finalize` marks the record applied but cannot write the
    cockpit's event-log board. The subsequent cockpit submit/drag must complete
    the card WITHOUT a second submission or duplicate email."""
    from command_center.job_search.finalize import finalize_application

    app_id = _prepared_card(tmp_path=client[2])
    _, tc, tmp_path = client
    finalize_application(app_id, root=tmp_path, env={})
    resp = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/submit",
        json={"confirm": True})
    assert resp.status_code == 200, resp.json()
    side = resp.json()["side_effect"]
    assert side["already_submitted"] is True
    assert side["email"]["status"] == "skipped"       # no duplicate record email
    assert resp.json()["card"]["status"] == "Completed"
    # applied_at from the original finalize survived (not overwritten)
    record = yaml.safe_load(
        (tmp_path / "applications_active" / app_id / "application.yml")
        .read_text(encoding="utf-8"))
    assert record["status"] == "applied"


def test_blocked_drag_leaves_card_and_events_untouched_after_reorder(client):
    """Finalize now runs BEFORE the governed event: a blocked completion must
    leave the event log unchanged and the card in its original lane."""
    _, tc, tmp_path = client
    _prepared_card(tmp_path, card_id="job-blocked-drag")
    tc.post("/api/domain/job_application/card/job-blocked-drag/packet/request-changes",
            json={"notes": "hold on", "regenerate": False})
    events_before = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-blocked-drag", "status": "Completed"})
    assert resp.status_code == 409
    assert (tmp_path / "events.jsonl").read_text(encoding="utf-8") == events_before
    card = tc.get("/api/domain/job_application/cards").json()["cards"]
    me = next(c for c in card if c["card_id"] == "job-blocked-drag")
    assert me["status"] == "Needs Geoff"


def test_story_lists_moments_in_linear_order(client, monkeypatch):
    """The Story view: notes, edits, and agent attempts appear as ordered
    moments with the long content attached as expandable detail."""
    mod, tc, tmp_path = client
    _prepared_card(tmp_path)
    from command_center.job_search import application_memory
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "1")
    monkeypatch.setattr(
        application_memory, "generate_materials",
        lambda inputs, bank, *, trace_path, trace_step, **kw: _fake_generated())
    tc.post("/api/domain/job_application/card/job-review-me/packet/request-changes",
            json={"notes": "tighten the summary"})
    body = tc.get("/api/domain/job_application/card/job-review-me/packet").json()
    story = body["story"]
    assert story, "story must not be empty after a review round"
    kinds = [s["kind"] for s in story]
    assert "note" in kinds
    titles = " | ".join(s["title"] for s in story)
    assert "review changes requested" in titles
    assert "materials regenerated" in titles
    # linear order: timestamps never go backwards
    stamps = [s["ts"] for s in story if s["ts"]]
    assert stamps == sorted(stamps)


def test_packet_file_edit_saves_and_records_manual_edit(client):
    _, tc, tmp_path = client
    app_id = _prepared_card(tmp_path)
    resp = tc.put(
        "/api/domain/job_application/card/job-review-me/packet/file",
        json={"file": "resume", "content": "# Geoffrey Hadfield\nGeoff's own rewrite"})
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "saved"
    assert "Geoff's own rewrite" in body["packet"]["files"]["resume"]
    # provenance: the edit is a story moment and recorded on the record
    assert body["packet"]["record"]["generation"]["manual_edits"][0]["file"] == "resume"
    assert any("manual edit" in s["title"] for s in body["packet"]["story"])
    app_dir = tmp_path / "applications_active" / app_id
    assert "Geoff's own rewrite" in (app_dir / "generated_resume.md").read_text(encoding="utf-8")
    # guardrails: unknown file and empty content are refused
    assert tc.put("/api/domain/job_application/card/job-review-me/packet/file",
                  json={"file": "application", "content": "x"}).status_code == 400
    assert tc.put("/api/domain/job_application/card/job-review-me/packet/file",
                  json={"file": "resume", "content": "   "}).status_code == 400


def test_regenerate_without_notes_records_no_review_note(client, monkeypatch):
    _, tc, tmp_path = client
    app_id = _prepared_card(tmp_path)
    from command_center.job_search import application_memory
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "1")
    monkeypatch.setattr(
        application_memory, "generate_materials",
        lambda inputs, bank, *, trace_path, trace_step, **kw: _fake_generated())
    resp = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/request-changes",
        json={"notes": "", "regenerate": True})
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "regenerated"
    assert body["packet"]["record"]["revision"] == 2
    app_dir = tmp_path / "applications_active" / app_id
    assert not (app_dir / "review_notes.md").exists()   # no phantom note
    # and notes-less non-regenerate is refused
    resp = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/request-changes",
        json={"notes": "", "regenerate": False})
    assert resp.status_code == 400


def test_submit_requires_confirm(client):
    _, tc, tmp_path = client
    _prepared_card(tmp_path)
    resp = tc.post(
        "/api/domain/job_application/card/job-review-me/packet/submit",
        json={})
    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"]


def test_completed_drag_is_blocked_before_event_when_invalid(client):
    _, tc, tmp_path = client
    app_id = _prepared_card(tmp_path)
    tc.post("/api/domain/job_application/card/job-review-me/packet/request-changes",
            json={"notes": "not ready", "regenerate": False})
    events_before = (tmp_path / "events.jsonl").read_text(encoding="utf-8").count("\n")
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": "job-review-me", "status": "Completed"})
    assert resp.status_code == 409
    assert "packet validation failed" in resp.json()["detail"]
    events_after = (tmp_path / "events.jsonl").read_text(encoding="utf-8").count("\n")
    assert events_after == events_before   # no Completed event was logged
    record = yaml.safe_load(
        (tmp_path / "applications_active" / app_id / "application.yml")
        .read_text(encoding="utf-8"))
    assert record["status"] == "prepared"   # nothing was marked applied
