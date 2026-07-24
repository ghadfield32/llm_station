from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from command_center.agent_sessions import policy_builtins, policy_engine, spec_bridge
from command_center.agent_sessions.events import AgentEvent
from command_center.agent_sessions.fake_harness import FakeHarness
from command_center.agent_sessions.policy_engine import ToolAction, evaluate, resolve
from command_center.agent_sessions.protocol import ApprovalDecision, SessionStart
from command_center.agent_sessions.registry import HarnessDescriptor, HarnessRegistry
from command_center.agent_sessions.service import AgentSessionService, PolicyRefusal
from command_center.agent_sessions.store import SessionStore
from command_center.schemas.session_policy import (
    PolicyHandler,
    PolicyLevel,
    PolicyRule,
    PolicySet,
    PolicyVerdict,
    SessionPoliciesConfig,
)
from command_center.usage.schemas import (
    Attribution,
    CostSource,
    SampleKind,
    UsageSample,
    UsageSource,
)
from command_center.usage.service import UsageService
from command_center.usage.store import UsageStore


ASK_HANDLER = PolicyHandler.ASK_ON_OS_TOOLS.value
CALL_CAP_HANDLER = PolicyHandler.MAX_TOOL_CALLS_PER_SESSION.value
COST_HANDLER = PolicyHandler.COST_BUDGET.value


def _rule(handler: PolicyHandler | str, **params) -> PolicyRule:
    return PolicyRule.model_validate({"handler": handler, "params": params})


def _action(
    *, os_tool: bool = False, cost: float | None = None, calls: int = 1,
) -> ToolAction:
    return ToolAction(
        tool_name="Bash" if os_tool else "Read",
        is_os_tool=os_tool,
        estimated_cost_usd=cost,
        session_tool_call_count=calls,
    )


async def _drain(events):
    return [event async for event in events]


def test_schema_yaml_round_trip_and_unknown_key_rejection():
    original = SessionPoliciesConfig.model_validate({
        "schema_version": "command-center.session-policies.v1",
        "policy_sets": [{
            "name": "session-guard",
            "level": "session",
            "rules": [{"handler": ASK_HANDLER, "params": {}, "note": "ask"}],
        }],
    })
    dumped = yaml.safe_dump(original.model_dump(mode="json"))
    assert SessionPoliciesConfig.model_validate(yaml.safe_load(dumped)) == original

    data = original.model_dump(mode="json")
    data["policy_sets"][0]["override"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SessionPoliciesConfig.model_validate(data)


def test_schema_rejects_unknown_handler_and_duplicate_policy_names():
    with pytest.raises(ValidationError, match="Input should be"):
        PolicyRule.model_validate({
            "handler": "some.module.operator_grant", "params": {},
        })

    duplicate = {
        "schema_version": "v1",
        "policy_sets": [
            {"name": "same", "level": "session", "rules": []},
            {"name": "same", "level": "server", "rules": []},
        ],
    }
    with pytest.raises(ValidationError, match="names must be unique"):
        SessionPoliciesConfig.model_validate(duplicate)


@pytest.mark.parametrize(
    "rule",
    [
        {"handler": ASK_HANDLER, "params": {"unexpected": True}},
        {"handler": CALL_CAP_HANDLER, "params": {}},
        {"handler": CALL_CAP_HANDLER, "params": {"limit": -1}},
        {"handler": COST_HANDLER, "params": {}},
        {"handler": COST_HANDLER, "params": {"max_cost_usd": -0.01}},
        {"handler": COST_HANDLER, "params": {
            "max_cost_usd": 10, "ask_thresholds_usd": [-1]}},
        {"handler": COST_HANDLER, "params": {
            "max_cost_usd": 10, "currency": "USD"}},
    ],
)
def test_schema_validates_params_for_each_builtin(rule):
    with pytest.raises(ValidationError):
        PolicyRule.model_validate(rule)


def test_engine_returns_allow_ask_and_deny():
    rules = [
        _rule(PolicyHandler.ASK_ON_OS_TOOLS),
        _rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=3),
    ]
    assert evaluate(rules, _action()).verdict == PolicyVerdict.ALLOW
    assert evaluate(rules, _action(os_tool=True)).verdict == PolicyVerdict.ASK
    assert evaluate(rules, _action(calls=4)).verdict == PolicyVerdict.DENY


def test_engine_declaration_order_deny_short_circuits(monkeypatch):
    def should_not_run(_action):
        raise AssertionError("rule after DENY was evaluated")

    monkeypatch.setitem(
        policy_engine._HANDLERS, PolicyHandler.ASK_ON_OS_TOOLS, should_not_run)
    decision = evaluate([
        _rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=0),
        _rule(PolicyHandler.ASK_ON_OS_TOOLS),
    ], _action(calls=1))
    assert decision.verdict == PolicyVerdict.DENY
    assert decision.rule_index == 0


def test_engine_resolves_stricter_first_across_levels():
    server_allow = PolicySet(
        name="server-allow", level=PolicyLevel.SERVER,
        rules=[_rule(PolicyHandler.ASK_ON_OS_TOOLS)])
    session_deny = PolicySet(
        name="session-deny", level=PolicyLevel.SESSION,
        rules=[_rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=0)])

    decision = resolve([server_allow, session_deny], _action(calls=1))
    assert decision.verdict == PolicyVerdict.DENY
    assert decision.level == PolicyLevel.SESSION
    assert decision.policy_set == "session-deny"


def test_engine_keeps_ask_sticky_across_later_allow_levels():
    session_ask = PolicySet(
        name="session-ask", level=PolicyLevel.SESSION,
        rules=[_rule(PolicyHandler.ASK_ON_OS_TOOLS)])
    server_allow = PolicySet(
        name="server-allow", level=PolicyLevel.SERVER,
        rules=[_rule(PolicyHandler.MAX_TOOL_CALLS_PER_SESSION, limit=100)])
    decision = resolve([server_allow, session_ask], _action(os_tool=True))
    assert decision.verdict == PolicyVerdict.ASK
    assert decision.level == PolicyLevel.SESSION


def test_ask_on_os_tools_builtin():
    assert policy_builtins.ask_on_os_tools(_action()).value == "allow"
    assert policy_builtins.ask_on_os_tools(_action(os_tool=True)).value == "ask"


def test_max_tool_calls_per_session_builtin():
    assert policy_builtins.max_tool_calls_per_session(
        _action(calls=3), limit=3) == PolicyVerdict.ALLOW
    assert policy_builtins.max_tool_calls_per_session(
        _action(calls=4), limit=3) == PolicyVerdict.DENY


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        (None, PolicyVerdict.ALLOW),
        (4.99, PolicyVerdict.ALLOW),
        (5.0, PolicyVerdict.ASK),
        (10.0, PolicyVerdict.ASK),
        (10.01, PolicyVerdict.DENY),
    ],
)
def test_cost_budget_soft_threshold_and_hard_cap(cost, expected):
    assert policy_builtins.cost_budget(
        _action(cost=cost), max_cost_usd=10,
        ask_thresholds_usd=[5]) == expected


def _usage_sample(
    sample_id: str, session_id: str, cost: float | None,
    cost_source: CostSource = CostSource.PROVIDER_REPORTED,
) -> UsageSample:
    return UsageSample(
        sample_id=sample_id,
        runtime_id="claude_agent",
        source=UsageSource.PROVIDER_DERIVED,
        observed_at=f"2026-07-24T00:00:0{sample_id[-1]}+00:00",
        ingested_at="2026-07-24T00:00:10+00:00",
        source_hash=f"hash-{sample_id}",
        sample_kind=SampleKind.REQUEST_DELTA,
        cost_usd=cost,
        cost_source=cost_source,
        attribution=Attribution(agent_session_id=session_id),
    )


def test_cost_budget_reads_canonical_usage_layer_running_total():
    store = UsageStore()
    store.ingest_sample(_usage_sample("s1", "target", 1.25))
    store.ingest_sample(_usage_sample("s2", "target", 2.0))
    store.ingest_sample(_usage_sample("s3", "other", 99.0))
    usage = UsageService(store)

    running_cost = usage.session_cost_usd("target")
    assert running_cost == 3.25
    assert policy_builtins.cost_budget(
        _action(cost=running_cost), max_cost_usd=3.0) == PolicyVerdict.DENY
    assert usage.session_cost_usd("unknown") is None


class _PreDispatchFakeHarness(FakeHarness):
    def __init__(self, store):
        super().__init__(store)
        self.dispatched = False

    async def send(self, session_id: str, prompt: str):
        yield self.store.append_event(
            session_id,
            AgentEvent("tool_requested", {"tool": "Bash", "action": prompt}),
        )
        self.dispatched = True
        yield self.store.append_event(
            session_id, AgentEvent("tool_finished", {"tool": "Bash"}))


def _policy_service(
    monkeypatch, tmp_path: Path, rule: dict, *, enabled: bool,
):
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    (specs_dir / "policy-test.yaml").write_text(yaml.safe_dump({
        "name": "policy-test",
        "instructions": "Use the fake pre-dispatch seam.",
        "harness": "fake",
        "capability_profile": "generalist",
        "mode": "workspace",
        "policy_refs": ["test-policy"],
    }), encoding="utf-8")
    policy_path = tmp_path / "session_policies.yaml"
    policy_path.write_text(yaml.safe_dump({
        "schema_version": "command-center.session-policies.v1",
        "policy_sets": [{
            "name": "test-policy", "level": "session", "rules": [rule],
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(spec_bridge, "AGENT_SESSION_SPECS_DIR", specs_dir)
    monkeypatch.setattr(policy_engine, "SESSION_POLICIES_CONFIG", policy_path)
    monkeypatch.setenv("AGENT_SESSION_SPEC_ENABLED", "1")
    if enabled:
        monkeypatch.setenv("AGENT_SESSION_POLICIES_ENABLED", "1")
    else:
        monkeypatch.delenv("AGENT_SESSION_POLICIES_ENABLED", raising=False)

    store = SessionStore()
    harness = _PreDispatchFakeHarness(store)
    registry = HarnessRegistry([HarnessDescriptor(
        harness_id="fake", label="Fake", production=False,
        supported_modes=("workspace",), factory=lambda: harness,
    )])
    service = AgentSessionService(store=store, registry=registry)
    record = asyncio.run(service.start_session(SessionStart(
        conversation_id="c1", repo_id="r", mode="analysis",
        spec_name="policy-test")))
    return service, store, harness, record.session_id


def test_consumer_flag_off_preserves_fake_harness_path(monkeypatch, tmp_path):
    service, store, harness, session_id = _policy_service(
        monkeypatch, tmp_path,
        {"handler": CALL_CAP_HANDLER, "params": {"limit": 0}},
        enabled=False)
    monkeypatch.setattr(
        policy_engine, "SESSION_POLICIES_CONFIG", tmp_path / "missing.yaml")

    events = asyncio.run(_drain(service.send_message(session_id, "run it")))
    assert [event.type for event in events] == [
        "user_message", "tool_requested", "tool_finished"]
    assert harness.dispatched is True
    assert not any(event.type.startswith("policy_")
                   for event in store.events_since(session_id))


def test_consumer_flag_on_records_deny_and_refuses_dispatch(monkeypatch, tmp_path):
    service, store, harness, session_id = _policy_service(
        monkeypatch, tmp_path,
        {"handler": CALL_CAP_HANDLER, "params": {"limit": 0}},
        enabled=True)

    with pytest.raises(PolicyRefusal) as exc_info:
        asyncio.run(_drain(service.send_message(session_id, "run it")))
    assert exc_info.value.decision.verdict == PolicyVerdict.DENY
    assert harness.dispatched is False
    denial = store.events_since(session_id)[-1]
    assert denial.type == "policy_denied"
    assert denial.payload["policy_set"] == "test-policy"


def test_consumer_flag_on_ask_routes_existing_approval_path(monkeypatch, tmp_path):
    service, store, harness, session_id = _policy_service(
        monkeypatch, tmp_path,
        {"handler": ASK_HANDLER, "params": {}},
        enabled=True)

    events = asyncio.run(_drain(service.send_message(session_id, "run it")))
    assert [event.type for event in events] == [
        "user_message", "tool_requested", "approval_required"]
    assert harness.dispatched is False
    approval_id = events[-1].payload["approval_id"]
    assert store.get_approval(approval_id).status == "pending"

    asyncio.run(service.resolve_approval(
        session_id,
        ApprovalDecision(approval_id=approval_id, approved=True, reason="human"),
    ))
    assert store.get_approval(approval_id).approved is True


def test_checked_in_session_policy_config_validates():
    config = policy_engine.load_policy_config(Path("configs/session_policies.yaml"))
    assert {policy_set.level for policy_set in config.policy_sets} == {
        PolicyLevel.SESSION, PolicyLevel.AGENT, PolicyLevel.SERVER,
    }
    assert {rule.handler for policy_set in config.policy_sets
            for rule in policy_set.rules} == set(PolicyHandler)
