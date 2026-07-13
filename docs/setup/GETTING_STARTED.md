# Getting started

llm_station / Command Center is a **local LLM control plane** that drives kanban
work through one action layer and one human approval wall. This is the 10-minute
path from a fresh clone to "the loop is wired."

> New machine? See [INSTALL_WINDOWS.md](INSTALL_WINDOWS.md) /
> [INSTALL_WSL.md](INSTALL_WSL.md) first. The full system map is
> [MASTER.md](../MASTER.md); the security boundaries are
> [SECURITY_MODEL.md](../architecture/SECURITY_MODEL.md).

## 1. Prerequisites

Docker, [uv](https://docs.astral.sh/uv/), Ollama, and git. Then:

```bash
git clone --recurse-submodules https://github.com/ghadfield32/llm_station.git
cd llm_station
uv run cc doctor          # green/red preflight — fix what it flags
```

`cc doctor` reports each check as **PASS / FAIL / BLOCKED / NOT_RUN** with the
exact next command. It never hides a failure.

## 2. Bring up the control plane

```bash
uv run cc init-env        # create .env with LOCAL secrets (no provider keys)
uv run cc models-light    # pull a small local model (~5 GB qwen3:8b)
uv run cc start           # one button: doctor -> build -> up -> health -> open UIs
uv run cc live-smoke      # prove real local replies through Ollama -> LiteLLM
```

Pick your board surface:

- **AppFlowy** (drag-to-approve boards): `uv run cc start --appflowy`.
- **Internal Command Center UI** (the recommended cockpit; `uv run cc start`
  already brings it up): `docker compose --profile ui up -d --build agent-kanban-ui`.

Both drive the **same action contract** — see [ADDING_A_KANBAN.md](ADDING_A_KANBAN.md).

## 3. Verify the autonomy loop is wired

```bash
uv run cc kanban-verify --board-id llm_station_command_center
uv run cc repo-verify   --repo-id  llm_station
uv run cc demo full-loop --repo llm_station --board llm_station_command_center
```

`cc demo full-loop` prints the canonical 14-step loop (mission card -> human
approve -> branch/worktree/devcontainer -> tests -> PR -> human approve -> human
**merge** -> daily DAG -> self-improvement card -> report) and marks each step
`VERIFY` / `AUTOMATABLE` / `HUMAN_GATE`. It performs **no writes and never merges**.

## 4. Daily operation

| You want to… | Command |
|---|---|
| Talk to it | `uv run cc channel telegram` (or discord/slack/whatsapp) |
| Onboard another repo | [ADDING_A_REPO.md](ADDING_A_REPO.md) |
| Add a board for it | [ADDING_A_KANBAN.md](ADDING_A_KANBAN.md) |
| Run the daily self-improvement scan | [RUNNING_DAILY_SELF_IMPROVEMENT.md](../operations/RUNNING_DAILY_SELF_IMPROVEMENT.md) |
| Remember a project fact across chats | `uv run cc memory-add --scope project --subject <repo> --value "…" --source-ref <ref> --approved-by <you>` |
| Day-to-day ops + emergency stop | [OPERATIONS_RUNBOOK.md](../operations/OPERATIONS_RUNBOOK.md) |
| Something's broken | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

## The one rule that makes it safe

The agent can **draft** cards and **open PRs**, but it can **never approve its
own work, merge, deploy, publish, rotate secrets, or weaken branch protection.**
You approve by dragging a card to Approved and by merging the PR. That wall is
structural (CODEOWNERS + the `protect-main-command-center` ruleset + the
ObserverCharter), not a convention.
