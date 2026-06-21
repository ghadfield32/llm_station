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
