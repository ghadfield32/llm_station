# Implementation Note

## Already Complete

- `configs/autonomy.yaml` is the current source of truth for autonomy hardening.
- Canonical event families, repo registration manifest, desktop target rights manifest, completion verifier contract, disabled canaries, telemetry decision, GitHub App auth policy, and external-runtime gate validate through `AutonomyConfig`.
- `llm_station` has a declared devcontainer manifest and CODEOWNERS/CI paths.
- The GitHub App private key is referenced by env var path outside the repository.
- `uv run cc github-app-verify` authenticates the GitHub App, discovers the selected-repo installation, mints a short-lived installation token in memory, reads `ghadfield32/llm_station`, and reads check/status endpoints.
- The operator-approved `issues: read` permission is recorded in `configs/autonomy.yaml`, and GitHub App repository permission verification passes.
- `uv run cc branch-protection-verify` exists and verifies local expected check contexts from `.github/workflows/contracts.yml` plus CODEOWNERS path before attempting owner/admin GitHub reads.
- `docs/github-token-storage-rotation.md` documents env-ref-only storage, out-of-repo PEM handling, in-memory installation tokens, one-run owner/admin observer token use, and rotation steps.
- `uv run cc agent-validation` passes live local-model checks for parsed tool calls, memory-block recall, 14-turn recall, and fresh-conversation abstention through the `chat` route.
- The configured AppFlowy staging card was moved to `In Progress` through the existing `move_item` intent, and `uv run cc desktop-target-verify` now passes from the regenerated live snapshot.
- `uv run cc desktop-adapter` exists as a readiness gate; it performs no desktop actions and blocks until live-action policy is declared.
- The verifier prints no token, private key, `.env` value, or raw credential material and performs no writes.

## Blocked

- Repository autonomy remains disabled.
- Branch protection verification is blocked because `GITHUB_OWNER_ADMIN_TOKEN` is absent; the GitHub App token still must not receive Administration permission solely for observation.
- Token storage and rotation policy is drafted but final auth approval is blocked until branch-protection verification passes.
- Desktop/browser live actions remain blocked because the target is disabled and no TTL, action timeout, human takeover hotkey, or screenshot/evidence policy is declared.
- Canaries remain disabled until their declared blockers clear.

## Can Be Completed Locally

- Re-run `uv run cc github-app-verify --output evaluation/system-validation/20260616-autonomy-contracts/github-app-verify.json` after GitHub App auth/policy changes.
- Set `GITHUB_OWNER_ADMIN_TOKEN` for one read-only observer run, then run `uv run cc branch-protection-verify --output evaluation/system-validation/20260616-autonomy-contracts/branch-protection-verify.json`.
- Re-run `uv run cc agent-validation --output evaluation/system-validation/20260616-autonomy-contracts/agent-validation.json` after model-route changes.
- Re-run `uv run python -m command_center.cli.kanban_surface board-snapshot --output generated/board-snapshot.json`, then `uv run cc desktop-target-verify --output evaluation/system-validation/20260616-autonomy-contracts/desktop-target-verify.json` after AppFlowy target changes.
- Declare desktop TTL, action timeout, human takeover, and screenshot/evidence policy before enabling live desktop actions.
- Re-run `uv run cc system-validation --run-id 20260616-autonomy-contracts` after verifier changes.
- Keep `docs/MASTER.md`, `configs/autonomy.yaml`, and this evidence package synchronized after each verifier result.
- Add an owner/admin branch-protection observer only if an approved credential path exists and it does not broaden the GitHub App.

## Requires External User Action

- Provide `GITHUB_OWNER_ADMIN_TOKEN` only if you approve an owner/admin read-only observer credential for branch-protection verification.

## Must Not Be Attempted Yet

- Do not enable `autonomous_edits_enabled`.
- Do not set repo `auth_mode: github_app`.
- Do not grant the GitHub App Administration permission solely to inspect branch protection.
- Do not use a PAT to bypass the GitHub App production-auth blocker.
- Do not store installation tokens.
- Do not print secrets or `.env` values.
- Do not perform branch pushes, PR writes, merges, deploys, settings changes, secret changes, or desktop automation in this pass.
