# RUNDOC — KAN-24 · Master grand-todo board: full cockpit parity

First feature todo through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md)
loop (satisfies PROC-1's end-to-end proof together with the PROC-4 migration).

## 1. Objective & definition of done

The `grand_todo` board (master tracker) gets identical cockpit treatment to
`betts_basketball_grand_todo`: source-sync status chip + "Sync canonical
source" button, in-UI canonical Markdown editor for tracked items, and
API-backed sync/edit endpoints — with **zero** behavior change for the Betts
board.

Done when:
- No remaining hardcoded `betts_basketball_grand_todo` literals in
  `web/src/App.tsx` / `web/src/api.ts` outside one shared constant/flag
  definition; all grand-todo UI gates work for both boards.
- Backend sync + card-edit endpoints accept both domain ids (existing betts
  URL paths keep working — the cockpit bundle in the field calls them).
- Existing tests green + new/extended tests cover the master board's sync,
  edit, and move paths; `npm run build` succeeds.

## 2. Research (verified, 2026-07-23)

Wiring map from a read-only sweep of the repo (line numbers ≈ pre-migration;
the migration commit `adab21a` added `GRAND_TODO_DOMAIN_IDS` +
`_grand_todo_source(domain_id)` + `MASTER_GRAND_TODO_SOURCE` and already
parameterized: routable-domain exclusion, `_allowed_transitions`,
`_todo_audit_fields`, `_domain_cards` source_sync, and the move write-through):

- `services/agent_kanban_ui/app.py` — REMAINING hardcoded literals:
  - `@app.post("/api/domain/betts_basketball_grand_todo/sync")` (~L6280) —
    `sync_grand_todo_source()` calls `run_import(..., apply=True)` with
    `GRAND_TODO_SOURCE`; needs domain-parameterized route + profile.
  - `@app.put("/api/domain/betts_basketball_grand_todo/card/{card_id}")`
    (~L8100) — `edit_grand_todo(card_id, GrandTodoEditIn)` calls
    `edit_grand_todo_card(...)`; same.
  - `add_timeline(..., "grand_todo", "source_revision", ...)` (~L4450) is
    already domain-agnostic (reads card fields) — verify, don't change.
- `web/src/api.ts`: `syncGrandTodoSource()` (~L342) and
  `updateGrandTodoCard()` (~L734) hardcode the betts URL path.
- `web/src/App.tsx`: gates at ~L7459, L7512-7516, L7517-7536, L7599-7614,
  L7792, L7829, L7846, L7976-7978, L8057-8064, L8087-8095, L8416 compare
  `spec.domain_id === "betts_basketball_grand_todo"`.
- Importer seam (done in `adab21a`): `command_center.cli.grand_todo_import`
  exposes `PROFILES` (board_id → BoardProfile), and `run_import` /
  `move_grand_todo_card` / `edit_grand_todo_card` take `profile=`.
- Source paths in-app: `_grand_todo_source(domain_id)` (call-time module-attr
  read — tests monkeypatch `GRAND_TODO_SOURCE` / `MASTER_GRAND_TODO_SOURCE`;
  never snapshot them into a dict at import time).
- Tests pinning current behavior:
  `tests/test_agent_kanban_ui.py::test_grand_todo_api_explicitly_syncs_edits_archives_and_restores`
  (betts paths), `tests/test_domain_surfaces.py` (read-never-writes + domain
  list), `tests/test_todo_routing_workflow.py` (write-boundary refusals).

## 3. KPIs & baseline

- Baseline: master board sync = CLI-only; UI editor/sync button absent;
  betts board fully wired. Test count on affected suites: 215 green.
- Target: both boards expose working sync/edit/move via API + UI; affected
  suites green with ≥3 new master-board assertions; `npm run build` exit 0;
  literal-count KPI: `grep -c betts_basketball_grand_todo web/src/App.tsx`
  drops to ≤1 (the shared constant), api.ts to 0.

## 4. Plan (bounded)

1. app.py: replace the two literal routes with
   `/api/domain/{domain_id}/sync` and
   `/api/domain/{domain_id}/card/{card_id}` handlers that 404/400 unless
   `domain_id in GRAND_TODO_DOMAIN_IDS`, then dispatch with
   `PROFILES[domain_id]` + `_grand_todo_source(domain_id)`. (FastAPI dynamic
   routes match the old literal URLs — deployed bundles keep working.)
   Guard: registered dynamic routes must not shadow other existing
   `/api/domain/...` routes (check route order; more-specific routes first).
2. api.ts: `syncGrandTodoSource(domainId)`, `updateGrandTodoCard(domainId,
   cardId, ...)` — parameterized paths.
3. App.tsx: one exported `GRAND_TODO_DOMAIN_IDS` set (or spec-driven flag if
   the domain spec already carries `intake.producer === "grand_todo_import"`
   client-side — prefer spec-driven if the data is present in the fetched
   spec) + replace every literal gate; thread `spec.domain_id` into the two
   api calls.
4. Tests: extend the grand-todo API test to run for BOTH boards
   (parameterize source monkeypatch: `GRAND_TODO_SOURCE` /
   `MASTER_GRAND_TODO_SOURCE`); keep the read-never-writes invariant test
   for the master board too.
5. Verify: pytest affected suites; `npm ci && npm run build` in
   `services/agent_kanban_ui/web`.

Allowed files: `services/agent_kanban_ui/app.py`,
`services/agent_kanban_ui/web/src/App.tsx`,
`services/agent_kanban_ui/web/src/api.ts`, `tests/test_agent_kanban_ui.py`,
`tests/test_domain_surfaces.py`. Forbidden: importer, configs, docs, any
other file. No dependency changes.

## 5. Open questions

None blocking (operator approved the packet 2026-07-23). Deferred: whether
the master board's UI editor should hide the `**Repo:**` line behind a
dropdown — follow-up under KAN-13, not this packet.

## 6. Model allocation (resolved live 2026-07-23)

- Implementation: `throughput` profile → Codex **gpt-5.6-sol** (priority 1 in
  `codex debug models`, lowest = current), reasoning effort **high**,
  `codex exec --sandbox workspace-write --full-auto` in an isolated worktree
  (`feat/kan-24-grand-todo-ui-parity` off `feat/grand-todo-master`).
- Independent review: Fable (this session's model family, fresh read-only
  pass over the diff — reviewer ≠ author per the workflow); verdict recorded
  below and in WORKLOG.
- Fallback: if Codex write-mode is unavailable/blocked, STOP and surface to
  the operator (no silent Claude-side implementation).

## 7. Links

- Master item: [`docs/todos/GRAND_TODO_LIST.md`](../../todos/GRAND_TODO_LIST.md) → KAN-24
- Board card: `grand_todo` / `grand-todo-kan-24`
- Process: [`docs/todos/TODO_PROCESS.md`](../../todos/TODO_PROCESS.md)

## 8. Execution log

- 2026-07-23 — Run-doc created; packet approved by operator; worktree +
  Codex execution starting. (Append results, review verdict, and evidence
  here as they land.)
