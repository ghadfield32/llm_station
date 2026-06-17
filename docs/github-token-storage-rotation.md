# GitHub Token Storage And Rotation Policy

Status: **drafted, blocked from final approval until branch protection verifies**.

This policy covers the `llm-station-command-center` GitHub App and the temporary
owner/admin observer credential used only for branch-protection verification.

## Source Basis

- GitHub App installation access tokens are short-lived; GitHub's current docs
  state that installation tokens expire after one hour:
  <https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app>
- GitHub App private keys do not expire automatically. GitHub recommends using
  multiple private keys so keys can be rotated without downtime, and documents a
  25-key app limit:
  <https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps>

## Credential Classes

| Credential | Storage | Runtime Use | Rotation |
| --- | --- | --- | --- |
| GitHub App id/client id/name | `.env` env refs only | Non-secret identity inputs | Change only when the app identity changes |
| GitHub App private key | Path in `.env`; PEM outside repo under user secret storage | Read only by verifier/control-plane token minting code | Generate overlapping replacement key, update `GITHUB_APP_PRIVATE_KEY_PATH`, verify, then revoke old key |
| Installation access token | Never written to disk; minted in memory per operation | Selected repo only, requested permissions only | Let GitHub expiry end the token; mint a fresh token per operation |
| Owner/admin branch-protection observer token | Optional env ref `GITHUB_OWNER_ADMIN_TOKEN`; never committed | Read-only branch-protection verification only | Remove from shell/env after one verifier run |

## Rules

1. Committed config stores only env-var names and paths, never token values.
2. Installation tokens are generated just-in-time and are not logged, persisted,
   cached in files, injected into repo-task containers, or copied into reports.
3. Repo-task containers keep `allowed_secrets: []`; git credentials are provided
   only to the lease holder outside committed files.
4. `GITHUB_OWNER_ADMIN_TOKEN` is not a repo-execution identity. It exists only
   to call read-only branch-protection endpoints when the GitHub App cannot see
   settings without Administration permission.
5. Do not grant the GitHub App Administration permission solely to inspect branch
   protection.
6. If the private key is suspected compromised, generate a new key, update the
   local secret path, run `cc github-app-verify`, then revoke the old key in
   GitHub settings.
7. If any token value appears in logs, docs, generated artifacts, screenshots,
   or git diff, treat the run as failed and rotate the affected credential.

## Approval Gate

This policy is not enough to enable repo autonomy. `auth_mode: github_app` and
`autonomous_edits_enabled: true` remain blocked until:

1. `cc github-app-verify` passes.
2. `cc branch-protection-verify` passes with owner/admin observer auth.
3. Required checks, PR review, CODEOWNERS review, force-push/delete blocks, and
   linear-history policy are verified from GitHub.
4. A human approves the auth-mode change.
