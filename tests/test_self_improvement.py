"""Hermetic tests for the daily self-improvement commands (observer/draft-only)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from command_center.cli import self_improvement
from command_center.improvement.discovery.charter import CharterViolation, ObserverCharter
from command_center.improvement.discovery.findings import Finding
from command_center.improvement.discovery.pillars import Pillar
from command_center.improvement.discovery.sources import ScanOutcome
from command_center.improvement.registry import ExperimentRegistry

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def _reg(tmp_path) -> ExperimentRegistry:
    return ExperimentRegistry(db_path=str(tmp_path / "experiments.sqlite"))


def _outcome() -> ScanOutcome:
    finding = Finding(
        pillar=Pillar.CODE_QUALITY, source="code_health",
        title="add a unit test for the retry path",
        claim="retry path is untested", evidence="code_health: branch coverage gap",
        confidence=0.9,
    )
    return ScanOutcome(scanner="code_health", pillar=Pillar.CODE_QUALITY, findings=[finding])


def test_scan_is_observer_only_and_writes_nothing(tmp_path):
    reg = _reg(tmp_path)
    result = self_improvement.run_scan(
        reg=reg, now=NOW, report_path=str(tmp_path / "report.md"), outcomes=[_outcome()])
    assert result["status"] == "observed"
    assert result["applied_code_changes"] is False
    assert result["drafted_ids"] == []          # nothing drafted
    assert result["would_draft_ids"]            # but it would
    assert reg.list_experiments() == []          # registry untouched


def test_daily_draft_kanban_drafts_only_proposed_cards(tmp_path):
    reg = _reg(tmp_path)
    result = self_improvement.run_daily(
        reg=reg, now=NOW, draft_kanban=True, code_apply=False,
        report_path=str(tmp_path / "report.md"), outcomes=[_outcome()])
    assert result["status"] == "drafted"
    assert result["applied_code_changes"] is False
    assert result["drafted_card_ids"]
    experiments = reg.list_experiments()
    assert experiments  # cards landed in the registry
    # human approval is still required: every drafted card is Proposed, never running/promoted
    assert all(e["status"] == "Proposed" for e in experiments)


def test_daily_refuses_to_apply_code_changes(tmp_path):
    reg = _reg(tmp_path)
    result = self_improvement.run_daily(
        reg=reg, now=NOW, draft_kanban=True, code_apply=True, outcomes=[_outcome()])
    assert result["status"] == "blocked"
    assert "code_apply_not_supported_daily_is_observer_draft_only" in result["blockers"]
    assert reg.list_experiments() == []          # refused before any drafting


def test_charter_structurally_forbids_promote_and_merge(tmp_path):
    charter = ObserverCharter(_reg(tmp_path), report_path=str(tmp_path / "r.md"))
    for forbidden in ("promote", "merge", "deploy", "set_status"):
        with pytest.raises(CharterViolation):
            getattr(charter, forbidden)


def test_report_writes_without_drafting(tmp_path):
    reg = _reg(tmp_path)
    result = self_improvement.run_report(
        reg=reg, now=NOW, report_path=str(tmp_path / "report.md"), outcomes=[_outcome()])
    assert result["status"] == "report_written"
    assert (tmp_path / "report.md").is_file()
    assert reg.list_experiments() == []          # report only; no cards drafted
