"""The packet review loop: validation gate, request-changes → regenerate with
notes, finalize (validate → mark submitted → email record → evidence)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from command_center.job_search import application_memory
from command_center.job_search.achievement_bank import ensure_bank
from command_center.job_search.agent_writer import AgentWriterError, GeneratedMaterials
from command_center.job_search.application_memory import (
    create_prepared_application,
    load_application,
    regenerate_materials,
    request_changes,
)
from command_center.job_search.automation_policy import classify_automation
from command_center.job_search.config import ensure_data_dirs, load_config
from command_center.job_search.finalize import FinalizeBlocked, finalize_application
from command_center.job_search.packet_validation import validate_packet
from command_center.job_search.record_email import (
    build_email_html,
    email_config_status,
    send_application_record,
)
from command_center.job_search.resume_selection import select_resume
from command_center.job_search.scoring import normalize_job_from_text, score_job

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "job_search" / "examples"


def _prepare(tmp_path: Path) -> tuple[Path, str]:
    ensure_data_dirs(tmp_path)
    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text(
        (EXAMPLES / "basketball_ai_data_scientist.md").read_text(encoding="utf-8"))
    app_dir = create_prepared_application(
        job,
        score_job(job, bank, cfg),
        classify_automation(job, cfg),
        select_resume(job, bank, cfg),
        root=tmp_path,
        bank=bank,
    )
    return app_dir, app_dir.name


def _fake_generated(claims: list[str]) -> GeneratedMaterials:
    return GeneratedMaterials(
        resume="# Geoffrey Hadfield\nregenerated resume\n## Claim Traceability\n- `x`",
        cover_letter="regenerated cover letter",
        recruiter_message="regenerated recruiter message",
        claim_ids=claims,
        model="chat",
        attempts=1,
    )


def test_template_fallback_is_recorded_honestly(tmp_path):
    app_dir, app_id = _prepare(tmp_path)
    _, record = load_application(app_id, root=tmp_path)
    # suite conftest pins JOB_SEARCH_AGENT_WRITER=0 — the mode says so verbatim
    assert record.generation["mode"] == "template_fallback"
    assert "disabled" in str(record.generation["error"])
    assert record.revision == 1
    assert record.review_state == "ready_for_review"


def test_validation_passes_for_fresh_packet_with_agent_warning(tmp_path):
    app_dir, app_id = _prepare(tmp_path)
    _, record = load_application(app_id, root=tmp_path)
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    result = validate_packet(app_dir, record, bank)
    assert result["ok"] is True                      # warnings never block
    assert "agent_generated" in result["warnings"]   # but the mode is visible
    assert "agent_trace" in result["warnings"]
    by_id = {c["id"]: c for c in result["checks"]}
    assert by_id["materials_present"]["ok"] is True
    assert by_id["claims_valid"]["ok"] is True


def test_validation_blocks_on_missing_file_and_unresolved_notes(tmp_path):
    app_dir, app_id = _prepare(tmp_path)
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    (app_dir / "cover_letter.md").unlink()
    request_changes(app_id, "cover letter is too generic", root=tmp_path)
    _, record = load_application(app_id, root=tmp_path)
    result = validate_packet(app_dir, record, bank)
    assert result["ok"] is False
    assert "materials_present" in result["errors"]
    assert "review_clean" in result["errors"]


def test_request_changes_requires_text_and_records_note(tmp_path):
    app_dir, app_id = _prepare(tmp_path)
    with pytest.raises(ValueError, match="non-empty note"):
        request_changes(app_id, "   ", root=tmp_path)
    _, record = request_changes(app_id, "tighten the summary", root=tmp_path)
    assert record.review_state == "changes_requested"
    notes = (app_dir / "review_notes.md").read_text(encoding="utf-8")
    assert "tighten the summary" in notes
    comms = (app_dir / "communications.jsonl").read_text(encoding="utf-8")
    assert "review_changes_requested" in comms


def test_regenerate_applies_notes_and_bumps_revision(tmp_path, monkeypatch):
    app_dir, app_id = _prepare(tmp_path)
    request_changes(app_id, "lead with the NBA platform work", root=tmp_path)
    seen_inputs = {}

    def fake_generate(inputs, bank, *, trace_path, trace_step, **kwargs):
        seen_inputs["inputs"] = inputs
        seen_inputs["trace_step"] = trace_step
        return _fake_generated(["nba_player_value_platform"])
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "1")
    monkeypatch.setattr(application_memory, "generate_materials", fake_generate)
    _, record = regenerate_materials(app_id, root=tmp_path)
    assert record.revision == 2
    assert record.review_state == "ready_for_review"
    assert record.generation["mode"] == "agent"
    assert record.generation["claim_ids"] == ["nba_player_value_platform"]
    assert seen_inputs["inputs"].reviewer_notes  # the notes reached the writer
    assert "lead with the NBA platform work" in seen_inputs["inputs"].reviewer_notes[0]
    assert seen_inputs["trace_step"] == "regenerate_materials_rev2"
    assert "regenerated resume" in (app_dir / "generated_resume.md").read_text(encoding="utf-8")


def test_regenerate_failure_keeps_changes_requested(tmp_path, monkeypatch):
    app_dir, app_id = _prepare(tmp_path)
    request_changes(app_id, "fix it", root=tmp_path)

    def fail_generate(*args, **kwargs):
        raise AgentWriterError("model down")
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "1")
    monkeypatch.setattr(application_memory, "generate_materials", fail_generate)
    with pytest.raises(AgentWriterError, match="model down"):
        regenerate_materials(app_id, root=tmp_path)
    _, record = load_application(app_id, root=tmp_path)
    assert record.review_state == "changes_requested"   # the note was NOT lost
    assert record.revision == 1


def test_email_status_reports_missing_vars(tmp_path):
    status = email_config_status(env={})
    assert status["configured"] is False
    assert "DISCOVERY_SMTP_HOST" in status["missing"]
    assert any("JOB_SEARCH_EMAIL_TO" in m for m in status["missing"])


def test_email_record_written_even_without_smtp(tmp_path):
    app_dir, app_id = _prepare(tmp_path)
    _, record = load_application(app_id, root=tmp_path)
    result = send_application_record(app_dir, record, env={})
    assert result["status"] == "recorded_only"
    assert Path(result["record_path"]).is_file()
    html = build_email_html(app_dir, record)
    assert record.company in html
    assert "Job Description" in html
    assert "Resume" in html


def test_email_sends_with_attachments_when_configured(tmp_path):
    app_dir, app_id = _prepare(tmp_path)
    _, record = load_application(app_id, root=tmp_path)
    sent = {}

    def fake_send(cfg, msg):
        sent["cfg"] = cfg
        sent["msg"] = msg
    env = {
        "DISCOVERY_SMTP_HOST": "smtp.test", "DISCOVERY_SMTP_USER": "u",
        "DISCOVERY_SMTP_PASSWORD": "p", "DISCOVERY_SMTP_FROM": "from@test",
        "JOB_SEARCH_EMAIL_TO": "geoff@test",
    }
    result = send_application_record(app_dir, record, env=env, sender_fn=fake_send)
    assert result["status"] == "sent"
    msg = sent["msg"]
    assert msg["To"] == "geoff@test"
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert "generated_resume.md" in names
    assert "cover_letter.md" in names
    assert "answer_bank.md" in names


def test_finalize_blocks_then_succeeds_with_evidence(tmp_path, monkeypatch):
    app_dir, app_id = _prepare(tmp_path)
    request_changes(app_id, "not ready yet", root=tmp_path)
    with pytest.raises(FinalizeBlocked) as exc:
        finalize_application(app_id, root=tmp_path)
    assert "review_clean" in exc.value.validation["errors"]

    def fake_generate(inputs, bank, *, trace_path, trace_step, **kwargs):
        return _fake_generated(["wms_founder_platform"])
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "1")
    monkeypatch.setattr(application_memory, "generate_materials", fake_generate)
    regenerate_materials(app_id, root=tmp_path)
    result = finalize_application(app_id, root=tmp_path, env={})
    assert result["record"]["status"] == "applied"
    assert result["record"]["stage"] == "completed"
    assert result["email"]["status"] == "recorded_only"
    evidence = json.loads(
        (app_dir / "submission_record.json").read_text(encoding="utf-8"))
    assert evidence["validation"]["ok"] is True
    assert evidence["email"]["status"] == "recorded_only"
    assert evidence["application_id"] == app_id
    # double-submit is blocked by validation
    with pytest.raises(FinalizeBlocked) as exc2:
        finalize_application(app_id, root=tmp_path, env={})
    assert "not_already_submitted" in exc2.value.validation["errors"]
