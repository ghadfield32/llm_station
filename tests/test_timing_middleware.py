"""Env-gated request timing for the agent kanban UI."""

import importlib.util
import json
import logging
import sys
from pathlib import Path

from fastapi.testclient import TestClient

APP = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "agent_kanban_ui"
    / "app.py"
)


def _load_app(monkeypatch, *, timing_enabled: bool):
    if timing_enabled:
        monkeypatch.setenv("KANBAN_UI_TIMING_LOG", "1")
    else:
        monkeypatch.delenv("KANBAN_UI_TIMING_LOG", raising=False)
    module_name = f"agent_kanban_ui_timing_{timing_enabled}_test"
    spec = importlib.util.spec_from_file_location(module_name, APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_timing_disabled_has_no_endpoint_or_rollup(monkeypatch):
    mod = _load_app(monkeypatch, timing_enabled=False)

    assert mod.KANBAN_UI_TIMING_LOG is False
    assert not hasattr(mod.app.state, "timing_rollup")
    assert TestClient(mod.app).get("/api/debug/timings").status_code == 404


def test_timing_enabled_rolls_up_route_templates(
    monkeypatch, caplog,
):
    mod = _load_app(monkeypatch, timing_enabled=True)
    monkeypatch.setattr(
        mod,
        "_domain_spec",
        lambda domain_id: {"domain_id": domain_id, "columns": []},
    )
    monkeypatch.setattr(mod, "_domain_cards", lambda _spec: {"cards": []})
    client = TestClient(mod.app)

    with caplog.at_level(logging.INFO, logger=mod.__name__):
        assert client.get("/api/domain/first/cards").status_code == 200
        assert client.get("/api/domain/second/cards").status_code == 200

    timings = client.get("/api/debug/timings").json()
    route = "/api/domain/{domain_id}/cards"
    assert route in timings
    assert "/api/domain/first/cards" not in timings
    assert "/api/domain/second/cards" not in timings
    assert timings[route]["count"] >= 2
    assert (
        timings[route]["p50_ms"]
        <= timings[route]["p95_ms"]
        <= timings[route]["max_ms"]
    )

    # Filter to the cards route: /api/debug/timings is ITSELF a timed request
    # (correct behavior — every request is measured), and it is fetched below
    # while caplog is still capturing, so counting all request_timing records
    # would be order/log-level dependent. The test's intent is "the two cards
    # requests each logged exactly once", which the route filter expresses.
    cards_logs = [
        entry
        for record in caplog.records
        if '"event":"request_timing"' in record.getMessage()
        and (entry := json.loads(record.getMessage()))["route"] == route
    ]
    assert len(cards_logs) == 2
    assert {entry["method"] for entry in cards_logs} == {"GET"}
    assert {entry["status_code"] for entry in cards_logs} == {200}
