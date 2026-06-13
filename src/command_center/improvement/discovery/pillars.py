"""
The nine improvement pillars and how each maps to the 13 target types + its scan sources.

Seven from the addendum (Automation, Structure, Updated Metrics, Code Quality, Rules/Standards,
Data Handling, Full Idea) plus two recommended additions (Reliability/Observability, Cost/FinOps).
Every finding belongs to exactly one pillar, and each pillar resolves to a default target type so
a drafted card enters the existing experiment lifecycle correctly.
"""
from __future__ import annotations

from enum import StrEnum

from ..schema import TargetType


class Pillar(StrEnum):
    AUTOMATION = "automation"                       # toil, schedule gaps, manual steps
    STRUCTURE = "structure"                         # architecture, hotspots, coupling
    UPDATED_METRICS = "updated_metrics"             # models, providers, pricing, benchmarks
    CODE_QUALITY = "code_quality"                   # lint, complexity, dead code, coverage, vulns
    RULES_STANDARDS = "rules_standards"             # coding standards, guardrails, policy
    DATA_HANDLING = "data_handling"                 # schemas, retrieval quality, drift
    FULL_IDEA = "full_idea"                         # net-new capabilities from research
    RELIABILITY_OBSERVABILITY = "reliability_observability"   # error/latency/DORA signals
    COST_FINOPS = "cost_finops"                     # token spend, cost-per-improvement


# pillar -> candidate target types (first is the default for a drafted card)
PILLAR_TARGETS: dict[Pillar, list[TargetType]] = {
    Pillar.AUTOMATION: [TargetType.WORKFLOW, TargetType.PROACTIVE_CHECK],
    Pillar.STRUCTURE: [TargetType.REPOSITORY_TEMPLATE, TargetType.SKILL, TargetType.TOOL],
    Pillar.UPDATED_METRICS: [TargetType.MODEL, TargetType.ROUTING, TargetType.JUDGE],
    Pillar.CODE_QUALITY: [TargetType.REPOSITORY_TEMPLATE, TargetType.TOOL, TargetType.STANDARD],
    Pillar.RULES_STANDARDS: [TargetType.STANDARD, TargetType.DOCUMENTATION, TargetType.JUDGE],
    Pillar.DATA_HANDLING: [TargetType.RETRIEVAL, TargetType.MEMORY],
    Pillar.FULL_IDEA: [TargetType.SKILL, TargetType.TOOL, TargetType.WORKFLOW,
                       TargetType.PROACTIVE_CHECK],
    Pillar.RELIABILITY_OBSERVABILITY: [TargetType.PROACTIVE_CHECK, TargetType.STANDARD,
                                       TargetType.WORKFLOW],
    Pillar.COST_FINOPS: [TargetType.ROUTING, TargetType.MODEL, TargetType.WORKFLOW],
}

# pillar -> the named scan sources that feed it (for the DAG's dynamic task mapping + docs)
PILLAR_SOURCES: dict[Pillar, list[str]] = {
    Pillar.AUTOMATION: ["airflow_metrics", "openlineage", "kanban_cycle_time"],
    Pillar.STRUCTURE: ["codescene", "sonarqube", "radon", "code_health"],
    Pillar.UPDATED_METRICS: ["litellm_registry", "chatbot_arena", "huggingface",
                             "openrouter", "artificial_analysis"],
    Pillar.CODE_QUALITY: ["ruff", "mypy", "semgrep", "bandit", "mutmut", "coverage",
                          "vulture", "pip_audit", "gitleaks", "code_health"],
    Pillar.RULES_STANDARDS: ["semgrep_custom", "ruff_config", "standards_yaml"],
    Pillar.DATA_HANDLING: ["great_expectations", "pandera", "evidently", "ledger_runs"],
    Pillar.FULL_IDEA: ["arxiv", "semantic_scholar", "papers_with_code"],
    Pillar.RELIABILITY_OBSERVABILITY: ["prometheus", "openlineage", "incident_log", "ledger"],
    Pillar.COST_FINOPS: ["litellm_spend", "provider_billing", "ledger"],
}


def target_for(pillar: Pillar) -> TargetType:
    """The default target type a drafted card uses for this pillar."""
    return PILLAR_TARGETS[pillar][0]
