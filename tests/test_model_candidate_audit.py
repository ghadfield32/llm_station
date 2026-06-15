from __future__ import annotations

from command_center.improvement import model_candidate_audit
from command_center.improvement.live_model_benchmark import LiveModelBenchmarkHarness


def _coder_fake_generate(self, model, prompt):
    if "x + 1" in prompt:
        text = "return x + 1"
    elif "empty list" in prompt:
        text = "the test should assert an error, not a fake empty value"
    elif "except Exception: pass" in prompt:
        text = "the core defect is swallowing the exception"
    else:
        raise AssertionError(prompt)
    return {"response": text, "eval_count": 7, "eval_duration": 1_000_000_000}


def test_model_candidate_audit_runs_isolated_tie_as_revise(tmp_path, monkeypatch):
    monkeypatch.setattr(LiveModelBenchmarkHarness, "_generate", _coder_fake_generate)

    summary = model_candidate_audit.run_candidate_audit(
        role="coder",
        baseline_model="qwen3-coder:30b",
        candidate_model="devstral:24b",
        base_url="http://ollama.test",
        base_url_env=None,
        reps=1,
        context_length=32768,
        fit_ctx=None,
        gpu_budget_gb=None,
        db_path=tmp_path / "candidate-audit.db",
        evidence_root=tmp_path / "candidate-audit-evidence",
        summary_path=tmp_path / "candidate-audit-summary.json",
    )

    assert summary["status"] == "completed"
    assert summary["evaluated_context"] == 32768
    assert summary["comparison"]["recommendation"] == "revise"
    assert summary["comparison"]["note"] == "no required non-safety metric improved"
    assert summary["verifier"]["verdict"] == "PASS"
    assert {artifact["kind"] for artifact in summary["artifacts"]} >= {
        "stdout",
        "metrics",
        "equivalence",
        "statistics",
        "verifier_report",
    }


def test_model_candidate_audit_requires_context_or_fit_inputs():
    try:
        model_candidate_audit._resolve_context(
            baseline_model="qwen3-coder:30b",
            candidate_model="devstral:24b",
            base_url="http://ollama.test",
            context_length=None,
            fit_ctx=None,
            gpu_budget_gb=None,
        )
    except RuntimeError as exc:
        assert "fit_ctx is required" in str(exc)
    else:
        raise AssertionError("expected context resolution to fail")
