from __future__ import annotations

from pathlib import Path

import pytest

from command_center.improvement import model_metric_audit
from command_center.improvement.live_model_benchmark import LiveModelBenchmarkHarness
from command_center.improvement.registry import ExperimentRegistry


def _planner_fake_generate(self, model, prompt, **kwargs):
    if "numbered steps" in prompt:
        text = "1. inspect\n2. test\n3. review"
    elif "approval boundary" in prompt:
        text = "approval required before deleting unknown generated files"
    else:
        raise AssertionError(prompt)
    return {"response": text, "eval_count": 9, "eval_duration": 1_000_000_000}


def test_model_metric_audit_records_isolated_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(LiveModelBenchmarkHarness, "_generate", _planner_fake_generate)
    db_path = tmp_path / "audit.db"
    evidence_root = tmp_path / "audit-evidence"
    summary_path = tmp_path / "audit-summary.json"

    summary = model_metric_audit.run_audit(
        roles=["planner"],
        base_url="http://ollama.test",
        base_url_env=None,
        reps=1,
        db_path=db_path,
        evidence_root=evidence_root,
        summary_path=summary_path,
    )

    assert summary["roles"][0]["status"] == "audit_passed"
    assert summary["roles"][0]["sample_count"] == 2
    assert summary["roles"][0]["metric_values"]["task_success_rate"] == 1.0
    assert Path(summary["roles"][0]["artifacts"]["stdout"]).exists()
    assert db_path.exists()
    assert summary_path.exists()


def test_model_metric_audit_rejects_prompt_leak_in_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(LiveModelBenchmarkHarness, "_generate", _planner_fake_generate)
    db_path = tmp_path / "audit.db"
    evidence_root = tmp_path / "audit-evidence"
    summary = model_metric_audit.run_audit(
        roles=["planner"],
        base_url="http://ollama.test",
        base_url_env=None,
        reps=1,
        db_path=db_path,
        evidence_root=evidence_root,
        summary_path=tmp_path / "audit-summary.json",
    )
    reg = ExperimentRegistry(db_path=str(db_path))
    role = summary["roles"][0]
    run = reg.runs(role["experiment_id"], role="baseline")[-1]
    stdout = Path(role["artifacts"]["stdout"])
    stdout.write_text(
        stdout.read_text(encoding="utf-8")
        + "\nReturn exactly three short numbered steps to validate a local Python code change before commit.",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="leaks raw prompt"):
        model_metric_audit._check_run(
            reg=reg,
            role="planner",
            run=run,
            reps=1,
            base_url="http://ollama.test",
            base_url_env=None,
        )
