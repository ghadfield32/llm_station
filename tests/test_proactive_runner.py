"""Proactive runner evidence-collection contract — the root-cause fix.

Proves the runner NEVER fabricates evidence: a check whose evidence keys are not
all backed by a registered collector is skipped (no judge call, no mission). Once
a collector is wired, the same check runs for real. Loaded by path because the
runner is a standalone service module, not part of the package.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SVC = Path(__file__).resolve().parents[1] / "services" / "proactive_runner"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # so app.py's `from collectors import ...` resolves
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner():
    """Fresh collectors registry + app each test (registry is module-global)."""
    collectors = _load("collectors", SVC / "collectors.py")
    app = _load("proactive_app_under_test", SVC / "app.py")
    collectors.COLLECTORS.clear()
    return app, collectors


def test_collect_evidence_empty_registry_marks_all_unwired(runner):
    _, collectors = runner
    check = {"name": "c", "target": "t", "evidence": ["a", "b"]}
    evidence, unwired = collectors.collect_evidence(check)
    assert evidence == {}
    assert sorted(unwired) == ["a", "b"]


def test_collect_evidence_returns_real_values_when_wired(runner):
    _, collectors = runner

    @collectors.collector("a")
    def _a(check):
        return {"value": f"real-a-for-{check['target']}"}

    check = {"name": "c", "target": "t", "evidence": ["a", "b"]}
    evidence, unwired = collectors.collect_evidence(check)
    assert evidence == {"a": {"value": "real-a-for-t"}}
    assert unwired == ["b"]           # b still unwired


def test_run_check_skips_unwired_without_calling_judge(runner, monkeypatch):
    app, _ = runner
    # If the runner ever called the judge on unwired evidence, this fails loudly.
    monkeypatch.setattr(app, "ask_judges",
                        lambda *a, **k: pytest.fail("judge called on unwired evidence"))
    check = {"name": "dag-freshness-daily", "target": "airflow",
             "evidence": ["dag_runs", "task_logs"], "on_fail": "open_rca_mission"}
    result = app.run_check(check)
    assert result["result"] == "skipped"
    assert sorted(result["unwired_evidence"]) == ["dag_runs", "task_logs"]


def test_run_check_judges_when_fully_wired(runner, monkeypatch):
    app, collectors = runner

    @collectors.collector("metrics")
    def _m(check):
        return {"p95_ms": 12}

    monkeypatch.setattr(app, "ask_judges",
                        lambda check, ev: {"healthy": True, "summary": "ok"})
    recorded = {}
    monkeypatch.setattr(app, "record_event",
                        lambda *a, **k: recorded.setdefault("called", True))
    check = {"name": "svc-perf", "target": "services", "evidence": ["metrics"],
             "on_fail": "ledger_report"}
    result = app.run_check(check)
    assert result == {"name": "svc-perf", "result": "healthy"}
    assert recorded.get("called") is True
