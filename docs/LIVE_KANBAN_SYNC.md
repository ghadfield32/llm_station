# Live kanban sync — one event stream, many projections

The goal: a governed action on **any** surface (Discord, SMS, the internal UI,
the daily DAG, a repo agent) shows up on every other surface right away or
near-real-time, and the evidence is stored once.

The way we get there **without** chaos: surfaces do not each hold their own
truth. There is one source of truth and everything else is a projection of it.

```
Discord / UI / SMS / AppFlowy / daily DAG / repo agent
        ↓ (call the governed action — the only legal writer)
Kanban event log = source of truth   (generated/kanban-events.jsonl)
        ↓ (projections derive from events)
internal UI board   +   AppFlowy board   +   reports
```

- **Source of truth:** the append-only kanban **event log**. Every card change is
  one `KanbanEvent`.
- **The only legal writer:** `emit_event`. The governed action layer funnels
  through it (see *Activation* below), and `cc kanban-emit` exposes it directly.
- **The wall is structural, on the action AND the status value:**
  - Wall *actions* (`approve_card`, `merge`, `deploy`, `delete_card`,
    `delete_board`) raise `GovernanceViolation` — they have no event mapping.
  - A permitted verb still cannot carry a human-owned **status**: any
    `status_after` that normalises to an approval state (`Approved` / `approved` /
    `Awaiting Approval` / `awaiting_approval` — case- and space/underscore-folded)
    is rejected at `emit_event` *and* in the `KanbanEvent` validator, and
    `AppFlowyProjection.write_through` refuses to write one. So an agent can never
    emit, project, or write an approval. Approval stays human-only.
- **Projections:** the internal UI and AppFlowy render *from the event log*. They
  never invent state.

## The three levels (built in order)

### Level 1 — immediate internal UI sync (done)

The UI subscribes to the event log over SSE and moves cards as events arrive — no
manual refresh.

- `GET /api/events/kanban/snapshot` → folded current card state (initial load).
- `GET /api/events/kanban` → SSE stream. Each frame carries `id: <resume-offset>`,
  so the browser records it as `Last-Event-ID`; on auto-reconnect the browser sends
  that header and resumes exactly where it left off — **no replay, no manual
  refresh**. (Poll-stream with auto-reconnect, not a persistent push — documented
  honestly. The reconnect is automatic and fast, so the board feels live.)

Proven by `tests/test_kanban_ui_events.py`: a `stage_card` shows up in the UI
snapshot **and** the SSE stream tagged with its `source_surface`, and a reconnect
via `Last-Event-ID` returns only the new event.

### Level 2 — AppFlowy near-live sync (write-through + verify + reconcile)

AppFlowy is **not** assumed to have a realtime watch API. The honest contract is:

- **Write-through** (`AppFlowyProjection.write_through`): after a governed event,
  set the card's status on the AppFlowy board. **Fails closed** when the board env
  is absent → `degraded`, never a fake `PASS`.
- **Read-back verify** (`cc kanban-verify-projection --snapshot`): compare an
  AppFlowy snapshot to the event-log fold. Mismatch → `BLOCKED`. No snapshot →
  `DEGRADED`.
- **Reconcile** (`cc kanban-reconcile --snapshot [--apply]`): compare the board to
  the log; classify each difference as **drift** (projection lag — repairable) or
  **conflict** (a human moved the card into an approval state — `review_required`).
  `--apply` repairs **drift only**; it never touches conflicts and never approves,
  merges, or deletes.

This is not fake live — it is *write-through + verify + reconcile*. If AppFlowy
later exposes a reliable event/webhook, add it as an optimization; the contract
does not require it.

### Level 3 — live writing feel

- Model thinking / tool events already stream in chat (`/api/chat/stream`).
- For card drafting, show the draft as a **UI preview first**, then commit the
  final card through `add_mission_card` (which emits `kanban.card.created`). Do
  **not** stream half-written content into production AppFlowy cards.

## Conflict policy (never silent last-write-wins)

- The Ledger / event log **wins for agent-owned fields** (card status the agent set).
- **Human approval fields are never overwritten.** A board status that normalises
  to an approval state (`Approved`/`approved`/`Awaiting Approval`/`awaiting_approval`
  — case- and space/underscore-folded, so the capitalized `mission_intake` board
  and the lowercase `missions` board are both covered) → `review_required`.
- **A human re-opening a terminal card** (the log says `Rejected`/`Done` but the
  board moved it elsewhere) → `review_required`, never silently reverted.
- A card on the board that the event log never produced → `review_required`
  (human-created; the agent does not delete it).
- Otherwise a divergence is repairable **drift**. `cc kanban-reconcile --apply`
  repairs drift only, writing the **folded target status** (not the card's last
  event, which may be a progress comment), and `write_through` still refuses to
  write any human-owned status. Conflicts are never auto-repaired.

## Activation (wiring the action layer to the event log)

The engine is wired into the **one governed action layer** that every channel
shares (`GatewayCore`), so a granted card/todo verb on any surface emits an event.
Emission is **the standard path — ON BY DEFAULT** (no flag needed); it is the
single sync mechanism for every governed kanban write. The states:

- **default (no flag)** — emission is **active as soon as a board resolves**: a
  single registered board is used automatically, or `KANBAN_PRIMARY_BOARD_ID`
  selects one when several are registered. If multiple boards are registered and no
  primary is set, emission is **inactive with a clear reason** (surfaced by
  `cc setup`) — it does not guess and does not crash.
- `KANBAN_EMIT_EVENTS=0` — explicit **opt-out** (turn emission off).
- `KANBAN_EMIT_EVENTS=1` — explicit **opt-in**; if a board can't be resolved,
  construction **fails loudly** (you asked for it, so the misconfig is surfaced).
- `KANBAN_EVENT_LOG=<path>` — the event log path, shared with the UI service
  (defaults to `generated/kanban-events.jsonl`).

So by default `stage_card` on Discord/SMS/the in-app console/CLI all funnel through
`emit_event` → the same log the UI SSE and AppFlowy projection read. Non-governed
verbs (search/list/read) are untouched; model code never writes AppFlowy directly.
Run `cc setup` to see whether emission is ACTIVE, which board it tags, and — if
inactive — exactly what to set.

## Commands

| Command | What it does |
|---|---|
| `cc kanban-emit --action stage_card --board B --card C --source discord --status-after Ready` | The single legal writer. Wall actions rejected. |
| `cc kanban-project` | Fold the event log into current card state (source of truth). |
| `cc kanban-verify-projection --snapshot snap.json` | Compare a surface snapshot to the log (PASS / BLOCKED / DEGRADED). |
| `cc kanban-reconcile --snapshot snap.json [--apply]` | Drift vs conflict; `--apply` repairs drift only (fail-closed). |
| `cc operate verify --all` | High-level: verify every board + repo at once. |

The event log lives at `generated/kanban-events.jsonl` (per-deployment runtime
state, gitignored). The UI reads it via `KANBAN_EVENT_LOG`.

## What is immediate vs near-real-time

- **Immediate:** internal UI (SSE off the local event log).
- **Near-real-time:** AppFlowy (write-through after the event + periodic
  read-back/reconcile). Without AppFlowy board env it reports `degraded` — never a
  fake success.

See also: [SECURITY_MODEL.md](SECURITY_MODEL.md) (the walls), [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md).
