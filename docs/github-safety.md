# GitHub safety — the hard boundary

The agent may: read repo, create branch, push **feature** branch, open/update PR, comment, read CI status.
The agent may NOT: push main, merge, delete branches, change settings/protections, administer secrets, publish, deploy, bypass checks.

## Protect main (run once per repo, with YOUR admin token)
```bash
OWNER=your-username; REPO=betts_basketball; GH=ghp_admin_token
curl -sS -X PUT -H "Authorization: Bearer $GH" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/branches/main/protection" \
  -d '{
    "required_status_checks":{"strict":true,"contexts":["validate / tests","validate / lint","validate / typecheck","validate / secret-scan"]},
    "enforce_admins":false,
    "required_pull_request_reviews":{"required_approving_review_count":1,"require_code_owner_reviews":true,"dismiss_stale_reviews":true},
    "restrictions":null,"required_linear_history":true,"allow_force_pushes":false,
    "allow_deletions":false,"required_conversation_resolution":true
  }'
```
Keep `enforce_admins:false` so YOU can fix emergencies; never give the agent an admin token.

## CODEOWNERS
Use `repo-template/CODEOWNERS` — a matching owner review becomes mandatory before merge.

## Agent token (fine-grained PAT for MVP; GitHub App long-term)
Contents R/W · Pull requests R/W · Issues R · Metadata R · everything else **No access**.
A GitHub App is better long-term: Apps start with zero permissions; grant only the minimum. PATs act as you and are worse for long-lived automation.

## Required CI
`repo-template/.github/workflows/validate.yml` provides the four required checks referenced above.

## Deploy = separate human-gated environment
Settings → Environments → `production` with a required reviewer and "prevent self-review". Deploy jobs reference `environment: production` and pause for a human. The agent never gets the environment's secrets.

## In-sandbox command policy (defense in depth)
allow: git status/diff/log, grep/rg/find, pytest/mypy/ruff, create branch, edit files (after plan), install deps (logged).
push: only after `scripts/pre_push_gate.sh` exits 0.
deny: read .env / keys, sudo, rm -rf, chmod -R, curl|bash, force push, merge.
