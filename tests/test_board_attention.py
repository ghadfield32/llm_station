"""Growth OS improvements-board + human-attention tests.

Prove the board projects the Ledger faithfully (board/Ledger agree), never clobbers a
human-owned field, never invents a human decision, and that the attention digest counts
the queue and prioritizes the right items.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

import yaml
from pathlib import Path

from command_center.improvement.schema import ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.lifecycle import Actor, ExperimentStatus as S, TransitionConditions
from command_center.improvement.board import (
    ImprovementsBoard, FileBoardSink, merge_clobber_safe, BOARD_FIELDS, HUMAN_OWNED,
)
from command_center.improvement.attention import attention_metrics, morning_brief

REPO_ROOT = Path(__file__).resolve().parents[1]
_BASE = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))["experiments"][0]


def _good() -> TransitionConditions:
    return TransitionConditions(deterministic_passed=True, verification_present=True,
                                verification_verdict="PASS", independent_verifier_distinct=True,
                                human_approval=True, rollback_demonstrated=True)


def _register(reg, eid: str) -> str:
    raw = copy.deepcopy(_BASE)
    raw["experiment_id"] = eid
    reg.register(ExperimentDefinition.model_validate(raw), mission_id=f"T-{eid[-3:]}")
    return eid


def _advance_to(reg, eid, target: S):
    """Walk an experiment to a target state through valid transitions."""
    path = [S.BASELINE_READY, S.RUNNING, S.AWAITING_VERIFICATION, S.VERIFIED,
            S.AWAITING_HUMAN_PROMOTION]
    for s in path:
        if s == S.VERIFIED:
            reg.set_verifier_verdict(eid, "PASS",
                                     detail={"independent": True, "verifier_identity": "v"})
        cond = _good() if s in (S.AWAITING_HUMAN_PROMOTION,) else None
        reg.set_status(eid, s, actor=Actor.AGENT, conditions=cond)
        if s == target:
            return


# ---- board ------------------------------------------------------------------

def test_board_rows_match_ledger(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    _register(reg, "EXP-a")
    board = ImprovementsBoard(reg)
    rows = board.rows()
    assert len(rows) == 1
    r = rows[0]
    assert set(r) == set(BOARD_FIELDS)
    # board agrees with the Ledger on the authoritative fields
    exp = reg.get("EXP-a")
    assert r["ExperimentID"] == exp["experiment_id"]
    assert r["Status"] == exp["status"]
    assert r["MissionID"] == exp["mission_id"]


def test_sync_creates_then_preserves_human_fields(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    _register(reg, "EXP-a")
    sink = FileBoardSink(tmp_path / "board.json")
    board = ImprovementsBoard(reg)
    res = board.sync(sink, dry_run=False)
    assert res["created"] == ["EXP-a"]

    # a human edits the board: adds review notes + a reopen condition
    data = sink.existing()
    data["EXP-a"]["ReviewNotes"] = "looks promising, check latency under load"
    data["EXP-a"]["HumanDecision"] = "defer"
    sink.write(data)

    # the Ledger advances; agent re-syncs
    _advance_to(reg, "EXP-a", S.AWAITING_VERIFICATION)
    res2 = board.sync(sink, dry_run=False)
    assert "EXP-a" in res2["human_fields_preserved"]
    after = sink.existing()["EXP-a"]
    # human-owned fields survived; Ledger-owned status updated
    assert after["ReviewNotes"] == "looks promising, check latency under load"
    assert after["HumanDecision"] == "defer"
    assert after["Status"] == "Awaiting Verification"


def test_agent_sync_never_invents_human_decision(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    _register(reg, "EXP-a")
    board = ImprovementsBoard(reg)
    # nothing in the Ledger set human_decision, so the board row must not claim one
    row = board.rows()[0]
    assert row["HumanDecision"] == ""


def test_merge_clobber_safe_unit():
    existing = {"ExperimentID": "X", "ReviewNotes": "human note", "Status": "old"}
    incoming = {"ExperimentID": "X", "ReviewNotes": "", "Status": "new"}
    merged = merge_clobber_safe(existing, incoming)
    assert merged["ReviewNotes"] == "human note"   # preserved
    assert merged["Status"] == "new"               # updated
    assert HUMAN_OWNED == {"HumanDecision", "ReopenConditions", "ReviewNotes"}


def test_dry_run_does_not_write(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    _register(reg, "EXP-a")
    sink = FileBoardSink(tmp_path / "board.json")
    ImprovementsBoard(reg).sync(sink, dry_run=True)
    assert not (tmp_path / "board.json").exists()


# ---- attention --------------------------------------------------------------

def test_attention_metrics_counts(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    _register(reg, "EXP-v1"); _advance_to(reg, "EXP-v1", S.AWAITING_VERIFICATION)
    _register(reg, "EXP-p1"); _advance_to(reg, "EXP-p1", S.AWAITING_HUMAN_PROMOTION)
    _register(reg, "EXP-p2"); _advance_to(reg, "EXP-p2", S.AWAITING_HUMAN_PROMOTION)
    m = attention_metrics(reg)
    assert m["experiments_awaiting_verification"] == 1
    assert m["experiments_awaiting_human_promotion"] == 2
    assert m["concurrent_human_decisions"] == 2
    assert m["pct_independently_reproduced"] > 0.0   # all three have verifier verdicts


def test_morning_brief_prioritizes_and_warns(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    _register(reg, "EXP-p1"); _advance_to(reg, "EXP-p1", S.AWAITING_HUMAN_PROMOTION)
    _register(reg, "EXP-v1"); _advance_to(reg, "EXP-v1", S.AWAITING_VERIFICATION)
    brief = morning_brief(reg)
    assert "Improvement queue" in brief
    assert "EXP-p1" in brief and "EXP-v1" in brief
    # human-promotion item ranks above the verification item
    assert brief.index("EXP-p1") < brief.index("EXP-v1")
    assert "approve (start canary)" in brief


def test_morning_brief_flags_stale(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    _register(reg, "EXP-p1"); _advance_to(reg, "EXP-p1", S.AWAITING_HUMAN_PROMOTION)
    updated = reg.get("EXP-p1")["updated_at"]
    future = (datetime.fromisoformat(updated) + timedelta(hours=100)).isoformat()
    brief = morning_brief(reg, now_iso=future)
    assert "older than 48h" in brief
