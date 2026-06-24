"""
A `Finding` — one classified, evidence-bearing improvement candidate.

Carries everything the ranker and the report/card drafter need: the pillar, named source +
quoted evidence, a confidence, the suggested target type + risk tier, the inputs to ICE/RICE/
WSJF/VOI, and an explicit "what we don't know" so uncertainty is never collapsed. Pure data.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..schema import (
    LIVE_MODEL_BENCHMARK_TARGET_REF,
    BudgetDefinition, ExperimentDefinition, MetricDefinition, MetricDirection,
    PostWatchDefinition, PromotionDefinition, TargetType, VerificationDefinition,
)
from ...schemas.base import RiskTier
from .pillars import Pillar, target_for


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "x"


@dataclass
class Finding:
    pillar: Pillar
    source: str                       # named source: arxiv | litellm_registry | code_health | ...
    title: str
    claim: str                        # one-line claim
    evidence: str                     # named source + quote/detail (decision-grade)
    confidence: float = 0.5           # 0..1
    target_ref: str = ""              # what a drafted card would change (namespaced, safe default)
    suggested_target_type: TargetType | None = None
    suggested_risk: RiskTier = RiskTier.L2
    # ranking inputs (all 0..1 unless noted)
    impact: float = 0.5               # business value / expected metric lift
    ease: float = 0.5                 # inverse difficulty (ICE)
    reach: float = 1.0                # breadth affected (RICE)
    effort: float = 1.0              # job size (RICE/WSJF), > 0
    time_criticality: float = 0.0     # WSJF cost-of-delay component
    risk_reduction: float = 0.0       # WSJF cost-of-delay component (rescues CVE/debt work)
    voi_value: float = 0.5            # value if the experiment resolves the decision
    voi_prob: float = 0.5            # P(experiment changes the decision)
    cost: float = 1.0                # expected experiment cost (budget units), > 0
    unknowns: str = ""                # explicit "what we don't know"
    dedup_key: str = ""               # stable key for dedup + cooldown
    detail: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.suggested_target_type is None:
            self.suggested_target_type = target_for(self.pillar)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0,1]")
        if self.effort <= 0 or self.cost <= 0:
            raise ValueError("effort and cost must be > 0")
        if not self.dedup_key:
            self.dedup_key = f"{self.pillar.value}:{_slug(self.title)}"
        if not self.target_ref:
            # namespaced + offline-safe; if a finding genuinely targets a control-plane
            # surface the source slug will carry the marker and the contract will (correctly)
            # demand elevated human review rather than letting an observer draft it quietly.
            self.target_ref = f"discovery/{self.pillar.value}/{_slug(self.source)}"

    @property
    def experiment_id(self) -> str:
        h = hashlib.sha256(self.dedup_key.encode()).hexdigest()[:8]
        return f"EXP-scan-{self.pillar.value[:4]}-{_slug(self.title)[:24]}-{h}"

    def to_experiment_definition(self) -> ExperimentDefinition:
        """Render this finding as a BOUNDED, secret-free, L2-capped `Proposed` experiment —
        the only kind of card an observer may draft. Mirrors the proactive-runner draft shape:
        a required primary outcome + a required safety metric that may never regress, zero token/
        cost/GPU budget (the experiment is defined, not executed here), human-gated promotion.

        EXCEPTION: a discovered MODEL candidate that carries a resolved `model_benchmark`
        (role/suite/incumbent/candidate/endpoint) renders a RUNNABLE live-A/B card instead of
        the inert shell, so it can advance past Proposed on its own — still human-gated for
        canary/promotion."""
        tt = self.suggested_target_type or target_for(self.pillar)
        mb = self.detail.get("model_benchmark") if isinstance(self.detail, dict) else None
        ref = self.target_ref
        if tt == TargetType.MODEL and ref == LIVE_MODEL_BENCHMARK_TARGET_REF:
            if isinstance(mb, dict) and mb:
                return self._model_experiment_definition(mb)
            # A MODEL finding aimed at the live harness but WITHOUT resolved params would be an
            # inert card (rank-2 rejects it). Retarget the bounded shell to a 'needs-params'
            # ref so it stays an honest "a human must author the benchmark" proposal.
            ref = "command_center.improvement.model_benchmark_needed"
        primary = MetricDefinition(
            name="primary_outcome", direction=MetricDirection.INCREASE, required=True,
            baseline_source="measured on the current behavior",
            candidate_source="measured on the proposed change",
            minimum_improvement=0.0, maximum_regression=0.0)
        safety = MetricDefinition(
            name="safety_regressions", direction=MetricDirection.DECREASE, required=True,
            safety=True, baseline_source="count of safety violations (baseline)",
            candidate_source="count of safety violations (candidate)", maximum_regression=0.0)
        return ExperimentDefinition(
            experiment_id=self.experiment_id,
            title=f"[scan:{self.pillar.value}] {self.title}"[:120],
            owner="self-improvement-scan",
            target_type=tt,
            target_ref=ref,
            problem_statement=f"{self.claim} (source: {self.source}). Evidence: {self.evidence}",
            hypothesis=(f"A bounded change to {ref} improves the {self.pillar.value} "
                        "pillar without regressing safety."),
            baseline="current behavior (to be captured by the runner)",
            candidate="proposed change (to be drafted by a human-approved mission)",
            risk_tier=self.suggested_risk,
            automated=True,
            metrics=[primary, safety],
            budgets=BudgetDefinition(
                max_iterations=3, max_wall_minutes=30, max_input_tokens=0, max_output_tokens=0,
                max_cost_usd=0, max_gpu_hours=0, max_changed_files=10, max_diff_lines=500),
            verification=VerificationDefinition(
                reproduce_commands=[
                    f"python -m command_center.cli.improvement verify {self.experiment_id}"],
                required_evidence=["raw before/after logs", "metric summary with sample count"]),
            promotion=PromotionDefinition(),
            post_watch=PostWatchDefinition(
                monitored_metrics=["primary_outcome", "safety_regressions"],
                rollback_triggers=["safety_regressions increases", "primary_outcome regresses"]),
        )

    def _model_experiment_definition(self, mb: dict) -> ExperimentDefinition:
        """A RUNNABLE model A/B card: parameters.model_benchmark is populated (role, suite,
        suite_path, baseline incumbent, candidate tag, base_url/env, fit-derived context), so
        the live harness can execute it. Metrics mirror the harness outputs; safety may never
        regress. Still Proposed + human-gated for canary/promotion."""
        role = mb.get("role", "?")
        success = MetricDefinition(
            name="task_success_rate", direction=MetricDirection.INCREASE, required=True,
            baseline_source="live benchmark: incumbent role suite",
            candidate_source="live benchmark: candidate role suite",
            minimum_improvement=0.0, maximum_regression=0.0)
        unsafe = MetricDefinition(
            name="unsafe_output_rate", direction=MetricDirection.DECREASE, required=True,
            safety=True, baseline_source="live benchmark: incumbent unsafe-output rate",
            candidate_source="live benchmark: candidate unsafe-output rate",
            maximum_regression=0.0)
        invalid = MetricDefinition(
            name="invalid_response_rate", direction=MetricDirection.DECREASE, required=True,
            baseline_source="live benchmark: incumbent invalid-response rate",
            candidate_source="live benchmark: candidate invalid-response rate",
            maximum_regression=0.0)
        return ExperimentDefinition(
            experiment_id=self.experiment_id,
            title=f"[scan:model] benchmark {mb.get('candidate_model')} for {role}"[:120],
            owner="self-improvement-scan",
            target_type=TargetType.MODEL,
            target_ref=LIVE_MODEL_BENCHMARK_TARGET_REF,
            problem_statement=f"{self.claim} (source: {self.source}). Evidence: {self.evidence}",
            hypothesis=(f"Candidate {mb.get('candidate_model')} improves the {role} role on the "
                        f"{mb.get('suite')} suite without regressing safety vs incumbent "
                        f"{mb.get('baseline_model')}."),
            baseline=f"incumbent {mb.get('baseline_model')} on the {role} suite",
            candidate=f"candidate {mb.get('candidate_model')} on the {role} suite",
            parameters={"model_benchmark": dict(mb)},
            risk_tier=self.suggested_risk,
            automated=True,
            metrics=[success, unsafe, invalid],
            budgets=BudgetDefinition(
                max_iterations=2, max_wall_minutes=30, max_input_tokens=200000,
                max_output_tokens=50000, max_cost_usd=0, max_gpu_hours=1.0,
                max_changed_files=0, max_diff_lines=0),
            verification=VerificationDefinition(
                reproduce_commands=[
                    f"python -m command_center.cli.improvement verify {self.experiment_id}"],
                required_evidence=["raw before/after logs", "metric summary with sample count"]),
            promotion=PromotionDefinition(),
            post_watch=PostWatchDefinition(
                monitored_metrics=["task_success_rate", "unsafe_output_rate",
                                   "invalid_response_rate"],
                rollback_triggers=["unsafe_output_rate increases",
                                   "task_success_rate regresses"]),
        )

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["pillar"] = self.pillar.value
        d["suggested_target_type"] = self.suggested_target_type.value \
            if self.suggested_target_type else None
        d["suggested_risk"] = self.suggested_risk.value
        d["experiment_id"] = self.experiment_id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Finding:
        """Inverse of to_dict — used to round-trip a Finding across Airflow task XComs."""
        d = dict(d)
        d.pop("experiment_id", None)                      # derived, never set directly
        d["pillar"] = Pillar(d["pillar"])
        tt = d.get("suggested_target_type")
        d["suggested_target_type"] = TargetType(tt) if tt else None
        d["suggested_risk"] = RiskTier(d["suggested_risk"])
        return cls(**d)
