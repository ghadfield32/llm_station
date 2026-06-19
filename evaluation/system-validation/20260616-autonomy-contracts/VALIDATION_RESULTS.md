# Validation Results

## Commands

| Command | Result | Notes |
| --- | --- | --- |
| `uv run cc validate` | PASS | All config contracts passed, including `configs/autonomy.yaml`; cross-refs passed; forbidden-provider scan passed. |
| `uv run pytest -q tests/test_branch_protection_verify.py tests/test_autonomy_contracts.py` | PASS | 21 passed. |
| `uv run pytest -q tests/test_desktop_adapter.py tests/test_desktop_target_verify.py tests/test_autonomy_contracts.py` | PASS | 20 passed. |
| `uv run pytest -q tests/test_agent_validation.py tests/test_gateway_toolcall.py tests/test_github_app_verify.py tests/test_system_validation.py` | PASS | 19 passed. |
| `uv run pytest -q tests/test_branch_protection_verify.py tests/test_desktop_adapter.py tests/test_desktop_target_verify.py tests/test_system_validation.py tests/test_autonomy_contracts.py tests/test_github_app_verify.py tests/test_agent_validation.py tests/test_gateway_toolcall.py tests/test_memory.py` | PASS | Focused deep suite passed. |
| `uv run pytest -q tests/test_system_validation.py tests/test_branch_protection_verify.py tests/test_autonomy_contracts.py` | PASS | 23 passed. |
| `uv run pytest -q tests/test_github_app_verify.py tests/test_system_validation.py tests/test_autonomy_contracts.py tests/test_branch_protection_verify.py` | PASS | 30 passed after GitHub wall verification. |
| `uv run ruff check src tests services/ledger/app.py` | PASS | Ruff passed; uv reported cache package-root warnings only. |
| `uv run cc evals` | PASS | All routing/safety eval fixtures passed, including fake fallback and L3/L4 approval cases. |
| `uv run cc mission-dryrun` | PASS | L0-L2 auto gates and L3/L4 approval gates behaved as configured. |
| `uv run cc live-smoke` | PASS | Passed Ollama direct, LiteLLM `triage`, `planner`, `local-judge`, denied cloud aliases, executor-key absence, and forbidden-provider scan. |
| `uv run pytest -q` | PASS | Full suite passed with 1 existing Starlette deprecation warning. |
| `uv run cc agent-validation --output evaluation/system-validation/20260616-autonomy-contracts/agent-validation.json` | PASS | Live `chat` route passed parsed tool-call parsing, memory-block recall, 14-turn recall, and fresh-conversation abstention. Artifact stores synthetic scenario statuses only. |
| `growthos.actions.move_item('mission_intake', 'review Q3 odds metrics', 'In Progress')` | PASS | Single scoped AppFlowy test-card status write returned `'review Q3 odds metrics' -> In Progress`. |
| `uv run python -m command_center.cli.kanban_surface board-snapshot --output generated/board-snapshot.json` | PASS | Live AppFlowy snapshot wrote 6 boards. The configured staging card now shows `In Progress`. |
| `uv run cc desktop-target-verify --output evaluation/system-validation/20260616-autonomy-contracts/desktop-target-verify.json` | PASS | The configured staging card is present and verifier value `In Progress` is observed. No desktop actions were performed. |
| `uv run cc desktop-adapter --output evaluation/system-validation/20260616-autonomy-contracts/desktop-adapter-readiness.json` | BLOCKED | Adapter exists and performs no GUI actions; blocks because live target is disabled and TTL, action timeout, human takeover, and screenshot/evidence policy are missing. |
| `uv run cc github-app-verify --output evaluation/system-validation/20260616-autonomy-contracts/github-app-verify.json` | PASS | App auth, installation discovery, installation-token mint, selected repo read, checks/status reads, and repository permission verification succeeded. App Administration visibility is intentionally not required. |
| `uv run cc branch-protection-verify --output evaluation/system-validation/20260616-autonomy-contracts/branch-protection-verify.json` | PASS | Local workflow checks, CODEOWNERS path, and active `protect-main-command-center` ruleset were verified, including CODEOWNERS review, required checks, PR review, linear history, deletion restriction, force-push block, and empty bypass actors. |
| `uv run cc system-validation --run-id 20260616-autonomy-contracts` | PASS | Evidence package refreshed with current ordered work and artifact statuses. |
| `git diff --check` | PASS | No whitespace errors; Git reported line-ending warnings for generated evidence files. |

## Current Evidence Verdict

- Local contract, unit, full-suite, lint, eval, mission dry-run, live model routing, and live agent behavior checks are green.
- GitHub App installation is no longer the blocker.
- GitHub App repository permissions are verified under the operator-approved `issues: read` policy.
- Branch-protection verification now passes through the owner/admin observer path; remove or expire the temporary observer token after final audit reruns.
- Repository autonomy remains disabled until one tiny branch-only mission proves the branch/worktree/devcontainer, validation, and PR/check evidence loop.
- Desktop target verification now passes from the live snapshot.
- Desktop adapter readiness remains blocked because live desktop actions are disabled and timeout/takeover/evidence policies are not declared.

## Safety

- No secrets were printed.
- No `.env` values, tokens, private keys, or credential-derived material were written into this package.
- One scoped AppFlowy test-card status write was performed and verified; no repo pushes, PR writes, merges, deployments, settings changes, secret changes, or desktop actions were performed.
- No provider API keys were added.
- No tests were weakened or skipped.
