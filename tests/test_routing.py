"""Routing-contract tests: hard coding escalates cross-provider, never to a local
model, and every judge escalation route resolves to a real model.

The architecture's guarantee against "a local model flailing on hard coding" is
structural, not runtime: coding is executor-driven (Claude Code primary, Codex
fallback), the executor fallback chain spans >=2 provider families, every config
role is local-only, and the judge stuck-escalation stage routes to a stronger
local reviewer whose role actually exists. These tests lock that contract.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from command_center.schemas import ModelRegistry
from command_center.cli.check_cross_refs import (
    check_autonomy_manifest_paths,
    check_gate_routes,
    check_judge_routing,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _registry() -> ModelRegistry:
    raw = yaml.safe_load((REPO_ROOT / "configs/models.yaml").read_text(encoding="utf-8"))
    return ModelRegistry.model_validate(raw)


def _judges() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs/judges.yaml").read_text(encoding="utf-8"))


def _gates() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs/gates.yaml").read_text(encoding="utf-8"))


def test_executor_primary_is_claude_with_codex_cross_provider_fallback():
    ex = sorted(_registry().executors, key=lambda e: e.priority)
    assert ex, "no executors configured"
    primary = ex[0]
    assert primary.priority == 1
    assert primary.name == "claude-code"
    assert primary.family.value == "anthropic"
    # a real fallback exists and is a DIFFERENT provider family — a stalled primary
    # escalates cross-provider, never silently down to a local model
    families = {e.family.value for e in ex}
    assert "openai" in families
    assert len(families) >= 2
    assert any(e.name == "codex-cli" for e in ex)


def test_every_role_candidate_is_local_only():
    # no coding/judging role can silently route to a hosted provider; the executor
    # auth path (Claude/Codex) is the ONLY non-local lane and lives outside roles.
    for role, cands in _registry().roles.items():
        for c in cands:
            assert c.provider.value == "ollama", f"{role}/{c.alias} is not ollama"
            assert c.local is True, f"{role}/{c.alias} is not local"


def test_stuck_escalation_routes_to_a_stronger_existing_local_judge():
    judges = _judges()
    roles = set((_registry().roles or {}).keys())
    stage = next((s for s in judges["stages"] if s["stage"] == "stuck-escalation"), None)
    assert stage is not None, "stuck-escalation stage missing from judges.yaml"
    by_name = {j["name"]: j for j in stage["judges"]}
    detector = by_name["stuck-detector"]
    # the detector escalates a stuck segment to a DIFFERENT, stronger role that exists
    assert detector["escalation_role"] != detector["role_alias"]
    assert detector["escalation_role"] in roles
    assert detector["escalation_role"] == "architect-judge"
    # and the fixer that acts on the stuck segment runs on that stronger role
    assert by_name["segment-fixer"]["role_alias"] == "architect-judge"


def test_all_judge_routes_resolve_against_models_yaml():
    roles = set((_registry().roles or {}).keys())
    assert check_judge_routing(_judges(), roles) == []


def test_all_gate_default_routes_resolve_against_models_yaml():
    roles = set((_registry().roles or {}).keys())
    assert check_gate_routes(_gates(), roles) == []


def test_gate_default_routes_preserve_current_classify_policy():
    tiers = _gates()["tiers"]
    assert tiers["L0_read_only"]["default_route_alias"] == "triage"
    assert tiers["L1_plan_only"]["default_route_alias"] == "planner"
    assert tiers["L2_local_edits"]["default_route_alias"] == "coder"
    assert tiers["L3_external_write"]["default_route_alias"] == "coder"
    assert tiers["L4_dangerous"]["default_route_alias"] == "architect-judge"


def test_check_gate_routes_flags_a_dangling_default_route():
    bad = {"tiers": {"L0_read_only": {"default_route_alias": "ghost-role"}}}
    problems = check_gate_routes(bad, roles={"triage", "architect-judge"})
    assert len(problems) == 1
    assert "ghost-role" in problems[0]
    assert "default_route_alias" in problems[0]


def test_check_gate_routes_flags_a_missing_default_route():
    bad = {"tiers": {"L0_read_only": {}}}
    problems = check_gate_routes(bad, roles={"triage", "architect-judge"})
    assert len(problems) == 1
    assert "missing default_route_alias" in problems[0]


def test_check_judge_routing_flags_a_dangling_escalation():
    bad = {"stages": [{"stage": "x", "judges": [
        {"name": "j1", "role_alias": "triage", "escalation_role": "ghost-role"},
    ]}]}
    problems = check_judge_routing(bad, roles={"triage", "architect-judge"})
    assert len(problems) == 1
    assert "ghost-role" in problems[0]
    assert "escalation_role" in problems[0]


def test_autonomy_manifest_paths_exist_inside_repo():
    autonomy = yaml.safe_load((REPO_ROOT / "configs/autonomy.yaml").read_text(encoding="utf-8"))

    assert check_autonomy_manifest_paths(autonomy, REPO_ROOT) == []


def test_autonomy_manifest_path_check_flags_missing_files(tmp_path):
    autonomy = {
        "repo_manifests": [{
            "repo_id": "example",
            "devcontainer_path": ".devcontainer/devcontainer.json",
            "codeowners_path": ".github/CODEOWNERS",
        }]
    }

    problems = check_autonomy_manifest_paths(autonomy, tmp_path)

    assert len(problems) == 2
    assert all("does not exist" in problem for problem in problems)


def test_autonomy_manifest_path_check_flags_repo_escape(tmp_path):
    autonomy = {
        "repo_manifests": [{
            "repo_id": "example",
            "devcontainer_path": "../outside/devcontainer.json",
        }]
    }

    problems = check_autonomy_manifest_paths(autonomy, tmp_path)

    assert len(problems) == 1
    assert "escapes the repository" in problems[0]
