"""Strict contracts for the declarative agent-session policy stack."""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, model_validator

from .base import Strict


class PolicyVerdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PolicyLevel(StrEnum):
    SESSION = "session"
    AGENT = "agent"
    SERVER = "server"


class PolicyHandler(StrEnum):
    """Closed builtin registry keys; policy YAML can never name an import."""

    ASK_ON_OS_TOOLS = (
        "command_center.agent_sessions.policy_builtins.ask_on_os_tools"
    )
    MAX_TOOL_CALLS_PER_SESSION = (
        "command_center.agent_sessions.policy_builtins.max_tool_calls_per_session"
    )
    COST_BUDGET = "command_center.agent_sessions.policy_builtins.cost_budget"


class _AskOnOsToolsParams(Strict):
    pass


class _MaxToolCallsParams(Strict):
    limit: int = Field(ge=0)


_NonNegativeFloat = Annotated[float, Field(ge=0)]


class _CostBudgetParams(Strict):
    max_cost_usd: float = Field(ge=0)
    ask_thresholds_usd: list[_NonNegativeFloat] = Field(default_factory=list)


_HANDLER_PARAMS: dict[PolicyHandler, type[Strict]] = {
    PolicyHandler.ASK_ON_OS_TOOLS: _AskOnOsToolsParams,
    PolicyHandler.MAX_TOOL_CALLS_PER_SESSION: _MaxToolCallsParams,
    PolicyHandler.COST_BUDGET: _CostBudgetParams,
}


class PolicyRule(Strict):
    handler: PolicyHandler
    params: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None

    @model_validator(mode="after")
    def validate_handler_params(self) -> PolicyRule:
        validated = _HANDLER_PARAMS[self.handler].model_validate(self.params)
        object.__setattr__(self, "params", validated.model_dump())
        return self


class PolicySet(Strict):
    name: str = Field(pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    level: PolicyLevel
    rules: list[PolicyRule]


class SessionPoliciesConfig(Strict):
    schema_version: str = Field(min_length=1)
    policy_sets: list[PolicySet]

    @model_validator(mode="after")
    def policy_set_names_are_unique(self) -> SessionPoliciesConfig:
        names = [policy_set.name for policy_set in self.policy_sets]
        if len(names) != len(set(names)):
            raise ValueError("policy_sets names must be unique")
        return self
