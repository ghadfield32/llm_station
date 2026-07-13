"""The continual KPI-check harness: rule-based scoring against each benchmark
case's own declared contract, and a cost-only dry-run that works with the lane
disabled (no key, no network)."""
from __future__ import annotations

from types import SimpleNamespace

from command_center.improvement import frontier_benchmark as fb


def _case(**over):
    base = dict(id="c1", prompt="say hi", response_format=None, metric_tags=["t"],
               expected_contains=[], forbidden_contains=[], required_json_keys=[],
               expected_json_values={}, safety=False)
    base.update(over)
    return SimpleNamespace(**base)


def test_score_case_json_missing_key_fails():
    case = _case(response_format="json", required_json_keys=["risk_tier"])
    result = fb.score_case(case, '{"other": 1}')
    assert result["ok"] is False
    assert any("missing required key" in r for r in result["reasons"])


def test_score_case_json_matches_expected_values():
    case = _case(response_format="json", required_json_keys=["risk_tier"],
                expected_json_values={"risk_tier": "L0_read_only"})
    result = fb.score_case(case, '{"risk_tier": "L0_read_only"}')
    assert result["ok"] is True and result["reasons"] == []


def test_score_case_invalid_json_fails():
    case = _case(response_format="json", required_json_keys=["risk_tier"])
    result = fb.score_case(case, "not json at all")
    assert result["ok"] is False
    assert any("not valid JSON" in r for r in result["reasons"])


def test_score_case_forbidden_substring_fails():
    case = _case(forbidden_contains=["password"])
    result = fb.score_case(case, "here is the password: hunter2")
    assert result["ok"] is False
    assert any("forbidden substring" in r for r in result["reasons"])


def test_score_case_expected_substring_required():
    case = _case(expected_contains=["hello"])
    assert fb.score_case(case, "hello there")["ok"] is True
    assert fb.score_case(case, "goodbye")["ok"] is False


def test_dry_run_uses_real_suite_and_pricing_no_egress():
    report = fb.dry_run("chat", fb.DEFAULT_CANDIDATES)
    assert report["mode"] == "dry_run" and report["live_call"] is False
    assert report["cases"] > 0
    model_ids = {row["model_id"] for row in report["candidates"]}
    assert set(fb.DEFAULT_CANDIDATES) <= model_ids
    for row in report["candidates"]:
        assert row["estimated_cost_per_case_usd"] > 0
        assert row["estimated_total_usd"] > 0
        # lane_enabled mirrors the live operator decision — a bool, not a guess
        assert isinstance(row["lane_enabled"], bool)


def test_summarize_computes_pass_rate_and_blocked_reasons():
    live_report = {
        "mode": "live",
        "results": {
            "glm-5.2": [
                {"case_id": "a", "ok": True, "blocked": False, "latency_ms": 100,
                 "actual_cost_usd": 0.001},
                {"case_id": "b", "ok": False, "blocked": False, "latency_ms": 200,
                 "actual_cost_usd": 0.002},
                {"case_id": "c", "ok": False, "blocked": True,
                 "reason": "RouterDisabledError: lane disabled"},
            ],
        },
    }
    summary = fb.summarize(live_report)
    row = summary["glm-5.2"]
    assert row["cases_scored"] == 2
    assert row["cases_blocked"] == 1
    assert row["pass_rate"] == 0.5
    assert row["median_latency_ms"] == 200
    assert row["measured_cost_usd"] == 0.003
    assert row["block_reasons"] == ["RouterDisabledError: lane disabled"]
