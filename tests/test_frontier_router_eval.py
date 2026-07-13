"""Frontier-router preflight gate tests — fail-closed, no live calls, no keys."""
import pytest

from command_center.improvement import frontier_router_eval as fre
from command_center.schemas import FrontierRouterBudgetsConfig


def _enabled_budgets():
    """An ENABLED budget for testing the allowed path (the real config stays disabled)."""
    return FrontierRouterBudgetsConfig.model_validate({
        "schema_version": "command-center.frontier-router-budgets.v1",
        "default": {
            "enabled": True, "monthly_cap_usd": 10.0, "per_run_cap_usd": 1.0,
            "per_request_cap_usd": 0.25, "require_redaction": True,
            "require_human_approval_for_live_repo_context": True, "log_token_usage": True,
            "log_cost_estimate": True, "fail_on_missing_usage": True},
        "allowed_task_classes": ["frontier_reference_eval", "long_context_comparison"],
        "blocked_payloads": ["secrets", "raw_env_files"],
    })


def _kwargs(**over):
    base = dict(
        model_id="kimi-k2", provider="openrouter", input_tokens=2000, output_tokens=500,
        task_class="frontier_reference_eval", payload_redacted=True, api_key_present=True,
        providers_cfg=fre.load_providers(), budgets_cfg=_enabled_budgets())
    base.update(over)
    return base


def test_real_config_lane_is_disabled_by_default():
    # The shipped config has enabled=false -> any preflight refuses, fail-closed.
    with pytest.raises(fre.RouterDisabledError, match="disabled"):
        fre.preflight(**_kwargs(budgets_cfg=fre.load_budgets()))


def test_preflight_allows_when_every_gate_passes():
    rec = fre.preflight(**_kwargs())
    assert rec.budget_verdict == "allowed"
    assert rec.estimated_cost_usd > 0
    assert rec.cost_source == "preflight_estimate"
    assert rec.actual_cost_usd is None     # never fabricated


def test_preflight_blocks_unredacted_payload():
    with pytest.raises(fre.RouterGateError, match="not redacted"):
        fre.preflight(**_kwargs(payload_redacted=False))


def test_preflight_blocks_missing_key():
    with pytest.raises(fre.RouterGateError, match="API key"):
        fre.preflight(**_kwargs(api_key_present=False))


def test_preflight_blocks_disallowed_task_class():
    with pytest.raises(fre.RouterGateError, match="task_class"):
        fre.preflight(**_kwargs(task_class="promote_local_incumbent"))


def test_preflight_blocks_unknown_model():
    with pytest.raises(fre.RouterGateError, match="not in frontier-router"):
        fre.preflight(**_kwargs(model_id="not-a-model"))


def test_preflight_blocks_cost_over_cap():
    # glm-5.2 (1M ctx) with 200k output @ $4.10/Mtok ≈ $0.82 blows the $0.25 per-request cap
    # while staying within the context window (so the COST gate fires, not the context gate).
    with pytest.raises(fre.RouterGateError, match="per_request_cap"):
        fre.preflight(**_kwargs(model_id="glm-5.2", output_tokens=200_000))


def test_call_frontier_never_makes_a_live_call(monkeypatch):
    # Even with a key in the env, the shipped (disabled) config refuses before any egress.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-real")
    with pytest.raises(fre.RouterDisabledError):
        fre.call_frontier(
            model_id="kimi-k2", provider="openrouter", prompt_tokens_estimate=2000,
            output_tokens_estimate=500, task_class="frontier_reference_eval",
            payload_redacted=True)


# ---- dry-run preview (no egress, works while the lane is disabled) -----------

def test_dry_run_report_previews_cost_without_calling():
    rep = fre.dry_run_report(
        model_id="glm-5.2", provider="openrouter", input_tokens=120_000,
        output_tokens=8_000, task_class="frontier_reference_eval")
    assert rep["live_call"] is False
    assert rep["lane_enabled"] is False           # shipped config is disabled
    assert rep["estimated_cost_usd"] > 0
    assert rep["provider"] == "openrouter"


def test_dry_run_report_picks_cheapest_when_provider_omitted():
    rep = fre.dry_run_report(
        model_id="glm-5.2", provider=None, input_tokens=2_000, output_tokens=500,
        task_class="frontier_reference_eval")
    # glm-5.2 openrouter ($1.20/$4.10) is cheaper than z_ai_direct ($1.40/$4.40) at this size
    assert rep["provider"] == "openrouter"
    assert rep["budget_verdict"] == "allowed"


def test_dry_run_report_denies_over_cap():
    rep = fre.dry_run_report(
        model_id="glm-5.2", provider="openrouter", input_tokens=2_000,
        output_tokens=200_000, task_class="frontier_reference_eval")
    assert rep["budget_verdict"].startswith("denied:over_per_request_cap")
    assert rep["live_call"] is False
