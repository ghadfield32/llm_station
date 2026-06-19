# Implementation Note

## Already Complete

- `configs/autonomy.yaml` is the current source of truth for autonomy hardening.
- Canonical event families, repo registration manifest, desktop target rights manifest, completion verifier contract, disabled canaries, telemetry decision, GitHub App auth policy, and external-runtime gate validate through `AutonomyConfig`.
- `llm_station` has a declared devcontainer manifest and CODEOWNERS/CI paths.
- The GitHub App private key is referenced by env var path outside the repository.
- `uv run cc github-app-verify` authenticates the GitHub App, discovers the selected-repo installation, mints a short-lived installation token in memory, reads `ghadfield32/llm_station`, and reads check/status endpoints.
- The operator-approved `issues: read` permission is recorded in `configs/autonomy.yaml`, and GitHub App repository permission verification passes.
- `uv run cc branch-protection-verify` exists and verifies local expected check contexts from `.github/workflows/contracts.yml` plus CODEOWNERS path before attempting owner/admin GitHub reads.
- `uv run cc branch-protection-verify` now diagnoses both classic branch protection and GitHub active branch rules/rulesets after a classic endpoint miss.
- `GITHUB_OWNER_ADMIN_TOKEN` is present for the observer run and can read `ghadfield32/llm_station`; no token value is printed or written.
- `uv run cc branch-protection-verify` passes against the active `protect-main-command-center` ruleset.
- `docs/github-token-storage-rotation.md` documents env-ref-only storage, out-of-repo PEM handling, in-memory installation tokens, one-run owner/admin observer token use, rotation steps, and the recommendation to remove or expire the temporary observer token after final audit reruns.
- `uv run cc agent-validation` passes live local-model checks for parsed tool calls, memory-block recall, 14-turn recall, and fresh-conversation abstention through the `chat` route.
- The configured AppFlowy staging card was moved to `In Progress` through the existing `move_item` intent, and `uv run cc desktop-target-verify` now passes from the regenerated live snapshot.
- `uv run cc desktop-adapter` exists as a readiness gate; it performs no desktop actions and blocks until live-action policy is declared.
- `uv run cc branch-mission` passes the bounded local branch/worktree/docs-only validation loop.
- `uv run cc pr-check-verify --apply --poll-interval 15 --poll-timeout 1800` passes the remote branch/draft-PR/required-check evidence loop through draft PR #6.
- `llm_station` repo autonomy is enabled for registered L2 feature-branch-only work after local and remote evidence gates passed.
- PR #7 merged via squash auto-merge after CODEOWNERS approval; obsolete draft proof PR #6 was closed without deleting its branch.
- Desktop timeout/takeover policy plus human-takeover and screenshot artifact policy are declared for `appflowy_browser_staging`; numeric TTL and action-timeout controls remain unset until no-op canary telemetry derives them.
- Observer verifiers print no token, private key, `.env` value, or raw credential material and perform no writes. The PR/check verifier performs only the explicitly approved feature-branch and draft-PR writes and stores redacted evidence.

## Blocked

- Repository autonomy is no longer blocked for `llm_station` L2 feature-branch-only work; merge/deploy/settings/secrets/branch deletion remain human-gated.
- Token storage and rotation policy is finalized after branch-protection verification passed.
- Desktop/browser live actions remain blocked because the target is disabled, no no-op canary policy has approved live actions, and the adapter records missing telemetry-derived TTL/action-timeout controls.
- Canaries remain disabled until their declared blockers clear.

## Can Be Completed Locally

- Re-run `uv run cc github-app-verify --output evaluation/system-validation/20260616-autonomy-contracts/github-app-verify.json` after GitHub App auth/policy changes.
- Re-run `uv run cc branch-mission --output evaluation/system-validation/20260616-autonomy-contracts/branch-mission.json` after repo-manifest or validation-command changes.
- Re-run `uv run cc pr-check-verify --apply --poll-interval <operator-derived> --poll-timeout <operator-derived> --output evaluation/system-validation/20260616-autonomy-contracts/pr-check-loop.json` only when a fresh PR/check evidence loop is intentionally required.
- Re-run `uv run cc agent-validation --output evaluation/system-validation/20260616-autonomy-contracts/agent-validation.json` after model-route changes.
- Re-run `uv run python -m command_center.cli.kanban_surface board-snapshot --output generated/board-snapshot.json`, then `uv run cc desktop-target-verify --output evaluation/system-validation/20260616-autonomy-contracts/desktop-target-verify.json` after AppFlowy target changes.
- Enable the desktop target only after timeout/takeover policy and no-op canary plan are verified by evidence, including telemetry-derived TTL/action-timeout controls.
- Re-run `uv run cc system-validation --run-id 20260616-autonomy-contracts` after verifier changes.
- Keep `docs/MASTER.md`, `configs/autonomy.yaml`, and this evidence package synchronized after each verifier result.
- Add an owner/admin branch-protection observer only if an approved credential path exists and it does not broaden the GitHub App.

## Requires External User Action

- None for branch protection. Optional cleanup: remove `GITHUB_OWNER_ADMIN_TOKEN` or let it expire after final audit reruns.

## Must Not Be Attempted Yet

- Do not grant the GitHub App Administration permission solely to inspect branch protection.
- Do not use a PAT to bypass the GitHub App production-auth blocker.
- Do not store installation tokens.
- Do not print secrets or `.env` values.
- Do not merge, deploy, change settings, change secrets, delete branches, or perform desktop automation in this pass.
