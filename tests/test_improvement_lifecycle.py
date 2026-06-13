"""Lifecycle state-machine tests.

Prove the two structural walls: (1) an agent can never enter Canary/Promoted, and
(2) the gated states require deterministic-pass + an independent PASS verdict. These
are the "no component may promote itself" and "a model verdict cannot override a
deterministic failure" invariants, made unrepresentable.
"""
from __future__ import annotations

import pytest

from command_center.improvement.lifecycle import (
    Actor,
    ExperimentStatus as S,
    TransitionConditions,
    validate_transition,
    IllegalTransition,
    HumanApprovalRequired,
    GateNotSatisfied,
    is_terminal,
    allowed_targets,
)


def _good() -> TransitionConditions:
    """All gate conditions satisfied (deterministic pass + independent PASS verdict)."""
    return TransitionConditions(
        deterministic_passed=True,
        verification_present=True,
        verification_verdict="PASS",
        safety_inconclusive=False,
        independent_verifier_distinct=True,
        human_approval=True,
        rollback_demonstrated=True,
    )


# ---- the happy forward path -------------------------------------------------

def test_forward_path_with_human_and_evidence():
    g = _good()
    validate_transition(S.PROPOSED, S.BASELINE_READY, actor=Actor.AGENT)
    validate_transition(S.BASELINE_READY, S.RUNNING, actor=Actor.AGENT)
    validate_transition(S.RUNNING, S.AWAITING_VERIFICATION, actor=Actor.AGENT)
    validate_transition(S.AWAITING_VERIFICATION, S.VERIFIED, actor=Actor.AGENT)
    # agent may request human promotion once evidence is present...
    validate_transition(S.VERIFIED, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT, conditions=g)
    # ...but only a human may actually enter Canary / Promoted
    validate_transition(S.AWAITING_HUMAN_PROMOTION, S.CANARY, actor=Actor.HUMAN, conditions=g)
    validate_transition(S.CANARY, S.PROMOTED, actor=Actor.HUMAN, conditions=g)


# ---- wall 1: no component may promote itself --------------------------------

def test_agent_cannot_enter_canary():
    with pytest.raises(HumanApprovalRequired):
        validate_transition(S.AWAITING_HUMAN_PROMOTION, S.CANARY, actor=Actor.AGENT, conditions=_good())


def test_agent_cannot_enter_promoted():
    with pytest.raises(HumanApprovalRequired):
        validate_transition(S.AWAITING_HUMAN_PROMOTION, S.PROMOTED, actor=Actor.AGENT, conditions=_good())


def test_agent_cannot_enter_promoted_even_from_canary():
    with pytest.raises(HumanApprovalRequired):
        validate_transition(S.CANARY, S.PROMOTED, actor=Actor.AGENT, conditions=_good())


def test_promotion_requires_signed_human_approval():
    cond = _good()
    cond = TransitionConditions(
        deterministic_passed=True, verification_present=True, verification_verdict="PASS",
        independent_verifier_distinct=True, human_approval=False, rollback_demonstrated=True,
    )
    with pytest.raises(HumanApprovalRequired):
        validate_transition(S.AWAITING_HUMAN_PROMOTION, S.PROMOTED, actor=Actor.HUMAN, conditions=cond)


# ---- wall 2: deterministic-first gate ---------------------------------------

def test_gate_blocks_on_failed_deterministic_checks():
    cond = TransitionConditions(
        deterministic_passed=False, verification_present=True, verification_verdict="PASS",
        independent_verifier_distinct=True,
    )
    with pytest.raises(GateNotSatisfied):
        validate_transition(S.VERIFIED, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT, conditions=cond)


def test_gate_blocks_when_verifier_not_independent():
    cond = TransitionConditions(
        deterministic_passed=True, verification_present=True, verification_verdict="PASS",
        independent_verifier_distinct=False,
    )
    with pytest.raises(GateNotSatisfied):
        validate_transition(S.VERIFIED, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT, conditions=cond)


def test_gate_blocks_on_non_pass_verdict():
    cond = TransitionConditions(
        deterministic_passed=True, verification_present=True, verification_verdict="FAIL",
        independent_verifier_distinct=True,
    )
    with pytest.raises(GateNotSatisfied):
        validate_transition(S.VERIFIED, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT, conditions=cond)


def test_gate_blocks_on_inconclusive_safety():
    cond = TransitionConditions(
        deterministic_passed=True, verification_present=True, verification_verdict="PASS",
        safety_inconclusive=True, independent_verifier_distinct=True,
    )
    with pytest.raises(GateNotSatisfied):
        validate_transition(S.VERIFIED, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT, conditions=cond)


def test_gate_blocks_with_no_verification_present():
    cond = TransitionConditions(deterministic_passed=True, verification_present=False)
    with pytest.raises(GateNotSatisfied):
        validate_transition(S.VERIFIED, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT, conditions=cond)


# ---- illegal edges ----------------------------------------------------------

def test_illegal_skip_to_promoted():
    with pytest.raises(IllegalTransition):
        validate_transition(S.PROPOSED, S.PROMOTED, actor=Actor.HUMAN, conditions=_good())


def test_illegal_running_to_verified_directly():
    with pytest.raises(IllegalTransition):
        validate_transition(S.RUNNING, S.VERIFIED, actor=Actor.AGENT, conditions=_good())


def test_rejected_is_terminal():
    assert is_terminal(S.REJECTED)
    # nothing leads out of Rejected
    assert allowed_targets(S.REJECTED) == frozenset()


def test_any_running_state_can_reject_or_defer_or_expire():
    for early in (S.REJECTED, S.DEFERRED, S.EXPIRED):
        validate_transition(S.RUNNING, early, actor=Actor.AGENT)
        validate_transition(S.PROPOSED, early, actor=Actor.AGENT)


def test_promoted_can_roll_back_with_demonstrated_rollback():
    validate_transition(S.PROMOTED, S.ROLLED_BACK, actor=Actor.AGENT, conditions=_good())


def test_rollback_requires_demonstration():
    cond = TransitionConditions(rollback_demonstrated=False)
    with pytest.raises(GateNotSatisfied):
        validate_transition(S.PROMOTED, S.ROLLED_BACK, actor=Actor.AGENT, conditions=cond)
