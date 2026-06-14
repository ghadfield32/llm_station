"""
The self-improvement → Kanban bridge: the scan's top findings become human-gated mission cards
(Backlog, Command Center section, risk mapped to L0–L4). Observer-only — drafts only, never
approves. Hermetic: the card drafter is injected, so no AppFlowy is touched.
"""
from __future__ import annotations

import pytest

from command_center.improvement.discovery import (
    Finding, ObserverCharter, Pillar, ScanPipeline, draft_self_improvement_cards,
)
from command_center.improvement.discovery.kanban import _risk_code
from command_center.improvement.discovery.sources import Scanner
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.schema import TargetType

NOW = "2026-06-13T08:00:00+00:00"


class _Static(Scanner):
    name = "code_health"
    pillar = Pillar.CODE_QUALITY

    def __init__(self, findings):
        self._f = findings

    def scan(self):
        return list(self._f)


def _report(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    charter = ObserverCharter(reg, report_path=tmp_path / "r.md")
    findings = [
        Finding(pillar=Pillar.CODE_QUALITY, source="code_health",
                title="remove swallowed exception in the Discord gateway",
                claim="channels/core.py swallows an exception", evidence="core.py:205",
                confidence=0.85, impact=0.7, suggested_target_type=TargetType.STANDARD),
        Finding(pillar=Pillar.AUTOMATION, source="kanban_cycle_time",
                title="unblock aged card", claim="card blocked 21d", evidence="age=21d",
                confidence=0.7, impact=0.5, unknowns="toil vs dependency"),
    ]
    return ScanPipeline(charter).run([_Static(findings)], date="2026-06-13",
                                     now_iso=NOW, apply=False)


def test_risk_code_maps_tier_to_bare_code():
    assert _risk_code("L2_local_edits") == "L2"
    assert _risk_code("L1_plan_only") == "L1"
    with pytest.raises(ValueError):
        _risk_code("bogus")


def test_draft_cards_are_backlog_command_center_human_gated(tmp_path):
    rep = _report(tmp_path)
    calls = []

    def fake_card(**kw):
        calls.append(kw)
        return f"drafted {len(calls)} card(s) in Backlog; drag to Approved"

    cards = draft_self_improvement_cards(rep, draft_card=fake_card, top_n=2)
    assert len(cards) == 2 and len(calls) == 2
    for kw in calls:
        assert kw["title"].startswith("[self-improve] ")
        assert kw["section"] == "Command Center"        # control-plane self-improvement
        assert kw["risk"] in {"L0", "L1", "L2"}          # bounded, mapped from the finding
        assert kw["priority"] == "P2"
        assert "Evidence:" in kw["acceptance"]
    # the card carries the experiment id for traceability back to the scan
    assert cards[0]["experiment_id"].startswith("EXP-scan-")
    # unknowns flow into acceptance when present (no fabrication when absent)
    assert any("Unknown:" in kw["acceptance"] for kw in calls)


def test_top_n_caps_the_cards(tmp_path):
    rep = _report(tmp_path)
    cards = draft_self_improvement_cards(rep, draft_card=lambda **kw: "ok", top_n=1)
    assert len(cards) == 1                                # only the top finding
