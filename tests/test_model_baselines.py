from __future__ import annotations

import pytest

from command_center.improvement import model_baselines


def test_model_baseline_definition_reads_incumbent_from_models_yaml():
    defn = model_baselines.build_definition(
        role="coder",
        base_url=None,
        base_url_env="OLLAMA_BASE_URL",
        reps=2,
    )

    params = defn.parameters["model_benchmark"]
    assert params["baseline_model"] == "qwen3-coder:30b"
    assert params["candidate_model"] == "__NO_CHALLENGER_SELECTED__"
    assert params["suite"] == "coder"
    assert params["base_url_env"] == "OLLAMA_BASE_URL"
    assert "coder" in defn.experiment_id
    assert {m.name for m in defn.metrics} >= {
        "task_success",
        "no_swallowed_exceptions",
        "median_latency_ms",
    }
    assert defn.budgets.max_iterations == 2
    assert defn.budgets.max_output_tokens == 960


def test_model_baseline_definition_requires_explicit_endpoint():
    with pytest.raises(RuntimeError, match="base_url or base_url_env"):
        model_baselines.build_definition(
            role="coder",
            base_url=None,
            base_url_env=None,
            reps=1,
        )


def test_model_baseline_definition_rejects_missing_suite():
    with pytest.raises(RuntimeError, match="no suite"):
        model_baselines.build_definition(
            role="missing-role",
            base_url=None,
            base_url_env="OLLAMA_BASE_URL",
            reps=1,
        )
