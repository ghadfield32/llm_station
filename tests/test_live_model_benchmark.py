from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from command_center.improvement.live_model_benchmark import (
    TARGET_REF,
    LiveModelBenchmarkHarness,
)
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import EquivalenceError, ExperimentRunner, HARNESSES
from command_center.improvement.schema import ExperimentDefinition

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_model_benchmark_config(root: Path, *, description: str = "fixture suite") -> Path:
    config = {
        "schema_version": "command-center.model-benchmarks.v1",
        "defaults": {
            "timeout_seconds": 30,
            "temperature": 0,
            "num_predict": 32,
        },
        "suites": {
            "planner": {
                "role": "planner",
                "description": description,
                "metric_policy": {
                    "primary": ["json_quality", "safety_quality"],
                    "hard_non_regression": [
                        "invalid_response_rate",
                        "unsafe_output_rate",
                    ],
                    "supporting": ["median_latency_ms", "tokens_per_second"],
                    "directions": {
                        "json_quality": "increase",
                        "safety_quality": "increase",
                        "invalid_response_rate": "decrease",
                        "unsafe_output_rate": "decrease",
                        "median_latency_ms": "decrease",
                        "tokens_per_second": "increase",
                    },
                },
                "cases": [
                    {
                        "id": "valid_json",
                        "response_format": "json",
                        "metric_tags": ["json_quality"],
                        "prompt": "case valid_json",
                        "required_json_keys": ["route", "escalate"],
                        "expected_json_values": {"route": "coder", "escalate": True},
                        "forbidden_contains": ["leak"],
                        "safety": True,
                    },
                    {
                        "id": "unsafe_text",
                        "metric_tags": ["safety_quality"],
                        "prompt": "case unsafe_text",
                        "expected_contains": ["approved"],
                        "forbidden_contains": ["leak"],
                        "safety": True,
                    },
                    {
                        "id": "invalid_json",
                        "response_format": "json",
                        "metric_tags": ["json_quality"],
                        "prompt": "case invalid_json",
                        "required_json_keys": ["route"],
                        "expected_json_values": {"route": "planner"},
                        "safety": True,
                    },
                ],
            }
        },
    }
    config_path = root / "configs" / "model-benchmarks.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def _experiment(**params) -> ExperimentDefinition:
    model_params = {
        "role": "planner",
        "suite": "planner",
        "baseline_model": "baseline-local",
        "candidate_model": "candidate-local",
        "suite_path": "configs/model-benchmarks.yaml",
        "base_url": "http://ollama.test",
    }
    model_params.update(params)
    return ExperimentDefinition.model_validate({
        "experiment_id": "EXP-live-model-001",
        "title": "Live local model benchmark",
        "owner": "geoff",
        "target_type": "model",
        "target_ref": TARGET_REF,
        "problem_statement": "Evaluate a local open-weight model candidate.",
        "hypothesis": "The candidate improves task success without safety regression.",
        "baseline": "baseline-local on planner suite",
        "candidate": "candidate-local on planner suite",
        "parameters": {"model_benchmark": model_params},
        "risk_tier": "L2_local_edits",
        "metrics": [
            {
                "name": "task_success_rate",
                "direction": "increase",
                "required": True,
                "baseline_source": "live_model_benchmark baseline",
                "candidate_source": "live_model_benchmark candidate",
                "minimum_improvement": 0.01,
                "maximum_regression": 0.0,
            },
            {
                "name": "unsafe_output_rate",
                "direction": "decrease",
                "required": True,
                "safety": True,
                "baseline_source": "live_model_benchmark baseline",
                "candidate_source": "live_model_benchmark candidate",
                "maximum_regression": 0.0,
            },
            {
                "name": "invalid_response_rate",
                "direction": "decrease",
                "required": True,
                "safety": True,
                "baseline_source": "live_model_benchmark baseline",
                "candidate_source": "live_model_benchmark candidate",
                "maximum_regression": 0.0,
            },
        ],
        "budgets": {
            "max_iterations": 3,
            "max_wall_minutes": 10,
            "max_input_tokens": 0,
            "max_output_tokens": 0,
            "max_cost_usd": 0,
            "max_gpu_hours": 1,
            "max_changed_files": 0,
            "max_diff_lines": 0,
        },
        "verification": {
            "independent_context": True,
            "allow_self_verification": False,
            "reproduce_commands": [
                "python -m command_center.cli.improvement verify EXP-live-model-001"
            ],
            "required_evidence": ["raw redacted benchmark logs", "metric summary"],
        },
        "promotion": {
            "human_approval_required": True,
            "canary_required": True,
            "rollback_required": True,
            "automatic_promotion": False,
        },
        "post_watch": {
            "checkpoints": ["1h", "24h", "7d"],
            "monitored_metrics": ["task_success_rate", "unsafe_output_rate"],
            "rollback_triggers": [
                "task_success_rate regresses vs promoted baseline",
                "a safety metric regresses",
            ],
        },
    })


def test_live_model_harness_registered():
    assert TARGET_REF in HARNESSES


def test_live_model_benchmark_records_redacted_ledger_artifacts(tmp_path, monkeypatch):
    def fake_generate(self, model, prompt, **kwargs):
        if model == "baseline-local":
            return {"response": "not enough evidence", "eval_count": 3,
                    "eval_duration": 1_000_000_000}
        if "numbered steps" in prompt:
            text = "1. inspect\n2. test\n3. review"
        else:
            text = "approval required before delete"
        return {"response": text, "eval_count": 9, "eval_duration": 1_000_000_000}

    monkeypatch.setattr(LiveModelBenchmarkHarness, "_generate", fake_generate)
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    defn = _experiment()
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(REPO_ROOT), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)
    cmp = runner.run_candidate(defn.experiment_id, reps=1)
    assert cmp.all_required_pass and cmp.safety_ok

    artifacts = reg.artifacts(defn.experiment_id)
    stdout_path = next(Path(a["path"]) for a in artifacts if a["kind"] == "stdout"
                       and "candidate" in a["path"])
    log = stdout_path.read_text(encoding="utf-8")
    assert "output_sha256=" in log
    assert "approval required before delete" not in log
    assert "1. inspect" not in log
    assert "Return exactly three" not in log

    equivalence_path = next(Path(a["path"]) for a in artifacts if a["kind"] == "equivalence"
                            and "candidate" in a["path"])
    eq = json.loads(equivalence_path.read_text(encoding="utf-8"))
    assert eq["suite"] == "planner"
    assert eq["baseline_model"] == "baseline-local"
    assert eq["candidate_model"] == "candidate-local"
    assert "base_url_sha256" in eq and "ollama.test" not in json.dumps(eq)


def test_live_model_benchmark_requires_explicit_parameters():
    defn = _experiment()
    raw = defn.model_dump(mode="json")
    del raw["parameters"]["model_benchmark"]["base_url"]
    with pytest.raises(RuntimeError, match="base_url or base_url_env"):
        LiveModelBenchmarkHarness(REPO_ROOT, ExperimentDefinition.model_validate(raw))


def test_live_model_benchmark_rejects_invalid_context_length():
    defn = _experiment(context_length=0)

    with pytest.raises(RuntimeError, match="context_length"):
        LiveModelBenchmarkHarness(REPO_ROOT, defn)


def test_model_benchmark_json_cases_require_explicit_json_format(tmp_path):
    config_path = _write_model_benchmark_config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    del config["suites"]["planner"]["cases"][0]["response_format"]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    defn = _experiment(suite_path="configs/model-benchmarks.yaml")

    with pytest.raises(ValueError, match="response_format"):
        LiveModelBenchmarkHarness(tmp_path, defn)


def test_live_model_benchmark_passes_explicit_context_to_ollama(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "ok"}

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, path, json):
            calls.append({"path": path, "json": json, "client": self.kwargs})
            return FakeResponse()

    monkeypatch.setattr(
        "command_center.improvement.live_model_benchmark.httpx.Client",
        FakeClient,
    )
    defn = _experiment(context_length=32768)
    harness = LiveModelBenchmarkHarness(REPO_ROOT, defn)

    generated = harness._generate("baseline-local", "prompt", response_format="json")

    assert generated["response"] == "ok"
    assert harness.equivalence_key()["evaluated_context"] == 32768
    assert calls[0]["json"]["options"]["num_ctx"] == 32768
    assert calls[0]["json"]["options"]["temperature"] == 0
    assert calls[0]["json"]["format"] == "json"
    assert calls[0]["path"] == "/api/generate"


def test_live_model_benchmark_scores_json_invalid_and_metric_tags(tmp_path, monkeypatch):
    _write_model_benchmark_config(tmp_path)

    def fake_generate(self, model, prompt, **kwargs):
        if "invalid_json" in prompt:
            text = "not json"
        elif "valid_json" in prompt:
            text = json.dumps({"route": "coder", "escalate": True})
        elif "unsafe_text" in prompt:
            text = "approved leak"
        else:
            raise AssertionError(prompt)
        return {"response": text, "eval_count": 4, "eval_duration": 1_000_000_000}

    monkeypatch.setattr(LiveModelBenchmarkHarness, "_generate", fake_generate)
    defn = _experiment(suite_path="configs/model-benchmarks.yaml")
    harness = LiveModelBenchmarkHarness(tmp_path, defn)

    result = harness.measure("baseline", reps=1)

    assert result.sample_count == 3
    assert result.metric_values["task_success_rate"] == pytest.approx(1 / 3)
    assert result.metric_values["unsafe_output_rate"] == pytest.approx(1 / 3)
    assert result.metric_values["invalid_response_rate"] == pytest.approx(1 / 3)
    assert result.metric_values["json_quality"] == pytest.approx(0.5)
    assert result.metric_values["safety_quality"] == pytest.approx(0.0)
    assert result.samples["json_quality"] == [1.0, 0.0]
    assert result.samples["safety_quality"] == [0.0]
    assert "unsafe_text: forbidden marker present" in result.failures
    assert "invalid_json: invalid structured response" in result.failures
    assert "approved leak" not in result.raw_log
    assert "not json" not in result.raw_log
    assert "output_sha256=" in result.raw_log


def test_live_model_benchmark_excludes_candidate_when_suite_changes(tmp_path, monkeypatch):
    _write_model_benchmark_config(tmp_path, description="baseline fixture")

    def fake_generate(self, model, prompt, **kwargs):
        return {
            "response": json.dumps({"route": "coder", "escalate": True}),
            "eval_count": 4,
            "eval_duration": 1_000_000_000,
        }

    monkeypatch.setattr(LiveModelBenchmarkHarness, "_generate", fake_generate)
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    defn = _experiment(suite_path="configs/model-benchmarks.yaml")
    reg.register(defn)
    runner = ExperimentRunner(reg, repo_root=str(tmp_path), evidence_root=str(tmp_path / "ev"))
    runner.run_baseline(defn.experiment_id, reps=1)

    _write_model_benchmark_config(tmp_path, description="candidate fixture drift")

    with pytest.raises(EquivalenceError):
        runner.run_candidate(defn.experiment_id, reps=1)

    excluded = [r for r in reg.runs(defn.experiment_id, role="candidate")
                if r["status"] == "excluded"]
    assert len(excluded) == 1
    assert excluded[0]["excluded_reason"] == "baseline/candidate equivalence lost"
    changed = excluded[0]["metrics"]["changed_equivalence_fields"]
    assert "benchmark_config_hash" in changed
    assert "suite_hash" in changed
