"""External framework-runner tests: config contract, availability gate, result parsing, and
the fail-soft control flow. No heavy tool is ever launched (the executor is injected)."""
from pathlib import Path

import pytest
import yaml

from command_center.improvement.frameworks import availability, bigcodebench_runner
from command_center.improvement.frameworks import evalplus_runner as ep
from command_center.improvement.frameworks.runner import FrameworkResult
from command_center.schemas import FrameworkEvalsConfig, FrameworkEvalSpec

ROOT = Path(__file__).resolve().parents[1]


def _spec(**over):
    base = {
        "enabled": False, "cli_command": "evalplus.evaluate", "backend": "openai_compatible",
        "base_url_env": "OLLAMA_OPENAI_BASE_URL", "sample_budget": 20, "informs_role": "coder",
        "trust": "supporting_evidence_only", "datasets": ["humaneval_plus"]}
    base.update(over)
    return FrameworkEvalSpec.model_validate(base)


# ---- config contract --------------------------------------------------------

def test_real_framework_config_validates():
    raw = yaml.safe_load(
        (ROOT / "configs" / "framework-evals.yaml").read_text(encoding="utf-8"))
    cfg = FrameworkEvalsConfig.model_validate(raw)
    assert "evalplus" in cfg.frameworks
    assert cfg.frameworks["evalplus"].enabled is False        # off by default


def test_trust_is_pinned_to_supporting_evidence_only():
    with pytest.raises(ValueError):
        _spec(trust="promotion_gate")
    with pytest.raises(ValueError):
        _spec(sample_budget=0)


# ---- availability gate ------------------------------------------------------

def test_availability_false_for_absent_tool():
    ok, why = availability("definitely-not-installed-xyz.evaluate")
    assert ok is False and "not installed" in why


def test_availability_true_for_importable_module():
    ok, _ = availability("json.tool")     # the stdlib json module is importable
    assert ok is True


# ---- EvalPlus parsing -------------------------------------------------------

def test_parse_evalplus_nested_and_flat():
    nested = ep.parse_evalplus(
        {"humaneval+": {"pass@1": 0.63}, "mbpp+": {"pass@1": 0.55}}, "evalplus", _spec())
    by_ds = {r.dataset: r for r in nested}
    assert by_ds["humaneval+"].score == pytest.approx(0.63)
    assert by_ds["mbpp+"].metric == "pass@1"
    assert all(not r.is_decision_gate() for r in nested)
    assert all(r.trust == "supporting_evidence_only" for r in nested)
    flat = ep.parse_evalplus({"pass@1": 0.7}, "evalplus", _spec())
    assert flat[0].score == pytest.approx(0.7)


def test_parse_evalplus_garbage_is_error_not_fake_score():
    res = ep.parse_evalplus({"unexpected": 123}, "evalplus", _spec())
    # 'unexpected' isn't a pass@1 dict -> score stays None, never invented
    assert res[0].score is None


# ---- BigCodeBench parsing ---------------------------------------------------

def test_parse_bigcodebench_flat_and_split():
    flat = bigcodebench_runner.parse_bigcodebench(
        {"pass@1": 0.45}, "bigcodebench", _spec(cli_command="bigcodebench.evaluate", subset="hard"))
    assert flat[0].score == pytest.approx(0.45) and flat[0].dataset == "hard"
    split = bigcodebench_runner.parse_bigcodebench(
        {"complete": {"pass@1": 0.4}, "instruct": {"pass@1": 0.3}}, "bigcodebench",
        _spec(cli_command="bigcodebench.evaluate", subset="hard"))
    assert {r.dataset for r in split} == {"hard/complete", "hard/instruct"}


# ---- fail-soft control flow -------------------------------------------------

def test_run_disabled_returns_disabled_status():
    res = ep.run(_spec(enabled=False))
    assert res[0].status == "disabled"


def test_run_unavailable_is_soft_not_a_failure():
    res = ep.run(_spec(enabled=True), available_fn=lambda _c: (False, "not installed"))
    assert res[0].status == "unavailable"        # soft: supporting evidence absent, not an error


def test_run_available_but_no_executor_is_ready_never_auto_runs():
    res = ep.run(_spec(enabled=True), available_fn=lambda _c: (True, "on PATH"))
    assert res[0].status == "ready"              # never launches the heavy tool on its own


def test_run_with_injected_executor_parses_results():
    res = ep.run(
        _spec(enabled=True),
        available_fn=lambda _c: (True, "on PATH"),
        subprocess_runner=lambda _spec: {"humaneval+": {"pass@1": 0.61}})
    assert res[0].status == "ok"
    assert res[0].score == pytest.approx(0.61)
    assert res[0].is_decision_gate() is False    # external result is never a promotion gate


def test_run_executor_failure_is_captured_as_error():
    def boom(_spec):
        raise RuntimeError("evalplus blew up")
    res = ep.run(_spec(enabled=True), available_fn=lambda _c: (True, "on PATH"),
                 subprocess_runner=boom)
    assert res[0].status == "error" and "blew up" in res[0].note


def test_framework_result_is_never_a_decision_gate():
    r = FrameworkResult(framework="x", informs_role="coder", status="ok", note="n",
                        metric="pass@1", score=0.9)
    assert r.is_decision_gate() is False
