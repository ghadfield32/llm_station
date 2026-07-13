"""Egress reconciliation gate: router-lane keys are permitted ONLY under the explicit flag AND
only when the budget is enabled with redaction + usage accounting. The local lane stays strict.
"""
import textwrap

import pytest

from command_center.cli import check_forbidden_providers as cfp


def _write_budgets(path, *, enabled, redaction=True, usage=True):
    path.write_text(textwrap.dedent(f"""
        schema_version: command-center.frontier-router-budgets.v1
        default:
          enabled: {str(enabled).lower()}
          monthly_cap_usd: 10.0
          per_run_cap_usd: 1.0
          per_request_cap_usd: 0.25
          require_redaction: {str(redaction).lower()}
          require_human_approval_for_live_repo_context: true
          log_token_usage: true
          log_cost_estimate: true
          fail_on_missing_usage: {str(usage).lower()}
        allowed_task_classes: [frontier_reference_eval]
        blocked_payloads: [secrets]
    """).strip() + "\n", encoding="utf-8")


def test_egress_ready_requires_enabled_and_redaction(tmp_path, monkeypatch):
    p = tmp_path / "b.yaml"
    monkeypatch.setattr(cfp, "FRONTIER_BUDGETS", p)
    _write_budgets(p, enabled=False)
    ready, why = cfp.frontier_egress_ready()
    assert ready is False and "enabled is false" in why
    _write_budgets(p, enabled=True)
    ready, why = cfp.frontier_egress_ready()
    assert ready is True


def test_default_mode_still_forbids_router_key_in_process_env(monkeypatch):
    # No flag -> OPENROUTER_API_KEY in the process env is a hard failure (local-only intact).
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-not-real")
    assert cfp.main(allow_router_egress=False) == 1


def test_egress_flag_requires_the_lane_to_be_ready(tmp_path, monkeypatch):
    # Flag set but budget disabled -> refuse (cannot opt into egress that isn't budgeted).
    p = tmp_path / "b.yaml"
    monkeypatch.setattr(cfp, "FRONTIER_BUDGETS", p)
    _write_budgets(p, enabled=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-not-real")
    assert cfp.main(allow_router_egress=True) == 1


def test_egress_flag_permits_router_key_when_budgeted(tmp_path, monkeypatch):
    # Flag set + budget enabled -> the router key is permitted; the check passes.
    p = tmp_path / "b.yaml"
    monkeypatch.setattr(cfp, "FRONTIER_BUDGETS", p)
    _write_budgets(p, enabled=True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-not-real")
    assert cfp.main(allow_router_egress=True) == 0


def test_egress_mode_never_permits_the_local_cloud_keys(tmp_path, monkeypatch):
    # Even in egress mode, OPENAI/ANTHROPIC keys stay forbidden (those aren't router-lane keys).
    p = tmp_path / "b.yaml"
    monkeypatch.setattr(cfp, "FRONTIER_BUDGETS", p)
    _write_budgets(p, enabled=True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-real")
    assert cfp.main(allow_router_egress=True) == 1


def _write_agent_session_budgets(path, *, enabled, codex=False, claude=False):
    path.write_text(textwrap.dedent(f"""
        schema_version: command-center.agent-session-budgets.v1
        default:
          enabled: {str(enabled).lower()}
          harnesses:
            codex_agent: {str(codex).lower()}
            claude_agent: {str(claude).lower()}
    """).strip() + "\n", encoding="utf-8")


def test_agent_session_egress_ready_requires_enabled_and_a_harness(tmp_path, monkeypatch):
    p = tmp_path / "a.yaml"
    monkeypatch.setattr(cfp, "AGENT_SESSION_BUDGETS", p)
    _write_agent_session_budgets(p, enabled=False)
    ready, why = cfp.agent_session_egress_ready()
    assert ready is False and "enabled is false" in why

    _write_agent_session_budgets(p, enabled=True)  # no harness on -> still not ready
    ready, why = cfp.agent_session_egress_ready()
    assert ready is False and "no harness" in why

    _write_agent_session_budgets(p, enabled=True, codex=True)
    ready, why = cfp.agent_session_egress_ready()
    assert ready is True and "codex_agent" in why


def test_default_mode_still_forbids_agent_session_keys_in_process_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-real")
    assert cfp.main(allow_agent_session_egress=False) == 1


def test_agent_session_egress_flag_requires_readiness(tmp_path, monkeypatch):
    p = tmp_path / "a.yaml"
    monkeypatch.setattr(cfp, "AGENT_SESSION_BUDGETS", p)
    _write_agent_session_budgets(p, enabled=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-real")
    assert cfp.main(allow_agent_session_egress=True) == 1


def test_agent_session_egress_flag_permits_the_keys_when_ready(tmp_path, monkeypatch):
    p = tmp_path / "a.yaml"
    monkeypatch.setattr(cfp, "AGENT_SESSION_BUDGETS", p)
    _write_agent_session_budgets(p, enabled=True, codex=True)
    # isolate from this developer's real .env, which may legitimately carry an
    # OPENROUTER_API_KEY for the (separate, unrelated) frontier-router lane —
    # this test is about the agent-session flag only, not router-lane state
    monkeypatch.setattr(cfp, "dotenv_keys", lambda path: set())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-real")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-real")
    assert cfp.main(allow_agent_session_egress=True) == 0


def test_agent_session_egress_never_permits_the_router_lane_keys(tmp_path, monkeypatch):
    # Enabling agent-session egress must not silently unlock the frontier-router keys.
    p = tmp_path / "a.yaml"
    monkeypatch.setattr(cfp, "AGENT_SESSION_BUDGETS", p)
    _write_agent_session_budgets(p, enabled=True, codex=True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-not-real")
    assert cfp.main(allow_agent_session_egress=True) == 1


def test_frontier_egress_never_permits_the_agent_session_keys(tmp_path, monkeypatch):
    # The existing flag must not have silently gained the new keys either — the two
    # lanes stay fully independent in both directions.
    p = tmp_path / "b.yaml"
    monkeypatch.setattr(cfp, "FRONTIER_BUDGETS", p)
    _write_budgets(p, enabled=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-real")
    assert cfp.main(allow_router_egress=True) == 1


def test_both_egress_flags_together_only_unlock_their_own_keys(tmp_path, monkeypatch):
    router_budgets = tmp_path / "b.yaml"
    agent_budgets = tmp_path / "a.yaml"
    monkeypatch.setattr(cfp, "FRONTIER_BUDGETS", router_budgets)
    monkeypatch.setattr(cfp, "AGENT_SESSION_BUDGETS", agent_budgets)
    _write_budgets(router_budgets, enabled=True)
    _write_agent_session_budgets(agent_budgets, enabled=True, claude=True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-real")
    assert cfp.main(allow_router_egress=True, allow_agent_session_egress=True) == 0


def test_agent_session_egress_never_relaxes_the_local_litellm_lane(tmp_path, monkeypatch):
    """The wall check_models_yaml()/check_litellm_config() enforce is unconditional —
    neither egress flag may ever touch it, even when both are active and ready."""
    router_budgets = tmp_path / "b.yaml"
    agent_budgets = tmp_path / "a.yaml"
    monkeypatch.setattr(cfp, "FRONTIER_BUDGETS", router_budgets)
    monkeypatch.setattr(cfp, "AGENT_SESSION_BUDGETS", agent_budgets)
    _write_budgets(router_budgets, enabled=True)
    _write_agent_session_budgets(agent_budgets, enabled=True, codex=True, claude=True)
    calls = []
    monkeypatch.setattr(cfp, "check_models_yaml", lambda errors: calls.append("models"))
    monkeypatch.setattr(cfp, "check_litellm_config", lambda errors: calls.append("litellm"))
    monkeypatch.setattr(cfp, "check_local_frontier_providers",
                        lambda errors: calls.append("local_frontier"))
    cfp.main(allow_router_egress=True, allow_agent_session_egress=True)
    assert calls == ["models", "litellm", "local_frontier"]


# ---- local-frontier host allowlist (not a cloud-egress concern — no key involved) ----------

@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1:8000/v1",
    "http://localhost:8000/v1",
    "http://host.docker.internal:8000/v1",
    "http://192.168.1.50:8000/v1",
    "http://10.0.0.5:8000/v1",
    "http://mymachine.ts.net:8000/v1",
])
def test_assert_local_frontier_host_allowed_permits_local_hosts(base_url):
    cfp.assert_local_frontier_host_allowed(base_url)  # must not raise


@pytest.mark.parametrize("base_url", [
    "http://evil.example.com:8000/v1",
    "http://8.8.8.8:8000/v1",
    "https://api.openai.com/v1",
])
def test_assert_local_frontier_host_allowed_rejects_public_hosts(base_url):
    with pytest.raises(ValueError, match="not loopback|non-private"):
        cfp.assert_local_frontier_host_allowed(base_url)


def test_check_local_frontier_providers_passes_when_unset(monkeypatch):
    monkeypatch.delenv("LOCAL_FRONTIER_COLIBRI_BASE_URL", raising=False)
    monkeypatch.setattr(cfp, "dotenv_kv", lambda path: {})
    errors: list[str] = []
    cfp.check_local_frontier_providers(errors)
    assert errors == []


def test_check_local_frontier_providers_passes_for_loopback(monkeypatch):
    monkeypatch.setattr(cfp, "dotenv_kv", lambda path: {})
    monkeypatch.setenv("LOCAL_FRONTIER_COLIBRI_BASE_URL", "http://127.0.0.1:8000/v1")
    errors: list[str] = []
    cfp.check_local_frontier_providers(errors)
    assert errors == []


def test_check_local_frontier_providers_rejects_public_host(monkeypatch):
    monkeypatch.setattr(cfp, "dotenv_kv", lambda path: {})
    monkeypatch.setenv("LOCAL_FRONTIER_COLIBRI_BASE_URL", "http://evil.example.com:8000/v1")
    errors: list[str] = []
    cfp.check_local_frontier_providers(errors)
    assert len(errors) == 1
    assert "not loopback" in errors[0]


def test_local_frontier_check_runs_unconditionally_in_main(tmp_path, monkeypatch):
    """No --allow-*-egress flag required — this isn't a cloud-egress gate (no key, nothing
    bills), it's a "never point local-frontier at a public host" invariant that always runs,
    same as the local Ollama-lane checks (mirrors
    test_agent_session_egress_never_relaxes_the_local_litellm_lane's call-order technique)."""
    calls: list[str] = []
    monkeypatch.setattr(cfp, "check_env_files", lambda errors, forbidden: calls.append("env"))
    monkeypatch.setattr(cfp, "check_process_env", lambda errors, forbidden: calls.append("process"))
    monkeypatch.setattr(cfp, "check_compose", lambda errors, forbidden: calls.append("compose"))
    monkeypatch.setattr(cfp, "check_models_yaml", lambda errors: calls.append("models"))
    monkeypatch.setattr(cfp, "check_litellm_config", lambda errors: calls.append("litellm"))
    monkeypatch.setattr(cfp, "check_local_frontier_providers",
                        lambda errors: calls.append("local_frontier"))
    cfp.main()
    assert calls[-1] == "local_frontier"
