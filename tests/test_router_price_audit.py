"""Price-freshness audit tests. Deterministic: `today` is injected, never the wall clock."""
import pytest

from command_center.improvement.router_price_audit import audit_prices
from command_center.schemas import FrontierRouterProvidersConfig


def _cfg(candidates, *, max_age_days=14):
    return FrontierRouterProvidersConfig.model_validate({
        "schema_version": "command-center.frontier-router-providers.v1",
        "providers": {"openrouter": {
            "base_url": "https://x", "api_style": "openai_compatible",
            "secret_env": "OPENROUTER_API_KEY"}},
        "price_freshness": {"max_age_days": max_age_days, "stale_action": "warn_in_scan",
                            "auto_update": False},
        "models": {"m": {"local_lane": "frontier_watch", "router_candidates": candidates}},
    })


def _cand(observed):
    c = {"provider": "openrouter", "model": "x", "input_usd_per_mtok": 1.0,
         "output_usd_per_mtok": 2.0, "context_tokens": 1000}
    if observed is not None:
        c["price_observed_at"] = observed
    return c


def test_fresh_prices_pass():
    cfg = _cfg([_cand("2026-06-20")])
    report = audit_prices(cfg, today="2026-06-21")
    assert report.verdict == "fresh"
    assert report.stale == [] and report.undated == []


def test_stale_price_flagged_with_age():
    cfg = _cfg([_cand("2026-05-01")])
    report = audit_prices(cfg, today="2026-06-20")
    assert report.verdict == "stale"
    assert len(report.stale) == 1
    assert report.stale[0].age_days == 50


def test_undated_price_reported_not_silently_fresh():
    cfg = _cfg([_cand(None)])
    report = audit_prices(cfg, today="2026-06-20")
    assert report.verdict == "undated"
    assert report.undated == ["openrouter:m"]
    assert report.n_dated == 0


def test_audit_never_auto_updates_by_contract():
    # auto_update: true must be refused at config-validation time (prices are never overwritten).
    with pytest.raises(ValueError, match="auto_update"):
        FrontierRouterProvidersConfig.model_validate({
            "schema_version": "command-center.frontier-router-providers.v1",
            "providers": {"o": {"base_url": "u", "api_style": "openai_compatible",
                                "secret_env": "OPENROUTER_API_KEY"}},
            "price_freshness": {"max_age_days": 14, "stale_action": "warn_in_scan",
                                "auto_update": True},
            "models": {"m": {"local_lane": "frontier_watch", "router_candidates": [_cand("2026-06-20")]}},
        })


def test_real_providers_config_prices_are_dated():
    from command_center.improvement.frontier_router_eval import load_providers
    report = audit_prices(load_providers(), today="2026-06-20")
    # every shipped candidate carries a price_observed_at (no undated entries)
    assert report.undated == []
    assert report.n_dated == report.n_candidates
