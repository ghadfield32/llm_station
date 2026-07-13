# Security model

The system's safety is **structural**, not policy-by-convention. This document
states the boundaries and why each one holds.

## The two walls

1. **Human approval wall (kanban).** The agent drafts mission cards and moves
   them between non-terminal states; it **cannot** approve. A human drags a card
   to Approved. Every board's verb contract forbids `approve_card` (see
   [ADDING_A_KANBAN.md](../setup/ADDING_A_KANBAN.md)).
2. **Human merge wall (GitHub).** `main` is protected by the
   `protect-main-command-center` ruleset (required PR + 1 CODEOWNERS approval,
   required `validate` + `lint-test` checks, linear history, no force-push, no
   deletion, empty bypass list). The GitHub App can push a feature branch and
   open a PR; it **cannot merge**.

### Merge-wall postures (`RepoManifest.merge_wall`)

The merge wall above is the strongest posture, but GitHub does **not** offer
branch protection / rulesets for a **private repo on a free plan**. Each repo
declares how its merge wall is enforced:

- **`github_branch_protection`** (default, strongest) — server-side ruleset /
  branch protection enforces "no merge without PR + Code Owner review", even if
  the agent misbehaves. Requires a public repo or a paid plan for private repos.
- **`local_pre_push_and_human_merge`** (lower assurance) — for a private repo on a
  free plan. Enforcement = the global agent discipline (the action layer has no
  `merge` verb; direct `main` pushes are refused) **plus** a local `pre-push` guard
  (`cc repo-merge-guard`) that blocks direct pushes to protected branches on this
  machine, **plus** a human doing the merge. There is **no server-side backstop**:
  the App token technically *could* push `main` if the agent code were buggy or
  compromised. This posture is chosen deliberately, per repo, and is always
  recorded as `lower_assurance` — never reported as "branch protection verified".

## What the agent can and cannot do

| Can | Cannot |
|---|---|
| Read boards, repos, evidence | Approve a card / merge a PR |
| Draft `Proposed` cards | Deploy, publish, rotate secrets |
| Open a PR via the GitHub App | Push to `main` directly |
| Run bounded L0–L2 repo missions | Weaken branch protection / bypass checks |
| Propose updates to itself | Self-approve, self-merge, self-widen permissions |

The daily self-improvement loop runs through the **ObserverCharter**, whose object
literally has no `promote`/`merge`/`deploy`/`set_status` method — accessing one
raises `CharterViolation`. A buggy or compromised scan cannot escalate.

## Secrets

- Provider API keys are **forbidden** by contract (`cc validate` fails on any).
  Model calls go to local Ollama; Claude/Codex executors use their own logins.
- `.env` holds local secrets and is never committed or mounted into a repo task
  container (`secret_policy: no_runtime_secrets_inside_container`).
- Configs **name** env keys; they never hold values. Cross-conversation memory
  rejects secret-bearing values at write time and stores no secrets.
- The GitHub App private key path lives outside the repo; tokens are short-lived,
  minted in memory, never printed or written to evidence.

## GitHub App permissions (least privilege)

`metadata:read`, `contents:read_write`, `pull_requests:read_write`,
`checks:read`, `statuses:read`, `issues:read`. **No** `workflows`, `administration`,
`secrets`, `deployments`, `actions`. See gotchas in
[TROUBLESHOOTING.md](../setup/TROUBLESHOOTING.md) (workflow changes need human creds; a
PR's last reviewable pusher must differ from its approver).

## Desktop automation

Disabled by default and **canary-gated**: read-only verifier -> no-op canary ->
representative action-latency evidence -> data-derived TTL/action-timeout -> human
takeover hotkey + redaction policy -> single staging live action. No clipboard or
password reads, no destructive clicks, no production live action until every gate
passes with **real measured evidence** (never placeholder timing values).
