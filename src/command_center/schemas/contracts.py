"""
The config contracts. One file — these are small and related, so splitting them
into ten modules would be ceremony, not clarity. Each top-level class maps to one
configs/*.yaml file.
"""
from __future__ import annotations
from typing import Literal
from pydantic import Field, model_validator
from .base import Strict, RiskTier, Decision, Provider, EnvKind


# ---- models.yaml ------------------------------------------------------------
class ModelCandidate(Strict):
    alias: str
    provider: Provider
    model: str
    priority: int = Field(ge=1)
    local: bool = False
    monthly_budget_usd: float | None = Field(default=None, ge=0)
    canary_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    vram_gb: int | None = Field(default=None, ge=1)
    license: str | None = None
    notes: str | None = None


class ScoutSpec(Strict):
    """The model scout: watches sources (leaderboards, model cards, provider
    docs) and PROPOSES updates as PRs against this file. It can never promote.
    Leaderboards are a discovery signal, not an authority — promotion requires
    the canary + `make evals` regression gate + a human tap, because public
    leaderboards are gameable and a board-topping model can still be worse for
    THIS system's judges and diffs."""
    cadence: str = "monthly"                      # how often the scout mission runs
    sources: list[str] = []                       # urls/names: lmarena, hf-leaderboards, provider blogs
    propose_only: bool = True                     # contract refuses False — no auto-promotion
    max_candidates_per_run: int = Field(default=3, ge=1, le=10)


class ExecutorSpec(Strict):
    """A CLI coding agent that drives the leased worktree/devcontainer (Claude
    Code, Codex CLI). Distinct from the `coder` API role: the executor is the
    agent harness; coder_alias is the LiteLLM route it speaks through. Swapping
    or reordering executors is a YAML edit here, nothing else."""
    name: str                                     # claude-code | codex-cli | ...
    family: Provider                              # anthropic | openai — for cross-provider review pairing
    command: str                                  # the CLI binary the worker invokes
    coder_alias: str                              # must exist in roles.coder
    priority: int = Field(ge=1)                   # 1 = primary, 2 = first fallback, ...


class ModelRegistry(Strict):
    schema_version: str
    roles: dict[str, list[ModelCandidate]]
    executors: list[ExecutorSpec] = []
    scout: ScoutSpec | None = None
    local_whitelist: list[str] = []

    @model_validator(mode="after")
    def _checks(self):
        if self.scout is not None and not self.scout.propose_only:
            raise ValueError("scout.propose_only must stay true — models are never auto-promoted; "
                             "the path is scout PR -> validate -> canary -> evals -> human tap")
        for role, cands in self.roles.items():
            if not cands:
                raise ValueError(f"role '{role}' has no candidates")
            for c in cands:
                if c.provider != Provider.OLLAMA:
                    raise ValueError(
                        f"role '{role}' candidate '{c.alias}' uses provider '{c.provider}'; "
                        "LiteLLM roles are local-only and must use provider: ollama"
                    )
                if not c.local:
                    raise ValueError(
                        f"role '{role}' candidate '{c.alias}' must set local: true"
                    )
            # priorities must be unique within a role (deterministic ordering)
            pr = [c.priority for c in cands]
            if len(pr) != len(set(pr)):
                raise ValueError(f"role '{role}' has duplicate priorities {pr}")
            # at most one canary per role
            if sum(1 for c in cands if c.canary_weight > 0) > 1:
                raise ValueError(f"role '{role}' has more than one canary")
        if self.executors:
            pr = [e.priority for e in self.executors]
            if len(pr) != len(set(pr)) or 1 not in pr:
                raise ValueError("executors need unique priorities including exactly one priority-1 primary")
            names = [e.name for e in self.executors]
            if len(names) != len(set(names)):
                raise ValueError("duplicate executor names")
            # every executor must speak through a real coder route
            coder_aliases = {c.alias for c in self.roles.get("coder", [])}
            for e in self.executors:
                if e.coder_alias not in coder_aliases:
                    raise ValueError(f"executor '{e.name}' references unknown coder alias '{e.coder_alias}'")
            # the fallback chain must span >1 provider family, or cross-provider
            # review degenerates and an Anthropic/OpenAI outage stalls all coding
            if len(self.executors) > 1 and len({e.family for e in self.executors}) < 2:
                raise ValueError("executor fallback chain must span at least two provider families")
        return self


# ---- judges.yaml ------------------------------------------------------------
class JudgeSpec(Strict):
    name: str
    role_alias: str                       # which LiteLLM role this judge calls
    blocks_on: list[Decision] = [Decision.BLOCK]
    escalation_role: str | None = None    # cross-provider escalation alias
    max_cost_usd: float = Field(default=0.10, ge=0)
    timeout_seconds: int = Field(default=120, ge=1)


class JudgeStage(Strict):
    stage: str
    cheap_first: bool = True
    judges: list[JudgeSpec]


class JudgeConfig(Strict):
    schema_version: str
    # judge that WRITES must be reviewed by a different provider family
    cross_provider_review: bool = True
    stages: list[JudgeStage]


# ---- gates.yaml -------------------------------------------------------------
class TierPolicy(Strict):
    auto: bool
    requires_approval: bool
    required_stages: list[str]
    forbidden_auto_actions: list[str] = []


class GatesConfig(Strict):
    schema_version: str
    tiers: dict[RiskTier, TierPolicy]

    @model_validator(mode="after")
    def _all_tiers(self):
        missing = set(RiskTier) - set(self.tiers)
        if missing:
            raise ValueError(f"gates.yaml missing tiers: {sorted(m.value for m in missing)}")
        # L3/L4 must require approval — hard safety invariant
        for t in (RiskTier.L3, RiskTier.L4):
            if not self.tiers[t].requires_approval:
                raise ValueError(f"{t.value} must require approval")
        return self


# ---- environments.yaml ------------------------------------------------------
class EnvironmentSpec(Strict):
    name: str
    kind: EnvKind
    host: str
    image: str | None = None
    devcontainer_path: str | None = None
    allowed_egress: list[str] = []
    allowed_secrets: list[str] = []
    max_parallel_tasks: int = Field(default=1, ge=1)
    gpu_required: bool = False
    persistent: bool = False


class EnvironmentsConfig(Strict):
    schema_version: str
    environments: list[EnvironmentSpec]

    @model_validator(mode="after")
    def _checks(self):
        names = [e.name for e in self.environments]
        if len(names) != len(set(names)):
            raise ValueError("duplicate environment names")
        # repo_task must be ephemeral and hold no secrets (isolation invariant)
        for e in self.environments:
            if e.kind == EnvKind.REPO_TASK:
                if e.persistent:
                    raise ValueError(f"repo_task '{e.name}' must be non-persistent")
                if e.allowed_secrets:
                    raise ValueError(f"repo_task '{e.name}' must hold no secrets")
        return self


# ---- proactive.yaml ---------------------------------------------------------
# The proactive lane: scheduled checks on already-done work (DAG/data health and
# repo stewardship). Checks OBSERVE and open gated missions; they never edit
# directly. The invariants below make "wandering refactor agent" unrepresentable.
class ProactiveCheck(Strict):
    name: str
    target: str                                   # what it watches: a DAG system, asset, repo
    schedule: str                                 # cron; the runner is the only thing that reads it
    owner: str                                    # every check is owned by someone
    evidence: list[str] = []                      # what it collects before judging
    checks: list[str] = []                        # named sub-checks (schema, null_rate, structure, ...)
    judges: list[str] = []                         # judge names from judges.yaml stages
    # what happens on a finding. Deliberately NOT "auto_fix": the strongest
    # autonomous action a proactive check can take is opening a gated mission.
    on_fail: str = "open_rca_mission"             # ledger_report | open_rca_mission
    # ceiling on any patch this check is allowed to PROPOSE (still gated downstream).
    auto_patch_max_risk: RiskTier = RiskTier.L0
    max_staleness_hours: int | None = Field(default=None, ge=1)


class ProactiveConfig(Strict):
    schema_version: str
    runtime_checks: list[ProactiveCheck] = []     # DAG/data freshness, quality, drift
    repo_stewardship: list[ProactiveCheck] = []   # structure, tests, docs, defensive-coding debt

    @model_validator(mode="after")
    def _checks(self):
        all_checks = self.runtime_checks + self.repo_stewardship
        names = [c.name for c in all_checks]
        if len(names) != len(set(names)):
            raise ValueError("duplicate proactive check names")
        valid_on_fail = {"ledger_report", "open_rca_mission"}
        for c in all_checks:
            # every check must declare owner, schedule, evidence, and on_fail
            if not c.owner:
                raise ValueError(f"proactive check '{c.name}' must declare an owner")
            if not c.schedule:
                raise ValueError(f"proactive check '{c.name}' must declare a schedule")
            if not c.evidence and not c.checks:
                raise ValueError(f"proactive check '{c.name}' must collect evidence or run checks")
            if c.on_fail not in valid_on_fail:
                raise ValueError(f"'{c.name}' on_fail must be one of {sorted(valid_on_fail)}")
            # proactive cannot auto-push: the most it may PROPOSE is an L2 worktree patch.
            # L3 (external write) and L4 (dangerous) can never originate from a scheduled check.
            if c.auto_patch_max_risk in (RiskTier.L3, RiskTier.L4):
                raise ValueError(
                    f"'{c.name}' auto_patch_max_risk={c.auto_patch_max_risk} not allowed; "
                    "proactive patches cap at L2 and still pass the normal gates")
        # repo stewardship specifically must never propose external writes
        for c in self.repo_stewardship:
            if c.auto_patch_max_risk not in (RiskTier.L0, RiskTier.L1, RiskTier.L2):
                raise ValueError(f"repo stewardship '{c.name}' cannot exceed L2")
        return self


# ---- targets.yaml ----------------------------------------------------------
# The canonical inventory of what the system is responsible for watching: repos,
# DAGs, data assets, services. The proactive lane's `target:` fields should name
# entries here. Invariants make "a target with no owner / no SLO / no check"
# unrepresentable, so the inventory can't silently rot.
class RepoTarget(Strict):
    name: str
    path: str
    owner: str
    criticality: str = "medium"                   # low | medium | high
    standards_profile: str                        # e.g. python_ml_pipeline
    required_checks: list[str] = []
    stewardship_schedule: str | None = None


class DagTarget(Strict):
    name: str
    orchestrator: str                             # airflow | dagster | prefect
    owner: str
    criticality: str = "medium"
    freshness_slo_hours: int | None = Field(default=None, ge=1)
    expected_outputs: list[str] = []
    checks: list[str] = []                         # dag_success, partition_freshness, ...
    on_fail: str = "open_rca_mission"


class DataAssetTarget(Strict):
    name: str
    path: str
    owner: str
    criticality: str = "medium"
    freshness_slo_hours: int | None = Field(default=None, ge=1)
    quality_checks: list[str] = []                # not_empty, expected_columns, ...


class ServiceTarget(Strict):
    name: str
    owner: str
    criticality: str = "medium"
    checks: list[str] = []
    on_fail: str = "ledger_report"


class TargetsConfig(Strict):
    schema_version: str
    repos: list[RepoTarget] = []
    dags: list[DagTarget] = []
    data_assets: list[DataAssetTarget] = []
    services: list[ServiceTarget] = []

    @model_validator(mode="after")
    def _checks(self):
        all_names = ([r.name for r in self.repos] + [d.name for d in self.dags]
                     + [a.name for a in self.data_assets] + [s.name for s in self.services])
        if len(all_names) != len(set(all_names)):
            raise ValueError("duplicate target names across the inventory")
        # high-criticality targets must declare an SLO so a regression is detectable
        for d in self.dags:
            if d.criticality == "high" and d.freshness_slo_hours is None:
                raise ValueError(f"high-criticality DAG '{d.name}' needs a freshness_slo_hours")
            if not d.checks:
                raise ValueError(f"DAG '{d.name}' needs at least one check")
        for a in self.data_assets:
            if a.criticality == "high" and a.freshness_slo_hours is None:
                raise ValueError(f"high-criticality asset '{a.name}' needs a freshness_slo_hours")
            if not a.quality_checks:
                raise ValueError(f"data asset '{a.name}' needs at least one quality_check")
        for r in self.repos:
            if not r.standards_profile:
                raise ValueError(f"repo '{r.name}' needs a standards_profile")
        return self


# ---- kanban.yaml -----------------------------------------------------------
# Human task boards are intake only. They can open Ledger missions, but they
# cannot execute code, bypass approvals, push branches, or call provider APIs.
class KanbanSource(Strict):
    name: str
    kind: Literal["appflowy"] = "appflowy"
    enabled: bool = True
    growthos_root: str = "appflowy_kanban/growth-os"
    database: str = "mission_intake"
    database_map_path: str = "config/databases.json"
    base_url_env: str = "APPFLOWY_BASE_URL"
    workspace_id_env: str = "APPFLOWY_WORKSPACE_ID"
    email_env: str = "APPFLOWY_EMAIL"
    password_env: str = "APPFLOWY_PASSWORD"


class KanbanSection(Strict):
    name: str
    appflowy_section: str
    target_kind: Literal["repo", "dag", "data_asset", "service", "learning"]
    target: str
    default_repo: str = "unknown"
    default_risk: RiskTier = RiskTier.L1
    max_auto_risk: RiskTier = RiskTier.L2
    ready_statuses: list[str] = ["Ready", "Approved"]
    done_statuses: list[str] = ["Done", "Rejected"]
    branch_prefix: str = "kanban"


class KanbanConfig(Strict):
    schema_version: str
    sources: list[KanbanSource] = []
    sections: list[KanbanSection] = []
    dry_run_default: bool = True
    ledger_base_url_env: str = "LEDGER_BASE_URL"
    imported_state_path: str = "generated/kanban-imported.json"

    @model_validator(mode="after")
    def _checks(self):
        source_names = [s.name for s in self.sources]
        if len(source_names) != len(set(source_names)):
            raise ValueError("duplicate kanban source names")
        section_names = [s.name for s in self.sections]
        if len(section_names) != len(set(section_names)):
            raise ValueError("duplicate kanban section names")
        appflowy_sections = [s.appflowy_section for s in self.sections]
        if len(appflowy_sections) != len(set(appflowy_sections)):
            raise ValueError("duplicate appflowy_section values")
        for s in self.sections:
            if not s.ready_statuses:
                raise ValueError(f"kanban section '{s.name}' needs at least one ready_status")
            if s.max_auto_risk in (RiskTier.L3, RiskTier.L4):
                raise ValueError(
                    f"kanban section '{s.name}' max_auto_risk cannot exceed L2; "
                    "external writes and dangerous work stay human-gated"
                )
            if s.target_kind == "learning" and s.default_risk not in (RiskTier.L0, RiskTier.L1):
                raise ValueError("learning intake must default to L0/L1; code changes belong in repo sections")
        return self


# ---- tools.yaml ------------------------------------------------------------
# Explicit tool permissions the judges can cite. One tier owns each action.
# The same L3/L4 discipline as gates.yaml: dangerous actions are manual-only,
# never auto-allowlisted. Mirage stays read-only and Phase-4 by contract.
class ToolPolicy(Strict):
    default_mode: str = "read_only"               # read_only | read_write
    allowed_l2: list[str] = []                    # local, auto after checks
    allowed_l3_actions: list[str] = []            # external write, needs approval
    denied_actions: list[str] = []                # never, regardless of tier
    manual_only: list[str] = []                   # L4: human runs it, never the agent
    phase: str | None = None                      # e.g. optional_phase_4
    denied_mounts: list[str] = []                 # for filesystem-style tools


class ToolsConfig(Strict):
    schema_version: str
    tools: dict[str, ToolPolicy]

    @model_validator(mode="after")
    def _checks(self):
        # a few actions must NEVER be allowlisted at L2/L3 no matter what a tool says
        forbidden_anywhere = {"merge", "force_push", "deploy", "publish",
                              "administer_secrets", "change_repo_settings",
                              "change_branch_protection", "bypass_required_checks"}
        for name, t in self.tools.items():
            auto = set(t.allowed_l2) | set(t.allowed_l3_actions)
            leaked = auto & forbidden_anywhere
            if leaked:
                raise ValueError(f"tool '{name}' auto-allows forbidden action(s) {sorted(leaked)} "
                                 "— these are L4 manual-only")
            # if a tool is named mirage, it must stay read-only (watch-list discipline)
            if name == "mirage" and t.default_mode != "read_only":
                raise ValueError("mirage must remain read_only until it matures past v0.0.1")
        return self


# ---- evals.yaml ------------------------------------------------------------
# Regression suite for the command center itself. Becomes the model-promotion
# gate: a new model/prompt/judge must pass these before it's trusted. Each case
# pins expected risk tier and which stages must / must not run.
class EvalCase(Strict):
    name: str
    input: str
    expected_risk: RiskTier
    expected_stages: list[str] = []
    forbidden_stages: list[str] = []
    expected_blocking_judges: list[str] = []
    expected_auto_allowed: bool | None = None


class EvalsConfig(Strict):
    schema_version: str
    cases: list[EvalCase]

    @model_validator(mode="after")
    def _checks(self):
        names = [c.name for c in self.cases]
        if len(names) != len(set(names)):
            raise ValueError("duplicate eval case names")
        for c in self.cases:
            # L4 cases must assert auto is NOT allowed — the whole point of testing them
            if c.expected_risk == RiskTier.L4 and c.expected_auto_allowed is not False:
                raise ValueError(f"L4 eval '{c.name}' must set expected_auto_allowed: false")
            # a stage can't be both expected and forbidden
            overlap = set(c.expected_stages) & set(c.forbidden_stages)
            if overlap:
                raise ValueError(f"eval '{c.name}' lists stage(s) {sorted(overlap)} as both expected and forbidden")
        return self


# ---- ui.yaml ---------------------------------------------------------------
# Human UI surfaces (Hermes WebUI + dashboards). The WebUI is a CONVENIENCE layer,
# never the policy layer: external writes still flow through the Ledger/gates, and
# the contract forbids exposing it publicly without a password. Phase 4 optional.
class WebUIConfig(Strict):
    enabled: bool = False
    host: str = "127.0.0.1"                        # loopback; reach over Tailscale
    port: int = Field(default=8787, ge=1, le=65535)
    password_required: bool = True
    container_mode: str = "single"                # single | two | three
    workspace_mount: str = "/workspace"
    external_write_policy: str = "governed_by_ledger"   # never "webui_direct"
    shell_approval_policy: str = "human_only_for_dangerous"

    @model_validator(mode="after")
    def _checks(self):
        # if it's bound to anything other than loopback, a password is mandatory
        if self.host not in ("127.0.0.1", "::1") and not self.password_required:
            raise ValueError("WebUI exposed beyond loopback must set password_required: true")
        # the WebUI can never be declared the write-authority — that stays with the Ledger
        if self.external_write_policy != "governed_by_ledger":
            raise ValueError("WebUI external_write_policy must be 'governed_by_ledger'")
        # two-container has the #681 tool-location limitation; flag the safe modes
        if self.container_mode not in ("single", "two", "three"):
            raise ValueError("container_mode must be single | two | three")
        return self


class UIConfig(Strict):
    schema_version: str
    hermes_webui: WebUIConfig = WebUIConfig()


# ---- standards.yaml ---------------------------------------------------------
# The standing engineering values, written ONCE, injected EVERYWHERE: rendered
# into CLAUDE.md (Claude Code) and AGENTS.md (Codex) on repo-install, and read
# by the Judge Gate for judge prompts. You never re-type "no defensive coding"
# again — the executors and judges carry it on every mission automatically.
class StandardsProfile(Strict):
    name: str                                     # referenced by targets.yaml standards_profile
    principles: list[str]                         # the standing rules for this kind of repo
    blocked_patterns: list[str] = []              # what the defensive-coding judge cites
    allowed_patterns: list[str] = []              # explicitly legitimate (boundary validation etc.)


class SkillUpdatePolicy(Strict):
    """Skills (Hermes skills, Claude Code skills, judge prompts) may be UPDATED
    automatically only as gated missions: the system proposes (often from RCA
    prevention output), the change is an L2 worktree edit through the normal
    judges, and anything external needs approval. Self-rewriting outside the
    pipeline is unrepresentable."""
    auto_propose: bool = True                     # post-RCA prevention may draft skill edits
    max_auto_risk: RiskTier = RiskTier.L2         # contract caps this at L2


class StandardsConfig(Strict):
    schema_version: str
    core_principles: list[str]                    # apply to every profile
    profiles: list[StandardsProfile]
    skill_updates: SkillUpdatePolicy = SkillUpdatePolicy()

    @model_validator(mode="after")
    def _checks(self):
        if not self.core_principles:
            raise ValueError("core_principles cannot be empty — they are the point of this file")
        names = [p.name for p in self.profiles]
        if len(names) != len(set(names)):
            raise ValueError("duplicate profile names")
        for p in self.profiles:
            if not p.principles:
                raise ValueError(f"profile '{p.name}' has no principles")
        if self.skill_updates.max_auto_risk in (RiskTier.L3, RiskTier.L4):
            raise ValueError("skill_updates.max_auto_risk caps at L2 — skill changes go through "
                             "the gated pipeline like any other edit")
        return self


# ---- channels.yaml ---------------------------------------------------------
# Chat transports (Discord, Slack, Telegram, WhatsApp, ...). Each is ONE MORE
# SURFACE, not a new authority: every channel routes through LiteLLM to the same
# growthos action layer the other surfaces use, and none can approve mission
# cards. Secrets never live here — tokens/allowlists are read from .env by env
# name; this file only declares which transports are on and which model they speak.
class ChannelSpec(Strict):
    name: str                                     # unique label, e.g. "discord-main"
    transport: Literal["discord", "slack", "telegram", "whatsapp"]
    enabled: bool = True
    model: str                                    # a models.yaml role alias (e.g. "triage")
    max_history: int = Field(default=12, ge=1, le=200)
    max_rounds: int = Field(default=6, ge=1, le=20)
    description: str | None = None


class ChannelsConfig(Strict):
    schema_version: str
    surface_label: str = "Growth OS gateway"      # shown in the per-channel system prompt
    channels: list[ChannelSpec] = []

    @model_validator(mode="after")
    def _checks(self):
        names = [c.name for c in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("duplicate channel names")
        # one transport may appear more than once (e.g. two Discord bots), but the
        # name must disambiguate them — enforced above. Nothing else to gate here:
        # the model alias is cross-checked against models.yaml in check_cross_refs.
        return self


# ---- ledger wire types (runtime, not config; used by services + dry-run) ----
class MissionOpen(Strict):
    repo: str
    requested_action: str
    requester: str
    risk_tier: RiskTier | None = None
    branch: str | None = None


class JudgeVerdict(Strict):
    mission_id: str
    stage: str
    judge_name: str
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    blocking_reasons: list[str] = []
    defensive_bloat_detected: bool = False
    scope_creep_detected: bool = False
