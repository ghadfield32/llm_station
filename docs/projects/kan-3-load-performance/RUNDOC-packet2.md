# RUNDOC — KAN-3 packet 2 · Measure then fix board-switch + notes→books latency

Continuation of [RUNDOC.md](RUNDOC.md) (packet 1 = resilience, merged + live).
Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop; KPI
leaderboard rules apply — **no optimization before measurement**.

## 1. Objective & definition of done

Board switching and notes→books navigation feel instant. Done when: latency
is measured with real numbers (p50/p95, before), the top offender is fixed at
root cause, and the same measurement shows the improvement (after) — recorded
on the card as a leaderboard entry. No behavioral regressions.

## 2. Research (verified, from packet 1's seam map + KAN-26 sweep)

Known facts (measure before believing more):
- `POLL_MS = 5000` global refresh; `refreshGlobal` refetches missions,
  metrics, activity, boards, lanes, status, debug, chat runtime, registered
  repos on every tick — regardless of the active view.
- Grand-todo boards poll per-domain every 15s; `DomainsView` refetches the
  full card list per domain on switch (`/api/domain/{id}/cards`) with no
  client cache; the betts board folds 151 cards server-side per read.
- The books surface loads through the board store + `book_enrich` paths
  (notes→books complaint); server timing unmeasured.
- The cockpit backend is a single uvicorn worker in a container; board reads
  fold event logs server-side (grand reconciliation noted "tens of seconds on
  Docker Desktop bind mounts" in docker-compose comments — plausible root
  cause for board-switch latency, NOT yet proven).

## 3. KPIs & baseline (measure first — this packet's step 1 PRODUCES the baseline)

- Instrument: server-side per-endpoint timing (structured log line with
  route + ms, behind an env flag) + a tiny client perf-mark harness for
  view-switch → first-card-render.
- Collect: p50/p95 for `/api/domain/{id}/cards` per board, `/api/domains`,
  books/notes endpoints, over a realistic session (operator uses the app
  normally for a few minutes, or scripted curl loop).
- Then and only then: fix the top offender; re-measure identically.

## 4. Plan (bounded)

1. Instrumentation (small, merge-worthy on its own): timing middleware in
   `services/agent_kanban_ui/app.py` (route, status, ms — env-gated
   `KANBAN_UI_TIMING_LOG=1`), client perf marks around view switches.
2. Baseline run against the LIVE stack; record numbers in this run-doc.
3. Root-cause the top offender (candidates from §2: event-log fold cost on
   bind mounts, no client cache on domain switch, full refetch cadence).
4. Fix ONE offender at root cause; re-measure; append before/after to the
   card + leaderboard.
5. Repeat 3-4 only if the target ("feels instant", p95 < ~500ms for board
   switch) is still unmet and the next fix is bounded.

Allowed files: `services/agent_kanban_ui/app.py` (timing middleware),
`web/src/App.tsx`/helpers (perf marks, cache if that's the proven fix),
backend board-store read path ONLY if the fold is the proven offender;
tests for whatever changes. Forbidden: speculative caching layers, configs,
anything not justified by a measurement.

## 5. Decisions (defaults)

1. Measurement ships first as its own commit — it's permanently useful.
2. "Instant" target: p95 board switch < 500ms, notes→books < 1s (adjust
   against the baseline once real numbers exist).
3. Fixes are one-offender-at-a-time with before/after evidence (KPI loop).

## 6. Model allocation (resolve live at execution)

- Step 1 instrumentation: Codex (throughput/high) — mechanical.
- Step 3 root-cause: reviewer session drives (measurement analysis), Codex
  implements the chosen fix (deep_code/xhigh if it lands in the event-log
  fold / durable-state path).
- Independent review: Fable, non-author.

## 7. Links

- Card: KAN-3 · packet 1: [RUNDOC.md](RUNDOC.md)

## 8. Execution log

- 2026-07-23 — Packet 2 run-doc created; instrumentation step next.
