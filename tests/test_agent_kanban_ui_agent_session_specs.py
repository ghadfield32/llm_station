"""Read-only agent-session spec catalog tests."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    spec = importlib.util.spec_from_file_location(
        "agent_kanban_ui_agent_session_specs_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_agent_session_specs_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod, TestClient(mod.app)


def test_agent_session_specs_returns_seed_specs_without_instructions_or_secrets(
        client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")

    response = tc.get("/api/agent-session-specs")

    assert response.status_code == 200, response.json()
    entries = response.json()
    assert {entry["name"] for entry in entries} == {
        "claude-local-analysis",
        "codex-analysis",
    }
    for entry in entries:
        assert set(entry) == {
            "name",
            "harness",
            "capability_profile",
            "effort",
            "mode",
            "instructions_source",
            "policy_refs",
        }
        assert entry["instructions_source"] == "inline"
        assert "instructions" not in entry
        assert "instructions_file" not in entry

    by_name = {entry["name"]: entry for entry in entries}
    assert by_name["claude-local-analysis"]["harness"] == "claude_code_local"
    assert by_name["claude-local-analysis"]["capability_profile"] == "generalist"
    assert by_name["claude-local-analysis"]["effort"] is None
    assert by_name["codex-analysis"]["harness"] == "codex_agent"
    assert by_name["codex-analysis"]["effort"] == "high"

    serialized = json.dumps(entries)
    assert "Review the requested work" not in serialized
    assert "Analyze the requested repository work" not in serialized


def test_agent_session_specs_reports_malformed_file_as_redacted_typed_error(
        client, monkeypatch):
    mod, tc = client
    configs = ROOT / "tests" / "fixtures" / "agent_session_specs" / "configs"
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)

    response = tc.get("/api/agent-session-specs")

    assert response.status_code == 200, response.text
    error_entry = next(
        entry for entry in response.json() if entry["name"] == "malformed")
    assert error_entry == {
        "name": "malformed",
        "error": {
            "code": "invalid_agent_session_spec",
            "message": "This agent-session spec could not be loaded or validated.",
        },
    }
    assert "NEVER_EXPOSE_THIS_SECRET" not in response.text
