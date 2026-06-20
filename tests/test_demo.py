"""Hermetic tests for the full-loop demo orchestrator (no writes, no merge automation)."""
from __future__ import annotations

from command_center.cli import demo


def test_demo_ready_for_llm_station_and_never_automates_merge():
    result = demo.run_full_loop_demo(
        repo_id="llm_station", board_id="llm_station_command_center", env={})
    assert result["status"] == "ready"
    assert result["loop_ready"] is True
    assert result["merge_automated"] is False
    assert result["writes_performed"] is False
    # the merge step (10) is a human gate, never automatable
    merge = next(s for s in result["steps"] if s["step"] == 10)
    assert merge["kind"] == "HUMAN_GATE" and "NEVER automated" in merge["command"]
    # every step flagged HUMAN_GATE has HUMAN_GATE status (no human gate is auto-run)
    assert all(s["status"] == "HUMAN_GATE"
               for s in result["steps"] if s["kind"] == "HUMAN_GATE")


def test_demo_blocks_for_unregistered_repo():
    result = demo.run_full_loop_demo(
        repo_id="not_a_repo", board_id="llm_station_command_center", env={})
    assert result["status"] == "blocked"
    assert "repo_not_ready_not_a_repo" in result["blockers"]
    assert result["writes_performed"] is False


def test_demo_blocks_for_unregistered_board():
    result = demo.run_full_loop_demo(
        repo_id="llm_station", board_id="no_such_board", env={})
    assert result["status"] == "blocked"
    assert "board_not_ready_no_such_board" in result["blockers"]
