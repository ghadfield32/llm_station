"""Command-center config contracts. Edit configs/*.yaml; these validate them."""
from .base import Strict, RiskTier, Decision, Provider, EnvKind
from .contracts import (
    ModelCandidate, ModelRegistry, ExecutorSpec,
    JudgeSpec, JudgeStage, JudgeConfig,
    TierPolicy, GatesConfig,
    EnvironmentSpec, EnvironmentsConfig,
    ProactiveCheck, SelfImprovementScan, ProactiveConfig,
    RepoTarget, DagTarget, DataAssetTarget, ServiceTarget, TargetsConfig,
    KanbanSource, KanbanSection, KanbanConfig,
    ToolPolicy, ToolsConfig,
    EvalCase, EvalsConfig, EvalSuiteRef,
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

# The improvement loop's experiment contract. Registered here so the same
# `make validate` / `make schema` / `make impact` machinery covers it — it is an
# editable config like any other, not a parallel system. Imported after the dict
# to keep the import edge one-directional (improvement.schema -> schemas.base).
from ..improvement.schema import ImprovementConfig  # noqa: E402

CONFIG_CONTRACTS["configs/improvement.yaml"] = ImprovementConfig
# Per-target reference experiments (one per target type) — same contract, validated by
# the same `make validate`. Kept separate so the main improvement.yaml stays the worked set.
CONFIG_CONTRACTS["configs/improvement-targets.yaml"] = ImprovementConfig
