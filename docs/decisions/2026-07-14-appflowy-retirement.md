# AppFlowy retirement decision — 2026-07-14

Decision: AppFlowy is archived and is no longer an active service, board provider,
health check, configuration source, or setup option in LLM Station.

## Why

The first-party Agent Kanban Cockpit is a better fit for this system. It can be
updated alongside the typed contracts, presents the domain-specific cards the
workflows need, integrates Codex and Claude agent sessions directly, and gives us
control over mobile usability, post composition, observability, and governed
status transitions without translating through a second product.

Maintaining both surfaces added credentials, containers, snapshots, projection
reconciliation, REST limitations, and two places for operators to look. Those
costs no longer bought a capability the owned cockpit lacked.

## Current authority

- Board fields: `generated/boards/` through `CommandCenterBoardProvider`.
- Status: the append-only `generated/kanban-events.jsonl` fold.
- UI and chat: `services/agent_kanban_ui` plus the host agent worker.
- Approval wall: unchanged. Agents still cannot approve, merge, deploy, publish,
  delete cards, or delete boards.
- Posts: composed and reviewed on the first-party Posts board; LinkedIn publishing
  remains an explicit operator-run external action with its durable dedupe ledger.

## Archive boundary

The former pinned server, client, setup scripts, and deployment reports are under
`archive/appflowy/` for provenance and rollback analysis only. They are not part
of normal install, validation, doctor, compose, or CLI help. Dated worklogs,
sealed evaluations, and historical evidence may still mention AppFlowy and are
not rewritten because that would falsify captured history.

## Migration and rollback

No external subscription dates or credentials are copied into the replacement.
Existing local cockpit cards remain authoritative. If historical AppFlowy data
must be recovered, export it from the archived deployment in an isolated manual
migration and import fields into the first-party board store; do not restore the
old server to the default compose path.