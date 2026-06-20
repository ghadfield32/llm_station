# Adding a kanban board

Boards live in `configs/kanban_boards.yaml` (contract `KanbanBoardsConfig`). One
`board_id` maps a surface (**AppFlowy** or the **internal Command Center UI**) to
the repos it drives, the canonical status workflow, required mission-card fields,
and the agent verb contract. Both providers share **one** action contract.

## Register

```bash
uv run cc kanban-register \
  --board-id betts_board \
  --provider appflowy \                # or: command_center_ui
  --workspace-ref env:APPFLOWY_WORKSPACE_ID \   # appflowy MUST be an env: ref
  --board-ref betts_intake \
  --repo-id betts_basketball
```

Dry-run by default (prints the validated block). `--apply` writes it. AppFlowy
`workspace_ref` must be an `env:` reference — an inline value is rejected so no
workspace secret lands in config.

## The canonical contract (enforced by the schema)

- **Statuses** (all seven required): `backlog, ready, in_progress, done, blocked,
  rejected, awaiting_approval`, each mapped to a provider label.
- **Granted verbs** (the agent may do): `add_mission_card, stage_card,
  start_todo, finish_todo, block_card, reject_card`.
- **Wall verbs** (forbidden on every board, always): `approve_card, merge,
  deploy, delete_card, delete_board`. A board cannot grant these.

This is why switching surfaces (AppFlowy ⇄ internal UI) is safe: the approval/merge
wall can't be bypassed by adding a board.

## Verify

```bash
uv run cc kanban-verify --board-id betts_board
# with a board snapshot, it also flags duplicate MissionIDs + unredacted secrets:
uv run cc kanban-verify --board-id betts_board --snapshot generated/board-snapshot.json
```

The snapshot check reports **NOT_RUN** when no snapshot is supplied (never faked).

## Plan a sync (read-only)

```bash
uv run cc kanban-sync --dry-run        # plan: boards -> repos / status mapping; no writes
```

Actual card mutation stays with `cc kanban-bridge --apply` (AppFlowy cards ->
Ledger missions). `kanban-sync` is a planner only.
