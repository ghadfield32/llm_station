"""Whole-system autonomy contract tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from command_center.schemas import CONFIG_CONTRACTS
from command_center.schemas.contracts import AutonomyConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


def _raw() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs/autonomy.yaml").read_text(encoding="utf-8"))


def test_autonomy_yaml_is_registered_and_valid():
    assert "configs/autonomy.yaml" in CONFIG_CONTRACTS
    AutonomyConfig.model_validate(_raw())


def test_event_contract_rejects_raw_payload_retention():
    raw = _raw()
    raw["event_contract"]["families"][0]["raw_payload_allowed"] = True

    with pytest.raises(ValueError, match="raw payloads"):
        AutonomyConfig.model_validate(raw)


def test_event_contract_requires_all_declared_event_families():
    raw = _raw()
    raw["event_contract"]["families"] = [
        family for family in raw["event_contract"]["families"]
        if family["kind"] != "desktop.action"
    ]

    with pytest.raises(ValueError, match="desktop.action"):
        AutonomyConfig.model_validate(raw)


def test_autonomy_work_order_rejects_duplicates_and_completed_overlap():
    raw = _raw()
    raw["ordered_work"].append(raw["ordered_work"][0])

    with pytest.raises(ValueError, match="ordered_work contains duplicates"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    raw["completed_work"].append(raw["ordered_work"][0])

    with pytest.raises(ValueError, match="both completed and ordered"):
        AutonomyConfig.model_validate(raw)


def test_enabled_repo_autonomy_requires_github_app_and_devcontainer():
    raw = _raw()
    repo = raw["repo_manifests"][0]
    repo["autonomous_edits_enabled"] = True
    repo["blockers"] = []
    repo["auth_mode"] = "github_app_pending"

    with pytest.raises(ValueError, match="auth_mode=github_app"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    repo = raw["repo_manifests"][0]
    repo["autonomous_edits_enabled"] = True
    repo["blockers"] = []
    repo["auth_mode"] = "github_app"
    repo.pop("devcontainer_path")

    with pytest.raises(ValueError, match="devcontainer"):
        AutonomyConfig.model_validate(raw)


def test_devcontainer_execution_requires_path_even_before_autonomy_is_enabled():
    raw = _raw()
    repo = raw["repo_manifests"][0]
    repo["execution_mode"] = "devcontainer"
    repo.pop("devcontainer_path")

    with pytest.raises(ValueError, match="devcontainer_path"):
        AutonomyConfig.model_validate(raw)


def test_disabled_repo_manifest_must_name_blockers():
    raw = _raw()
    # llm_station is now enabled; exercise the invariant on a disabled manifest.
    raw["repo_manifests"][0]["autonomous_edits_enabled"] = False
    raw["repo_manifests"][0]["blockers"] = []

    with pytest.raises(ValueError, match="disabled manifests must list blockers"):
        AutonomyConfig.model_validate(raw)


def test_enabled_repo_manifest_must_not_list_blockers():
    raw = _raw()
    raw["repo_manifests"][0]["autonomous_edits_enabled"] = True
    raw["repo_manifests"][0]["blockers"] = ["some_blocker"]

    with pytest.raises(ValueError, match="enabled manifests cannot list blockers"):
        AutonomyConfig.model_validate(raw)


def test_desktop_target_rejects_overlap_and_missing_default_denies():
    raw = _raw()
    target = raw["desktop_targets"][0]
    target["forbidden_actions"].append("click")

    with pytest.raises(ValueError, match="both allowed and forbidden"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    target = raw["desktop_targets"][0]
    target["forbidden_actions"].remove("clipboard_read")

    with pytest.raises(ValueError, match="missing default deny"):
        AutonomyConfig.model_validate(raw)


def test_enabled_desktop_target_requires_ttl_and_takeover_policy():
    raw = _raw()
    target = raw["desktop_targets"][0]
    target["enabled"] = True
    target["blockers"] = []
    target.pop("human_takeover_hotkey")
    target.pop("screenshot_artifact_policy")

    with pytest.raises(ValueError, match="ttl_minutes"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    target = raw["desktop_targets"][0]
    target["enabled"] = True
    target["blockers"] = []
    target["ttl_minutes"] = 5
    target["ttl_source"] = "unit_test_measurement_fixture"
    target.pop("human_takeover_hotkey")
    target.pop("screenshot_artifact_policy")

    with pytest.raises(ValueError, match="action_timeout_seconds"):
        AutonomyConfig.model_validate(raw)


def test_selected_desktop_card_requires_board_and_snapshot_evidence():
    raw = _raw()
    target = raw["desktop_targets"][0]
    target.pop("board")

    with pytest.raises(ValueError, match="board and card_ref"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    target = raw["desktop_targets"][0]
    target.pop("snapshot_evidence_ref")

    with pytest.raises(ValueError, match="snapshot evidence"):
        AutonomyConfig.model_validate(raw)


def test_completion_verifier_requires_forecast_and_verification_events():
    raw = _raw()
    raw["completion_verifier"]["required_event_families"] = ["mission.forecast"]

    with pytest.raises(ValueError, match="mission.verification"):
        AutonomyConfig.model_validate(raw)


def test_agent_validation_requires_budget_source_and_unique_scenarios():
    raw = _raw()
    raw["agent_validation"]["max_tokens_source"] = ""

    with pytest.raises(ValueError, match="max_tokens_source"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    raw["agent_validation"]["required_scenarios"].append(
        raw["agent_validation"]["required_scenarios"][0]
    )

    with pytest.raises(ValueError, match="required_scenarios contains duplicates"):
        AutonomyConfig.model_validate(raw)


def test_github_app_auth_requires_minimum_permissions_and_forbidden_scope():
    raw = _raw()
    raw["github_app_auth"]["allowed_repository_permissions"]["contents"] = "read"

    with pytest.raises(ValueError, match="contents: read_write"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    raw["github_app_auth"]["forbidden_repository_permissions"].pop("administration")

    with pytest.raises(ValueError, match="administration"):
        AutonomyConfig.model_validate(raw)


def test_github_app_auth_requires_private_key_env_reference():
    raw = _raw()
    raw["github_app_auth"]["private_key_path_env"] = "github_key"

    with pytest.raises(ValueError, match="env ref"):
        AutonomyConfig.model_validate(raw)


def test_branch_protection_verification_requires_token_env_and_check_source():
    raw = _raw()
    raw["branch_protection_verification"]["owner_admin_token_env"] = "github_token"

    with pytest.raises(ValueError, match="owner_admin_token_env"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    raw["branch_protection_verification"]["required_status_check_contexts"] = []

    with pytest.raises(ValueError, match="required_status_check_contexts"):
        AutonomyConfig.model_validate(raw)


def test_enabled_canary_requires_schedule_and_cleared_blockers():
    raw = _raw()
    canary = deepcopy(raw["canaries"][0])
    canary["enabled"] = True
    raw["canaries"][0] = canary

    with pytest.raises(ValueError, match="must declare schedule"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    canary = deepcopy(raw["canaries"][0])
    canary["enabled"] = True
    canary["schedule"] = "hourly"
    raw["canaries"][0] = canary

    with pytest.raises(ValueError, match="cannot list blocked_until"):
        AutonomyConfig.model_validate(raw)


def test_desktop_noop_canary_requires_target_id():
    raw = _raw()
    raw["desktop_noop_canaries"][0].pop("target_id")

    with pytest.raises(ValueError, match="target_id"):
        AutonomyConfig.model_validate(raw)


def test_desktop_noop_canary_rejects_allowed_forbidden_overlap():
    raw = _raw()
    canary = raw["desktop_noop_canaries"][0]
    canary["forbidden_actions"].append(canary["allowed_actions"][0])

    with pytest.raises(ValueError, match="both allowed and forbidden"):
        AutonomyConfig.model_validate(raw)


def test_desktop_noop_canary_rejects_screenshot_without_redaction_policy():
    raw = _raw()
    canary = raw["desktop_noop_canaries"][0]
    canary["screenshot_policy"] = "redacted_hashes_and_refs_only"
    canary.pop("redaction_policy")

    with pytest.raises(ValueError, match="redaction_policy"):
        AutonomyConfig.model_validate(raw)


def test_desktop_noop_canary_rejects_unknown_target():
    raw = _raw()
    raw["desktop_noop_canaries"][0]["target_id"] = "unknown_target"

    with pytest.raises(ValueError, match="unknown target"):
        AutonomyConfig.model_validate(raw)


def test_desktop_timing_sample_plan_rejects_unknown_target():
    raw = _raw()
    raw["desktop_timing_sample_plans"][0]["target_id"] = "unknown_target"

    with pytest.raises(ValueError, match="unknown target"):
        AutonomyConfig.model_validate(raw)


def test_desktop_timing_sample_plan_requires_repo_relative_evidence_refs():
    raw = _raw()
    raw["desktop_timing_sample_plans"][0]["required_evidence_refs"][0] = (
        r"C:\tmp\desktop-noop-canary.json"
    )

    with pytest.raises(ValueError, match="repo-relative non-secret artifact"):
        AutonomyConfig.model_validate(raw)

    raw = _raw()
    raw["desktop_timing_sample_plans"][0]["required_evidence_refs"][0] = ".env"

    with pytest.raises(ValueError, match="repo-relative non-secret artifact"):
        AutonomyConfig.model_validate(raw)


def test_desktop_timing_sample_plan_count_source_must_name_evidence_refs():
    raw = _raw()
    raw["desktop_timing_sample_plans"][0]["required_sample_count_source"] = (
        "operator_cli_args"
    )

    with pytest.raises(ValueError, match="required_evidence_refs"):
        AutonomyConfig.model_validate(raw)
