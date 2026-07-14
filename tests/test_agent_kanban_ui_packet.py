"""Cockpit Readiness Packet routes: assemble a packet from a plan, read its
readiness gate, set review outcomes, and commit (refused until ready) — which
creates the work graph and links every item back via packet_id. Hermetic:
module loaded by path, in-process packet + work-graph services (no Ledger).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


def _load(monkeypatch, *, enabled=True):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("akui_packet_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["akui_packet_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "WORKGRAPH_ENABLED", enabled)
    mod._workgraph_service = None
    mod._chat_planner = None
    mod._packet_service = None
    return mod, TestClient(mod.app)


def _plan_body(**extra):
    return {"plan": {"conversation_id": "chat-1", "items": [
        {"ref": "a", "title": "Ship the packet feature", "kind": "feature",
         "primary_board": {"board_id": "eng", "domain_id": "eng"}}]}, **extra}


def test_assemble_readiness_review_and_commit_loop(monkeypatch):
    _mod, client = _load(monkeypatch)
    r = client.post("/api/packets", json=_plan_body(
        runbook=["build", "test"], acceptance_criteria=["it works"],
        review_roles=["codex_agent"]))
    assert r.status_code == 201, r.text
    pkt = r.json()
    pid = pkt["packet_id"]
    assert pkt["plan_summary"]["item_count"] == 1
    assert pkt["status"] == "in_review"

    # readiness gate blocks on the pending review
    ready = client.get(f"/api/packets/{pid}/readiness").json()
    assert ready["ready"] is False
    assert any(c["id"] == "reviews_approved" and not c["ok"] for c in ready["checks"])

    # commit refused while not ready — and NOTHING was created
    assert client.post(f"/api/packets/{pid}/commit").status_code == 409
    assert client.get("/api/work-items").json() == []

    # a human approves the review -> ready
    client.post(f"/api/packets/{pid}/reviews/codex_agent",
                json={"status": "approved", "summary": "ok"})
    assert client.get(f"/api/packets/{pid}/readiness").json()["ready"] is True

    # commit now creates the graph and links the item back to the packet
    committed = client.post(f"/api/packets/{pid}/commit")
    assert committed.status_code == 201, committed.text
    assert committed.json()["status"] == "committed"
    items = client.get("/api/work-items").json()
    assert len(items) == 1 and items[0]["packet_id"] == pid
    # the packet permalink is emitted for the item
    wid = items[0]["work_item_id"]
    links = client.get(f"/api/work-items/{wid}/links").json()
    assert any(lk["kind"] == "packet" and lk["resource_id"] == pid for lk in links)


def test_no_reviews_packet_is_ready_and_commits(monkeypatch):
    _mod, client = _load(monkeypatch)
    pid = client.post("/api/packets", json=_plan_body()).json()["packet_id"]
    assert client.get(f"/api/packets/{pid}/readiness").json()["ready"] is True
    assert client.post(f"/api/packets/{pid}/commit").status_code == 201


def test_bad_review_role_is_400_and_unknown_packet_404(monkeypatch):
    _mod, client = _load(monkeypatch)
    pid = client.post("/api/packets",
                      json=_plan_body(review_roles=["codex_agent"])).json()["packet_id"]
    assert client.post(f"/api/packets/{pid}/reviews/nobody",
                       json={"status": "approved"}).status_code == 400
    assert client.get("/api/packets/never-seen").status_code == 404


def test_structurally_invalid_plan_is_400_not_500(monkeypatch):
    _mod, client = _load(monkeypatch)
    # duplicate refs -> rejected at assemble with 400 (never a 500 at commit)
    r = client.post("/api/packets", json={"plan": {"conversation_id": "c", "items": [
        {"ref": "a", "title": "one"}, {"ref": "a", "title": "two"}]}})
    assert r.status_code == 400, r.text


def test_packets_disabled_is_503(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=False)
    assert client.post("/api/packets", json=_plan_body()).status_code == 503
    assert client.get("/api/packets").status_code == 503
