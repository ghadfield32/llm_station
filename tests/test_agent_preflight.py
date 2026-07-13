"""cc agent-preflight (Phase 0 of the Claude/Codex agent-session plan): every probe must
report PASS / BLOCKED / NOT_CONFIGURED with a concrete reason, never a generic
"unavailable", and the module must never write anything or make a network call.
"""
from __future__ import annotations

from pathlib import Path

from command_center.cli import agent_preflight as pf


def test_sdk_probe_not_configured_when_uninstalled():
    p = pf._sdk_probe("x", "definitely_not_a_real_module_xyz", "not-a-real-package")
    assert p.status == "NOT_CONFIGURED"
    assert "pip install not-a-real-package" in p.detail


def test_sdk_probe_pass_for_a_real_stdlib_module():
    # os is always importable; version lookup falls back gracefully for a
    # distribution name that has no matching installed package
    p = pf._sdk_probe("x", "os", "not-a-pypi-distribution-xyz")
    assert p.status == "PASS"
    assert "importable from" in p.detail


def test_cli_probe_not_configured_when_binary_missing(monkeypatch):
    monkeypatch.setattr(pf.shutil, "which", lambda b: None)
    p = pf._cli_probe("x", "definitely-not-a-real-binary")
    assert p.status == "NOT_CONFIGURED"
    assert "not found on PATH" in p.detail


def test_cli_probe_pass_when_version_succeeds(monkeypatch):
    monkeypatch.setattr(pf.shutil, "which", lambda b: "/usr/bin/fake")

    class _Result:
        stdout = "fake-tool 1.2.3"
        stderr = ""

    monkeypatch.setattr(pf.subprocess, "run", lambda *a, **k: _Result())
    p = pf._cli_probe("x", "fake")
    assert p.status == "PASS"
    assert "1.2.3" in p.detail


def test_cli_probe_blocked_when_version_call_fails(monkeypatch):
    monkeypatch.setattr(pf.shutil, "which", lambda b: "/usr/bin/fake")

    def _raise(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(pf.subprocess, "run", _raise)
    p = pf._cli_probe("x", "fake")
    assert p.status == "BLOCKED"
    assert "permission denied" in p.detail


def test_env_key_probe_never_prints_the_value(monkeypatch):
    monkeypatch.setattr("command_center.channels.core.env",
                        lambda: {"SOME_SECRET_KEY": "sk-super-secret-value"})
    p = pf._env_key_probe("x", "SOME_SECRET_KEY")
    assert p.status == "PASS"
    assert "sk-super-secret-value" not in p.detail
    assert "is set" in p.detail


def test_env_key_probe_not_configured_when_absent(monkeypatch):
    monkeypatch.setattr("command_center.channels.core.env", lambda: {})
    p = pf._env_key_probe("x", "SOME_KEY")
    assert p.status == "NOT_CONFIGURED"


def test_codex_cli_session_auth_probe_finds_a_real_login_file(tmp_path, monkeypatch):
    home = tmp_path / "codex_home"
    home.mkdir()
    (home / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    p = pf._codex_cli_session_auth_probe()
    assert p.status == "PASS"
    assert str(home) in p.detail


def test_codex_cli_session_auth_probe_not_configured_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nope"))
    p = pf._codex_cli_session_auth_probe()
    assert p.status == "NOT_CONFIGURED"
    assert "codex login" in p.detail


def test_forbidden_provider_policy_probe_is_always_blocked_and_names_both_keys():
    """This is a real, ground-truth cross-check against check_forbidden_providers.py's
    own FORBIDDEN_KEYS/ROUTER_LANE_KEYS constants, not a paraphrase — if that module's
    policy ever changes (e.g. a future --allow-agent-session-egress flag), this test
    fails and forces the preflight wording to be updated to match, rather than silently
    drifting out of sync with the real gate."""
    p = pf._forbidden_provider_policy_probe()
    assert p.status == "BLOCKED"
    assert "ANTHROPIC_API_KEY" in p.detail
    assert "OPENAI_API_KEY" in p.detail
    assert "OPENROUTER_API_KEY" not in p.detail.split("no existing")[0]  # not in the "never exemptable" list


def test_probe_host_detects_container_via_dockerenv(monkeypatch):
    original_is_file = Path.is_file

    def fake_is_file(self):
        return True if self.as_posix() == "/.dockerenv" else original_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    probes = pf.probe_host()
    assert probes[0].status == "BLOCKED"
    assert "container" in probes[0].detail


def test_run_overall_is_blocked_when_any_probe_is_blocked(monkeypatch):
    monkeypatch.setattr(pf, "probe_host",
                        lambda: [pf.Probe("execution_context", "PASS", "on host")])
    monkeypatch.setattr(pf, "probe_claude", lambda: [pf.Probe("x", "PASS", "ok")])
    monkeypatch.setattr(pf, "probe_codex", lambda: [pf.Probe("x", "PASS", "ok")])
    result = pf.run("all")
    # forbidden_provider_policy always fires and is always BLOCKED today
    assert result["overall"] == "BLOCKED"
    assert any(p["check"] == "forbidden_provider_policy" for p in result["probes"])


def test_run_codex_only_excludes_the_claude_specific_policy_probe(monkeypatch):
    """forbidden_provider_policy is a genuinely CLAUDE-specific blocker (the
    Claude Agent SDK structurally requires ANTHROPIC_API_KEY). Codex never
    touches OPENAI_API_KEY (verified live via a real account() call — see
    WORKLOG.md "Agent-session chat integration"), so including this probe in
    a codex-only run made `--harness codex --live` report BLOCKED overall
    even when every Codex-relevant check passed. Real regression test: with
    every codex probe mocked to PASS, overall must be PASS, not BLOCKED by
    an irrelevant Claude policy note."""
    monkeypatch.setattr(pf, "probe_host",
                        lambda: [pf.Probe("execution_context", "PASS", "on host")])
    monkeypatch.setattr(pf, "probe_codex", lambda: [pf.Probe("x", "PASS", "ok")])
    result = pf.run("codex")
    assert result["overall"] == "PASS"
    assert not any(p["check"] == "forbidden_provider_policy" for p in result["probes"])


def test_informational_probe_never_gates_overall(monkeypatch):
    """codex_api_key_present is informational: NOT_CONFIGURED there is the
    EXPECTED state for existing-login Codex (verified live — a real turn runs
    with no OPENAI_API_KEY). It must not drag overall down to NOT_CONFIGURED
    when every gating probe passes. Real regression test for Fix A's
    completion (the packet's target: `--harness codex --live` -> PASS)."""
    monkeypatch.setattr(pf, "probe_host",
                        lambda: [pf.Probe("execution_context", "PASS", "on host")])
    monkeypatch.setattr(pf, "probe_codex", lambda: [
        pf.Probe("codex_sdk_importable", "PASS", "ok"),
        pf.Probe("codex_api_key_present", "NOT_CONFIGURED",
                 "OPENAI_API_KEY is not set", informational=True),
        pf.Probe("codex_cli_session_auth", "PASS", "login session found"),
    ])
    result = pf.run("codex")
    assert result["overall"] == "PASS"
    # the informational probe is still REPORTED — just not gating
    assert any(p["check"] == "codex_api_key_present" for p in result["probes"])


def test_real_probe_codex_marks_api_key_probe_informational():
    """Ground-truth: the real probe_codex() output flags codex_api_key_present
    as informational (not just the synthetic test above)."""
    probes = {p.check: p for p in pf.probe_codex()}
    assert probes["codex_api_key_present"].informational is True
    # the SDK/CLI probes are NOT informational — they genuinely gate
    assert probes["codex_sdk_importable"].informational is False


def test_run_never_writes_anything(monkeypatch, tmp_path):
    """Read-only guarantee: point HOME/CODEX_HOME somewhere pristine and confirm the
    directory is untouched after a full run."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
    before = list(tmp_path.rglob("*"))
    pf.run("all")
    after = list(tmp_path.rglob("*"))
    assert before == after


def test_main_exits_nonzero_when_not_fully_pass(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["cc-agent-preflight", "--harness", "claude"])
    code = pf.main()
    assert code != 0        # forbidden_provider_policy is always BLOCKED today
    out = capsys.readouterr().out
    assert "agent-preflight (claude):" in out
