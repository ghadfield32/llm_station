"""Hermetic tests for repo registration + autonomy gates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from command_center.cli import repo_registry
from command_center.schemas.contracts import RepoManifest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _base_autonomy() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs/autonomy.yaml").read_text(encoding="utf-8"))


def _scaffold(tmp_path: Path, *, autonomy: dict, board_repo_ids=("llm_station",),
              evidence_pass=True, devcontainer=True, codeowners=True) -> Path:
    """Build a tmp repo root with the files the gates check."""
    (tmp_path / "configs").mkdir(parents=True)
    (tmp_path / "configs/autonomy.yaml").write_text(yaml.safe_dump(autonomy), encoding="utf-8")
    (tmp_path / "configs/kanban_boards.yaml").write_text(yaml.safe_dump({
        "schema_version": "command-center.kanban-boards.v1",
        "boards": [{
            "board_id": "llm_station_command_center", "provider": "appflowy",
            "workspace_ref": "env:APPFLOWY_WORKSPACE_ID", "board_ref": "mission_intake",
            "repo_ids": list(board_repo_ids),
            "status_mapping": {k: k.title() for k in
                               ["backlog", "ready", "in_progress", "done", "blocked",
                                "rejected", "awaiting_approval"]},
            "required_fields": ["MissionID"],
            "allowed_agent_verbs": ["add_mission_card"],
            "forbidden_agent_verbs": ["approve_card", "merge", "deploy", "delete_card", "delete_board"],
        }],
    }), encoding="utf-8")
    if devcontainer:
        (tmp_path / ".devcontainer").mkdir()
        (tmp_path / ".devcontainer/devcontainer.json").write_text("{}", encoding="utf-8")
    if codeowners:
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github/CODEOWNERS").write_text("* @ghadfield32\n", encoding="utf-8")
    ev = tmp_path / repo_registry.RUN_ID_DIR
    ev.mkdir(parents=True)
    status = "pass" if evidence_pass else "blocked"
    (ev / "branch-mission.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    (ev / "pr-check-loop.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    return tmp_path / "configs/autonomy.yaml"


def test_verify_passes_for_fully_gated_repo(tmp_path):
    cfg = _scaffold(tmp_path, autonomy=_base_autonomy())
    result = repo_registry.run_repo_verify(repo_id="llm_station", config_path=cfg, root=tmp_path)
    assert result["status"] == "pass", result["blockers"]


def test_verify_blocks_on_missing_devcontainer(tmp_path):
    cfg = _scaffold(tmp_path, autonomy=_base_autonomy(), devcontainer=False)
    result = repo_registry.run_repo_verify(repo_id="llm_station", config_path=cfg, root=tmp_path)
    assert result["status"] == "blocked"
    assert "llm_station:devcontainer_present" in result["blockers"]


def test_verify_blocks_on_missing_codeowners(tmp_path):
    cfg = _scaffold(tmp_path, autonomy=_base_autonomy(), codeowners=False)
    result = repo_registry.run_repo_verify(repo_id="llm_station", config_path=cfg, root=tmp_path)
    assert "llm_station:codeowners_present" in result["blockers"]


def test_verify_blocks_on_missing_kanban_board_mapping(tmp_path):
    # board exists but does not list this repo -> mapping fails
    cfg = _scaffold(tmp_path, autonomy=_base_autonomy(), board_repo_ids=("other",))
    result = repo_registry.run_repo_verify(repo_id="llm_station", config_path=cfg, root=tmp_path)
    assert "llm_station:kanban_board_mapping" in result["blockers"]


def test_verify_blocks_when_pr_check_evidence_missing(tmp_path):
    cfg = _scaffold(tmp_path, autonomy=_base_autonomy(), evidence_pass=False)
    result = repo_registry.run_repo_verify(repo_id="llm_station", config_path=cfg, root=tmp_path)
    assert "llm_station:pr_check_evidence_proven" in result["blockers"]
    assert "llm_station:branch_mission_proven" in result["blockers"]


def test_verify_blocks_when_github_app_not_installed_for_repo(tmp_path):
    raw = _base_autonomy()
    raw["github_app_auth"]["selected_repositories"] = ["ghadfield32/other"]
    cfg = _scaffold(tmp_path, autonomy=raw)
    result = repo_registry.run_repo_verify(repo_id="llm_station", config_path=cfg, root=tmp_path)
    assert "llm_station:github_app_installed" in result["blockers"]


def test_verify_blocks_when_branch_protection_unverified(tmp_path):
    # github_branch_protection posture (default): the server-side attestation gates
    raw = _base_autonomy()
    raw["branch_protection_verification"]["status"] = "blocked"
    cfg = _scaffold(tmp_path, autonomy=raw)
    result = repo_registry.run_repo_verify(repo_id="llm_station", config_path=cfg, root=tmp_path)
    assert "llm_station:merge_wall_verified" in result["blockers"]


def test_enable_autonomy_refuses_when_gates_block(tmp_path):
    cfg = _scaffold(tmp_path, autonomy=_base_autonomy(), devcontainer=False)
    result = repo_registry.run_repo_enable_autonomy(repo_id="llm_station", config_path=cfg,
                                                    root=tmp_path, apply=True)
    assert result["status"] == "blocked"
    assert any("devcontainer_present" in b for b in result["blockers"])


# ---- external repo: gates must check the TARGET repo, not the control repo ---
def test_external_repo_gates_check_target_not_control_repo(tmp_path):
    from command_center.schemas import AutonomyConfig, KanbanBoardsConfig
    # control repo (root) HAS codeowners, devcontainer, and passing loop evidence
    control = _scaffold(tmp_path, autonomy=_base_autonomy())  # writes those into tmp_path
    cfg = AutonomyConfig.model_validate(yaml.safe_load(control.read_text(encoding="utf-8")))
    # external repo: a devcontainer but NO codeowners and NO per-repo evidence
    ext = tmp_path / "external_repo"
    (ext / ".devcontainer").mkdir(parents=True)
    (ext / ".devcontainer/devcontainer.json").write_text("{}", encoding="utf-8")
    boards = KanbanBoardsConfig.model_validate(yaml.safe_load(
        (tmp_path / "configs/kanban_boards.yaml").read_text(encoding="utf-8")))
    boards.boards[0].repo_ids.append("ext")
    repo = RepoManifest(**_manifest(repo_id="ext", local_path_ref="env:EXT_PATH",
                                    kanban_board_id="llm_station_command_center",
                                    autonomous_edits_enabled=False,
                                    blockers=["onboarding_incomplete"]))

    res = repo_registry.verify_repo(repo=repo, cfg=cfg, boards=boards, root=tmp_path,
                                    env={"EXT_PATH": str(ext)})
    g = {x["check"]: x["status"] for x in res["gates"]}
    # the external repo's OWN files/evidence decide — not the control repo's
    assert g["devcontainer_present"] == "PASS"        # ext has one
    assert g["codeowners_present"] == "BLOCKED"       # ext has none (control does)
    # external repos' bounded loop is proven by the LIVE PR-check loop (binding);
    # branch-mission (local CI smoke) is not applicable to an external repo
    assert g["pr_check_evidence_proven"] != "PASS"    # no per-repo evidence yet (binding)
    assert g["branch_mission_proven"] == "PASS"       # not_applicable_external_repo
    assert g["local_path_ref_resolves"] == "PASS"

    # env unset -> target path unresolved -> file gates cannot verify -> blocked
    res2 = repo_registry.verify_repo(repo=repo, cfg=cfg, boards=boards, root=tmp_path, env={})
    g2 = {x["check"]: x["status"] for x in res2["gates"]}
    assert g2["local_path_ref_resolves"] == "BLOCKED"
    assert g2["devcontainer_present"] == "BLOCKED"


def test_local_merge_wall_posture_verifies_the_guard(tmp_path):
    import subprocess
    from command_center.cli import merge_guard
    from command_center.schemas import AutonomyConfig, KanbanBoardsConfig
    control = _scaffold(tmp_path, autonomy=_base_autonomy())
    cfg = AutonomyConfig.model_validate(yaml.safe_load(control.read_text(encoding="utf-8")))
    boards = KanbanBoardsConfig.model_validate(yaml.safe_load(
        (tmp_path / "configs/kanban_boards.yaml").read_text(encoding="utf-8")))
    boards.boards[0].repo_ids.append("ext")
    # external repo with devcontainer + codeowners so only the wall gate varies
    ext = tmp_path / "ext_repo"
    (ext / ".devcontainer").mkdir(parents=True)
    (ext / ".devcontainer/devcontainer.json").write_text("{}", encoding="utf-8")
    (ext / ".github").mkdir()
    (ext / ".github/CODEOWNERS").write_text("* @ghadfield32\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(ext)], check=True)
    repo = RepoManifest(**_manifest(
        repo_id="ext", local_path_ref="env:EXT_PATH",
        kanban_board_id="llm_station_command_center",
        merge_wall="local_pre_push_and_human_merge",
        autonomous_edits_enabled=False, blockers=["onboarding_incomplete"]))

    # no guard installed yet -> the local merge-wall gate BLOCKS (not faked as pass)
    res = repo_registry.verify_repo(repo=repo, cfg=cfg, boards=boards, root=tmp_path,
                                    env={"EXT_PATH": str(ext)})
    g = {x["check"]: x["status"] for x in res["gates"]}
    assert g["merge_wall_verified"] == "BLOCKED"

    # install the real guard -> the gate PASSES (lower assurance, recorded)
    merge_guard._hook_path(ext).write_text(merge_guard.guard_hook(["main"]), encoding="utf-8")
    res2 = repo_registry.verify_repo(repo=repo, cfg=cfg, boards=boards, root=tmp_path,
                                     env={"EXT_PATH": str(ext)})
    g2 = {x["check"]: x for x in res2["gates"]}
    assert g2["merge_wall_verified"]["status"] == "PASS"
    assert "local_pre_push_and_human_merge" in g2["merge_wall_verified"]["detail"]


# ---- schema invariants ------------------------------------------------------
def _manifest(**over):
    base = dict(
        repo_id="r1", remote_url="https://github.com/x/r1.git", default_branch="main",
        protected_branches=["main"], allowed_base_branches=["main"],
        branch_write_policy="feature_branch_only", auth_mode="github_app",
        execution_mode="devcontainer", devcontainer_path=".devcontainer/devcontainer.json",
        ci_commands=["uv run cc validate"], secret_policy="no_runtime_secrets_inside_container",
        codeowners_required=True, codeowners_path=".github/CODEOWNERS",
        risk_ceiling="L2_local_edits", kanban_board_id="b1", local_path_ref="self",
        autonomous_edits_enabled=True, blockers=[],
    )
    base.update(over)
    return base


def test_enabled_manifest_requires_kanban_board_id():
    with pytest.raises(ValueError, match="require a kanban_board_id"):
        RepoManifest(**_manifest(kanban_board_id=None))


def test_enabled_manifest_requires_local_path_ref():
    with pytest.raises(ValueError, match="require a local_path_ref"):
        RepoManifest(**_manifest(local_path_ref=None))


def test_local_path_ref_rejects_absolute_path():
    with pytest.raises(ValueError, match="local_path_ref must be"):
        RepoManifest(**_manifest(local_path_ref="C:/Users/example/repo"))


def test_register_dry_run_does_not_write_and_blocks_duplicate(tmp_path):
    cfg = _scaffold(tmp_path, autonomy=_base_autonomy())
    before = cfg.read_text(encoding="utf-8")
    ok = repo_registry.run_repo_register(
        repo_id="newrepo", local_path="C:/x/newrepo",
        remote_url="https://github.com/x/newrepo.git", kanban_board="llm_station_command_center",
        config_path=cfg, root=tmp_path, apply=False)
    assert ok["status"] == "validated_dry_run"
    assert cfg.read_text(encoding="utf-8") == before
    dup = repo_registry.run_repo_register(
        repo_id="llm_station", local_path="C:/x", remote_url="https://github.com/x/llm.git",
        kanban_board="llm_station_command_center", config_path=cfg, root=tmp_path, apply=False)
    assert dup["status"] == "blocked"
