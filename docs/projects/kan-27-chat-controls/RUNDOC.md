# RUNDOC — KAN-27 packet 1 · Chat controls near Send (stop · queue · dropdown width)

Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop. KAN-27 is
broad ("stop button near Send, queue-another-message while running, settings
adjustable mid-chat, usage limits viewable in chat, newest models always
available, fix too-wide dropdown"). This packet ships the bounded, highest-value
**"controls near Send"** cluster the operator led with: **a Stop button next to
Send, the ability to queue a follow-up while the agent is running, and the
too-wide model/effort dropdown capped to fit the screen**. Deferred to packet 2
(recorded §5): settings adjustable mid-chat, usage/limits viewable in chat,
newest-models-always-available (GPT Sol) — those need the usage layer / catalog
seam and deserve their own packet.

## 1. Objective & definition of done

While the agent is running, I can **Stop** it from right next to Send, and I can
**type + queue** a next message that auto-sends when the agent goes idle — I no
longer have to wait, watch, and then remember to send. The model/effort dropdown
never overflows the composer/screen at 390px. Done when: (a) a Stop button sits
in `.chat-composer-bar` and interrupts the running session; (b) a queued message
is accepted while `status === "active"` and is sent automatically on the next
`session_idle`; (c) the model & effort `<select>`s are width-capped to their
container (no page-level horizontal scroll at 390px); (d) `npm run build` green;
(e) `npm test` green; (f) the frontend guardrail tests stay green.

## 2. Research (verified seam map, 2026-07-24; main @ 44bb172)

Component: **`AgentSessionPanel`** (App.tsx `function AgentSessionPanel(` @ L9560).
- State block ~L9583-9607: `events` (L9583), `input`/`setInput` (L9584),
  `busy`/`setBusy` (L9587), `models` (L9601), `model` (L9602), `effort` (L9603),
  `egressAck` (L9607). Refs: `sessionIdRef` (L9645), `closeStreamRef` (L9647).
- `send()` @ L9754: guards `!id || (!text && no attachments) || busy`; sets
  `busy`, resolves attachments, `setInput("")`, `await sendAgentMessage(id, prompt)`,
  clears `busy` in `finally`.
- `doInterrupt()` @ L9817: `await interruptAgentSession(sessionId)` then refetch
  the record. **Already exists — no new backend needed for Stop.**
- Stream handler @ L9682-9690: on each event, `setEvents(...)`; when the event
  type is in `["session_idle","session_failed","session_closed"]` it refetches
  the record (L9686). **This is the natural queue-flush point** — when the
  session goes idle, flush any queued message.
- `status = record?.status` @ L9851. Send button @ L10268-10275 is
  `disabled={busy || status === "active" || (!input.trim() && no attachments)
  || (external_egress && !egressAck)}`. So today, while the agent runs
  (`status === "active"`), Send is disabled → cannot queue.
- Composer bar @ L10262-10276: `<AttachMenu/>`, a status `<span>`, then the
  single Send `<button>`. This is where Stop goes (next to Send).
- Model `<select className="select">` @ L9913; effort `<select className="select">`
  @ L9926. Both live in the setup panel (`if (!sessionId)` branch). `.select`
  is a shared class → width-cap must not break other selects; scope via a
  wrapper/added class on the chat fields (`.chat-field .select`).
- Guardrail: `test_todo_routing_workflow.py::test_frontend_exposes_reviewed_chat_and_capture_routing_flow`
  reads App.tsx substrings — keep `buildTodoSections`, `General & unassigned`,
  `row.repo_ids.map`.

## 3. KPIs & baseline

- Baseline: no Stop button in the composer (interrupt only reachable elsewhere);
  Send disabled while running (no queue); model/effort selects can exceed 390px
  width with long model names.
- Target: Stop button interrupts from the composer bar; a follow-up can be
  queued while running and auto-sends on idle; selects cap to container width;
  build + test + guardrail green; no page-level horizontal scroll at 390px.

## 4. Plan (bounded — frontend only)

1. **Stop button (low risk, reuses `doInterrupt`)**: in `.chat-composer-bar`,
   render a Stop `<button className="clear">` when `status === "active"` (agent
   running) that calls `void doInterrupt()`. Keep Send present but its disabled
   logic unchanged. Stop is only shown/enabled while running.
2. **Queue-another-message (medium risk, self-contained)**:
   - Add `const [queued, setQueued] = useState<string>("")` near the state block.
   - When `status === "active"`, the composer accepts input; the primary action
     becomes **"Queue"** (instead of disabled Send): on click it stores
     `setQueued(input.trim())`, `setInput("")`, and shows a small "1 queued —
     will send when idle" marker (reuse `.agent-marker` idiom). Only one queued
     message (typing again replaces it / appends with a newline — choose replace
     for simplicity, record it). A tiny "clear queued" affordance removes it.
   - Flush: in the stream handler where `session_idle` is detected (L9686), if
     `queued` is non-empty and `sessionIdRef.current === id`, send it: set
     `input` from `queued`, clear `queued`, and call `send()` (or inline the
     send). Guard against double-send (clear `queued` before awaiting). Must not
     fire for `session_failed`/`session_closed` — only `session_idle`.
   - Keep the Enter-to-send handler working: while running, Enter queues; while
     idle, Enter sends (same key handler, branch on `status`).
3. **Dropdown width (low risk, CSS)**: cap the chat model/effort selects to
   their container. Prefer scoping to `.chat-field .select { max-width: 100%;
   width: 100%; }` (+ `text-overflow: ellipsis` if needed) in styles.css using
   existing tokens — do NOT globally change `.select` if it risks other views;
   if `.chat-field` already constrains width, add a minimal `min-width: 0` /
   `max-width` only. Verify at 390px the setup panel does not force horizontal
   page scroll.
4. Verify build + `npm test` + the frontend guardrail; keep pinned substrings.

Allowed files: `services/agent_kanban_ui/web/src/App.tsx`,
`services/agent_kanban_ui/web/src/styles.css`, this RUNDOC. Forbidden: backend
(`app.py`), `api.ts` (no contract change — `interruptAgentSession` already
exists), `package.json`, `AllTodosView.tsx`, any other file.

## 5. Decisions (defaults) + deferred slices

1. Packet 1 = Stop + Queue-one-message + dropdown-width. **Packet 2 (recorded,
   not lost):** settings adjustable mid-chat (there's already a `settingsNotes`
   "binds to the next session" seam @ L10188 to build on); usage & limits
   viewable in chat (wire the usage layer, PR #34, into the chat chrome);
   newest-models-always-available / GPT Sol (catalog/`fetchAgentModels` seam —
   likely backend, needs its own investigation). KAN-29 (OpenRouter leaderboard)
   is a separate item.
2. Queue holds ONE pending message (replace-on-retype), not a full FIFO —
   simplest correct behavior; a multi-message queue can come later if wanted
   (recorded).
3. Queue flushes ONLY on `session_idle` (not on failure/close), reusing the
   existing stream-handler branch — no new polling/timer.
4. Dropdown fix scoped to `.chat-field .select` (not global `.select`) to avoid
   regressing other views' selects.

## 6. Model allocation (resolve live 2026-07-24)

- Implementation: `throughput` → current lowest-priority Sol model via
  `codex debug models` at launch, effort **high** (bounded UI, but the queue
  flush has a correctness edge — double-send guard), isolated worktree off
  origin/main, detached, fail-closed. Under DESIGN.md (tokens only, 390px).
- Independent review: Fable (non-author), DESIGN.md + queue-correctness lens
  (no double-send, no send-on-failure, no stuck queue).

## 7. Links

- Card: KAN-27 · Related: KAN-28 (nav, #94), KAN-29 (OpenRouter leaderboard),
  usage layer (PR #34) feeds packet 2's usage-in-chat.

## 8. Execution log

- 2026-07-24 — Run-doc created from the verified AgentSessionPanel seam map;
  packet 1 launching (Stop + Queue + dropdown-width). Branched off main
  (disjoint from KAN-28's nav region, so not stacked).
- 2026-07-24 — Packet 1 implemented in the bounded frontend seam: active
  sessions now show Stop beside the primary Queue action; one trimmed message
  is replace-queued and flushed only on `session_idle` through a shared send
  helper. The synchronous queue ref is cleared before send (duplicate idle
  events cannot double-send), and failure/close events clear without sending.
  Auto-flush preserves any newer draft and staged attachments. Setup selects
  now use container-capped width/min-width/ellipsis rules; source-level layout
  review confirms the border-box setup card and selects fit the 390px track.
- 2026-07-24 — Verification (fail-closed): `npm ci --no-audit --no-fund`
  failed twice with sandbox `spawn EPERM`; the prescribed fallback
  `npm ci --no-audit --no-fund --ignore-scripts` exited 0 (114 packages).
  `npm test` exited 0 (41 tests). TypeScript passed both as the completed first
  half of `npm run build` and independently via
  `node node_modules/typescript/bin/tsc --noEmit`. The full build did **not**
  exit 0: Vite/esbuild was blocked while loading `vite.config.ts` by
  `Error: spawn EPERM`, so rendered 390px QA could not be run here. The exact
  Python guardrail command also did **not** reach test bodies: all 110 cases
  errored in fixture setup because the sandbox denied pytest's temp directory;
  retries with explicit writable basetemps remained permission-blocked.
  Therefore no commit was created. Pytest left ignored, permission-locked temp
  directories that this sandbox token could not remove.
- 2026-07-24 — Reviewer (Fable, non-author; Codex/Sol implemented) completed
  host verification the sandbox blocked: `npm ci` exit 0, `npm run build`
  exit 0 (tsc + vite build, dist emitted), `npm test` exit 0 (41 subtests
  across 5 files: 4/23/7/4/3), and the Python guardrail
  `test_todo_routing_workflow.py + test_agent_kanban_ui.py` exit 0 (110 tests)
  — pinned substrings intact. Independent review on the queue-correctness lens:
  APPROVED — ref-based `queuedRef`/`sendTextRef` avoid the stale-closure trap
  (handler is created in `connect()`), `queuedRef` is cleared before the async
  send (no double-send on repeated idle), flush fires ONLY on `session_idle`
  (failure/close drop the queue), and `clearComposer=false` preserves the
  in-progress draft. Stop reuses `doInterrupt()`; the CSS is scoped to
  `.agent-session-setup .chat-field .select` (not global `.select`), tokens
  only, `min-width:0` the load-bearing fit-to-390px fix. Committing.
