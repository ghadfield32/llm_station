"""
Structured experiment + execution events.

Two families:
  * experiment events — the lifecycle audit trail (registered, baseline, candidate,
    budget, deterministic gate, verification, promotion, canary, rollback, post-watch).
  * execution events — fine-grained credit assignment within a mission (plan, hypothesis,
    source, file change, test, root cause, implementation, summary).

Each event records *decisions, evidence, actions, and outcomes* — never hidden model
reasoning. `EventRecord` is the validated wire/storage shape; the registry appends them.
"""
from __future__ import annotations

from enum import StrEnum

from ..schemas.base import Strict
from pydantic import Field


class ExperimentEventType(StrEnum):
    EXPERIMENT_REGISTERED = "EXPERIMENT_REGISTERED"
    BASELINE_STARTED = "BASELINE_STARTED"
    BASELINE_COMPLETED = "BASELINE_COMPLETED"
    CANDIDATE_STARTED = "CANDIDATE_STARTED"
    CANDIDATE_COMPLETED = "CANDIDATE_COMPLETED"
    BUDGET_WARNING = "BUDGET_WARNING"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    DETERMINISTIC_GATE_FAILED = "DETERMINISTIC_GATE_FAILED"
    VERIFICATION_REQUESTED = "VERIFICATION_REQUESTED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_REPRODUCED = "VERIFICATION_REPRODUCED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    HUMAN_PROMOTION_REQUESTED = "HUMAN_PROMOTION_REQUESTED"
    CANARY_STARTED = "CANARY_STARTED"
    CANARY_FAILED = "CANARY_FAILED"
    CANARY_PASSED = "CANARY_PASSED"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"
    POST_WATCH_COMPLETED = "POST_WATCH_COMPLETED"
    EXPERIMENT_REJECTED = "EXPERIMENT_REJECTED"
    EXPERIMENT_DEFERRED = "EXPERIMENT_DEFERRED"


class ExecutionEventType(StrEnum):
    PLAN_CREATED = "PLAN_CREATED"
    HYPOTHESIS_CREATED = "HYPOTHESIS_CREATED"
    SOURCE_RETRIEVED = "SOURCE_RETRIEVED"
    FILE_CHANGED = "FILE_CHANGED"
    TEST_STARTED = "TEST_STARTED"
    TEST_FAILED = "TEST_FAILED"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    PLAN_REVISED = "PLAN_REVISED"
    IMPLEMENTATION_COMPLETED = "IMPLEMENTATION_COMPLETED"
    SUMMARY_CREATED = "SUMMARY_CREATED"


ALL_EXPERIMENT_EVENTS: frozenset[str] = frozenset(e.value for e in ExperimentEventType)
ALL_EXECUTION_EVENTS: frozenset[str] = frozenset(e.value for e in ExecutionEventType)
_KNOWN_EVENTS = ALL_EXPERIMENT_EVENTS | ALL_EXECUTION_EVENTS


class EventRecord(Strict):
    """One append-only event. Stored in the Ledger's experiment_events table.

    `kind` must be a known experiment- or execution-event type. The recorded
    fields are decisions/evidence/actions/outcomes only — there is deliberately
    no field for hidden chain-of-thought.
    """
    kind: str
    experiment_id: str
    mission_id: str | None = None
    actor_role: str | None = None                 # "implementer" | "verifier" | "runner" | "human" | ...
    actor_model: str | None = None                # model/route used, where applicable
    action: str = ""                              # short human-readable action summary
    input_artifact_hashes: list[str] = Field(default_factory=list)
    output_artifact_hashes: list[str] = Field(default_factory=list)
    duration_seconds: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    exit_code: int | None = None
    error_class: str | None = None
    evidence_links: list[str] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)    # extra structured payload (no raw reasoning)

    def model_post_init(self, _ctx) -> None:
        if self.kind not in _KNOWN_EVENTS:
            raise ValueError(
                f"unknown event kind {self.kind!r}; must be one of the experiment "
                "or execution event types"
            )
