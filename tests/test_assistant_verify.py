"""cc assistant-verify — the first leaderboard evidence producer. Hermetic: the
worker probe fetch is monkeypatched; no network, no quota."""
from __future__ import annotations

import json

from command_center.cli import assistant_verify as av


def test_evidence_available_vs_unavailable():
    avail = av._evidence_for({"harness_id": "codex_agent", "available": True,
                              "external_egress": False})
    serving = next(e for e in avail if e["dimension_id"] == "serving_reliability")
    assert serving["value"] == 1.0 and serving["source"] == "assistant-verify"
    down = av._evidence_for({"harness_id": "codex_agent", "available": False,
                             "external_egress": False})
    assert next(e for e in down if e["dimension_id"] == "serving_reliability")["value"] == 0.0


def test_safety_is_egress_honesty():
    # openrouter MUST declare external egress -> safe; a local declaring egress -> unsafe
    orouter_ok = av._evidence_for({"harness_id": "openrouter_agent", "available": True,
                                   "external_egress": True})
    assert next(e for e in orouter_ok if e["dimension_id"] == "safety")["value"] == 1.0
    orouter_bad = av._evidence_for({"harness_id": "openrouter_agent", "available": True,
                                    "external_egress": False})
    assert next(e for e in orouter_bad if e["dimension_id"] == "safety")["value"] == 0.0
    local_ok = av._evidence_for({"harness_id": "claude_code_local", "available": True,
                                 "external_egress": False})
    assert next(e for e in local_ok if e["dimension_id"] == "safety")["value"] == 1.0
    local_bad = av._evidence_for({"harness_id": "claude_code_local", "available": True,
                                  "external_egress": True})
    assert next(e for e in local_bad if e["dimension_id"] == "safety")["value"] == 0.0


def test_run_requires_worker_token(monkeypatch, capsys):
    monkeypatch.delenv("AGENT_WORKER_TOKEN", raising=False)
    assert av.run(["--json"]) == 1
    assert "AGENT_WORKER_TOKEN not set" in capsys.readouterr().out


def test_run_emits_evidence_and_reports_repair(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_WORKER_TOKEN", "t")
    monkeypatch.setattr(av, "_fetch_probes", lambda *a, **k: [
        {"harness_id": "codex_agent", "available": True, "external_egress": False,
         "detail": "ok"},
        {"harness_id": "claude_agent", "available": False, "external_egress": False,
         "detail": "claude-agent-sdk not installed"},
    ])
    log = tmp_path / "leaderboard-evidence.jsonl"
    rc = av.run(["--json", "--evidence-path", str(log)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["overall"] == "fail"     # one assistant unavailable
    # unavailable assistant carries a precise repair action
    ca = next(a for a in out["assistants"] if a["assistant"] == "claude_agent")
    assert ca["repair"] and "claude-agent-sdk" in ca["repair"]
    # evidence was appended to the log (4 samples: 2 dims x 2 assistants)
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert out["evidence_emitted"] == 4 and len(lines) == 4
    assert {l["dimension_id"] for l in lines} == {"serving_reliability", "safety"}


def test_no_emit_flag_skips_the_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_WORKER_TOKEN", "t")
    monkeypatch.setattr(av, "_fetch_probes", lambda *a, **k: [
        {"harness_id": "codex_agent", "available": True, "external_egress": False,
         "detail": "ok"}])
    log = tmp_path / "leaderboard-evidence.jsonl"
    av.run(["--json", "--evidence-path", str(log), "--no-emit"])
    assert not log.exists()


def test_emitted_evidence_feeds_the_leaderboard(monkeypatch, tmp_path):
    # end-to-end: assistant-verify's samples, read back by build_leaderboard, rank
    monkeypatch.setenv("AGENT_WORKER_TOKEN", "t")
    monkeypatch.setattr(av, "_fetch_probes", lambda *a, **k: [
        {"harness_id": "codex_agent", "available": True, "external_egress": False,
         "detail": "ok"},
        {"harness_id": "claude_agent", "available": False, "external_egress": False,
         "detail": "down"}])
    log = tmp_path / "ev.jsonl"
    av.run(["--evidence-path", str(log)])
    from command_center.ranking import EvidenceSample, build_leaderboard
    samples = [EvidenceSample(executor=d["executor"], dimension_id=d["dimension_id"],
                              value=d["value"], sample_size=d["sample_size"],
                              source=d["source"])
               for d in (json.loads(x) for x in log.read_text().splitlines() if x.strip())]
    board = build_leaderboard(samples)
    serving = next(d for d in board.dimensions if d.dimension.id == "serving_reliability")
    ranks = {c.executor: c.rank for c in serving.cells}
    assert ranks["codex_agent"] == 1              # available -> ranked #1
    assert ranks["claude_agent"] == 2             # down (0.0) -> ranked lower
