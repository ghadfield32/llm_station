"""System-validation evidence runner tests."""
from __future__ import annotations

from pathlib import Path

from command_center.cli import system_validation


def test_system_validation_writes_evidence_package(tmp_path):
    out = system_validation.build_package(tmp_path, "test-run")

    assert out == tmp_path / "test-run"
    expected = {
        "BASELINE.md",
        "SCENARIOS.md",
        "COMMANDS.md",
        "PRIVACY.md",
        "FORECASTS.md",
        "GAPS.md",
        "NEXT.md",
    }
    assert expected == {path.name for path in out.iterdir()}

    baseline = (out / "BASELINE.md").read_text(encoding="utf-8")
    gaps = (out / "GAPS.md").read_text(encoding="utf-8")
    privacy = (out / "PRIVACY.md").read_text(encoding="utf-8")
    scenarios = (out / "SCENARIOS.md").read_text(encoding="utf-8")
    next_steps = (out / "NEXT.md").read_text(encoding="utf-8")

    assert "mission.forecast" in baseline
    assert "devcontainer=.devcontainer/devcontainer.json" in baseline
    assert "card=mission_intake/card-review q3 odds metrics" in baseline
    assert "model_alias=chat" in baseline
    assert "max_tokens_source=existing_live_smoke_generation_budget" in baseline
    assert "app=llm-station-command-center" in baseline
    assert "private_key_path_env=GITHUB_APP_PRIVATE_KEY_PATH" in baseline
    assert "owner_admin_token_env=GITHUB_OWNER_ADMIN_TOKEN" in baseline
    assert "required_status_check_contexts=validate, lint-test" in baseline
    assert "require_ruleset_bypass_actors_absent=True" in baseline
    assert "ruleset_bypass_policy_source=GitHub wall requires no unverified" in baseline
    assert "repo `llm_station` autonomous edits blocked" not in gaps
    assert "desktop target `appflowy_browser_staging` blocked" in gaps
    assert "GitHub App auth is `blocked` pending auth requirements" not in gaps
    assert "GitHub App production auth review pending" not in gaps
    assert ".env` was not read" in privacy
    assert "| local agent tool/memory/multi-turn validation | MISSING | agent-validation.json |" in scenarios
    assert "| desktop target snapshot verification | MISSING | desktop-target-verify.json |" in scenarios
    assert "| desktop adapter readiness | MISSING | desktop-adapter-readiness.json |" in scenarios
    assert "| GitHub App installation observed | PASS | github-app-verify.json |" in scenarios
    assert "| GitHub App repository permission verification | PASS |" in scenarios
    assert "| GitHub branch protection verification | MISSING | branch-protection-verify.json |" in scenarios
    assert "| tiny branch-only repo mission | MISSING | branch-mission.json |" in scenarios
    assert "| live PR/check evidence loop | MISSING | pr-check-loop.json |" in scenarios
    assert "| repo autonomy enabled | BLOCKED | configs/autonomy.yaml + pr-check-loop.json |" in scenarios
    assert "Completed Contract Work" in next_steps
    assert "canonical_event_schemas" in next_steps
    assert "repo_devcontainer_manifest_added_for_llm_station" in next_steps
    assert "github_app_production_auth_review_completed" in next_steps
    assert "github_app_created_selected_env_recorded" in next_steps
    assert "github_app_private_key_secured_and_env_ref_recorded" in next_steps
    assert "github_app_installed_on_selected_llm_station_repo" in next_steps
    assert "github_app_installation_token_and_selected_repo_read_verified" in next_steps
    assert "github_app_issues_read_policy_approved" in next_steps
    assert "github_app_repository_permissions_verified" in next_steps
    assert "branch_protection_owner_admin_verifier_added" in next_steps
    assert "github_token_storage_rotation_policy_drafted" in next_steps
    assert "staging_appflowy_card_state_in_progress_verified" in next_steps
    assert "desktop_adapter_readiness_gate_added" in next_steps
    assert "branch_protection_observer_token_supplied_and_repo_read_verified" in next_steps
    assert "branch_protection_ruleset_diagnostics_added" in next_steps
    assert "branch_protection_rerun_confirmed_main_unprotected" in next_steps
    assert "branch_protection_active_ruleset_detected" in next_steps
    assert "branch_protection_required_checks_and_core_rules_verified" in next_steps
    assert "code_owner_reviews_verified_on_active_branch_ruleset" in next_steps
    assert "branch_protection_verified_with_active_ruleset" in next_steps
    assert "github_token_storage_rotation_policy_finalized" in next_steps
    assert "github_app_auth_verified_after_branch_wall" in next_steps
    assert "tiny_branch_only_repo_mission_passed" in next_steps
    assert "pr_check_evidence_loop_verified" in next_steps
    assert "run_tiny_branch_only_repo_mission" not in next_steps
    assert "verify_pr_check_evidence_loop_before_autonomous_edits" not in next_steps
    assert "declare_desktop_timeout_and_human_takeover_policy_before_live_actions" in next_steps
    assert "enable_code_owner_reviews_on_active_branch_ruleset" not in next_steps
    assert "rerun_branch_protection_verify_until_verified" not in next_steps
    assert "remove_unneeded_github_app_issues_permission" not in next_steps
    assert "implement_desktop_adapter_after_target_state_verifies" not in next_steps


def test_system_validation_main_uses_requested_run_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(system_validation, "ROOT", Path.cwd())
    monkeypatch.setattr(
        "sys.argv",
        [
            "system-validation",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "manual-run",
        ],
    )

    rc = system_validation.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "manual-run" in out
    assert (tmp_path / "manual-run" / "SCENARIOS.md").exists()
