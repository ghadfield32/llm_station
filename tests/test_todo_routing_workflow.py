"""End-to-end chat/capture TODO routing into live generic board projections.

All state is hermetic: temp configs, in-memory graph/captures, temp board store.
No live board, Ledger, generated evidence, or source-backed tracker is touched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"

MAPPING = {
    "backlog": "Backlog",
    "ready": "Ready",
    "in_progress": "In Progress",
    "done": "Done",
    "blocked": "Blocked",
    "rejected": "Rejected",
    "awaiting_approval": "Awaiting Approval",
}
COLUMNS = list(MAPPING.values())
ACTIONS = {
    "Backlog": "add_mission_card",
    "Ready": "stage_card",
    "In Progress": "start_todo",
    "Done": "finish_todo",
    "Blocked": "block_card",
    "Rejected": "reject_card",
    "Awaiting Approval": "stage_card",
}
WALL = ["approve_card", "merge", "deploy", "delete_card", "delete_board"]
ALLOWED = [
    "add_mission_card", "stage_card", "start_todo", "finish_todo",
    "block_card", "reject_card",
]


def _board(board_id: str, *, repo_ids: list[str] | None = None) -> dict:
    return {
        "board_id": board_id,
        "provider": "command_center_ui",
        "workspace_ref": "self",
        "board_ref": board_id,
        "execution_scope": "repository" if repo_ids else "life",
        "repo_ids": repo_ids or [],
        "status_mapping": MAPPING,
        "required_fields": [
            "MissionID", "RepoID", "Risk", "LastSync", "Section"],
        "allowed_agent_verbs": ALLOWED,
        "forbidden_agent_verbs": WALL,
        "blockers": [],
    }


def _domain(
    domain_id: str,
    *,
    board_id: str,
    component: str = "generic_task",
    columns: list[str] | None = None,
) -> dict:
    lanes = columns or COLUMNS
    return {
        "domain_id": domain_id,
        "title": domain_id.replace("_", " ").title(),
        "card_component": component,
        "source": "board_store",
        "board_id": board_id,
        "columns": lanes,
        "column_actions": {
            lane: ACTIONS[lane] for lane in lanes if lane in ACTIONS},
        "summary_fields": [{"name": "title", "label": "Title"}],
        "drawer_fields": [{"name": "description", "label": "Description"}],
        "allowed_actions": ALLOWED,
        "empty_state": {"title": "Empty", "hint": "Route a TODO here."},
    }


def _seed_configs(configs: Path) -> None:
    configs.mkdir(parents=True)
    registry = {
        "schema_version": "command-center.kanban-boards.v1",
        "boards": [
            _board("tasks", repo_ids=["llm_station"]),
            _board(
                "betts_basketball_grand_todo",
                repo_ids=["betts_basketball"],
            ),
            _board("posts"),
        ],
    }
    domains = {
        "schema_version": "command-center.domain-surfaces.v1",
        "domains": [
            _domain("tasks", board_id="tasks"),
            _domain(
                "betts_basketball_grand_todo",
                board_id="betts_basketball_grand_todo"),
            _domain(
                "posts", board_id="posts", component="linkedin_post",
                columns=["Draft", "In Queue", "Scheduled", "Published"]),
        ],
    }
    (configs / "kanban_boards.yaml").write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    (configs / "domain_surfaces.yaml").write_text(
        yaml.safe_dump(domains, sort_keys=False), encoding="utf-8")
    (configs / "autonomy.yaml").write_text(
        yaml.safe_dump({
            "repo_manifests": [
                {
                    "repo_id": "llm_station",
                    "remote_url": "https://github.com/ghadfield32/llm_station.git",
                    "kanban_board_id": "tasks",
                },
                {
                    "repo_id": "betts_basketball",
                    "remote_url": "https://github.com/ghadfield32/betts_basketball.git",
                    "kanban_board_id": "betts_basketball_grand_todo",
                },
            ],
        }, sort_keys=False),
        encoding="utf-8",
    )


def _load(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    configs = tmp_path / "configs"
    _seed_configs(configs)
    spec = importlib.util.spec_from_file_location(
        "agent_kanban_ui_todo_routing_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_todo_routing_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "BOARD_STORE_DIR", tmp_path / "boards")
    monkeypatch.setattr(mod, "KANBAN_EVENT_LOG", tmp_path / "events.jsonl")
    mod.BOARD_STORE_DIR.mkdir(parents=True)
    monkeypatch.setattr(mod, "WORKGRAPH_ENABLED", True)
    monkeypatch.setattr(mod, "WORKGRAPH_LEDGER", False)
    monkeypatch.setattr(mod, "CHAT_ENABLED", False)
    monkeypatch.setattr(mod, "CAPTURE_LEDGER", False)
    mod._workgraph_service = None
    mod._capture_service = None
    mod._chat_planner = None
    mod._telemetry_service = None
    service = mod._get_workgraph_service()  # hermetic in-memory service
    mod._get_telemetry_service()
    monkeypatch.setattr(mod, "WORKGRAPH_LEDGER", True)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    return mod, service, TestClient(mod.app), configs


def _create_board(client, title: str, description: str = "") -> str:
    response = client.post(
        "/api/board-module",
        json={"title": title, "description": description},
    )
    assert response.status_code == 201, response.text
    return response.json()["board_id"]


def _teach_route(client, title: str, board_id: str, *, repeats: int = 1) -> None:
    for _ in range(repeats):
        response = client.post("/api/routing-corrections", json={
            "title": title,
            "chosen_board_id": board_id,
        })
        assert response.status_code == 201, response.text


def _convert_chat_item(client, item: dict, board: dict, conversation_id: str) -> dict:
    captured = client.post("/api/captures", json={
        "raw_content": item["title"],
        "source_type": "chat",
        "conversation_id": conversation_id,
        "requested_mode": "create_task",
    })
    assert captured.status_code == 201, captured.text
    capture_id = captured.json()["record"]["capture_id"]
    converted = client.post(f"/api/captures/{capture_id}/convert", json={
        "conversation_id": conversation_id,
        "items": [{
            **item,
            "primary_board": {
                "board_id": board["board_id"],
                "domain_id": board["domain_id"],
                "card_component": "generic_task",
            },
        }],
        "edges": [],
    })
    assert converted.status_code == 201, converted.text
    return {
        "capture_id": capture_id,
        "receipt": converted.json(),
    }


def test_empty_compatible_board_is_offered_but_specialized_and_grand_are_not(
    monkeypatch, tmp_path,
):
    _mod, _service, client, _configs = _load(monkeypatch, tmp_path)
    response = client.post(
        "/api/work-items/route",
        json={"text": "- research injury data\n- write a post\n- buy filters"},
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert [board["board_id"] for board in proposal["routable_boards"]] == ["tasks"]
    assert len(proposal["plan"]["items"]) == 3
    assert client.get("/api/work-items").json() == []
    board_questions = [
        question for question in proposal["needs_confirmation"]
        if question["question"].startswith("Which board")]
    assert board_questions
    assert all(question["options"] == ["tasks"] for question in board_questions)


def test_new_empty_board_is_immediately_routable_without_seed_card(
    monkeypatch, tmp_path,
):
    _mod, _service, client, _configs = _load(monkeypatch, tmp_path)
    created = client.post(
        "/api/board-module",
        json={"title": "Home Projects", "description": "house TODOs"},
    )
    assert created.status_code == 201, created.text
    proposal = client.post(
        "/api/work-items/route", json={"text": "paint the garage"}).json()
    options = {board["board_id"] for board in proposal["routable_boards"]}
    assert options == {"tasks", "home_projects"}
    assert client.get("/api/domain/home_projects/cards").json()["cards"] == []


@pytest.mark.parametrize(("title", "description", "expected_id", "example"), [
    ("Home Maintenance", "house and repair work", "home_maintenance",
     "service the furnace"),
    ("Learning Lab", "courses and deliberate practice", "learning_lab",
     "complete the Rust ownership module"),
    ("Launch Plan 2027", "launch preparation", "launch_plan_2027",
     "draft the launch checklist"),
])
def test_varied_new_kanbans_are_governed_empty_and_immediately_offered(
    monkeypatch, tmp_path, title, description, expected_id, example,
):
    _mod, _service, client, configs = _load(monkeypatch, tmp_path)
    board_id = _create_board(client, title, description)
    assert board_id == expected_id

    proposal = client.post("/api/work-items/route", json={"text": example}).json()
    catalog = {board["board_id"]: board for board in proposal["routable_boards"]}
    assert expected_id in catalog
    assert catalog[expected_id]["title"] == title
    assert catalog[expected_id]["columns"] == COLUMNS
    assert catalog[expected_id]["status_mapping"] == MAPPING
    question = next(
        q for q in proposal["needs_confirmation"]
        if q["question"].startswith("Which board"))
    assert expected_id in question["options"]
    assert client.get(f"/api/domain/{expected_id}/cards").json()["cards"] == []

    registry = yaml.safe_load(
        (configs / "kanban_boards.yaml").read_text(encoding="utf-8"))
    saved = next(board for board in registry["boards"] if board["board_id"] == expected_id)
    assert saved["forbidden_agent_verbs"] == WALL
    assert "delete_card" not in saved["allowed_agent_verbs"]


def test_unmatched_todo_lists_every_compatible_existing_and_new_board_option(
    monkeypatch, tmp_path,
):
    _mod, _service, client, _configs = _load(monkeypatch, tmp_path)
    for title in ("Fitness Plan", "Travel Plans", "Finance Ops"):
        _create_board(client, title)

    proposal = client.post(
        "/api/work-items/route",
        json={"text": "organize a miscellaneous idea"},
    ).json()
    question = next(
        q for q in proposal["needs_confirmation"]
        if q["question"].startswith("Which board"))
    assert question["options"] == [
        "finance_ops", "fitness_plan", "tasks", "travel_plans"]
    assert [board["title"] for board in proposal["routable_boards"]] == [
        "Finance Ops", "Fitness Plan", "Tasks", "Travel Plans"]
    assert all(
        board["columns"] == COLUMNS
        for board in proposal["routable_boards"])
    assert client.get("/api/work-items").json() == []


def test_mixed_chat_topics_route_to_different_kanbans_and_convert_one_by_one(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    destinations = {
        "research_queue": _create_board(client, "Research Queue"),
        "content_studio": _create_board(client, "Content Studio"),
        "home_care": _create_board(client, "Home Care"),
    }
    assert destinations == {
        "research_queue": "research_queue",
        "content_studio": "content_studio",
        "home_care": "home_care",
    }
    _teach_route(client, "biomechanics evidence", "research_queue")
    _teach_route(client, "newsletter campaign", "content_studio")
    _teach_route(client, "furnace maintenance", "home_care")

    response = client.post("/api/work-items/route", json={
        "conversation_id": "chat-mixed-topics",
        "text": (
            "- investigate biomechanics evidence\n"
            "- draft newsletter campaign\n"
            "- schedule furnace maintenance"
        ),
    })
    assert response.status_code == 200, response.text
    proposal = response.json()
    items = proposal["plan"]["items"]
    assert [item["primary_board"]["board_id"] for item in items] == [
        "research_queue", "content_studio", "home_care"]
    assert [suggestion["board_id"] for suggestion in proposal["board_suggestions"]] == [
        "research_queue", "content_studio", "home_care"]
    assert not [
        q for q in proposal["needs_confirmation"]
        if q["question"].startswith("Which board")]

    captures: list[str] = []
    for item in items:
        result = _convert_chat_item(
            client, item, item["primary_board"], "chat-mixed-topics")
        captures.append(result["capture_id"])
        assert len(result["receipt"]["created"]) == 1

    assert len(service.list_items()) == 3
    assert all(
        client.get(f"/api/captures/{capture_id}").json()["processing_status"]
        == "routed"
        for capture_id in captures)
    expected = {
        "research_queue": "investigate biomechanics evidence",
        "content_studio": "draft newsletter campaign",
        "home_care": "schedule furnace maintenance",
    }
    for domain_id, title in expected.items():
        cards = client.get(f"/api/domain/{domain_id}/cards").json()["cards"]
        matching = [card for card in cards if card["title"] == title]
        assert len(matching) == 1
        assert matching[0]["conversation_id"] == "chat-mixed-topics"


def test_ambiguous_topic_offers_only_the_two_evidence_matched_boards(
    monkeypatch, tmp_path,
):
    _mod, _service, client, _configs = _load(monkeypatch, tmp_path)
    _create_board(client, "Research Queue")
    _create_board(client, "Content Studio")
    _teach_route(client, "biomechanics", "research_queue")
    _teach_route(client, "newsletter", "content_studio")

    proposal = client.post("/api/work-items/route", json={
        "text": "prepare a biomechanics newsletter",
    }).json()
    assert proposal["plan"]["items"][0]["primary_board"] is None
    assert {suggestion["board_id"] for suggestion in proposal["board_suggestions"]} == {
        "research_queue", "content_studio"}
    question = next(
        q for q in proposal["needs_confirmation"]
        if q["question"].startswith("Which board"))
    assert set(question["options"]) == {"research_queue", "content_studio"}
    assert "tasks" not in question["options"]


def test_human_override_updates_future_topic_routing_without_restart(
    monkeypatch, tmp_path,
):
    _mod, _service, client, _configs = _load(monkeypatch, tmp_path)
    _create_board(client, "Research Queue")
    _create_board(client, "Content Studio")
    title = "quarterly analysis brief"
    _teach_route(client, title, "research_queue")

    first = client.post("/api/work-items/route", json={"text": title}).json()
    assert first["plan"]["items"][0]["primary_board"]["board_id"] == "research_queue"

    _teach_route(client, title, "content_studio", repeats=2)
    updated = client.post("/api/work-items/route", json={"text": title}).json()
    assert updated["plan"]["items"][0]["primary_board"]["board_id"] == "content_studio"
    suggestion = updated["board_suggestions"][0]
    assert suggestion["board_id"] == "content_studio"
    assert "matched" in suggestion["reason"]


def test_one_canonical_todo_stays_updated_across_two_kanban_projections(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    _create_board(client, "Home Projects")
    _create_board(client, "Quarterly Planning")
    proposal = client.post("/api/work-items/route", json={
        "text": "replace the office lighting",
        "conversation_id": "chat-shared-projection",
    }).json()
    item = proposal["plan"]["items"][0]
    primary = {
        "board_id": "home_projects", "domain_id": "home_projects",
        "card_component": "generic_task",
    }
    converted = _convert_chat_item(
        client, item, primary, "chat-shared-projection")
    work_id = converted["receipt"]["created"][0]["work_item"]["work_item_id"]
    secondary = client.post(f"/api/work-items/{work_id}/placements", json={
        "board_id": "quarterly_planning",
        "domain_id": "quarterly_planning",
        "card_component": "generic_task",
        "is_primary": False,
    })
    assert secondary.status_code == 201, secondary.text

    def projected(domain_id: str) -> dict:
        return next(
            card for card in client.get(
                f"/api/domain/{domain_id}/cards").json()["cards"]
            if card.get("work_item_id") == work_id)

    home = projected("home_projects")
    planning = projected("quarterly_planning")
    assert home["status"] == planning["status"] == "Backlog"
    moved = client.post("/api/domain/home_projects/move", json={
        "card_id": home["card_id"], "status": "Ready",
    })
    assert moved.status_code == 200, moved.text
    assert service.get_item(work_id).canonical_status == "ready"
    assert projected("home_projects")["status"] == "Ready"
    assert projected("quarterly_planning")["status"] == "Ready"
    assert len(service.list_items()) == 1


def test_rerouting_an_existing_chat_todo_surfaces_reuse_and_never_writes(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    title = "book the annual HVAC service"
    initial = client.post("/api/work-items/route", json={"text": title}).json()
    _convert_chat_item(
        client, initial["plan"]["items"][0],
        {"board_id": "tasks", "domain_id": "tasks"}, "chat-duplicate")
    [existing] = service.list_items()

    rerouted = client.post("/api/work-items/route", json={"text": title}).json()
    assert len(service.list_items()) == 1
    [candidate] = rerouted["duplicate_candidates"]
    assert candidate["ref"] == "i1"
    assert candidate["existing_work_item_id"] == existing.work_item_id
    assert candidate["existing_title"] == title
    # evidence-tagged reason: match class + plain-language why
    assert candidate["reason"].startswith("exact_same:")
    # the rich report carries the same finding with explicit resolutions
    [report] = rerouted["duplicate_reports"]
    finding = report["report"]["findings"][0]
    assert finding["existing_work_item_id"] == existing.work_item_id
    assert finding["match_class"] == "exact_same"
    duplicate_question = next(
        q for q in rerouted["needs_confirmation"]
        if "looks like existing work" in q["question"])
    assert "reuse_existing" in duplicate_question["options"]
    assert "create_separate" in duplicate_question["options"]
    assert rerouted["summary"]["item_count"] == 1


def test_varied_list_uses_past_corrections_and_keeps_unmatched_choice_explicit(
    monkeypatch, tmp_path,
):
    _mod, _service, client, _configs = _load(monkeypatch, tmp_path)
    for title in ("Research Queue", "Content Queue"):
        result = client.post("/api/board-module", json={"title": title})
        assert result.status_code == 201, result.text
    for _ in range(2):
        assert client.post("/api/routing-corrections", json={
            "title": "research feasibility study",
            "chosen_board_id": "research_queue",
        }).status_code == 201
        assert client.post("/api/routing-corrections", json={
            "title": "write linkedin post",
            "chosen_board_id": "content_queue",
        }).status_code == 201

    proposal = client.post("/api/work-items/route", json={
        "text": (
            "- research feasibility study for player health\n"
            "- write linkedin post about the findings\n"
            "- replace furnace filter"
        ),
    }).json()
    items = proposal["plan"]["items"]
    assert items[0]["primary_board"]["board_id"] == "research_queue"
    assert items[1]["primary_board"]["board_id"] == "content_queue"
    assert items[2]["primary_board"] is None
    unanswered = next(
        question for question in proposal["needs_confirmation"]
        if question["ref"] == "i3"
        and question["question"].startswith("Which board"))
    assert set(unanswered["options"]) == {
        "tasks", "research_queue", "content_queue"}


def test_chat_commit_projects_to_board_and_move_updates_canonical_state(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    proposal = client.post(
        "/api/work-items/route",
        json={"text": "renew the water filter", "conversation_id": "chat-1"},
    ).json()
    plan = proposal["plan"]
    plan["items"][0]["primary_board"] = {
        "board_id": "tasks", "domain_id": "tasks",
        "card_component": "generic_task",
    }
    committed = client.post("/api/chat/work-items/commit", json=plan)
    assert committed.status_code == 201, committed.text
    receipt = committed.json()["created"][0]
    work_id = receipt["work_item"]["work_item_id"]

    board = client.get("/api/domain/tasks/cards").json()
    cards = [card for card in board["cards"] if card.get("work_item_id") == work_id]
    assert len(cards) == 1
    assert cards[0]["title"] == "renew the water filter"
    assert cards[0]["status"] == "Backlog"
    assert cards[0]["conversation_id"] == "chat-1"

    moved = client.post(
        "/api/domain/tasks/move",
        json={"card_id": cards[0]["card_id"], "status": "Ready"},
    )
    assert moved.status_code == 200, moved.text
    assert service.get_item(work_id).canonical_status == "ready"
    reread = client.get("/api/domain/tasks/cards").json()["cards"]
    assert next(card for card in reread if card.get("work_item_id") == work_id)[
        "status"] == "Ready"


def test_specialized_board_never_renders_generic_work_projection(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    item = service.create_item("draft a post", kind="post")
    service.add_placement(
        item.work_item_id, "posts", "posts", is_primary=True,
        card_component="generic_task")
    cards = client.get("/api/domain/posts/cards").json()["cards"]
    assert all(card.get("work_item_id") != item.work_item_id for card in cards)


def test_capture_conversion_retry_repairs_link_without_duplicate_work(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    captured = client.post(
        "/api/captures",
        json={"raw_content": "replace furnace filter", "requested_mode": "create_task"},
    ).json()
    capture_id = captured["record"]["capture_id"]
    existing = service.create_item(
        "replace furnace filter", capture_id=capture_id)
    assert service._store.placements_for(existing.work_item_id) == []
    body = {
        "items": [{
            "ref": "i1", "title": "replace furnace filter", "kind": "todo",
            "primary_board": {
                "board_id": "tasks", "domain_id": "tasks",
                "card_component": "generic_task",
            },
        }],
        "edges": [],
    }
    repaired = client.post(
        f"/api/captures/{capture_id}/convert", json=body)
    assert repaired.status_code == 201, repaired.text
    assert repaired.json()["created"] == []
    assert repaired.json()["linked_existing"][0]["work_item"][
        "work_item_id"] == existing.work_item_id
    placements = service._store.placements_for(existing.work_item_id)
    assert len(placements) == 1
    assert placements[0].board_id == "tasks"
    assert placements[0].is_primary is True
    assert len(service.list_items()) == 1


def test_capture_retry_rolls_forward_partial_primary_placement_write(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    capture_id = client.post("/api/captures", json={
        "raw_content": "repair partial placement", "requested_mode": "create_task",
    }).json()["record"]["capture_id"]
    body = {
        "items": [{
            "ref": "i1", "title": "repair partial placement",
            "primary_board": {
                "board_id": "tasks", "domain_id": "tasks",
                "card_component": "generic_task",
            },
        }],
        "edges": [],
    }
    # Seed the exact legacy split state produced before placement + primary/event
    # became one atomic store operation. Current writes can no longer create it;
    # the retry path remains able to reconcile already-persisted historical state.
    from command_center.work_graph import WorkPlacement
    partial = service.create_item(
        "repair partial placement", capture_id=capture_id,
        conversation_id=f"capture:{capture_id}",
    )
    service._store.add_placement(WorkPlacement(
        placement_id="P-legacy-partial",
        work_item_id=partial.work_item_id,
        board_id="tasks",
        domain_id="tasks",
        is_primary=True,
        card_component="generic_task",
        created_at="2026-07-16T00:00:00+00:00",
    ))
    assert partial.primary_board_id is None
    assert len(service._store.placements_for(partial.work_item_id)) == 1
    assert not [
        event for event in service._store.events(partial.work_item_id)
        if event.kind == "placement_added"]

    repaired = client.post(f"/api/captures/{capture_id}/convert", json=body)
    assert repaired.status_code == 201, repaired.text
    assert len(service.list_items()) == 1
    assert len(service._store.placements_for(partial.work_item_id)) == 1
    assert service.get_item(partial.work_item_id).primary_board_id == "tasks"
    placement_events = [
        event for event in service._store.events(partial.work_item_id)
        if event.kind == "placement_added"]
    assert len(placement_events) == 1
    assert placement_events[0].payload["recovered"] is True
    assert client.get(
        f"/api/captures/{capture_id}").json()["processing_status"] == "routed"
    first_view = client.get(f"/api/captures/{capture_id}").json()
    assert first_view["processing_status"] == "routed"
    repeated = client.post(f"/api/captures/{capture_id}/convert", json=body)
    assert repeated.status_code == 201
    second_view = client.get(f"/api/captures/{capture_id}").json()
    assert second_view["event_count"] == first_view["event_count"]
    assert len(service.list_items()) == 1


def test_write_boundary_refuses_specialized_and_grand_todo_placements(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    bad_plan = {
        "items": [{
            "ref": "i1", "title": "do not contaminate posts",
            "primary_board": {
                "board_id": "posts", "domain_id": "posts",
                "card_component": "generic_task",
            },
        }],
        "edges": [],
    }
    refused = client.post("/api/chat/work-items/commit", json=bad_plan)
    assert refused.status_code == 400, refused.text
    assert service.list_items() == []

    item = service.create_item("canonical only")
    refused = client.post(
        f"/api/work-items/{item.work_item_id}/placements",
        json={
            "board_id": "betts_basketball_grand_todo",
            "domain_id": "betts_basketball_grand_todo",
            "card_component": "generic_task", "is_primary": True,
        },
    )
    assert refused.status_code == 400, refused.text
    assert service._store.placements_for(item.work_item_id) == []


def test_generic_transitions_unblock_reopen_restore_and_hold_approval_wall(
    monkeypatch, tmp_path,
):
    _mod, service, client, _configs = _load(monkeypatch, tmp_path)
    item = service.create_item("reversible task")
    service.add_placement(
        item.work_item_id, "tasks", "tasks", is_primary=True,
        card_component="generic_task")
    transitions = client.get("/api/domain/tasks/cards").json()["transitions"]
    assert transitions["Blocked"] == ["In Progress", "Rejected"]
    assert transitions["Done"] == ["In Progress"]
    assert transitions["Rejected"] == ["Backlog"]
    assert transitions["Awaiting Approval"] == []
    assert "Blocked" not in transitions["Done"]

    service.set_status(item.work_item_id, "blocked")
    card = next(
        card for card in client.get("/api/domain/tasks/cards").json()["cards"]
        if card.get("work_item_id") == item.work_item_id)
    moved = client.post(
        "/api/domain/tasks/move",
        json={"card_id": card["card_id"], "status": "In Progress"},
    )
    assert moved.status_code == 200, moved.text
    service.set_status(item.work_item_id, "done")
    moved = client.post(
        "/api/domain/tasks/move",
        json={"card_id": card["card_id"], "status": "In Progress"},
    )
    assert moved.status_code == 200, moved.text


def test_board_module_crash_journal_blocks_reads_until_governed_recovery(
    monkeypatch, tmp_path,
):
    mod, _service, client, configs = _load(monkeypatch, tmp_path)
    original_atomic = mod._atomic_write_bytes
    crashed = False

    def crash_between_configs(path, payload):
        nonlocal crashed
        if path == configs / "domain_surfaces.yaml" and not crashed:
            crashed = True
            raise KeyboardInterrupt("simulated hard stop")
        original_atomic(path, payload)

    monkeypatch.setattr(mod, "_atomic_write_bytes", crash_between_configs)
    with pytest.raises(KeyboardInterrupt, match="simulated hard stop"):
        client.post("/api/board-module", json={"title": "Home Projects"})
    assert mod._config_intent_path().is_file()
    monkeypatch.setattr(mod, "_atomic_write_bytes", original_atomic)

    tracked_paths = [
        configs / "kanban_boards.yaml",
        configs / "domain_surfaces.yaml",
        mod._config_intent_path(),
    ]
    before_get = {path: path.read_bytes() for path in tracked_paths}
    blocked = client.get("/api/domains")
    assert blocked.status_code == 503, blocked.text
    assert "recovery is pending" in blocked.json()["detail"]
    assert {path: path.read_bytes() for path in tracked_paths} == before_get

    # A governed write operation owns recovery. The requested module already
    # exists after roll-forward, so this exact retry reports a conflict only
    # after it has durably reconciled and removed the journal.
    recovery = client.post("/api/board-module", json={"title": "Home Projects"})
    assert recovery.status_code == 409, recovery.text
    assert not mod._config_intent_path().exists()

    recovered = client.get("/api/domains")
    assert recovered.status_code == 200, recovered.text
    assert any(
        domain["domain_id"] == "home_projects"
        for domain in recovered.json()["domains"])
    registry = yaml.safe_load(
        (configs / "kanban_boards.yaml").read_text(encoding="utf-8"))
    assert any(
        board["board_id"] == "home_projects"
        for board in registry["boards"])


def test_frontend_exposes_reviewed_chat_and_capture_routing_flow():
    source = (
        ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"
    ).read_text(encoding="utf-8")
    assert "function TodoRoutingWizard" in source
    assert "Route TODOs" in source
    assert "Route as TODOs" in source
    assert "+ Create a new kanban" in source
    assert "Choose a valid board" in source
    assert "auto-retried; choose Repair" in source
    assert "source_type: \"chat\"" in source
    assert "saved.record.capture_id" in source
    assert "commitChatWork" not in source
    assert "convertCaptureToWork" in source
    assert "Repair / create remaining" in source
    assert "setInterval(refresh" not in source
    all_todos = (
        ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "AllTodosView.tsx"
    ).read_text(encoding="utf-8")
    assert "Completeness verified" in all_todos
    assert "PARTIAL INVENTORY" in all_todos
    assert "Assign / add kanban" in all_todos
    assert "Or create a new kanban" in all_todos
    assert "Unassigned" in all_todos
    assert "Accept creates a maintenance TODO" in all_todos
    assert "window.setTimeout" in all_todos
    assert "Master TODO List" in all_todos
    assert "TODO story" in all_todos
    assert "Immutable raw capture" in all_todos
    assert "buildTodoSections" in all_todos
    assert "General & unassigned" in all_todos
    assert "references unregistered repo" in all_todos
    assert "row.repo_ids.map" in all_todos
    assert "setData(null)" in all_todos
    assert "setInterval" not in all_todos
    assert "recordRoutingCorrection" in source
    assert "routingMode" in source
    assert "fetchDomainSchema().then" in source
    assert "disabled={busy || !boardCreateGate.writable}" in source
    assert "New kanban unavailable" in source
    assert "prepareCapture" in source
    assert "if (prepared[0] && onOpenChat)" in source
    assert "onOpenChat(prepared[0].chat_prompt" in source
    assert "onOpenChat={chatOn ? openChatWithPrompt : undefined}" in source
    assert "onClose();" in source
    assert "Prepare in chat" in source
    assert "Choose destination" in source
    assert "work page-by-page in chat" in source
    assert "I submitted externally — record it" in source
    assert "updateJobSearchCompanyTargets" in source
    assert "updateJobSearchRetention" in source
    assert "furthersProcess" in source
    assert "Add this non-sensitive question to library" in source
    assert "save candidate only" in source
    assert "review for Standing Answers" in source
    assert "add known contact" in source
    assert "check known contacts" in source
    assert "Search phrases only; no named people are invented" in source


def test_current_todo_surface_display_names_are_exact():
    app_source = (
        ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"
    ).read_text(encoding="utf-8")
    assert '{ id: "domains", label: "Kanban Boards" }' in app_source
    assert '{ id: "todos", label: "Master TODO List" }' in app_source
    assert '<div className="nav-section-label">Kanban Boards</div>' in app_source

    config = yaml.safe_load(
        (ROOT / "configs" / "domain_surfaces.yaml").read_text(encoding="utf-8")
    )
    titles = {
        domain["domain_id"]: domain["title"] for domain in config["domains"]
    }
    assert titles["betts_basketball_grand_todo"] == (
        "Betts Grand TODO — Source Tracker"
    )
    assert titles["generic_task"] == "General Todos"


def _without_grand_todo(configs: Path) -> None:
    path = configs / "domain_surfaces.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["domains"] = [
        domain for domain in data["domains"]
        if domain["domain_id"] != "betts_basketball_grand_todo"
    ]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_all_todos_lists_unassigned_and_every_board_link_with_filters(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    unassigned = service.create_item("Unassigned research", kind="research")
    assigned = service.create_item("Placed bug", kind="bug")
    service.add_placement(
        assigned.work_item_id, "tasks", "tasks", is_primary=True,
        card_component="generic_task")

    response = client.get("/api/todos")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completeness"]["complete"] is True
    assert body["completeness"]["emitted_total"] == 2
    assert body["completeness"]["unassigned_total"] == 1
    by_id = {row["work_item_id"]: row for row in body["rows"]}
    assert by_id[unassigned.work_item_id]["status"] == "backlog"
    assert by_id[unassigned.work_item_id]["assigned"] is False
    assert by_id[unassigned.work_item_id]["repo_ids"] == []
    assert by_id[assigned.work_item_id]["repo_ids"] == ["llm_station"]
    assert by_id[assigned.work_item_id]["boards"][0]["href"].startswith("?view=domains")
    assert by_id[assigned.work_item_id]["boards"][0]["repo_ids"] == ["llm_station"]
    assert [repo["repo_id"] for repo in body["registered_repos"]] == [
        "llm_station", "betts_basketball",
    ]

    assert client.get("/api/todos", params={"assigned": "false"}).json()[
        "filtered_total"] == 1
    assert client.get("/api/todos", params={"kind": "bug"}).json()[
        "rows"][0]["work_item_id"] == assigned.work_item_id
    assert client.get("/api/todos", params={"board_id": "tasks"}).json()[
        "filtered_total"] == 1
    assert client.get("/api/todos", params={"q": "research"}).json()[
        "filtered_total"] == 1
    paged = client.get("/api/todos", params={"limit": 1}).json()
    assert paged["inventory_total"] == 2
    assert paged["has_more"] is True
    assert set(paged["filter_catalogs"]["kinds"]) == {"bug", "research"}
    assert paged["completeness"]["emitted_total"] == 2


def test_all_todos_attributes_grand_todo_cards_to_registered_betts_repo(
    monkeypatch, tmp_path,
):
    mod, _service, client, _configs = _load(monkeypatch, tmp_path)
    from command_center.boards.command_center_provider import CommandCenterBoardProvider

    provider = CommandCenterBoardProvider(
        board_id="betts_basketball_grand_todo",
        event_log=mod.EventLog(mod.KANBAN_EVENT_LOG),
        store_dir=mod.BOARD_STORE_DIR,
    )
    provider.upsert_card("grand-todo-de-1", {
        "title": "Preserve the canonical Betts task",
        "description": "The source-backed task remains intact.",
        "status": "Backlog",
        "item_id": "DE-1",
        "source_kind": "tracked_item",
    })

    body = client.get("/api/todos").json()
    row = next(
        candidate for candidate in body["rows"]
        if candidate["todo_id"] == (
            "card:betts_basketball_grand_todo:grand-todo-de-1"
        )
    )
    assert row["repo_ids"] == ["betts_basketball"]
    assert row["boards"] == [{
        "board_id": "betts_basketball_grand_todo",
        "domain_id": "betts_basketball_grand_todo",
        "is_primary": True,
        "placement_id": None,
        "source_projection": False,
        "href": (
            "?view=domains&domain=betts_basketball_grand_todo"
            "&card=grand-todo-de-1"
        ),
        "repo_ids": ["betts_basketball"],
    }]


def test_assign_unconverted_capture_is_idempotent_and_preserves_source(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    captured = client.post("/api/captures", json={
        "raw_content": "Plan the garden irrigation",
        "requested_mode": "create_task",
    }).json()
    capture_id = captured["record"]["capture_id"]
    todo_id = f"capture:{capture_id}"
    assert any(row["todo_id"] == todo_id and not row["assigned"]
               for row in client.get("/api/todos").json()["rows"])

    first = client.post(f"/api/todos/{todo_id}/assign", json={
        "board_id": "tasks", "domain_id": "tasks",
        "canonical_title": "Plan the garden irrigation",
        "canonical_description": "Organize the irrigation plan.",
        "canonical_kind": "todo",
        "confirm_canonical_fields": True,
    })
    assert first.status_code == 200, first.text
    second = client.post(f"/api/todos/{todo_id}/assign", json={
        "board_id": "tasks", "domain_id": "tasks",
        "canonical_title": "Plan the garden irrigation",
        "canonical_description": "Organize the irrigation plan.",
        "canonical_kind": "todo",
        "confirm_canonical_fields": True,
    })
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "already_assigned"
    assert len(service.list_items()) == 1
    assert len(service._store.list_placements()) == 1
    assert client.get(f"/api/captures/{capture_id}").json()[
        "processing_status"] == "routed"
    rows = client.get("/api/todos").json()["rows"]
    assert len([row for row in rows if row["source_id"] == capture_id]) == 1


def test_assign_requires_explicit_canonical_fields_and_never_promotes_raw_source(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    raw = "RAW FIRST LINE\nRAW body is source, not organized text."
    capture_id = client.post("/api/captures", json={
        "raw_content": raw, "requested_mode": "create_task",
    }).json()["record"]["capture_id"]
    endpoint = f"/api/todos/capture:{capture_id}/assign"

    refused = client.post(endpoint, json={
        "board_id": "tasks", "domain_id": "tasks",
    })
    assert refused.status_code == 400
    assert service.list_items() == []

    accepted = client.post(endpoint, json={
        "board_id": "tasks", "domain_id": "tasks",
        "canonical_title": "Human-confirmed irrigation work",
        "canonical_description": "A separately organized description.",
        "canonical_kind": "project",
        "confirm_canonical_fields": True,
    })
    assert accepted.status_code == 200, accepted.text
    [item] = service.list_items()
    assert (item.title, item.description, item.kind) == (
        "Human-confirmed irrigation work",
        "A separately organized description.",
        "project",
    )
    assert client.get(f"/api/captures/{capture_id}").json()["record"][
        "raw_content"
    ] == raw


def test_routed_capture_conflict_is_detected_before_assignment_or_conversion_writes(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    capture_id = client.post("/api/captures", json={
        "raw_content": "Already routed elsewhere",
        "requested_mode": "create_task",
    }).json()["record"]["capture_id"]
    mod._get_capture_service().mark_converted(
        capture_id, ["W-foreign"], conversation_id="chat-foreign",
    )
    assignment = client.post(f"/api/todos/capture:{capture_id}/assign", json={
        "board_id": "tasks", "domain_id": "tasks",
        "canonical_title": "Must not be created",
        "canonical_description": "Must not be created",
        "canonical_kind": "todo",
        "confirm_canonical_fields": True,
    })
    assert assignment.status_code == 409
    assert service.list_items() == []
    assert service._store.list_placements() == []

    conversion = client.post(f"/api/captures/{capture_id}/convert", json={
        "items": [{
            "ref": "i1",
            "title": "Must not be converted",
            "kind": "todo",
            "description": "",
            "primary_board": {
                "board_id": "tasks",
                "domain_id": "tasks",
                "card_component": "generic_task",
            },
        }],
        "edges": [],
        "conversation_id": "chat-new",
    })
    assert conversion.status_code == 409
    assert service.list_items() == []
    assert service._store.list_placements() == []


def test_assign_direct_board_todo_materializes_once_and_keeps_original_card(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    from command_center.boards.command_center_provider import CommandCenterBoardProvider

    provider = CommandCenterBoardProvider(
        board_id="tasks", event_log=mod.EventLog(mod.KANBAN_EVENT_LOG),
        store_dir=mod.BOARD_STORE_DIR)
    provider.upsert_card("legacy-1", {
        "title": "Preserve legacy task", "description": "Original remains canonical"})
    todo_id = "card:tasks:legacy-1"
    before = client.get("/api/todos").json()
    assert any(row["todo_id"] == todo_id for row in before["rows"])
    same_source = client.post(f"/api/todos/{todo_id}/assign", json={
        "board_id": "tasks", "domain_id": "tasks",
    })
    assert same_source.status_code == 200
    assert same_source.json()["status"] == "already_assigned"
    assert service.list_items() == []

    assigned = client.post(f"/api/todos/{todo_id}/assign", json={
        "new_board_title": "House Projects",
        "canonical_title": "Preserve legacy task",
        "canonical_description": "Original remains canonical",
        "canonical_kind": "todo",
        "confirm_canonical_fields": True,
    })
    assert assigned.status_code == 200, assigned.text
    retry = client.post(f"/api/todos/{todo_id}/assign", json={
        "new_board_title": "House Projects",
        "canonical_title": "Preserve legacy task",
        "canonical_description": "Original remains canonical",
        "canonical_kind": "todo",
        "confirm_canonical_fields": True,
    })
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "already_assigned"
    assert provider.list_cards()[0]["title"] == "Preserve legacy task"
    assert len(service.list_items()) == 1
    assert service.list_items()[0].packet_id == "todo-source:tasks:legacy-1"
    assert len(service._store.list_placements()) == 1
    assert any(board["board_id"] == "house_projects"
               for board in client.get("/api/todos").json()["routable_boards"])
    materialized = next(row for row in client.get("/api/todos").json()["rows"]
                        if row["source_id"] == "tasks:legacy-1")
    assert {board["board_id"] for board in materialized["boards"]} == {
        "tasks", "house_projects"}
    assert any(board.get("source_projection") is True
               for board in materialized["boards"])
    work_id = service.list_items()[0].work_item_id
    back_to_source = client.post(f"/api/todos/work:{work_id}/assign", json={
        "board_id": "tasks", "domain_id": "tasks",
    })
    assert back_to_source.status_code == 200
    assert back_to_source.json()["status"] == "already_assigned"
    assert len(service._store.list_placements()) == 1


@pytest.mark.parametrize("params,expected", [
    ({"source": "work_graph"}, 1),
    ({"status": "done"}, 1),
    ({"kind": "maintenance", "assigned": "true"}, 1),
    ({"board_id": "tasks", "q": "rotate"}, 1),
    ({"board_id": "other"}, 0),
])
def test_all_todo_filter_combinations_are_stable(
    monkeypatch, tmp_path, params, expected,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    item = service.create_item("Rotate backup media", kind="maintenance")
    service.add_placement(
        item.work_item_id, "tasks", "tasks", is_primary=True,
        card_component="generic_task")
    service.set_status(item.work_item_id, "done")
    response = client.get("/api/todos", params=params)
    assert response.status_code == 200, response.text
    assert response.json()["filtered_total"] == expected


def test_board_remove_is_archive_only_and_human_can_restore(
    monkeypatch, tmp_path,
):
    _mod, _service, client, configs = _load(monkeypatch, tmp_path)
    board_id = _create_board(client, "Never Delete Me")
    archived = client.delete(f"/api/domain-schema/{board_id}")
    assert archived.status_code == 200, archived.text
    saved = yaml.safe_load(
        (configs / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    row = next(domain for domain in saved["domains"]
               if domain["domain_id"] == board_id)
    assert row["archived"] is True
    assert all(board["board_id"] != board_id
               for board in client.get("/api/todos").json()["routable_boards"])
    refused = client.post(f"/api/domain/{board_id}/move", json={
        "card_id": "anything", "status": "Ready"})
    assert refused.status_code == 409
    assert "read-only" in refused.json()["detail"]

    restored = client.post(f"/api/domain-schema/{board_id}/restore")
    assert restored.status_code == 200, restored.text
    assert any(board["board_id"] == board_id
               for board in client.get("/api/todos").json()["routable_boards"])


def test_maintenance_accept_creates_one_review_todo_and_reject_changes_nothing(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    _create_board(client, "General Todos")
    _create_board(client, "Unused Planning")

    scanned = client.post("/api/kanban-maintenance/scan")
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["destructive_actions_performed"] is False
    open_rows = scanned.json()["open"]
    accepted_row = next(row for row in open_rows if "unused_planning" in row["board_ids"])
    rejected_row = next(row for row in open_rows
                        if row["suggestion_id"] != accepted_row["suggestion_id"])

    rejected = client.post(
        f"/api/kanban-maintenance/{rejected_row['suggestion_id']}/decision",
        json={"decision": "reject", "reason_note": "keep this board"},
    )
    assert rejected.status_code == 200, rejected.text
    assert service.list_items() == []

    endpoint = f"/api/kanban-maintenance/{accepted_row['suggestion_id']}/decision"
    first = client.post(endpoint, json={"decision": "accept"})
    retry = client.post(endpoint, json={"decision": "accept"})
    assert first.status_code == retry.status_code == 200
    assert first.json()["destructive_actions_performed"] is False
    items = [item for item in service.list_items() if item.kind == "maintenance"]
    assert len(items) == 1
    placements = service._store.placements_for(items[0].work_item_id)
    assert len(placements) == 1
    assert placements[0].board_id == "general_todos"
    saved = yaml.safe_load(
        (configs / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    unused = next(domain for domain in saved["domains"]
                  if domain["domain_id"] == "unused_planning")
    assert unused.get("archived") is not True
    assert client.get("/api/kanban-maintenance").json()["history"]


def test_concurrent_assign_retry_creates_one_work_item_and_one_placement(
    monkeypatch, tmp_path,
):
    from concurrent.futures import ThreadPoolExecutor

    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    capture_id = client.post("/api/captures", json={
        "raw_content": "Concurrent assignment",
        "requested_mode": "create_task",
    }).json()["record"]["capture_id"]
    endpoint = f"/api/todos/capture:{capture_id}/assign"

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(
            lambda _: client.post(endpoint, json={
                "board_id": "tasks", "domain_id": "tasks",
                "canonical_title": "Concurrent assignment",
                "canonical_description": "Confirmed concurrent assignment.",
                "canonical_kind": "todo",
                "confirm_canonical_fields": True,
            }), range(6)))
    assert all(response.status_code == 200 for response in responses)
    assert len(service.list_items()) == 1
    assert len(service._store.list_placements()) == 1
    assert sorted(response.json()["status"] for response in responses) == [
        "already_assigned", "already_assigned", "already_assigned",
        "already_assigned", "already_assigned", "assigned"]


def test_new_board_slug_collision_requires_explicit_existing_board_choice(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    _create_board(client, "C")
    item = service.create_item("Choose intentionally")
    response = client.post(f"/api/todos/work:{item.work_item_id}/assign", json={
        "new_board_title": "C++",
    })
    assert response.status_code == 409
    assert "choose that existing board explicitly" in response.json()["detail"]
    assert service._store.placements_for(item.work_item_id) == []


def test_all_todos_reports_partial_source_failure_without_showing_false_empty(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    service.create_item("Still visible")
    original = mod._domain_cards

    def fail_one(spec):
        if spec["domain_id"] == "tasks":
            raise RuntimeError(
                "SENTINEL_PRIVATE_PROVIDER_TEXT C:\\private\\board-store",
            )
        return original(spec)

    monkeypatch.setattr(mod, "_domain_cards", fail_one)
    body = client.get("/api/todos").json()
    assert body["completeness"]["complete"] is False
    assert body["completeness"]["error_count"] == 1
    assert body["completeness"]["errors"][0]["source"] == "tasks"
    assert body["completeness"]["errors"][0]["code"] == "source_unavailable"
    assert body["completeness"]["errors"][0]["message"] == (
        "board TODO inventory is unavailable"
    )
    assert "SENTINEL_PRIVATE_PROVIDER_TEXT" not in str(body)
    assert "private\\board-store" not in str(body)
    assert any(row["title"] == "Still visible" for row in body["rows"])


def test_all_todos_fails_loud_for_unregistered_board_repo_mapping(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    service.create_item("Never guess repository ownership")
    registry_path = configs / "kanban_boards.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    next(board for board in registry["boards"] if board["board_id"] == "tasks")[
        "repo_ids"
    ] = ["not_registered"]
    registry_path.write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    response = client.get("/api/todos")
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "kanban board 'tasks' references unregistered repos: not_registered"
    )


def test_todo_detail_preserves_raw_capture_and_plural_exact_work_links(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    created = client.post("/api/captures", json={
        "raw_content": "Original wording stays immutable",
        "requested_mode": "create_task",
        "conversation_id": "chat-source-1",
    }).json()
    capture_id = created["record"]["capture_id"]

    before = client.get(f"/api/todos/capture:{capture_id}")
    assert before.status_code == 200, before.text
    assert before.headers["cache-control"] == "no-store"
    assert before.json()["requested_identity"]["state"] == "not_materialized"
    assert before.json()["raw_captures"][0]["record"]["raw_content"] == (
        "Original wording stays immutable"
    )
    inventory_row = next(
        row for row in client.get("/api/todos").json()["rows"]
        if row["todo_id"] == f"capture:{capture_id}"
    )
    assert inventory_row["title"] is None
    assert inventory_row["kind"] is None
    assert inventory_row["raw_preview"] == "Original wording stays immutable"
    assert inventory_row["status"] is None
    assert inventory_row["integrity"]["missing_fields"] == [
        "title", "kind", "canonical_status",
    ]

    first = service.create_item("First exact child")
    second = service.create_item("Second exact child")
    from command_center.intake import CaptureEvent
    mod._get_capture_service()._store.append_event(CaptureEvent(
        capture_id=capture_id,
        ts="2026-07-16T10:00:00+00:00",
        kind="link",
        payload={
            "work_item_ids": [first.work_item_id, second.work_item_id],
            "conversation_id": "chat-route-1",
        },
    ))

    detail = client.get(f"/api/todos/capture:{capture_id}").json()
    assert detail["requested_identity"]["state"] == "folded_into_work_items"
    assert detail["canonical_item"] is None
    assert {row["work_item_id"] for row in detail["linked_work_items"]} == {
        first.work_item_id, second.work_item_id,
    }
    assert {row["conversation_id"] for row in detail["conversations"]} == {
        "chat-source-1", "chat-route-1",
    }
    rows = client.get("/api/todos").json()["rows"]
    assert not any(row["todo_id"] == f"capture:{capture_id}" for row in rows)


def test_work_todo_story_has_removed_history_exact_routing_and_atomic_edit(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    capture = client.post("/api/captures", json={
        "raw_content": "Raw source must never be rewritten",
        "requested_mode": "create_task",
        "conversation_id": "chat-work-1",
    }).json()
    capture_id = capture["record"]["capture_id"]
    item = service.create_item(
        "Canonical work", description="organized before", capture_id=capture_id,
        conversation_id="chat-work-1", mission_id="M-exact",
    )
    primary = service.add_placement(
        item.work_item_id, "tasks", "tasks", is_primary=True,
        card_component="generic_task",
    )
    secondary = service.add_placement(
        item.work_item_id, "tasks", "tasks-secondary",
        card_component="generic_task",
    )
    service.remove_placement(secondary.placement_id)
    child = service.create_item("Child task")
    edge = service.add_edge(item.work_item_id, child.work_item_id, "parent_of")
    service.remove_edge(edge.edge_id)
    service.set_status(item.work_item_id, "archived")
    service.set_status(item.work_item_id, "backlog")
    mod._get_capture_service().mark_converted(
        capture_id, [item.work_item_id], conversation_id="chat-work-1",
    )
    exact = client.post("/api/routing-corrections", json={
        "title": "Canonical work",
        "capture_id": capture_id,
        "conversation_id": "chat-work-1",
        "suggested_board_id": "other",
        "chosen_board_id": "tasks",
    })
    assert exact.status_code == 201
    client.post("/api/routing-corrections", json={
        "title": "Canonical work",
        "capture_id": "different-capture",
        "conversation_id": "chat-work-1",
        "chosen_board_id": "tasks",
    })
    monkeypatch.setattr(mod, "mission", lambda mission_id: {
        "mission": {"id": mission_id, "status": "done"},
        "events": [
            {
                "ts": "2026-07-16T10:59:00+00:00",
                "kind": "mission.verification",
                "payload": {
                    "detail": {
                        "evidence_refs": ["evidence://exact-pass"],
                    },
                },
            },
            {
                "ts": "2026-07-16T11:00:00+00:00",
                "kind": "mission.completion_verdict",
                "payload": {
                    "status": "PASS",
                    "reasons": [],
                    "evidence_refs": ["evidence://verdict"],
                },
            },
        ],
        "approvals": [],
    })

    detail_response = client.get(f"/api/todos/work:{item.work_item_id}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["canonical_item"]["work_item_id"] == item.work_item_id
    assert {row["active"] for row in detail["placements"]} == {True, False}
    assert all(row["board_event_join_state"] == "not_linked"
               for row in detail["placements"])
    assert detail["relationships"][0]["active"] is False
    assert [row["correction_id"] for row in detail["routing"]["corrections"]] == [
        exact.json()["correction_id"]
    ]
    assert detail["missions"][0]["completion_state"] == "recorded"
    assert {row["evidence_ref"] for row in detail["completion_evidence"]} == {
        "evidence://exact-pass", "evidence://verdict",
    }
    assert detail["completeness"]["board_event_join_state"] == "not_linked"
    archive_statuses = [
        row["payload"]["status"]
        for row in detail["archive_history"]
        if row["kind"] == "status"
    ]
    assert archive_statuses == ["archived", "backlog"]
    assert {row["kind"] for row in detail["archive_history"]} >= {
        "placement_added", "placement_removed", "edge_added", "edge_removed",
    }
    assert sum(row["kind"] == "placement_removed" for row in detail["timeline"]) == 1
    assert sum(row["kind"] == "edge_removed" for row in detail["timeline"]) == 1

    updated = client.put(
        f"/api/work-items/{item.work_item_id}/description",
        json={
            "description": "organized after",
            "expected_updated_at": detail["canonical_item"]["updated_at"],
            "expected_description": "organized before",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.headers["cache-control"] == "no-store"
    assert updated.json()["item"]["description"] == "organized after"
    assert client.get(f"/api/captures/{capture_id}").json()["record"]["raw_content"] == (
        "Raw source must never be rewritten"
    )
    stale = client.put(
        f"/api/work-items/{item.work_item_id}/description",
        json={
            "description": "stale overwrite",
            "expected_updated_at": item.updated_at,
            "expected_description": "organized before",
        },
    )
    assert stale.status_code == 409
    assert stale.headers["cache-control"] == "no-store"
    assert service.get_item(item.work_item_id).description == "organized after"
    assert primary.placement_id in {row["placement_id"] for row in detail["placements"]}


def test_grand_todo_detail_reads_exact_revisions_conflicts_and_card_events(
    monkeypatch, tmp_path,
):
    mod, _service, client, _configs = _load(monkeypatch, tmp_path)
    from command_center.boards.command_center_provider import CommandCenterBoardProvider

    provider = CommandCenterBoardProvider(
        board_id="betts_basketball_grand_todo",
        event_log=mod.EventLog(mod.KANBAN_EVENT_LOG),
        store_dir=mod.BOARD_STORE_DIR,
    )
    provider.upsert_card("grand:detail/1", {
        "title": "Source tracked story",
        "description": "Current exact source text",
        "status": "Ready",
        "source_kind": "tracked_item",
        "source_revisions": [{
            "sha256": "sha-one", "captured_at": "2026-07-15T00:00:00+00:00",
            "status": "Backlog", "raw_markdown": "original markdown",
        }],
        "sync_conflicts": [{
            "captured_at": "2026-07-16T00:00:00+00:00",
            "source_sha256": "sha-two", "board_status": "Ready",
        }],
        "active_sync_conflict": {"source_sha256": "sha-two"},
    })
    mod.emit_event(
        mod.EventLog(mod.KANBAN_EVENT_LOG),
        action="stage_card", board_id="betts_basketball_grand_todo",
        card_id="grand:detail/1", source_surface="internal_ui",
        actor_type="human", status_before="Backlog", status_after="Ready",
    )
    todo_id = "card:betts_basketball_grand_todo:grand:detail/1"
    response = client.get(f"/api/todos/{todo_id}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["requested_identity"]["state"] == "not_materialized"
    assert detail["source"]["audit"]["source_revisions"][0]["raw_markdown"] == (
        "original markdown"
    )
    assert detail["source"]["audit"]["sync_conflicts"][0]["source_sha256"] == "sha-two"
    assert len(detail["board_events"]) == 1
    assert detail["board_events"][0]["card_id"] == "grand:detail/1"
    assert detail["repositories"][0]["repo_id"] == "betts_basketball"

    provider.upsert_card("grand-malformed", {
        "title": "Malformed history stays visible",
        "status": "Backlog",
        "source_kind": "tracked_item",
        "source_revisions": {"not": "a list"},
    })
    malformed = client.get(
        "/api/todos/card:betts_basketball_grand_todo:grand-malformed"
    ).json()
    assert malformed["completeness"]["complete"] is False
    assert malformed["source"]["audit"]["source_revisions"] is None
    assert malformed["completeness"]["errors"][0]["code"] == (
        "malformed_audit_history"
    )

    provider.upsert_card("grand-bad-timestamp", {
        "title": "Malformed timestamp remains raw",
        "status": "Backlog",
        "source_kind": "tracked_item",
        "source_revisions": [{
            "sha256": "sha-bad", "captured_at": {"not": "a timestamp"},
            "raw_markdown": "preserve this exact malformed record",
        }],
    })
    bad_timestamp = client.get(
        "/api/todos/card:betts_basketball_grand_todo:grand-bad-timestamp"
    )
    assert bad_timestamp.status_code == 200, bad_timestamp.text
    bad_body = bad_timestamp.json()
    assert bad_body["source"]["audit"]["source_revisions"][0]["malformed"] is True
    assert bad_body["source"]["audit"]["source_revisions"][0]["raw"][
        "raw_markdown"
    ] == "preserve this exact malformed record"
    assert any(error["code"] == "malformed_source"
               for error in bad_body["completeness"]["errors"])
    assert not any(row["source"] == "grand_todo"
                   for row in bad_body["timeline"])


def test_private_todo_and_work_routes_are_no_store_on_errors(monkeypatch, tmp_path):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    item = service.create_item("privacy contract")
    assert client.get("/api/todos").headers["cache-control"] == "no-store"
    missing = client.get("/api/todos/work:missing")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"
    invalid = client.put(
        f"/api/work-items/{item.work_item_id}/description", json={"description": 4},
    )
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"
    assert invalid.json()["detail"] != "invalid private job-search memory request"
    assert isinstance(invalid.json()["detail"], list)
    assert client.get("/api/work-graph").headers["cache-control"] == "no-store"


def test_unhandled_todo_failure_is_sanitized_and_no_store(
    monkeypatch, tmp_path,
):
    mod, _service, client, _configs = _load(monkeypatch, tmp_path)

    def explode(_todo_id):
        raise RuntimeError("private sentinel must not escape")

    monkeypatch.setattr(mod, "_todo_detail", explode)
    response = client.get("/api/todos/work:anything")
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "private history request failed"}
    assert "sentinel" not in response.text


def test_wrong_work_item_url_cannot_remove_another_items_placement(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    owner = service.create_item("placement owner")
    other = service.create_item("different item")
    placement = service.add_placement(
        owner.work_item_id, "tasks", "tasks", is_primary=True,
    )
    response = client.delete(
        f"/api/work-items/{other.work_item_id}/placements/{placement.placement_id}"
    )
    assert response.status_code == 409
    assert service._store.get_placement(placement.placement_id).removed_at is None
    assert service.get_item(owner.work_item_id).primary_board_id == "tasks"


def test_assignment_rejects_ambiguous_source_identity_and_divergent_retry(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    capture_id = client.post("/api/captures", json={
        "raw_content": "Ambiguous source", "requested_mode": "create_task",
    }).json()["record"]["capture_id"]
    service.create_item("First", capture_id=capture_id)
    service.create_item("Second", capture_id=capture_id)
    ambiguous = client.post(f"/api/todos/capture:{capture_id}/assign", json={
        "board_id": "tasks", "domain_id": "tasks",
        "canonical_title": "First", "canonical_description": "",
        "canonical_kind": "todo", "confirm_canonical_fields": True,
    })
    assert ambiguous.status_code == 409
    assert service._store.list_placements() == []

    clean_capture = client.post("/api/captures", json={
        "raw_content": "Exact retry source", "requested_mode": "create_task",
    }).json()["record"]["capture_id"]
    endpoint = f"/api/todos/capture:{clean_capture}/assign"
    exact = {
        "board_id": "tasks", "domain_id": "tasks",
        "canonical_title": "Exact canonical title",
        "canonical_description": "Exact organized description.",
        "canonical_kind": "todo", "confirm_canonical_fields": True,
    }
    assert client.post(endpoint, json=exact).status_code == 200
    divergent = client.post(endpoint, json={
        **exact, "canonical_description": "Divergent retry text.",
    })
    assert divergent.status_code == 409
    matched = [item for item in service.list_items() if item.capture_id == clean_capture]
    assert len(matched) == 1
    assert matched[0].description == "Exact organized description."


def test_inventory_reports_dangling_capture_and_projection_provenance(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    from command_center.boards.command_center_provider import CommandCenterBoardProvider
    from command_center.intake import CaptureEvent

    live = service.create_item("Live linked item")
    capture_id = client.post("/api/captures", json={
        "raw_content": "Raw capture with one dangling link",
        "requested_mode": "create_task",
    }).json()["record"]["capture_id"]
    mod._get_capture_service()._store.append_event(CaptureEvent(
        capture_id=capture_id,
        ts="2026-07-16T00:01:00+00:00",
        kind="link",
        payload={
            "work_item_ids": [live.work_item_id, "W-missing"],
            "conversation_id": "chat-links",
        },
    ))
    provider = CommandCenterBoardProvider(
        board_id="tasks",
        event_log=mod.EventLog(mod.KANBAN_EVENT_LOG),
        store_dir=mod.BOARD_STORE_DIR,
    )
    provider.upsert_card("dangling-projection", {
        "title": "Dangling projection remains visible",
        "status": "Backlog",
        "projection_source": "work_graph",
        "work_item_id": "W-not-present",
    })
    response = client.get("/api/todos")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completeness"]["complete"] is False
    assert {error["code"] for error in body["completeness"]["errors"]} >= {
        "dangling_work_item_link", "dangling_work_graph_projection",
    }
    assert any(row["todo_id"] == f"capture:{capture_id}" for row in body["rows"])
    assert any(row["todo_id"] == "card:tasks:dangling-projection"
               for row in body["rows"])


def test_same_board_multi_domain_links_keep_each_exact_destination(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    item = service.create_item("same physical board, two domain views")
    service.add_placement(item.work_item_id, "tasks", "tasks", is_primary=True)
    service.add_placement(item.work_item_id, "tasks", "tasks-secondary")
    row = next(row for row in client.get("/api/todos").json()["rows"]
               if row["work_item_id"] == item.work_item_id)
    by_domain = {board["domain_id"]: board["href"] for board in row["boards"]}
    assert "domain=tasks&" in by_domain["tasks"]
    assert "domain=tasks-secondary&" in by_domain["tasks-secondary"]


def test_story_keeps_board_archive_reversal_and_incoming_edge_addition(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    from command_center.boards.command_center_provider import CommandCenterBoardProvider

    provider = CommandCenterBoardProvider(
        board_id="tasks",
        event_log=mod.EventLog(mod.KANBAN_EVENT_LOG),
        store_dir=mod.BOARD_STORE_DIR,
    )
    provider.upsert_card("archive-story", {
        "title": "Archive reversal source", "status": "Ready",
    })
    event_log = mod.EventLog(mod.KANBAN_EVENT_LOG)
    mod.emit_event(
        event_log, action="finish_todo", board_id="tasks",
        card_id="archive-story", source_surface="internal_ui", actor_type="human",
        status_before="Ready", status_after="Archived",
    )
    mod.emit_event(
        event_log, action="stage_card", board_id="tasks",
        card_id="archive-story", source_surface="internal_ui", actor_type="human",
        status_before="Archived", status_after="Ready",
    )
    response = client.get("/api/todos/card:tasks:archive-story")
    assert response.status_code == 200, response.text
    source_detail = response.json()
    board_statuses = [
        row["payload"]["status_after"]
        for row in source_detail["archive_history"]
        if row["source"] == "board"
    ]
    assert board_statuses == ["Archived", "Ready"]

    parent = service.create_item("Incoming parent")
    child = service.create_item("Incoming child")
    edge = service.add_edge(parent.work_item_id, child.work_item_id, "parent_of")
    child_detail = client.get(f"/api/todos/work:{child.work_item_id}").json()
    assert any(
        row["kind"] == "edge_added" and row["ref"] == edge.edge_id
        for row in child_detail["archive_history"]
    )


def test_projected_board_card_assignment_reuses_canonical_work(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    item = service.create_item("projection identity")
    service.add_placement(
        item.work_item_id, "tasks", "tasks", is_primary=True,
    )
    before_ids = {candidate.work_item_id for candidate in service.list_items()}

    response = client.post(
        f"/api/todos/card:tasks:work-{item.work_item_id}/assign",
        json={"new_board_title": "Second Home"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["todo"]["work_item_id"] == item.work_item_id
    assert {candidate.work_item_id for candidate in service.list_items()} == before_ids


def test_assignment_preflights_missing_work_before_new_board_write(
    monkeypatch, tmp_path,
):
    _mod, _service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    registry = (configs / "kanban_boards.yaml").read_bytes()
    domains = (configs / "domain_surfaces.yaml").read_bytes()

    response = client.post(
        "/api/todos/work:missing/assign",
        json={"new_board_title": "Must Not Exist"},
    )

    assert response.status_code == 404
    assert (configs / "kanban_boards.yaml").read_bytes() == registry
    assert (configs / "domain_surfaces.yaml").read_bytes() == domains


def test_workitem_missing_capture_and_card_sources_make_inventory_partial(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    capture_backed = service.create_item(
        "missing capture source", capture_id="capture-gone",
    )
    card_backed = service.create_item(
        "missing card source", packet_id="todo-source:tasks:card-gone",
    )

    body = client.get("/api/todos").json()

    assert body["completeness"]["complete"] is False
    error_sources = {error["source"] for error in body["completeness"]["errors"]}
    assert {"capture:capture-gone", "card:tasks:card-gone"} <= error_sources
    card_row = next(
        row for row in body["rows"]
        if row["work_item_id"] == card_backed.work_item_id
    )
    assert not any(board.get("source_projection") for board in card_row["boards"])
    assert any(
        row["work_item_id"] == capture_backed.work_item_id for row in body["rows"]
    )


def test_malformed_capture_link_is_partial_for_unrelated_work_story(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    item = service.create_item("unrelated canonical work")
    capture = client.post("/api/captures", json={
        "raw_content": "malformed link source", "requested_mode": "create_task",
    }).json()["record"]
    from command_center.intake import CaptureEvent
    mod._get_capture_service()._store.append_event(CaptureEvent(
        capture_id=capture["capture_id"], ts="t", kind="link",
        payload={"work_item_ids": [{"not": "an id"}], "conversation_id": "chat"},
    ))

    response = client.get(f"/api/todos/work:{item.work_item_id}")

    assert response.status_code == 200, response.text
    assert response.json()["completeness"]["complete"] is False
    assert any(
        error["code"] == "malformed_link_event"
        for error in response.json()["completeness"]["errors"]
    )


def test_invalid_mission_evidence_is_not_reported_as_recorded(
    monkeypatch, tmp_path,
):
    mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    item = service.create_item("invalid mission evidence", mission_id="M-invalid")
    monkeypatch.setattr(mod, "mission", lambda _mission_id: {
        "mission": {"id": "M-invalid", "status": "done"},
        "events": [{
            "ts": "2026-07-16T11:00:00+00:00",
            "kind": "mission.completion_verdict",
            "payload": {"status": "PASS", "reasons": [], "evidence_refs": [{}]},
        }],
        "approvals": [],
    })

    detail = client.get(f"/api/todos/work:{item.work_item_id}").json()

    assert detail["completeness"]["complete"] is False
    assert detail["missions"][0]["completion_state"] == "malformed_source"
    assert detail["completion_evidence"] == []


def test_all_private_capture_and_work_history_reads_are_no_store(
    monkeypatch, tmp_path,
):
    _mod, service, client, configs = _load(monkeypatch, tmp_path)
    _without_grand_todo(configs)
    capture_id = client.post("/api/captures", json={
        "raw_content": "private raw wording", "requested_mode": "create_task",
    }).json()["record"]["capture_id"]
    item = service.create_item("private work")
    other = service.create_item("private related work")
    for path in (
        f"/api/captures/{capture_id}",
        "/api/captures",
        "/api/intake/inbox",
        f"/api/work/{item.work_item_id}/resolve",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert response.headers["cache-control"] == "no-store", path
    edge = client.post("/api/work-edges", json={
        "from_work_item_id": item.work_item_id,
        "to_work_item_id": other.work_item_id,
        "relation": "related_to",
    })
    assert edge.status_code == 201, edge.text
    assert edge.headers["cache-control"] == "no-store"
