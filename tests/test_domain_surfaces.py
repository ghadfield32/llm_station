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


def test_domain_registry_lists_all_domains(client):
    _, tc, _ = client
    response = tc.get("/api/domains")
    assert response.status_code == 200, response.json()
    body = response.json()
    ids = {d["domain_id"] for d in body["domains"]}
    assert ids == {
        "betts_basketball_grand_todo", "grand_todo", "job_application",
        "linkedin_post",
        "book", "paper", "repo", "dag", "self_improvement", "mission",
        "generic_task", "home_house", "movies_shows", "site_basketball",
        "station_improvements", "kanban_improvements", "business",
        "tech_hardware_setup",
        "life_center_overview", "life_center_services",
        "life_center_operations",
    }
    # every domain ships a designed empty state, not a blank screen
    assert all(d["empty_state"]["title"] for d in body["domains"])
    # Intake is part of the reusable domain contract, including future boards.
    assert all(d["intake"]["producer"] for d in body["domains"])
    assert all(d["intake"]["summary"] for d in body["domains"])


def test_todos_is_a_real_durable_routing_domain(client):
    """The visible General Todos board must be a compatible Work Graph destination,
    not a fixture label that leaves Prepare-now with zero choices."""
    mod, tc, _ = client
    domains = tc.get("/api/domains").json()["domains"]
    todos = next(d for d in domains if d["domain_id"] == "generic_task")
    assert todos["title"] == "General Todos"
    assert todos["source"] == "board_store"
    assert todos["board_id"] == "personal_todos"
    cards = tc.get("/api/domain/generic_task/cards").json()
    assert cards["origin"] == "board_store"
    assert cards["board_id"] == "personal_todos"
    assert any(
        board["board_id"] == "personal_todos"
        for board in mod._routable_work_boards()
    )


def test_upkeep_status_is_explicit_before_and_after_first_cycle(client, monkeypatch):
    mod, tc, tmp_path = client
    status = tmp_path / "watcher-status.json"
    monkeypatch.setattr(mod, "WATCHER_STATUS_FILE", status)
    pending = tc.get("/api/upkeep/status")
    assert pending.status_code == 503
    assert "has not completed" in pending.json()["detail"]

    value = {
        "schema_version": "growthos.watcher-status.v1",
        "tasks": {"curate": {"status": "failed", "error": "rate limited"}},
    }
    status.write_text(json.dumps(value), encoding="utf-8")
    assert tc.get("/api/upkeep/status").json() == value


def test_grand_todo_card_reads_never_reconcile_or_write(client, monkeypatch):
    mod, tc, tmp_path = client
    source = tmp_path / "GRAND_TODO_LIST.md"
    source.write_text("# Canonical tracker\n\nRead-only probe.\n", encoding="utf-8")
    monkeypatch.setattr(mod, "GRAND_TODO_SOURCE", source)

    response = tc.get("/api/domain/betts_basketball_grand_todo/cards")

    assert response.status_code == 200, response.json()
    assert response.json()["cards"] == []
    assert response.json()["source_sync"]["state"] == "not_imported"
    assert response.json()["source_sync"]["write_on_read"] is False
    assert not (tmp_path / "boards").exists()
    assert not (tmp_path / "events.jsonl").exists()
    sync = tc.post("/api/domain/betts_basketball_grand_todo/sync")
    assert sync.status_code == 503
    assert not (tmp_path / "boards").exists()
    assert not (tmp_path / "events.jsonl").exists()


def test_no_domain_offers_wall_verbs(client):
    _, tc, _ = client
    wall = {"approve_card", "merge", "deploy", "delete_card", "delete_board"}
    for d in tc.get("/api/domains").json()["domains"]:
        assert not wall & set(d.get("allowed_actions", [])), d["domain_id"]


def test_post_domain_is_a_real_internal_board(client):
    _, tc, _ = client
    body = tc.get("/api/domain/linkedin_post/cards").json()
    assert body["origin"] == "board_store"
    assert body["board_id"] == "linkedin_content_pipeline_internal"
    assert body["cards"] == []
    assert body["columns"] == [
        "Draft", "In Queue", "Scheduled", "Published", "Needs Geoff"]


def test_post_composer_creates_a_governed_draft(client, monkeypatch):
    mod, tc, _ = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    options = tc.get("/api/domain/linkedin_post/composer").json()
    account_ids = {row["id"] for row in options["accounts"]}
    assert account_ids == {
        "geoffhadfield32_content", "world_model_sports_content"}
    assert options["max_characters"] == 3000

    text = "A strong first line.\n\nHere is the evidence.\n\nWhat would you test?"
    resp = tc.post(
        "/api/domain/linkedin_post/drafts",
        json={
            "account": "geoffhadfield32_content",
            "body": text,
            "tags": ["#AI", "#Evaluation"],
            "source_ref": "cockpit/manual",
        },
    )

    assert resp.status_code == 201, resp.json()
    created = resp.json()
    assert created["card"]["status"] == "Draft"
    assert created["card"]["hook"] == "A strong first line."
    assert created["card"]["account"] == "geoffhadfield32_content"
    assert created["card"]["char_count"] == len(text)
    assert created["event"]["actor_type"] == "human"
    cards = tc.get("/api/domain/linkedin_post/cards").json()["cards"]
    assert [row["card_id"] for row in cards] == [created["card_id"]]


def test_board_lock_contention_is_http_423_and_writes_nothing(client, monkeypatch):
    mod, tc, tmp_path = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    lock = (
        tmp_path / "boards" / ".locks"
        / "linkedin_content_pipeline_internal.write.lock"
    )
    lock.parent.mkdir(parents=True)
    lock.write_text(
        json.dumps({"token": "live-writer", "pid": 123, "hostname": "other-runtime"}),
        encoding="utf-8",
    )

    response = tc.post(
        "/api/domain/linkedin_post/drafts",
        json={"account": "geoffhadfield32_content", "body": "Do not persist me"},
    )

    assert response.status_code == 423
    assert response.headers["retry-after"] == "2"
    assert "No card was changed" in response.json()["detail"]
    assert not (tmp_path / "boards" / "linkedin_content_pipeline_internal").exists()
    assert not (tmp_path / "events.jsonl").exists()
    assert str(tmp_path) not in response.text


def test_post_composer_rejects_unknown_account_and_over_limit_body(client, monkeypatch):
    mod, tc, _ = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    bad_account = tc.post(
        "/api/domain/linkedin_post/drafts",
        json={"account": "invented", "body": "Real body"},
    )
    assert bad_account.status_code == 400
    assert "configured content account" in bad_account.json()["detail"]

    too_long = tc.post(
        "/api/domain/linkedin_post/drafts",
        json={
            "account": "geoffhadfield32_content",
            "body": "x" * 3001,
        },
    )
    assert too_long.status_code == 422


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


def test_domain_list_omits_bulk_audit_history_without_deleting_store(client):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog
    provider = CommandCenterBoardProvider(
        board_id="research_papers",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    history = [{"source_sha256": "a" * 64, "cells": {"Abstract": "large"}}]
    provider.upsert_card(
        "paper-audit",
        {
            "title": "Audit paper",
            "appflowy_revisions": history,
            "appflowy_source_cells": {"Abstract": "large"},
            "appflowy_revision_count": 1,
        },
        status="Inbox",
    )

    card = tc.get("/api/domain/paper/cards").json()["cards"][0]
    stored = provider.list_cards()[0]
    assert "appflowy_revisions" not in card
    assert "appflowy_source_cells" not in card
    assert card["appflowy_revision_count"] == 1
    assert stored["appflowy_revisions"] == history


@pytest.mark.parametrize(
    ("domain_id", "board_id", "source_key", "expected"),
    [
        ("paper", "research_papers", "Title", "Recovered paper title"),
        ("repo", "research_repos", "Name", "Recovered repository title"),
    ],
)
def test_research_titles_recover_from_retained_source_before_redaction(
    client, domain_id, board_id, source_key, expected,
):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog

    provider = CommandCenterBoardProvider(
        board_id=board_id,
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card(
        f"{domain_id}-legacy",
        {
            "appflowy_source_cells": {
                source_key: expected,
                "Notes": "Source code: https://github.com/example/source-backed",
            },
            "suggested": "Could reduce our evaluation setup time.",
        },
        status="Inbox",
    )

    response = tc.get(f"/api/domain/{domain_id}/cards")
    assert response.status_code == 200, response.json()
    card = response.json()["cards"][0]
    assert card["title"] == expected
    assert card["title_integrity"] == "recovered_from_source"
    assert card["useful_for_us"] == "Could reduce our evaluation setup time."
    assert card["analysis_status"] == "not_analyzed"
    assert card["code_links"] == [
        "https://github.com/example/source-backed"]
    assert card["related_links"] == [
        "https://github.com/example/source-backed"]
    assert "appflowy_source_cells" not in card
    # Display recovery does not silently rewrite the historical store.
    assert "title" not in provider.list_cards()[0]

    prompt = tc.get(
        f"/api/domain/{domain_id}/card/{domain_id}-legacy/progress").json()[
            "chat_prompt"]
    assert expected in prompt
    assert "BOARD INTAKE" in prompt
    assert "FULL RESEARCH CARD PROVENANCE" in prompt
    assert "local-model analysis" in prompt


@pytest.mark.parametrize(
    ("domain_id", "board_id"),
    [("paper", "research_papers"), ("repo", "research_repos")],
)
def test_empty_research_imports_are_retained_but_quarantined_from_boards(
    client, domain_id, board_id,
):
    _mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog

    provider = CommandCenterBoardProvider(
        board_id=board_id,
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card(
        f"{domain_id}-empty-import",
        {
            "appflowy_importer": "legacy",
            "appflowy_source_cells": {
                "Name": "", "URL": "", "Done": False, "Status": None,
                "Updated": {"start": None, "timezone": "Etc/UTC"},
            },
        },
    )
    provider.upsert_card(
        f"{domain_id}-url-only",
        {"url": "https://example.test/source-without-title"},
    )
    provider.upsert_card(
        f"{domain_id}-source-note-only",
        {"appflowy_source_cells": {
            "Notes": "Source URL: https://example.test/source-note"}},
    )

    response = tc.get(f"/api/domain/{domain_id}/cards")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert [card["card_id"] for card in body["cards"]] == [
        f"{domain_id}-source-note-only", f"{domain_id}-url-only"]
    assert body["cards"][0]["title_integrity"] == "missing"
    assert body["data_quality"] == {
        "quarantined_empty_imports": 1,
        "retained_in_store": True,
        "reason": (
            "No title, source identifier, URL, summary, or retained source "
            "cells were available."
        ),
    }
    stored_ids = {card["card_id"] for card in provider.list_cards()}
    assert stored_ids == {
        f"{domain_id}-empty-import", f"{domain_id}-source-note-only",
        f"{domain_id}-url-only",
    }


def test_book_titles_project_exact_retained_source_without_rewriting_store(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card(
        "book-source-title",
        {
            "author": "Plato",
            "appflowy_source_cells": {"Name": "The Last Days of Socrates"},
        },
        status="Reading",
    )
    provider.upsert_card(
        "book-source-title-blank",
        {"appflowy_source_cells": {"Name": ""}},
        status="To read",
    )

    response = tc.get("/api/domain/book/cards")
    assert response.status_code == 200, response.json()
    cards = {card["card_id"]: card for card in response.json()["cards"]}
    recovered = cards["book-source-title"]
    assert recovered["title"] == "The Last Days of Socrates"
    assert recovered["title_integrity"] == "recovered_from_source"
    assert "appflowy_source_cells" not in recovered
    assert cards["book-source-title-blank"]["title"] == ""
    assert cards["book-source-title-blank"]["title_integrity"] == "missing"
    # Presentation recovery is explicit and read-only; canonical repair remains
    # a separately audited operator action.
    assert "title" not in provider._read_fields("book-source-title")

    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    positioned = tc.put(
        "/api/domain/book/card/book-source-title",
        json={
            "current_chapter": "The trial",
            "current_page": 22,
            "total_pages": 160,
            "progress_percent": 14,
        },
    )
    assert positioned.status_code == 200, positioned.json()
    assert positioned.json()["card"]["title"] == "The Last Days of Socrates"
    assert positioned.json()["card"]["current_chapter"] == "The trial"
    assert "title" not in provider._read_fields("book-source-title")

    noted = tc.post(
        "/api/domain/book/card/book-source-title/notes",
        json={"author": "Geoff", "text": "Revisit the trial and defense."},
    )
    assert noted.status_code == 201, noted.json()
    assert noted.json()["card"]["title"] == "The Last Days of Socrates"
    assert noted.json()["card"]["title_integrity"] == "recovered_from_source"
    assert "appflowy_source_cells" not in noted.json()["card"]

    moved = tc.post("/api/domain/book/move", json={
        "card_id": "book-source-title",
        "status": "Done",
    })
    assert moved.status_code == 200, moved.json()
    assert moved.json()["card"]["title"] == "The Last Days of Socrates"
    assert moved.json()["card"]["title_integrity"] == "recovered_from_source"
    assert moved.json()["card"]["status"] == "Done"
    assert "appflowy_source_cells" not in moved.json()["card"]

    duplicate = tc.post("/api/domain/book/cards", json={
        "title": "Ｔｈｅ　Ｌａｓｔ　Ｄａｙｓ　ｏｆ　Ｓｏｃｒａｔｅｓ",
        "author": "plato",
        "status": "To read",
    })
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_model_analysis_urls_are_never_reclassified_as_source_links(client):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog

    provider = CommandCenterBoardProvider(
        board_id="research_papers",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card(
        "paper-analysis-url",
        {
            "title": "No source code link",
            "suggested": "A model guessed https://github.com/invented/not-source",
        },
        status="Inbox",
    )

    card = tc.get("/api/domain/paper/cards").json()["cards"][0]
    assert card["useful_for_us"].endswith(
        "https://github.com/invented/not-source")
    assert card["code_links"] == []
    assert card["related_links"] == []


def _enable_temp_domain_config(mod, monkeypatch, tmp_path):
    configs = tmp_path / "configs"
    configs.mkdir()
    source = yaml.safe_load(
        (ROOT / "configs" / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    target = configs / "domain_surfaces.yaml"
    target.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    return target


def test_research_intake_rejects_one_sided_updates(
    client, monkeypatch, tmp_path,
):
    mod, tc, _ = client
    target = _enable_temp_domain_config(mod, monkeypatch, tmp_path)
    current = tc.get("/api/domain/paper/intake").json()

    stable_bytes = target.read_bytes()
    candidate = json.loads(json.dumps(current["intake"]))
    candidate["parameters"]["review_topics"].append("Agent evaluation")

    rejected = tc.put(
        "/api/domain/paper/intake",
        json={"intake": candidate, "expected_revision": current["revision"]},
    )

    assert rejected.status_code == 409
    assert "/api/research/settings" in rejected.json()["detail"]
    assert target.read_bytes() == stable_bytes


def test_shared_research_settings_save_topics_and_queue_a_real_refresh(
    client, monkeypatch, tmp_path,
):
    mod, tc, _ = client
    target = _enable_temp_domain_config(mod, monkeypatch, tmp_path)
    refresh = tmp_path / "research-refresh.json"
    monkeypatch.setattr(mod, "RESEARCH_REFRESH_FILE", refresh)
    current = tc.get("/api/research/settings")
    assert current.status_code == 200, current.json()
    value = current.json()
    body = {
        "topics": [*value["topics"], "Agent evaluation"],
        "paper": {
            "enabled": True,
            "top_n": 14,
            "lookback_days": 5,
            "analysis_batch_size": 20,
            "categories": ["cs.AI", "cs.LG"],
        },
        "repo": {
            "enabled": True,
            "top_n": 12,
            "lookback_days": 10,
            "analysis_batch_size": 20,
            "min_stars": 10,
        },
        "expected_revisions": {
            "paper": value["paper"]["revision"],
            "repo": value["repo"]["revision"],
        },
        "refresh": True,
    }

    saved = tc.put("/api/research/settings", json=body)

    assert saved.status_code == 200, saved.json()
    assert saved.json()["topics"][-1] == "Agent evaluation"
    assert saved.json()["refresh"]["state"] == "queued"
    queued = json.loads(refresh.read_text(encoding="utf-8"))
    assert queued["requested_sources"] == ["paper", "repo"]
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    research = {
        row["domain_id"]: row for row in data["domains"]
        if row["domain_id"] in {"paper", "repo"}
    }
    assert research["paper"]["intake"]["parameters"]["review_topics"] == body["topics"]
    assert research["repo"]["intake"]["parameters"]["review_topics"] == body["topics"]

    from command_center.boards.command_center_provider import CommandCenterBoardProvider
    from command_center.kanban_sync import EventLog
    provider = CommandCenterBoardProvider(
        board_id="research_papers",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )
    provider.upsert_card("paper-new-topic", {
        "title": "Agent evaluation for tool-using systems",
        "abstract": "A controlled agent evaluation protocol.",
        "review_topics": ["LLM agents"],
    })
    projected = tc.get("/api/domain/paper/cards").json()["cards"][0]
    assert projected["review_topics"] == ["LLM agents", "Agent evaluation"]

    body["topics"] = ["all:agent AND all:evaluation"]
    rejected = tc.put("/api/research/settings", json=body)
    assert rejected.status_code == 422
    assert "readable topic" in rejected.json()["detail"]


def test_intake_rejects_stale_invalid_and_identity_changes_without_writes(
    client, monkeypatch, tmp_path,
):
    mod, tc, _ = client
    target = _enable_temp_domain_config(mod, monkeypatch, tmp_path)
    original = tc.get("/api/domain/book/intake").json()
    first = json.loads(json.dumps(original["intake"]))
    first["parameters"]["instructions"] = "Add durable technical books."
    saved = tc.put(
        "/api/domain/book/intake",
        json={"intake": first, "expected_revision": original["revision"]},
    )
    assert saved.status_code == 200, saved.json()

    stable_bytes = target.read_bytes()
    stale = json.loads(json.dumps(original["intake"]))
    stale["summary"] = "A stale edit."
    response = tc.put(
        "/api/domain/book/intake",
        json={"intake": stale, "expected_revision": original["revision"]},
    )
    assert response.status_code == 409
    assert target.read_bytes() == stable_bytes

    invalid = json.loads(json.dumps(saved.json()["intake"]))
    invalid["parameters"]["Bad Key"] = True
    response = tc.put(
        "/api/domain/book/intake",
        json={"intake": invalid, "expected_revision": saved.json()["revision"]},
    )
    assert response.status_code == 422
    assert target.read_bytes() == stable_bytes

    identity_change = json.loads(json.dumps(saved.json()["intake"]))
    identity_change["producer"] = "manual"
    response = tc.put(
        "/api/domain/book/intake",
        json={
            "intake": identity_change,
            "expected_revision": saved.json()["revision"],
        },
    )
    assert response.status_code == 409
    assert "registry-owned" in response.json()["detail"]
    assert target.read_bytes() == stable_bytes

    schedule_change = json.loads(json.dumps(saved.json()["intake"]))
    schedule_change["schedule"] = "daily"
    response = tc.put(
        "/api/domain/book/intake",
        json={
            "intake": schedule_change,
            "expected_revision": saved.json()["revision"],
        },
    )
    assert response.status_code == 409
    assert target.read_bytes() == stable_bytes


def test_board_store_domain_empty_is_empty_plus_designed_state(client):
    _, tc, _ = client
    body = tc.get("/api/domain/job_application/cards").json()
    assert body["cards"] == []                      # no fixture smuggling
    assert body["empty_state"]["command"].startswith("uv run cc job-search")


def test_card_detail_and_404(client):
    _, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog
    provider = CommandCenterBoardProvider(
        board_id="linkedin_content_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card(
        "post-real-1",
        {"account": "geoffhadfield32_content", "body": "Real post"},
        status="Draft")
    detail = tc.get("/api/domain/linkedin_post/card/post-real-1").json()
    assert detail["card"]["card_id"] == "post-real-1"
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


def _book_provider(mod, tmp_path):
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.kanban_sync import EventLog

    return CommandCenterBoardProvider(
        board_id="reading_library",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards",
    )


def test_book_done_move_uses_configured_action_and_exact_transitions(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card(
        "book-done", {"title": "A Finished Book", "author": "A. Reader"},
        status="Reading")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    response = tc.post(
        "/api/domain/book/move",
        json={"card_id": "book-done", "status": "Done"},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["event"]["action"] == "finish_todo"
    assert response.json()["event"]["actor_type"] == "human"
    assert response.json()["card"]["status"] == "Done"
    pack = tc.get("/api/domain/book/cards").json()
    assert pack["cards"][0] == response.json()["card"]
    assert pack["transitions"] == {
        "To read": ["Reading", "Archived"],
        "Reading": ["To read", "Done", "Archived"],
        "Done": ["Reading", "Archived"],
        "Archived": ["To read"],
    }


def test_book_move_does_not_materialize_every_book_field_document(
    client, monkeypatch,
):
    """The governed event response is exact without two 283-card projections."""
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)

    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card(
        "book-fast", {"title": "Fast Feedback", "author": "A. Reader"},
        status="To read",
    )
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    def whole_board_read_is_a_regression(_provider):
        pytest.fail("one book move materialized the complete Books board")

    monkeypatch.setattr(
        CommandCenterBoardProvider, "list_cards",
        whole_board_read_is_a_regression,
    )
    response = tc.post(
        "/api/domain/book/move",
        json={"card_id": "book-fast", "status": "Reading"},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["card"]["status"] == "Reading"
    assert response.json()["card"]["title"] == "Fast Feedback"
    assert response.json()["event"]["action"] == "start_todo"


def test_book_mutations_require_write_enabled_and_writable_store(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card("book-gated", {"title": "Gated"}, status="To read")
    paths = (
        ("post", "/api/domain/book/cards",
         {"title": "New", "status": "To read"}),
        ("put", "/api/domain/book/card/book-gated", {"author": "Writer"}),
        ("post", "/api/domain/book/card/book-gated/notes",
         {"author": "Geoff", "text": "Note"}),
        ("delete", "/api/domain/book/card/book-gated", None),
    )
    for method, path, payload in paths:
        response = tc.request(method.upper(), path, json=payload)
        assert response.status_code == 503, (path, response.json())

    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(
        mod, "_domain_write_blockers", lambda _spec: ["store is read-only"])
    for method, path, payload in paths:
        response = tc.request(method.upper(), path, json=payload)
        assert response.status_code == 503, (path, response.json())
        assert "store is read-only" in response.json()["detail"]


def test_book_create_is_strict_governed_and_duplicate_safe(client, monkeypatch):
    mod, tc, _ = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    payload = {
        "title": "  Deep Work  ",
        "author": "Cal Newport",
        "description": "A practical guide to focused work.",
        "tier": "Essential",
        "type": "Nonfiction",
        "genre": "Productivity",
        "module": "Focus",
        "section": "Productivity",
        "hours": "8.5",
        "isbn": "9781455586691",
        "notes": "Imported or editable overview.",
        "current_chapter": "Chapter 2",
        "current_page": 42,
        "total_pages": 304,
        "progress_percent": 14,
        "status": "Reading",
    }

    response = tc.post("/api/domain/book/cards", json=payload)

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["card"]["title"] == "Deep Work"
    assert body["card"]["status"] == "Reading"
    assert body["card"]["book_notes"] == []
    assert body["card"]["genre"] == "Productivity"
    assert body["card"]["current_chapter"] == "Chapter 2"
    assert body["card"]["current_page"] == 42
    assert body["card"]["total_pages"] == 304
    assert body["card"]["progress_percent"] == 14
    assert body["event"]["action"] == "start_todo"
    assert body["event"]["actor_type"] == "human"
    assert body["card_id"].startswith("book-manual-")

    duplicate = tc.post("/api/domain/book/cards", json={
        **payload,
        "title": "Ｄｅｅｐ　Ｗｏｒｋ",
        "author": "cal newport",
        "status": "To read",
    })
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]

    assert tc.post("/api/domain/book/cards", json={
        "title": " ", "status": "To read"}).status_code == 422
    assert tc.post("/api/domain/book/cards", json={
        "title": "Typed", "author": 42, "status": "To read"}).status_code == 422
    assert tc.post("/api/domain/book/cards", json={
        "title": "Unknown", "status": "To read", "invented": True,
    }).status_code == 422
    invalid_status = tc.post("/api/domain/book/cards", json={
        "title": "Invalid lane", "status": "Shelf"})
    assert invalid_status.status_code == 400
    assert "not a configured column" in invalid_status.json()["detail"]
    assert tc.post("/api/domain/book/cards", json={
        "title": "Impossible location",
        "status": "Reading",
        "current_page": 401,
        "total_pages": 400,
    }).status_code == 422
    assert tc.post("/api/domain/book/cards", json={
        "title": "Invalid progress",
        "status": "Reading",
        "progress_percent": 101,
    }).status_code == 422
    assert tc.post("/api/domain/book/cards", json={
        "title": "Wrong page type",
        "status": "Reading",
        "current_page": "42",
    }).status_code == 422


def test_titleless_provenance_rows_do_not_block_create_repair_or_duplicates(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    titleless_a = {
        "author": "Unknown",
        "appflowy_row_id": "blank-source-a",
        "appflowy_source_sha256": "a" * 64,
    }
    titleless_b = {
        "notes": "The historical source title was blank.",
        "appflowy_row_id": "blank-source-b",
        "appflowy_source_sha256": "b" * 64,
    }
    provider.upsert_card("book-titleless-a", titleless_a)
    provider.upsert_card("book-titleless-b", titleless_b, status="Archived")
    durable_titleless_a = provider._read_fields("book-titleless-a")
    durable_titleless_b = provider._read_fields("book-titleless-b")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    created = tc.post("/api/domain/book/cards", json={
        "title": "A New Book",
        "author": "A Writer",
        "status": "To read",
    })

    assert created.status_code == 201, created.json()
    assert provider._read_fields("book-titleless-a") == durable_titleless_a
    assert provider._read_fields("book-titleless-b") == durable_titleless_b

    repaired = tc.put("/api/domain/book/card/book-titleless-a", json={
        "title": "Recovered by the operator",
    })
    assert repaired.status_code == 200, repaired.json()
    assert repaired.json()["card"]["title"] == "Recovered by the operator"
    assert repaired.json()["card"]["author"] == "Unknown"
    assert repaired.json()["card"]["appflowy_row_id"] == "blank-source-a"
    assert provider._read_fields("book-titleless-b") == durable_titleless_b

    duplicate = tc.post("/api/domain/book/cards", json={
        "title": "Ｒｅｃｏｖｅｒｅｄ　ｂｙ　ｔｈｅ　ｏｐｅｒａｔｏｒ",
        "author": "unknown",
        "status": "To read",
    })
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_book_duplicate_scan_rejects_malformed_stored_text_without_writes(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card(
        "book-malformed-text",
        {"title": 7, "appflowy_row_id": "malformed-source"},
    )
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    malformed_title = provider._read_fields("book-malformed-text")
    response = tc.post("/api/domain/book/cards", json={
        "title": "Candidate One", "status": "To read",
    })
    assert response.status_code == 409
    assert "title must be text" in response.json()["detail"]
    assert provider._read_fields("book-malformed-text") == malformed_title
    assert len(provider.list_cards()) == 1
    assert provider.log.read() == []

    provider.upsert_card("book-malformed-text", {"title": "", "author": 7})
    malformed_author = provider._read_fields("book-malformed-text")
    response = tc.post("/api/domain/book/cards", json={
        "title": "Candidate Two", "status": "To read",
    })
    assert response.status_code == 409
    assert "author must be text" in response.json()["detail"]
    assert provider._read_fields("book-malformed-text") == malformed_author
    assert len(provider.list_cards()) == 1
    assert provider.log.read() == []

    provider.upsert_card(
        "book-malformed-text",
        {
            "title": "",
            "author": "",
            "appflowy_source_cells": {"Name": 7},
        },
    )
    malformed_source_title = provider._read_fields("book-malformed-text")
    response = tc.post("/api/domain/book/cards", json={
        "title": "Candidate Three", "status": "To read",
    })
    assert response.status_code == 409
    assert "appflowy_source_cells.Name must be text" in response.json()["detail"]
    assert provider._read_fields("book-malformed-text") == malformed_source_title
    assert len(provider.list_cards()) == 1
    assert provider.log.read() == []


def test_concurrent_duplicate_book_create_writes_exactly_one(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    mod, tc, tmp_path = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    def create(_index):
        return tc.post("/api/domain/book/cards", json={
            "title": "The Same Book",
            "author": "One Author",
            "status": "To read",
        }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(create, range(2)))

    assert sorted(statuses) == [201, 409]
    provider = _book_provider(mod, tmp_path)
    assert [card["title"] for card in provider.list_cards()] == ["The Same Book"]
    events = provider.log.read()
    assert len(events) == 1 and events[0].action == "add_mission_card"


def test_book_create_event_failure_rolls_back_and_statusless_recovery_is_exact(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    provider = _book_provider(mod, tmp_path)
    real_emit_event = mod.emit_event

    def fail_event(*_args, **_kwargs):
        raise OSError("event append failed")

    monkeypatch.setattr(mod, "emit_event", fail_event)
    with pytest.raises(OSError, match="event append failed"):
        tc.post("/api/domain/book/cards", json={
            "title": "Atomic Creation", "status": "To read"})
    assert provider.list_cards() == []

    monkeypatch.setattr(mod, "emit_event", real_emit_event)
    provider.upsert_card("book-recovery", {"title": "Interrupted Before Fix"})
    pack = tc.get("/api/domain/book/cards").json()
    assert pack["transitions"][""] == ["To read"]
    recovered = tc.post("/api/domain/book/move", json={
        "card_id": "book-recovery", "status": "To read"})
    assert recovered.status_code == 200, recovered.json()
    assert recovered.json()["card"]["status"] == "To read"


def test_concurrent_book_moves_validate_one_latest_status(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card(
        "book-racing-move", {"title": "One Transition at a Time"},
        status="Reading")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    def move(target):
        return tc.post("/api/domain/book/move", json={
            "card_id": "book-racing-move", "status": target})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(move, ("Done", "To read")))

    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(provider.log.read()) == 2
    assert provider.list_cards()[0]["status"] in {"Done", "To read"}


def test_book_edit_is_partial_and_preserves_state_provenance_and_notes(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    original_note = {
        "note_id": "book-note-0000000000000001",
        "sequence": 1,
        "author": "Geoff",
        "text": "Keep this ordered note.",
        "created_at": "2026-07-16T12:00:00+00:00",
    }
    provider.upsert_card(
        "book-edit",
        {
            "title": "Original",
            "author": "Original Author",
            "notes": "Keep the legacy notes.",
            "book_notes": [original_note],
            "current_page": 20,
            "total_pages": 300,
            "progress_percent": 7,
            "appflowy_row_id": "source-row",
            "appflowy_source_sha256": "a" * 64,
        },
        status="Reading",
    )
    provider.upsert_card(
        "book-conflict",
        {"title": "Existing", "author": "Writer"},
        status="Archived",
    )
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    response = tc.put("/api/domain/book/card/book-edit", json={
        "title": "Updated",
        "author": "",
        "description": "Better details.",
    })

    assert response.status_code == 200, response.json()
    card = response.json()["card"]
    assert card["title"] == "Updated"
    assert "author" not in card
    assert card["description"] == "Better details."
    assert card["status"] == "Reading"
    assert card["notes"] == "Keep the legacy notes."
    assert card["book_notes"] == [original_note]
    assert card["appflowy_row_id"] == "source-row"
    assert card["appflowy_source_sha256"] == "a" * 64
    assert card["current_page"] == 20
    assert card["total_pages"] == 300
    assert card["progress_percent"] == 7

    positioned = tc.put("/api/domain/book/card/book-edit", json={
        "genre": "History",
        "current_chapter": "Chapter 4 - The turning point",
        "current_page": 75,
        "total_pages": 300,
        "progress_percent": 25,
    })
    assert positioned.status_code == 200, positioned.json()
    positioned_card = positioned.json()["card"]
    assert positioned_card["genre"] == "History"
    assert positioned_card["current_chapter"] == "Chapter 4 - The turning point"
    assert positioned_card["current_page"] == 75
    assert positioned_card["total_pages"] == 300
    assert positioned_card["progress_percent"] == 25
    assert positioned_card["reading_position_updated_at"]

    before_invalid_location = provider._read_fields("book-edit")
    invalid_location = tc.put("/api/domain/book/card/book-edit", json={
        "current_page": 301,
    })
    assert invalid_location.status_code == 409
    assert "cannot exceed total_pages" in invalid_location.json()["detail"]
    assert provider._read_fields("book-edit") == before_invalid_location

    duplicate = tc.put("/api/domain/book/card/book-edit", json={
        "title": " existing ",
        "author": "WRITER",
    })
    assert duplicate.status_code == 409
    assert tc.put(
        "/api/domain/book/card/book-edit", json={}).status_code == 400
    assert tc.put(
        "/api/domain/book/card/book-edit", json={"title": None}).status_code == 422
    assert tc.put(
        "/api/domain/book/card/missing", json={"author": "Nobody"}).status_code == 404


def test_book_notes_append_in_order_and_reject_bad_state(client, monkeypatch):
    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card(
        "book-notes",
        {"title": "Notes", "notes": "Legacy notes render first."},
        status="Reading",
    )
    provider.upsert_card(
        "book-malformed",
        {"title": "Malformed", "book_notes": {"not": "a list"}},
        status="To read",
    )
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    first = tc.post("/api/domain/book/card/book-notes/notes", json={
        "author": "Geoff", "text": "First observation."})
    second = tc.post("/api/domain/book/card/book-notes/notes", json={
        "author": "Assistant",
        "text": "Second observation.",
        "chapter": "Chapter 3 - Evidence",
        "page": 48,
        "total_pages": 320,
        "progress_percent": 15,
    })

    assert first.status_code == second.status_code == 201
    notes = second.json()["card"]["book_notes"]
    assert [note["sequence"] for note in notes] == [1, 2]
    assert [note["author"] for note in notes] == ["Geoff", "Assistant"]
    assert [note["text"] for note in notes] == [
        "First observation.", "Second observation."]
    assert len({note["note_id"] for note in notes}) == 2
    assert "chapter" not in notes[0]
    assert notes[1]["chapter"] == "Chapter 3 - Evidence"
    assert notes[1]["page"] == 48
    assert notes[1]["total_pages"] == 320
    assert notes[1]["progress_percent"] == 15
    assert second.json()["card"]["notes"] == "Legacy notes render first."
    assert second.json()["card"]["current_chapter"] == "Chapter 3 - Evidence"
    assert second.json()["card"]["current_page"] == 48
    assert second.json()["card"]["total_pages"] == 320
    assert second.json()["card"]["progress_percent"] == 15
    assert second.json()["card"]["reading_position_updated_at"]

    assert tc.post("/api/domain/book/card/book-notes/notes", json={
        "author": " ", "text": "No author"}).status_code == 422
    assert tc.post("/api/domain/book/card/book-notes/notes", json={
        "author": "Geoff", "text": " ", "extra": True}).status_code == 422
    assert tc.post("/api/domain/book/card/book-notes/notes", json={
        "author": "Geoff",
        "text": "Bad typed progress",
        "progress_percent": "15",
    }).status_code == 422
    conflicting_location = tc.post(
        "/api/domain/book/card/book-notes/notes",
        json={
            "author": "Geoff",
            "text": "This must not append.",
            "page": 400,
        },
    )
    assert conflicting_location.status_code == 409
    assert "cannot exceed total_pages" in conflicting_location.json()["detail"]
    assert len(provider._read_fields("book-notes")["book_notes"]) == 2
    malformed = tc.post("/api/domain/book/card/book-malformed/notes", json={
        "author": "Geoff", "text": "Must not rewrite bad state."})
    assert malformed.status_code == 409
    assert provider._read_fields("book-malformed")["book_notes"] == {
        "not": "a list"}
    assert tc.post("/api/domain/book/card/missing/notes", json={
        "author": "Geoff", "text": "No card"}).status_code == 404


def test_concurrent_book_notes_are_lossless_and_strictly_ordered(
    client, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor

    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card(
        "book-concurrent-notes", {"title": "Parallel Notes", "book_notes": []},
        status="Reading")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    def append(index):
        return tc.post(
            "/api/domain/book/card/book-concurrent-notes/notes",
            json={
                "author": "Geoff" if index % 2 else "Assistant",
                "text": f"Observation {index}",
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(append, range(20)))

    assert statuses == [201] * 20
    notes = provider.list_cards()[0]["book_notes"]
    assert [note["sequence"] for note in notes] == list(range(1, 21))
    assert len({note["note_id"] for note in notes}) == 20
    assert {note["text"] for note in notes} == {
        f"Observation {index}" for index in range(20)}


def test_book_remove_is_archive_only_idempotent_and_restorable(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    fields = {
        "title": "Keep Everything",
        "author": "History",
        "notes": "Never erase this.",
        "book_notes": [{
            "note_id": "book-note-0000000000000002",
            "sequence": 1,
            "author": "Geoff",
            "text": "Retained",
            "created_at": "2026-07-16T12:00:00+00:00",
        }],
        "appflowy_row_id": "row-1",
    }
    provider.upsert_card("book-archive", fields, status="To read")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    archived = tc.delete("/api/domain/book/card/book-archive")
    repeated = tc.delete("/api/domain/book/card/book-archive")

    assert archived.status_code == repeated.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["event"]["action"] == "reject_card"
    assert repeated.json()["status"] == "unchanged"
    assert repeated.json()["event"] is None
    stored = provider._read_fields("book-archive")
    for key, value in fields.items():
        assert stored[key] == value
    events = provider.log.read()
    assert [event.action for event in events] == [
        "add_mission_card", "reject_card"]

    restored = tc.post("/api/domain/book/move", json={
        "card_id": "book-archive", "status": "To read"})
    assert restored.status_code == 200, restored.json()
    assert restored.json()["event"]["action"] == "add_mission_card"
    assert restored.json()["card"]["status"] == "To read"


def test_concurrent_book_remove_emits_one_archive_event(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    mod, tc, tmp_path = client
    provider = _book_provider(mod, tmp_path)
    provider.upsert_card(
        "book-racing-archive", {"title": "Archive Once"}, status="To read")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda _index: tc.delete(
                "/api/domain/book/card/book-racing-archive"),
            range(2),
        ))

    assert [response.status_code for response in responses] == [200, 200]
    assert {response.json()["status"] for response in responses} == {
        "archived", "unchanged"}
    assert [event.action for event in provider.log.read()] == [
        "add_mission_card", "reject_card"]


def test_job_move_to_selected_queues_packet_prep(client, monkeypatch):
    import time

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

    # gate 1 of the 3-step flow: found -> Selected by Geoff. The move returns
    # IMMEDIATELY and queues packet prep on the background worker (no inline LLM
    # wait), so Geoff can move through cards fast. The worker advances the card
    # to Needs Geoff on its own.
    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": card_id, "status": "Selected by Geoff"})

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["event"]["status_after"] == "Selected by Geoff"
    assert body["side_effect"]["operation"] == "process_selected_queued"
    # the card has NOT advanced yet — prep runs in the background
    assert body["card"]["status"] == "Selected by Geoff"

    # wait for the background worker to finish preparing the packet
    deadline = time.time() + 30
    card = None
    while time.time() < deadline:
        cards = {c["card_id"]: c for c in provider.list_cards()}
        card = cards.get(card_id)
        if card and card.get("status") == "Needs Geoff":
            break
        time.sleep(0.05)

    prep = tc.get("/api/job-search/prep-status").json()
    assert card is not None and card["status"] == "Needs Geoff", (
        f"packet prep did not complete in time: {prep}")
    assert prep["runs_completed"] >= 1
    assert prep["last_error"] is None
    app_id = card.get("application_id")
    assert app_id
    app_dir = tmp_path / "applications_active" / app_id
    assert app_dir.is_dir()
    assert (app_dir / "executor.json").is_file()
    assert card["company"] == suggestion["job"]["company"]
    assert card["job_key"] == suggestion["job"]["job_key"]


def test_job_reject_move_records_reason(client, monkeypatch):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.job_search.board import publish_suggestions
    from command_center.job_search.config import load_config
    from command_center.job_search.rejections import load_rejections
    from command_center.kanban_sync import EventLog

    _write_suggestion(tmp_path, "sportsbook_analytics_engineer.md")
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

    resp = tc.post("/api/domain/job_application/move",
                   json={"card_id": card_id, "status": "Rejected / Skip",
                         "reason_code": "salary", "reason_note": "too low"})
    assert resp.status_code == 200, resp.json()
    assert resp.json()["side_effect"]["operation"] == "rejection_recorded"
    assert resp.json()["side_effect"]["reason_code"] == "salary"
    rows = load_rejections(tmp_path)
    assert len(rows) == 1
    assert rows[0]["reason_code"] == "salary"
    assert rows[0]["note"] == "too low"


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
            "furthers_process": True,
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


def test_non_furthering_recruiter_note_does_not_move_to_interviewing(
    client, monkeypatch,
):
    mod, tc, tmp_path = client
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    from command_center.job_search.config import load_config
    from command_center.kanban_sync import EventLog

    app_dir = _prepared_application(tmp_path)
    provider = CommandCenterBoardProvider(
        board_id="job_search_pipeline_internal",
        event_log=EventLog(tmp_path / "events.jsonl"),
        store_dir=tmp_path / "boards")
    provider.upsert_card(
        "job-recruiter-rejection",
        {"company": "Basketball AI Lab", "role_title": "Data Scientist",
         "application_id": app_dir.name, "materials_path": str(app_dir)},
        status="Completed")
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(
        mod, "_job_search_config_and_root", lambda: (load_config(), tmp_path))

    response = tc.post(
        "/api/domain/job_application/card/job-recruiter-rejection/note",
        json={"type": "recruiter_email", "source": "email",
              "text": "The recruiter closed the role.",
              "furthers_process": False})

    assert response.status_code == 200, response.json()
    assert response.json()["card"]["status"] == "Completed"
    assert response.json()["event"] is None


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
