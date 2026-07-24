"""Cannot-loosen proofs for the declarative session-policy floor."""
from __future__ import annotations

from itertools import permutations

from command_center.agent_sessions.policy_engine import ToolAction, resolve
from command_center.agent_sessions.store import SessionStore
from command_center.schemas.session_policy import (
    PolicyHandler,
    PolicyLevel,
    PolicyRule,
    PolicySet,
    PolicyVerdict,
)


def _rule(handler: PolicyHandler, **params) -> PolicyRule:
    return PolicyRule(handler=handler, params=params)


ACTION = ToolAction(
    tool_name="Bash", is_os_tool=True, estimated_cost_usd=20,
    session_tool_call_count=2)


def test_permissive_server_allow_cannot_override_session_deny():
    session_deny = PolicySet(
        name="session-deny", level=PolicyLevel.SESSION,
        rules=[_rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=0)])
    later_allows = [
        PolicySet(
            name="agent-allow", level=PolicyLevel.AGENT,
            rules=[_rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=100)]),
        PolicySet(
            name="server-allow", level=PolicyLevel.SERVER,
            rules=[_rule(PolicyHandler.ASK_ON_OS_TOOLS)]),
    ]
    read_action = ToolAction(
        tool_name="Read", is_os_tool=False, estimated_cost_usd=0,
        session_tool_call_count=1)

    for declared_order in permutations([session_deny, *later_allows]):
        decision = resolve(declared_order, read_action)
        assert decision.verdict == PolicyVerdict.DENY
        assert decision.level == PolicyLevel.SESSION


def test_human_only_ask_is_never_auto_allowed_by_another_policy():
    session_ask = PolicySet(
        name="human-wall", level=PolicyLevel.SESSION,
        rules=[_rule(PolicyHandler.ASK_ON_OS_TOOLS)])
    agent_allow = PolicySet(
        name="agent-allow", level=PolicyLevel.AGENT,
        rules=[_rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=100)])
    server_allow = PolicySet(
        name="server-allow", level=PolicyLevel.SERVER,
        rules=[_rule(PolicyHandler.COST_BUDGET, max_cost_usd=1000)])

    decision = resolve([server_allow, agent_allow, session_ask], ACTION)
    assert decision.verdict == PolicyVerdict.ASK
    assert decision.policy_set == "human-wall"

    store = SessionStore()
    session = store.create_session(
        harness="fake", conversation_id="c", repo_id="r",
        permission_profile="read_only")
    approval = store.create_approval(session.session_id, action=ACTION.tool_name)
    assert approval.status == "pending" and approval.approved is None
    store.resolve_approval(
        session.session_id, approval.approval_id,
        approved=True, reason="explicit human decision")
    assert store.get_approval(approval.approval_id).approved is True


def test_read_only_and_destructive_floors_survive_every_policy_verdict():
    store = SessionStore()
    session = store.create_session(
        harness="fake", conversation_id="c", repo_id="r",
        permission_profile="read_only")
    policies = [
        PolicySet(
            name="allow", level=PolicyLevel.SESSION,
            rules=[_rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=100)]),
        PolicySet(
            name="ask", level=PolicyLevel.SESSION,
            rules=[_rule(PolicyHandler.ASK_ON_OS_TOOLS)]),
        PolicySet(
            name="deny", level=PolicyLevel.SESSION,
            rules=[_rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=0)]),
    ]

    assert {resolve([policy], ACTION).verdict for policy in policies} == {
        PolicyVerdict.ALLOW, PolicyVerdict.ASK, PolicyVerdict.DENY,
    }
    # Policy evaluation returns a gate decision only. It has no mutation or
    # capability-grant surface, so one policy or one approval cannot turn a
    # read-only cockpit session into a destructive executor.
    assert store.get(session.session_id).permission_profile == "read_only"
    approval = store.create_approval(session.session_id, action="delete workspace")
    store.resolve_approval(
        session.session_id, approval.approval_id, approved=True,
        reason="one approval is still not a destructive double-agreement")
    assert store.get(session.session_id).permission_profile == "read_only"


def test_policy_language_has_no_grant_or_override_verdict():
    assert {verdict.value for verdict in PolicyVerdict} == {
        "allow", "deny", "ask",
    }
    assert "grant" not in PolicyVerdict.__members__
    assert "override" not in PolicyVerdict.__members__
