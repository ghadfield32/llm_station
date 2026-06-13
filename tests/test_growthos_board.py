"""Growth OS / AppFlowy board upsert logic, tested with a FAKE client.

The clobber-safe projection is what matters and it is fully tested here; only the real
network call to AppFlowy needs a reachable server (that thin wrapper is the one untested
line). Proves: human-owned fields survive an agent re-sync, agent rows land non-approved,
and dry-run writes nothing.
"""
from __future__ import annotations

import copy

import yaml
from pathlib import Path

from command_center.improvement.schema import ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.board import ImprovementsBoard, GrowthOsBoardSink
from command_center.improvement.lifecycle import Actor, ExperimentStatus as S

REPO_ROOT = Path(__file__).resolve().parents[1]
_CFG = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
_BASE = _CFG["experiments"][0]


class FakeAppFlowyClient:
    """Stands in for the curator's AppFlowyClient: holds rows keyed by ExperimentID and
    records upserts. A real client wraps AppFlowyClient.upsert (server-side dedup)."""
    def __init__(self, seed=None):
        self.rows = {r["ExperimentID"]: r for r in (seed or [])}
        self.upsert_calls = 0

    def list_rows(self, database):
        return [dict(r) for r in self.rows.values()]

    def upsert(self, database, rows):
        self.upsert_calls += 1
        for r in rows:
            self.rows[r["ExperimentID"]] = dict(r)


def _register(reg, eid):
    raw = copy.deepcopy(_BASE)
    raw["experiment_id"] = eid
    reg.register(ExperimentDefinition.model_validate(raw), mission_id=f"T-{eid[-3:]}")


def test_human_fields_survive_agent_resync(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    _register(reg, "EXP-x")
    # AppFlowy already holds a human-curated row (notes + a decision)
    fake = FakeAppFlowyClient(seed=[{
        "ExperimentID": "EXP-x", "Status": "Proposed", "ReviewNotes": "check latency",
        "HumanDecision": "defer", "ReopenConditions": "if latency improves"}])
    sink = GrowthOsBoardSink(fake)
    board = ImprovementsBoard(reg)

    # the Ledger advances; the agent re-syncs the board
    reg.set_status("EXP-x", S.BASELINE_READY, actor=Actor.AGENT)
    res = board.sync(sink, dry_run=False)
    assert "EXP-x" in res["human_fields_preserved"]
    row = fake.rows["EXP-x"]
    assert row["ReviewNotes"] == "check latency"          # human note kept
    assert row["HumanDecision"] == "defer"                # human decision kept
    assert row["ReopenConditions"] == "if latency improves"
    assert row["Status"] == "Baseline Ready"              # Ledger field updated


def test_agent_row_lands_non_approved(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    _register(reg, "EXP-new")
    fake = FakeAppFlowyClient()                           # nothing in AppFlowy yet
    res = ImprovementsBoard(reg).sync(GrowthOsBoardSink(fake), dry_run=False)
    assert res["created"] == ["EXP-new"]
    assert fake.rows["EXP-new"]["HumanDecision"] == ""    # agent invented no decision


def test_dry_run_does_not_upsert(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    _register(reg, "EXP-x")
    fake = FakeAppFlowyClient()
    ImprovementsBoard(reg).sync(GrowthOsBoardSink(fake), dry_run=True)
    assert fake.upsert_calls == 0
