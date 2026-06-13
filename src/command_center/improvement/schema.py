"""
The improvement-experiment contract — configs/improvement.yaml validates against this.

Same discipline as the rest of configs/: strict (extra="forbid"), and strict
exactly where it prevents real breakage. An experiment that disables human approval,
omits a baseline, lets a safety metric regress without limit, or asks to promote
itself fails `make improvement-validate` — it never reaches the runner.

Rejected at validation time (each has a contract test):
  * automatic_promotion true
  * human approval disabled
  * rollback absent
  * no baseline
  * no required metric
  * a safety metric with an unbounded maximum_regression
  * candidate evaluates itself (independent_context off / self-verification allowed)
  * any budget field missing
  * an L3/L4 experiment (experiments run as isolated L2-or-lower missions)
  * a secret-bearing repo_task requested
  * raw-evidence retention disabled
  * a control-plane target (approval / Ledger / GitHub wall) without elevated human review
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ..schemas.base import Strict, RiskTier
from .lifecycle import ExperimentStatus


class TargetType(StrEnum):
    MODEL = "model"
    PROMPT = "prompt"
    SKILL = "skill"
    JUDGE = "judge"
    ROUTING = "routing"
    TOOL = "tool"
    RETRIEVAL = "retrieval"
    MEMORY = "memory"
    STANDARD = "standard"
    PROACTIVE_CHECK = "proactive_check"
    WORKFLOW = "workflow"
    DOCUMENTATION = "documentation"
    REPOSITORY_TEMPLATE = "repository_template"


class MetricDirection(StrEnum):
    INCREASE = "increase"     # higher is better (e.g. recall, pass rate)
    DECREASE = "decrease"     # lower is better (e.g. latency, tokens, cost, false blocks)


# Control-plane surfaces a target may not touch without elevated human review.
_CONTROL_PLANE_MARKERS = (
    "services/ledger", "ledger.db", "gates.yaml", "approval", "github", ".git/",
    "branch_protection", "codeowners",
)


class MetricDefinition(Strict):
    name: str
    direction: MetricDirection
    required: bool = False
    safety: bool = False                          # safety metrics may never regress without a limit
    relative: bool = False                        # thresholds are fractions of the baseline, not native units
    baseline_source: str                          # how the baseline value is measured
    candidate_source: str                         # how the candidate value is measured
    minimum_improvement: float | None = Field(default=None)   # required delta to count as a win
    maximum_regression: float | None = Field(default=None)    # worst tolerated regression (>=0)

    @model_validator(mode="after")
    def _checks(self):
        if not self.name:
            raise ValueError("metric needs a name")
        if self.maximum_regression is not None and self.maximum_regression < 0:
            raise ValueError(f"metric '{self.name}' maximum_regression must be >= 0")
        # A safety metric with no regression ceiling is the dangerous case — reject it.
        if self.safety:
            if not self.required:
                raise ValueError(f"safety metric '{self.name}' must be required")
            if self.maximum_regression is None:
                raise ValueError(
                    f"safety metric '{self.name}' must set a finite maximum_regression "
                    "(safety may never regress without limit)"
                )
        return self


class BudgetDefinition(Strict):
    """Every field is required. A missing budget is how experiments run away, so
    'absent' is rejected; an explicit 0 means 'none of this resource is permitted'."""
    max_iterations: int = Field(ge=1)
    max_wall_minutes: int = Field(ge=1)
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_cost_usd: float = Field(ge=0)
    max_gpu_hours: float = Field(ge=0)
    max_changed_files: int = Field(ge=0)
    max_diff_lines: int = Field(ge=0)


class VerificationDefinition(Strict):
    independent_context: bool = True
    different_model_family_preferred: bool = True
    allow_self_verification: bool = False          # contract refuses True
    reproduce_commands: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    sealed_eval_ids: list[str] = Field(default_factory=list)
    adversarial_eval_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if not self.independent_context:
            raise ValueError("verification.independent_context must be true — the "
                             "candidate cannot evaluate itself")
        if self.allow_self_verification:
            raise ValueError("verification.allow_self_verification must be false")
        if not self.reproduce_commands:
            raise ValueError("verification.reproduce_commands cannot be empty — the "
                             "verifier must be given commands to reproduce independently")
        if not self.required_evidence:
            raise ValueError("verification.required_evidence cannot be empty")
        # Raw evidence must be retained for the verifier and the audit trail.
        joined = " ".join(self.required_evidence).lower()
        if not any(tok in joined for tok in ("raw", "log", "stdout", "stderr", "artifact")):
            raise ValueError(
                "verification.required_evidence must retain raw evidence "
                "(raw logs / stdout / stderr / artifacts), not only a summary"
            )
        return self


class PromotionDefinition(Strict):
    human_approval_required: bool = True
    canary_required: bool = True
    rollback_required: bool = True
    automatic_promotion: bool = False              # contract refuses True
    minimum_observation_period: str = "24h"
    elevated_human_review: bool = False            # required for control-plane targets

    @model_validator(mode="after")
    def _checks(self):
        if self.automatic_promotion:
            raise ValueError("promotion.automatic_promotion must be false — no "
                             "component may promote itself")
        if not self.human_approval_required:
            raise ValueError("promotion.human_approval_required must be true")
        if not self.rollback_required:
            raise ValueError("promotion.rollback_required must be true")
        return self


class PostWatchDefinition(Strict):
    checkpoints: list[str] = Field(default_factory=lambda: ["1h", "24h", "7d"])
    monitored_metrics: list[str] = Field(default_factory=list)
    rollback_triggers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if not self.checkpoints:
            raise ValueError("post_watch.checkpoints cannot be empty")
        if not self.rollback_triggers:
            raise ValueError("post_watch.rollback_triggers cannot be empty — define "
                             "what a regression looks like before promoting")
        return self


class StatisticalPlan(Strict):
    """Pre-registered statistical protocol (mission research roadmap, Area A1). Optional and
    defaulted, so existing experiments validate unchanged. When `require_significance` is on,
    the verifier gates eligibility on a statistically significant (FDR-controlled) win on the
    primary metric — it still only *rejects*; a human still promotes."""
    alpha: float = Field(default=0.05, gt=0, lt=1)
    power: float = Field(default=0.8, gt=0, lt=1)
    mde: float | None = Field(default=None, ge=0)        # pre-registered min detectable effect
    test_type: Literal["paired", "unpaired", "auto"] = "auto"
    fdr_family_id: str | None = None                      # group experiments for FDR control
    n_resamples: int = Field(default=2000, ge=200)
    seed: int = 12345
    require_significance: bool = False                    # off by default (non-breaking)
    primary_metric: str | None = None                    # the OEC; inferred if omitted
    guardrail_metrics: list[str] = Field(default_factory=list)


class ExperimentDefinition(Strict):
    experiment_id: str
    title: str
    owner: str
    target_type: TargetType
    target_ref: str                                # what is being changed (file/role/skill/...)
    problem_statement: str
    hypothesis: str
    baseline: str                                  # description / ref of the current behavior
    candidate: str                                 # description / ref of the proposed change
    risk_tier: RiskTier = RiskTier.L2
    status: ExperimentStatus = ExperimentStatus.PROPOSED
    automated: bool = True                         # proactive-proposed + runner-driven by default
    requests_secrets: bool = False                 # experiments run secret-free; contract refuses True
    retain_raw_evidence: bool = True               # contract refuses False
    created_at: str | None = None
    expires_at: str | None = None

    metrics: list[MetricDefinition]
    budgets: BudgetDefinition
    verification: VerificationDefinition
    promotion: PromotionDefinition
    post_watch: PostWatchDefinition
    statistics: StatisticalPlan = Field(default_factory=StatisticalPlan)

    @model_validator(mode="after")
    def _checks(self):
        if not self.experiment_id:
            raise ValueError("experiment_id is required")
        if not self.baseline:
            raise ValueError(f"experiment '{self.experiment_id}' has no baseline defined")
        if not self.metrics:
            raise ValueError(f"experiment '{self.experiment_id}' defines no metrics")
        if not any(m.required for m in self.metrics):
            raise ValueError(f"experiment '{self.experiment_id}' has no required metric — "
                             "at least one metric must be required to judge the result")

        # Experiments run as isolated local missions. External writes / dangerous
        # actions never originate from an experiment; they happen through the normal
        # gates AFTER a human promotion. So an experiment can never *be* L3/L4.
        if self.risk_tier in (RiskTier.L3, RiskTier.L4):
            raise ValueError(
                f"experiment '{self.experiment_id}' risk_tier={self.risk_tier.value} not allowed; "
                "experiments cap at L2 (isolated local edits) — L3/L4 actions cannot be "
                "requested from an automated experiment"
            )

        if self.requests_secrets:
            raise ValueError(
                f"experiment '{self.experiment_id}' requests secrets; experiment missions run in "
                "ephemeral, secret-free repo_task environments"
            )
        if not self.retain_raw_evidence:
            raise ValueError(
                f"experiment '{self.experiment_id}' disables raw-evidence retention; "
                "raw positive and negative evidence must be preserved"
            )

        # Control-plane targets (approval / Ledger / GitHub wall) need elevated human review.
        ref = self.target_ref.lower()
        if any(marker in ref for marker in _CONTROL_PLANE_MARKERS):
            if not self.promotion.elevated_human_review:
                raise ValueError(
                    f"experiment '{self.experiment_id}' targets a control-plane surface "
                    f"({self.target_ref!r}) but promotion.elevated_human_review is false; "
                    "changing the approval, Ledger, or GitHub wall requires elevated human review"
                )

        # monitored post-watch metrics must be real metric names
        names = {m.name for m in self.metrics}
        unknown = [m for m in self.post_watch.monitored_metrics if m not in names]
        if unknown:
            raise ValueError(
                f"experiment '{self.experiment_id}' post_watch.monitored_metrics "
                f"references unknown metric(s) {unknown}"
            )
        # the statistical plan must reference real metrics
        sp = self.statistics
        if sp.primary_metric is not None and sp.primary_metric not in names:
            raise ValueError(
                f"experiment '{self.experiment_id}' statistics.primary_metric "
                f"{sp.primary_metric!r} is not a defined metric")
        unknown_g = [m for m in sp.guardrail_metrics if m not in names]
        if unknown_g:
            raise ValueError(
                f"experiment '{self.experiment_id}' statistics.guardrail_metrics "
                f"references unknown metric(s) {unknown_g}")
        return self


class ImprovementConfig(Strict):
    schema_version: str
    experiments: list[ExperimentDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        ids = [e.experiment_id for e in self.experiments]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate experiment_id values in improvement.yaml")
        return self


# ---------------------------------------------------------------------------
# Discovery-scan knobs (configs/discovery.yaml). The CONTRACT lives here — beside the
# other improvement contracts and importable without pulling the heavy discovery package
# (charter/registry/...) into `make validate`. The yaml LOADER lives in
# discovery/config.py. No scan decision is an inline literal; an explicit, documented
# config knob is the sanctioned form ("a config knob, not in-line magic").
# ---------------------------------------------------------------------------

class RankingKnobs(Strict):
    confidence_band_half_width: float = Field(default=0.15, gt=0, lt=1)   # ~1/sqrt(n_sources)
    default_method: Literal["ice", "rice", "wsjf", "voi"] = "wsjf"


class TriageKnobs(Strict):
    min_confidence: float = Field(default=0.4, ge=0, le=1)     # below this a finding is noise
    cooldown_hours: float = Field(default=168.0, gt=0)         # re-propose window for soft terminals
    max_cards: int = Field(default=20, ge=1)                   # per-run card cap (overflow reported)


class CodeHealthKnobs(Strict):
    """Absolute maintainability bounds (documented config knobs): a function over N
    statements or a module over M lines is a refactor candidate regardless of repo norms."""
    max_function_statements: int = Field(default=60, ge=1)
    max_module_lines: int = Field(default=600, ge=1)
    min_debt_markers: int = Field(default=12, ge=1)
    min_swallowed_excepts: int = Field(default=1, ge=1)
    sample_limit: int = Field(default=6, ge=1)


class AcceptanceKnobs(Strict):
    """Governs the learned P(accept) ranker (discovery/acceptance.py). Mirrors the modeling
    guides' sanctioned documented minimums (e.g. GBDT's sample-size floor)."""
    min_decisions: int = Field(default=40, ge=1)               # below this, abstain → use formula
    holdout_fraction: float = Field(default=0.3, gt=0, lt=1)   # temporal holdout for champ/challenger
    min_auc_uplift: float = Field(default=0.02, ge=0)          # challenger must beat formula by this
    learning_rate: float = Field(default=0.1, gt=0)            # logistic GD step
    max_iterations: int = Field(default=500, ge=1)             # logistic GD iterations
    l2: float = Field(default=1.0, ge=0)                       # ridge penalty (regularization)


class DiscoveryConfig(Strict):
    schema_version: str
    ranking: RankingKnobs = Field(default_factory=RankingKnobs)
    triage: TriageKnobs = Field(default_factory=TriageKnobs)
    code_health: CodeHealthKnobs = Field(default_factory=CodeHealthKnobs)
    acceptance: AcceptanceKnobs = Field(default_factory=AcceptanceKnobs)
