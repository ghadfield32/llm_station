# Baseline

- Run id: `20260616-autonomy-contracts`
- Commit: `6b22965`
- Dirty entries: 55

## Dirty Worktree
- M .env.example
-  M .gitignore
-  M Makefile
-  M appflowy_kanban/growth-os/agent/growthos_mcp.py
-  M appflowy_kanban/growth-os/growthos/actions.py
-  M appflowy_kanban/growth-os/growthos/assistant.py
-  M appflowy_kanban/growth-os/scripts/test_abilities.py
-  M docker-compose.yml
-  M docs/MASTER.md
-  M docs/autonomous-pipeline-gap-review-2026-06-16.md
-  M docs/backend/projects/AGENT_KANBAN_SURFACE.md
-  M generated/board-snapshot.json
-  M scripts/live_smoke.ps1
-  M scripts/live_smoke.sh
-  M services/agent_kanban_ui/app.py
-  M services/agent_kanban_ui/web/src/App.tsx
-  M services/agent_kanban_ui/web/src/styles.css
-  M services/ledger/app.py
-  M src/command_center/channels/core.py
-  M src/command_center/cli/check_cross_refs.py
-  M src/command_center/cli/main.py
-  M src/command_center/schemas/__init__.py
-  M src/command_center/schemas/contracts.py
-  M tests/test_actions_intent.py
-  M tests/test_agent_kanban_ui.py
-  M tests/test_gateway_toolcall.py
-  M tests/test_ledger_rest.py
-  M tests/test_routing.py
- ?? .devcontainer/
- ?? configs/autonomy.yaml
- ?? docs/github-app-production-auth-review-2026-06-16.md
- ?? docs/github-token-storage-rotation.md
- ?? evaluation/system-validation/
- ?? generated/model-baseline-summary.json
- ?? generated/model-candidate-audit-evidence/
- ?? generated/model-candidate-audit-summary.json
- ?? generated/model-metric-audit-evidence/
- ?? generated/model-metric-audit-summary.json
- ?? generated/model-scout-feed.json
- ?? generated/model-scout-report.json
- ?? src/command_center/autonomy/
- ?? src/command_center/cli/agent_validation.py
- ?? src/command_center/cli/branch_protection_verify.py
- ?? src/command_center/cli/desktop_adapter.py
- ?? src/command_center/cli/desktop_target_verify.py
- ?? src/command_center/cli/github_app_verify.py
- ?? src/command_center/cli/system_validation.py
- ?? tests/test_agent_validation.py
- ?? tests/test_autonomy_contracts.py
- ?? tests/test_autonomy_events.py
- ?? tests/test_branch_protection_verify.py
- ?? tests/test_desktop_adapter.py
- ?? tests/test_desktop_target_verify.py
- ?? tests/test_github_app_verify.py
- ?? tests/test_system_validation.py

## Validated Config Contracts
- configs/agent_surface.yaml
- configs/autonomy.yaml
- configs/channels.yaml
- configs/content.yaml
- configs/discovery.yaml
- configs/environments.yaml
- configs/evals.yaml
- configs/gates.yaml
- configs/improvement-targets.yaml
- configs/improvement.yaml
- configs/judges.yaml
- configs/kanban.yaml
- configs/model-benchmarks.yaml
- configs/model-scout-curated-openweight.yaml
- configs/models.yaml
- configs/proactive.yaml
- configs/standards.yaml
- configs/targets.yaml
- configs/tools.yaml
- configs/ui.yaml

## Event Families
- mission.forecast
- mission.action
- mission.verification
- mission.completion_verdict
- mission.rollback
- route.decision
- repo.action
- kanban.mutation
- desktop.observation
- desktop.action
- model.call
- notification.sent

## Repo Manifests
- `llm_station`: blocked; auth=github_app_pending; execution=devcontainer; risk_ceiling=L2_local_edits; devcontainer=.devcontainer/devcontainer.json; blockers=owner_admin_branch_protection_observer_token_missing, branch_protection_not_verified_with_owner_admin_path, token_storage_and_rotation_not_finalized_after_branch_protection

## Desktop Targets
- `appflowy_browser_staging`: blocked; surface=browser; os=windows; card=mission_intake/card-review q3 odds metrics; snapshot=generated/board-snapshot.json; blockers=desktop_live_actions_not_enabled, desktop_timeout_and_takeover_policy_not_declared

## Agent Validation
- model_alias=chat
- max_tokens=512
- max_tokens_source=existing_live_smoke_generation_budget_required_for_qwen_visible_content
- required_scenarios=chat_tool_call_parse, memory_block_recall, long_multi_turn_recall, fresh_conversation_without_memory_abstains

## GitHub App Auth
- status=blocked
- app=llm-station-command-center
- owner=ghadfield32
- homepage=https://github.com/ghadfield32/llm_station
- webhook_active=False
- app_id_env=GITHUB_APP_ID
- client_id_env=GITHUB_CLIENT_ID
- installation_id_env=GITHUB_APP_INSTALLATION_ID
- private_key_path_env=GITHUB_APP_PRIVATE_KEY_PATH
- selected_repositories=ghadfield32/llm_station
- token_storage_policy=env_refs_only_private_key_outside_repo_short_lived_installation_tokens

## Branch Protection Verification
- status=blocked
- owner_admin_token_env=GITHUB_OWNER_ADMIN_TOKEN
- selected_repositories=ghadfield32/llm_station
- required_status_check_contexts=validate, lint-test
- required_status_check_source_path=.github/workflows/contracts.yml
- codeowners_path=.github/CODEOWNERS
- required_approving_review_count=1
- required_review_count_source=.github/CODEOWNERS default_owner_policy
- token_policy=env_ref_only_owner_admin_observer_no_settings_writes
