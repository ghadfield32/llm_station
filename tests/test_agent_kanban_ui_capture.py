"""Cockpit Universal Capture routes — create (immutable), bulk-split, list, get,
and the Inbox fold. Hermetic: the module is loaded by path and uses the in-process
CaptureService (no worker, no network, no Ledger).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


def _load(monkeypatch, *, enabled=True):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_capture_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_capture_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CAPTURE_ENABLED", enabled)
    mod._capture_service = None       # fresh in-memory store per test
    return mod, TestClient(mod.app)


def test_capture_is_created_and_lands_in_inbox(monkeypatch):
    _mod, client = _load(monkeypatch)
    r = client.post("/api/captures", json={
        "raw_content": "call the dentist", "requested_mode": "save_only"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["processing_status"] == "captured"
    cid = body["record"]["capture_id"]

    inbox = client.get("/api/intake/inbox").json()
    assert inbox["total"] == 1
    captured = next(c for c in inbox["columns"] if c["name"] == "captured")
    assert captured["captures"][0]["capture_id"] == cid


def test_empty_capture_is_400(monkeypatch):
    _mod, client = _load(monkeypatch)
    assert client.post("/api/captures", json={"raw_content": "  "}).status_code == 400


def test_bulk_list_splits_into_captures_sharing_a_batch(monkeypatch):
    _mod, client = _load(monkeypatch)
    r = client.post("/api/captures/batch", json={
        "text": "- post about biomechanics\n- research shot detection\n- call dentist"})
    assert r.status_code == 201
    body = r.json()
    assert body["count"] == 3
    assert body["batch_id"] is not None
    contents = [c["record"]["raw_content"] for c in body["captures"]]
    assert contents == ["post about biomechanics", "research shot detection", "call dentist"]
    # all recoverable from the inbox
    assert client.get("/api/intake/inbox").json()["total"] == 3


def test_get_and_list_captures(monkeypatch):
    _mod, client = _load(monkeypatch)
    cid = client.post("/api/captures", json={"raw_content": "improve the job board"}
                      ).json()["record"]["capture_id"]
    assert client.get(f"/api/captures/{cid}").json()["record"]["capture_id"] == cid
    assert client.get("/api/captures/never-seen").status_code == 404
    assert len(client.get("/api/captures").json()) == 1


def test_capture_disabled_is_503(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=False)
    assert client.post("/api/captures", json={"raw_content": "x"}).status_code == 503
    assert client.get("/api/intake/inbox").status_code == 503


# --- frontend guardrail (source-level) -------------------------------------------

APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"


def test_frontend_has_global_capture_and_inbox():
    src = APP_TSX.read_text(encoding="utf-8")
    assert "function CaptureComposer" in src
    assert "function InboxView" in src
    assert "+ Capture" in src                       # global capture button
    assert '{ id: "inbox", label: "Inbox" }' in src  # Inbox nav item
    assert "createCaptureBatch(" in src             # bulk list support
    # capturing is framed as save-not-start (no silent work)
    assert "Saved, not started" in src
