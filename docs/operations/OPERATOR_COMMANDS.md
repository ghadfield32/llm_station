# Operator commands — the simple set

You don't have to memorize the full command list. Seven friendly commands cover
day-to-day operation; the lower-level commands stay underneath for evidence and
debugging.

| Command | What it does | Wraps |
|---|---|---|
| `cc doctor` | Preflight readiness checklist | — |
| `cc setup` | `doctor` + registry summary + the exact next steps | `doctor` |
| `cc onboard repo --path <dir>` | Register another local repo (dry-run + gate checklist) | `repo-register` + `repo-verify` |
| `cc onboard kanban --provider <p> --repo <id>` | Register a board for a repo (dry-run + verify) | `kanban-register` + `kanban-verify` |
| `cc operate verify --all` | Verify every board + repo in one call | `kanban-verify` + `repo-verify` |
| `cc improve daily --draft-kanban true` | Daily self-improvement (observer/draft-only) | `self-improvement-daily` |
| `cc demo full-loop --repo <id> --board <id>` | Document + verify the 14-step loop (no writes) | — |

## Onboarding a second repo (disabled, the safe default)

```powershell
uv run cc onboard repo --path C:\docker_projects\my_repo
```

This infers `repo_id` from the folder name, the remote URL from the repo's git
`origin`, and the board id as `<repo_id>_command_center`. It **writes nothing**
without `--apply`; it runs `repo-register` (dry-run) then `repo-verify` and prints
the gate checklist (devcontainer / CI / CODEOWNERS / branch protection / kanban
board mapping / branch-mission / PR-check evidence). The repo's local path is
stored as an `env:` reference — no absolute path is committed. Autonomy stays
**disabled** until every gate is green and you run:

```powershell
uv run cc onboard repo --path C:\docker_projects\my_repo --apply   # writes the disabled manifest
uv run cc repo-enable-autonomy --repo-id my_repo --apply           # only after verify passes
```

## Onboarding a board per repo

```powershell
# internal-UI board (self-hosted, no AppFlowy creds):
uv run cc onboard kanban --provider command_center_ui --repo my_repo
# AppFlowy board (env refs only — no literal ids committed):
uv run cc onboard kanban --provider appflowy --repo my_repo `
    --workspace-ref env:APPFLOWY_WORKSPACE_ID --board-ref env:MY_REPO_BOARD_ID
```

Both go through the **same board registry and action layer** — model code never
writes AppFlowy directly. Canonical statuses + the wall verb set are applied
automatically; wall verbs (approve/merge/deploy/delete) are forbidden on every
board by construction.

See also: [GETTING_STARTED.md](../setup/GETTING_STARTED.md), [ADDING_A_REPO.md](../setup/ADDING_A_REPO.md),
[ADDING_A_KANBAN.md](../setup/ADDING_A_KANBAN.md), [LIVE_KANBAN_SYNC.md](../kanban/LIVE_KANBAN_SYNC.md).
