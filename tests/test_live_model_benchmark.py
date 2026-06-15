from __future__ import annotations

import json
from pathlib import Path

import pytest

from command_center.improvement.live_model_benchmark import (
    TARGET_REF,
    LiveModelBenchmarkHarness,
)
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner, HARNESSES
from command_center.improvement.schema import ExperimentDefinition

REPO_ROOT = Path(__file__).resolve().parents[1]


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
    def fake_generate(self, model, prompt):
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
