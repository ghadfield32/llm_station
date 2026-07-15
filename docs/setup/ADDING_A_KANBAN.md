# Adding a kanban board

Boards live in `configs/kanban_boards.yaml` under `KanbanBoardsConfig`. Every
active board uses the first-party `command_center_ui` provider and shares the
same governed event log, card store, status contract, and approval wall.

## Register

```bash
uv run cc kanban-register \
  --board-id betts_board \
  --provider command_center_ui \
  --workspace-ref self \
  --board-ref betts_board \
  --repo-id betts_basketball
```

Dry-run is the default; `--apply` writes the validated block. No board credential
or external workspace reference is accepted.

## Contract

- All canonical statuses are mapped: `backlog`, `ready`, `in_progress`, `done`,
  `blocked`, `rejected`, and `awaiting_approval`.
- Grantable agent verbs are `add_mission_card`, `stage_card`, `start_todo`,
  `finish_todo`, `block_card`, and `reject_card`.
- `approve_card`, `merge`, `deploy`, `delete_card`, and `delete_board` remain
  forbidden on every board.

Bind a specialized card view in `configs/domain_surfaces.yaml` with
`source: board_store` and the same `board_id`, then run:

```bash
uv run cc validate
uv run cc kanban-verify --board-id betts_board
uv run cc kanban-sync --dry-run
```

Normal mutation happens through the cockpit or `cc kanban-emit`; both use the
same event writer. AppFlowy was retired in
[the 2026-07-14 decision](../decisions/2026-07-14-appflowy-retirement.md).