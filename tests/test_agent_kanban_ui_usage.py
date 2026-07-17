"""Cockpit Usage & Limits routes: disabled-mode 503, honest-empty when enabled
but nothing polled, the FakeCollector demo path populating through
/api/model-usage/refresh, literal /api/model-usage/* paths NOT being captured
by the /{runtime_id} catch-all, and bad attribution params -> 400.

Hermetic: the module is loaded by file path (importlib) and the usage service
is the in-process UsageService (no worker, no network, no SDK).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"
APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"


def _load(monkeypatch, *, enabled=True, fake=False):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_usage_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_usage_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "USAGE_ENABLED", enabled)
    monkeypatch.setattr(mod, "USAGE_FAKE", fake)
    monkeypatch.setattr(mod, "USAGE_CODEX", False)
    # reset the module-level singletons (fresh module, but be explicit)
    mod._usage_service = None
    mod._usage_collectors.clear()
    return mod, TestClient(mod.app)


def test_disabled_returns_503_everywhere(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=False)
    for path in ("/api/model-usage", "/api/model-limits", "/api/model-alerts",
                 "/api/model-usage/collector-health",
                 "/api/model-usage/recent-activity?runtime_id=codex_agent",
                 "/api/model-usage/portfolio"):
        r = client.get(path)
        assert r.status_code == 503, path
    assert client.post("/api/model-usage/refresh").status_code == 503


def test_enabled_but_unpolled_is_honestly_empty(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=True, fake=False)
    assert client.get("/api/model-usage").json() == []
    assert client.get("/api/model-limits").json() == []
    assert client.get("/api/model-alerts").json() == []
    # refresh with no registered collectors is a no-op, not a crash
    assert client.post("/api/model-usage/refresh").json() == {
        "collectors_run": 0, "results": []}


def test_unseen_runtime_detail_is_unknown_not_error(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=True)
    r = client.get("/api/model-usage/never_seen")
    assert r.status_code == 200
    body = r.json()
    assert body["availability"] == "unknown"
    assert body["limits"] == []


def test_fake_refresh_populates_the_page(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=True, fake=True)
    ref = client.post("/api/model-usage/refresh").json()
    assert ref["collectors_run"] == 1
    assert ref["results"][0]["collector_id"] == "fake"

    overview = client.get("/api/model-usage").json()
    assert [r["runtime_id"] for r in overview] == ["fake_runtime"]
    assert overview[0]["availability"] == "available"

    limits = client.get("/api/model-limits").json()
    assert {lim["bucket_id"] for lim in limits} == {"primary", "monthly_budget"}


def test_collector_health_is_not_swallowed_by_runtime_catchall(monkeypatch):
    # the literal path must resolve to the health handler (a list), NOT the
    # /{runtime_id} detail handler (a dict) — proves route ordering
    _mod, client = _load(monkeypatch, enabled=True, fake=True)
    client.post("/api/model-usage/refresh")
    health = client.get("/api/model-usage/collector-health").json()
    assert isinstance(health, list)
    assert {h["collector_id"] for h in health} == {"fake"}
    assert health[0]["never_ran"] is False


def test_claude_rate_limit_event_tees_into_the_usage_store(monkeypatch):
    # a live claude_code_local rate_limit AgentEvent, teed through the cockpit,
    # must land on the claude_code_local runtime card (NOT the API lane) — the
    # loop that lights up the Usage page + selector badge from a real session.
    mod, client = _load(monkeypatch, enabled=True, fake=False)
    monkeypatch.setattr(mod, "USAGE_CLAUDE", True)
    mod._session_harness["s1"] = "claude_code_local"
    ev = {"type": "rate_limit", "ts": "2026-07-12T00:00:00+00:00",
          "payload": {"status": "allowed_warning", "rate_limit_type": "five_hour",
                      "utilization": None, "resets_at": 1783896000}}
    mod._feed_agent_usage(None, "s1", ev)      # harness cached -> no worker call

    rows = {r["runtime_id"]: r for r in client.get("/api/model-usage").json()}
    assert "claude_code_local" in rows and "claude_agent" not in rows
    claude = rows["claude_code_local"]
    assert claude["availability"] == "near_limit"
    assert any(lim["bucket_id"] == "five_hour" for lim in claude["limits"])


def test_tee_stands_down_as_a_writer_under_usage_ledger(monkeypatch):
    # when the cockpit reads the shared Ledger, the WORKER is the sole writer;
    # the browser-dependent tee must NOT also write. It should early-return
    # before it even builds/touches the usage service.
    mod, _client = _load(monkeypatch, enabled=True, fake=False)
    monkeypatch.setattr(mod, "USAGE_CLAUDE", True)
    monkeypatch.setattr(mod, "USAGE_LEDGER", True)
    mod._usage_service = None
    mod._session_harness["s1"] = "claude_code_local"
    ev = {"type": "rate_limit", "ts": "2026-07-13T00:00:00+00:00",
          "payload": {"status": "allowed_warning", "rate_limit_type": "five_hour",
                      "utilization": None, "resets_at": 1783896000}}
    mod._feed_agent_usage(None, "s1", ev)
    assert mod._usage_service is None    # tee wrote nothing (never even built it)


def test_ledger_refresh_and_health_are_delegated_to_host_worker(monkeypatch):
    mod, client = _load(monkeypatch, enabled=True, fake=False)
    monkeypatch.setattr(mod, "USAGE_LEDGER", True)
    monkeypatch.setattr(mod, "AGENT_SESSIONS_ENABLED", True)
    # Avoid constructing a real Ledger client: these routes only need the
    # feature gate before delegating to the injected worker.
    mod._usage_service = object()

    class Response:
        status_code = 200
        text = ""

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class Worker:
        def __init__(self):
            self.calls = []

        def refresh_usage(self):
            self.calls.append("refresh")
            return Response({"collectors_run": 1, "results": [
                {"collector_id": "codex_app_server",
                 "runtimes": ["codex_agent"], "alerts_fired": 0}]})

        def usage_collector_health(self):
            self.calls.append("health")
            return Response([{"collector_id": "codex_app_server",
                              "never_ran": False}])

    worker = Worker()
    mod._agent_worker_client = worker

    refreshed = client.post("/api/model-usage/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["results"][0]["collector_id"] == "codex_app_server"
    health = client.get("/api/model-usage/collector-health")
    assert health.status_code == 200
    assert health.json()[0]["collector_id"] == "codex_app_server"
    assert worker.calls == ["refresh", "health"]


def test_top_drivers_bad_dimension_is_400(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=True, fake=True)
    client.post("/api/model-usage/refresh")
    ok = client.get("/api/model-usage/top-drivers",
                    params={"runtime_id": "fake_runtime"})
    assert ok.status_code == 200
    assert ok.json()["rows"][0]["key"] == "(unattributed)"

    bad = client.get("/api/model-usage/top-drivers",
                     params={"runtime_id": "fake_runtime", "dimension": "bogus"})
    assert bad.status_code == 400


def test_recent_activity_route_returns_sanitized_kpis(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=True, fake=True)
    client.post("/api/model-usage/refresh")
    response = client.get(
        "/api/model-usage/recent-activity",
        params={"runtime_id": "fake_runtime"})
    assert response.status_code == 200
    body = response.json()
    assert body["runtime_id"] == "fake_runtime"
    assert body["window"]["id"] == "week"
    assert body["kpis"]["average_tokens_per_call"] == 1000.0
    assert body["rows"][0]["purpose"] == "Agent session"


def test_usage_routes_reject_unknown_windows(monkeypatch):
    _mod, client = _load(monkeypatch, enabled=True, fake=True)
    for path in (
        "/api/model-usage",
        "/api/model-usage/portfolio",
        "/api/model-usage/recent-activity?runtime_id=fake_runtime",
    ):
        separator = "&" if "?" in path else "?"
        response = client.get(path + separator + "window=quarter")
        assert response.status_code == 400, path


def test_jsonl_usage_rows_degrade_when_time_window_cannot_be_proven(
        monkeypatch, tmp_path):
    mod, _client = _load(monkeypatch, enabled=True)
    ledger = tmp_path / "usage.jsonl"
    ledger.write_text(
        '{"model_id":"missing-time"}\n'
        '{"model_id":"valid","ts":"2026-07-16T10:00:00Z"}\n',
        encoding="utf-8",
    )
    rows, source = mod._jsonl_usage_rows(
        ledger, source_id="test", label="Test ledger",
        after_iso="2026-07-15T00:00:00+00:00",
    )
    assert [row["model_id"] for row in rows] == ["valid"]
    assert source["state"] == "degraded"
    assert "excluded 1 rows without a valid timestamp" in source["detail"]


def test_portfolio_combines_local_openrouter_and_local_frontier_usage(
        monkeypatch, tmp_path):
    mod, client = _load(monkeypatch, enabled=True)
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")
    monkeypatch.setattr(mod, "_litellm_usage_rows", lambda _after=None: ([
        {"model": "ollama_chat/qwen3:30b", "model_group": "chat",
         "prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15,
         "request_duration_ms": 250, "status": "success",
         "startTime": "2026-07-16T10:00:00Z"},
    ], {"source_id": "litellm", "label": "Local model gateway",
        "state": "ok", "row_count": 1, "detail": "Loaded 1 retained call"}))

    frontier = tmp_path / "frontier.jsonl"
    frontier.write_text(
        '{"ts":"2026-07-10T10:00:00Z","provider":"openrouter",'
        '"model_id":"glm-5.2","actual_input_tokens":7,'
        '"actual_output_tokens":3,"actual_cost_usd":0.002}\n',
        encoding="utf-8")
    local_frontier = tmp_path / "local-frontier.jsonl"
    local_frontier.write_text(
        '{"ts":"2026-07-11T10:00:00Z","model_id":"glm-5.2-colibri",'
        '"prompt_tokens":5,"completion_tokens":2,"elapsed_seconds":10}\n',
        encoding="utf-8")
    monkeypatch.setattr(mod, "FRONTIER_USAGE_LEDGER", frontier)
    monkeypatch.setattr(mod, "LOCAL_FRONTIER_USAGE_LEDGER", local_frontier)

    response = client.get("/api/model-usage/portfolio")
    assert response.status_code == 200
    body = response.json()
    by_model = {row["model_id"]: row for row in body["models"]}
    assert by_model["qwen3:30b"]["total_tokens"] == 15
    assert by_model["glm-5.2"]["provider"] == "OpenRouter"
    assert by_model["glm-5.2-colibri"]["provider"] == "Local frontier"
    assert {source["state"] for source in body["sources"]} == {"ok"}


def test_usage_frontend_distinguishes_loading_empty_and_error_states():
    source = APP_TSX.read_text(encoding="utf-8")

    assert "type AgentUsageDetailLoad =" in source
    assert 'detailLoad.state === "loading"' in source
    assert 'detailLoad.state === "error"' in source
    assert 'detailLoad.state === "ready"' in source
    assert "Recent usage unavailable: {detailLoad.error}" in source
    assert "<RecentUsageList rows={detailLoad.detail.rows} />" in source
    assert "detail?.rows ?? []" not in source


def test_usage_frontend_exposes_truthful_live_filters_and_labels():
    source = APP_TSX.read_text(encoding="utf-8")

    for marker in (
        "Reads live sources every 30 seconds",
        "24 hours",
        "7 days",
        "30 days",
        "All retained",
        "Model, role, or purpose",
        "Estimated OpenRouter cost",
        "Model not recorded",
        "Identified models active",
        "Cached input share",
        "hardware cost not measured",
    ):
        assert marker in source
    assert "OpenRouter spend" not in source
    assert "Cache utilization" not in source
    assert "Healthy data sources" not in source
