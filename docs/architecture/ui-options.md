# UI architecture

The first-party Agent Kanban Cockpit is the only active board UI. It serves the
typed domains, post composer, usage panels, chats, and Codex/Claude agent sessions
from `services/agent_kanban_ui`.

Board fields live in `generated/boards/`; governed status truth is the append-only
`generated/kanban-events.jsonl` fold. No external board server, projection, or
board credentials are required.

See [the retirement decision](../decisions/2026-07-14-appflowy-retirement.md) and
[the cockpit quickstart](../setup/COCKPIT_QUICKSTART.md).
