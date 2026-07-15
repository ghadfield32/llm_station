# Kanban Integration — first-party cockpit

AppFlowy was retired on 2026-07-14. The decision and archive boundary are in
[the retirement record](../decisions/2026-07-14-appflowy-retirement.md).

## Authority and flow

```text
human / chat / Codex / Claude
            |
            v
      governed intent verb
            |
            v
generated/kanban-events.jsonl  (status truth, append-only)
            +
generated/boards/<board_id>/   (typed card fields)
            |
            v
   Agent Kanban Cockpit / Ledger mission lifecycle
```

`CommandCenterBoardProvider` joins the event-log fold with the local card fields.
The UI never needs external board credentials or a snapshot projection. All
surfaces share the same verb contract, and human-owned approval statuses remain
structurally unavailable to agent events.

## Commands

```powershell
uv run cc kanban-verify --all
uv run cc kanban-project
uv run cc kanban-emit --action stage_card --board <board-id> --card <card-id> --source internal_ui --status-after Ready
uv run cc validate
```

Normal card moves happen in the cockpit. `kanban-emit` is the lower-level
operator/debug path and still enforces the wall. There is no `appflowy-up`,
`appflowy-init`, `appflowy-audit`, or AppFlowy bridge command.

## Adding a board

Add a `provider: command_center_ui` entry to `configs/kanban_boards.yaml`, bind a
typed domain in `configs/domain_surfaces.yaml` when it needs a custom card, and
run `uv run cc validate`. `workspace_ref` is `self`; no credential env reference
is accepted.