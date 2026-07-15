# Growth OS — first-party board harness

Growth OS supplies the reusable action, memory, curation, and observability layer
for the Command Center cockpit. As of 2026-07-14 it writes only to the cockpit's
governed event log and local board stores (`generated/kanban-events.jsonl` and
`generated/boards/`). It has no AppFlowy server, credential, or projection dependency.

The former AppFlowy implementation and setup material are preserved read-only under
`archive/appflowy/` for provenance. Current operators should start the main compose
stack and use the cockpit at `http://127.0.0.1:8787`.

Runtime paths can be overridden with `GROWTHOS_BOARD_STORE` and
`GROWTHOS_KANBAN_EVENT_LOG`. The cockpit compose service sets both to its mounted
`/snapshot` volume. Agent-call observability continues to use
`GROWTHOS_AGENT_LOG`.