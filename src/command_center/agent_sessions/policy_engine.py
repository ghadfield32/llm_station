"""Pure, monotone evaluation for declarative agent-session policies."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from command_center.schemas.session_policy import (
    PolicyHandler,
    PolicyLevel,
    PolicyRule,
    PolicySet,
    PolicyVerdict,
    SessionPoliciesConfig,
)

from . import policy_builtins


SESSION_POLICIES_CONFIG = Path("configs/session_policies.yaml")
_LEVEL_ORDER = (PolicyLevel.SESSION, PolicyLevel.AGENT, PolicyLevel.SERVER)
_HANDLERS = {
    PolicyHandler.ASK_ON_OS_TOOLS: policy_builtins.ask_on_os_tools,
    PolicyHandler.MAX_TOOL_CALLS_PER_SESSION:
        policy_builtins.max_tool_calls_per_session,
    PolicyHandler.COST_BUDGET: policy_builtins.cost_budget,
}


@dataclass(frozen=True)
class ToolAction:
    tool_name: str
    is_os_tool: bool
    estimated_cost_usd: float | None
    session_tool_call_count: int
    author_harness: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("tool_name must not be blank")
        if self.estimated_cost_usd is not None and self.estimated_cost_usd < 0:
            raise ValueError("estimated_cost_usd must be non-negative")
        if self.session_tool_call_count < 0:
            raise ValueError("session_tool_call_count must be non-negative")
        if self.author_harness is not None and not self.author_harness.strip():
            raise ValueError("author_harness must not be blank")
        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("session_id must not be blank")
        if (self.author_harness is None) != (self.session_id is None):
            raise ValueError(
                "author_harness and session_id must be supplied together")


@dataclass(frozen=True)
class PolicyDecision:
    verdict: PolicyVerdict
    level: PolicyLevel | None = None
    policy_set: str | None = None
    rule_index: int | None = None
    handler: PolicyHandler | None = None
    note: str | None = None


def evaluate(
    rules_in_level_order: Iterable[PolicyRule], action: ToolAction,
) -> PolicyDecision:
    """Evaluate declaration order: first DENY wins; ASK is otherwise sticky."""
    first_ask: PolicyDecision | None = None
    for index, rule in enumerate(rules_in_level_order):
        verdict = _HANDLERS[rule.handler](action, **rule.params)
        decision = PolicyDecision(
            verdict=verdict, rule_index=index, handler=rule.handler,
            note=rule.note)
        if verdict == PolicyVerdict.DENY:
            return decision
        if verdict == PolicyVerdict.ASK and first_ask is None:
            first_ask = decision
    return first_ask or PolicyDecision(PolicyVerdict.ALLOW)


def resolve(
    policy_sets: Iterable[PolicySet], action: ToolAction,
) -> PolicyDecision:
    """Resolve session -> agent -> server without any grant/override operation."""
    declared = list(policy_sets)
    first_ask: PolicyDecision | None = None
    for level in _LEVEL_ORDER:
        for policy_set in declared:
            if policy_set.level != level:
                continue
            decision = evaluate(policy_set.rules, action)
            decision = replace(
                decision, level=level, policy_set=policy_set.name)
            if decision.verdict == PolicyVerdict.DENY:
                return decision
            if decision.verdict == PolicyVerdict.ASK and first_ask is None:
                first_ask = decision
    return first_ask or PolicyDecision(PolicyVerdict.ALLOW)


def load_policy_config(path: Path | None = None) -> SessionPoliciesConfig:
    """Load on demand so config changes and test monkeypatches are immediate."""
    config_path = path if path is not None else SESSION_POLICIES_CONFIG
    with config_path.open(encoding="utf-8") as handle:
        return SessionPoliciesConfig.model_validate(yaml.safe_load(handle))


def select_policy_sets(
    config: SessionPoliciesConfig, policy_refs: Iterable[str],
) -> list[PolicySet]:
    """Resolve references in declaration order and fail loudly on a dangling ref."""
    by_name = {policy_set.name: policy_set for policy_set in config.policy_sets}
    selected: list[PolicySet] = []
    for ref in policy_refs:
        try:
            selected.append(by_name[ref])
        except KeyError as exc:
            raise KeyError(f"unknown agent-session policy reference: {ref!r}") from exc
    return selected
