"""
CodeSOTA frontier-watch adapter: offline mapping, per-row benchmark validation, fail-loud
behaviour, and that the emitted records flow through the real ModelRegistryScanner.

All fixtures are trimmed copies of live `/api/sota/{task}?tier=sota` payloads (captured
2026-06-23), including the observed cross-benchmark mixing in a runners-up row.
"""
from __future__ import annotations

import pytest

from command_center.improvement.discovery import ModelRegistryScanner
from command_center.improvement.discovery.codesota import (
    fetch_codesota_records,
)

# --- captured payloads -----------------------------------------------------------------

_SWE_BENCH = {
    "task_full_id": "swe-bench",
    "snapshot_id": "reg-2026-06-23-3a9798",
    "as_of": None,
    "pick": {
        "model_id": "claude-mythos-preview", "model_name": "Claude Mythos Preview",
        "model_url": "https://www.codesota.com/model/claude-mythos-preview",
        "vendor": "Anthropic", "score": 93.9,
        "score_metric": "swe-bench-verified-agentic_resolve_rate", "higher_is_better": True,
        "benchmark": {"id": "swe-bench-verified-agentic", "name": "SWE-bench Verified"},
        "cost_per_1k_usd": None, "result_date": None,
    },
    "runners_up": [
        {"model_id": "claude-opus-45", "model_name": "Claude Opus 4.5", "vendor": "Anthropic",
         "score": 80.9, "score_metric": "swe-bench-verified-agentic_resolve_rate",
         "higher_is_better": True,
         "benchmark": {"id": "swe-bench-verified-agentic", "name": "SWE-bench Verified"}},
        {"model_id": "claude-opus-46", "model_name": "Claude Opus 4.6", "vendor": "Anthropic",
         "score": 80.8, "score_metric": "swe-bench-verified-agentic_resolve_rate",
         "higher_is_better": True,
         "benchmark": {"id": "swe-bench-verified-agentic", "name": "SWE-bench Verified"}},
    ],
}

# Terminal-Bench task whose SECOND runner-up is a DIFFERENT benchmark (the mixing to reject).
_AUTONOMOUS_CODING = {
    "task_full_id": "autonomous-coding",
    "snapshot_id": "reg-2026-04-27-a72774",
    "as_of": "2026-04-27T00:00:00.000Z",
    "pick": {
        "model_id": "terminal-bench-codex-gpt-55", "model_name": "Codex / GPT-5.5",
        "model_url": "https://www.codesota.com/model/terminal-bench-codex-gpt-55",
        "vendor": "OpenAI", "score": 82, "score_metric": "terminal-bench-2_accuracy",
        "higher_is_better": True,
        "benchmark": {"id": "terminal-bench-2", "name": "Terminal-Bench 2.0"},
        "result_date": "2026-04-27",
    },
    "runners_up": [
        {"model_id": "terminal-bench-forgecode-gpt-54", "model_name": "ForgeCode / GPT-5.4",
         "vendor": "ForgeCode", "score": 81.8, "score_metric": "terminal-bench-2_accuracy",
         "higher_is_better": True,
         "benchmark": {"id": "terminal-bench-2", "name": "Terminal-Bench 2.0"}},
        # cross-benchmark contaminant: higher raw score, but a DIFFERENT benchmark/metric
        {"model_id": "claude-opus-4-5", "model_name": "Claude Opus 4.5", "vendor": "Anthropic",
         "score": 99.0, "score_metric": "swe-bench-agentic_pct_resolved",
         "higher_is_better": True,
         "benchmark": {"id": "swe-bench-agentic", "name": "SWE-bench"}},
    ],
}

# A task whose pick has NO comparable runner-up → must yield no record.
_LONELY = {
    "task_full_id": "coding-agents",
    "snapshot_id": "reg-2026-06-23-aaaa",
    "pick": {"model_id": "solo", "model_name": "Solo", "vendor": "X", "score": 70,
             "score_metric": "x_acc", "higher_is_better": True,
             "benchmark": {"id": "x", "name": "X"}},
    "runners_up": [
        {"model_id": "other", "model_name": "Other", "score": 60, "score_metric": "y_acc",
         "higher_is_better": True, "benchmark": {"id": "y", "name": "Y"}},  # different benchmark
    ],
}

# A lower-is-better task (e.g. error rate) to check direction handling.
_LOWER_BETTER = {
    "task_full_id": "asr",
    "pick": {"model_id": "best", "model_name": "Best", "vendor": "V", "score": 2.0,
             "score_metric": "wer", "higher_is_better": False,
             "benchmark": {"id": "asr-wer", "name": "ASR WER"}},
    "runners_up": [
        {"model_id": "ok", "model_name": "Ok", "score": 3.0, "score_metric": "wer",
         "higher_is_better": False, "benchmark": {"id": "asr-wer", "name": "ASR WER"}},
        {"model_id": "worst", "model_name": "Worst", "score": 9.0, "score_metric": "wer",
         "higher_is_better": False, "benchmark": {"id": "asr-wer", "name": "ASR WER"}},
    ],
}


def _fake_get(payloads: dict[str, dict]):
    """An http_get stub keyed by task id parsed out of the /api/sota/{task} URL."""
    def get(url: str) -> dict:
        task = url.rsplit("/api/sota/", 1)[1].split("?", 1)[0]
        if task not in payloads:
            return {"error": f"Task '{task}' not found in the CodeSOTA registry."}
        return payloads[task]
    return get


# --- tests -----------------------------------------------------------------------------

def test_maps_pick_against_same_benchmark_runner_up():
    recs = fetch_codesota_records(["swe-bench"],
                                  http_get=_fake_get({"swe-bench": _SWE_BENCH}))
    assert len(recs) == 1
    r = recs[0]
    assert r["model"] == "Claude Mythos Preview"
    assert r["provider"] == "Anthropic"
    assert r["candidate"] == 93.9
    assert r["incumbent"] == 80.9          # the strongest SAME-benchmark runner-up
    assert r["runner_up_model"] == "Claude Opus 4.5"
    assert r["direction"] == "increase"
    assert r["benchmark_id"] == "swe-bench-verified-agentic"
    assert r["source_name"] == "codesota"
    assert r["snapshot_id"] == "reg-2026-06-23-3a9798"


def test_rejects_cross_benchmark_runner_up():
    """The 99.0 swe-bench row must NOT become the incumbent of a terminal-bench task."""
    recs = fetch_codesota_records(["autonomous-coding"],
                                  http_get=_fake_get({"autonomous-coding": _AUTONOMOUS_CODING}))
    assert len(recs) == 1
    r = recs[0]
    assert r["incumbent"] == 81.8          # the same-benchmark ForgeCode row, not 99.0
    assert r["runner_up_model"] == "ForgeCode / GPT-5.4"
    assert r["benchmark_id"] == "terminal-bench-2"
    assert r["evaluation_date"] == "2026-04-27"


def test_skips_task_without_comparable_runner_up():
    recs = fetch_codesota_records(["coding-agents"],
                                  http_get=_fake_get({"coding-agents": _LONELY}))
    assert recs == []


def test_lower_is_better_uses_min_runner_up_and_decrease_direction():
    recs = fetch_codesota_records(["asr"], http_get=_fake_get({"asr": _LOWER_BETTER}))
    assert len(recs) == 1
    r = recs[0]
    assert r["direction"] == "decrease"
    assert r["candidate"] == 2.0
    assert r["incumbent"] == 3.0           # strongest = LOWEST wer among runners-up
    assert r["runner_up_model"] == "Ok"


def test_unknown_task_fails_loud():
    with pytest.raises(RuntimeError, match="not in registry"):
        fetch_codesota_records(["does-not-exist"], http_get=_fake_get({}))


def test_records_flow_through_real_model_registry_scanner():
    recs = fetch_codesota_records(
        ["swe-bench", "autonomous-coding"],
        http_get=_fake_get({"swe-bench": _SWE_BENCH, "autonomous-coding": _AUTONOMOUS_CODING}))
    findings = ModelRegistryScanner(lambda: recs, name="codesota").scan()
    titles = {f.title for f in findings}
    assert "evaluate Claude Mythos Preview on swe-bench-verified-agentic_resolve_rate" in titles
    assert "evaluate Codex / GPT-5.5 on terminal-bench-2_accuracy" in titles
    assert all(f.pillar.value == "updated_metrics" for f in findings)
