"""First-party Self Improvement board destination and all-board scan coverage."""
from __future__ import annotations

from datetime import UTC, datetime

import yaml

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.improvement.discovery.board_feed import all_board_opportunity_records
from command_center.improvement.discovery.kanban import command_center_card_drafter
from command_center.kanban_sync.events import EventLog, emit_event


def _board(board_id: str, repo_ids: list[str] | None = None) -> dict:
    return {
        "board_id": board_id, "provider": "command_center_ui",
        "workspace_ref": "self", "board_ref": board_id,
        "execution_scope": "life", "repo_ids": repo_ids or [],
        "status_mapping": {
            "backlog": "Backlog", "ready": "Ready", "in_progress": "In Progress",
            "done": "Done", "blocked": "Blocked", "rejected": "Rejected",
            "awaiting_approval": "Awaiting Approval",
        },
        "required_fields": ["title"],
        "allowed_agent_verbs": [
            "add_mission_card", "stage_card", "start_todo", "finish_todo",
            "block_card", "reject_card",
        ],
        "forbidden_agent_verbs": [
            "approve_card", "merge", "deploy", "delete_card", "delete_board",
        ],
        "blockers": [],
    }


def test_all_registered_boards_are_sources_except_non_recursive_output(tmp_path):
    config = tmp_path / "boards.yaml"
    config.write_text(yaml.safe_dump({
        "schema_version": "command-center.kanban-boards.v1",
        "boards": [
            _board("alpha", ["llm_station"]), _board("beta"),
            _board("self_improvement"),
        ],
    }), encoding="utf-8")
    store = tmp_path / "store"
    log = EventLog(tmp_path / "events.jsonl")
    old = datetime(2026, 6, 1, tzinfo=UTC)

    for board_id, card_id, status in (
        ("alpha", "a1", "Backlog"), ("beta", "b1", "Done"),
        ("self_improvement", "out1", "Blocked"),
    ):
        provider = CommandCenterBoardProvider(
            board_id=board_id, event_log=log, store_dir=store)
        provider.upsert_card(card_id, {"title": f"{board_id} card"})
        action = {"Done": "finish_todo", "Blocked": "block_card"}.get(
            status, "add_mission_card")
        emit_event(
            log, action=action, board_id=board_id, card_id=card_id,
            source_surface="daily_dag", status_after=status, now=old)

    records = all_board_opportunity_records(
        board_config_path=config, board_store_dir=store, event_log_path=log.path,
        now=datetime(2026, 7, 1, tzinfo=UTC))
    assert [(row["board_id"], row["card_id"]) for row in records] == [("alpha", "a1")]
    assert records[0]["age_days"] == 30
    assert records[0]["repo_ids"] == ["llm_station"]
    assert "registered to llm_station" in records[0]["repository_reason"]


def test_first_party_drafter_is_idempotent_and_traceable(tmp_path, monkeypatch):
    event_path = tmp_path / "events.jsonl"
    store = tmp_path / "boards"
    monkeypatch.setenv("KANBAN_EVENT_LOG", str(event_path))
    monkeypatch.setenv("KANBAN_BOARD_STORE", str(store))
    draft = command_center_card_drafter()
    fields = {
        "card_id": "EXP-scan-code-123", "title": "[self-improve] tighten a check",
        "section": "Command Center", "action": "add deterministic validation",
        "acceptance": "Evidence: failing case", "risk": "L1", "priority": "P2",
        "notes": "trace", "pillar": "code_quality", "score": 3.5,
        "source": "code_health", "evidence": "failing case", "unknowns": "",
        "repo_ids": ["llm_station"],
        "repository_reason": "Dogfood the control plane repository.",
    }
    assert "drafted" in draft(**fields)
    assert "updated" in draft(**fields)

    provider = CommandCenterBoardProvider(
        board_id="self_improvement", event_log=EventLog(event_path), store_dir=store)
    cards = provider.list_cards()
    assert len(cards) == 1
    assert cards[0]["experiment_id"] == "EXP-scan-code-123"
    assert cards[0]["status"] == "Backlog"
    assert cards[0]["repo_ids"] == ["llm_station"]
    assert cards[0]["repository_reason"].startswith("Dogfood")
    assert len(EventLog(event_path).read()) == 1


def test_repository_registry_wires_self_improvement_domain():
    with open("configs/kanban_boards.yaml", encoding="utf-8") as fh:
        boards = yaml.safe_load(fh)
    with open("configs/domain_surfaces.yaml", encoding="utf-8") as fh:
        domains = yaml.safe_load(fh)
    board = next(row for row in boards["boards"] if row["board_id"] == "self_improvement")
    domain = next(row for row in domains["domains"] if row["domain_id"] == "self_improvement")
    assert domain["title"] == "Self Improvement"
    assert domain["source"] == "board_store"
    assert domain["board_id"] == board["board_id"]
    assert domain["intake"]["producer"] == "self_improvement_daily"
    drawer_fields = {field["name"] for field in domain["drawer_fields"]}
    assert {"repo_ids", "repository_reason"} <= drawer_fields
    assert all(row["domain_id"] != "machine_upkeep" for row in domains["domains"])
