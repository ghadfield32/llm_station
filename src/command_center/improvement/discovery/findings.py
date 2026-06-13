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
        cost/GPU budget (the experiment is defined, not executed here), human-gated promotion."""
        tt = self.suggested_target_type or target_for(self.pillar)
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
            target_ref=self.target_ref,
            problem_statement=f"{self.claim} (source: {self.source}). Evidence: {self.evidence}",
            hypothesis=(f"A bounded change to {self.target_ref} improves the {self.pillar.value} "
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
