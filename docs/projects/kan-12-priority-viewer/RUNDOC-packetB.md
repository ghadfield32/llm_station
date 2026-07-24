# RUNDOC — KAN-12 packet B · The priority viewer strip (frontend)

Continuation of packet A (merged #86: priority/impact/timeline are first-class
card fields + `/api/todos` filter). Through the
[`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop.

## 1. Objective & definition of done

A persistent, filterable priority strip sits above the board tabs, reads the
active board, lets me filter/search by priority level, and links to Work Map.
Done when: a strip renders above `domain-tabs` in DomainsView showing a
priority summary for the active grand-todo board (counts by P1/P2/P3), with a
priority filter that narrows the visible cards, a search box, and a Work Map
link; `npm run build` green; the frontend guardrail tests still pass.

## 2. Research (verified seam map, 2026-07-24; packet-A merged main)

- Priority is now a real card field (packet A): grand_todo cards carry
  `priority` (P1/P2/P3), and the frontend `cardPriority()` (App.tsx ~L179-205,
  `CARD_PRIORITY_FIELDS` includes `"priority"`) already surfaces it in card
  disclosures. So the data is present client-side today.
- Mount point: DomainsView (def ~L7700); render top-of-boards order is
  `<HorizontalScroller className="domain-tabs">` (~L8071) then
  `<div className="domain-head">` (~L8079). The strip mounts just ABOVE
  `domain-tabs` so it sits over the columns and reacts to `spec.domain_id` /
  `activeDomain`.
- Filter precedent to reuse: the shared `FilterBar` (~L158-177,
  `filterbar`/`search`/`select`/`clear`) and the DomainsView generic filter
  bar (~L8275-8303) with `qByDomain`/`statusByDomain` per-domain state maps.
  The strip adds a per-domain `priorityByDomain` map in the same idiom.
- Work Map: view id `"work-map"`, reachable via `setView("work-map")` (nav at
  ~L84, WorkMapView ~L11326). The strip's Work Map link flips the view.
- Card filtering: the board columns render the domain's cards; the priority
  filter narrows which cards show, reusing whatever the existing
  q/status filter path does (do NOT rebuild the column render — hook the
  priority predicate into the same visible-cards computation).
- DESIGN.md governs: tokens only, fit-to-screen (the strip must not force
  page-level horizontal scroll at 390px), bounded selects.
- Guardrail: `test_todo_routing_workflow.py::test_frontend_exposes_reviewed_chat_and_capture_routing_flow`
  reads App.tsx/AllTodosView.tsx for specific substrings — must keep
  `buildTodoSections`, `General & unassigned`, `row.repo_ids.map`.

## 3. KPIs & baseline

- Baseline: no priority strip; priority visible only per-card in disclosure;
  no priority filter on the board view.
- Target: strip renders for grand-todo boards; priority filter narrows cards;
  P1/P2/P3 counts shown for the active board; Work Map link present; build
  green; no new page-level horizontal scroll at 390px; guardrail strings kept.

## 4. Plan (bounded — frontend only)

1. A `PriorityStrip` component (in App.tsx near DomainsView) that, given the
   active domain's cards, shows P1/P2/P3 counts (from `cardPriority`), a
   priority `<select>` (All/P1/P2/P3), a search input, and a "Work Map" button
   (`onClick={() => setView("work-map")}`), all in the `filterbar` idiom with
   bounded `.select`.
2. `priorityByDomain` state map (mirror `qByDomain`) in DomainsView; the strip
   sets it; the visible-cards computation for the board gains a priority
   predicate (`!filter || cardPriority(card) === filter`).
3. Mount the strip above `domain-tabs`, rendered for grand-todo domains (and
   any domain whose cards carry priority) — reuse `isGrandTodoDomain` /
   feature-detect `cardPriority` non-empty across the domain's cards so it
   auto-appears wherever priority exists.
4. Styles in styles.css using existing tokens (no new hex); the strip is a
   `filterbar`-class row + count chips; fits 390px.
5. Verify build + the frontend guardrail test; keep the pinned substrings.

Allowed files: `services/agent_kanban_ui/web/src/App.tsx`,
`services/agent_kanban_ui/web/src/styles.css`, this RUNDOC. Forbidden:
backend (packet A shipped it), api.ts contract changes, package.json,
AllTodosView.tsx unless a tiny reuse is cleaner (prefer not).

## 5. Decisions (defaults)

1. Areas-of-life filter (home/study/work/…) is a SECOND slice — this packet
   ships the priority strip + Work Map link; areas-of-life rides KAN-12
   packet C or KAN-28 (they share the same strip). Recorded so nothing is
   lost.
2. The strip auto-appears wherever cards carry priority (feature-detected),
   not hardcoded to grand_todo — so personal_todos etc. benefit too.
3. No new test runner; verify via build + the existing backend guardrail
   (web/ has only node:test over pure helpers — a pure `priorityCounts`
   helper is extracted if logic warrants a unit test).

## 6. Model allocation (resolve live 2026-07-24)

- Implementation: `throughput` → current lowest-priority Sol model via
  `codex debug models` at launch, effort high (bounded UI), isolated worktree
  off origin/main, detached, fail-closed. Under DESIGN.md.
- Independent review: Fable (non-author), DESIGN.md + fit-to-screen lens.

## 7. Links

- Card: KAN-12 · Packet A: [RUNDOC.md](RUNDOC.md) (merged #86) · Work Map
  shared with KAN-28.

## 8. Execution log

- 2026-07-24 — Packet B run-doc created from the packet-A-merged seam map;
  launching. NOTE: #90 (AGT reconcile) also touches App.tsx and is pending
  merge — if it lands first, rebase this branch.
- 2026-07-24 — Codex gpt-5.6-sol (high) implemented the App.tsx side
  completely: `PriorityStrip` component, `priorityByDomain` state, filter
  predicate `(!priority || cardPriority(card) === priority)` in the visible-
  cards path, `hasPriority` feature-gate, mount above `domain-tabs`,
  `onOpenView` threaded App→DomainsView→strip and wired to `setView`, and
  clear-resets. Its run was CUT OFF by a Codex CLI internal error
  (`failed to renew cache TTL: missing field supports_reasoning_summaries`)
  before it wrote styles.css, verified, or committed — a tool crash, not a
  task fault.
- 2026-07-24 — Reviewer completed + verified: added the tokens-only
  `.priority-strip`/`.priority-counts`/`.priority-count-chip` CSS Codex was
  cut off before writing (filterbar-based, flex-wrap + min-width:0 for
  390px). Host verification: `npm ci` (transient EPERM on first try, clean on
  retry) + `npm run build` exit 0; `npm test` exit 0; no new hardcoded hex;
  frontend guardrail `test_todo_routing_workflow` + `test_agent_kanban_ui`
  green (pinned substrings intact). Independent review (Fable, DESIGN.md +
  fit-to-screen lens): APPROVED — strip auto-appears only where priority
  exists, shares existing per-domain filter state, no page-level horizontal
  scroll. Areas-of-life filter deferred to a later slice (recorded in §5).
