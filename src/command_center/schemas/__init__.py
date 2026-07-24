"""Command-center config contracts. Edit configs/*.yaml; these validate them."""
from .base import Strict, RiskTier, Decision, Provider, EnvKind
from .agent_session_spec import (
    AgentEffort, AgentHarnessId, AgentSessionSpec, CapabilityProfile,
)
from .contracts import (
    ModelCandidate, ModelRegistry, ExecutorSpec,
    CuratedModelScoutConfig,
    WatchlistBenchmark, WatchlistLocalArtifact, ModelWatchlistRecord, ModelWatchlistConfig,
    FrontierRouterProvider, FrontierRouterCandidate, FrontierRouterModel,
    FrontierRouterPriceFreshness,
    FrontierRouterProvidersConfig, FrontierRouterBudgetPolicy, FrontierRouterBudgetsConfig,
    UsageThresholds, UsagePolling, UsageRouting, UsageAlertChannels, UsageRetention,
    UsageMonitoringConfig,
    LocalFrontierCapabilities, LocalFrontierProvider, LocalFrontierThroughputEstimate,
    LocalFrontierModel, LocalFrontierProvidersConfig,
    FrameworkEvalSpec, FrameworkEvalsConfig,
    KNOWN_SCOUT_SOURCES,
    JudgeSpec, JudgeStage, JudgeConfig,
    TierPolicy, GatesConfig,
    EnvironmentSpec, EnvironmentsConfig,
    ProactiveCheck, SelfImprovementScan, ProactiveConfig,
    RepoTarget, DagTarget, DataAssetTarget, ServiceTarget, TargetsConfig,
    KanbanSource, KanbanSection, KanbanConfig,
    KanbanBoardSpec, KanbanBoardsConfig,
    DomainFieldSpec, DomainEmptyState, DomainSurfaceSpec, DomainSurfacesConfig,
    MemoryRecord, MemoryConfig,
    ContentSource, ContentStatuses, LinkedInApi, LinkedInAccount, ContentConfig,
    ContentStream, ContentViewpoint, ContentPipelineConfig,
    ContentModelPrice, ContentLLMPolicy, ContentLLMRouting,
    ReferenceItem, ContentReferenceConfig,
    ToolPolicy, ToolsConfig,
    CapabilityTrust, CapabilityProvenance, CapabilityEntry, CapabilityCatalogConfig,
    EvalCase, EvalsConfig, EvalSuiteRef,
    StandardsProfile, SkillUpdatePolicy, StandardsConfig, ScoutSpec,
    WebUIConfig, UIConfig,
    BoardStateKnobs, AddressingKnobs, TuningKnobs, AgentSurfaceConfig,
    EventFamilySpec, EventContractConfig, RepoManifest, DesktopVerifierSpec,
    DesktopTarget, CompletionVerifierConfig, AgentValidationConfig, AutonomyCanarySpec,
    DesktopNoopCanarySpec, DesktopTimingSamplePlan, DesktopActionLatencyCanarySpec,
    TelemetryDecision, GitHubAppReview, GitHubAppAuth, BranchProtectionVerification,
    ExternalRuntimeEvaluation, AutonomyConfig,
    ChannelSpec, ChannelsConfig,
    MissionOpen, JudgeVerdict,
)
from .contracts import AssistantRoutingConfig
from ..job_search.schemas import JobSearchConfig

# Map each config file to its top-level contract — used by validate + impact tools.
CONFIG_CONTRACTS = {
    "configs/models.yaml": ModelRegistry,
    "configs/model-scout-curated-openweight.yaml": CuratedModelScoutConfig,
    "configs/model-scout-watchlist.yaml": ModelWatchlistConfig,
    "configs/frontier-router-providers.yaml": FrontierRouterProvidersConfig,
    "configs/frontier-router-budgets.yaml": FrontierRouterBudgetsConfig,
    "configs/usage-monitoring.yaml": UsageMonitoringConfig,
    "configs/local-frontier-providers.yaml": LocalFrontierProvidersConfig,
    "configs/framework-evals.yaml": FrameworkEvalsConfig,
    "configs/judges.yaml": JudgeConfig,
    "configs/gates.yaml": GatesConfig,
    "configs/environments.yaml": EnvironmentsConfig,
    "configs/proactive.yaml": ProactiveConfig,
    "configs/targets.yaml": TargetsConfig,
    "configs/kanban.yaml": KanbanConfig,
    "configs/kanban_boards.yaml": KanbanBoardsConfig,
    "configs/domain_surfaces.yaml": DomainSurfacesConfig,
    "configs/memory.yaml": MemoryConfig,
    "configs/content.yaml": ContentConfig,
    "configs/content_pipeline.yaml": ContentPipelineConfig,
    "configs/content_reference.yaml": ContentReferenceConfig,
    "configs/tools.yaml": ToolsConfig,
    "configs/capabilities.yaml": CapabilityCatalogConfig,
    "configs/evals.yaml": EvalsConfig,
    "configs/standards.yaml": StandardsConfig,
    "configs/ui.yaml": UIConfig,
    "configs/channels.yaml": ChannelsConfig,
    "configs/agent_surface.yaml": AgentSurfaceConfig,
    "configs/autonomy.yaml": AutonomyConfig,
    "configs/job_search.yaml": JobSearchConfig,
    "configs/assistant-routing.yaml": AssistantRoutingConfig,
}

# The improvement loop's contracts. Registered here so the same `make validate` /
# `make schema` / `make impact` machinery covers them — editable configs like any other,
# not a parallel system. Imported from improvement.schema (lightweight: it only pulls
# schemas.base + lifecycle, never the heavy discovery/registry package — avoids a cycle).
from ..improvement.schema import (  # noqa: E402
    DiscoveryConfig,
    ImprovementConfig,
    ModelBenchmarksConfig,
    ServingBenchmarksConfig,
)

CONFIG_CONTRACTS["configs/improvement.yaml"] = ImprovementConfig
# Per-target reference experiments (one per target type) — same contract, validated by
# the same `make validate`. Kept separate so the main improvement.yaml stays the worked set.
CONFIG_CONTRACTS["configs/improvement-targets.yaml"] = ImprovementConfig
# The discovery scan's tunable knobs (ranking/triage/code-health/acceptance) — externalized
# so no scan decision is an inline literal.
CONFIG_CONTRACTS["configs/discovery.yaml"] = DiscoveryConfig
CONFIG_CONTRACTS["configs/model-benchmarks.yaml"] = ModelBenchmarksConfig
CONFIG_CONTRACTS["configs/model-serving-benchmarks.yaml"] = ServingBenchmarksConfig
