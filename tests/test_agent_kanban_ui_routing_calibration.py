"""Cockpit routing calibration: the router LEARNS keyword->board rules from the
correction log and then makes evidence-tagged suggestions (instead of always
asking), while GET /api/routing-rules surfaces the learned evidence. Hermetic:
module loaded by path, in-process work-graph + telemetry (no Ledger).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


def _load(monkeypatch, *, enabled=True):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("akui_routing_calib_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["akui_routing_calib_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")
    monkeypatch.setattr(mod, "WORKGRAPH_ENABLED", enabled)
    mod._workgraph_service = None
    mod._telemetry_service = None
    mod._chat_planner = None
    return mod, TestClient(mod.app)


def _seed_board(client, board="research", domain="research"):
    """Create a placement so board_id->domain_id is resolvable from REAL data."""
    wid = client.post("/api/work-items", json={"title": "anchor"}
                      ).json()["item"]["work_item_id"]
    client.post(f"/api/work-items/{wid}/placements",
                json={"board_id": board, "domain_id": domain, "is_primary": True})


def _teach(client, title, board, times=1):
    for _ in range(times):
        client.post("/api/routing-corrections",
                    json={"title": title, "chosen_board_id": board})


def test_router_learns_from_corrections_then_suggests(monkeypatch):
    _mod, client = _load(monkeypatch)
    _seed_board(client, "research", "research")
    _teach(client, "cv feasibility study", "research", times=2)

    # the learned evidence is visible, with support + distribution
    rules = client.get("/api/routing-rules").json()
    feas = next(r for r in rules["derived"] if r["keyword"] == "feasibility")
    assert feas["board_id"] == "research" and feas["support"] == 2
    assert feas["distribution"] == {"research": 2}
    assert any(r["board_id"] == "research" and "feasibility" in r["keywords"]
               for r in rules["applied"])

    # the router now SUGGESTS research for a new feasibility item (no longer asks)
    prop = client.post("/api/work-items/route",
                       json={"text": "feasibility of a new approach"}).json()
    item = prop["plan"]["items"][0]
    assert item["primary_board"] is not None
    assert item["primary_board"]["board_id"] == "research"
    assert item["primary_board"]["domain_id"] == "research"
    assert any(s["board_id"] == "research" for s in prop["board_suggestions"])


def test_without_evidence_the_router_still_asks(monkeypatch):
    _mod, client = _load(monkeypatch)
    _seed_board(client, "research", "research")           # boards exist, but no log
    prop = client.post("/api/work-items/route",
                       json={"text": "feasibility of a new approach"}).json()
    assert prop["plan"]["items"][0]["primary_board"] is None   # never auto-routed
    assert any(q["question"].startswith("Which board")
               for q in prop["needs_confirmation"])
    assert client.get("/api/routing-rules").json()["applied"] == []


def test_learned_board_with_no_placement_is_derived_but_not_applied(monkeypatch):
    _mod, client = _load(monkeypatch)
    _seed_board(client, "research", "research")     # only 'research' has a domain
    _teach(client, "ship the widget", "widgets")    # 'widgets' has NO placement
    rules = client.get("/api/routing-rules").json()
    assert any(r["board_id"] == "widgets" for r in rules["derived"])   # learned
    assert all(r["board_id"] != "widgets" for r in rules["applied"])   # not applied


def test_routing_rules_disabled_is_503(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=False)
    assert client.get("/api/routing-rules").status_code == 503
