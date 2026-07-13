from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class RemoteType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class AutomationClass(StrEnum):
    BOT_POSSIBLE = "bot_possible"
    PREPARE_ONLY = "prepare_only"
    MANUAL_REQUIRED = "manual_required"
    SKIP = "skip"


class FitAction(StrEnum):
    APPLY_NOW = "APPLY_NOW"
    APPLY_MANUAL = "APPLY_MANUAL"
    NETWORK_FIRST = "NETWORK_FIRST"
    SAVE_FOR_LATER = "SAVE_FOR_LATER"
    UPSKILL_FIRST = "UPSKILL_FIRST"
    SKIP = "SKIP"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class JobSearchRuntime(Strict):
    enabled: bool = False
    timezone: str = "America/New_York"
    daily_run_time: str = "08:00"
    require_geoff_selection: bool = True
    submit_without_geoff_selection: bool = False
    auto_submit_enabled: bool = False
    max_suggested_jobs_per_day: int = Field(default=25, ge=1, le=100)
    max_bot_possible_suggestions_per_day: int = Field(default=25, ge=0, le=100)
    max_manual_required_suggestions_per_day: int = Field(default=25, ge=0, le=100)
    max_selected_jobs_per_day: int = Field(default=5, ge=1, le=25)
    board_name: str = "job_search_pipeline"
    data_root: str = "data/job_search"
    digest_path: str = "generated/job-search-digest.md"

    @model_validator(mode="after")
    def _checks(self):
        if self.submit_without_geoff_selection:
            raise ValueError("submit_without_geoff_selection must remain false")
        if self.auto_submit_enabled:
            raise ValueError("auto_submit_enabled is intentionally disabled for the MVP")
        if not self.require_geoff_selection:
            raise ValueError("require_geoff_selection must remain true")
        if not self.board_name:
            raise ValueError("board_name is required")
        return self


class JobSearchRanking(Strict):
    min_score_to_show: int = Field(default=70, ge=0, le=100)
    min_score_to_recommend_apply: int = Field(default=82, ge=0, le=100)
    sports_domain_bonus: int = Field(default=8, ge=0, le=20)
    founder_operator_bonus_for_startups: int = Field(default=6, ge=0, le=20)
    missing_salary_penalty: int = Field(default=3, ge=0, le=20)
    manual_required_penalty: int = Field(default=5, ge=0, le=20)
    target_company_bonus: int = Field(default=6, ge=0, le=20)

    @model_validator(mode="after")
    def _checks(self):
        if self.min_score_to_recommend_apply < self.min_score_to_show:
            raise ValueError("min_score_to_recommend_apply must be >= min_score_to_show")
        return self


class JobSearchRetention(Strict):
    rich_application_cache_days: int = Field(default=30, ge=1, le=365)
    extend_when_active: bool = True
    purge_rich_files: bool = False
    active_statuses: list[str]

    @model_validator(mode="after")
    def _checks(self):
        if not self.active_statuses:
            raise ValueError("retention.active_statuses cannot be empty")
        return self


class JobSearchAutomation(Strict):
    confidence_threshold: float = Field(default=0.85, ge=0, le=1)
    mvp_submit_behavior: Literal["disabled_prepare_only"] = "disabled_prepare_only"
    manual_portals: list[str]
    manual_phrases: list[str]
    blocked_actions: list[str]

    @model_validator(mode="after")
    def _checks(self):
        if not self.manual_portals:
            raise ValueError("automation.manual_portals cannot be empty")
        if not self.manual_phrases:
            raise ValueError("automation.manual_phrases cannot be empty")
        required = {
            "bypass_login",
            "bypass_mfa",
            "bypass_captcha",
            "answer_eeo",
            "answer_self_id",
            "answer_legal_certification",
            "send_message_without_approval",
            "submit_restricted_application",
            "mass_apply",
        }
        missing = required - set(self.blocked_actions)
        if missing:
            raise ValueError(f"automation.blocked_actions missing {sorted(missing)}")
        return self


class ApplicationQuestions(Strict):
    default_policy: Literal["draft_or_route_manual"]
    review_required: list[str]
    draft_defaults: dict[str, str]
    never_auto_answer: list[str]

    @model_validator(mode="after")
    def _checks(self):
        if not self.review_required:
            raise ValueError("application_questions.review_required cannot be empty")
        if not self.draft_defaults:
            raise ValueError("application_questions.draft_defaults cannot be empty")
        missing = set(self.never_auto_answer) - set(self.review_required)
        if missing:
            raise ValueError(
                "application_questions.never_auto_answer must be a subset of review_required: "
                f"{sorted(missing)}"
            )
        return self


class JobCategory(Strict):
    id: str
    resume_variant: str
    keywords: list[str]
    role_focus: Literal["primary", "secondary"] = "primary"


class CompanyTargets(Strict):
    faang: list[str] = []
    sports_teams_keywords: list[str] = []
    sports_tech_companies: list[str] = []
    major_other: list[str] = []


class ExecutorFallback(Strict):
    primary: str
    fallback: str
    prompt_path: str
    rule: str

    @model_validator(mode="after")
    def _checks(self):
        if self.primary == self.fallback:
            raise ValueError("executor fallback must name different executors")
        if not self.prompt_path.endswith(".md"):
            raise ValueError("executor fallback prompt_path must be a markdown file")
        return self


class JobSearchConfig(Strict):
    schema_version: str
    job_search: JobSearchRuntime
    ranking: JobSearchRanking
    retention: JobSearchRetention
    automation: JobSearchAutomation
    application_questions: ApplicationQuestions
    resume_variants: list[str]
    job_categories: list[JobCategory]
    executor_fallback: ExecutorFallback
    company_targets: CompanyTargets = Field(default_factory=CompanyTargets)

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.job-search.v1":
            raise ValueError("schema_version must be command-center.job-search.v1")
        if not self.resume_variants:
            raise ValueError("resume_variants cannot be empty")
        category_ids = [c.id for c in self.job_categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("duplicate job category ids")
        for category in self.job_categories:
            if category.resume_variant not in self.resume_variants:
                raise ValueError(
                    f"category {category.id!r} references unknown resume variant "
                    f"{category.resume_variant!r}"
                )
            if not category.keywords:
                raise ValueError(f"category {category.id!r} must define keywords")
        return self


class ProjectType(StrEnum):
    PYTHON_PROJECT = "python_project"
    ENGINEERING_PROJECT = "engineering_project"
    ANALYST_PROJECT = "analyst_project"
    LEADERSHIP_PROJECT = "leadership_project"
    FOUNDER_PROJECT = "founder_project"


class Achievement(Strict):
    id: str
    title: str
    company: str
    role: str
    dates: str
    type: Literal["experience", "project", "education", "certification", "leadership"]
    categories: list[str] = []
    role_families: list[str] = []
    tools: list[str] = []
    domains: list[str] = []
    metrics: list[str] = []
    bullet_versions: dict[str, str | None] = {}
    evidence_files: list[str] = []
    confidence: Confidence = Confidence.HIGH
    resume_safe: bool = True
    notes: str | None = None
    project_type: ProjectType | None = None
    full_story: str | None = None

    @model_validator(mode="after")
    def _checks(self):
        if self.resume_safe and not self.evidence_files:
            raise ValueError(f"resume-safe achievement {self.id!r} needs evidence_files")
        return self


class AchievementBank(Strict):
    schema_version: str = "command-center.job-search.achievement-bank.v1"
    achievements: list[Achievement]

    @model_validator(mode="after")
    def _checks(self):
        ids = [a.id for a in self.achievements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate achievement ids")
        return self


class CanonicalJob(Strict):
    job_key: str
    source: str = "local_file"
    source_id: str | None = None
    company: str
    role_title: str
    normalized_company: str
    normalized_role: str
    location: str
    remote_type: RemoteType = RemoteType.UNKNOWN
    portal: str = "unknown"
    apply_url: str
    description_text: str
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    posted_at: datetime | None = None
    deadline: datetime | None = None
    last_seen_at: datetime


class FitResult(Strict):
    score: int = Field(ge=0, le=100)
    action: FitAction
    reasons: list[str]
    risks: list[str] = []
    gaps: list[str] = []
    evidence_achievement_ids: list[str] = []
    company_tier: str = "none"
    explanation: str = ""


class AutomationResult(Strict):
    value: AutomationClass
    reason: str
    confidence: float = Field(ge=0, le=1)
    blockers: list[str] = []
    # detected questions covered by profile/standing_answers.yml — rendered
    # into the packet's application_answers.md instead of blocking automation
    auto_answered: list[str] = []
    mvp_submit_disabled: bool = True


class ResumeSelection(Strict):
    resume_variant: str
    selected_achievement_ids: list[str]
    selected_bullets: list[str]
    matched_keywords: list[str]
    unsupported_keywords: list[str]
    rejected_claims: list[str] = []
    wms_treatment: str


class ApplicationSalary(Strict):
    listed: bool = False
    min: int | None = None
    max: int | None = None
    currency: str | None = None
    notes: str | None = None


class ApplicationRecord(Strict):
    application_id: str
    company: str
    role_title: str
    category: str
    source: str
    portal: str
    apply_url: str
    status: str
    stage: str
    automation_class: AutomationClass
    manual_required: bool
    manual_reason: str | None = None
    # questions detected in the posting that Geoff's standing answers cover —
    # handled, not blocking. Persisted so the card/story can show them as such.
    auto_answered: list[str] = []
    resume_variant: str
    applied_at: str | None = None
    last_activity_at: str
    retention_until: str
    keep_rich: bool = False
    salary: ApplicationSalary
    fit: FitResult
    keywords: dict[str, list[str]]
    materials: dict[str, str]
    followup: dict[str, object]
    bullet_ids_used: list[str] = []
    archived_at: str | None = None
    rich_compacted: bool = False
    # Agent-writer provenance: mode is "agent" (LLM-generated, trace on disk) or
    # "template_fallback" (deterministic templates; error records why). Never
    # silently absent for new packets — validation surfaces the mode to Geoff.
    generation: dict[str, object] = {}
    # Bumped every time materials are regenerated from reviewer notes.
    revision: int = 1
    # "ready_for_review" | "changes_requested" — the packet-review gate state.
    review_state: str = "ready_for_review"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
