"""
The `improvement scan` touchpoint command — the CLI any operator (or a Kanban/Discord hook)
calls to set the self-improvement loop loose. Dry-run by default; --apply drafts Proposed
cards + one report; feed records are injectable so it runs deterministically offline.
"""
from __future__ import annotations

import argparse
import json

import pytest

from command_center.cli import improvement as cli
from command_center.improvement.registry import ExperimentRegistry


@pytest.fixture
def temp_registry(tmp_path, monkeypatch):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    monkeypatch.setattr(cli, "_registry", lambda: reg)
    return reg


def _args(tmp_path, **kw) -> argparse.Namespace:
    base = dict(apply=False, method="wsjf", feeds="", source=[], max_cards=20,
                report_out=str(tmp_path / "report.md"), show_report=False,
                email=False, email_to="", board=False, ping=False, feature_log="")
    base.update(kw)
    return argparse.Namespace(**base)


def _model_feed(tmp_path) -> str:
    feeds = {"litellm_registry": [
        {"model": "claude-x", "provider": "anthropic", "metric": "accuracy",
         "candidate": 0.92, "incumbent": 0.80, "direction": "increase"}]}
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps(feeds), encoding="utf-8")
    return str(path)


def test_scan_dry_run_default_writes_nothing(tmp_path, temp_registry, capsys):
    rc = cli.cmd_scan(_args(tmp_path, source=["ledger"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert temp_registry.list_experiments() == []
    assert not (tmp_path / "report.md").exists()


def test_scan_apply_drafts_proposed_card_from_feed(tmp_path, temp_registry, capsys):
    rc = cli.cmd_scan(_args(tmp_path, source=["litellm_registry"], feeds=_model_feed(tmp_path),
                            apply=True))
    out = capsys.readouterr().out
    assert rc == 0 and "APPLY" in out
    rows = temp_registry.list_experiments()
    assert len(rows) == 1 and rows[0]["status"] == "Proposed"
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# Daily")


def test_scan_dry_run_with_feed_previews_without_writing(tmp_path, temp_registry, capsys):
    rc = cli.cmd_scan(_args(tmp_path, source=["litellm_registry"], feeds=_model_feed(tmp_path),
                            apply=False, show_report=True))
    out = capsys.readouterr().out
    assert rc == 0 and "would-draft=1" in out
    assert temp_registry.list_experiments() == []      # dry run: nothing persisted
    assert "DRY RUN" in out                             # the rendered report is shown


def test_scan_wired_into_main_parser(tmp_path, temp_registry, monkeypatch, capsys):
    # exercises the REAL parser in main(): `improvement scan --source ledger`
    monkeypatch.setattr("sys.argv", ["improvement", "scan", "--source", "ledger"])
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0 and "DRY-RUN" in out


def test_scan_rejects_unknown_method(monkeypatch):
    # argparse choices guard the ranking method (no silent fallback to a default)
    monkeypatch.setattr("sys.argv", ["improvement", "scan", "--method", "bogus"])
    with pytest.raises(SystemExit):
        cli.main()
