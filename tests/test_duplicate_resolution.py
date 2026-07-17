"""Duplicate checking + resolution endpoints: side-effect-free checks, and
explicit human resolutions (reuse / occurrence / reopen / discard) that are
recorded append-only and never hard-delete anything.

Hermetic: temp configs, in-memory graph/captures, temp board store.
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
    "backlog": "Backlog", "ready": "Ready", "in_progress": "In Progress",
    "done": "Done", "blocked": "Blocked", "rejected": "Rejected",
    "awaiting_approval": "Awaiting Approval",
}
COLUMNS = list(MAPPING.values())
ACTIONS = {
    "Backlog": "add_mission_card", "Ready": "stage_card",
    "In Progress": "start_todo", "Done": "finish_todo",
    "Blocked": "block_card", "Rejected": "reject_card",
    "Awaiting Approval": "stage_card",
}
ALLOWED = ["add_mission_card", "stage_card", "start_todo", "finish_todo",
           "block_card", "reject_card"]
WALL = ["approve_card", "merge", "deploy", "delete_card", "delete_board"]


def _seed_configs(configs: Path) -> None:
    configs.mkdir(parents=True)
    board = {
        "board_id": "tasks", "provider": "command_center_ui",
        "workspace_ref": "self", "board_ref": "tasks",
        "execution_scope": "life", "repo_ids": [],
        "status_mapping": MAPPING,
        "required_fields": ["MissionID", "RepoID", "Risk", "LastSync",
                            "Section"],
        "allowed_agent_verbs": ALLOWED, "forbidden_agent_verbs": WALL,
        "blockers": [],
    }
    domain = {
        "domain_id": "tasks", "title": "Tasks",
        "card_component": "generic_task", "source": "board_store",
        "board_id": "tasks", "columns": COLUMNS,
        "column_actions": {lane: ACTIONS[lane] for lane in COLUMNS},
        "summary_fields": [{"name": "title", "label": "Title"}],
        "drawer_fields": [{"name": "description", "label": "Description"}],
        "allowed_actions": ALLOWED,
        "empty_state": {"title": "Empty", "hint": "Route a TODO here."},
    }
    (configs / "kanban_boards.yaml").write_text(
        yaml.safe_dump({"schema_version": "command-center.kanban-boards.v1",
                        "boards": [board]}, sort_keys=False),
        encoding="utf-8")
    (configs / "domain_surfaces.yaml").write_text(
        yaml.safe_dump({"schema_version": "command-center.domain-surfaces.v1",
                        "domains": [domain]}, sort_keys=False),
        encoding="utf-8")


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    configs = tmp_path / "configs"
    _seed_configs(configs)
    spec = importlib.util.spec_from_file_location(
        "agent_kanban_ui_duplicate_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_duplicate_test"] = mod
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
    service = mod._get_workgraph_service()
    mod._get_telemetry_service()
    monkeypatch.setattr(mod, "WORKGRAPH_LEDGER", True)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    return mod, service, TestClient(mod.app)


def _capture(client, text: str) -> str:
    r = client.post("/api/captures", json={
        "raw_content": text, "requested_mode": "create_task"})
    assert r.status_code == 201, r.text
    return r.json()["record"]["capture_id"]


def _convert(client, cid: str, title: str) -> str:
    r = client.post(f"/api/captures/{cid}/convert", json={
        "conversation_id": f"capture:{cid}", "capture_id": cid,
        "items": [{"ref": "i1", "title": title, "kind": "todo",
                   "primary_board": {"board_id": "tasks",
                                     "domain_id": "tasks",
                                     "card_component": "generic_task"}}],
        "edges": []})
    assert r.status_code == 201, r.text
    return r.json()["created"][0]["work_item"]["work_item_id"]


def _seed_done_item(client, service, text: str, title: str) -> str:
    wid = _convert(client, _capture(client, text), title)
    service.set_status(wid, "done")
    return wid


# ---- side-effect-free checking ----------------------------------------------

def test_capture_duplicate_check_is_side_effect_free(ctx):
    _mod, service, client = ctx
    wid = _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    before_items = len(service.list_items())
    for _ in range(2):                       # idempotent, no state change
        r = client.post(f"/api/captures/{cid}/duplicate-check")
        assert r.status_code == 200, r.text
        finding = r.json()["findings"][0]
        assert finding["existing_work_item_id"] == wid
        assert finding["match_class"] == "exact_same"
        assert "reopen_existing" in finding["allowed_resolutions"]
    assert len(service.list_items()) == before_items
    view = client.get(f"/api/captures/{cid}").json()
    assert view["processing_status"] != "routed"


def test_free_text_duplicate_check_finds_paraphrase(ctx):
    mod, service, client = ctx
    _seed_done_item(
        client, service,
        "Make kanban job hunt have a go through application with you setup",
        "Build a page-by-page job application companion")
    r = client.post("/api/work-items/duplicate-check", json={
        "text": "Make kanban job hunt have a go through application with "
                "you setup"})
    assert r.status_code == 200
    finding = r.json()["findings"][0]
    assert finding["match_class"] == "likely_same"
    assert any(e["kind"] == "shared_source" for e in finding["evidence"])


def test_route_question_offers_resolution_options(ctx):
    mod, service, client = ctx
    _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    r = client.post(f"/api/captures/{cid}/route")
    assert r.status_code == 200
    q = next(q for q in r.json()["needs_confirmation"]
             if "what should happen" in q["question"])
    assert "add_occurrence" in q["options"]
    assert "reopen_existing" in q["options"]


# ---- resolutions --------------------------------------------------------------

def test_reuse_existing_creates_no_new_work_item(ctx):
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    before = len(service.list_items())
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "reuse_existing",
        "match_class": "exact_same"})
    assert r.status_code == 200, r.text
    assert len(service.list_items()) == before
    view = client.get(f"/api/captures/{cid}").json()
    assert view["processing_status"] == "routed"
    decisions = client.get(
        f"/api/work-items/{wid}/duplicate-decisions").json()["decisions"]
    assert decisions[0]["payload"]["resolution"] == "reuse_existing"


def test_add_occurrence_increments_badge_and_links_capture(ctx):
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Apply to more jobs",
                          "Apply to more jobs")
    cid = _capture(client, "Applied to three more jobs")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "add_occurrence",
        "quantity": 3, "unit": "applications",
        "match_class": "repeat_occurrence"})
    assert r.status_code == 200, r.text
    assert r.json()["occurrence_count"] == 1
    occurrences = client.get(
        f"/api/work-items/{wid}/occurrences").json()
    assert occurrences["occurrence_count"] == 1
    payload = occurrences["occurrences"][0]["payload"]
    assert payload["quantity"] == 3
    assert payload["source_capture_id"] == cid
    # canonical status untouched; capture linked, not duplicated
    assert service.get_item(wid).canonical_status == "done"
    assert len(service.list_items()) == 1


def test_reopen_existing_changes_canonical_status_once(ctx):
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "reopen_existing"})
    assert r.status_code == 200, r.text
    assert service.get_item(wid).canonical_status == "ready"


def test_discard_capture_hides_from_inbox_but_preserves_history(ctx):
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "discard_capture",
        "note": "duplicate rewatch entry"})
    assert r.status_code == 200, r.text
    view = client.get(f"/api/captures/{cid}").json()
    assert view["processing_status"] == "archived"
    assert view["record"]["raw_content"] == "Watch tenet"   # never destroyed
    inbox = client.get("/api/intake/inbox").json()
    archived_col = next((c for c in inbox["columns"]
                         if c["name"] == "archived"), None)
    active = [cap["capture_id"] for col in inbox["columns"]
              if col["name"] not in ("archived", "routed")
              for cap in col["captures"]]
    assert cid not in active
    assert archived_col is None or cid in [
        c["capture_id"] for c in archived_col["captures"]]


def test_routed_capture_cannot_be_archived(ctx):
    mod, service, client = ctx
    cid = _capture(client, "Watch tenet")
    _convert(client, cid, "Watch tenet")
    r = client.post(f"/api/captures/{cid}/archive",
                    json={"reason": "cleanup"})
    assert r.status_code == 409


def test_expand_existing_applies_only_selected_deltas(ctx):
    mod, service, client = ctx
    wid = _convert(client, _capture(client,
                                    "Build an editable company watchlist"),
                   "Build an editable company watchlist")
    cid = _capture(client,
                   "Build an editable company watchlist. Track competitor "
                   "companies. Refresh the list weekly.")
    report = client.post(f"/api/captures/{cid}/matches").json()
    finding = report["findings"][0]
    assert finding["match_class"] == "expands_existing"
    deltas = finding["expansion_deltas"]
    assert len(deltas) >= 2
    chosen = deltas[0]["delta_id"]                    # apply ONE only
    chosen_delta = next(delta for delta in deltas if delta["delta_id"] == chosen)
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "expand_existing",
        "selected_delta_ids": [chosen], "match_class": "expands_existing",
        "canonical_children": {chosen: {
            "title": chosen_delta["text"],
            "description": "Human-confirmed expansion child.",
            "kind": "todo",
        }},
    })
    assert r.status_code == 200, r.text
    assert r.json()["applied_delta_ids"] == [chosen]
    # title/description untouched; expansion recorded append-only
    item = service.get_item(wid)
    assert item.title == "Build an editable company watchlist"
    assert item.description == ""
    events = service.expansions(wid)
    assert len(events) == 1
    applied = [d["delta_id"] for d in events[0].payload["deltas"]]
    assert applied == [chosen]                        # unselected NOT applied


def test_expand_with_no_selection_is_rejected(ctx):
    mod, service, client = ctx
    wid = _convert(client, _capture(client, "Build a watchlist"),
                   "Build a watchlist")
    cid = _capture(client, "Build a watchlist. Track competitors weekly.")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "expand_existing",
        "selected_delta_ids": []})
    assert r.status_code == 422


def test_add_child_creates_child_with_parent_edge(ctx):
    mod, service, client = ctx
    wid = _convert(client, _capture(client, "Camera Setup Project"),
                   "Camera Setup Project")
    cid = _capture(client, "Buy the tripod for the camera setup")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "add_child",
        "canonical_title": "Buy the tripod for the camera setup",
        "canonical_description": "Human-confirmed child work.",
        "canonical_kind": "todo", "confirm_canonical_fields": True,
    })
    assert r.status_code == 200, r.text
    child_id = r.json()["created_work_item_id"]
    graph = client.get(f"/api/work-graph/{wid}").json()
    edge = next(e for e in graph["edges"]
                if e["to_work_item_id"] == child_id)
    assert edge["relation"] == "parent_of"
    assert edge["from_work_item_id"] == wid
    # child inherits the parent's board placement
    child_places = [p for p in graph["placements"]
                    if p["work_item_id"] == child_id]
    assert child_places and child_places[0]["board_id"] == "tasks"


def test_create_project_group_groups_members_without_new_board(ctx):
    mod, service, client = ctx
    w1 = _convert(client, _capture(client, "Research the best camera setup"),
                  "Research the best camera setup")
    w2 = _convert(client, _capture(client, "Compare camera prices"),
                  "Compare camera prices")
    cid = _capture(client, "Buy a camera tripod")
    boards_before = {d["board_id"] for d in client.get(
        "/api/domain-schema").json()["domains"]}
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": w1, "resolution": "create_project_group",
        "group_title": "Camera Setup", "member_work_item_ids": [w2],
        "canonical_project_title": "Camera Setup",
        "canonical_project_description": "Human-confirmed project grouping.",
        "canonical_project_kind": "project", "confirm_canonical_project": True,
        "canonical_title": "Buy a camera tripod",
        "canonical_description": "Human-confirmed grouped child.",
        "canonical_kind": "todo", "confirm_canonical_fields": True,
    })
    assert r.status_code == 200, r.text
    out = r.json()
    project_id = out["project_work_item_id"]
    assert set(out["member_work_item_ids"]) == {w1, w2}
    project = service.get_item(project_id)
    assert project.kind == "project"
    # grouping created a PROJECT, never a board
    boards_after = {d["board_id"] for d in client.get(
        "/api/domain-schema").json()["domains"]}
    assert boards_after == boards_before
    # members keep their own identity and status
    assert service.get_item(w1).canonical_status == "backlog"
    graph = client.get(f"/api/work-graph/{project_id}").json()
    children = {e["to_work_item_id"] for e in graph["edges"]
                if e["from_work_item_id"] == project_id
                and e["relation"] == "parent_of"}
    assert {w1, w2}.issubset(children)


def test_group_under_existing_project(ctx):
    mod, service, client = ctx
    parent = _convert(client, _capture(client, "Job Search System"),
                      "Job Search System")
    cid = _capture(client, "Prepare three tailored resumes")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": parent,
        "resolution": "group_under_existing",
        "canonical_title": "Prepare three tailored resumes",
        "canonical_description": "Human-confirmed grouped child.",
        "canonical_kind": "todo", "confirm_canonical_fields": True,
    })
    assert r.status_code == 200, r.text
    child = r.json()["created_work_item_id"]
    assert r.json()["parent_work_item_id"] == parent
    assert service.get_item(child).title == "Prepare three tailored resumes"


def test_resolved_capture_cannot_be_resolved_twice(ctx):
    # Codex finding #1: replaying a resolution must not create a second
    # child/project/occurrence
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Camera Setup Project",
                          "Camera Setup Project")
    cid = _capture(client, "Buy the tripod for the camera setup")
    resolution_body = {
        "existing_work_item_id": wid, "resolution": "add_child",
        "canonical_title": "Buy the tripod for the camera setup",
        "canonical_description": "Human-confirmed child work.",
        "canonical_kind": "todo", "confirm_canonical_fields": True,
    }
    first = client.post(
        f"/api/captures/{cid}/resolve-duplicate", json=resolution_body,
    )
    assert first.status_code == 200, first.text
    items_after = len(service.list_items())
    retry = client.post(
        f"/api/captures/{cid}/resolve-duplicate", json=resolution_body,
    )
    assert retry.status_code == 200, retry.text
    assert len(service.list_items()) == items_after   # no duplicate child


def test_partial_child_resolution_retry_reuses_intent_work_item(ctx, monkeypatch):
    _mod, service, client = ctx
    from command_center.work_graph import WorkGraphError
    parent = _seed_done_item(
        client, service, "Durable parent", "Durable parent",
    )
    capture_id = _capture(client, "A separately confirmed child")
    body = {
        "existing_work_item_id": parent,
        "resolution": "add_child",
        "canonical_title": "Confirmed child",
        "canonical_description": "Organized child description.",
        "canonical_kind": "todo",
        "confirm_canonical_fields": True,
    }
    original_add_placement = service.add_placement
    failures = {"remaining": 1}

    def fail_after_item(*args, **kwargs):
        if failures["remaining"]:
            failures["remaining"] -= 1
            raise WorkGraphError("injected placement interruption")
        return original_add_placement(*args, **kwargs)

    monkeypatch.setattr(service, "add_placement", fail_after_item)
    first = client.post(
        f"/api/captures/{capture_id}/resolve-duplicate", json=body,
    )
    assert first.status_code == 409
    item_ids_after_failure = {item.work_item_id for item in service.list_items()}
    assert len(item_ids_after_failure) == 2

    retry = client.post(
        f"/api/captures/{capture_id}/resolve-duplicate", json=body,
    )
    assert retry.status_code == 200, retry.text
    assert {item.work_item_id for item in service.list_items()} == item_ids_after_failure
    child_id = retry.json()["created_work_item_id"]
    assert child_id in item_ids_after_failure
    assert len([
        edge for edge in service._store.edges()
        if edge.from_work_item_id == parent and edge.to_work_item_id == child_id
    ]) == 1


def test_pending_foreign_link_blocks_duplicate_mutation_before_occurrence(ctx):
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Existing exact work", "Existing exact work")
    cid = _capture(client, "Existing exact work again")
    from command_center.intake import CaptureEvent
    mod._get_capture_service()._store.append_event(CaptureEvent(
        capture_id=cid,
        ts="2026-07-16T00:00:30+00:00",
        kind="link",
        payload={"work_item_ids": ["W-foreign"], "conversation_id": "chat-foreign"},
    ))
    before_events = list(service._store.events(wid))
    response = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid,
        "resolution": "add_occurrence",
        "note": "must not persist",
    })
    assert response.status_code == 409
    assert service._store.events(wid) == before_events
    assert service.occurrence_count(wid) == 0


def test_archive_existing_archives_and_leaves_capture_open(ctx):
    # Codex finding #4: archive_existing was advertised but rejected
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "archive_existing"})
    assert r.status_code == 200, r.text
    assert service.get_item(wid).canonical_status == "archived"
    # archived, never hard-deleted; capture stays open for normal routing
    assert service.get_item(wid).title == "Watch tenet"
    view = client.get(f"/api/captures/{cid}").json()
    assert view["processing_status"] not in ("routed", "archived")


def test_decision_records_server_classification_not_client_claim(ctx):
    # Codex finding #8: forged client match_class must not poison telemetry
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "reuse_existing",
        "match_class": "repeat_occurrence",          # forged claim
        "evidence_kinds": ["semantic_similarity"]})  # forged evidence
    assert r.status_code == 200, r.text
    decision = client.get(
        f"/api/work-items/{wid}/duplicate-decisions").json()["decisions"][-1]
    assert decision["payload"]["match_class"] == "exact_same"
    assert "semantic_similarity" not in decision["payload"].get(
        "evidence_kinds", [])


def test_create_separate_is_record_only(ctx):
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    before = len(service.list_items())
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "create_separate"})
    assert r.status_code == 200, r.text
    # record-only: nothing created/changed here — /convert does the create
    assert len(service.list_items()) == before
    assert client.get(
        f"/api/captures/{cid}").json()["processing_status"] != "routed"
    decisions = client.get(
        f"/api/work-items/{wid}/duplicate-decisions").json()["decisions"]
    assert decisions[-1]["payload"]["resolution"] == "create_separate"


def test_unknown_resolution_is_rejected(ctx):
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Watch tenet", "Watch tenet")
    cid = _capture(client, "Watch tenet")
    r = client.post(f"/api/captures/{cid}/resolve-duplicate", json={
        "existing_work_item_id": wid, "resolution": "permanently_purge"})
    assert r.status_code == 422


def test_occurrence_endpoint_rejects_bad_quantity(ctx):
    mod, service, client = ctx
    wid = _seed_done_item(client, service, "Apply to more jobs",
                          "Apply to more jobs")
    r = client.post(f"/api/work-items/{wid}/occurrences",
                    json={"quantity": -2})
    assert r.status_code == 409
