"""Assistant-routing policy: strict config contract (preview-only v1) and the
cockpit roles endpoint that joins it with live Assistant availability.
Design: docs/architecture/task-assistant-routing.md."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from command_center.schemas import CONFIG_CONTRACTS

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"
CONTRACT = CONFIG_CONTRACTS["configs/assistant-routing.yaml"]


def _policy(**overrides):
    base = {
        "schema_version": "command-center.assistant-routing.v1",
        "enabled": False,
        "default_mode": "preview_only",
        "evidence": {
            "usage_max_age_seconds": 300, "preview_ttl_seconds": 60,
            "unknown_usage": {
                "local_unmetered_gateway": "eligible_with_disclosure",
                "agent_or_paid_lane": "confirmation_required"}},
        "categories": {
            "conversation": {
                "capability_profile": "local_action_chat",
                "risk_ceiling": "L0_read_only",
                "candidates": [
                    {"assistant_id": "gatewaycore", "preference": 1}]}},
        "manual_only_model_lanes": ["frontier", "local_frontier"],
    }
    base.update(overrides)
    return base


def test_committed_config_validates():
    import yaml
    cfg = yaml.safe_load(
        (ROOT / "configs" / "assistant-routing.yaml").read_text("utf-8"))
    policy = CONTRACT(**cfg)
    assert policy.default_mode == "preview_only"   # v1 admits nothing else
    assert policy.enabled is False                 # ships disabled


def test_duplicate_preferences_are_rejected():
    bad = _policy(categories={"deep_code": {
        "capability_profile": "deep_code", "risk_ceiling": "L2_local_edits",
        "candidates": [
            {"assistant_id": "codex_agent", "preference": 1},
            {"assistant_id": "claude_code_local", "preference": 1}]}})
    with pytest.raises(Exception, match="duplicate candidate preferences"):
        CONTRACT(**bad)


def test_frontier_lane_cannot_be_an_assistant_candidate():
    bad = _policy(categories={"deep_code": {
        "capability_profile": "deep_code", "risk_ceiling": "L2_local_edits",
        "candidates": [{"assistant_id": "frontier", "preference": 1}]}})
    with pytest.raises(Exception, match="manual-only model lane"):
        CONTRACT(**bad)


def test_dispatch_modes_are_not_configurable_in_v1():
    with pytest.raises(Exception):
        CONTRACT(**_policy(default_mode="auto_dispatch"))


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location(
        "assistant_routing_app_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["assistant_routing_app_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")
    monkeypatch.setattr(mod, "AGENT_SESSIONS_ENABLED", False)
    return TestClient(mod.app)


def test_roles_endpoint_joins_policy_with_catalog(client):
    body = client.get("/api/assistant-routing").json()
    assert body["default_mode"] == "preview_only"
    assert body["config_path"] == "configs/assistant-routing.yaml"
    ids = {c["category_id"] for c in body["categories"]}
    assert {"conversation", "repository_analysis", "deep_code"} <= ids
    repo = next(c for c in body["categories"]
                if c["category_id"] == "repository_analysis")
    prefs = [c["preference"] for c in repo["candidates"]]
    assert prefs == sorted(prefs)                  # preference-ordered
    # agent sessions disabled in this fixture: candidates surface a grounded
    # unavailability instead of vanishing or claiming availability
    agent = next(c for c in repo["candidates"]
                 if c["assistant_id"] == "claude_code_local")
    assert agent["availability"] != "available"
