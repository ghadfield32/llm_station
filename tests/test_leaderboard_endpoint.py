"""Phase 8 leaderboard endpoint — reads the durable evidence log, ranks each
dimension independently, never collapses to one score, marks unmeasured
dimensions insufficient."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"


def _load(monkeypatch, tmp_path, evidence=None):
    from fastapi.testclient import TestClient
    log = tmp_path / "leaderboard-evidence.jsonl"
    if evidence:
        log.write_text("\n".join(json.dumps(e) for e in evidence), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("akui_lb_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["akui_lb_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LEADERBOARD_EVIDENCE", log)
    return mod, TestClient(mod.app)


def test_leaderboard_empty_is_all_insufficient_no_winner(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path)
    r = tc.get("/api/leaderboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "overall" not in body and "winner" not in body
    assert "no single" in body["note"].lower()
    # every dimension present, every cell insufficient (honest empty state)
    for dim in body["dimensions"]:
        assert all(c["insufficient"] and c["rank"] is None for c in dim["cells"])


def test_leaderboard_ranks_from_evidence_and_marks_gaps(monkeypatch, tmp_path):
    evidence = [
        {"executor": "codex_agent", "dimension_id": "task_success", "value": 0.9,
         "sample_size": 10, "source": "assistant-verify"},
        {"executor": "claude_code_local", "dimension_id": "task_success",
         "value": 0.95, "sample_size": 10, "source": "assistant-verify"},
        {"executor": "openrouter_agent", "dimension_id": "actual_cost",
         "value": 0.08, "sample_size": 3, "source": "usage"},
    ]
    _mod, tc = _load(monkeypatch, tmp_path, evidence)
    body = tc.get("/api/leaderboard").json()
    dims = {d["id"]: d for d in body["dimensions"]}
    # task_success ranked (higher better): claude #1, codex #2; others insufficient
    ts = {c["executor"]: c for c in dims["task_success"]["cells"]}
    assert ts["claude_code_local"]["rank"] == 1
    assert ts["codex_agent"]["rank"] == 2
    assert ts["openrouter_agent"]["insufficient"] is True   # no task_success evidence
    # actual_cost: openrouter has the only evidence → rank 1; rest insufficient
    ac = {c["executor"]: c for c in dims["actual_cost"]["cells"]}
    assert ac["openrouter_agent"]["rank"] == 1
    assert ac["claude_code_local"]["insufficient"] is True
    # quality has NO evidence anywhere → all insufficient
    assert all(c["insufficient"] for c in dims["quality"]["cells"])


def test_malformed_evidence_line_is_skipped_not_fatal(monkeypatch, tmp_path):
    log = tmp_path / "leaderboard-evidence.jsonl"
    log.write_text('{"executor":"codex_agent","dimension_id":"safety","value":1.0}\n'
                   'not-json\n{"missing":"fields"}\n', encoding="utf-8")
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("akui_lb_test2", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["akui_lb_test2"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LEADERBOARD_EVIDENCE", log)
    body = TestClient(mod.app).get("/api/leaderboard").json()
    safety = next(d for d in body["dimensions"] if d["id"] == "safety")
    ranked = [c for c in safety["cells"] if c["rank"] == 1]
    assert len(ranked) == 1 and ranked[0]["executor"] == "codex_agent"
