"""
The controlled recursive-improvement loop.

A supervised engineering feedback loop layered ON TOP of the existing command
center — same Ledger, same configs/contract pattern, same gates, same approval
wall. It lets the system propose, run, independently verify, compare, remember,
and *recommend* improvements to its own prompts/skills/models/tools/routing/
judges/standards/workflows. It can never approve, promote, merge, deploy, or
certify itself: every promotion still terminates at the human HMAC gate in the
Ledger.

Module map:
  lifecycle.py    experiment state machine + agent/human transition rules
  events.py       validated experiment + execution event taxonomy
  schema.py       Pydantic contracts for configs/improvement.yaml
  ledger_schema.py canonical SQLite DDL for the experiment registry (one DB: the Ledger)
  registry.py     append-oriented experiment registry over ledger.db
  runner.py       deterministic baseline-vs-candidate runner (budgets, raw evidence, hashes)
  verifier.py     genuinely independent verifier (separation, reproduction, verdict)
  evals.py        sealed / rotating / adversarial / historical eval access control
  calibration.py  judge + verifier calibration metrics
  proposals.py    controlled proactive proposal generation (evidence, dedup, cooldown)
  attention.py    human-attention metrics + morning-brief prioritization
  promotion.py    generalized promotion / canary / rollback gates + target adapters
  board.py        Growth OS improvements-board surface (offline-capable, clobber-safe)
"""
from __future__ import annotations

from .lifecycle import (
    ExperimentStatus,
    Actor,
    TransitionConditions,
    TransitionError,
    IllegalTransition,
    HumanApprovalRequired,
    GateNotSatisfied,
    validate_transition,
    is_terminal,
    HUMAN_ONLY_STATES,
    GATED_STATES,
)
from .events import (
    ExperimentEventType,
    ExecutionEventType,
    EventRecord,
    ALL_EXPERIMENT_EVENTS,
    ALL_EXECUTION_EVENTS,
)
from .schema import (
    ImprovementConfig,
    ExperimentDefinition,
    MetricDefinition,
    BudgetDefinition,
    VerificationDefinition,
    PromotionDefinition,
    PostWatchDefinition,
    TargetType,
    MetricDirection,
)

__all__ = [
    "ExperimentStatus", "Actor", "TransitionConditions", "TransitionError",
    "IllegalTransition", "HumanApprovalRequired", "GateNotSatisfied",
    "validate_transition", "is_terminal", "HUMAN_ONLY_STATES", "GATED_STATES",
    "ExperimentEventType", "ExecutionEventType", "EventRecord",
    "ALL_EXPERIMENT_EVENTS", "ALL_EXECUTION_EVENTS",
    "ImprovementConfig", "ExperimentDefinition", "MetricDefinition",
    "BudgetDefinition", "VerificationDefinition", "PromotionDefinition",
    "PostWatchDefinition", "TargetType", "MetricDirection",
]
