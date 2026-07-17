"""Runtime fingerprint + assistant-doctor drift detection (2026-07-17 incident:
a stale worker/cockpit contract failed sessions mid-chat)."""
from __future__ import annotations

import json

from command_center.agent_sessions.fingerprint import compute_fingerprint
from command_center.cli import assistant_doctor


def test_host_fingerprint_validates_current_checkout():
    fp = compute_fingerprint()
    # the live checkout's contract MUST validate its own config (regression: if
    # research_capabilities drift ever recurs in-source, this fails loudly)
    assert fp["autonomy_validates"] is True
    assert fp["autonomy_validation_error"] is None
    assert fp["config_sha256"]["autonomy.yaml"]      # tracked + hashed
    assert "git_sha" in fp and "source_root" in fp


def test_fingerprint_reports_drift_when_config_has_unknown_field(tmp_path):
    # simulate the incident: a config with a field the contract rejects
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "autonomy.yaml").write_text(
        "repo_manifests:\n  - repo_id: x\n    made_up_field: [oops]\n",
        encoding="utf-8")
    fp = compute_fingerprint(tmp_path)
    assert fp["autonomy_validates"] is False
    assert fp["autonomy_validation_error"]           # a legible reason, not None


def test_assistant_doctor_reports_pass_for_healthy_host(monkeypatch, capsys):
    # no worker token -> worker unreachable, but the HOST self-check still runs;
    # overall FAIL only because the worker couldn't be queried (honest, not a
    # false green). The host_autonomy_validates check must PASS.
    monkeypatch.delenv("AGENT_WORKER_TOKEN", raising=False)
    rc = assistant_doctor.run(["--json"])
    out = json.loads(capsys.readouterr().out)
    host_check = next(c for c in out["checks"]
                      if c["id"] == "host_autonomy_validates")
    assert host_check["status"] == "pass"
    reachable = next(c for c in out["checks"] if c["id"] == "worker_reachable")
    assert reachable["status"] == "fail"             # honest: token absent
    assert rc == 1


def test_dirty_tree_is_advisory_by_default_and_gates_under_release(monkeypatch, capsys):
    # release-stabilization §1: a dirty working tree is a WARN by default (dev is
    # normally dirty) but a hard FAIL under --release (production acceptance).
    from command_center.agent_sessions import fingerprint as fp
    monkeypatch.setattr(fp, "_git_dirty", lambda _root: True)
    monkeypatch.delenv("AGENT_WORKER_TOKEN", raising=False)
    # default: the dirty check is advisory (not counted in the gate); it appears
    # as advisory in the JSON and does not, by itself, cause the failure
    assistant_doctor.run(["--json"])
    default = json.loads(capsys.readouterr().out)
    tree = next(c for c in default["checks"] if c["id"] == "host_tree_committed")
    assert tree["status"] == "fail" and tree["advisory"] is True
    assert default["release_mode"] is False
    # --release: the same dirty tree is now a GATING failure
    assistant_doctor.run(["--release", "--json"])
    rel = json.loads(capsys.readouterr().out)
    rel_tree = next(c for c in rel["checks"] if c["id"] == "host_tree_committed")
    assert rel_tree["status"] == "fail" and rel_tree["advisory"] is False
    assert rel["overall"] == "fail" and rel["release_mode"] is True


def test_clean_tree_passes_the_committed_check(monkeypatch, capsys):
    from command_center.agent_sessions import fingerprint as fp
    monkeypatch.setattr(fp, "_git_dirty", lambda _root: False)
    monkeypatch.delenv("AGENT_WORKER_TOKEN", raising=False)
    assistant_doctor.run(["--json"])
    out = json.loads(capsys.readouterr().out)
    tree = next(c for c in out["checks"] if c["id"] == "host_tree_committed")
    assert tree["status"] == "pass"
