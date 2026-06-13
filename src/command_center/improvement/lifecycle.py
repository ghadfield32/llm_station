"""
Experiment lifecycle — the one state machine every target type shares.

The same lifecycle governs a model swap, a prompt tweak, a judge change, a
retrieval-strategy A/B: nothing gets a private path to "Promoted". Transitions
are validated; the dangerous ones are *structurally* impossible for an agent.

    Proposed → Baseline Ready → Running → Awaiting Verification → Verified
            → Awaiting Human Promotion → Canary → Promoted

Alternative terminal states: Rejected, Deferred, Inconclusive, Rolled Back, Expired.

Two walls, enforced here and re-asserted by contract tests:

1. HUMAN_ONLY_STATES = {Canary, Promoted}. An *agent* actor can never transition
   into these — only a human (an approval) can. This is the "no component may
   promote itself" invariant, made unrepresentable rather than merely discouraged.

2. GATED_STATES = {Awaiting Human Promotion, Canary, Promoted}. Entering any of
   these requires the deterministic checks to have passed AND an independent
   verification verdict to be present (and PASS on safety). A model verdict can
   never override a deterministic failure; a missing/failed verifier blocks the gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExperimentStatus(StrEnum):
    PROPOSED = "Proposed"
    BASELINE_READY = "Baseline Ready"
    RUNNING = "Running"
    AWAITING_VERIFICATION = "Awaiting Verification"
    VERIFIED = "Verified"
    AWAITING_HUMAN_PROMOTION = "Awaiting Human Promotion"
    CANARY = "Canary"
    PROMOTED = "Promoted"
    # terminal alternates
    REJECTED = "Rejected"
    DEFERRED = "Deferred"
    INCONCLUSIVE = "Inconclusive"
    ROLLED_BACK = "Rolled Back"
    EXPIRED = "Expired"


class Actor(StrEnum):
    """Who is requesting a transition. The runner/proactive lane act as AGENT;
    only a human operator presenting an approval acts as HUMAN."""
    AGENT = "agent"
    HUMAN = "human"


# Canary and Promoted are reachable ONLY by a human actor. No exceptions.
HUMAN_ONLY_STATES: frozenset[ExperimentStatus] = frozenset({
    ExperimentStatus.CANARY,
    ExperimentStatus.PROMOTED,
})

# Entering any of these requires deterministic-pass + an independent PASS verdict.
GATED_STATES: frozenset[ExperimentStatus] = frozenset({
    ExperimentStatus.AWAITING_HUMAN_PROMOTION,
    ExperimentStatus.CANARY,
    ExperimentStatus.PROMOTED,
})

_TERMINAL: frozenset[ExperimentStatus] = frozenset({
    ExperimentStatus.PROMOTED,
    ExperimentStatus.REJECTED,
    ExperimentStatus.DEFERRED,
    ExperimentStatus.INCONCLUSIVE,
    ExperimentStatus.ROLLED_BACK,
    ExperimentStatus.EXPIRED,
})

# Any non-terminal state may end early as Rejected / Deferred / Expired — the
# human can always stop an experiment. Inconclusive is reachable once running.
_EARLY_EXITS: frozenset[ExperimentStatus] = frozenset({
    ExperimentStatus.REJECTED,
    ExperimentStatus.DEFERRED,
    ExperimentStatus.EXPIRED,
})

# The forward path. Early-exit terminals are added to each non-terminal source below.
_FORWARD: dict[ExperimentStatus, frozenset[ExperimentStatus]] = {
    ExperimentStatus.PROPOSED: frozenset({ExperimentStatus.BASELINE_READY}),
    ExperimentStatus.BASELINE_READY: frozenset({
        ExperimentStatus.RUNNING,
        ExperimentStatus.INCONCLUSIVE,           # equivalence lost before the candidate ran
    }),
    ExperimentStatus.RUNNING: frozenset({
        ExperimentStatus.RUNNING,                # iterate within budget
        ExperimentStatus.AWAITING_VERIFICATION,
        ExperimentStatus.INCONCLUSIVE,           # budget exhausted / no material improvement
    }),
    ExperimentStatus.AWAITING_VERIFICATION: frozenset({
        ExperimentStatus.VERIFIED,
        ExperimentStatus.INCONCLUSIVE,
    }),
    ExperimentStatus.VERIFIED: frozenset({ExperimentStatus.AWAITING_HUMAN_PROMOTION}),
    ExperimentStatus.AWAITING_HUMAN_PROMOTION: frozenset({
        ExperimentStatus.CANARY,
        ExperimentStatus.PROMOTED,               # human may promote without a canary
    }),
    ExperimentStatus.CANARY: frozenset({
        ExperimentStatus.PROMOTED,
        ExperimentStatus.ROLLED_BACK,
    }),
    ExperimentStatus.PROMOTED: frozenset({ExperimentStatus.ROLLED_BACK}),  # post-watch rollback
}


def allowed_targets(src: ExperimentStatus) -> frozenset[ExperimentStatus]:
    """Every state reachable in one step from ``src`` (forward path + early exits)."""
    fwd = _FORWARD.get(src, frozenset())
    if src in _TERMINAL and src is not ExperimentStatus.PROMOTED:
        return fwd  # Promoted keeps its post-watch rollback edge; other terminals are dead-ends
    return fwd | _EARLY_EXITS


def is_terminal(status: ExperimentStatus) -> bool:
    return status in _TERMINAL


@dataclass(frozen=True)
class TransitionConditions:
    """Evidence the gated transitions require. The runner/registry fills these
    from real Ledger state — never from a model's say-so."""
    deterministic_passed: bool = False
    verification_present: bool = False
    verification_verdict: str | None = None       # "PASS" | "FAIL" | "INCONCLUSIVE" | None
    safety_inconclusive: bool = False             # a safety criterion came back INCONCLUSIVE
    independent_verifier_distinct: bool = False   # verifier context/identity != implementer
    human_approval: bool = False                  # a signed human approval exists
    rollback_demonstrated: bool = False           # rollback was actually exercised

    def gate_satisfied(self) -> tuple[bool, str]:
        """True iff a GATED_STATE may be entered. Deterministic-first: a failed
        or missing deterministic check blocks regardless of any model verdict."""
        if not self.deterministic_passed:
            return False, "deterministic checks have not passed"
        if not self.verification_present:
            return False, "no independent verification verdict is present"
        if not self.independent_verifier_distinct:
            return False, "verifier was not independent of the implementer"
        if self.verification_verdict != "PASS":
            return False, f"verification verdict is {self.verification_verdict!r}, not PASS"
        if self.safety_inconclusive:
            return False, "a safety criterion is INCONCLUSIVE (never acceptable)"
        return True, "ok"


class TransitionError(ValueError):
    """Base for all illegal lifecycle transitions."""


class IllegalTransition(TransitionError):
    """The edge does not exist in the state machine."""


class HumanApprovalRequired(TransitionError):
    """An agent tried to enter a human-only state (Canary / Promoted)."""


class GateNotSatisfied(TransitionError):
    """A gated state was entered without deterministic-pass + independent PASS."""


def validate_transition(
    src: ExperimentStatus,
    dst: ExperimentStatus,
    *,
    actor: Actor,
    conditions: TransitionConditions | None = None,
) -> None:
    """Raise if (src → dst) by ``actor`` is not permitted. Silent success = allowed.

    Order matters: the edge must exist, then the human-only wall, then the
    evidence gate. Promotion additionally requires a real human approval.
    """
    conditions = conditions or TransitionConditions()

    if dst not in allowed_targets(src):
        raise IllegalTransition(
            f"no transition {src.value!r} → {dst.value!r}; "
            f"allowed: {sorted(s.value for s in allowed_targets(src))}"
        )

    # Wall 1 — Canary/Promoted are human-only. An agent can never enter them.
    if dst in HUMAN_ONLY_STATES and actor is not Actor.HUMAN:
        raise HumanApprovalRequired(
            f"only a human may move an experiment into {dst.value!r}; "
            "no component may promote itself"
        )

    # Wall 2 — gated states require deterministic-pass + independent PASS verdict.
    if dst in GATED_STATES:
        ok, why = conditions.gate_satisfied()
        if not ok:
            raise GateNotSatisfied(
                f"cannot enter {dst.value!r}: {why}"
            )

    # Promotion (the real act) needs a signed human approval, not just human actor.
    if dst is ExperimentStatus.PROMOTED and not conditions.human_approval:
        raise HumanApprovalRequired(
            "promotion requires a signed human approval recorded in the Ledger"
        )

    # Rollback after promotion must have been demonstrated first (tested rollback).
    if dst is ExperimentStatus.ROLLED_BACK and not conditions.rollback_demonstrated:
        raise GateNotSatisfied(
            "rollback cannot be recorded before it has been demonstrated"
        )
