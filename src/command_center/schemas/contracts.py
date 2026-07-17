"""
The config contracts. One file — these are small and related, so splitting them
into ten modules would be ceremony, not clarity. Each top-level class maps to one
configs/*.yaml file.
"""
from __future__ import annotations
import re
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
    # Lifecycle status. `active` candidates are routed (rendered into the LiteLLM
    # model_list). `scout` candidates are tracked here as a watchlist — under
    # evaluation, NOT yet routed — so a proposed model has one home alongside the
    # roster instead of living only in the scout feed. Promotion (scout -> active)
    # stays human-only: `cc model-promote --role R --candidate ALIAS --approver YOU
    # --apply`. Default `active` keeps every existing entry valid unchanged.
    status: Literal["active", "scout"] = "active"
    monthly_budget_usd: float | None = Field(default=None, ge=0)
    canary_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    vram_gb: int | None = Field(default=None, ge=1)
    license: str | None = None
    notes: str | None = None
    # Name of the env var holding this candidate's Ollama endpoint. Lets a
    # second GPU (e.g. the 5080 on the tailnet) serve a role's lower-priority
    # candidate. Defaults to OLLAMA_API_BASE (the primary 4090) so existing
    # single-endpoint configs are unchanged. Still local-only — it names an
    # Ollama base, never a cloud provider; provider routes stay forbidden.
    api_base_env: str = "OLLAMA_API_BASE"


# The sources the scout knows how to fetch. Kept here (next to ScoutSpec) so a typo'd
# source in configs/models.yaml is rejected at `make validate` instead of only surfacing
# as a per-source runtime error. model_scout.py imports this as the single source of truth.
KNOWN_SCOUT_SOURCES = frozenset({
    "aider-polyglot",       # public coding leaderboard (keyless discovery signal)
    "local-ollama-tags",    # installed models (guaranteed-runnable provenance)
    "curated-openweight",   # strict, installed-and-digest-joined promotion-grade source
    "artificial-analysis",  # optional API tiebreaker (skipped without AA_API_KEY)
    "model-watchlist",      # un-pulled frontier / pull-to-verify models (track-as-context)
})


class ScoutSpec(Strict):
    """The model scout: watches sources (leaderboards, model cards, provider
    docs) and PROPOSES updates as PRs against this file. It can never promote.
    Leaderboards are a discovery signal, not an authority — promotion requires
    the canary + `make evals` regression gate + a human tap, because public
    leaderboards are gameable and a board-topping model can still be worse for
    THIS system's judges and diffs."""
    cadence: str = "monthly"                      # how often the scout mission runs
    sources: list[str] = []                       # names from KNOWN_SCOUT_SOURCES
    propose_only: bool = True                     # contract refuses False — no auto-promotion
    max_candidates_per_run: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def _checks(self):
        unknown = [s for s in self.sources if s not in KNOWN_SCOUT_SOURCES]
        if unknown:
            raise ValueError(
                f"scout.sources has unknown source(s) {unknown}; "
                f"known sources are {sorted(KNOWN_SCOUT_SOURCES)}"
            )
        if len(self.sources) != len(set(self.sources)):
            raise ValueError("scout.sources contains duplicate sources")
        return self


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
            # a role must keep at least one active (routed) candidate — an
            # all-scout role would render an empty route and silently break.
            if not any(c.status == "active" for c in cands):
                raise ValueError(
                    f"role '{role}' has no active candidate (all scout); routing would be empty"
                )
            # scout candidates are not routed, so they cannot also be a canary —
            # promote to active first, then canary.
            for c in cands:
                if c.status == "scout" and c.canary_weight > 0:
                    raise ValueError(
                        f"role '{role}' candidate '{c.alias}' is scout but has canary_weight>0; "
                        "scout models are not routed — promote to active before canarying"
                    )
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


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CuratedScoutIdentity(Strict):
    model_family: str
    release_id: str
    source_model_id: str
    source_model_url: str
    source_model_payload_sha256: str
    ollama_tag: str
    ollama_digest: str
    parameter_size: str
    quantization: str
    license: str
    context_length: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _checks(self):
        fields = (
            "model_family", "release_id", "source_model_id", "source_model_url",
            "source_model_payload_sha256", "ollama_tag", "ollama_digest",
            "parameter_size", "quantization", "license",
        )
        for field in fields:
            if not getattr(self, field):
                raise ValueError(f"curated scout identity missing {field}")
        if not _SHA256_RE.match(self.source_model_payload_sha256):
            raise ValueError("source_model_payload_sha256 must be a lowercase sha256 hex digest")
        if not _SHA256_RE.match(self.ollama_digest):
            raise ValueError("ollama_digest must be a lowercase sha256 hex digest")
        return self


class CuratedScoutBenchmark(Strict):
    name: str
    version: str
    metric: str
    score: float
    score_definition: str
    evaluation_date: str
    candidate_roles: list[str]
    source_url: str
    retrieval_timestamp: str
    source_payload_sha256: str

    @model_validator(mode="after")
    def _checks(self):
        fields = (
            "name", "version", "metric", "score_definition", "evaluation_date",
            "source_url", "retrieval_timestamp", "source_payload_sha256",
        )
        for field in fields:
            if not getattr(self, field):
                raise ValueError(f"curated scout benchmark missing {field}")
        if not self.candidate_roles:
            raise ValueError("curated scout benchmark must declare candidate_roles")
        if len(self.candidate_roles) != len(set(self.candidate_roles)):
            raise ValueError("curated scout benchmark candidate_roles contains duplicates")
        if not _SHA256_RE.match(self.source_payload_sha256):
            raise ValueError("source_payload_sha256 must be a lowercase sha256 hex digest")
        return self


class CuratedScoutRecord(Strict):
    record_id: str
    identity: CuratedScoutIdentity
    open_weight_evidence: str
    benchmark: CuratedScoutBenchmark

    @model_validator(mode="after")
    def _checks(self):
        if not self.record_id:
            raise ValueError("curated scout record_id is required")
        if not self.open_weight_evidence:
            raise ValueError("curated scout record must include open_weight_evidence")
        return self


class CuratedModelScoutConfig(Strict):
    schema_version: str
    records: list[CuratedScoutRecord]

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.model-scout-curated-openweight.v1":
            raise ValueError(
                "schema_version must be command-center.model-scout-curated-openweight.v1")
        if not self.records:
            raise ValueError("curated model scout config must define at least one record")
        ids = [record.record_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("curated model scout config contains duplicate record_id values")
        return self


# ---- model-scout-watchlist.yaml --------------------------------------------
# A LOWER-trust tier than curated-openweight: open-weight models we are TRACKING
# but have NOT installed (and in the frontier case never will, because they do not
# fit this hardware). It carries provenance + public-benchmark CONTEXT and an honest
# weights-only fit verdict — never promotion-grade evidence, never a fabricated FITS.
# This is what lets GLM-5.2 / Kimi K2 be "checked on" by name without a download.
class WatchlistBenchmark(Strict):
    """Public capability CONTEXT for a watchlist model. Explicitly NOT promotion
    evidence — a high public score never substitutes for the repo's own local A/B."""
    name: str
    metric: str
    score: float
    score_definition: str
    source_url: str
    evaluation_date: str

    @model_validator(mode="after")
    def _checks(self):
        for f in ("name", "metric", "score_definition", "source_url", "evaluation_date"):
            if not getattr(self, f):
                raise ValueError(f"watchlist benchmark missing {f}")
        return self


class WatchlistLocalArtifact(Strict):
    """A concrete downloadable quantized artifact + its VERIFIED on-disk size, when one is
    published (e.g. an Unsloth dynamic-GGUF). When present, the size is authoritative for the
    fit verdict (more honest than a params×bpw estimate) — e.g. GLM-5.2's ~238 GB dynamic 2-bit
    is a hard NO on a 24/16 GB box but plausible on a 256 GB-class unified-memory machine."""
    type: str                                      # gguf | safetensors | ...
    provider: str                                  # who published the quant (unsloth, vendor, ...)
    smallest_verified_size_gb: float = Field(gt=0)  # smallest verified runnable artifact size
    quant: str                                     # e.g. dynamic-2bit, Q2_K_XL

    @model_validator(mode="after")
    def _checks(self):
        for f in ("type", "provider", "quant"):
            if not getattr(self, f):
                raise ValueError(f"watchlist local_artifact missing {f}")
        return self


class ModelWatchlistRecord(Strict):
    record_id: str
    # frontier_watch: too large to run here — track-as-context, NEVER drafts a local benchmark.
    # pull_to_verify: plausibly fits — may draft a propose-only 'ollama pull' candidate.
    tier: Literal["frontier_watch", "pull_to_verify"]
    model_family: str
    release_id: str
    source_model_url: str                          # HF/vendor model card (provenance root)
    parameter_count_b: float = Field(gt=0)         # TOTAL params — drives the memory footprint
    reference_quant: str                           # quant used for the weights-only fit bound
    license: str
    open_weight_evidence: str
    source_url: str
    retrieval_timestamp: str
    active_param_count_b: float | None = Field(default=None, gt=0)  # MoE active (speed, not size)
    is_moe: bool = False
    context_length: int | None = Field(default=None, ge=1)
    ollama_tag: str | None = None                  # e.g. 'glm-4.7-flash:...' or cloud-only tag
    ollama_local: bool = False                     # is the tag actually downloadable locally?
    candidate_roles: list[str] = []                # required for pull_to_verify (which role to test)
    local_artifact: WatchlistLocalArtifact | None = None   # verified quant size, when published
    benchmark: WatchlistBenchmark | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _checks(self):
        for f in ("record_id", "model_family", "release_id", "source_model_url",
                  "reference_quant", "license", "open_weight_evidence", "source_url",
                  "retrieval_timestamp"):
            if not getattr(self, f):
                raise ValueError(f"watchlist record missing {f}")
        if self.candidate_roles and len(self.candidate_roles) != len(set(self.candidate_roles)):
            raise ValueError(f"watchlist record {self.record_id!r} has duplicate candidate_roles")
        if self.tier == "pull_to_verify" and not self.candidate_roles:
            raise ValueError(
                f"watchlist record {self.record_id!r} is pull_to_verify and must declare "
                "candidate_roles (which role a pulled candidate would be benchmarked for)")
        # a cloud-only / non-local tag must not claim to be locally downloadable
        if self.ollama_local and not self.ollama_tag:
            raise ValueError(
                f"watchlist record {self.record_id!r} sets ollama_local but has no ollama_tag")
        return self


class ModelWatchlistConfig(Strict):
    schema_version: str
    records: list[ModelWatchlistRecord]

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.model-scout-watchlist.v1":
            raise ValueError(
                "schema_version must be command-center.model-scout-watchlist.v1")
        if not self.records:
            raise ValueError("model watchlist config must define at least one record")
        ids = [record.record_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("model watchlist config contains duplicate record_id values")
        return self


# ---- frontier-router-providers.yaml / frontier-router-budgets.yaml ----------
# A SEPARATE lane from the local-only LiteLLM gateway: paid frontier APIs as a budgeted,
# redacted, token-measured BACKUP/escalation path for open-weight models too large to run
# locally (GLM-5.2, Kimi K2). It NEVER becomes a local incumbent and NEVER routes the local
# lane. The local-only contract + check_forbidden_providers stay intact: these files are pure
# metadata, off by default, and naming a provider key here (as the env var to read) is NOT the
# same as putting the key in .env — actually enabling the lane is a deliberate, separate
# operator decision (set the key AND reconcile the forbidden-providers gate). The safety
# properties below are CONTRACT-enforced, not merely asserted.
class FrontierRouterProvider(Strict):
    base_url: str
    api_style: Literal["openai_compatible", "anthropic_compatible"]
    secret_env: str                                # env var NAME to read at runtime (not a key)
    # Only legal value: the lane cannot self-enable. Turning it on is a budgeted operator step.
    default_policy: Literal["disabled_until_budgeted"] = "disabled_until_budgeted"
    data_policy_required: bool = True

    @model_validator(mode="after")
    def _checks(self):
        for f in ("base_url", "secret_env"):
            if not getattr(self, f):
                raise ValueError(f"frontier router provider missing {f}")
        if not self.data_policy_required:
            raise ValueError("frontier router provider must require a data policy")
        return self


class FrontierRouterCandidate(Strict):
    provider: str
    model: str
    input_usd_per_mtok: float = Field(ge=0)
    output_usd_per_mtok: float = Field(ge=0)
    context_tokens: int = Field(ge=1)
    cached_input_usd_per_mtok: float | None = Field(default=None, ge=0)
    # Price provenance — public prices drift, so each is dated and the freshness audit flags
    # staleness rather than trusting a frozen number (router_price_audit.py).
    price_source: str | None = None
    price_observed_at: str | None = None           # ISO date, e.g. "2026-06-20"
    price_is_drift_prone: bool = True


class FrontierRouterPriceFreshness(Strict):
    """Policy for the price-freshness audit. auto_update is refused: prices are never silently
    overwritten — a stale price is surfaced for a human, not patched in."""
    max_age_days: int = Field(default=14, ge=1)
    stale_action: Literal["warn_in_scan", "fail"] = "warn_in_scan"
    auto_update: bool = False

    @model_validator(mode="after")
    def _checks(self):
        if self.auto_update:
            raise ValueError("price_freshness.auto_update must be false — never silently "
                             "overwrite provider prices")
        return self


class FrontierRouterModel(Strict):
    # Router-backed models stay frontier-watch for fit purposes — never a local lane.
    local_lane: Literal["frontier_watch"] = "frontier_watch"
    router_candidates: list[FrontierRouterCandidate]

    @model_validator(mode="after")
    def _checks(self):
        if not self.router_candidates:
            raise ValueError("frontier router model must list at least one router_candidate")
        return self


class FrontierRouterProvidersConfig(Strict):
    schema_version: str
    providers: dict[str, FrontierRouterProvider]
    models: dict[str, FrontierRouterModel]
    price_freshness: FrontierRouterPriceFreshness = Field(
        default_factory=FrontierRouterPriceFreshness)

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.frontier-router-providers.v1":
            raise ValueError(
                "schema_version must be command-center.frontier-router-providers.v1")
        if not self.providers:
            raise ValueError("frontier router config must define at least one provider")
        for model_id, spec in self.models.items():
            for cand in spec.router_candidates:
                if cand.provider not in self.providers:
                    raise ValueError(
                        f"frontier router model {model_id!r} candidate references unknown "
                        f"provider {cand.provider!r}")
        return self


class FrontierRouterBudgetPolicy(Strict):
    enabled: bool = False                           # OFF by default — fail closed
    monthly_cap_usd: float = Field(gt=0)
    per_run_cap_usd: float = Field(gt=0)
    per_request_cap_usd: float = Field(gt=0)
    require_redaction: bool = True                  # contract refuses False
    require_human_approval_for_live_repo_context: bool = True
    log_token_usage: bool = True
    log_cost_estimate: bool = True
    fail_on_missing_usage: bool = True              # no fabricated usage/cost

    @model_validator(mode="after")
    def _checks(self):
        if not self.require_redaction:
            raise ValueError("frontier router budget must require_redaction (no raw egress)")
        if self.per_request_cap_usd > self.per_run_cap_usd:
            raise ValueError("per_request_cap_usd must be <= per_run_cap_usd")
        if self.per_run_cap_usd > self.monthly_cap_usd:
            raise ValueError("per_run_cap_usd must be <= monthly_cap_usd")
        # Enabling the lane requires real usage accounting + human approval for repo context.
        if self.enabled and not (self.fail_on_missing_usage
                                 and self.require_human_approval_for_live_repo_context):
            raise ValueError(
                "an ENABLED frontier router budget must keep fail_on_missing_usage and "
                "require_human_approval_for_live_repo_context true")
        return self


class FrontierRouterBudgetsConfig(Strict):
    schema_version: str
    default: FrontierRouterBudgetPolicy
    allowed_task_classes: list[str]
    blocked_payloads: list[str]

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.frontier-router-budgets.v1":
            raise ValueError(
                "schema_version must be command-center.frontier-router-budgets.v1")
        if not self.allowed_task_classes:
            raise ValueError("frontier router budgets must list allowed_task_classes")
        if "secrets" not in self.blocked_payloads:
            raise ValueError(
                "frontier router budgets must block the 'secrets' payload class at minimum")
        return self


# ---- usage-monitoring.yaml -------------------------------------------------
# Thresholds/polling/routing/alerts for the unified runtime Usage/Limits layer
# (src/command_center/usage/). Distinct from the frontier/agent-session BUDGET
# configs: those are internal spend caps; this governs how PROVIDER-reported
# usage/limits/availability are polled, alerted on, and used for routing.
class UsageThresholds(Strict):
    warning_percent: float = Field(default=75.0, ge=0, le=100)
    critical_percent: float = Field(default=90.0, ge=0, le=100)

    @model_validator(mode="after")
    def _checks(self):
        if self.critical_percent < self.warning_percent:
            raise ValueError("critical_percent must be >= warning_percent")
        return self


class UsagePolling(Strict):
    active_session_seconds: int = Field(default=30, gt=0)
    idle_seconds: int = Field(default=300, gt=0)


class UsageRouting(Strict):
    block_when_exhausted: bool = True
    allow_silent_fallback: bool = False
    reserve_capacity_for_high_risk_missions: bool = True

    @model_validator(mode="after")
    def _checks(self):
        # Structural enforcement of the "no silent fallback" invariant (KPI:
        # silent fallbacks = 0): the toggle exists for config symmetry but the
        # contract refuses True, same fail-closed discipline as the frontier
        # budget's require_redaction. A router must surface every rejection.
        if self.allow_silent_fallback:
            raise ValueError(
                "allow_silent_fallback must be false — every executor rejection "
                "must be surfaced, never a silent substitution")
        return self


class UsageAlertChannels(Strict):
    cockpit: bool = True
    chat_notification: bool = True
    ledger: bool = True
    email_digest: bool = True


class UsageRetention(Strict):
    # Detailed per-request samples are the biggest table; keep them a bounded
    # window. Aggregates/alerts/routing decisions are cheap + evidential, so
    # they're kept far longer / indefinitely — the evidence behind a routing
    # decision is NEVER pruned.
    request_sample_days: int = Field(default=90, gt=0)
    keep_aggregates_days: int = Field(default=730, gt=0)
    keep_alerts_and_routing_indefinitely: bool = True

    @model_validator(mode="after")
    def _checks(self):
        if self.keep_aggregates_days < self.request_sample_days:
            raise ValueError(
                "keep_aggregates_days must be >= request_sample_days "
                "(aggregates outlive the detailed samples they summarize)")
        return self


class UsageMonitoringConfig(Strict):
    schema_version: str
    enabled: bool = True
    thresholds: UsageThresholds = Field(default_factory=UsageThresholds)
    polling: UsagePolling = Field(default_factory=UsagePolling)
    routing: UsageRouting = Field(default_factory=UsageRouting)
    alerts: UsageAlertChannels = Field(default_factory=UsageAlertChannels)
    retention: UsageRetention = Field(default_factory=UsageRetention)

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.usage-monitoring.v1":
            raise ValueError(
                "schema_version must be command-center.usage-monitoring.v1")
        return self


# ---- local-frontier-providers.yaml ------------------------------------------
# A THIRD lane, distinct from both the local-only LiteLLM/Ollama gateway and the paid
# frontier-router backup lane: an experimental LOOPBACK-only engine (colibrì, or any future
# disk-streamed/local-server engine) too large to fit VRAM but running entirely on this
# machine — no API key, no $ cost, no cloud egress. It is NOT a LiteLLM role (ModelRegistry
# stays ollama-only) and NOT a frontier-router candidate (no provider pricing, no budget caps
# apply — there is nothing to bill). Like frontier-router-providers.yaml, this file NAMES an
# env var for the base URL; it holds no value and executes nothing. The actual host the env
# var resolves to is validated at RUNTIME by check_forbidden_providers.check_local_frontier_providers()
# and by local_frontier_client — this contract can only assert the env var NAME is sane, not
# the resolved value. `enabled: false` by default; flipping it on is a deliberate operator
# decision after Phase 2's smoke test (see docs/MASTER.md "Local frontier lane").
class LocalFrontierCapabilities(Strict):
    text: bool = True
    streaming: bool = True
    tools: Literal[False] = False        # contract-refuses True: these engines reject tool schemas
    json_mode: Literal[False] = False    # contract-refuses True: engines reject non-text response_format
    vision: bool = False
    audio: bool = False


class LocalFrontierProvider(Strict):
    base_url_env: str                    # env var NAME holding the loopback/private base URL
    api_key_env: str | None = None       # optional local bearer token; never a FORBIDDEN_KEYS concern
    api_style: Literal["openai_compatible"] = "openai_compatible"

    @model_validator(mode="after")
    def _checks(self):
        if not self.base_url_env:
            raise ValueError("local frontier provider missing base_url_env")
        return self


class LocalFrontierThroughputEstimate(Strict):
    """Published, NOT measured-here, tokens/sec range. `source` must say so — this is
    context for the operator until a real generated/local-frontier-benchmark-report.json
    exists (see local_frontier_client._last_benchmark_summary), never a substitute for one."""
    low: float = Field(gt=0)
    high: float = Field(gt=0)
    source: str

    @model_validator(mode="after")
    def _checks(self):
        if self.high < self.low:
            raise ValueError("expected_tokens_per_second.high must be >= low")
        if not self.source:
            raise ValueError("expected_tokens_per_second needs a source (this is unverified until measured)")
        return self


class LocalFrontierModel(Strict):
    provider: str
    context_tokens: int = Field(ge=1)
    capabilities: LocalFrontierCapabilities = Field(default_factory=LocalFrontierCapabilities)
    disk_footprint_gb: float = Field(gt=0)
    expected_tokens_per_second: LocalFrontierThroughputEstimate
    kv_slots: int = Field(default=2, ge=1, le=16)
    max_queue: int = Field(default=2, ge=1)
    queue_timeout_seconds: int = Field(default=900, ge=1)
    # Sent as `max_tokens` on every request — REQUIRED, not optional, unlike the paid frontier
    # lane (which is fast enough that an uncapped reply is merely more expensive). At colibrì's
    # self-reported 0.05-1.06 tok/s, an uncapped reply can run past queue_timeout_seconds itself
    # (observed live 2026-07-11: a real cockpit turn with no max_tokens set blew past a 900s
    # queue_timeout_seconds and surfaced as an opaque "could not reach" transport error, not a
    # clear timeout). Default kept low on purpose — see docs/MASTER.md "Local frontier lane".
    max_output_tokens: int = Field(default=200, ge=1)


class LocalFrontierProvidersConfig(Strict):
    schema_version: str
    enabled: bool = False                # OFF by default — fail closed, same as the router lane
    providers: dict[str, LocalFrontierProvider]
    models: dict[str, LocalFrontierModel]

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.local-frontier-providers.v1":
            raise ValueError(
                "schema_version must be command-center.local-frontier-providers.v1")
        if not self.providers:
            raise ValueError("local frontier config must define at least one provider")
        for model_id, spec in self.models.items():
            if spec.provider not in self.providers:
                raise ValueError(
                    f"local frontier model {model_id!r} references unknown provider {spec.provider!r}")
        return self


# ---- framework-evals.yaml --------------------------------------------------
# External code-eval frameworks (EvalPlus, BigCodeBench) as SUPPORTING evidence only — the
# `trust` Literal makes "this can promote a model" unrepresentable. They run against the local
# Ollama OpenAI-compatible endpoint, are off by default, and are bounded by a sample budget.
class FrameworkEvalSpec(Strict):
    enabled: bool = False
    cli_command: str                               # binary/module checked for availability + run
    backend: Literal["openai_compatible", "ollama"] = "openai_compatible"
    base_url_env: str                              # env var naming the local endpoint
    sample_budget: int = Field(ge=1)               # bounded subset (full runs are minutes-hours)
    informs_role: str                              # which local role this is evidence FOR
    trust: Literal["supporting_evidence_only"] = "supporting_evidence_only"
    datasets: list[str] = []                       # e.g. EvalPlus: humaneval_plus, mbpp_plus
    subset: str | None = None                      # e.g. BigCodeBench: full | hard

    @model_validator(mode="after")
    def _checks(self):
        for f in ("cli_command", "base_url_env", "informs_role"):
            if not getattr(self, f):
                raise ValueError(f"framework eval spec missing {f}")
        return self


class FrameworkEvalsConfig(Strict):
    schema_version: str
    frameworks: dict[str, FrameworkEvalSpec]

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.framework-evals.v1":
            raise ValueError("schema_version must be command-center.framework-evals.v1")
        if not self.frameworks:
            raise ValueError("framework-evals config must define at least one framework")
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
    default_route_alias: str
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
    gpu_vram_gb: int | None = Field(default=None, ge=1)   # total card VRAM; the model-fit budget
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


class SelfImprovementScan(Strict):
    name: str
    target: str
    schedule: str
    owner: str
    pillars: list[Literal[
        "automation",
        "structure",
        "updated_metrics",
        "code_quality",
        "rules_standards",
        "data_handling",
        "full_idea_updates",
        "reliability_observability",
        "cost_finops",
    ]]
    sources: list[str]
    evidence: list[str]
    output_artifacts: list[Literal["backlog_cards", "decision_report"]]
    trigger_surfaces: list[Literal["airflow", "kanban", "discord", "chat", "mcp"]] = ["airflow"]
    max_daily_cards: int = Field(default=10, ge=1, le=25)
    report_top_n: int = Field(default=15, ge=1, le=50)
    min_evidence_occurrences: int = Field(default=3, ge=1)
    cooldown_hours: int = Field(default=168, ge=24)
    write_scopes: list[Literal["backlog_cards", "report_artifact"]] = [
        "backlog_cards",
        "report_artifact",
    ]
    # The scan itself is observer-only. This cap controls the strongest generated
    # experiment contract it may draft into Proposed state.
    max_generated_experiment_risk: RiskTier = RiskTier.L2
    observer_only: bool = True
    uses_existing_approval_wall: bool = True
    independent_verifier_required: bool = True
    forbidden_actions: list[str] = Field(default_factory=lambda: [
        "approve",
        "promote",
        "canary",
        "merge",
        "deploy",
        "rotate_secrets",
        "execute_experiment",
        "mark_verified",
    ])


class ProactiveConfig(Strict):
    schema_version: str
    runtime_checks: list[ProactiveCheck] = []     # DAG/data freshness, quality, drift
    repo_stewardship: list[ProactiveCheck] = []   # structure, tests, docs, defensive-coding debt
    self_improvement_scans: list[SelfImprovementScan] = []  # observer-only proposal/report loops

    @model_validator(mode="after")
    def _checks(self):
        all_checks = self.runtime_checks + self.repo_stewardship
        names = [c.name for c in all_checks]
        scan_names = [s.name for s in self.self_improvement_scans]
        if len(names + scan_names) != len(set(names + scan_names)):
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
        for s in self.self_improvement_scans:
            if not s.owner:
                raise ValueError(f"self-improvement scan '{s.name}' must declare an owner")
            if not s.schedule:
                raise ValueError(f"self-improvement scan '{s.name}' must declare a schedule")
            if not s.pillars:
                raise ValueError(f"self-improvement scan '{s.name}' must declare at least one pillar")
            if not s.sources:
                raise ValueError(f"self-improvement scan '{s.name}' must declare at least one source")
            if not s.evidence:
                raise ValueError(f"self-improvement scan '{s.name}' must collect evidence")
            if set(s.output_artifacts) != {"backlog_cards", "decision_report"}:
                raise ValueError(
                    f"self-improvement scan '{s.name}' may write only backlog_cards "
                    "and decision_report artifacts"
                )
            if set(s.write_scopes) != {"backlog_cards", "report_artifact"}:
                raise ValueError(
                    f"self-improvement scan '{s.name}' write_scopes must stay limited to "
                    "backlog_cards and report_artifact"
                )
            if s.max_generated_experiment_risk in (RiskTier.L3, RiskTier.L4):
                raise ValueError(
                    f"self-improvement scan '{s.name}' cannot generate L3/L4 experiments"
                )
            if not s.observer_only:
                raise ValueError(f"self-improvement scan '{s.name}' must stay observer_only")
            if not s.uses_existing_approval_wall:
                raise ValueError(
                    f"self-improvement scan '{s.name}' must use the existing approval wall"
                )
            if not s.independent_verifier_required:
                raise ValueError(
                    f"self-improvement scan '{s.name}' must require independent verification"
                )
            required_forbidden = {
                "approve",
                "promote",
                "canary",
                "merge",
                "deploy",
                "rotate_secrets",
                "execute_experiment",
                "mark_verified",
            }
            missing = required_forbidden - set(s.forbidden_actions)
            if missing:
                raise ValueError(
                    f"self-improvement scan '{s.name}' missing forbidden action(s): "
                    f"{sorted(missing)}"
                )
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
    kind: Literal["command_center_ui"] = "command_center_ui"
    enabled: bool = True
    board_id: str = "llm_station_command_center"
    board_store_dir: str = "generated/boards"
    event_log_path: str = "generated/kanban-events.jsonl"

class KanbanSection(Strict):
    name: str
    board_section: str
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
        board_sections = [s.board_section for s in self.sections]
        if len(board_sections) != len(set(board_sections)):
            raise ValueError("duplicate board_section values")
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


# ---- kanban_boards.yaml ----------------------------------------------------
# A provider-agnostic registry of kanban boards. One board_id maps a surface
# (the internal Command Center UI) to the repos it drives, the
# canonical status workflow, the fields a mission card must carry, and the agent
# verb contract. Both providers MUST expose the same canonical verbs/statuses so
# the action layer + approval wall behave identically regardless of surface.
_KANBAN_CANONICAL_STATUSES = frozenset({
    "backlog", "ready", "in_progress", "done", "blocked", "rejected", "awaiting_approval",
})
# Verbs the agent may be granted (none of these approve, merge, deploy, or delete).
_KANBAN_GRANTABLE_VERBS = frozenset({
    "add_mission_card", "stage_card", "start_todo", "finish_todo", "block_card", "reject_card",
})
# Verbs that must NEVER be available to the model/action layer on any board —
# they are the human approval/merge wall and destructive operations.
_KANBAN_WALL_VERBS = frozenset({
    "approve_card", "merge", "deploy", "delete_card", "delete_board",
})
# The recognised per-card mission-dependency fields (Cline-style dependency chains).
# `blocked_by`: mission ids that must finish before this card may start. `unblocks`:
# the inverse edge, for surfacing. A board opts in via KanbanBoardSpec.dependency_fields;
# they are OPTIONAL per card (never in required_fields) and carry no approval authority.
_KANBAN_CARD_DEPENDENCY_FIELDS = frozenset({"blocked_by", "unblocks"})


class KanbanBoardSpec(Strict):
    board_id: str
    provider: Literal["command_center_ui"]
    workspace_ref: str
    board_ref: str
    # execution_scope decides whether the board drives a repository. `life` boards
    # (Health, Books, Personal Tasks…) run NO repository work — outputs live in the
    # Ledger/board store — so they legitimately carry an empty repo_ids. `repository`
    # and `hybrid` boards drive repo work and must name ≥1 repo. Default preserves
    # every existing board (which never set this) as a repository board.
    execution_scope: Literal["life", "repository", "hybrid"] = "repository"
    repo_ids: list[str]
    status_mapping: dict[str, str]
    required_fields: list[str]
    allowed_agent_verbs: list[str]
    forbidden_agent_verbs: list[str]
    blockers: list[str] = Field(default_factory=list)
    # Optional per-card mission-dependency fields this board supports (blocked_by / unblocks).
    # Empty = the board has no dependency chains. These are optional per card and must NOT
    # be listed in required_fields (a card without dependencies is valid).
    dependency_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if not _REPO_ID_RE.match(self.board_id):
            raise ValueError(f"kanban board board_id {self.board_id!r} must be a stable id")
        if not self.workspace_ref:
            raise ValueError(f"kanban board {self.board_id!r} needs a workspace_ref")
        if not self.board_ref:
            raise ValueError(f"kanban board {self.board_id!r} needs a board_ref")
        if self.execution_scope != "life" and not self.repo_ids:
            raise ValueError(
                f"kanban board {self.board_id!r} ({self.execution_scope}) must list at "
                "least one repo_id; only execution_scope='life' boards may be repo-less")
        if len(self.repo_ids) != len(set(self.repo_ids)):
            raise ValueError(f"kanban board {self.board_id!r} has duplicate repo_ids")
        # status_mapping must cover exactly the canonical workflow statuses.
        keys = set(self.status_mapping)
        missing = _KANBAN_CANONICAL_STATUSES - keys
        extra = keys - _KANBAN_CANONICAL_STATUSES
        if missing:
            raise ValueError(
                f"kanban board {self.board_id!r} status_mapping missing canonical "
                f"status(es): {sorted(missing)}"
            )
        if extra:
            raise ValueError(
                f"kanban board {self.board_id!r} status_mapping has unknown status(es): "
                f"{sorted(extra)}"
            )
        if any(not label for label in self.status_mapping.values()):
            raise ValueError(f"kanban board {self.board_id!r} status_mapping has blank label(s)")
        if not self.required_fields:
            raise ValueError(f"kanban board {self.board_id!r} must declare required_fields")
        if len(self.required_fields) != len(set(self.required_fields)):
            raise ValueError(f"kanban board {self.board_id!r} has duplicate required_fields")
        # dependency_fields: recognised, de-duplicated, and OPTIONAL (never required) —
        # a mission with no dependencies is valid, so requiring the field would be wrong.
        dep = set(self.dependency_fields)
        if len(self.dependency_fields) != len(dep):
            raise ValueError(f"kanban board {self.board_id!r} has duplicate dependency_fields")
        unknown_dep = dep - _KANBAN_CARD_DEPENDENCY_FIELDS
        if unknown_dep:
            raise ValueError(
                f"kanban board {self.board_id!r} dependency_fields may only be "
                f"{sorted(_KANBAN_CARD_DEPENDENCY_FIELDS)}; got: {sorted(unknown_dep)}"
            )
        required_dep = dep & set(self.required_fields)
        if required_dep:
            raise ValueError(
                f"kanban board {self.board_id!r} dependency_fields {sorted(required_dep)} "
                "must stay optional; a card without dependencies is valid, so they cannot "
                "be in required_fields"
            )
        # verb contract: allowed/forbidden disjoint; wall verbs always forbidden;
        # allowed may only be grantable verbs (never the wall verbs).
        allowed = set(self.allowed_agent_verbs)
        forbidden = set(self.forbidden_agent_verbs)
        if len(self.allowed_agent_verbs) != len(allowed):
            raise ValueError(f"kanban board {self.board_id!r} has duplicate allowed_agent_verbs")
        if len(self.forbidden_agent_verbs) != len(forbidden):
            raise ValueError(f"kanban board {self.board_id!r} has duplicate forbidden_agent_verbs")
        overlap = allowed & forbidden
        if overlap:
            raise ValueError(
                f"kanban board {self.board_id!r} verb(s) both allowed and forbidden: "
                f"{sorted(overlap)}"
            )
        wall_missing = _KANBAN_WALL_VERBS - forbidden
        if wall_missing:
            raise ValueError(
                f"kanban board {self.board_id!r} must forbid wall verb(s): {sorted(wall_missing)}"
            )
        ungrantable = allowed - _KANBAN_GRANTABLE_VERBS
        if ungrantable:
            raise ValueError(
                f"kanban board {self.board_id!r} allowed_agent_verbs may only grant "
                f"{sorted(_KANBAN_GRANTABLE_VERBS)}; got disallowed: {sorted(ungrantable)}"
            )
        return self


class KanbanBoardsConfig(Strict):
    schema_version: str
    boards: list[KanbanBoardSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.kanban-boards.v1":
            raise ValueError("schema_version must be command-center.kanban-boards.v1")
        board_ids = [b.board_id for b in self.boards]
        if len(board_ids) != len(set(board_ids)):
            raise ValueError("duplicate kanban board_ids")
        return self


# ---- domain_surfaces.yaml ---------------------------------------------------
# Typed cockpit surfaces: each domain renders its objects with its own card
# grammar in agent_kanban_ui (jobs look like jobs, posts preview like posts).
# A domain BINDS to a data source — a registry board's internal card store, the
# Ledger's missions, or committed demo fixtures — and lists the governed verbs
# its cards may offer. The wall is the same wall as kanban boards: no domain may
# offer approve/merge/deploy/delete, and the validator enforces it structurally.
_DOMAIN_SOURCES = ("board_store", "ledger_missions", "fixtures")
_DOMAIN_CARD_COMPONENTS = frozenset({
    "job_application", "linkedin_post", "book", "paper", "repo", "dag",
    "machine_upkeep", "mission", "generic_task",
})
_DOMAIN_FIELD_KINDS = ("text", "badge", "score", "money", "url", "datetime",
                       "markdown", "list", "progress")


class DomainFieldSpec(Strict):
    name: str
    label: str
    kind: Literal["text", "badge", "score", "money", "url", "datetime",
                  "markdown", "list", "progress"] = "text"


class DomainEmptyState(Strict):
    title: str
    hint: str
    command: str | None = None   # the exact cc command that fills this surface


DomainIntakeValue = bool | int | float | str | list[str]


class DomainIntakeSpec(Strict):
    """Board-visible, producer-owned inputs for one domain surface.

    ``source`` on :class:`DomainSurfaceSpec` names where cards are stored. This
    contract separately names what produces them and the inputs that producer
    consumes. Producer ids are intentionally extensible; the two automated
    Growth OS producers receive additional exact validation because their
    parameters drive network queries on the next watcher cycle.
    """

    producer: str = "manual"
    mode: Literal["manual", "scheduled", "event", "projection", "external"] = "manual"
    summary: str = Field(
        default="Cards are added directly from this board.",
        min_length=1,
        max_length=500,
    )
    schedule: str = Field(default="on demand", min_length=1, max_length=120)
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    parameters: dict[str, DomainIntakeValue] = Field(default_factory=dict, max_length=30)
    editable: bool = True

    @model_validator(mode="after")
    def _checks(self):
        if not _REPO_ID_RE.match(self.producer):
            raise ValueError(
                f"intake producer {self.producer!r} must be a stable id")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("intake source_refs must be unique")
        if any(not ref.strip() or len(ref) > 300 for ref in self.source_refs):
            raise ValueError("intake source_refs must be non-empty and at most 300 chars")
        for name, value in self.parameters.items():
            if not _REPO_ID_RE.match(name):
                raise ValueError(
                    f"intake parameter {name!r} must be a stable id")
            if isinstance(value, str) and len(value) > 2000:
                raise ValueError(f"intake parameter {name!r} is longer than 2000 chars")
            if isinstance(value, list):
                if len(value) > 100 or any(not item.strip() or len(item) > 500 for item in value):
                    raise ValueError(
                        f"intake parameter {name!r} must contain 1-100 non-empty "
                        "strings of at most 500 chars")
        self._validate_growth_os_parameters()
        return self

    def _validate_growth_os_parameters(self) -> None:
        shapes = {
            "growth_os_arxiv": {
                "enabled": bool,
                "top_n": int,
                "lookback_days": int,
                "analysis_batch_size": int,
                "categories": list,
                "review_topics": list,
            },
            "growth_os_github": {
                "enabled": bool,
                "top_n": int,
                "lookback_days": int,
                "min_stars": int,
                "analysis_batch_size": int,
                "review_topics": list,
            },
        }
        expected = shapes.get(self.producer)
        if expected is None:
            return
        if set(self.parameters) != set(expected):
            raise ValueError(
                f"{self.producer} intake parameters must be exactly "
                f"{sorted(expected)}; got {sorted(self.parameters)}")
        for name, expected_type in expected.items():
            value = self.parameters[name]
            if expected_type is int:
                valid = type(value) is int and value >= 0
            elif expected_type is bool:
                valid = type(value) is bool
            else:
                valid = (
                    isinstance(value, list)
                    and all(isinstance(item, str) and item.strip() for item in value)
                )
            if not valid:
                raise ValueError(
                    f"{self.producer} intake parameter {name!r} has invalid type/value")
        top_n = self.parameters["top_n"]
        lookback_days = self.parameters["lookback_days"]
        if self.parameters["enabled"] and type(top_n) is int and top_n < 1:
            raise ValueError(f"{self.producer} top_n must be at least 1 while enabled")
        if type(top_n) is int and top_n > 500:
            raise ValueError(f"{self.producer} top_n must be <= 500")
        if type(lookback_days) is int and lookback_days > 365:
            raise ValueError(f"{self.producer} lookback_days must be <= 365")
        batch_size = self.parameters["analysis_batch_size"]
        if type(batch_size) is int and not 1 <= batch_size <= 200:
            raise ValueError(
                f"{self.producer} analysis_batch_size must be between 1 and 200")
        from command_center.research_topics import normalize_research_topics
        try:
            topics = normalize_research_topics(self.parameters["review_topics"])
        except ValueError as exc:
            raise ValueError(f"{self.producer} review_topics: {exc}") from exc
        if self.parameters["enabled"] and not topics:
            raise ValueError(
                f"{self.producer} needs at least one review topic while enabled")
        if topics != self.parameters["review_topics"]:
            raise ValueError(
                f"{self.producer} review_topics must be normalized and unique")
        if (
            self.parameters["enabled"]
            and type(top_n) is int
            and top_n < len(topics)
        ):
            raise ValueError(
                f"{self.producer} top_n must cover all configured review_topics")
        if self.producer == "growth_os_arxiv":
            categories = self.parameters["categories"]
            category_re = re.compile(
                r"^[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)?$")
            if len(categories) != len(set(categories)):
                raise ValueError("growth_os_arxiv categories must be unique")
            if any(
                len(category) > 50
                or category != category.strip()
                or not category_re.fullmatch(category)
                for category in categories
            ):
                raise ValueError(
                    "growth_os_arxiv categories must be valid arXiv category ids")


class DomainSurfaceSpec(Strict):
    domain_id: str
    title: str
    archived: bool = False
    card_component: str
    source: Literal["board_store", "ledger_missions", "fixtures"]
    board_id: str | None = None          # required iff source == board_store
    columns: list[str] = Field(default_factory=list)
    column_actions: dict[str, str] = Field(default_factory=dict)
    summary_fields: list[DomainFieldSpec] = Field(default_factory=list)
    drawer_fields: list[DomainFieldSpec] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    empty_state: DomainEmptyState
    intake: DomainIntakeSpec = Field(default_factory=DomainIntakeSpec)

    @model_validator(mode="after")
    def _checks(self):
        if not _REPO_ID_RE.match(self.domain_id):
            raise ValueError(f"domain_id {self.domain_id!r} must be a stable id")
        if self.card_component not in _DOMAIN_CARD_COMPONENTS:
            raise ValueError(
                f"domain {self.domain_id!r} card_component must be one of "
                f"{sorted(_DOMAIN_CARD_COMPONENTS)}; got {self.card_component!r}")
        if self.source == "board_store" and not self.board_id:
            raise ValueError(
                f"domain {self.domain_id!r} with source board_store needs board_id")
        if self.source != "board_store" and self.board_id:
            raise ValueError(
                f"domain {self.domain_id!r} board_id only applies to board_store")
        if len(self.columns) != len(set(self.columns)):
            raise ValueError(f"domain {self.domain_id!r} has duplicate columns")
        unknown_columns = set(self.column_actions) - set(self.columns)
        if unknown_columns:
            raise ValueError(
                f"domain {self.domain_id!r} column_actions reference unknown "
                f"column(s): {sorted(unknown_columns)}")
        actions = set(self.allowed_actions)
        if len(self.allowed_actions) != len(actions):
            raise ValueError(f"domain {self.domain_id!r} has duplicate allowed_actions")
        wall = actions & _KANBAN_WALL_VERBS
        if wall:
            raise ValueError(
                f"domain {self.domain_id!r} may never offer wall verb(s): {sorted(wall)}")
        ungrantable = actions - _KANBAN_GRANTABLE_VERBS
        if ungrantable:
            raise ValueError(
                f"domain {self.domain_id!r} allowed_actions may only grant "
                f"{sorted(_KANBAN_GRANTABLE_VERBS)}; got: {sorted(ungrantable)}")
        bad_column_actions = {
            column: action for column, action in self.column_actions.items()
            if action not in _KANBAN_GRANTABLE_VERBS
        }
        if bad_column_actions:
            raise ValueError(
                f"domain {self.domain_id!r} column_actions may only use grantable "
                f"kanban verbs; got: {bad_column_actions}")
        return self


class DomainSurfacesConfig(Strict):
    schema_version: str
    domains: list[DomainSurfaceSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.domain-surfaces.v1":
            raise ValueError("schema_version must be command-center.domain-surfaces.v1")
        ids = [d.domain_id for d in self.domains]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate domain_ids")
        return self


# ---- memory.yaml + memory records ------------------------------------------
# Cross-conversation/project memory. Records persist outside any single chat and
# are injected only when human-approved, namespaced by scope+subject, redacted,
# and citing provenance. Secrets are never stored. The config NAMES policies; the
# records carry their own provenance and retention so nothing is a magic global.
_MEMORY_SCOPES = ("conversation", "project", "board", "user_preference", "artifact")
# Content that must never be stored as a memory value (secrets / credentials).
_MEMORY_SECRET_RE = re.compile(
    r"(BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|ghs_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"
    r"(password|secret|token|api[_-]?key|client[_-]?secret)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
# retention_policy forms: "keep_until_superseded" or "expire_after_days:<N>"
_RETENTION_RE = re.compile(r"^(keep_until_superseded|expire_after_days:[1-9][0-9]*)$")


class MemoryRecord(Strict):
    memory_id: str
    scope: Literal["conversation", "project", "board", "user_preference", "artifact"]
    subject: str
    value: str
    source_ref: str
    created_at: str
    updated_at: str
    confidence: float = Field(ge=0.0, le=1.0)
    sensitivity: Literal["public", "internal", "confidential"]
    redaction_status: Literal["redacted", "not_required", "pending"]
    approved_by_human: bool = False
    inject_policy: Literal["always", "on_subject_match", "never"]
    retention_policy: str

    @model_validator(mode="after")
    def _checks(self):
        if not self.memory_id:
            raise ValueError("memory record needs a memory_id")
        if not self.source_ref:
            raise ValueError(f"memory {self.memory_id!r} requires a source_ref (provenance)")
        if not self.value.strip():
            raise ValueError(f"memory {self.memory_id!r} value cannot be empty")
        if not self.subject.strip():
            raise ValueError(f"memory {self.memory_id!r} subject (namespace) cannot be empty")
        # secrets are never stored as memory values
        if _MEMORY_SECRET_RE.search(self.value):
            raise ValueError(f"memory {self.memory_id!r} value looks secret-bearing; not stored")
        # project/board memory must be namespaced by a stable id (no leakage)
        if self.scope in ("project", "board") and not _REPO_ID_RE.match(self.subject):
            raise ValueError(
                f"memory {self.memory_id!r} {self.scope} subject must be a stable id namespace"
            )
        # confidential memory must be redacted before it can persist
        if self.sensitivity == "confidential" and self.redaction_status != "redacted":
            raise ValueError(
                f"memory {self.memory_id!r} confidential records must be redaction_status=redacted"
            )
        if not _RETENTION_RE.match(self.retention_policy):
            raise ValueError(
                f"memory {self.memory_id!r} retention_policy must be 'keep_until_superseded' "
                "or 'expire_after_days:<N>'"
            )
        return self


class MemoryConfig(Strict):
    schema_version: str
    store_path: str
    # No durable memory is created automatically from raw chats unless this is on.
    auto_durable_from_raw_chat: bool = False
    sensitivity_classes: list[str] = Field(default_factory=list)
    default_inject_policy: Literal["always", "on_subject_match", "never"] = "on_subject_match"
    default_retention_policy: str = "keep_until_superseded"

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.memory.v1":
            raise ValueError("schema_version must be command-center.memory.v1")
        if not self.store_path:
            raise ValueError("memory config needs a store_path")
        if not _RETENTION_RE.match(self.default_retention_policy):
            raise ValueError("memory default_retention_policy is malformed")
        if set(self.sensitivity_classes) != {"public", "internal", "confidential"}:
            raise ValueError(
                "memory sensitivity_classes must be exactly public/internal/confidential"
            )
        return self


# ---- content.yaml ----------------------------------------------------------
# LinkedIn publishing reads the first-party Posts board. Human movement into
# Scheduled is the approval gate; only due Scheduled cards may leave the machine.
class ContentSource(Strict):
    """First-party board-store location for LinkedIn post cards."""
    kind: Literal["command_center_ui"] = "command_center_ui"
    board_id: str = "linkedin_content_pipeline_internal"
    board_store_dir: str = "generated/boards"
    event_log_path: str = "generated/kanban-events.jsonl"

class ContentStatuses(Strict):
    """The three board columns, named here so the publisher holds no string
    literals. `approved` is the only status the publisher will ship (the human
    drag into it IS the approval); `done` is stamped back after publish."""
    queue: str = "In Queue"
    approved: str = "Scheduled"
    done: str = "Published"


class LinkedInOrgApp(Strict):
    """A SEPARATE LinkedIn app dedicated to the Community Management API. LinkedIn
    requires that product to be the ONLY one on its app, so company-Page posting
    (w_organization_social) cannot share the member app - it needs its own OAuth
    identity and token store. Shares the member app's API endpoints/version."""
    client_id_env: str = "LINKEDIN_ORG_CLIENT_ID"
    client_secret_env: str = "LINKEDIN_ORG_CLIENT_SECRET"
    redirect_uri_env: str = "LINKEDIN_ORG_REDIRECT_URI"
    token_store: str = "generated/linkedin-org-token.json"
    scopes: list[str] = ["r_organization_social", "w_organization_social"]


class LinkedInApi(Strict):
    """Official LinkedIn API endpoints/scopes. `version` is the required
    LinkedIn-Version header (YYYYMM); it has no default so the live value is
    always explicit in content.yaml rather than a stale literal in code."""
    api_base: str = "https://api.linkedin.com"
    posts_path: str = "/rest/posts"
    userinfo_url: str = "https://api.linkedin.com/v2/userinfo"
    auth_base: str = "https://www.linkedin.com/oauth/v2"
    version: str
    client_id_env: str = "LINKEDIN_CLIENT_ID"
    client_secret_env: str = "LINKEDIN_CLIENT_SECRET"
    redirect_uri_env: str = "LINKEDIN_REDIRECT_URI"
    token_store: str = "generated/linkedin-token.json"
    publish_ledger: str = "generated/linkedin-published.json"   # durable dedupe (anti double-post)
    lock_path: str = "generated/linkedin-publish.lock"          # single-process guard
    # How many days before the ~60-day access token expires to start warning
    # loudly (LinkedIn issues no refresh token to standard apps, so a human must
    # re-run --login). Externalized so the reminder lead time isn't a buried literal.
    token_warn_days: int = Field(default=14, ge=1)
    # A LinkedIn API version (YYYYMM) is sunset ~this many months after release; the
    # preflight/run warns when the configured version is within `version_warn_days`
    # of that sunset, so the API can't silently break mid-cadence. The lifetime is
    # LinkedIn policy (config, not a buried literal), the warn lead time is config.
    version_lifetime_months: int = Field(default=12, ge=1)
    version_warn_days: int = Field(default=45, ge=1)
    # Least-privilege: only what posting needs. userinfo (for the member URN)
    # needs openid+profile; member posting needs w_member_social; org posting
    # needs w_organization_social. No email, no r_*_social (read) scopes.
    member_scopes: list[str] = ["openid", "profile", "w_member_social"]
    organization_scopes: list[str] = ["w_organization_social"]
    # The separate Community-Management app for company-Page posting (optional;
    # member posting works without it). Present in content.yaml even before App B
    # is approved, so the publisher is org-ready the moment its creds land.
    org_app: LinkedInOrgApp | None = None

    @model_validator(mode="after")
    def _check_version(self):
        # YYYYMM with a real month - a typo'd version fails loudly here, never at
        # publish time (a bad header silently breaks the official API call).
        if not re.match(r"^\d{4}(0[1-9]|1[0-2])$", self.version):
            raise ValueError(
                f"linkedin.version {self.version!r} must be YYYYMM (e.g. 202606)")
        return self


class LinkedInAccount(Strict):
    board: str                                   # account id stored on each Posts card
    author: Literal["member", "organization"]
    org_urn_env: str = ""                        # required iff author == organization
    cadence: Literal["daily"] = "daily"

    @model_validator(mode="after")
    def _check(self):
        if self.author == "organization" and not self.org_urn_env:
            raise ValueError(f"account '{self.board}': organization author needs org_urn_env")
        if self.author == "member" and self.org_urn_env:
            raise ValueError(f"account '{self.board}': member author must not set org_urn_env")
        return self


class ContentConfig(Strict):
    schema_version: str
    source: ContentSource = ContentSource()
    statuses: ContentStatuses = ContentStatuses()
    linkedin: LinkedInApi
    accounts: list[LinkedInAccount] = []
    dry_run_default: bool = True

    @model_validator(mode="after")
    def _checks(self):
        boards = [a.board for a in self.accounts]
        if len(boards) != len(set(boards)):
            raise ValueError("duplicate account board names")
        if self.statuses.approved == self.statuses.done:
            raise ValueError("statuses.approved and statuses.done must differ")
        return self


# ---- content_pipeline.yaml -------------------------------------------------
# The content ENGINE (distinct from content.yaml, which is the publisher). It
# gathers evidence-backed candidates, drafts breakdown posts on the best local
# model, validates them with a multi-viewpoint judge panel (escalating the
# advanced parts), and stages the top few as In Queue drafts for human approval.
# No claim ships that isn't traceable to evidence (the no-overreach rule).
class ContentStream(Strict):
    name: str                                    # personal | business (free label)
    board: str                                   # content board to stage into
    curator_dbs: list[str] = ["papers", "repos", "signals"]
    topics: list[str] = []                       # keyword filter; empty = take all
    own_repos: list[str] = []                    # repo dir names to mine (git log + README)
    pillar: str = ""                             # default Pillar for staged cards
    voice: str                                   # short voice brief for the drafter


class ContentViewpoint(Strict):
    """One judge in the accuracy/quality panel."""
    key: Literal["factual_currency", "technical", "brand_voice", "no_overreach"]
    blocking: bool = True
    needs_web: bool = False                      # true -> escalate to the advanced (web) tier


# Provider-agnostic content routing. The content engine is local-first: the
# default policy runs on Ollama (via the local LiteLLM role) and is the ONLY path
# enabled by default. Paid external policies (GLM/Kimi) are metadata here so the
# dry-run estimator can price them - they never make a live call from config; a
# live paid route is operator-gated (budget + redaction + explicit egress). Large
# hosted models are escalation, not the default post formatter (docs/MASTER.md).
class ContentModelPrice(Strict):
    """USD per million tokens for a routable model. Used only by the dry-run cost
    estimator - naming a model here does not enable or call it."""
    model: str
    input_usd_per_mtok: float = Field(ge=0)
    output_usd_per_mtok: float = Field(ge=0)
    context_window: int = Field(default=0, ge=0)


class ContentLLMPolicy(Strict):
    name: str
    primary: str                                 # local role (e.g. "chat") or model id
    fallback: str = ""
    allow_paid: bool = False                     # paid egress off unless explicitly true
    max_request_usd: float = Field(default=0.0, ge=0)
    require_redaction: bool = False
    human_approval: bool = False

    @model_validator(mode="after")
    def _checks(self):
        # A paid policy MUST carry a budget and demand redaction - no open-ended
        # paid route, ever. (The default local policy needs neither.)
        if self.allow_paid:
            if self.max_request_usd <= 0:
                raise ValueError(f"policy '{self.name}': allow_paid requires max_request_usd > 0")
            if not self.require_redaction:
                raise ValueError(f"policy '{self.name}': allow_paid requires require_redaction")
        return self


class ContentLLMRouting(Strict):
    default_policy: str = "local_first"
    policies: list[ContentLLMPolicy] = []
    prices: list[ContentModelPrice] = []

    @model_validator(mode="after")
    def _checks(self):
        names = [p.name for p in self.policies]
        if len(names) != len(set(names)):
            raise ValueError("duplicate content_llm policy names")
        if self.policies:                        # empty = no routing configured (ok)
            if self.default_policy not in names:
                raise ValueError(f"default_policy '{self.default_policy}' is not a policy")
            default = next(p for p in self.policies if p.name == self.default_policy)
            if default.allow_paid:
                raise ValueError("default_policy must be local (allow_paid=false) - "
                                 "the engine is local-first")
        return self


class ContentPipelineConfig(Strict):
    schema_version: str
    source: ContentSource = ContentSource()      # first-party board source
    litellm_base_url: str = "http://localhost:4000"   # infra (host port), not a secret
    litellm_key_env: str = "LITELLM_MASTER_KEY"       # the secret, named not stored
    draft_role: str = "chat"                     # LiteLLM role for drafting (qwen3:30b)
    judge_role: str = "local-judge"              # LiteLLM role for the panel
    own_repos_root: str = ".."                   # repos dir relative to llm_station
    lookback_days: int = Field(default=14, ge=1)
    candidates_per_run: int = Field(default=25, ge=1)
    surface_top: int = Field(default=5, ge=1)
    brief_path: str = "generated/content-brief.json"
    claims_path: str = "generated/content-claims.json"   # the evidence ledger
    streams: list[ContentStream] = []
    judges: list[ContentViewpoint] = []
    content_llm: ContentLLMRouting = ContentLLMRouting()  # provider-agnostic routing

    @model_validator(mode="after")
    def _checks(self):
        if len({s.board for s in self.streams}) != len(self.streams):
            raise ValueError("duplicate stream board names")
        if self.surface_top > self.candidates_per_run:
            raise ValueError("surface_top cannot exceed candidates_per_run")
        if not self.judges:
            raise ValueError("at least one judge viewpoint is required")
        return self


# ---- content_reference.yaml ------------------------------------------------
# The reference index: the curated half of "find things by intent, not exact
# names". Each item names a post/library/board/doc/etc. with aliases + tags so a
# fuzzy/semantic query resolves to it. The resolver also indexes live sources
# (the posts store, content streams) at build time; this file is the stable seed.
# Invariant (docs/MASTER.md): no user-facing command relies on exact names only -
# exact id is just the first fast path in a cascade, never the only path.
class ReferenceItem(Strict):
    id: str                                      # stable slug, first fast-path match
    kind: Literal["doc", "post", "library", "kanban", "config", "repo",
                  "model", "topic"]
    title: str
    aliases: list[str] = []                      # alternate names a human might say
    tags: list[str] = []                         # keywords (BM25 / semantic signal)
    source_path: str = ""                        # optional file/dir this points at
    summary: str = ""                            # one line, indexed for retrieval


class ContentReferenceConfig(Strict):
    schema_version: str
    items: list[ReferenceItem] = []
    # Resolver knobs (externalized so no retrieval decision is a buried literal).
    fuzzy_threshold: int = Field(default=72, ge=0, le=100)   # RapidFuzz score floor
    ambiguous_margin: float = Field(default=0.06, ge=0, le=1)  # top1-top2 gap -> top-3
    embed_enabled: bool = True                   # the semantic tier (local nomic-embed)
    embed_model: str = "nomic-embed-text"
    index_path: str = "data/reference/index.jsonl"

    @model_validator(mode="after")
    def _checks(self):
        ids = [i.id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate reference item ids")
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


# ---- capabilities.yaml -----------------------------------------------------
# Tamper-detection policy for capability provenance. The digest field turns
# "declared provenance" into "verified provenance": a sha256 over the local
# artifact a capability is backed by, recomputed by check_cross_refs (and so by
# `make validate`) and failed on drift. We require it only where tampering is
# both consequential and locally checkable — capability TYPES that execute or
# get promoted (skill/mcp_server/model_candidate), at risk_tier >= L1, for
# provenance refs that point at a repository-local file. Remote (URL) and opaque
# (scheme:opaque) refs can't be hashed here, so they're exempt from the
# requirement; lower-risk read-only types aren't worth the maintenance tax.
# These are NAMED knobs, not magic literals — widen the type set or lower the
# tier here and both the schema requirement and the verifier follow in lockstep.
DIGEST_REQUIRED_TYPES = frozenset({"skill", "mcp_server", "model_candidate"})
DIGEST_REQUIRED_MIN_TIER = RiskTier.L1

_RISK_ORDER = {t: i for i, t in enumerate(
    (RiskTier.L0, RiskTier.L1, RiskTier.L2, RiskTier.L3, RiskTier.L4))}
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def source_ref_kind(source_ref: str) -> str:
    """Classify a provenance source_ref so requirement and verification agree.

    "remote"  — a URL (http://, https://, …); content lives off-repo, not hashable here.
    "opaque"  — a non-path scheme like `operator-local:codex-rtk`; a pointer, not a file.
    "local"   — a repository-relative path (optionally with a #fragment); hashable.
    """
    base = source_ref.split("#", 1)[0].strip()
    if _URL_RE.match(base):
        return "remote"
    if _SCHEME_RE.match(base) and not _WIN_DRIVE_RE.match(base):
        return "opaque"
    return "local"


def digest_required_for(entry_type: str, risk_tier: RiskTier) -> bool:
    """A local provenance ref must pin a digest iff its capability is a
    tamper-relevant type at or above the minimum tier. Single predicate shared by
    the schema (which requires the field) and the verifier (which recomputes it)."""
    return (entry_type in DIGEST_REQUIRED_TYPES
            and _RISK_ORDER[risk_tier] >= _RISK_ORDER[DIGEST_REQUIRED_MIN_TIER])


# ARD-style discovery metadata for internal tools, skills, workflows, and model
# candidates. This is intentionally separate from tools.yaml: tools.yaml is the
# permission policy judges cite, while this catalog is the routing/discovery
# surface that says what exists, who owns it, when it was last reviewed, and what
# queries should retrieve it.
class CapabilityTrust(Strict):
    publisher: str
    identity: str
    identity_type: Literal["local_config", "local_doc", "upstream_project", "domain", "manual_review"]
    verification: str
    attestations: list[str] = []


class CapabilityProvenance(Strict):
    relation: str
    source_ref: str
    # sha256 over the artifact at source_ref. Optional here; CapabilityEntry makes
    # it mandatory for tamper-relevant capabilities (see digest_required_for).
    digest: str | None = None

    @model_validator(mode="after")
    def _checks(self):
        normalized = self.source_ref.replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("/"):
            raise ValueError("capability provenance source_ref must not be a local absolute path")
        if not self.relation:
            raise ValueError("capability provenance relation is required")
        if not self.source_ref:
            raise ValueError("capability provenance source_ref is required")
        if self.digest is not None and not _DIGEST_RE.match(self.digest):
            raise ValueError(
                "capability provenance digest must be 'sha256:<64 lowercase hex>' "
                "(run `make capabilities-digests` to compute it)")
        return self


class CapabilityEntry(Strict):
    identifier: str
    display_name: str
    type: Literal[
        "tool",
        "skill",
        "workflow",
        "model_candidate",
        "mcp_server",
        "openapi_tool",
        "a2a_agent",
        "registry",
    ]
    owner: str
    risk_tier: RiskTier
    summary: str
    artifact_ref: str
    capabilities: list[str] = []
    tags: list[str] = []
    representative_queries: list[str] = Field(min_length=2, max_length=5)
    updated_at: str
    trust: CapabilityTrust
    provenance: list[CapabilityProvenance] = Field(min_length=1)

    @model_validator(mode="after")
    def _checks(self):
        if not self.identifier.startswith("urn:air:"):
            raise ValueError(
                f"capability {self.identifier!r} must use the ARD-style urn:air namespace"
            )
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", self.updated_at):
            raise ValueError(
                f"capability {self.identifier!r} updated_at must be YYYY-MM-DD"
            )
        if len(self.representative_queries) != len(set(self.representative_queries)):
            raise ValueError(
                f"capability {self.identifier!r} has duplicate representative_queries"
            )
        if not self.owner:
            raise ValueError(f"capability {self.identifier!r} must declare an owner")
        # Verified-provenance gate: a tamper-relevant capability must pin a digest
        # for every local artifact it claims to come from. The verifier
        # (check_cross_refs) then recomputes that digest and fails on drift.
        if digest_required_for(self.type, self.risk_tier):
            for prov in self.provenance:
                if source_ref_kind(prov.source_ref) == "local" and not prov.digest:
                    raise ValueError(
                        f"capability {self.identifier!r} is a {self.type} at "
                        f"{self.risk_tier.value} and must pin a digest for local "
                        f"provenance {prov.source_ref!r} "
                        f"(run `make capabilities-digests` to compute it)")
        return self


class CapabilityCatalogConfig(Strict):
    schema_version: str
    entries: list[CapabilityEntry]

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.capabilities.v1":
            raise ValueError("schema_version must be command-center.capabilities.v1")
        if not self.entries:
            raise ValueError("capability catalog must define at least one entry")
        ids = [entry.identifier for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("capability catalog contains duplicate identifiers")
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


# A reference to a held-out / sealed / adversarial / historical / rotating eval
# SUITE. Implementers can read this REF (id/category/description) but NOT the suite
# CONTENT — the inputs and expected answers live under `source`, an access-controlled
# path the verifier/eval-service reads and the implementer's harness does not. This is
# filesystem SEPARATION, not cryptographic secrecy (see docs/improvement/independent-verification.md).
class EvalSuiteRef(Strict):
    id: str
    category: Literal["sealed", "adversarial", "historical", "rotating",
                      "repository_specific"]
    description: str
    version: str                                  # pinned; changing a suite is its own experiment
    source: str                                   # path to the access-controlled content file
    owner: str
    rotates: bool = False                         # rotating suites are refreshed on a cadence
    retired: bool = False                         # saturated suites are retired, not endlessly mined
    saturation_threshold: float = Field(default=0.98, ge=0.0, le=1.0)


class EvalsConfig(Strict):
    schema_version: str
    cases: list[EvalCase]
    # Held-out families. Visible refs only; content stays under access control.
    sealed: list[EvalSuiteRef] = []
    adversarial: list[EvalSuiteRef] = []
    historical: list[EvalSuiteRef] = []
    rotating: list[EvalSuiteRef] = []

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
        all_refs = self.sealed + self.adversarial + self.historical + self.rotating
        ids = [r.id for r in all_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate eval suite id across sealed/adversarial/historical/rotating")
        for r in all_refs:
            # sealed content must live under the access-controlled sealed-evals area
            if not r.source.replace("\\", "/").startswith("data/sealed-evals/"):
                raise ValueError(f"eval suite '{r.id}' source must live under data/sealed-evals/ "
                                 "(access-controlled; not visible to implementers)")
        return self


# ---- ui.yaml ---------------------------------------------------------------
# Human UI surfaces. The Phase-4 WebUI slot now hosts the FIRST-PARTY agent kanban +
# observability surface over board store/Ledger (repurposed from the deferred Hermes
# WebUI — see MASTER.md change log). Still a CONVENIENCE layer, never the policy
# layer: external writes flow through the Ledger/gates (external_write_policy must
# stay governed_by_ledger), and public exposure without a password is forbidden.
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
    agent_kanban_ui: WebUIConfig = WebUIConfig()


# ---- agent_surface.yaml -----------------------------------------------------
# Knobs for the agent kanban surface: how the harness re-injects canonical board
# state into the agent loop, how it resolves cards by title, and how the cadence
# learner is bounded. Every value here is externalized so no agent-loop decision
# is an inline literal — and the cadence is data-derived (the Phase-3 learner in
# command_center.kanban.tuning takes over from these defaults once it beats them
# on logged outcomes, abstaining below `tuning.min_decisions`). See
# docs/kanban/AGENT_KANBAN_SURFACE.md.
BoardName = Literal["mission_intake", "todos", "missions"]


class BoardStateKnobs(Strict):
    """The harness owns board state and re-injects it as a single source of truth
    each turn (the Cline focus-chain pattern). Fail-loud: a fetch error surfaces
    into context, never an empty/stale block."""
    enabled: bool = True
    # within one user turn, re-inject after this many tool rounds (0 = only at
    # turn start). The board is always injected at the start of a turn.
    refresh_every_rounds: int = Field(default=3, ge=0)
    # rows shown per column/status group; overflow is disclosed explicitly as
    # "(+N more)" — a bounded view, never a silent truncation.
    max_items_per_group: int = Field(default=12, ge=1)
    boards: list[BoardName] = ["mission_intake", "todos", "missions"]

    @model_validator(mode="after")
    def _checks(self):
        if not self.boards:
            raise ValueError("board_state.boards must list at least one board")
        if len(set(self.boards)) != len(self.boards):
            raise ValueError(f"board_state.boards has duplicates: {self.boards}")
        return self


class AddressingKnobs(Strict):
    """The harness resolves cards/todos by title (the model never sees row keys).
    A unique match above the ratio wins; otherwise the agent gets candidates back
    and must retry — no silent best-guess."""
    fuzzy_min_ratio: float = Field(default=0.6, gt=0.0, le=1.0)


class TuningKnobs(Strict):
    """Bounds for the cadence learner (command_center.kanban.tuning), mirroring the
    discovery scan's AcceptanceKnobs: it abstains to the config defaults below the
    decision floor, splits temporally, and only adopts a learned cadence when it
    beats the configured one by `min_auc_uplift` on held-out turns."""
    min_decisions: int = Field(default=40, ge=1)
    holdout_fraction: float = Field(default=0.3, gt=0.0, lt=1.0)
    min_auc_uplift: float = Field(default=0.02, ge=0.0)
    learning_rate: float = Field(default=0.1, gt=0.0)
    max_iterations: int = Field(default=500, ge=1)
    l2: float = Field(default=1.0, ge=0.0)


class AgentSurfaceConfig(Strict):
    schema_version: str
    board_state: BoardStateKnobs = Field(default_factory=BoardStateKnobs)
    addressing: AddressingKnobs = Field(default_factory=AddressingKnobs)
    tuning: TuningKnobs = Field(default_factory=TuningKnobs)


# ---- autonomy.yaml ----------------------------------------------------------
# Contracts for the whole-system autonomy hardening layer. This is deliberately a
# contract/config layer first: event schemas, repo manifests, desktop rights,
# completion verification, canaries, telemetry posture, auth review, and external
# runtime evaluation policy. It does not enable desktop automation or repo writes
# by itself.
_EVENT_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_REPO_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")

_MINIMUM_EVENT_FIELDS = {
    "event_id",
    "mission_id",
    "timestamp",
    "actor",
    "source_authority",
    "risk_tier",
    "privacy_classification",
    "result",
    "input_artifact_hashes",
    "output_artifact_hashes",
    "trace_id",
}
_REQUIRED_EVENT_FAMILIES = {
    "mission.forecast",
    "mission.action",
    "mission.verification",
    "mission.rollback",
    "route.decision",
    "repo.action",
    "kanban.mutation",
    "desktop.observation",
    "desktop.action",
    "model.call",
    "notification.sent",
}
_DEFAULT_DESKTOP_DENIES = {
    "clipboard_read",
    "password_field_read",
    "system_settings_change",
    "file_delete",
}
_AUTOMATION_ORDER = ["direct_api", "browser", "os_accessibility", "screenshot"]


class EventFamilySpec(Strict):
    kind: str
    required_fields: list[str]
    raw_payload_allowed: bool = False
    retained_artifact_policy: Literal["hashes_and_refs_only", "redacted_summary_only"]

    @model_validator(mode="after")
    def _checks(self):
        if not _EVENT_KIND_RE.match(self.kind):
            raise ValueError(f"event family {self.kind!r} must use dotted lowercase form")
        if not self.required_fields:
            raise ValueError(f"event family {self.kind!r} must declare required_fields")
        if len(self.required_fields) != len(set(self.required_fields)):
            raise ValueError(f"event family {self.kind!r} has duplicate required_fields")
        if self.raw_payload_allowed:
            raise ValueError(
                f"event family {self.kind!r} may not retain raw payloads; "
                "store hashes, refs, or redacted summaries"
            )
        return self


class EventContractConfig(Strict):
    schema_version: str
    privacy_classes: list[Literal["public", "internal", "confidential", "secret_reference"]]
    result_values: list[str]
    common_required_fields: list[str]
    families: list[EventFamilySpec]

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.events.v1":
            raise ValueError("event_contract.schema_version must be command-center.events.v1")
        if len(self.privacy_classes) != len(set(self.privacy_classes)):
            raise ValueError("event_contract.privacy_classes contains duplicates")
        if "confidential" not in self.privacy_classes:
            raise ValueError("event_contract must include confidential privacy class")
        if "secret_reference" not in self.privacy_classes:
            raise ValueError("event_contract must include secret_reference privacy class")
        if len(self.result_values) != len(set(self.result_values)):
            raise ValueError("event_contract.result_values contains duplicates")
        if len(self.common_required_fields) != len(set(self.common_required_fields)):
            raise ValueError("event_contract.common_required_fields contains duplicates")
        missing_fields = _MINIMUM_EVENT_FIELDS - set(self.common_required_fields)
        if missing_fields:
            raise ValueError(
                "event_contract.common_required_fields missing minimum field(s): "
                f"{sorted(missing_fields)}"
            )
        kinds = [family.kind for family in self.families]
        if len(kinds) != len(set(kinds)):
            raise ValueError("event_contract contains duplicate event families")
        missing_families = _REQUIRED_EVENT_FAMILIES - set(kinds)
        if missing_families:
            raise ValueError(
                "event_contract missing required event family/families: "
                f"{sorted(missing_families)}"
            )
        return self


class RepoManifest(Strict):
    repo_id: str
    remote_url: str
    default_branch: str
    protected_branches: list[str]
    allowed_base_branches: list[str]
    branch_write_policy: Literal["feature_branch_only"]
    auth_mode: Literal["github_app", "github_app_pending", "fine_grained_pat_pilot_only"]
    execution_mode: Literal["devcontainer", "contract_only"]
    devcontainer_path: str | None = None
    ci_commands: list[str]
    secret_policy: Literal["no_runtime_secrets_inside_container"]
    codeowners_required: bool
    codeowners_path: str | None = None
    risk_ceiling: RiskTier
    # Binds the repo to a board in kanban_boards.yaml (cross-checked by repo-verify).
    kanban_board_id: str | None = None
    # Where the repo lives on this machine. Stored as 'self' (the control-plane
    # repo) or an 'env:NAME' reference; never a committed absolute path.
    local_path_ref: str | None = None
    # Exact capability vocabulary used to ground Paper/Repo folder-fit scoring.
    # New manifests may start empty, but then research analysis must treat the
    # folder as having no declared direct fit rather than guessing from its name.
    research_capabilities: list[str] = Field(
        default_factory=list, max_length=12)
    # The repo's OWN required CI check names that gate its PRs (the PR-check loop +
    # branch protection use these). Empty -> fall back to the global
    # branch_protection_verification.required_status_check_contexts (the self repo).
    required_status_check_contexts: list[str] = Field(default_factory=list)
    # How the merge wall is enforced for this repo:
    #  - github_branch_protection: server-side (ruleset/branch protection); the
    #    strongest posture, but unavailable for PRIVATE repos on a free GitHub plan.
    #  - local_pre_push_and_human_merge: a local pre-push guard blocks direct pushes
    #    to protected branches on this machine, the agent stays PR-only (structural,
    #    via the action layer), and a human merges. LOWER ASSURANCE — there is no
    #    server-side backstop — chosen deliberately for a private+free repo.
    merge_wall: Literal["github_branch_protection",
                        "local_pre_push_and_human_merge"] = "github_branch_protection"
    autonomous_edits_enabled: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if not _REPO_ID_RE.match(self.repo_id):
            raise ValueError(f"repo_id {self.repo_id!r} must be a stable id")
        if not self.remote_url:
            raise ValueError(f"repo {self.repo_id!r} remote_url is required")
        if not self.default_branch:
            raise ValueError(f"repo {self.repo_id!r} default_branch is required")
        if self.default_branch not in self.allowed_base_branches:
            raise ValueError(
                f"repo {self.repo_id!r} default_branch must appear in allowed_base_branches"
            )
        if len(self.allowed_base_branches) != len(set(self.allowed_base_branches)):
            raise ValueError(f"repo {self.repo_id!r} allowed_base_branches has duplicates")
        if not self.ci_commands:
            raise ValueError(f"repo {self.repo_id!r} must declare ci_commands")
        if any(not cmd for cmd in self.ci_commands):
            raise ValueError(f"repo {self.repo_id!r} ci_commands cannot contain blank commands")
        if self.codeowners_required and not self.codeowners_path:
            raise ValueError(f"repo {self.repo_id!r} requires codeowners_path")
        if self.risk_ceiling in (RiskTier.L3, RiskTier.L4):
            raise ValueError(f"repo {self.repo_id!r} autonomous risk ceiling cannot exceed L2")
        if self.execution_mode == "devcontainer" and not self.devcontainer_path:
            raise ValueError(f"repo {self.repo_id!r} devcontainer execution needs devcontainer_path")
        if self.kanban_board_id is not None and not _REPO_ID_RE.match(self.kanban_board_id):
            raise ValueError(f"repo {self.repo_id!r} kanban_board_id must be a stable id")
        if self.local_path_ref is not None:
            ref = self.local_path_ref
            if ref != "self" and not ref.startswith("env:"):
                raise ValueError(
                    f"repo {self.repo_id!r} local_path_ref must be 'self' or an 'env:NAME' "
                    "reference; a committed absolute path would leak machine layout"
                )
        if (
            any(not capability.strip() for capability in self.research_capabilities)
            or len(self.research_capabilities)
            != len(set(self.research_capabilities))
        ):
            raise ValueError(
                f"repo {self.repo_id!r} research_capabilities must be unique "
                "non-blank strings")
        if self.autonomous_edits_enabled:
            if self.blockers:
                raise ValueError(f"repo {self.repo_id!r} enabled manifests cannot list blockers")
            if self.auth_mode != "github_app":
                raise ValueError(
                    f"repo {self.repo_id!r} autonomous edits require auth_mode=github_app"
                )
            if self.execution_mode != "devcontainer" or not self.devcontainer_path:
                raise ValueError(
                    f"repo {self.repo_id!r} autonomous edits require a devcontainer manifest"
                )
            if not self.codeowners_required:
                raise ValueError(
                    f"repo {self.repo_id!r} autonomous edits require CODEOWNERS review"
                )
            if not self.kanban_board_id:
                raise ValueError(
                    f"repo {self.repo_id!r} autonomous edits require a kanban_board_id"
                )
            if not self.local_path_ref:
                raise ValueError(
                    f"repo {self.repo_id!r} autonomous edits require a local_path_ref"
                )
        elif not self.blockers:
            raise ValueError(f"repo {self.repo_id!r} disabled manifests must list blockers")
        return self


class DesktopVerifierSpec(Strict):
    type: Literal["ui_assertion", "api_assertion", "event_assertion"]
    must_show: list[str] = Field(default_factory=list)
    evidence_event_family: str

    @model_validator(mode="after")
    def _checks(self):
        if self.type == "ui_assertion" and not self.must_show:
            raise ValueError("ui_assertion desktop verifier must declare must_show evidence")
        return self


class DesktopTarget(Strict):
    target_id: str
    enabled: bool = False
    os_family: Literal["windows", "macos", "browser"]
    surface: Literal["direct_api", "browser", "os_accessibility", "screenshot"]
    board: str | None = None
    card_ref: str | None = None
    snapshot_evidence_ref: str | None = None
    allowed_windows: list[str]
    allowed_actions: list[str]
    forbidden_actions: list[str]
    verifier: DesktopVerifierSpec
    automation_order: list[Literal["direct_api", "browser", "os_accessibility", "screenshot"]]
    ttl_minutes: int | None = Field(default=None, ge=1)
    ttl_source: str | None = None
    action_timeout_seconds: int | None = Field(default=None, ge=1)
    action_timeout_source: str | None = None
    human_takeover_hotkey: str | None = None
    screenshot_artifact_policy: Literal[
        "none",
        "redacted_hashes_and_refs_only",
    ] | None = None
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if not _REPO_ID_RE.match(self.target_id):
            raise ValueError(f"desktop target {self.target_id!r} must be a stable id")
        if not self.allowed_windows:
            raise ValueError(f"desktop target {self.target_id!r} must declare allowed_windows")
        if not self.allowed_actions:
            raise ValueError(f"desktop target {self.target_id!r} must declare allowed_actions")
        if (self.board is None) != (self.card_ref is None):
            raise ValueError(
                f"desktop target {self.target_id!r} board and card_ref must be declared together"
            )
        if self.card_ref and not self.snapshot_evidence_ref:
            raise ValueError(
                f"desktop target {self.target_id!r} selected card_ref needs snapshot evidence"
            )
        if len(self.allowed_windows) != len(set(self.allowed_windows)):
            raise ValueError(f"desktop target {self.target_id!r} has duplicate allowed_windows")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError(f"desktop target {self.target_id!r} has duplicate allowed_actions")
        if len(self.forbidden_actions) != len(set(self.forbidden_actions)):
            raise ValueError(f"desktop target {self.target_id!r} has duplicate forbidden_actions")
        overlap = set(self.allowed_actions) & set(self.forbidden_actions)
        if overlap:
            raise ValueError(
                f"desktop target {self.target_id!r} action(s) both allowed and forbidden: "
                f"{sorted(overlap)}"
            )
        missing_denies = _DEFAULT_DESKTOP_DENIES - set(self.forbidden_actions)
        if missing_denies:
            raise ValueError(
                f"desktop target {self.target_id!r} missing default deny action(s): "
                f"{sorted(missing_denies)}"
            )
        if self.automation_order != _AUTOMATION_ORDER:
            raise ValueError(
                f"desktop target {self.target_id!r} automation_order must be "
                f"{_AUTOMATION_ORDER}"
            )
        if (self.ttl_minutes is None) != (self.ttl_source is None):
            raise ValueError(
                f"desktop target {self.target_id!r} ttl_minutes and ttl_source must be "
                "declared together"
            )
        if (self.action_timeout_seconds is None) != (self.action_timeout_source is None):
            raise ValueError(
                f"desktop target {self.target_id!r} action_timeout_seconds and "
                "action_timeout_source must be declared together"
            )
        if self.enabled:
            if self.blockers:
                raise ValueError(f"desktop target {self.target_id!r} enabled target has blockers")
            if self.ttl_minutes is None:
                raise ValueError(
                    f"desktop target {self.target_id!r} enabled target needs ttl_minutes"
                )
            if self.action_timeout_seconds is None:
                raise ValueError(
                    f"desktop target {self.target_id!r} enabled target needs action_timeout_seconds"
                )
            if not self.human_takeover_hotkey:
                raise ValueError(
                    f"desktop target {self.target_id!r} enabled target needs takeover hotkey"
                )
            if not self.screenshot_artifact_policy:
                raise ValueError(
                    f"desktop target {self.target_id!r} enabled target needs screenshot policy"
                )
            if not self.board or not self.card_ref:
                raise ValueError(
                    f"desktop target {self.target_id!r} enabled target needs board and card_ref"
                )
        elif not self.blockers:
            raise ValueError(f"desktop target {self.target_id!r} disabled target needs blockers")
        return self


class CompletionVerifierConfig(Strict):
    enabled: bool = True
    done_requires_evidence_refs: bool = True
    required_event_families: list[str]
    repeated_action_policy: Literal[
        "block_or_strategy_change",
        "experiment_derived_threshold_required_before_autonomous_gui",
    ]

    @model_validator(mode="after")
    def _checks(self):
        required = {"mission.forecast", "mission.verification"}
        missing = required - set(self.required_event_families)
        if missing:
            raise ValueError(
                "completion_verifier.required_event_families missing "
                f"{sorted(missing)}"
            )
        if not self.done_requires_evidence_refs:
            raise ValueError("completion_verifier must require evidence refs before DONE")
        return self


class AgentValidationConfig(Strict):
    model_alias: str
    max_tokens: int = Field(ge=1)
    max_tokens_source: str
    required_scenarios: list[Literal[
        "chat_tool_call_parse",
        "memory_block_recall",
        "long_multi_turn_recall",
        "fresh_conversation_without_memory_abstains",
    ]]

    @model_validator(mode="after")
    def _checks(self):
        if not self.model_alias:
            raise ValueError("agent_validation.model_alias must be declared")
        if not self.max_tokens_source:
            raise ValueError("agent_validation.max_tokens_source must be declared")
        if len(self.required_scenarios) != len(set(self.required_scenarios)):
            raise ValueError("agent_validation.required_scenarios contains duplicates")
        return self


class AutonomyCanarySpec(Strict):
    name: str
    kind: Literal[
        "read_only_repo_scan",
        "noop_kanban_roundtrip",
        "browser_staging_task",
        "prompt_judge_suite",
        "model_routing_benchmark",
        "notification_dry_run",
        "privacy_artifact_scan",
    ]
    enabled: bool = False
    risk_tier: RiskTier
    schedule: str | None = None
    evidence_required: list[str]
    blocked_until: list[str] = Field(default_factory=list)
    writes_external: bool = False

    @model_validator(mode="after")
    def _checks(self):
        if not self.evidence_required:
            raise ValueError(f"canary {self.name!r} must declare evidence_required")
        if self.risk_tier in (RiskTier.L3, RiskTier.L4):
            raise ValueError(f"canary {self.name!r} cannot be L3/L4 autonomous work")
        if self.enabled:
            if not self.schedule:
                raise ValueError(f"enabled canary {self.name!r} must declare schedule")
            if self.blocked_until:
                raise ValueError(f"enabled canary {self.name!r} cannot list blocked_until")
        else:
            if self.schedule:
                raise ValueError(f"disabled canary {self.name!r} must not declare schedule")
            if not self.blocked_until:
                raise ValueError(f"disabled canary {self.name!r} must declare blocked_until")
        if self.writes_external:
            raise ValueError(f"canary {self.name!r} must not write external systems")
        return self


class DesktopNoopCanarySpec(Strict):
    target_id: str
    target_type: Literal["desktop", "browser"]
    allowed_mode: Literal["read_only", "no_op_roundtrip"]
    allowed_apps_windows_domains: list[str]
    allowed_actions: list[str]
    forbidden_actions: list[str]
    evidence_policy: Literal["redacted_json_only"]
    screenshot_policy: Literal["none", "redacted_hashes_and_refs_only"]
    redaction_policy: Literal["no_raw_content_no_secrets_no_clipboard"]
    human_takeover_policy_ref: str
    measurement_fields: list[Literal[
        "snapshot_load_ms",
        "target_verify_ms",
        "total_duration_ms",
    ]]
    max_action_count: int | None = Field(default=None, ge=0)
    max_action_count_source: str | None = None
    production_enabling: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if not _REPO_ID_RE.match(self.target_id):
            raise ValueError(f"desktop noop canary target_id {self.target_id!r} must be stable")
        if not self.allowed_apps_windows_domains:
            raise ValueError(
                f"desktop noop canary {self.target_id!r} must declare allowed targets"
            )
        if not self.allowed_actions:
            raise ValueError(
                f"desktop noop canary {self.target_id!r} must declare allowed_actions"
            )
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError(f"desktop noop canary {self.target_id!r} has duplicate allowed_actions")
        if len(self.forbidden_actions) != len(set(self.forbidden_actions)):
            raise ValueError(
                f"desktop noop canary {self.target_id!r} has duplicate forbidden_actions"
            )
        overlap = set(self.allowed_actions) & set(self.forbidden_actions)
        if overlap:
            raise ValueError(
                f"desktop noop canary {self.target_id!r} action(s) both allowed and forbidden: "
                f"{sorted(overlap)}"
            )
        missing_denies = _DEFAULT_DESKTOP_DENIES - set(self.forbidden_actions)
        if missing_denies:
            raise ValueError(
                f"desktop noop canary {self.target_id!r} missing default deny action(s): "
                f"{sorted(missing_denies)}"
            )
        if self.allowed_mode == "read_only":
            blocked_live_actions = {"click", "type", "select", "drag", "keyboard_shortcut"}
            live_overlap = blocked_live_actions & set(self.allowed_actions)
            if live_overlap:
                raise ValueError(
                    f"desktop noop canary {self.target_id!r} read_only mode cannot allow "
                    f"live action(s): {sorted(live_overlap)}"
                )
        if self.screenshot_policy != "none" and not self.redaction_policy:
            raise ValueError(
                f"desktop noop canary {self.target_id!r} screenshot storage needs redaction_policy"
            )
        if not self.human_takeover_policy_ref:
            raise ValueError(
                f"desktop noop canary {self.target_id!r} needs human_takeover_policy_ref"
            )
        if len(self.measurement_fields) != len(set(self.measurement_fields)):
            raise ValueError(
                f"desktop noop canary {self.target_id!r} measurement_fields contains duplicates"
            )
        required_measurements = {
            "snapshot_load_ms",
            "target_verify_ms",
            "total_duration_ms",
        }
        missing_measurements = required_measurements - set(self.measurement_fields)
        if missing_measurements:
            raise ValueError(
                f"desktop noop canary {self.target_id!r} missing measurement field(s): "
                f"{sorted(missing_measurements)}"
            )
        if (self.max_action_count is None) != (self.max_action_count_source is None):
            raise ValueError(
                f"desktop noop canary {self.target_id!r} max_action_count and "
                "max_action_count_source must be declared together"
            )
        if self.max_action_count is not None and self.production_enabling:
            raise ValueError(
                f"desktop noop canary {self.target_id!r} max_action_count cannot enable production"
            )
        return self


class DesktopTimingSamplePlan(Strict):
    target_id: str
    status: Literal["declared"]
    source_work_item: str
    sample_plan_basis: Literal["explicit_read_only_noop_samples_for_current_staging_snapshot"]
    required_evidence_refs: list[str]
    required_sample_count_source: str
    required_measurement_fields: list[Literal[
        "snapshot_load_ms",
        "target_verify_ms",
        "total_duration_ms",
    ]]
    candidate_derivation: Literal["max_observed_read_only_noop_timing_without_multiplier"]
    evidence_policy: Literal["redacted_json_only"]
    live_actions_allowed: bool = False
    production_enabling: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if not _REPO_ID_RE.match(self.target_id):
            raise ValueError(f"desktop timing sample plan target_id {self.target_id!r} must be stable")
        if not self.source_work_item:
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} must name source_work_item"
            )
        if not self.required_evidence_refs:
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} must list evidence refs"
            )
        if len(self.required_evidence_refs) != len(set(self.required_evidence_refs)):
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} has duplicate evidence refs"
            )
        for ref in self.required_evidence_refs:
            normalized = ref.replace("\\", "/")
            parts = [part for part in normalized.split("/") if part]
            if (
                not normalized
                or normalized.startswith("/")
                or ":" in normalized
                or ".." in parts
                or normalized.startswith(".env")
                or "/.env" in normalized
                or normalized.endswith(".pem")
            ):
                raise ValueError(
                    f"desktop timing sample plan {self.target_id!r} evidence_ref "
                    f"{ref!r} must be a repo-relative non-secret artifact"
                )
            if not normalized.startswith("evaluation/system-validation/"):
                raise ValueError(
                    f"desktop timing sample plan {self.target_id!r} evidence_ref "
                    f"{ref!r} must stay under evaluation/system-validation"
                )
        if "required_evidence_refs" not in self.required_sample_count_source:
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} required_sample_count_source "
                "must derive from required_evidence_refs"
            )
        if len(self.required_measurement_fields) != len(set(self.required_measurement_fields)):
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} measurement fields contain duplicates"
            )
        required_measurements = {
            "snapshot_load_ms",
            "target_verify_ms",
            "total_duration_ms",
        }
        missing_measurements = required_measurements - set(self.required_measurement_fields)
        if missing_measurements:
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} missing measurement field(s): "
                f"{sorted(missing_measurements)}"
            )
        if self.live_actions_allowed:
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} cannot allow live actions"
            )
        if self.production_enabling:
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} cannot enable production values"
            )
        if self.blockers:
            raise ValueError(
                f"desktop timing sample plan {self.target_id!r} must clear blockers before declared"
            )
        return self


class DesktopActionLatencyCanarySpec(Strict):
    """Representative desktop ACTION-latency canary contract.

    The read-only no-op canary times snapshot reads (~milliseconds), which is not
    representative of how long a real desktop action takes; deriving an
    action-timeout from it is meaningless. This canary instead measures the
    latency of the target's PRIMARY automation path (``direct_api``) performing a
    *reversible sandbox* round-trip: create then delete a throwaway row on a
    SANDBOX database — never the production board. It produces the real
    action-latency evidence that TTL/action-timeout candidates must be derived
    from.

    Credentials are env references only (no secrets in config); the canary fails
    closed when those env vars are absent. The sandbox database/workspace must be
    distinct from the target's production board, which is named in
    ``forbidden_targets``.
    """
    target_id: str
    surface: Literal["direct_api"]
    allowed_mode: Literal["reversible_sandbox_roundtrip"]
    reversible_action: Literal["create_then_delete_row"]
    sandbox_base_url_env: str
    sandbox_workspace_id_env: str
    sandbox_database_id_env: str
    sandbox_user_env: str
    sandbox_password_env: str
    forbidden_actions: list[str]
    forbidden_targets: list[str]
    measurement_fields: list[Literal[
        "action_create_ms",
        "action_delete_ms",
        "action_roundtrip_ms",
    ]]
    evidence_policy: Literal["redacted_json_only"]
    redaction_policy: Literal["no_raw_content_no_secrets_no_clipboard"]
    human_takeover_policy_ref: str
    production_enabling: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if not _REPO_ID_RE.match(self.target_id):
            raise ValueError(
                f"desktop action latency canary target_id {self.target_id!r} must be stable"
            )
        env_refs = [
            self.sandbox_base_url_env,
            self.sandbox_workspace_id_env,
            self.sandbox_database_id_env,
            self.sandbox_user_env,
            self.sandbox_password_env,
        ]
        for env_name in env_refs:
            if not re.match(r"^[A-Z][A-Z0-9_]*$", env_name):
                raise ValueError(
                    f"desktop action latency canary {self.target_id!r} env ref "
                    f"{env_name!r} is not a valid env name"
                )
        if len(env_refs) != len(set(env_refs)):
            raise ValueError(
                f"desktop action latency canary {self.target_id!r} has duplicate env refs"
            )
        if len(self.forbidden_actions) != len(set(self.forbidden_actions)):
            raise ValueError(
                f"desktop action latency canary {self.target_id!r} has duplicate forbidden_actions"
            )
        missing_denies = _DEFAULT_DESKTOP_DENIES - set(self.forbidden_actions)
        if missing_denies:
            raise ValueError(
                f"desktop action latency canary {self.target_id!r} missing default deny "
                f"action(s): {sorted(missing_denies)}"
            )
        if not self.forbidden_targets:
            raise ValueError(
                f"desktop action latency canary {self.target_id!r} must name the production "
                "board/database in forbidden_targets so the sandbox cannot touch it"
            )
        if len(self.measurement_fields) != len(set(self.measurement_fields)):
            raise ValueError(
                f"desktop action latency canary {self.target_id!r} measurement_fields has duplicates"
            )
        required_measurements = {"action_create_ms", "action_delete_ms", "action_roundtrip_ms"}
        missing = required_measurements - set(self.measurement_fields)
        if missing:
            raise ValueError(
                f"desktop action latency canary {self.target_id!r} missing measurement field(s): "
                f"{sorted(missing)}"
            )
        if not self.human_takeover_policy_ref:
            raise ValueError(
                f"desktop action latency canary {self.target_id!r} needs human_takeover_policy_ref"
            )
        if self.production_enabling:
            raise ValueError(
                f"desktop action latency canary {self.target_id!r} cannot enable production by itself"
            )
        return self


class TelemetryDecision(Strict):
    mode: Literal["structured_events_only", "defer_until_event_contracts", "opentelemetry"]
    decision_basis: list[str]

    @model_validator(mode="after")
    def _checks(self):
        if not self.decision_basis:
            raise ValueError("telemetry.decision_basis must explain the current mode")
        return self


class GitHubAppReview(Strict):
    status: Literal["pending", "approved", "not_required"]
    production_auth_policy: Literal["github_app_required", "not_applicable"]
    pilot_auth_policy: Literal["fine_grained_pat_pilot_only", "not_applicable"]
    requirements: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if self.status == "pending" and not self.requirements:
            raise ValueError("github_app_review pending status must list requirements")
        if self.production_auth_policy != "github_app_required":
            raise ValueError("production repo autonomy must require GitHub App auth")
        return self


_GITHUB_PERMISSION_VALUE = Literal["none", "read", "read_write"]


class GitHubAppAuth(Strict):
    status: Literal["created_pending_verification", "verified", "blocked"]
    app_name: str
    owner: str
    homepage_url: str
    webhook_active: bool = False
    app_id_env: str
    client_id_env: str
    installation_id_env: str
    private_key_path_env: str
    webhook_secret_env: str | None = None
    selected_repositories: list[str]
    allowed_repository_permissions: dict[str, _GITHUB_PERMISSION_VALUE]
    forbidden_repository_permissions: dict[str, Literal["any"]]
    token_storage_policy: Literal[
        "env_refs_only_private_key_outside_repo_short_lived_installation_tokens"
    ]

    @model_validator(mode="after")
    def _checks(self):
        if not self.app_name:
            raise ValueError("github_app_auth.app_name is required")
        if not self.owner:
            raise ValueError("github_app_auth.owner is required")
        if not self.homepage_url.startswith("https://github.com/"):
            raise ValueError("github_app_auth.homepage_url must point at the GitHub owner or repo")
        env_fields = [
            self.app_id_env,
            self.client_id_env,
            self.installation_id_env,
            self.private_key_path_env,
        ]
        if self.webhook_secret_env:
            env_fields.append(self.webhook_secret_env)
        for env_name in env_fields:
            if not re.match(r"^[A-Z][A-Z0-9_]*$", env_name):
                raise ValueError(f"github_app_auth env ref {env_name!r} is not a valid env name")
        if self.webhook_active and not self.webhook_secret_env:
            raise ValueError("active GitHub webhook requires webhook_secret_env")
        if not self.selected_repositories:
            raise ValueError("github_app_auth must list selected_repositories")
        for repo in self.selected_repositories:
            if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
                raise ValueError(
                    f"github_app_auth selected repository {repo!r} must be owner/repo"
                )
        required = {
            "metadata": "read",
            "contents": "read_write",
            "pull_requests": "read_write",
            "checks": "read",
            "statuses": "read",
        }
        for permission, expected in required.items():
            if self.allowed_repository_permissions.get(permission) != expected:
                raise ValueError(
                    "github_app_auth allowed_repository_permissions must include "
                    f"{permission}: {expected}"
                )
        disallowed = {
            "administration",
            "secrets",
            "variables",
            "deployments",
            "environments",
            "workflows",
            "actions",
        }
        missing_forbidden = disallowed - set(self.forbidden_repository_permissions)
        if missing_forbidden:
            raise ValueError(
                "github_app_auth forbidden_repository_permissions missing "
                f"{sorted(missing_forbidden)}"
            )
        if any(value != "any" for value in self.forbidden_repository_permissions.values()):
            raise ValueError("github_app_auth forbidden permissions must use value 'any'")
        return self


class BranchProtectionVerification(Strict):
    status: Literal["blocked", "verified"]
    owner_admin_token_env: str
    selected_repositories: list[str]
    required_status_check_contexts: list[str]
    required_status_check_source_path: str
    required_status_check_source: str
    codeowners_path: str
    required_approving_review_count: int = Field(ge=1)
    required_review_count_source: str
    require_code_owner_reviews: bool = True
    require_force_pushes_disabled: bool = True
    require_deletions_disabled: bool = True
    require_linear_history: bool = True
    require_ruleset_bypass_actors_absent: bool = True
    ruleset_bypass_policy_source: str
    token_policy: Literal["env_ref_only_owner_admin_observer_no_settings_writes"]

    @model_validator(mode="after")
    def _checks(self):
        if not re.match(r"^[A-Z][A-Z0-9_]*$", self.owner_admin_token_env):
            raise ValueError(
                "branch_protection_verification.owner_admin_token_env must be an env ref"
            )
        if not self.selected_repositories:
            raise ValueError("branch_protection_verification must list selected_repositories")
        for repo in self.selected_repositories:
            if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
                raise ValueError(
                    "branch_protection_verification selected repositories must be owner/repo"
                )
        if not self.required_status_check_contexts:
            raise ValueError(
                "branch_protection_verification.required_status_check_contexts must not be empty"
            )
        if len(self.required_status_check_contexts) != len(
            set(self.required_status_check_contexts)
        ):
            raise ValueError(
                "branch_protection_verification.required_status_check_contexts contains duplicates"
            )
        if not self.required_status_check_source:
            raise ValueError("branch protection required check source must be documented")
        if not self.required_status_check_source_path:
            raise ValueError("branch protection required check source path must be documented")
        if not self.required_review_count_source:
            raise ValueError("branch protection review count source must be documented")
        if not self.codeowners_path:
            raise ValueError("branch protection codeowners_path must be documented")
        if self.require_ruleset_bypass_actors_absent and not self.ruleset_bypass_policy_source:
            raise ValueError("branch protection ruleset bypass policy source must be documented")
        return self


class ExternalRuntimeEvaluation(Strict):
    status: Literal["blocked_until_measured_gap", "proposed", "approved_for_spike"]
    candidates: list[str]
    required_gates: list[str]

    @model_validator(mode="after")
    def _checks(self):
        if not self.required_gates:
            raise ValueError("external_runtime_evaluation must list required_gates")
        if self.status == "approved_for_spike" and not self.candidates:
            raise ValueError("approved runtime spikes must name candidate(s)")
        return self


class AutonomyConfig(Strict):
    schema_version: str
    completed_work: list[str] = Field(default_factory=list)
    ordered_work: list[str]
    event_contract: EventContractConfig
    repo_manifests: list[RepoManifest] = Field(default_factory=list)
    desktop_targets: list[DesktopTarget] = Field(default_factory=list)
    completion_verifier: CompletionVerifierConfig
    agent_validation: AgentValidationConfig
    canaries: list[AutonomyCanarySpec] = Field(default_factory=list)
    desktop_noop_canaries: list[DesktopNoopCanarySpec] = Field(default_factory=list)
    desktop_timing_sample_plans: list[DesktopTimingSamplePlan] = Field(default_factory=list)
    desktop_action_latency_canaries: list[DesktopActionLatencyCanarySpec] = Field(
        default_factory=list
    )
    telemetry: TelemetryDecision
    github_app_review: GitHubAppReview
    github_app_auth: GitHubAppAuth
    branch_protection_verification: BranchProtectionVerification
    external_runtime_evaluation: ExternalRuntimeEvaluation

    @model_validator(mode="after")
    def _checks(self):
        if self.schema_version != "command-center.autonomy.v1":
            raise ValueError("schema_version must be command-center.autonomy.v1")
        if not self.ordered_work:
            raise ValueError("autonomy config must declare ordered_work")
        if len(self.completed_work) != len(set(self.completed_work)):
            raise ValueError("autonomy config completed_work contains duplicates")
        if len(self.ordered_work) != len(set(self.ordered_work)):
            raise ValueError("autonomy config ordered_work contains duplicates")
        overlap = set(self.completed_work) & set(self.ordered_work)
        if overlap:
            raise ValueError(
                "autonomy config work item(s) cannot be both completed and ordered: "
                f"{sorted(overlap)}"
            )
        repo_ids = [repo.repo_id for repo in self.repo_manifests]
        if len(repo_ids) != len(set(repo_ids)):
            raise ValueError("duplicate repo manifest ids")
        desktop_ids = [target.target_id for target in self.desktop_targets]
        if len(desktop_ids) != len(set(desktop_ids)):
            raise ValueError("duplicate desktop target ids")
        canary_names = [canary.name for canary in self.canaries]
        if len(canary_names) != len(set(canary_names)):
            raise ValueError("duplicate canary names")
        desktop_noop_ids = [canary.target_id for canary in self.desktop_noop_canaries]
        if len(desktop_noop_ids) != len(set(desktop_noop_ids)):
            raise ValueError("duplicate desktop noop canary target ids")
        unknown_noop_targets = set(desktop_noop_ids) - set(desktop_ids)
        if unknown_noop_targets:
            raise ValueError(
                "desktop noop canary references unknown target(s): "
                f"{sorted(unknown_noop_targets)}"
            )
        action_latency_ids = [
            canary.target_id for canary in self.desktop_action_latency_canaries
        ]
        if len(action_latency_ids) != len(set(action_latency_ids)):
            raise ValueError("duplicate desktop action latency canary target ids")
        unknown_action_targets = set(action_latency_ids) - set(desktop_ids)
        if unknown_action_targets:
            raise ValueError(
                "desktop action latency canary references unknown target(s): "
                f"{sorted(unknown_action_targets)}"
            )
        timing_plan_ids = [plan.target_id for plan in self.desktop_timing_sample_plans]
        if len(timing_plan_ids) != len(set(timing_plan_ids)):
            raise ValueError("duplicate desktop timing sample plan target ids")
        unknown_timing_targets = set(timing_plan_ids) - set(desktop_ids)
        if unknown_timing_targets:
            raise ValueError(
                "desktop timing sample plan references unknown target(s): "
                f"{sorted(unknown_timing_targets)}"
            )
        missing_noop_plan_targets = set(timing_plan_ids) - set(desktop_noop_ids)
        if missing_noop_plan_targets:
            raise ValueError(
                "desktop timing sample plan target(s) lack desktop noop canary: "
                f"{sorted(missing_noop_plan_targets)}"
            )
        event_kinds = {family.kind for family in self.event_contract.families}
        missing_verifier_events = set(self.completion_verifier.required_event_families) - event_kinds
        if missing_verifier_events:
            raise ValueError(
                "completion_verifier references unknown event family/families: "
                f"{sorted(missing_verifier_events)}"
            )
        for target in self.desktop_targets:
            if target.verifier.evidence_event_family not in event_kinds:
                raise ValueError(
                    f"desktop target {target.target_id!r} verifier references unknown "
                    f"event family {target.verifier.evidence_event_family!r}"
                )
        return self


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
    transport: Literal["discord", "slack", "telegram", "whatsapp", "sms"]
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


# ---- assistant-routing.yaml -------------------------------------------------
# Task-category -> Assistant routing policy, per
# docs/architecture/task-assistant-routing.md. VERSION ONE IS PREVIEW-ONLY:
# `default_mode` admits no other value, so the config cannot enable silent
# dispatch even when `enabled` flips true. Frontier model lanes are settings
# behind a chosen Assistant, never Assistant candidates themselves (rule 6).
class AssistantRouteCandidate(Strict):
    assistant_id: str
    preference: int = Field(ge=1)


class AssistantRouteCategory(Strict):
    capability_profile: str
    risk_ceiling: RiskTier
    candidates: list[AssistantRouteCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def _checks(self):
        prefs = [c.preference for c in self.candidates]
        if len(prefs) != len(set(prefs)):
            raise ValueError(
                "duplicate candidate preferences — ties are ambiguous and "
                "rejected, never resolved by guessing (design rule 10)")
        ids = [c.assistant_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate assistant_id in one category")
        return self


class AssistantRoutingUnknownUsage(Strict):
    local_unmetered_gateway: Literal[
        "eligible_with_disclosure", "confirmation_required"]
    agent_or_paid_lane: Literal["confirmation_required"]


class AssistantRoutingEvidence(Strict):
    usage_max_age_seconds: int = Field(ge=1)
    preview_ttl_seconds: int = Field(ge=1)
    unknown_usage: AssistantRoutingUnknownUsage


class AssistantRoutingConfig(Strict):
    schema_version: Literal["command-center.assistant-routing.v1"]
    enabled: bool
    default_mode: Literal["preview_only"]
    evidence: AssistantRoutingEvidence
    categories: dict[str, AssistantRouteCategory] = Field(min_length=1)
    manual_only_model_lanes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        lanes = set(self.manual_only_model_lanes)
        for name, category in self.categories.items():
            for candidate in category.candidates:
                if candidate.assistant_id in lanes:
                    raise ValueError(
                        f"category {name!r}: {candidate.assistant_id!r} is a "
                        "manual-only model lane, not an Assistant — model "
                        "lanes are settings behind a chosen Assistant "
                        "(design rule 6)")
        return self
