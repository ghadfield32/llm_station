"""
The discovery scan's blocking validation gate: every invariant check passes on the shipped
code, and the gate is genuinely blocking (run_gate returns True only when all checks pass).
"""
from __future__ import annotations

from command_center.improvement.discovery.validate import gate_checks, run_gate, _LEAKAGE_TOKENS


def test_all_gate_checks_pass():
    checks = gate_checks()
    failed = [(name, detail) for name, ok, detail in checks if not ok]
    assert not failed, f"gate failures: {failed}"
    assert run_gate() is True


def test_gate_covers_the_load_bearing_invariants():
    names = {name for name, _, _ in gate_checks()}
    for required in ("config_validates", "charter_forbids_escalation",
                     "drafted_card_is_bounded_proposed_secret_free",
                     "acceptance_features_have_no_leakage", "ranking_methods_known_and_strict",
                     "charter_raises_on_forbidden_access"):
        assert required in names


def test_leakage_token_list_would_catch_an_outcome_feature():
    # the no-leakage check keys off these tokens; an outcome-derived feature name would trip it
    assert any(tok in "human_decision" for tok in _LEAKAGE_TOKENS)
    assert any(tok in "verdict_pass" for tok in _LEAKAGE_TOKENS)
    assert not any(tok in "impact" for tok in _LEAKAGE_TOKENS)   # a legit feature is clean
