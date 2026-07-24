"""Adaptive-rubric eval contracts, pure scoring, parsing, and safety boundaries."""
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from command_center.improvement.frameworks import rubric_judge_runner as runner
from command_center.improvement.rubric import analyze_loss_patterns, score_rubric
from command_center.schemas.contracts import (
    FrameworkEvalSpec,
    FrameworkEvalsConfig,
    Rubric,
)

ROOT = Path(__file__).resolve().parents[1]


def _rubric(**overrides) -> Rubric:
    raw = {
        "id": "answer-quality",
        "criteria": [
            {
                "name": "correctness",
                "guidance": "The response must be factually correct.",
                "weight": 2,
                "scale": [1, 5],
            },
            {
                "name": "clarity",
                "guidance": "The response must be easy to understand.",
                "weight": 1,
                "scale": [1, 5],
            },
        ],
        "prompt_template": "Prompt: {prompt}\nResponse: {response}",
        "sampling_count": 3,
        "judge_role": "local-judge",
    }
    raw.update(overrides)
    return Rubric.model_validate(raw)


def _spec(**overrides) -> FrameworkEvalSpec:
    raw = {
        "enabled": False,
        "cli_command": "local-judge",
        "backend": "openai_compatible",
        "base_url_env": "OLLAMA_OPENAI_BASE_URL",
        "sample_budget": 20,
        "informs_role": "coder",
        "trust": "supporting_evidence_only",
        "judge_role": "local-judge",
        "sampling_count": 3,
    }
    raw.update(overrides)
    return FrameworkEvalSpec.model_validate(raw)


def test_rubric_schema_rejects_bad_weight_and_missing_placeholders():
    bad_weight = _rubric().model_dump()
    bad_weight["criteria"][0]["weight"] = 0
    with pytest.raises(ValidationError):
        Rubric.model_validate(bad_weight)

    with pytest.raises(ValidationError):
        _rubric(prompt_template="Only the prompt: {prompt}")


def test_rubric_schema_rejects_extra_fields_and_unbounded_sampling():
    with pytest.raises(ValidationError):
        _rubric(unexpected=True)
    with pytest.raises(ValidationError):
        _rubric(sampling_count=33)


def test_score_rubric_uses_sample_medians_weights_and_jury_agreement():
    verdict = score_rubric(
        _rubric(),
        {
            "correctness": [
                {"score": 5, "explanation": "correct"},
                {"score": 3, "explanation": "minor issue"},
                {"score": 5, "explanation": "correct"},
            ],
            "clarity": [2, 4, 4],
        },
    )

    assert verdict.criteria["correctness"].score == 5
    assert verdict.criteria["clarity"].score == 4
    assert verdict.criteria["correctness"].agreement == pytest.approx(1 / 3)
    assert verdict.criteria["correctness"].agreement_band == "fair"
    assert verdict.overall_score == pytest.approx((5 * 2 + 4) / 3)
    assert verdict.flagged is False


def test_score_rubric_never_fabricates_missing_scores_or_overall():
    verdict = score_rubric(
        _rubric(),
        {
            "correctness": [
                {"score": None, "explanation": "no score"},
                {"score": "5", "explanation": "numeric strings are not judge numbers"},
                {"explanation": "missing"},
                {"score": float("nan")},
                {"score": 99},
            ],
            "clarity": [{"score": 4, "explanation": "clear"}],
        },
    )

    missing = verdict.criteria["correctness"]
    assert missing.score is None
    assert missing.agreement is None
    assert missing.valid_samples == 0
    assert verdict.overall_score is None
    assert verdict.flagged is True
    assert verdict.missing_criteria == ("correctness",)


def test_score_rubric_rejects_unknown_criterion_instead_of_ignoring_it():
    with pytest.raises(ValueError, match="unknown rubric criteria"):
        score_rubric(_rubric(), {"hallucinated": [5]})


def test_loss_patterns_rank_missing_and_below_threshold_criteria():
    first = score_rubric(
        _rubric(),
        {"correctness": [2, 2], "clarity": [4, 4]},
    )
    second = score_rubric(
        _rubric(),
        {"correctness": [3, 3], "clarity": [1, 1]},
    )
    third = score_rubric(
        _rubric(),
        {"correctness": [5, 5], "clarity": [None, "missing"]},
    )

    losses = analyze_loss_patterns([first, second, third], threshold=4)
    assert losses.most_common() == [("clarity", 2), ("correctness", 2)]


def test_parse_rubric_judge_normalizes_each_criterion_and_preserves_none():
    results = runner.parse_rubric_judge(
        {
            "criteria": {
                "correctness": {"score": 4, "explanation": "mostly correct", "n_samples": 3},
                "clarity": {"explanation": "score omitted"},
                "safety": {"score": "5", "explanation": "wrong type"},
            }
        },
        runner.FRAMEWORK,
        _spec(),
    )
    by_criterion = {result.dataset: result for result in results}

    assert by_criterion["correctness"].score == 4
    assert by_criterion["correctness"].n_samples == 3
    assert "mostly correct" in by_criterion["correctness"].note
    assert by_criterion["clarity"].score is None
    assert by_criterion["safety"].score is None
    assert all(result.metric == "rubric_score" for result in results)
    assert all(result.trust == "supporting_evidence_only" for result in results)


def test_runner_never_auto_launches_and_uses_only_injected_executor():
    ready = runner.run(
        _spec(enabled=True),
        available_fn=lambda _command: (True, "local judge configured"),
    )
    assert ready[0].status == "ready"

    calls = []

    def fake_judge(spec):
        calls.append(spec)
        return {"correctness": {"score": 5, "explanation": "correct"}}

    results = runner.run(
        _spec(enabled=True),
        judge_runner=fake_judge,
        available_fn=lambda _command: (True, "local judge configured"),
    )
    assert len(calls) == 1
    assert results[0].score == 5
    assert results[0].is_decision_gate() is False


def test_rubric_judge_config_is_local_off_and_supporting_evidence_only():
    raw = yaml.safe_load(
        (ROOT / "configs" / "framework-evals.yaml").read_text(encoding="utf-8")
    )
    config = FrameworkEvalsConfig.model_validate(raw)
    spec = config.frameworks["rubric_judge"]

    assert spec.enabled is False
    assert spec.backend == "openai_compatible"
    assert spec.base_url_env == "OLLAMA_OPENAI_BASE_URL"
    assert spec.judge_role == "local-judge"
    assert spec.sampling_count == 3
    assert spec.trust == "supporting_evidence_only"

    promotion_paths = [
        ROOT / "src" / "command_center" / "improvement" / "promotion.py",
        *(ROOT / "services" / "judge_gate").rglob("*.py"),
    ]
    assert all(
        runner.FRAMEWORK not in path.read_text(encoding="utf-8")
        for path in promotion_paths
    )


def test_rubric_judge_config_rejects_nonlocal_or_unbounded_judge_settings():
    raw = yaml.safe_load(
        (ROOT / "configs" / "framework-evals.yaml").read_text(encoding="utf-8")
    )
    raw["frameworks"]["rubric_judge"]["judge_role"] = "cloud-judge"
    with pytest.raises(ValidationError):
        FrameworkEvalsConfig.model_validate(raw)

    raw["frameworks"]["rubric_judge"]["judge_role"] = "local-judge"
    raw["frameworks"]["rubric_judge"]["sampling_count"] = 33
    with pytest.raises(ValidationError):
        FrameworkEvalsConfig.model_validate(raw)
