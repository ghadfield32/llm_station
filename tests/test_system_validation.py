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
    assert "repo `llm_station` autonomous edits blocked" in gaps
    assert "desktop target `appflowy_browser_staging` blocked" in gaps
    assert "GitHub App auth is `blocked`" in gaps
    assert ".env` was not read" in privacy
    assert "| local agent tool/memory/multi-turn validation | MISSING | agent-validation.json |" in scenarios
    assert "| desktop target snapshot verification | MISSING | desktop-target-verify.json |" in scenarios
    assert "| desktop adapter readiness | MISSING | desktop-adapter-readiness.json |" in scenarios
    assert "| GitHub App installation observed | PASS | github-app-verify.json |" in scenarios
    assert "| GitHub App repository permission verification | PASS |" in scenarios
    assert "| GitHub branch protection verification | MISSING | branch-protection-verify.json |" in scenarios
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
    assert "provide_owner_admin_branch_protection_observer_token" in next_steps
    assert "rerun_branch_protection_verify_and_required_checks" in next_steps
    assert "declare_desktop_timeout_and_human_takeover_policy_before_live_actions" in next_steps
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
