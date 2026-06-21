"""Frontier-router backup-lane runner — FAIL-CLOSED preflight, no live calls in this build.

This is the budgeted, redacted, token-measured escalation path for open-weight models too
large to run locally (GLM-5.2, Kimi K2). It is OFF by default and every gate must pass before a
call could ever happen. This module deliberately does NOT make a live paid request: `call_*`
runs the full preflight and then raises, because enabling real egress requires a separate,
explicit operator decision (set the provider key AND reconcile check_forbidden_providers, which
currently forbids OPENROUTER_API_KEY/ZAI_API_KEY everywhere — by design). A router result can
INFORM strategy; it can never promote a local model or bypass the local/quality/serving/canary
gates.

The preflight order (any failure raises, never a silent fallback):
  1. lane enabled?            (budgets.default.enabled)
  2. task class allowed?      (budgets.allowed_task_classes)
  3. model known + provider known?
  4. payload redacted?        (require_redaction is always true)
  5. provider API key present?
  6. cost preflight under the per-request cap?
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from ..schemas import FrontierRouterBudgetsConfig, FrontierRouterProvidersConfig
from .router_cost import CostRecord, cheapest_eligible, estimate_cost_usd

ROOT = Path(__file__).resolve().parents[3]
PROVIDERS_PATH = ROOT / "configs" / "frontier-router-providers.yaml"
BUDGETS_PATH = ROOT / "configs" / "frontier-router-budgets.yaml"


class RouterGateError(RuntimeError):
    """A preflight gate refused the call. Fail-closed — never downgraded to a warning."""


class RouterDisabledError(RouterGateError):
    """Live frontier egress is intentionally not enabled in this build."""


def load_providers(path: Path = PROVIDERS_PATH) -> FrontierRouterProvidersConfig:
    return FrontierRouterProvidersConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8")))


def load_budgets(path: Path = BUDGETS_PATH) -> FrontierRouterBudgetsConfig:
    return FrontierRouterBudgetsConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8")))


def preflight(*, model_id: str, provider: str, input_tokens: int, output_tokens: int,
              task_class: str, payload_redacted: bool, api_key_present: bool,
              providers_cfg: FrontierRouterProvidersConfig,
              budgets_cfg: FrontierRouterBudgetsConfig,
              cached_input_tokens: int = 0) -> CostRecord:
    """Run every gate and return an `allowed` CostRecord, or raise RouterGateError. Pure w.r.t.
    I/O (callers pass the configs + an `api_key_present` boolean), so it is fully unit-tested
    without a key or network."""
    policy = budgets_cfg.default
    if not policy.enabled:
        raise RouterDisabledError(
            "frontier router lane is disabled (budgets.default.enabled=false); enabling it is a "
            "deliberate budgeted operator decision")
    if task_class not in budgets_cfg.allowed_task_classes:
        raise RouterGateError(
            f"task_class {task_class!r} not in allowed_task_classes "
            f"{budgets_cfg.allowed_task_classes}")
    model = providers_cfg.models.get(model_id)
    if model is None:
        raise RouterGateError(f"model {model_id!r} is not in frontier-router-providers.yaml")
    candidate = next((c for c in model.router_candidates if c.provider == provider), None)
    if candidate is None:
        raise RouterGateError(
            f"model {model_id!r} has no candidate for provider {provider!r}")
    if policy.require_redaction and not payload_redacted:
        raise RouterGateError(
            "payload is not redacted; require_redaction forbids raw egress to a paid provider")
    if not api_key_present:
        prov = providers_cfg.providers[provider]
        raise RouterGateError(
            f"provider {provider!r} API key ({prov.secret_env}) is not present")
    if candidate.context_tokens < input_tokens + output_tokens:
        raise RouterGateError(
            f"candidate context {candidate.context_tokens} < needed "
            f"{input_tokens + output_tokens}")
    cost = estimate_cost_usd(
        input_tokens, output_tokens, candidate.input_usd_per_mtok,
        candidate.output_usd_per_mtok, cached_input_tokens=cached_input_tokens,
        cached_input_usd_per_mtok=candidate.cached_input_usd_per_mtok)
    if cost > policy.per_request_cap_usd:
        raise RouterGateError(
            f"estimated ${cost:.4f} exceeds per_request_cap_usd ${policy.per_request_cap_usd:.4f}")
    return CostRecord(
        provider=provider, model=candidate.model, input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens, output_tokens=output_tokens,
        estimated_cost_usd=cost, budget_verdict="allowed")


def dry_run_report(*, model_id: str, provider: str | None, input_tokens: int,
                   output_tokens: int, task_class: str, cached_input_tokens: int = 0) -> dict:
    """A no-egress PREVIEW of what a router call WOULD cost and whether policy would allow it.

    Works even while the lane is disabled (enabled=false) — it never calls preflight and never
    sends anything (`live_call` is always false). If `provider` is None it picks the cheapest
    ELIGIBLE candidate. Use it to sanity-check cost + policy before any enablement decision."""
    providers_cfg = load_providers()
    budgets_cfg = load_budgets()
    policy = budgets_cfg.default
    model = providers_cfg.models.get(model_id)
    if model is None:
        return {"model": model_id, "error": "unknown model", "live_call": False}
    if provider is None:
        pick = cheapest_eligible(
            model.router_candidates, input_tokens, output_tokens,
            cached_input_tokens=cached_input_tokens,
            per_request_cap_usd=policy.per_request_cap_usd)
        if pick is None:
            return {"model": model_id, "budget_verdict": "denied:no_eligible_candidate",
                    "live_call": False}
        provider = pick.provider
    candidate = next((c for c in model.router_candidates if c.provider == provider), None)
    if candidate is None:
        return {"model": model_id, "provider": provider,
                "error": "no candidate for provider", "live_call": False}
    cost = estimate_cost_usd(
        input_tokens, output_tokens, candidate.input_usd_per_mtok,
        candidate.output_usd_per_mtok, cached_input_tokens=cached_input_tokens,
        cached_input_usd_per_mtok=candidate.cached_input_usd_per_mtok)
    if task_class not in budgets_cfg.allowed_task_classes:
        verdict = f"denied:task_class_not_allowed({task_class})"
    elif candidate.context_tokens < input_tokens + output_tokens:
        verdict = "denied:context_too_small"
    elif cost > policy.per_request_cap_usd:
        verdict = f"denied:over_per_request_cap(${policy.per_request_cap_usd:g})"
    else:
        verdict = "allowed"
    return {
        "task_class": task_class,
        "model": candidate.model,
        "provider": provider,
        "estimated_input_tokens": input_tokens,
        "estimated_cached_input_tokens": cached_input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": cost,
        "budget_verdict": verdict,
        "redaction_required": policy.require_redaction,
        "lane_enabled": policy.enabled,
        "live_call": False,
    }


def call_frontier(*, model_id: str, provider: str, prompt_tokens_estimate: int,
                  output_tokens_estimate: int, task_class: str, payload_redacted: bool,
                  cached_input_tokens: int = 0) -> CostRecord:
    """Full path: load configs, read the env key, preflight — then REFUSE to make a live call.
    Live frontier egress is not enabled in this build (it requires reconciling
    check_forbidden_providers, which forbids the provider keys by design, plus an explicit
    operator opt-in). Use this to prove the gate sequence; it never spends money or sends data."""
    providers_cfg = load_providers()
    budgets_cfg = load_budgets()
    secret_env = providers_cfg.providers[provider].secret_env if (
        provider in providers_cfg.providers) else ""
    record = preflight(
        model_id=model_id, provider=provider, input_tokens=prompt_tokens_estimate,
        output_tokens=output_tokens_estimate, task_class=task_class,
        payload_redacted=payload_redacted, cached_input_tokens=cached_input_tokens,
        api_key_present=bool(secret_env and os.environ.get(secret_env)),
        providers_cfg=providers_cfg, budgets_cfg=budgets_cfg)
    raise RouterDisabledError(
        f"preflight passed ({record.estimated_cost_usd:.4f} USD est.) but LIVE frontier egress "
        "is not enabled in this build — enabling requires reconciling check_forbidden_providers "
        "and an explicit operator opt-in. No request was sent.")
