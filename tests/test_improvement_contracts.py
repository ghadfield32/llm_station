"""Contract tests for the improvement-experiment schema.

Deterministic, no network, no model calls. These prove the dangerous experiment
configurations are *rejected before they run* — the negative tests the existing
suite was missing for this subsystem. Each rejection maps to a mission requirement
in section 3 / 14 / 18.
"""
from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from command_center.improvement.schema import (
    ExperimentDefinition,
    ImprovementConfig,
)


def _valid_experiment() -> dict:
    """A minimal experiment that satisfies every contract rule. Each rejection
    test mutates exactly one thing so the failing reason is unambiguous."""
    return {
        "experiment_id": "EXP-test-001",
        "title": "test experiment",
        "owner": "geoff",
        "target_type": "retrieval",
        "target_ref": "command_center.improvement.retrieval_strategies",
        "problem_statement": "p",
        "hypothesis": "h",
        "baseline": "current behavior",
        "candidate": "proposed behavior",
        "risk_tier": "L2_local_edits",
        "metrics": [
            {
                "name": "recall_at_5",
                "direction": "increase",
                "required": True,
                "baseline_source": "b",
                "candidate_source": "c",
                "maximum_regression": 0.0,
            },
            {
                "name": "secret_exclusion",
                "direction": "increase",
                "required": True,
                "safety": True,
                "baseline_source": "b",
                "candidate_source": "c",
                "maximum_regression": 0.0,
            },
        ],
        "budgets": {
            "max_iterations": 3,
            "max_wall_minutes": 10,
            "max_input_tokens": 0,
            "max_output_tokens": 0,
            "max_cost_usd": 0,
            "max_gpu_hours": 0,
            "max_changed_files": 5,
            "max_diff_lines": 400,
        },
        "verification": {
            "independent_context": True,
            "reproduce_commands": ["python -m command_center.cli.improvement verify EXP-test-001"],
            "required_evidence": ["raw logs", "metric summary"],
        },
        "promotion": {
            "human_approval_required": True,
            "canary_required": True,
            "rollback_required": True,
            "automatic_promotion": False,
        },
        "post_watch": {
            "checkpoints": ["1h", "24h", "7d"],
            "monitored_metrics": ["recall_at_5"],
            "rollback_triggers": ["secret_exclusion drops below 1.0"],
        },
    }


def test_valid_experiment_passes():
    exp = ExperimentDefinition.model_validate(_valid_experiment())
    assert exp.experiment_id == "EXP-test-001"
    assert any(m.required for m in exp.metrics)


def test_shipped_improvement_yaml_validates():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "configs/improvement.yaml").read_text(encoding="utf-8"))
    cfg = ImprovementConfig.model_validate(data)
    assert cfg.experiments and cfg.experiments[0].experiment_id == "EXP-retrieval-rank-001"


# ---- the rejection table (mission section 3 / 14) ---------------------------

def _reject(mutate) -> str:
    exp = _valid_experiment()
    mutate(exp)
    with pytest.raises(ValidationError) as ei:
        ExperimentDefinition.model_validate(exp)
    return str(ei.value)


def test_rejects_automatic_promotion():
    msg = _reject(lambda e: e["promotion"].update(automatic_promotion=True))
    assert "automatic_promotion" in msg


def test_rejects_human_approval_disabled():
    msg = _reject(lambda e: e["promotion"].update(human_approval_required=False))
    assert "human_approval_required" in msg


def test_rejects_missing_rollback():
    msg = _reject(lambda e: e["promotion"].update(rollback_required=False))
    assert "rollback_required" in msg


def test_rejects_missing_baseline():
    msg = _reject(lambda e: e.update(baseline=""))
    assert "baseline" in msg


def test_rejects_no_required_metric():
    def mutate(e):
        for m in e["metrics"]:
            m["required"] = False
            m["safety"] = False
    msg = _reject(mutate)
    assert "required metric" in msg


def test_rejects_unbounded_safety_metric():
    # a safety metric with no maximum_regression == safety may regress without limit
    def mutate(e):
        e["metrics"][1].pop("maximum_regression", None)
    msg = _reject(mutate)
    assert "maximum_regression" in msg


def test_rejects_self_verification():
    msg = _reject(lambda e: e["verification"].update(allow_self_verification=True))
    assert "self_verification" in msg


def test_rejects_independent_context_off():
    msg = _reject(lambda e: e["verification"].update(independent_context=False))
    assert "independent_context" in msg


def test_rejects_missing_budget_field():
    msg = _reject(lambda e: e["budgets"].pop("max_iterations"))
    assert "max_iterations" in msg


def test_rejects_l3_experiment():
    msg = _reject(lambda e: e.update(risk_tier="L3_external_write"))
    assert "L3" in msg or "risk_tier" in msg


def test_rejects_l4_experiment():
    msg = _reject(lambda e: e.update(risk_tier="L4_dangerous"))
    assert "L4" in msg or "risk_tier" in msg


def test_rejects_secret_bearing_repo_task():
    msg = _reject(lambda e: e.update(requests_secrets=True))
    assert "secret" in msg.lower()


def test_rejects_raw_evidence_retention_disabled():
    msg = _reject(lambda e: e.update(retain_raw_evidence=False))
    assert "raw-evidence" in msg or "raw" in msg.lower()


def test_rejects_evidence_without_raw_logs():
    # required_evidence that keeps only a summary (no raw logs/artifacts) is refused
    msg = _reject(lambda e: e["verification"].update(required_evidence=["a polished summary"]))
    assert "raw evidence" in msg.lower()


def test_rejects_control_plane_target_without_elevated_review():
    def mutate(e):
        e["target_ref"] = "services/ledger/app.py"
        # elevated_human_review defaults False
    msg = _reject(mutate)
    assert "elevated_human_review" in msg or "control-plane" in msg


def test_accepts_control_plane_target_with_elevated_review():
    exp = _valid_experiment()
    exp["target_ref"] = "services/ledger/app.py"
    exp["promotion"]["elevated_human_review"] = True
    # still valid — elevated review is the gate, not a blanket ban
    ExperimentDefinition.model_validate(exp)


def test_rejects_empty_rollback_triggers():
    msg = _reject(lambda e: e["post_watch"].update(rollback_triggers=[]))
    assert "rollback_triggers" in msg


def test_rejects_post_watch_unknown_metric():
    msg = _reject(lambda e: e["post_watch"].update(monitored_metrics=["nonexistent_metric"]))
    assert "unknown metric" in msg


def test_rejects_extra_unknown_key():
    # extra="forbid" everywhere — a typo'd key fails loudly
    msg = _reject(lambda e: e.update(automatic_promotionn=True))
    assert "automatic_promotionn" in msg or "Extra" in msg or "extra" in msg


def test_rejects_duplicate_experiment_ids():
    exp = _valid_experiment()
    dup = copy.deepcopy(exp)
    with pytest.raises(ValidationError) as ei:
        ImprovementConfig.model_validate(
            {"schema_version": "v1", "experiments": [exp, dup]}
        )
    assert "duplicate experiment_id" in str(ei.value)
