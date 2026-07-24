# RUNDOC — KAN-28 packet 1 · Nav reorg (chat-first sidebar + tab audit)

Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop. KAN-28 is
broad; this packet ships the bounded, highest-value slice: **the sidebar
reorder (Chat first, Kanbans second) + tab audit (Activity folded, Work Map
placement confirmed)**. Deferred to packet 2 (recorded §5): Life Center as
its own board with links atop, and chat popping up on "New".

## 1. Objective & definition of done

The sidebar leads with Chat, then Kanban Boards, then the rest — matching how
the operator actually works. Activity stops being a top-level tab (it's a
review option, not a primary destination). Work Map is reachable atop the
boards (already shipped via #92's PriorityStrip button — verify + keep).
Done when: Chat is the first nav item and Kanban Boards second; Activity is
no longer a primary top-level nav button (reachable but demoted); `npm run
build` green; the frontend guardrail tests stay green.

## 2. Research (verified seam map, 2026-07-24; main @ 44bb172)

- `type View` (App.tsx L79) enumerates all views incl. `chat`, `work-map`,
  `life-center`, `activity`.
- `const NAV` (L80-92) is the top-level sidebar order: domains(Kanban Boards),
  life-center, todos(Master TODO List), work-map, inbox, settings(Controls),
  router, diagnostics(Status), observability(Metrics), usage, activity.
- `const nav = [...NAV, { id: "chat", label: "Chat" }]` (L11627) — **Chat is
  appended LAST today.** The sidebar renders `nav.map(...)` (L11642-11648)
  then the per-board `domain-nav-section` (L11650-11663).
- Work Map atop boards: **already delivered by #92** — the PriorityStrip
  (DomainsView) has a "Work Map" button → `onOpenView("work-map")`
  → `setView`. No new Work Map wiring needed here; verify it's present.
- Activity: nav id `activity`, count `activity?.calls.length` (L11631);
  view mounts in the router. Demote = remove from the primary NAV array
  (keep the view + VIEW_IDS so deep links still work), optionally surface it
  under a secondary/less-prominent spot.
- Guardrail: `test_todo_routing_workflow.py::test_frontend_exposes_reviewed_chat_and_capture_routing_flow`
  reads App.tsx substrings — must keep `buildTodoSections`,
  `General & unassigned`, `row.repo_ids.map`.

## 3. KPIs & baseline

- Baseline: Chat is the LAST sidebar item; Activity is a primary top-level
  tab; 11 primary NAV entries.
- Target: Chat is FIRST, Kanban Boards second; Activity demoted from the
  primary NAV array (view still reachable via VIEW_IDS/deep-link); build +
  guardrail green.

## 4. Plan (bounded — frontend only)

1. Reorder so Chat leads: build `nav` as `[{id:"chat",label:"Chat"},
   ...reordered NAV]` where the reordered NAV starts with domains(Kanban
   Boards). Move `chat` out of the trailing append into the front; keep every
   other entry, just reordered (chat, domains, then the current rest minus
   activity).
2. Demote Activity: remove the `{id:"activity"}` entry from the primary NAV
   array. Keep `"activity"` in the `View` type and `VIEW_IDS` and its router
   mount so deep links / the Metrics area can still reach it (do NOT delete
   the view). If there's a natural secondary spot (e.g. a small link in the
   Metrics/Status view header), add it there; otherwise leaving it
   deep-link-only is acceptable for packet 1 (record it).
3. Confirm Work Map atop boards: verify the PriorityStrip Work Map button
   exists and works (#92); no change unless it regressed.
4. No new CSS unless strictly needed (reorder uses existing `.navitem`).
5. Verify build + frontend guardrail; keep the pinned substrings.

Allowed files: `services/agent_kanban_ui/web/src/App.tsx`, optionally
`services/agent_kanban_ui/web/src/styles.css` (only if a tiny nav tweak
needs it), this RUNDOC. Forbidden: backend, api.ts, package.json (no test
deps), AllTodosView.tsx.

## 5. Decisions (defaults) + deferred slices

1. Packet 1 = sidebar reorder + Activity demotion + Work Map verify. **Packet
   2 (recorded, not lost):** Life Center as its own board with links atop;
   chat surfacing as an option while viewing kanbans + popping up on "New";
   the OpenRouter/leaderboard surface (KAN-29) is its own separate item.
2. Activity demotion keeps the view alive (deep-link/secondary), never
   deletes it — no functionality lost, only nav prominence changed.
3. Work Map atop boards is already satisfied by #92; this packet only
   verifies, avoiding duplicate buttons.

## 6. Model allocation (resolve live 2026-07-24)

- Implementation: `throughput` → current lowest-priority Sol model via
  `codex debug models` at launch, effort high (bounded nav edit), isolated
  worktree off origin/main, detached, fail-closed. Under DESIGN.md.
- Independent review: Fable (non-author).

## 7. Links

- Card: KAN-28 · Work Map button shipped in #92 (KAN-12 packet B) ·
  Related: KAN-27 (chat controls), KAN-29 (OpenRouter leaderboard).

## 8. Execution log

- 2026-07-24 — Run-doc created from the nav seam map; packet 1 launching.
- 2026-07-24 — Packet 1 implemented in `App.tsx`: Chat now leads the
  rendered primary nav, Kanban Boards remains second, and every remaining
  `NAV` item keeps its prior relative order. Activity was removed only from
  primary `NAV`; it remains in `View`, is explicit in `VIEW_IDS`, and its
  router mount remains intact. Activity is deep-link-only in this packet
  because Metrics and Status have no existing header/action seam suitable
  for a clean minimal secondary entry point.
- 2026-07-24 — Verified the existing PriorityStrip Work Map button remains
  above priority-enabled domain boards and calls `onOpenView("work-map")`;
  no duplicate or CSS change was added. The TODO guardrail markers remain
  intact in the untouched `AllTodosView.tsx`.
- 2026-07-24 — Verification: `npm ci --no-audit --no-fund` failed twice at
  sandbox-blocked child-process spawn/cleanup (`EPERM`); recovery
  `npm ci --ignore-scripts --no-audit --no-fund` succeeded. `npm test`
  passed all 41 subtests. `npm run build` completed `tsc` successfully, then
  failed when Vite/esbuild hit `spawn EPERM`. The requested Python command
  collected 110 tests but all errored before test bodies during pytest temp
  fixture setup (`PermissionError`); alternate basetemp retries were blocked
  by the same Windows ACL condition. Fail-closed: not staged, committed, or
  pushed because the mandatory build and guardrail were not green.

