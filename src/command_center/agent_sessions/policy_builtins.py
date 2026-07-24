"""Builtin session-policy handlers.

These functions are pure. YAML selects them through the closed ``PolicyHandler``
enum; it never controls an import path.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from command_center.schemas.session_policy import PolicyVerdict

if TYPE_CHECKING:
    from .policy_engine import ToolAction


def ask_on_os_tools(action: ToolAction) -> PolicyVerdict:
    return PolicyVerdict.ASK if action.is_os_tool else PolicyVerdict.ALLOW


def max_tool_calls_per_session(
    action: ToolAction, *, limit: int,
) -> PolicyVerdict:
    if action.session_tool_call_count > limit:
        return PolicyVerdict.DENY
    return PolicyVerdict.ALLOW


def cost_budget(
    action: ToolAction, *, max_cost_usd: float,
    ask_thresholds_usd: Sequence[float] = (),
) -> PolicyVerdict:
    cost = action.estimated_cost_usd
    if cost is None:
        return PolicyVerdict.ALLOW
    if cost > max_cost_usd:
        return PolicyVerdict.DENY
    if any(cost >= threshold for threshold in ask_thresholds_usd):
        return PolicyVerdict.ASK
    return PolicyVerdict.ALLOW
