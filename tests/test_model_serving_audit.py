from __future__ import annotations

import json

import pytest

from command_center.improvement import model_serving_audit


def _measure_factory(model, *, input_tokens, output_tokens, base_url):
    assert model == "candidate:latest"
    assert input_tokens == 12000
    assert output_tokens == 2500
    assert base_url == "http://ollama.test"
    return lambda: object()


def test_serving_audit_uses_committed_scenario_and_writes_evidence(tmp_path):
    def fake_sweep(measure, scenario_name, **kwargs):
        assert measure() is not None
        assert scenario_name == "repo_triage"
        assert kwargs["concurrency_points"] == [1, 2, 4, 8, 16]
        assert kwargs["slo_p90_ttft_s"] == 4
        assert kwargs["slo_p90_ttlt_s"] == 90
        return {
            "scenario": scenario_name,
            "sweep": [{"concurrency": 1, "rps": 0.5}],
            "operating_point": {"found": True, "concurrency": 1, "rps": 0.5},
        }

    output = tmp_path / "serving.json"
    summary = model_serving_audit.run_serving_audit(
        model="candidate:latest",
        scenario_name="repo_triage",
        base_url="http://ollama.test",
        output_path=output,
        measure_factory=_measure_factory,
        sweep_runner=fake_sweep,
    )

    assert summary["status"] == "passed"
    assert len(summary["endpoint_sha256"]) == 64
    assert summary["routing_changed"] is False
    assert summary["promotion_allowed"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed"


def test_serving_audit_fails_when_no_operating_point_meets_slo(tmp_path):
    def fake_sweep(*args, **kwargs):
        return {
            "scenario": "repo_triage",
            "sweep": [],
            "operating_point": {"found": False, "reason": "no point met SLO"},
        }

    summary = model_serving_audit.run_serving_audit(
        model="candidate:latest",
        scenario_name="repo_triage",
        base_url="http://ollama.test",
        output_path=tmp_path / "failed.json",
        measure_factory=_measure_factory,
        sweep_runner=fake_sweep,
    )
    assert summary["status"] == "failed"


def test_serving_audit_rejects_unknown_scenario(tmp_path):
    with pytest.raises(RuntimeError, match="unknown serving scenario"):
        model_serving_audit.run_serving_audit(
            model="candidate:latest",
            scenario_name="invented",
            base_url="http://ollama.test",
            output_path=tmp_path / "unused.json",
        )
