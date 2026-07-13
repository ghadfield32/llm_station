"""
The `cc onboard repo` wizard extensions: mode -> risk_ceiling, the ordered
stop-on-blocker gate walkthrough, and the auto PR-loop-proof that only fires for
pr-autonomy when pr_check_evidence_proven is the binding gap.
"""
from __future__ import annotations

import argparse

from command_center.cli import onboard
from command_center.cli.repo_registry import build_repo_manifest_block


def _gates(**status):
    """Build a verify result; kwargs map gate name -> 'PASS'|'BLOCKED'."""
    gates = [{"check": k, "status": v} for k, v in status.items()]
    blockers = [k for k, v in status.items() if v != "PASS"]
    return {"status": "blocked" if blockers else "pass",
            "gates": gates, "blockers": blockers}


def _ns(**kw):
    base = dict(path="/tmp/myrepo", repo_id="myrepo", remote_url="https://x/y.git",
                kanban_board="", mode="observe-only", no_loop_proof=False, apply=True)
    base.update(kw)
    return argparse.Namespace(**base)


def _patch_common(monkeypatch, *, register=None, verify=None, loop=None, calls=None):
    from command_center.cli import github_app_verify as gav
    monkeypatch.setattr(gav, "_read_dotenv", lambda p: {})
    monkeypatch.setattr(gav, "_merged_env", lambda d: {})
    monkeypatch.setattr(onboard, "_git_origin", lambda p: "https://x/y.git")

    def _register(**kw):
        if calls is not None:
            calls["register_kwargs"] = kw
        return register or {"status": "registered", "repo_id": kw["repo_id"]}
    monkeypatch.setattr(onboard, "run_repo_register", _register)

    verify_seq = list(verify or [])

    def _verify(**kw):
        return verify_seq.pop(0) if verify_seq else _gates()
    monkeypatch.setattr(onboard, "run_repo_verify", _verify)

    def _loop(**kw):
        if calls is not None:
            calls["loop_called"] = calls.get("loop_called", 0) + 1
            calls["loop_kwargs"] = kw
        return loop or {"status": "pass"}
    monkeypatch.setattr(onboard, "run_repo_loop_proof", _loop)


# ── mode -> risk_ceiling ──────────────────────────────────────────────

def test_mode_risk_mapping():
    assert onboard.MODE_RISK["observe-only"] == "L0_read_only"
    assert onboard.MODE_RISK["local-edits"] == "L2_local_edits"
    assert onboard.MODE_RISK["pr-autonomy"] == "L2_local_edits"


def test_manifest_risk_ceiling_threads_through():
    m = build_repo_manifest_block(repo_id="r", remote_url="u", local_path_ref="env:R",
                                  kanban_board_id="b", risk_ceiling="L0_read_only")
    assert m.risk_ceiling == "L0_read_only"
    default = build_repo_manifest_block(repo_id="r", remote_url="u",
                                        local_path_ref="env:R", kanban_board_id="b")
    assert default.risk_ceiling == "L2_local_edits"


def test_register_receives_mode_risk_ceiling(monkeypatch):
    calls = {}
    _patch_common(monkeypatch, verify=[_gates(devcontainer_present="PASS")], calls=calls)
    onboard._onboard_repo(_ns(mode="observe-only"))
    assert calls["register_kwargs"]["risk_ceiling"] == "L0_read_only"


# ── auto loop-proof gating ────────────────────────────────────────────

BLOCK_ONLY_PRCHECK = _gates(
    devcontainer_present="PASS", github_app_installed="PASS",
    merge_wall_verified="PASS", pr_check_evidence_proven="BLOCKED",
)
ALL_PASS = _gates(devcontainer_present="PASS", github_app_installed="PASS",
                  merge_wall_verified="PASS", pr_check_evidence_proven="PASS")


def test_pr_autonomy_runs_loop_proof_then_passes(monkeypatch):
    calls = {}
    # first verify blocks on pr-check; loop-proof passes; re-verify all-pass
    _patch_common(monkeypatch, verify=[BLOCK_ONLY_PRCHECK, ALL_PASS],
                  loop={"status": "pass"}, calls=calls)
    rc = onboard._onboard_repo(_ns(mode="pr-autonomy"))
    assert calls.get("loop_called") == 1
    assert calls["loop_kwargs"]["apply"] is True
    assert rc == 0


def test_observe_only_never_runs_loop_proof(monkeypatch):
    calls = {}
    _patch_common(monkeypatch, verify=[BLOCK_ONLY_PRCHECK], calls=calls)
    rc = onboard._onboard_repo(_ns(mode="observe-only"))
    assert calls.get("loop_called") is None      # not called
    assert rc == 1                               # blocker remains


def test_no_loop_proof_flag_suppresses_it(monkeypatch):
    calls = {}
    _patch_common(monkeypatch, verify=[BLOCK_ONLY_PRCHECK], calls=calls)
    rc = onboard._onboard_repo(_ns(mode="pr-autonomy", no_loop_proof=True))
    assert calls.get("loop_called") is None
    assert rc == 1


def test_loop_proof_skipped_when_github_app_also_blocked(monkeypatch):
    calls = {}
    blocked = _gates(github_app_installed="BLOCKED", pr_check_evidence_proven="BLOCKED")
    _patch_common(monkeypatch, verify=[blocked], calls=calls)
    rc = onboard._onboard_repo(_ns(mode="pr-autonomy"))
    assert calls.get("loop_called") is None      # prerequisite missing
    assert rc == 1


def test_dry_run_does_not_run_loop_proof(monkeypatch):
    calls = {}
    _patch_common(monkeypatch, verify=[BLOCK_ONLY_PRCHECK], calls=calls)
    rc = onboard._onboard_repo(_ns(mode="pr-autonomy", apply=False))
    assert calls.get("loop_called") is None      # --apply required
    assert rc == 1


# ── walkthrough ───────────────────────────────────────────────────────

def test_walk_gates_returns_blockers(capsys):
    ver = _gates(devcontainer_present="PASS", codeowners_present="BLOCKED")
    blockers = onboard._walk_gates(ver)
    assert blockers == ["codeowners_present"]
    out = capsys.readouterr().out
    assert "PASS    devcontainer_present" in out
    assert "BLOCKED codeowners_present" in out
    assert "add .github/CODEOWNERS" in out      # remediation hint shown
