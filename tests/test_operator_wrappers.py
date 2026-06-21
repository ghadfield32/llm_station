"""Friendly operator wrappers (cc onboard / cc setup) — thin sugar, real gates."""
from __future__ import annotations

from pathlib import Path

import yaml

from command_center.cli import onboard, setup

ROOT = Path(__file__).resolve().parents[1]


def _ns(**kw):
    import argparse
    return argparse.Namespace(**kw)


def test_onboard_repo_infers_id_and_blocks_without_remote(tmp_path, capsys):
    # no --remote-url and a path with no git origin -> BLOCKED (no fabricated url)
    rc = onboard._onboard_repo(_ns(path=str(tmp_path), repo_id="", remote_url="",
                                   kanban_board="", apply=False))
    out = capsys.readouterr().out
    assert rc == 1 and "no --remote-url" in out


def test_onboard_repo_dry_run_writes_nothing(tmp_path, capsys, monkeypatch):
    before = (ROOT / "configs/autonomy.yaml").read_text(encoding="utf-8")
    rc = onboard._onboard_repo(_ns(path=str(tmp_path), repo_id="brand_new_repo",
                                   remote_url="https://github.com/x/brand_new_repo.git",
                                   kanban_board="llm_station_command_center", apply=False))
    out = capsys.readouterr().out
    assert "VALIDATED_DRY_RUN" in out
    # dry-run must not mutate the registry
    assert (ROOT / "configs/autonomy.yaml").read_text(encoding="utf-8") == before
    assert rc == 1  # verify still BLOCKED (repo not actually registered)


def test_onboard_kanban_dry_run_validates_then_verify_blocks(capsys):
    rc = onboard._onboard_kanban(_ns(provider="command_center_ui", repo="demo_repo",
                                     board_id="", workspace_ref="", board_ref="",
                                     apply=False))
    out = capsys.readouterr().out
    assert "VALIDATED_DRY_RUN" in out
    # not written yet, so verify can't find the board
    assert "board_not_registered" in out and rc == 1


def test_onboard_kanban_appflowy_requires_env_refs(capsys):
    rc = onboard._onboard_kanban(_ns(provider="appflowy", repo="demo_repo",
                                     board_id="", workspace_ref="", board_ref="",
                                     apply=False))
    out = capsys.readouterr().out
    assert rc == 1 and "env:NAME" in out  # no literal ids; demands env refs


def test_setup_summary_reports_registry_and_activation(capsys, monkeypatch):
    monkeypatch.delenv("KANBAN_EMIT_EVENTS", raising=False)
    setup._summary()
    out = capsys.readouterr().out
    assert "boards:" in out and "repos:" in out
    # emission is the standard path; setup reports its ACTIVE/inactive status
    assert "live-sync emission" in out and ("ACTIVE" in out or "inactive" in out)
    assert "cc onboard repo" in out


def test_setup_returns_doctor_exit_code_unmasked(capsys, monkeypatch):
    # setup must surface doctor's verdict, never mask a failing machine as ready
    monkeypatch.setattr(setup.doctor, "main", lambda: 1)
    rc = setup.main()
    out = capsys.readouterr().out
    assert rc == 1 and "BLOCKED" in out


def test_registry_configs_are_valid():
    from command_center.schemas import AutonomyConfig, KanbanBoardsConfig
    KanbanBoardsConfig.model_validate(
        yaml.safe_load((ROOT / "configs/kanban_boards.yaml").read_text(encoding="utf-8")))
    AutonomyConfig.model_validate(
        yaml.safe_load((ROOT / "configs/autonomy.yaml").read_text(encoding="utf-8")))
