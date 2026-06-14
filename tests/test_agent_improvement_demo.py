"""
The agent-improvement demo runs end to end and proves the 'better over time' loop for the Kanban
and Discord agents: cards drafted (human-gated), the ranker flips from formula → learned as
feedback accrues, and a rejected idea is remembered.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_DEMO = Path(__file__).resolve().parents[1] / "evaluation" / "agent-improvement-demo" / "run_demo.py"
_spec = importlib.util.spec_from_file_location("agent_improvement_demo", _DEMO)
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)


def test_demo_runs_the_full_loop(tmp_path):
    res = demo.main(tmp_path)
    # 1. observe → propose: both agents get a Proposed (human-gated) card
    assert len(res["drafted"]) == 2
    assert res["all_proposed"] is True
    # 2. learn over time: abstain early, learned ranker takes over once feedback accrues
    assert res["early_champion"] == "formula"
    assert res["seasoned_champion"] == "learned"
    # 3. remember: the rejected idea is suppressed by negative-result memory
    assert res["resuppressed"] is True
