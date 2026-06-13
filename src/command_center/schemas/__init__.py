"""Command-center config contracts. Edit configs/*.yaml; these validate them."""
from .base import Strict, RiskTier, Decision, Provider, EnvKind
from .contracts import (
    ModelCandidate, ModelRegistry, ExecutorSpec,
    JudgeSpec, JudgeStage, JudgeConfig,
    TierPolicy, GatesConfig,
    EnvironmentSpec, EnvironmentsConfig,
    ProactiveCheck, ProactiveConfig,
    RepoTarget, DagTarget, DataAssetTarget, ServiceTarget, TargetsConfig,
    KanbanSource, KanbanSection, KanbanConfig,
    ToolPolicy, ToolsConfig,
    EvalCase, EvalsConfig,
    StandardsProfile, SkillUpdatePolicy, StandardsConfig, ScoutSpec,
    WebUIConfig, UIConfig,
    ChannelSpec, ChannelsConfig,
    MissionOpen, JudgeVerdict,
)

# Map each config file to its top-level contract — used by validate + impact tools.
CONFIG_CONTRACTS = {
    "configs/models.yaml": ModelRegistry,
    "configs/judges.yaml": JudgeConfig,
    "configs/gates.yaml": GatesConfig,
    "configs/environments.yaml": EnvironmentsConfig,
    "configs/proactive.yaml": ProactiveConfig,
    "configs/targets.yaml": TargetsConfig,
    "configs/kanban.yaml": KanbanConfig,
    "configs/tools.yaml": ToolsConfig,
    "configs/evals.yaml": EvalsConfig,
    "configs/standards.yaml": StandardsConfig,
    "configs/ui.yaml": UIConfig,
    "configs/channels.yaml": ChannelsConfig,
}
