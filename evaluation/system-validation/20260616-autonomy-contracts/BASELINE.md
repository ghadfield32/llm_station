# Baseline

- Run id: `20260616-autonomy-contracts`
- Commit: `5abf99a`
- Dirty entries: 0

## Dirty Worktree
- none

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
- `llm_station`: enabled; auth=github_app; execution=devcontainer; risk_ceiling=L2_local_edits; devcontainer=.devcontainer/devcontainer.json; blockers=none

## Desktop Targets
- `appflowy_browser_staging`: blocked; surface=browser; os=windows; card=mission_intake/card-review q3 odds metrics; snapshot=generated/board-snapshot.json; blockers=desktop_live_actions_not_enabled, desktop_timeout_and_takeover_policy_not_declared

## Agent Validation
- model_alias=chat
- max_tokens=512
- max_tokens_source=existing_live_smoke_generation_budget_required_for_qwen_visible_content
- required_scenarios=chat_tool_call_parse, memory_block_recall, long_multi_turn_recall, fresh_conversation_without_memory_abstains

## GitHub App Auth
- status=verified
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
- status=verified
- owner_admin_token_env=GITHUB_OWNER_ADMIN_TOKEN
- selected_repositories=ghadfield32/llm_station
- required_status_check_contexts=validate, lint-test
- required_status_check_source_path=.github/workflows/contracts.yml
- codeowners_path=.github/CODEOWNERS
- required_approving_review_count=1
- required_review_count_source=.github/CODEOWNERS default_owner_policy
- require_ruleset_bypass_actors_absent=True
- ruleset_bypass_policy_source=GitHub wall requires no unverified bot/admin bypass around required checks and review gates
- token_policy=env_ref_only_owner_admin_observer_no_settings_writes
