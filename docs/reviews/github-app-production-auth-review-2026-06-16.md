# GitHub App production auth review - 2026-06-16

> **Archived — superseded.** The "blocked" verdict and blockers below (403 on
> branch-protection inspection, missing owner/admin token) are all resolved;
> see `configs/autonomy.yaml` (`autonomous_edits_enabled: true`) and
> `docs/architecture/SECURITY_MODEL.md` §8 for current state. Kept as an
> evidence trail.

## Decision

Production repo autonomy for `llm_station` remains **blocked**. The GitHub App
identity and private-key path are recorded in local env references, the PEM has
been moved outside the repository, and the verifier can authenticate the app,
discover its installation, mint a short-lived installation token in memory, and
read the selected `ghadfield32/llm_station` repository. The remaining blockers
are narrower: the operator-approved `issues: read` permission is recorded in
policy and repository-permission verification passes, while branch-protection
inspection still returns 403 with the app token. `cc branch-protection-verify`
now provides the owner/admin observer path, but it is blocked until
`GITHUB_OWNER_ADMIN_TOKEN` is supplied for one read-only run. Fine-grained PATs
remain pilot-only.

This review completes the auth decision pass; it does not approve autonomous
repo writes.

## Source basis

- GitHub documents GitHub Apps as preferred over OAuth apps for automation
  because they use fine-grained permissions, repository selection, and
  short-lived tokens.
- GitHub App permissions start from no permissions and should be granted at the
  minimum level needed.
- Branch protection can require reviews, status checks, and push restrictions;
  the protected-branch API requires authenticated access with appropriate
  permissions.

## Local evidence collected

| Check | Result |
| --- | --- |
| Local remote URL | `https://github.com/ghadfield32/llm_station.git` |
| Remote default branch | `main` from `git ls-remote --symref origin HEAD` |
| Remote branch heads | `main` and `feat/agent-kanban-surface` resolved with `git ls-remote --heads` |
| Local branch | `feat/agent-kanban-surface` |
| CODEOWNERS path | `.github/CODEOWNERS` exists |
| CI workflow path | `.github/workflows/contracts.yml` exists |
| GitHub CLI | Not installed; `gh` command unavailable |
| GitHub App app id/client/name env refs | Present, checked by key name and length only |
| Private key path | Present, moved outside repo, checked by key name/path presence only |
| GitHub `/app` metadata | 200 via app JWT |
| GitHub `/app/installations` | 200 via app JWT |
| GitHub App installation | Verified for configured owner/repo scope by app JWT discovery |
| Installation token | 201, minted in memory only; token value not printed or stored |
| Selected repository read | `ghadfield32/llm_station` returned 200 |
| Checks/status read | Latest commit check-runs and commit status endpoints returned 200 |
| Repository permission verification | PASS; observed permissions match the approved policy, including operator-approved `issues: read` |
| Branch protection API check | Blocked; app token received 403, so owner/admin verification is still required |
| Owner/admin branch verifier | Added; blocked until `GITHUB_OWNER_ADMIN_TOKEN` is present |
| Token storage / rotation | Drafted in [github-token-storage-rotation.md](../github/github-token-storage-rotation.md); not final until branch-protection verification passes |
| Redacted verifier artifact | `evaluation/system-validation/20260616-autonomy-contracts/github-app-verify.json` |

No tokens, `.env` values, private keys, or raw credentials were printed or
stored. The verifier records key names, presence booleans, lengths, blockers,
and write/secrets flags only.

## Required production auth shape

1. GitHub App installed only on `ghadfield32/llm_station` or an explicitly
   approved repository allowlist.
2. Repository permissions no broader than the autonomous mission needs:
   contents write for branch commits, pull request write for PR creation/update,
   checks/status read for gate observation, metadata read, and explicitly
   approved Issues read for issue visibility. Administration, secrets,
   variables, deployments, environments, workflows, and actions remain forbidden
   for the app.
3. Installation access tokens generated just-in-time by the control plane or
   worker lease holder, never committed, never written into repo-task
   containers, and rotated by GitHub's token lifetime instead of a long-lived
   stored secret.
4. Main branch protected with CODEOWNERS review and required status checks before
   autonomous repo edits can be enabled.
5. Repo-task containers keep `allowed_secrets: []`; the executor receives only a
   scoped, short-lived git credential outside the committed repository.

## Current config state

`configs/autonomy.yaml` now records:

- `github_app_auth.status: blocked`
- `app_name: llm-station-command-center`
- `owner: ghadfield32`
- `homepage_url: https://github.com/ghadfield32/llm_station`
- `webhook_active: false`
- `app_id_env: GITHUB_APP_ID`
- `client_id_env: GITHUB_CLIENT_ID`
- `installation_id_env: GITHUB_APP_INSTALLATION_ID` (optional input; verifier
  can discover by owner after app authentication)
- `private_key_path_env: GITHUB_APP_PRIVATE_KEY_PATH`
- selected repository: `ghadfield32/llm_station`
- token storage policy:
  `env_refs_only_private_key_outside_repo_short_lived_installation_tokens`
- completed work:
  `github_app_installed_on_selected_llm_station_repo`,
  `github_app_installation_token_and_selected_repo_read_verified`,
  `github_app_issues_read_policy_approved`, and
  `github_app_repository_permissions_verified`

## Remaining blockers

1. Provide `GITHUB_OWNER_ADMIN_TOKEN` for a one-run read-only observer check,
   then run `uv run cc branch-protection-verify --output
   evaluation/system-validation/20260616-autonomy-contracts/branch-protection-verify.json`.
   The app itself should not receive administration permission just to inspect
   settings.
2. Document token generation, storage boundary, and rotation after the
   branch-protection gate passes. The draft policy already exists in
   [github-token-storage-rotation.md](../github/github-token-storage-rotation.md).
3. Only then set `auth_mode: github_app` and remove the GitHub auth blocker from
   `configs/autonomy.yaml`.
