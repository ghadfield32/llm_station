# Gaps

## Repo And Desktop Blockers
- repo `llm_station` autonomous edits blocked: owner_admin_branch_protection_observer_token_missing, branch_protection_not_verified_with_owner_admin_path, token_storage_and_rotation_not_finalized_after_branch_protection
- desktop target `appflowy_browser_staging` blocked: desktop_live_actions_not_enabled, desktop_timeout_and_takeover_policy_not_declared

## Canaries
- canary `read-only repo scan` blocked until: canary_schedule_plan_not_approved
- canary `no-op kanban roundtrip` blocked until: canary_schedule_plan_not_approved
- canary `browser staging board task` blocked until: desktop_live_actions_not_enabled, desktop_timeout_and_takeover_policy_not_declared
- canary `prompt judge suite` blocked until: canary_schedule_plan_not_approved
- canary `model routing benchmark` blocked until: structured_output_role_repair, canary_schedule_plan_not_approved
- canary `notification dry run` blocked until: canary_schedule_plan_not_approved
- canary `privacy artifact scan` blocked until: canary_schedule_plan_not_approved

## Telemetry
- telemetry mode is `structured_events_only`: canonical_event_contract_added_first, opentelemetry_deferred_until_cross_service_trace_gap_is_measured

## Auth And External Runtimes
- GitHub App production auth review pending: provide_owner_admin_branch_protection_observer_token, rerun_branch_protection_verify_and_required_checks, finalize_github_app_token_storage_rotation_after_branch_protection_passes
- GitHub App auth is `blocked`; run `cc github-app-verify` to identify the current installation or permission blocker
- external runtime evaluation blocked until measured gap and gates: measured_gap_against_current_control_plane, no_second_ledger_or_gateway, no_provider_key_fallback, threat_privacy_authority_review, rollback_plan, independent_verification

## Verifier
- loop-breaker numeric threshold not set; requires experiment-derived plan
