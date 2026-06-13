"""
Controlled proposal generation — the proactive lane that DRAFTS experiments from
real evidence.

This is where autonomy grows the safe way: the system observes, classifies, and
*drafts a bounded experiment* — it never approves, executes, promotes, or touches
production. A drafted experiment lands in the registry as `Proposed` (a Backlog card),
exactly where a human-gated experiment would start.

Three guards keep the board from filling with noise:
  * evidence thresholds — a signal must recur enough and breach its threshold to count.
  * deduplication — one open proposal per (source, target); a duplicate is skipped.
  * cooldown — the same proposal is not re-drafted within the cooldown window.

The proactive runner gathers the evidence (mission failures, judge FP/FN, token bloat,
slow retrieval, tool loops, review burden, routing regret, dependency changes, DAG
failures, doc drift, rollback causes, benchmark saturation, queue age) and hands signals
here; this module turns the actionable ones into drafts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from ..schemas.base import RiskTier
from .events import EventRecord, ExperimentEventType
from .registry import ExperimentRegistry
from .schema import (
    ExperimentDefinition, MetricDefinition, MetricDirection, BudgetDefinition,
    VerificationDefinition, PromotionDefinition, PostWatchDefinition, TargetType,
)


class EvidenceSource(StrEnum):
    REPEATED_MISSION_FAILURE = "repeated_mission_failure"
    JUDGE_FALSE_POSITIVE = "judge_false_positive"
    JUDGE_FALSE_NEGATIVE = "judge_false_negative"
    TOKEN_BLOAT = "token_bloat"
    SLOW_RETRIEVAL = "slow_retrieval"
    TOOL_LOOP = "tool_loop"
    REVIEW_BURDEN = "review_burden"
    ROUTING_REGRET = "routing_regret"
    DEPENDENCY_CHANGE = "dependency_change"
    DAG_FAILURE = "dag_failure"
    DOC_DRIFT = "doc_drift"
    ROLLBACK_CAUSE = "rollback_cause"
    BENCHMARK_SATURATION = "benchmark_saturation"
    QUEUE_AGE = "queue_age"


_SOURCE_TARGET: dict[EvidenceSource, TargetType] = {
    EvidenceSource.REPEATED_MISSION_FAILURE: TargetType.WORKFLOW,
    EvidenceSource.JUDGE_FALSE_POSITIVE: TargetType.JUDGE,
    EvidenceSource.JUDGE_FALSE_NEGATIVE: TargetType.JUDGE,
    EvidenceSource.TOKEN_BLOAT: TargetType.PROMPT,
    EvidenceSource.SLOW_RETRIEVAL: TargetType.RETRIEVAL,
    EvidenceSource.TOOL_LOOP: TargetType.TOOL,
    EvidenceSource.REVIEW_BURDEN: TargetType.WORKFLOW,
    EvidenceSource.ROUTING_REGRET: TargetType.ROUTING,
    EvidenceSource.DEPENDENCY_CHANGE: TargetType.TOOL,
    EvidenceSource.DAG_FAILURE: TargetType.PROACTIVE_CHECK,
    EvidenceSource.DOC_DRIFT: TargetType.DOCUMENTATION,
    EvidenceSource.ROLLBACK_CAUSE: TargetType.WORKFLOW,
    EvidenceSource.BENCHMARK_SATURATION: TargetType.STANDARD,
    EvidenceSource.QUEUE_AGE: TargetType.WORKFLOW,
}


@dataclass
class EvidenceSignal:
    source: EvidenceSource
    target_ref: str                      # what to experiment on (a role/file/skill/...)
    observed: float                      # measured value
    threshold: float                     # the bar that makes it noteworthy
    direction: str = "increase"          # "increase": observed>=threshold is bad; "decrease": <=
    occurrences: int = 1                 # how many times the signal recurred
    min_occurrences: int = 3             # evidence threshold: noise below this is ignored
    window: str = "7d"
    detail: str = ""

    @property
    def breaches(self) -> bool:
        if self.direction == "increase":
            return self.observed >= self.threshold
        return self.observed <= self.threshold

    @property
    def actionable(self) -> bool:
        return self.breaches and self.occurrences >= self.min_occurrences


@dataclass
class ProposalDraft:
    experiment_id: str
    dedup_key: str
    definition: ExperimentDefinition
    evidence: dict
    skipped: str = ""                    # non-empty if not drafted (dedup / cooldown / noise)

    def to_dict(self) -> dict:
        return {"experiment_id": self.experiment_id, "dedup_key": self.dedup_key,
                "skipped": self.skipped, "evidence": self.evidence}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:32] or "x"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_hours(ts: str, now_iso: str) -> float:
    try:
        return max(0.0, (datetime.fromisoformat(now_iso)
                         - datetime.fromisoformat(ts)).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return 1e9


class ProposalGenerator:
    """Drafts bounded experiments from evidence. Never approves, executes, or promotes."""

    def __init__(self, registry: ExperimentRegistry):
        self.reg = registry

    def dedup_key(self, signal: EvidenceSignal) -> str:
        return f"{signal.source.value}:{_slug(signal.target_ref)}"

    def _draft_definition(self, signal: EvidenceSignal, now_iso: str) -> ExperimentDefinition:
        eid = f"EXP-auto-{_slug(signal.source.value)}-{_slug(signal.target_ref)}"
        target_type = _SOURCE_TARGET[signal.source]
        primary = MetricDefinition(
            name="primary_outcome", direction=_primary_direction(signal), required=True,
            baseline_source="measured on the current behavior",
            candidate_source="measured on the proposed change",
            minimum_improvement=0.0,
            maximum_regression=0.0)
        safety = MetricDefinition(
            name="safety_regressions", direction=MetricDirection.DECREASE,
            required=True, safety=True,
            baseline_source="count of safety violations (baseline)",
            candidate_source="count of safety violations (candidate)",
            maximum_regression=0.0)
        return ExperimentDefinition(
            experiment_id=eid,
            title=f"[auto] address {signal.source.value} on {signal.target_ref}",
            owner="proactive-runner",
            target_type=target_type,
            target_ref=signal.target_ref,
            problem_statement=(f"Recurring {signal.source.value} ({signal.occurrences}x in "
                               f"{signal.window}); observed {signal.observed} vs threshold "
                               f"{signal.threshold}. {signal.detail}"),
            hypothesis=f"A bounded change to {signal.target_ref} reduces {signal.source.value} "
                       "without regressing safety.",
            baseline="current behavior (to be captured by the runner)",
            candidate="proposed change (to be drafted by a human-approved mission)",
            risk_tier=RiskTier.L2,
            automated=True,
            created_at=now_iso,
            metrics=[primary, safety],
            budgets=BudgetDefinition(max_iterations=3, max_wall_minutes=30,
                                     max_input_tokens=0, max_output_tokens=0, max_cost_usd=0,
                                     max_gpu_hours=0, max_changed_files=10, max_diff_lines=500),
            verification=VerificationDefinition(
                reproduce_commands=[f"python -m command_center.cli.improvement verify {eid}"],
                required_evidence=["raw before/after logs", "metric summary with sample count"]),
            promotion=PromotionDefinition(),
            post_watch=PostWatchDefinition(
                monitored_metrics=["primary_outcome", "safety_regressions"],
                rollback_triggers=["safety_regressions increases", "primary_outcome regresses"]),
        )

    def propose(self, signals: list[EvidenceSignal], *, cooldown_hours: float = 168.0,
                now_iso: str | None = None, apply: bool = False) -> list[ProposalDraft]:
        """Turn actionable signals into drafts. dry-run by default (apply=False just
        reports). Skips noise (below threshold), duplicates, and cooldown re-proposals."""
        now_iso = now_iso or _now_iso()
        existing = self.reg.list_experiments()
        by_id = {e["experiment_id"]: e for e in existing}
        drafts: list[ProposalDraft] = []
        seen_keys: set[str] = set()
        for signal in signals:
            key = self.dedup_key(signal)
            defn = self._draft_definition(signal, now_iso)
            draft = ProposalDraft(experiment_id=defn.experiment_id, dedup_key=key,
                                  definition=defn,
                                  evidence={"source": signal.source.value,
                                            "observed": signal.observed,
                                            "threshold": signal.threshold,
                                            "occurrences": signal.occurrences,
                                            "window": signal.window, "detail": signal.detail})
            # 1. evidence threshold
            if not signal.actionable:
                draft.skipped = "below evidence threshold (noise)"
                drafts.append(draft)
                continue
            # 2. dedup within this batch
            if key in seen_keys:
                draft.skipped = "duplicate within batch"
                drafts.append(draft)
                continue
            # 3. dedup + cooldown against the registry
            prior = by_id.get(defn.experiment_id)
            if prior is not None:
                if prior["status"] in ("Proposed", "Baseline Ready", "Running",
                                       "Awaiting Verification"):
                    draft.skipped = "open proposal already exists (dedup)"
                    drafts.append(draft)
                    continue
                if _age_hours(prior["created_at"], now_iso) < cooldown_hours:
                    draft.skipped = f"within cooldown ({cooldown_hours}h)"
                    drafts.append(draft)
                    continue
            seen_keys.add(key)
            if apply and draft.skipped == "":
                # land as a non-approved Proposed experiment (a Backlog card)
                self.reg.register(defn, mission_id=None)
                self.reg.append_event(EventRecord(
                    kind=ExperimentEventType.EXPERIMENT_REGISTERED.value,
                    experiment_id=defn.experiment_id, actor_role="proactive-runner",
                    action=f"drafted from evidence: {signal.source.value}",
                    detail=draft.evidence))
            drafts.append(draft)
        return drafts


def _primary_direction(signal: EvidenceSignal) -> MetricDirection:
    # the primary outcome wants the signal to go DOWN (fewer failures/tokens/latency)
    return MetricDirection.DECREASE
