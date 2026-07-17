from __future__ import annotations

import importlib.util
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

from command_center.job_search.memory import JobSearchMemory


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"
EXAMPLES = ROOT / "docs" / "job_search" / "examples"


def test_relationships_are_durable_idempotent_and_uuid_isolated(tmp_path):
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    fields = {
        "name": "Alex Smith",
        "company": "Acme",
        "role_title": "Director",
        "notes": "Met at a conference",
    }
    store = JobSearchMemory(tmp_path)
    status, first = store.put_relationship(first_id, **fields)
    assert status == "created"
    created_at = first["created_at"]
    updated_at = first["updated_at"]

    status, unchanged = store.put_relationship(first_id, **fields)
    assert status == "unchanged"
    assert unchanged["created_at"] == created_at
    assert unchanged["updated_at"] == updated_at

    status, second = store.put_relationship(second_id, **fields)
    assert status == "created"
    assert second["relationship_id"] != first["relationship_id"]

    restarted = JobSearchMemory(tmp_path)
    assert {
        row["relationship_id"] for row in restarted.list_relationships()
    } == {first_id, second_id}
    status, archived = restarted.put_relationship(
        first_id, **fields, active=False)
    assert status == "updated"
    assert archived["active"] is False
    assert [row["relationship_id"] for row in restarted.list_relationships(True)] == [
        second_id
    ]
    assert restarted.list_relationships(False)[0]["relationship_id"] == first_id


def test_question_candidates_are_category_scoped_and_restart_durable(tmp_path):
    store = JobSearchMemory(tmp_path)
    status, question, occurrence = store.record_question(
        application_id="app-1",
        card_id="card-1",
        category_id="sports_data_scientist",
        question="Why this team?",
    )
    assert status == "created"
    assert occurrence["category_id"] == "sports_data_scientist"
    question_id = question["question_id"]
    assert store.record_question(
        application_id="app-1",
        card_id="card-1",
        category_id="sports_data_scientist",
        question="  WHY   this TEAM? ",
    )[0] == "unchanged"

    store.put_candidate_answer(
        question_id, "sports_data_scientist", "Sports answer")
    store.put_candidate_answer(
        question_id, "analytics_engineer", "Analytics answer")
    restarted = JobSearchMemory(tmp_path)
    saved = restarted.list_questions()[0]
    assert {
        row["category_id"]: row["answer"]
        for row in saved["candidate_answers"]
    } == {
        "analytics_engineer": "Analytics answer",
        "sports_data_scientist": "Sports answer",
    }
    assert restarted.list_questions("sports_data_scientist")
    assert restarted.list_questions("product_data_scientist") == []


def test_schema_errors_are_loud(tmp_path):
    path = tmp_path / "job_search_memory.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (99, 'now')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="newer"):
        JobSearchMemory(tmp_path)


def test_incomplete_current_schema_is_loud(tmp_path):
    path = tmp_path / "job_search_memory.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (1, 'now')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="incomplete"):
        JobSearchMemory(tmp_path)


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from command_center.job_search.config import load_config

    spec = importlib.util.spec_from_file_location(
        "job_search_memory_api_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["job_search_memory_api_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")
    monkeypatch.setattr(mod, "KANBAN_EVENT_LOG", tmp_path / "events.jsonl")
    monkeypatch.setattr(mod, "BOARD_STORE_DIR", tmp_path / "boards")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    monkeypatch.setattr(
        mod, "_job_search_config_and_root", lambda: (load_config(), tmp_path))
    return mod, TestClient(mod.app), tmp_path


@pytest.fixture
def gated_client(monkeypatch):
    from fastapi.testclient import TestClient

    spec = importlib.util.spec_from_file_location(
        "job_search_memory_gated_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["job_search_memory_gated_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CHAT_ENABLED", False)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", False)
    return mod, TestClient(mod.app)


def _prepared_card(tmp_path: Path, card_id: str = "job-memory") -> str:
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider,
    )
    from command_center.job_search.achievement_bank import ensure_bank
    from command_center.job_search.application_memory import (
        create_prepared_application,
    )
    from command_center.job_search.automation_policy import classify_automation
    from command_center.job_search.config import load_config
    from command_center.job_search.resume_selection import select_resume
    from command_center.job_search.scoring import normalize_job_from_text, score_job
    from command_center.kanban_sync import EventLog

    cfg = load_config()
    bank = ensure_bank(tmp_path / "profile" / "achievement_bank.yml")
    job = normalize_job_from_text(
        (EXAMPLES / "basketball_ai_data_scientist.md").read_text(
            encoding="utf-8"))
    app_dir = create_prepared_application(
        job,
        score_job(job, bank, cfg),
        classify_automation(job, cfg),
        select_resume(job, bank, cfg),
        root=tmp_path,
        executor="codex",
        bank=bank,
    )
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card(
        card_id,
        {
            "company": "Basketball AI Lab",
            "role_title": "Basketball AI Data Scientist",
            "category": "sports_data_scientist",
            "application_id": app_dir.name,
            "materials_path": str(app_dir),
        },
        status="Needs Geoff",
    )
    return app_dir.name


def test_private_endpoints_are_gated(gated_client):
    _, client = gated_client
    relationship_id = str(uuid.uuid4())
    assert client.get("/api/job-search/relationships").status_code == 503
    assert client.get("/api/job-search/question-library").status_code == 503
    assert client.get(
        "/api/job-search/cards/card/outreach").status_code == 503
    assert client.put(
        f"/api/job-search/relationships/{relationship_id}",
        json={"name": "A", "company": "B"},
    ).status_code == 503


def test_writes_require_profile_write_gate(gated_client, monkeypatch):
    mod, client = gated_client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    relationship_id = str(uuid.uuid4())
    response = client.put(
        f"/api/job-search/relationships/{relationship_id}",
        json={"name": "A", "company": "B"},
    )
    assert response.status_code == 503
    assert "profile writes disabled" in response.json()["detail"]
    assert client.post(
        "/api/job-search/question-library",
        json={"card_id": "card", "question": "Why?"},
    ).status_code == 503


def test_private_reads_are_no_store_and_relationship_put_is_strict(api_client):
    _, client, _ = api_client
    relationship_id = str(uuid.uuid4())
    created = client.put(
        f"/api/job-search/relationships/{relationship_id}",
        json={"name": "Ada", "company": "Acme"},
    )
    assert created.status_code == 200, created.json()
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["relationship"]["provenance"] == (
        "operator_private_console")
    rejected = client.put(
        f"/api/job-search/relationships/{uuid.uuid4()}",
        json={"name": "Grace", "company": "Acme", "unknown": True},
    )
    assert rejected.status_code == 422
    assert rejected.headers["cache-control"] == "no-store"

    private_value = "PRIVATE-SECRET-" + ("x" * 5_001)
    validation = client.post(
        "/api/job-search/question-library",
        json={"card_id": "card", "question": private_value},
    )
    assert validation.status_code == 422
    assert validation.headers["cache-control"] == "no-store"
    assert private_value not in validation.text
    for path in (
        "/api/job-search/relationships",
        "/api/job-search/question-library",
        "/api/job-search/profile-controls",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"


def test_sensitive_capture_and_answer_are_rejected_without_leakage(api_client):
    _, client, tmp_path = api_client
    _prepared_card(tmp_path)
    sensitive_question = "Do you have a disability?"
    rejected = client.post(
        "/api/job-search/question-library",
        json={"card_id": "job-memory", "question": sensitive_question},
    )
    assert rejected.status_code == 400
    assert sensitive_question not in rejected.text
    assert rejected.headers["cache-control"] == "no-store"
    assert client.get(
        "/api/job-search/question-library").json()["questions"] == []
    assert sensitive_question.encode() not in (
        tmp_path / "job_search_memory.sqlite").read_bytes()

    captured = client.post(
        "/api/job-search/question-library",
        json={"card_id": "job-memory", "question": "Why this company?"},
    )
    assert captured.status_code == 200, captured.json()
    question_id = captured.json()["question"]["question_id"]
    sensitive_answer = "I have a disability."
    answer = client.put(
        f"/api/job-search/question-library/{question_id}"
        "/candidate/sports_data_scientist",
        json={"answer": sensitive_answer},
    )
    assert answer.status_code == 400
    assert sensitive_answer not in answer.text
    library = client.get("/api/job-search/question-library").json()
    assert library["questions"][0]["candidate_answers"] == []
    assert sensitive_answer.encode() not in (
        tmp_path / "job_search_memory.sqlite").read_bytes()

    for protected in (
        "My SSN is 123-45-6789.",
        "The password is hunter2.",
        "My MFA code is 123456.",
        "123-45-6789",
        "4111 1111 1111 1111",
        "sk-proj-abcdefghijklmnopqrstuvwx",
    ):
        blocked = client.put(
            f"/api/job-search/question-library/{question_id}"
            "/candidate/sports_data_scientist",
            json={"answer": protected},
        )
        assert blocked.status_code == 400
        assert blocked.headers["cache-control"] == "no-store"
        assert protected not in blocked.text
    assert client.get(
        "/api/job-search/question-library").json()["questions"][0][
            "candidate_answers"] == []


def test_standing_answer_is_private_bounded_and_rejects_bare_secrets(api_client):
    _, client, tmp_path = api_client
    too_long = "PRIVATE-STANDING-" + ("x" * 5_001)
    invalid = client.put(
        "/api/job-search/profile-controls/standing-answer",
        json={"topic": "salary", "answer": too_long, "unexpected": True},
    )
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"
    assert too_long not in invalid.text

    bare_secret = "4111 1111 1111 1111"
    rejected = client.put(
        "/api/job-search/profile-controls/standing-answer",
        json={"topic": "salary", "question": "What is your target?",
              "answer": bare_secret},
    )
    assert rejected.status_code == 400
    assert rejected.headers["cache-control"] == "no-store"
    assert bare_secret not in rejected.text
    assert not (tmp_path / "profile" / "standing_answers.yml").exists()


def test_candidate_answers_do_not_change_automation_or_rendering(
    api_client, monkeypatch,
):
    _, client, tmp_path = api_client
    _prepared_card(tmp_path)
    from command_center.job_search import automation_policy
    from command_center.job_search.config import load_config
    from command_center.job_search.scoring import normalize_job_from_text
    from command_center.job_search.standing_answers import (
        render_application_answers,
    )

    cfg = load_config()
    job = normalize_job_from_text(
        (EXAMPLES / "basketball_ai_data_scientist.md").read_text(
            encoding="utf-8"))
    monkeypatch.setattr(
        automation_policy, "load_standing_answers", lambda _root: [])
    classification_before = automation_policy.classify_automation(job, cfg)
    rendered_before = render_application_answers([], salary_max=None)

    captured = client.post(
        "/api/job-search/question-library",
        json={"card_id": "job-memory", "question": "Why this role?"},
    ).json()
    question_id = captured["question"]["question_id"]
    saved = client.put(
        f"/api/job-search/question-library/{question_id}"
        "/candidate/sports_data_scientist",
        json={"answer": "It matches my approved experience."},
    )
    assert saved.status_code == 200, saved.json()
    assert not (tmp_path / "profile" / "standing_answers.yml").exists()
    assert automation_policy.classify_automation(job, cfg) == classification_before
    assert render_application_answers([], salary_max=None) == rendered_before


def test_outreach_is_exact_deterministic_draft_only_and_offline(
    api_client, monkeypatch,
):
    mod, client, tmp_path = api_client
    _prepared_card(tmp_path)
    exact_id = str(uuid.uuid4())
    near_id = str(uuid.uuid4())
    for relationship_id, company, name, notes in (
        (exact_id, "  BASKETBALL   AI LAB ", "Ada Exact", "PRIVATE CONTEXT"),
        (near_id, "Basketball AI Labs", "Nora Near", "OTHER PRIVATE"),
    ):
        response = client.put(
            f"/api/job-search/relationships/{relationship_id}",
            json={
                "name": name,
                "company": company,
                "notes": notes,
            },
        )
        assert response.status_code == 200, response.json()

    monkeypatch.setattr(
        mod.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("outreach must not use a network lookup")),
    )
    response = client.get("/api/job-search/cards/job-memory/outreach")
    assert response.status_code == 200, response.json()
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["draft_only"] is True
    assert [row["name"] for row in body["known_contacts"]] == ["Ada Exact"]
    assert set(body["known_contacts"][0]) == {
        "relationship_id", "name", "company", "role_title",
        "relationship_kind", "linkedin_url", "active",
    }
    assert "PRIVATE CONTEXT" not in response.text
    drafts = "\n".join(row["body"] for row in body["drafts"])
    assert "Ada Exact" in drafts
    assert "Nora Near" not in drafts
    assert "PRIVATE CONTEXT" not in drafts
    assert "OTHER PRIVATE" not in drafts
    assert all("Ada Exact" not in phrase for phrase in body[
        "recommended_role_searches"])

    outreach_routes = [
        route for route in mod.app.routes
        if getattr(route, "path", "").endswith("/outreach")
    ]
    assert len(outreach_routes) == 1
    assert outreach_routes[0].methods == {"GET"}
    assert not any(
        "send" in getattr(route, "path", "").casefold()
        for route in mod.app.routes
        if "/api/job-search/" in getattr(route, "path", "")
    )

    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider,
    )
    from command_center.kanban_sync import EventLog

    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card(
        "job-suggested",
        {"company": "Basketball AI Lab", "role_title": "Analyst"},
        status="Suggested Jobs",
    )
    suggested = client.get(
        "/api/job-search/cards/job-suggested/outreach")
    assert suggested.status_code == 200, suggested.json()
    assert suggested.json()["application_id"] is None
    assert suggested.json()["known_contacts"][0]["name"] == "Ada Exact"


def test_note_success_survives_separate_question_failure(api_client):
    _, client, tmp_path = api_client
    application_id = _prepared_card(tmp_path)
    note_text = "Portal asks: Do you have a disability?"
    noted = client.post(
        "/api/domain/job_application/card/job-memory/note",
        json={"type": "portal_question", "text": note_text},
    )
    assert noted.status_code == 200, noted.json()

    rejected = client.post(
        "/api/job-search/question-library",
        json={
            "card_id": "job-memory",
            "question": "Do you have a disability?",
        },
    )
    assert rejected.status_code == 400
    notes = (
        tmp_path / "applications_active" / application_id / "communications.jsonl"
    ).read_text(encoding="utf-8")
    assert note_text in notes
    assert client.get(
        "/api/job-search/question-library").json()["questions"] == []
