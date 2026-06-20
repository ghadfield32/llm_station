"""Hermetic tests for the kanban board registry contract + verify/register/sync."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from command_center.cli import kanban_registry
from command_center.schemas.contracts import KanbanBoardSpec, KanbanBoardsConfig

CANONICAL = {
    "backlog": "Backlog", "ready": "Ready", "in_progress": "In Progress",
    "done": "Done", "blocked": "Blocked", "rejected": "Rejected",
    "awaiting_approval": "Awaiting Approval",
}
GRANT = ["add_mission_card", "stage_card", "start_todo", "finish_todo", "block_card", "reject_card"]
WALL = ["approve_card", "merge", "deploy", "delete_card", "delete_board"]


def _board(**over):
    base = dict(
        board_id="b1", provider="appflowy", workspace_ref="env:APPFLOWY_WORKSPACE_ID",
        board_ref="mission_intake", repo_ids=["llm_station"], status_mapping=dict(CANONICAL),
        required_fields=["MissionID", "RepoID", "Risk"], allowed_agent_verbs=list(GRANT),
        forbidden_agent_verbs=list(WALL),
    )
    base.update(over)
    return base


def _write_cfg(tmp_path: Path, boards: list[dict]) -> Path:
    p = tmp_path / "kanban_boards.yaml"
    p.write_text(yaml.safe_dump(
        {"schema_version": "command-center.kanban-boards.v1", "boards": boards}, sort_keys=False),
        encoding="utf-8")
    return p


# ---- schema contract --------------------------------------------------------
def test_valid_board_accepts():
    KanbanBoardSpec(**_board())


def test_appflowy_workspace_ref_must_be_env_reference():
    with pytest.raises(ValueError, match="env reference"):
        KanbanBoardSpec(**_board(workspace_ref="my-workspace-uuid"))


def test_status_mapping_must_be_canonical():
    bad = dict(CANONICAL); bad.pop("blocked")
    with pytest.raises(ValueError, match="missing canonical"):
        KanbanBoardSpec(**_board(status_mapping=bad))


def test_wall_verbs_must_be_forbidden():
    with pytest.raises(ValueError, match="must forbid wall verb"):
        KanbanBoardSpec(**_board(forbidden_agent_verbs=["merge", "deploy"]))


def test_allowed_verbs_cannot_grant_wall_verbs():
    # listing a wall verb as allowed (while it stays forbidden) is rejected as overlap
    with pytest.raises(ValueError, match="both allowed and forbidden"):
        KanbanBoardSpec(**_board(allowed_agent_verbs=[*GRANT, "approve_card"]))


def test_allowed_verbs_must_be_grantable():
    # a verb that is neither grantable nor a wall verb is rejected
    with pytest.raises(ValueError, match="may only grant"):
        KanbanBoardSpec(**_board(allowed_agent_verbs=[*GRANT, "frobnicate"]))


def test_duplicate_board_ids_rejected():
    with pytest.raises(ValueError, match="duplicate kanban board_ids"):
        KanbanBoardsConfig(schema_version="command-center.kanban-boards.v1",
                           boards=[KanbanBoardSpec(**_board()), KanbanBoardSpec(**_board())])


# ---- verify -----------------------------------------------------------------
def test_verify_passes_on_real_registry():
    result = kanban_registry.run_kanban_verify()
    assert result["status"] == "pass"
    assert "llm_station_command_center" in result["boards_verified"]
    assert result["writes_performed"] is False


def test_verify_blocks_when_board_missing(tmp_path):
    cfg = _write_cfg(tmp_path, [_board()])
    result = kanban_registry.run_kanban_verify(config_path=cfg, board_id="nope")
    assert result["status"] == "blocked"
    assert "board_not_registered_nope" in result["blockers"]


def test_verify_snapshot_detects_duplicate_mission_ids_and_secrets(tmp_path):
    cfg = _write_cfg(tmp_path, [_board()])
    snap = tmp_path / "board-snapshot.json"
    snap.write_text(json.dumps({"cards": [
        {"MissionID": "M-1"}, {"MissionID": "M-1"}, {"api_token": "x"},
    ]}), encoding="utf-8")
    result = kanban_registry.run_kanban_verify(config_path=cfg, board_id="b1", snapshot_path=snap)
    assert result["status"] == "blocked"
    joined = " ".join(result["blockers"])
    assert "duplicate_mission_ids" in joined
    assert "unredacted_secret_field_names" in joined


def test_verify_snapshot_not_run_without_snapshot(tmp_path):
    cfg = _write_cfg(tmp_path, [_board()])
    result = kanban_registry.run_kanban_verify(config_path=cfg, board_id="b1")
    assert result["status"] == "pass"
    assert result["board_results"][0]["snapshot_check"]["status"] == "NOT_RUN"


# ---- register / sync --------------------------------------------------------
def test_register_dry_run_validates_without_writing(tmp_path):
    cfg = _write_cfg(tmp_path, [_board()])
    before = cfg.read_text(encoding="utf-8")
    result = kanban_registry.run_kanban_register(
        board_id="b2", provider="command_center_ui", workspace_ref="ui:local",
        board_ref="b2_intake", repo_ids=["other_repo"], config_path=cfg, apply=False)
    assert result["status"] == "validated_dry_run"
    assert cfg.read_text(encoding="utf-8") == before  # no write


def test_register_apply_writes_and_blocks_duplicate(tmp_path):
    cfg = _write_cfg(tmp_path, [_board()])
    result = kanban_registry.run_kanban_register(
        board_id="b2", provider="command_center_ui", workspace_ref="ui:local",
        board_ref="b2_intake", repo_ids=["other_repo"], config_path=cfg, apply=True)
    assert result["status"] == "registered"
    reloaded = KanbanBoardsConfig.model_validate(yaml.safe_load(cfg.read_text(encoding="utf-8")))
    assert {b.board_id for b in reloaded.boards} == {"b1", "b2"}
    dup = kanban_registry.run_kanban_register(
        board_id="b1", provider="appflowy", workspace_ref="env:X", board_ref="x",
        repo_ids=["llm_station"], config_path=cfg, apply=True)
    assert dup["status"] == "blocked"


def test_register_apply_preserves_header_comments_and_existing_boards(tmp_path):
    # registering a board must APPEND, not re-dump the whole file (which would strip
    # the human-authored header comments and reformat existing boards).
    cfg = _write_cfg(tmp_path, [_board()])
    header = "# Provider-agnostic registry — do not lose this comment on register.\n"
    cfg.write_text(header + cfg.read_text(encoding="utf-8"), encoding="utf-8")
    result = kanban_registry.run_kanban_register(
        board_id="b2", provider="command_center_ui", workspace_ref="self",
        board_ref="b2", repo_ids=["other_repo"], config_path=cfg, apply=True)
    assert result["status"] == "registered"
    text = cfg.read_text(encoding="utf-8")
    assert header.strip() in text                      # comment preserved
    reloaded = KanbanBoardsConfig.model_validate(yaml.safe_load(text))
    assert {b.board_id for b in reloaded.boards} == {"b1", "b2"}


def test_sync_dry_run_plans_without_writing(tmp_path):
    cfg = _write_cfg(tmp_path, [_board()])
    result = kanban_registry.run_kanban_sync(config_path=cfg, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["writes_performed"] is False
    assert result["boards"][0]["board_id"] == "b1"


def test_sync_apply_refuses_and_defers_to_bridge(tmp_path):
    cfg = _write_cfg(tmp_path, [_board()])
    result = kanban_registry.run_kanban_sync(config_path=cfg, dry_run=False)
    assert result["status"] == "blocked"
    assert "use_kanban_bridge" in result["blockers"][0]
