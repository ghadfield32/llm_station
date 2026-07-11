"""Egress reconciliation gate: router-lane keys are permitted ONLY under the explicit flag AND
only when the budget is enabled with redaction + usage accounting. The local lane stays strict.
"""
import textwrap


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
    cfp.main(allow_router_egress=True, allow_agent_session_egress=True)
    assert calls == ["models", "litellm"]
