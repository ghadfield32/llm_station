"""Cockpit capture→work conversion: a captured idea becomes canonical work via
the planner, the created items carry the capture's provenance, and the capture is
marked 'routed' + linked (never destroyed). preview persists nothing. Hermetic:
module loaded by path, in-process Capture + WorkGraph services (no Ledger/worker).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


def _load(monkeypatch, *, capture=True, workgraph=True):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("akui_capture_convert_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["akui_capture_convert_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CAPTURE_ENABLED", capture)
    monkeypatch.setattr(mod, "WORKGRAPH_ENABLED", workgraph)
    mod._capture_service = None
    mod._workgraph_service = None
    mod._chat_planner = None
    return mod, TestClient(mod.app)


def _capture(client, text="research old NBA footage for biomechanics", **kw):
    r = client.post("/api/captures", json={"raw_content": text, **kw})
    assert r.status_code == 201, r.text
    return r.json()["record"]["capture_id"]


def _plan():
    return {"items": [
        {"ref": "feas", "title": "CV feasibility", "kind": "research",
         "primary_board": {"board_id": "basketball_cv", "domain_id": "basketball_cv"}},
        {"ref": "lic", "title": "Licensing", "kind": "research",
         "primary_board": {"board_id": "research", "domain_id": "research"}}],
        "edges": [{"from_ref": "lic", "to_ref": "feas", "relation": "blocks"}]}


def test_convert_creates_work_with_capture_provenance_and_routes_capture(monkeypatch):
    _mod, client = _load(monkeypatch)
    cid = _capture(client, conversation_id="chat-5")
    r = client.post(f"/api/captures/{cid}/convert", json=_plan())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["capture_id"] == cid
    # two canonical items, each stamped with the originating capture
    items = client.get("/api/work-items").json()
    assert len(items) == 2
    assert all(i["capture_id"] == cid for i in items)
    assert all(i["conversation_id"] == "chat-5" for i in items)   # capture's chat
    # the capture is now in the 'routed' lane — recoverable, not destroyed
    assert client.get(f"/api/captures/{cid}").json()["processing_status"] == "routed"


def test_convert_preview_is_side_effect_free(monkeypatch):
    _mod, client = _load(monkeypatch)
    cid = _capture(client)
    r = client.post(f"/api/captures/{cid}/work-preview", json=_plan())
    assert r.status_code == 200, r.text
    assert r.json()["preview"] is True
    # nothing persisted, capture untouched
    assert client.get("/api/work-items").json() == []
    assert client.get(f"/api/captures/{cid}").json()["processing_status"] == "captured"


def test_convert_unknown_capture_is_404(monkeypatch):
    _mod, client = _load(monkeypatch)
    assert client.post("/api/captures/nope/convert",
                       json=_plan()).status_code == 404
    assert client.post("/api/captures/nope/work-preview",
                       json=_plan()).status_code == 404


def test_convert_cycle_is_409_and_capture_stays_captured(monkeypatch):
    _mod, client = _load(monkeypatch)
    cid = _capture(client)
    bad = {"items": [{"ref": "a", "title": "A"}, {"ref": "b", "title": "B"}],
           "edges": [{"from_ref": "a", "to_ref": "b", "relation": "blocks"},
                     {"from_ref": "b", "to_ref": "a", "relation": "blocks"}]}
    assert client.post(f"/api/captures/{cid}/convert", json=bad).status_code == 409
    # the work side is atomic AND the capture was not marked (mark happens after)
    assert client.get("/api/work-items").json() == []
    assert client.get(f"/api/captures/{cid}").json()["processing_status"] == "captured"


def test_convert_disabled_when_graph_off(monkeypatch):
    _mod, client = _load(monkeypatch, workgraph=False)
    # with the graph off, conversion is 503 (checked before touching the capture)
    assert client.post("/api/captures/whatever/convert",
                       json=_plan()).status_code == 503
    assert client.post("/api/captures/whatever/work-preview",
                       json=_plan()).status_code == 503
