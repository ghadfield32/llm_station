"""Cockpit work-graph routes: create a canonical item, project it onto several
boards (one primary), connect items with cycle-checked edges, remove a projection
without destroying the item, and get backend-generated links. Hermetic: the
module is loaded by path and uses the in-process WorkGraphService (no Ledger).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


def _load(monkeypatch, *, enabled=True):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_workgraph_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_workgraph_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "WORKGRAPH_ENABLED", enabled)
    mod._workgraph_service = None
    return mod, TestClient(mod.app)


def _new_item(client, title, **kw):
    return client.post("/api/work-items", json={"title": title, **kw}).json()["item"]


def test_one_item_many_placements_and_links(monkeypatch):
    _mod, client = _load(monkeypatch)
    r = client.post("/api/work-items", json={
        "title": "CV feasibility", "kind": "research", "conversation_id": "chat-9"})
    assert r.status_code == 201, r.text
    body = r.json()
    wid = body["item"]["work_item_id"]
    # links are backend-generated (graph + chat present already)
    assert {lk["kind"] for lk in body["links"]} >= {"graph", "chat"}

    client.post(f"/api/work-items/{wid}/placements",
                json={"board_id": "basketball_cv", "domain_id": "basketball_cv",
                      "is_primary": True})
    client.post(f"/api/work-items/{wid}/placements",
                json={"board_id": "research", "domain_id": "research"})
    got = client.get(f"/api/work-items/{wid}").json()
    assert {p["board_id"] for p in got["placements"]} == {"basketball_cv", "research"}
    assert got["item"]["primary_board_id"] == "basketball_cv"


def test_duplicate_primary_is_409(monkeypatch):
    _mod, client = _load(monkeypatch)
    wid = _new_item(client, "x")["work_item_id"]
    client.post(f"/api/work-items/{wid}/placements",
                json={"board_id": "a", "domain_id": "a", "is_primary": True})
    r = client.post(f"/api/work-items/{wid}/placements",
                    json={"board_id": "b", "domain_id": "b", "is_primary": True})
    assert r.status_code == 409


def test_blocking_cycle_is_409_but_related_cycle_ok(monkeypatch):
    _mod, client = _load(monkeypatch)
    a = _new_item(client, "a")["work_item_id"]
    b = _new_item(client, "b")["work_item_id"]
    assert client.post("/api/work-edges", json={
        "from_work_item_id": a, "to_work_item_id": b, "relation": "blocks"}
    ).status_code == 201
    # the reverse blocking edge closes a cycle → 409
    assert client.post("/api/work-edges", json={
        "from_work_item_id": b, "to_work_item_id": a, "relation": "blocks"}
    ).status_code == 409
    # but a related_to cycle is allowed
    client.post("/api/work-edges", json={
        "from_work_item_id": a, "to_work_item_id": b, "relation": "related_to"})
    assert client.post("/api/work-edges", json={
        "from_work_item_id": b, "to_work_item_id": a, "relation": "related_to"}
    ).status_code == 201


def test_remove_placement_preserves_the_item(monkeypatch):
    _mod, client = _load(monkeypatch)
    wid = _new_item(client, "keep")["work_item_id"]
    p = client.post(f"/api/work-items/{wid}/placements",
                    json={"board_id": "a", "domain_id": "a", "is_primary": True}).json()
    assert client.delete(
        f"/api/work-items/{wid}/placements/{p['placement_id']}").status_code == 200
    got = client.get(f"/api/work-items/{wid}").json()
    assert got["item"]["title"] == "keep"          # item survives
    assert got["placements"] == []                 # only the projection is gone


def test_graph_neighbourhood_and_unknown_404(monkeypatch):
    _mod, client = _load(monkeypatch)
    a = _new_item(client, "a")["work_item_id"]
    b = _new_item(client, "b")["work_item_id"]
    client.post("/api/work-edges", json={
        "from_work_item_id": a, "to_work_item_id": b, "relation": "related_to"})
    g = client.get(f"/api/work-graph/{a}?depth=1").json()
    assert {i["work_item_id"] for i in g["items"]} == {a, b}
    assert client.get("/api/work-graph/never-seen").status_code == 404


def test_disabled_is_503(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=False)
    assert client.post("/api/work-items", json={"title": "x"}).status_code == 503
    assert client.get("/api/work-graph").status_code == 503
