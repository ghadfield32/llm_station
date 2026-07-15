# AppFlowy retirement archive

Status: retired from active runtime on 2026-07-14.

AppFlowy was replaced by the repository's first-party Agent Kanban Cockpit because
the owned surface is faster to update, better aligned with Codex/Claude sessions,
and easier to adapt to this project's typed workflows and usability needs. The
cockpit now owns board rendering, governed status events, typed domain cards,
post composition, provider-session selection, and local board storage.

This directory is retained only for provenance and rollback analysis:

- `AppFlowy-Cloud/` is the former pinned upstream checkout.
- `legacy-growth-os/` contains the retired network client and setup/runtime files.
- the setup and upgrade reports describe historical deployments, not current steps.

Do not start services or copy credentials from this archive. Current setup is in
`docs/setup/COCKPIT_QUICKSTART.md`; current board state lives in
`generated/kanban-events.jsonl` plus `generated/boards/` and remains governed by
the existing human approval wall.

Historical evidence, sealed evaluations, and dated worklog entries may still name
AppFlowy. They are intentionally not rewritten because they describe what was true
when captured; this retirement record supersedes them for current operations.