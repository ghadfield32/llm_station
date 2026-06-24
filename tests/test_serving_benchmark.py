"""Serving-benchmark tests: Ollama timing parse, SLO analysis, and config validation.

No live Ollama — the timing parser is fed synthetic /api/generate payloads, and the analysis
is pure. These guard the "quality_eval != serving_eval" gate.
"""
from pathlib import Path

import pytest
import yaml

from command_center.improvement import serving_slo as slo
from command_center.improvement.schema import ServingBenchmarksConfig
from command_center.improvement.serving_benchmark import (
    ServingBenchmarkError, parse_ollama_timings,
)

NS = 1_000_000_000
ROOT = Path(__file__).resolve().parents[1]


# ---- Ollama timing parse (TTFT / ITL / TTLT) --------------------------------

def _resp(**over):
    base = {
        "load_duration": 1 * NS, "prompt_eval_duration": 2 * NS, "prompt_eval_count": 3000,
        "eval_count": 100, "eval_duration": 5 * NS, "total_duration": 8 * NS,
    }
    base.update(over)
    return base


def test_parse_ollama_timings_computes_three_numbers():
    s = parse_ollama_timings(_resp())
    assert s.ttft_s == pytest.approx(3.0)        # (load 1s + prompt_eval 2s)
    assert s.itl_s == pytest.approx(0.05)        # 5s / 100 tokens
    assert s.ttlt_s == pytest.approx(8.0)        # total
    assert s.output_tokens == 100 and s.input_tokens == 3000


def test_parse_ollama_timings_raises_on_missing_field():
    bad = _resp()
    del bad["eval_duration"]
    with pytest.raises(ServingBenchmarkError, match="missing required timing"):
        parse_ollama_timings(bad)


def test_parse_ollama_timings_raises_on_zero_output():
    with pytest.raises(ServingBenchmarkError, match="no tokens generated"):
        parse_ollama_timings(_resp(eval_count=0))


# ---- pure SLO analysis ------------------------------------------------------

def test_percentile_interpolates_and_guards_empty():
    samples = [10, 20, 30, 40, 50]
    assert slo.percentile(samples, 50) == pytest.approx(30.0)
    assert slo.percentile(samples, 90) == pytest.approx(46.0)
    with pytest.raises(slo.ServingSloError):
        slo.percentile([], 50)
    with pytest.raises(slo.ServingSloError):
        slo.percentile(samples, 150)


def test_three_nineties_rule():
    # p90 TTLT ≈ p90 TTFT + p90 ITL × output_tokens
    assert slo.predict_p90_ttlt(2.0, 0.05, 1000) == pytest.approx(52.0)


def test_operating_point_picks_highest_rps_under_slo():
    points = [
        slo.SweepPoint(concurrency=1, rps=0.5, p90_ttft_s=2, p90_ttlt_s=20),
        slo.SweepPoint(concurrency=2, rps=0.9, p90_ttft_s=3, p90_ttlt_s=45),
        slo.SweepPoint(concurrency=4, rps=1.5, p90_ttft_s=4, p90_ttlt_s=85),
        slo.SweepPoint(concurrency=8, rps=2.0, p90_ttft_s=6, p90_ttlt_s=120),  # violates TTLT
    ]
    op = slo.operating_point("repo_triage", points, slo_p90_ttft_s=8, slo_p90_ttlt_s=90)
    assert op.found is True
    assert op.concurrency == 4 and op.rps == pytest.approx(1.5)


def test_operating_point_reports_no_fit_when_all_violate():
    points = [slo.SweepPoint(concurrency=1, rps=0.2, p90_ttft_s=30, p90_ttlt_s=300)]
    op = slo.operating_point("long_repo_reader", points, slo_p90_ttft_s=20, slo_p90_ttlt_s=240)
    assert op.found is False and op.rps is None
    assert "no sweep point meets SLO" in op.reason


def test_operating_point_excludes_erroring_rate():
    points = [
        slo.SweepPoint(concurrency=4, rps=1.5, p90_ttft_s=4, p90_ttlt_s=85),
        slo.SweepPoint(concurrency=8, rps=3.0, p90_ttft_s=5, p90_ttlt_s=88, error_rate=0.2),
    ]
    op = slo.operating_point("code_patch", points, slo_p90_ttft_s=8, slo_p90_ttlt_s=180)
    assert op.concurrency == 4   # the higher-rps point is dropped for erroring out


# ---- config contract --------------------------------------------------------

def test_real_serving_config_validates():
    raw = yaml.safe_load(
        (ROOT / "configs" / "model-serving-benchmarks.yaml").read_text(encoding="utf-8"))
    cfg = ServingBenchmarksConfig.model_validate(raw)
    assert "repo_triage" in cfg.scenarios
    assert cfg.concurrency_sweep[0] == 1


def _cfg(**over):
    base = {
        "schema_version": "command-center.model-serving-benchmarks.v1",
        "scenarios": {"s": {
            "input_tokens_p50": 100, "input_tokens_p90": 200,
            "output_tokens_p50": 50, "output_tokens_p90": 100,
            "slo_p90_ttft_seconds": 4, "slo_p90_ttlt_seconds": 90}},
        "concurrency_sweep": [1, 2, 4],
    }
    base.update(over)
    return base


def test_serving_config_rejects_bad_inputs():
    with pytest.raises(ValueError, match="schema_version"):
        ServingBenchmarksConfig.model_validate(_cfg(schema_version="x"))
    with pytest.raises(ValueError, match="at least one scenario"):
        ServingBenchmarksConfig.model_validate(_cfg(scenarios={}))
    with pytest.raises(ValueError, match="duplicate"):
        ServingBenchmarksConfig.model_validate(_cfg(concurrency_sweep=[1, 1, 2]))
    with pytest.raises(ValueError, match=">= 1"):
        ServingBenchmarksConfig.model_validate(_cfg(concurrency_sweep=[0, 1]))


def test_serving_scenario_rejects_inverted_percentiles_and_slo():
    bad_tokens = _cfg()
    bad_tokens["scenarios"]["s"]["input_tokens_p90"] = 50   # < p50
    with pytest.raises(ValueError, match="input_tokens_p90"):
        ServingBenchmarksConfig.model_validate(bad_tokens)
    bad_slo = _cfg()
    bad_slo["scenarios"]["s"]["slo_p90_ttlt_seconds"] = 1   # < ttft slo
    with pytest.raises(ValueError, match="slo_p90_ttlt_seconds"):
        ServingBenchmarksConfig.model_validate(bad_slo)
