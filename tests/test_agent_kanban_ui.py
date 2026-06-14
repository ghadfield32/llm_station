"""Phase 4: the read-only agent kanban UI backend.

Hermetic — the Ledger HTTP call and the agent-call log are stubbed, so we test the
grouping/proxy/metrics shape and the fail-loud Ledger path with no live services.
The service is read-only: there is no write endpoint to test because there is none.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "services" / "agent_kanban_ui" / "app.py"


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod, TestClient(mod.app)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_missions_grouped_into_ordered_columns(client, monkeypatch):
    mod, tc = client
    rows = [
        {"id": "T-1", "action": "do a", "risk": "L2", "status": "running"},
        {"id": "T-2", "action": "do b", "risk": "L3", "status": "awaiting_approval"},
        {"id": "T-3", "action": "do c", "risk": "L1", "status": "running"},
    ]
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: _Resp(rows))
    body = tc.get("/api/missions").json()
    assert body["total"] == 3
    names = [c["name"] for c in body["columns"]]
    # live columns appear in canonical order; awaiting_approval before running
    assert names == ["awaiting_approval", "running"]
    running = next(c for c in body["columns"] if c["name"] == "running")
    assert len(running["cards"]) == 2


def test_unknown_status_still_shown_not_hidden(client, monkeypatch):
    mod, tc = client
    rows = [{"id": "T-9", "action": "x", "status": "quarantined"}]
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: _Resp(rows))
    names = [c["name"] for c in tc.get("/api/missions").json()["columns"]]
    assert "quarantined" in names


def test_ledger_unreachable_is_502_not_empty_board(client, monkeypatch):
    mod, tc = client

    def boom(*a, **k):
        raise mod.httpx.ConnectError("refused")

    monkeypatch.setattr(mod.httpx, "get", boom)
    r = tc.get("/api/missions")
    assert r.status_code == 502 and "ledger unreachable" in r.json()["detail"]


def test_metrics_uses_kanban_metrics(client, monkeypatch):
    mod, tc = client
    calls = [{"ts": "t", "surface": "discord", "tool": "stage_card",
              "args": {}, "ok": True, "ms": 5.0}]
    monkeypatch.setattr(mod, "load_calls", lambda *a, **k: calls)
    body = tc.get("/api/metrics").json()
    assert body["total_calls"] == 1 and body["intent_verb_calls"] == 1


def test_health_and_config(client):
    _, tc = client
    assert tc.get("/api/health").json()["status"] == "ok"
    cfg = tc.get("/api/config").json()
    # chat is OFF by default (no KANBAN_UI_CHAT_ENABLED in the test env)
    assert cfg["chat_enabled"] is False and cfg["model_roles"] == []


def test_status_probes_report_ok_and_error(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: _Resp({}))
    assert tc.get("/api/status").json()["hops"]["ledger"] == "ok"

    def boom(*a, **k):
        raise mod.httpx.ConnectError("refused")
    monkeypatch.setattr(mod.httpx, "get", boom)
    assert tc.get("/api/status").json()["hops"]["ledger"].startswith("error")


def test_chat_and_writes_disabled_by_default_are_503(client):
    _, tc = client
    assert tc.post("/api/chat", json={"text": "hi"}).status_code == 503
    assert tc.post("/api/action", json={"action": "stage_card",
                                        "params": {}}).status_code == 503


def test_action_rejects_non_governed_verb(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    r = tc.post("/api/action", json={"action": "delete_everything", "params": {}})
    assert r.status_code == 400 and "not allowed" in r.json()["detail"]


def test_action_never_allows_approve(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    # there is simply no 'approve' verb in the governed set — the wall holds here too
    assert "approve" not in mod.ACTION_VERBS
    assert tc.post("/api/action", json={"action": "approve_card",
                                        "params": {}}).status_code == 400


def test_chat_validates_model_against_configs(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    (tmp_path / "models.yaml").write_text(
        "schema_version: '1'\nroles:\n  chat:\n    - alias: chat\n      provider: ollama\n"
        "      model: qwen3:30b\n      priority: 1\n      local: true\n")
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)
    r = tc.post("/api/chat", json={"text": "hi", "model": "no-such-role"})
    assert r.status_code == 400 and "unknown model role" in r.json()["detail"]


def test_boards_served_from_worker_snapshot(client, monkeypatch, tmp_path):
    mod, tc = client
    snap = tmp_path / "board-snapshot.json"
    snap.write_text('{"generated_at": "2026-06-13T00:00:00Z", '
                    '"boards": [{"board": "todos", "columns": []}]}')
    monkeypatch.setattr(mod, "BOARD_SNAPSHOT", snap)
    body = tc.get("/api/boards").json()
    assert body["boards"][0]["board"] == "todos"


def test_boards_missing_snapshot_is_503_with_path(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "BOARD_SNAPSHOT", tmp_path / "absent.json")
    r = tc.get("/api/boards")
    assert r.status_code == 503 and "snapshot not found" in r.json()["detail"]


def test_models_router_reads_configs_data_derived(client, monkeypatch, tmp_path):
    mod, tc = client
    (tmp_path / "models.yaml").write_text(
        "schema_version: '1'\nroles:\n  triage:\n    - alias: triage\n"
        "      provider: ollama\n      model: qwen3:30b\n      priority: 1\n"
        "      local: true\n")
    (tmp_path / "judges.yaml").write_text(
        "schema_version: '1'\nstages:\n  - stage: implement\n    judges:\n"
        "      - name: diff\n        role_alias: local-judge\n")
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)
    body = tc.get("/api/models").json()
    assert body["roles"][0]["role"] == "triage"
    assert body["roles"][0]["candidates"][0]["model"] == "qwen3:30b"
    assert body["judge_stages"][0]["stage"] == "implement"


def test_models_missing_config_is_503(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)   # empty dir, no models.yaml
    assert tc.get("/api/models").status_code == 503


def test_activity_feed_returns_recent_calls_newest_first(client, monkeypatch):
    mod, tc = client
    calls = [
        {"ts": "2026-01-01T00:00:01", "surface": "discord", "tool": "list_cards",
         "ok": True, "ms": 5.0, "detail": ""},
        {"ts": "2026-01-01T00:00:02", "surface": "mcp", "tool": "stage_card",
         "ok": False, "ms": 9.0, "detail": "boom"},
    ]
    monkeypatch.setattr(mod, "recent_calls", lambda limit=25: calls)
    out = tc.get("/api/activity").json()["calls"]
    assert out[0]["tool"] == "stage_card" and out[0]["ok"] is False   # newest first
    assert out[1]["tool"] == "list_cards"
