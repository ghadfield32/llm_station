"""Command-center config contracts. Edit configs/*.yaml; these validate them."""
from .base import Strict, RiskTier, Decision, Provider, EnvKind
from .contracts import (
    ModelCandidate, ModelRegistry, ExecutorSpec,
    CuratedModelScoutConfig,
    JudgeSpec, JudgeStage, JudgeConfig,
    TierPolicy, GatesConfig,
    EnvironmentSpec, EnvironmentsConfig,
    ProactiveCheck, SelfImprovementScan, ProactiveConfig,
    RepoTarget, DagTarget, DataAssetTarget, ServiceTarget, TargetsConfig,
    KanbanSource, KanbanSection, KanbanConfig,
    ContentSource, ContentStatuses, LinkedInApi, LinkedInAccount, ContentConfig,
    ToolPolicy, ToolsConfig,
    EvalCase, EvalsConfig, EvalSuiteRef,
    StandardsProfile, SkillUpdatePolicy, StandardsConfig, ScoutSpec,
    WebUIConfig, UIConfig,
    BoardStateKnobs, AddressingKnobs, TuningKnobs, AgentSurfaceConfig,
    ChannelSpec, ChannelsConfig,
    MissionOpen, JudgeVerdict,
)

# Map each config file to its top-level contract — used by validate + impact tools.
CONFIG_CONTRACTS = {
    "configs/models.yaml": ModelRegistry,
    "configs/model-scout-curated-openweight.yaml": CuratedModelScoutConfig,
    "configs/judges.yaml": JudgeConfig,
    "configs/gates.yaml": GatesConfig,
    "configs/environments.yaml": EnvironmentsConfig,
    "configs/proactive.yaml": ProactiveConfig,
    "configs/targets.yaml": TargetsConfig,
    "configs/kanban.yaml": KanbanConfig,
    "configs/content.yaml": ContentConfig,
    "configs/tools.yaml": ToolsConfig,
    "configs/evals.yaml": EvalsConfig,
    "configs/standards.yaml": StandardsConfig,
    "configs/ui.yaml": UIConfig,
    "configs/channels.yaml": ChannelsConfig,
    "configs/agent_surface.yaml": AgentSurfaceConfig,
}

# The improvement loop's contracts. Registered here so the same `make validate` /
# `make schema` / `make impact` machinery covers them — editable configs like any other,
# not a parallel system. Imported from improvement.schema (lightweight: it only pulls
# schemas.base + lifecycle, never the heavy discovery/registry package — avoids a cycle).
from ..improvement.schema import (  # noqa: E402
    DiscoveryConfig,
    ImprovementConfig,
    ModelBenchmarksConfig,
)

CONFIG_CONTRACTS["configs/improvement.yaml"] = ImprovementConfig
# Per-target reference experiments (one per target type) — same contract, validated by
# the same `make validate`. Kept separate so the main improvement.yaml stays the worked set.
CONFIG_CONTRACTS["configs/improvement-targets.yaml"] = ImprovementConfig
# The discovery scan's tunable knobs (ranking/triage/code-health/acceptance) — externalized
# so no scan decision is an inline literal.
CONFIG_CONTRACTS["configs/discovery.yaml"] = DiscoveryConfig
CONFIG_CONTRACTS["configs/model-benchmarks.yaml"] = ModelBenchmarksConfig
