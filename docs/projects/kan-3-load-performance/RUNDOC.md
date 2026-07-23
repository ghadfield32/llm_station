# RUNDOC — KAN-3 · Load performance + zero "Load failed"

Next todo through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop
(queued 2026-07-23 after KAN-24 proved the loop). Status: **stage 3-4 —
run-doc drafted, awaiting KPI-meeting answers before execution.**

## 1. Objective & definition of done

The cockpit never surfaces "boards: Load failed" / "router: load failed",
survives app-switching (iOS PWA backgrounding) without losing state, and
board/notes navigation feels instant. Done when the §3 KPIs are met and the
error strings cannot appear for transient causes.

## 2. Research (verified 2026-07-23, code-level)

- **Error surface**: `web/src/App.tsx` ~L11696-11697 renders
  `boards: {boardsNote}` and `router: {lanesNote}` inside the
  `surface-errors` banner; DiagnosticsView (~L2771) mirrors them.
- **Root cause of "Load failed"**: `reloadBoards` (~L11483-11488) does
  `setBoards(null); setBoardsNote((e as Error).message)` on ANY rejection —
  one transient failure **discards the already-loaded data** and prints the
  raw browser error. On WebKit (iPhone), a fetch killed by backgrounding
  rejects with `TypeError: Load failed` — hence the exact message. The
  lanes/router load and the `surfaceErrors` map (missions/observability/
  activity) follow the same null-out pattern (~L11530-11540).
- **App-switch failure mode**: iOS Safari cancels in-flight fetches on
  background; on return the UI shows the error until the next poll tick.
  There is no `visibilitychange` re-fetch hook and no retry/backoff.
- **Polling model**: `POLL_MS = 5000` (App.tsx ~L110) global refresh cadence;
  board-store domains also poll per-domain (15s for grand-todo boards). Full
  refetches on every tick are the first suspect for slow board switching —
  needs per-endpoint timing before changing anything (§5 Q2).
- **Notes→books slowness**: not yet measured — backend book/notes endpoints
  need timing probes before blaming frontend or backend (§5 Q2). Book
  enrichment work exists in `book_enrich.py`; do not guess.

## 3. KPIs & baseline (to finalize in the KPI meeting)

- Zero-transient-error KPI: backgrounding the app / toggling networks
  produces 0 user-visible "Load failed" banners (manual repro script), while
  REAL outages (backend down) still surface honestly within one poll cycle.
- Navigation latency KPI: board switch p50/p95 (measure first — baseline
  unknown; capture via browser perf marks before optimizing).
- Notes→books latency KPI: p50/p95 endpoint timing, before/after.
- No regression: all existing UI/API tests stay green.

## 4. Plan (bounded, pending §5 answers)

1. Keep-last-good state: on fetch rejection, retain previous data, mark a
   `stale` flag + timestamp instead of nulling; banner only after N
   consecutive failures or on explicit refresh.
2. Classify errors: swallow AbortError / background-kill TypeError as
   silent-stale; real HTTP/network errors count toward the banner.
3. `visibilitychange` hook: immediate quiet re-fetch when the app returns to
   foreground.
4. Measure then fix latency: add timing probes for board-switch and
   notes→books paths; optimize the top offender only, with before/after
   numbers (KPI leaderboard entry per attempt).
5. Tests: unit tests for the stale-state reducer + error classifier;
   existing suites green.

Allowed files (draft): `web/src/App.tsx`, `web/src/api.ts`, new small
frontend test file; backend timing probes if §5 Q2 lands backend-side.

## 5. Open questions — RESOLVED 2026-07-23 (best-practice defaults per
operator's "research and implement best practices" directive; adjust anytime)

1. Real outages stay loud but debounced: banner only after **2 consecutive**
   failed polls; a subtle "stale since HH:MM" chip appears immediately on the
   first failure. Transient background-kill errors never count.
2. **Yes — split.** Packet 1 (this run): resilience / zero-transient-error.
   Packet 2 (separate): latency measurement then optimization of the top
   offender (board-switch, notes→books).
3. Repro matrix: iPhone Safari (PWA) + desktop Chrome.

## 6. Model allocation (resolve live at execution)

- Implementation: `throughput` → current lowest-priority Sol model via
  `codex debug models` at execution time (2026-07-23 resolution:
  gpt-5.6-sol), effort high, isolated worktree. Frontend-state work is
  bounded and mechanical once the design in §4 is fixed.
- Independent review: Fable/Opus (non-author), read-only diff pass.
- Lesson applied from KAN-24: no launch-wrapper timeout shorter than the
  verify phase.

## 7. Links

- Master item: [`docs/todos/GRAND_TODO_LIST.md`](../../todos/GRAND_TODO_LIST.md) → KAN-3
- Board card: `grand_todo` / `grand-todo-kan-3`
- Related: KAN-4 (fit-to-screen), KAN-5 (books control), KAN-10 (board
  position memory) — same surfaces, separate packets.

## 8. Execution log

- 2026-07-23 — Run-doc drafted with code-verified root cause; awaiting §5
  KPI-meeting answers.
