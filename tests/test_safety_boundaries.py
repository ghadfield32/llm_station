"""Non-negotiable safety boundaries (mission section 2).

These assert the structural walls still hold AFTER the improvement loop was added —
both the pre-existing ones (L3/L4 approval, repo_task isolation, forbidden tool
actions, kanban can't approve, proactive caps at L2) and the new ones (experiments
cap at L2, no component promotes itself). Pure contract checks: deterministic, offline.
"""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError

from command_center.schemas import (
    GatesConfig, EnvironmentsConfig, ToolsConfig, KanbanConfig, ProactiveConfig,
)
from command_center.improvement.lifecycle import (
    Actor, ExperimentStatus as S, TransitionConditions, validate_transition,
    HumanApprovalRequired,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _cfg(name):
    return yaml.safe_load((REPO_ROOT / "configs" / name).read_text(encoding="utf-8"))


# ---- 3-4. L3/L4 require approval (gates.yaml) -------------------------------

def test_shipped_gates_keep_l3_l4_approval():
    g = GatesConfig.model_validate(_cfg("gates.yaml"))
    from command_center.schemas import RiskTier
    assert g.tiers[RiskTier.L3].requires_approval
    assert g.tiers[RiskTier.L4].requires_approval and not g.tiers[RiskTier.L4].auto


def test_gates_reject_l3_without_approval():
    bad = _cfg("gates.yaml")
    bad["tiers"]["L3_external_write"]["requires_approval"] = False
    with pytest.raises(ValidationError):
        GatesConfig.model_validate(bad)


# ---- 7. repo_task environments are ephemeral + secret-free ------------------

def test_repo_task_secret_bearing_rejected():
    bad = _cfg("environments.yaml")
    repo_task = next(e for e in bad["environments"] if e["kind"] == "repo_task")
    repo_task["allowed_secrets"] = ["OPENAI_API_KEY"]
    with pytest.raises(ValidationError):
        EnvironmentsConfig.model_validate(bad)


def test_repo_task_persistent_rejected():
    bad = _cfg("environments.yaml")
    repo_task = next(e for e in bad["environments"] if e["kind"] == "repo_task")
    repo_task["persistent"] = True
    with pytest.raises(ValidationError):
        EnvironmentsConfig.model_validate(bad)


# ---- 5. forbidden tool actions never auto-allowed --------------------------

def test_tools_reject_forbidden_auto_action():
    bad = _cfg("tools.yaml")
    first = next(iter(bad["tools"]))
    bad["tools"][first].setdefault("allowed_l2", []).append("merge")
    with pytest.raises(ValidationError):
        ToolsConfig.model_validate(bad)


# ---- 1. kanban sections cannot auto-approve above L2 ------------------------

def test_kanban_section_cannot_exceed_l2():
    bad = _cfg("kanban.yaml")
    bad["sections"][0]["max_auto_risk"] = "L3_external_write"
    with pytest.raises(ValidationError):
        KanbanConfig.model_validate(bad)


# ---- 14. proactive checks cap at L2 ----------------------------------------

def test_proactive_check_cannot_exceed_l2():
    bad = _cfg("proactive.yaml")
    bad["runtime_checks"][0]["auto_patch_max_risk"] = "L3_external_write"
    with pytest.raises(ValidationError):
        ProactiveConfig.model_validate(bad)


# ---- 15. no component may promote itself (lifecycle) ------------------------

def _ready() -> TransitionConditions:
    return TransitionConditions(deterministic_passed=True, verification_present=True,
                                verification_verdict="PASS", independent_verifier_distinct=True,
                                human_approval=True, rollback_demonstrated=True)


def test_agent_cannot_promote():
    for dst in (S.CANARY, S.PROMOTED):
        with pytest.raises(HumanApprovalRequired):
            validate_transition(
                S.AWAITING_HUMAN_PROMOTION if dst == S.CANARY else S.CANARY,
                dst, actor=Actor.AGENT, conditions=_ready())


# ---- 8-9. deterministic-first gate (verdict can't override det failure) ----

def test_model_verdict_cannot_override_deterministic_failure():
    from command_center.improvement.lifecycle import GateNotSatisfied
    cond = TransitionConditions(deterministic_passed=False, verification_present=True,
                                verification_verdict="PASS", independent_verifier_distinct=True)
    with pytest.raises(GateNotSatisfied):
        validate_transition(S.VERIFIED, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT,
                            conditions=cond)
