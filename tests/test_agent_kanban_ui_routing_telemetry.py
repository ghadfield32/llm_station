"""Cockpit router-correction telemetry routes: record a human's routing decision,
read the evidence log + summary, and gate on the work-graph flag. Hermetic:
module loaded by path, in-process in-memory telemetry store (no Ledger).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


def _load(monkeypatch, *, enabled=True):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("akui_routing_telemetry_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["akui_routing_telemetry_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "WORKGRAPH_ENABLED", enabled)
    mod._telemetry_service = None
    return mod, TestClient(mod.app)


def test_record_computes_accepted_and_shows_up_in_the_log(monkeypatch):
    _mod, client = _load(monkeypatch)
    r = client.post("/api/routing-corrections", json={
        "title": "write a linkedin post", "suggested_board_id": "posts",
        "chosen_board_id": "research", "matched_keywords": ["linkedin"],
        "source": "chat"})
    assert r.status_code == 201, r.text
    assert r.json()["accepted"] is False        # human overrode 'posts' → 'research'

    got = client.get("/api/routing-corrections").json()
    assert len(got["corrections"]) == 1
    assert got["summary"]["total"] == 1
    assert got["summary"]["by_chosen_board"] == {"research": 1}


def test_accepted_true_when_choice_matches(monkeypatch):
    _mod, client = _load(monkeypatch)
    r = client.post("/api/routing-corrections", json={
        "title": "x", "suggested_board_id": "posts", "chosen_board_id": "posts"})
    assert r.json()["accepted"] is True
    assert client.get("/api/routing-corrections").json()["summary"]["accepted"] == 1


def test_list_filters_by_board(monkeypatch):
    _mod, client = _load(monkeypatch)
    client.post("/api/routing-corrections", json={"title": "a", "chosen_board_id": "posts"})
    client.post("/api/routing-corrections", json={"title": "b", "chosen_board_id": "research"})
    got = client.get("/api/routing-corrections?board=posts").json()
    assert [c["title"] for c in got["corrections"]] == ["a"]


def test_empty_title_is_400(monkeypatch):
    _mod, client = _load(monkeypatch)
    assert client.post("/api/routing-corrections",
                       json={"title": "   "}).status_code == 400


def test_disabled_is_503(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=False)
    assert client.post("/api/routing-corrections",
                       json={"title": "x"}).status_code == 503
    assert client.get("/api/routing-corrections").status_code == 503
