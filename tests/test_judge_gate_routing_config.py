"""Judge Gate classify routing is loaded from validated config, not service constants."""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest
import yaml

APP = Path(__file__).resolve().parents[1] / "services" / "judge_gate" / "app.py"


def _base_gates() -> dict:
    return {
        "schema_version": "command-center.gates.v1",
        "tiers": {
            "L0_read_only": {
                "auto": True,
                "requires_approval": False,
                "default_route_alias": "triage",
                "required_stages": ["intake"],
            },
            "L1_plan_only": {
                "auto": True,
                "requires_approval": False,
                "default_route_alias": "planner",
                "required_stages": ["intake", "plan"],
            },
            "L2_local_edits": {
                "auto": True,
                "requires_approval": False,
                "default_route_alias": "coder",
                "required_stages": ["intake", "plan", "pre-commit"],
            },
            "L3_external_write": {
                "auto": False,
                "requires_approval": True,
                "default_route_alias": "coder",
                "required_stages": ["pre-push"],
            },
            "L4_dangerous": {
                "auto": False,
                "requires_approval": True,
                "default_route_alias": "architect-judge",
                "required_stages": ["architecture", "pre-push"],
            },
        },
    }


def _base_models() -> dict:
    return {
        "schema_version": "command-center.models.v1",
        "roles": {
            "triage": [],
            "planner": [],
            "coder": [],
            "architect-judge": [],
        },
    }


def _import_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                gates: dict, models: dict | None = None):
    gates_path = tmp_path / "gates.yaml"
    models_path = tmp_path / "models.yaml"
    gates_path.write_text(yaml.safe_dump(gates), encoding="utf-8")
    models_path.write_text(yaml.safe_dump(models or _base_models()), encoding="utf-8")
    monkeypatch.setenv("GATES_CONFIG", str(gates_path))
    monkeypatch.setenv("MODELS_CONFIG", str(models_path))
    monkeypatch.setenv("STANDARDS_CONFIG", "")
    name = f"judge_app_routing_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_judge_gate_loads_classify_routes_from_gates_config(tmp_path, monkeypatch):
    mod = _import_app(tmp_path, monkeypatch, _base_gates())

    assert mod.ROUTES_BY_RISK[mod.Risk.L0_READONLY] == "triage"
    assert mod.ROUTES_BY_RISK[mod.Risk.L1_PLAN] == "planner"
    assert mod.ROUTES_BY_RISK[mod.Risk.L2_LOCAL_CHANGE] == "coder"
    assert mod.ROUTES_BY_RISK[mod.Risk.L3_EXTERNAL_WRITE] == "coder"
    assert mod.ROUTES_BY_RISK[mod.Risk.L4_DANGEROUS] == "architect-judge"


def test_judge_gate_startup_fails_when_route_alias_missing(tmp_path, monkeypatch):
    gates = _base_gates()
    del gates["tiers"]["L0_read_only"]["default_route_alias"]

    with pytest.raises(RuntimeError, match="missing default_route_alias"):
        _import_app(tmp_path, monkeypatch, gates)


def test_judge_gate_startup_fails_when_route_alias_is_dangling(tmp_path, monkeypatch):
    gates = _base_gates()
    gates["tiers"]["L4_dangerous"]["default_route_alias"] = "ghost-role"

    with pytest.raises(RuntimeError, match="ghost-role"):
        _import_app(tmp_path, monkeypatch, gates)
