"""Pure cost-estimation + ranking tests for the frontier-router lane. No network, no keys."""
import pytest

from command_center.improvement.router_cost import (
    cheapest_eligible, estimate_cost_usd, rank_candidates,
)


def test_estimate_basic_per_mtok():
    # 1M input @ $1.20 + 1M output @ $4.10 = $5.30
    assert estimate_cost_usd(1_000_000, 1_000_000, 1.20, 4.10) == pytest.approx(5.30)


def test_estimate_with_cached_input_rate():
    # 30k uncached @1.40 + 90k cached @0.26 + 8k output @4.40
    got = estimate_cost_usd(120_000, 8_000, 1.40, 4.40,
                            cached_input_tokens=90_000, cached_input_usd_per_mtok=0.26)
    assert got == pytest.approx(0.042 + 0.0234 + 0.0352)


def test_estimate_falls_back_to_input_rate_when_no_cache_rate():
    # cached tokens billed at the normal input rate when no cached rate is given
    got = estimate_cost_usd(100_000, 0, 2.0, 9.0, cached_input_tokens=100_000)
    assert got == pytest.approx(0.2)


def test_estimate_rejects_bad_token_counts():
    with pytest.raises(ValueError):
        estimate_cost_usd(-1, 10, 1.0, 1.0)
    with pytest.raises(ValueError, match="cannot exceed"):
        estimate_cost_usd(100, 10, 1.0, 1.0, cached_input_tokens=200)


_C1 = {"provider": "openrouter", "model": "a", "input_usd_per_mtok": 1.20,
       "output_usd_per_mtok": 4.10, "context_tokens": 1_000_000}
_C2 = {"provider": "z_ai_direct", "model": "b", "input_usd_per_mtok": 1.40,
       "output_usd_per_mtok": 4.40, "context_tokens": 200_000}


def test_rank_is_data_derived_cheapest_first():
    ranked = rank_candidates([_C2, _C1], 100_000, 8_000)
    assert ranked[0].provider == "openrouter"   # cheaper, despite being listed second
    assert all(r.eligible for r in ranked)


def test_rank_marks_context_ineligible_and_sinks_it():
    # 300k input needs >200k context -> z_ai_direct ineligible, openrouter (1M) wins
    pick = cheapest_eligible([_C1, _C2], 300_000, 8_000)
    assert pick is not None and pick.provider == "openrouter"
    ranked = rank_candidates([_C1, _C2], 300_000, 8_000)
    assert ranked[-1].eligible is False and "context" in ranked[-1].reason


def test_per_request_cap_filters_and_can_exhaust():
    # cap below both estimates -> no eligible candidate
    assert cheapest_eligible([_C1, _C2], 100_000, 8_000, per_request_cap_usd=0.10) is None
    # cap between the two -> only the cheaper survives
    pick = cheapest_eligible([_C1, _C2], 100_000, 8_000, per_request_cap_usd=0.16)
    assert pick is not None and pick.provider == "openrouter"
