# RUNDOC — KAN-26 + KAN-4 + KAN-8 · Chat & layout under the DESIGN.md contract

One packet, three cards (they touch the same components; splitting them would
mean three passes over the same 11k-line file). Through the
[`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop, governed by
[`services/agent_kanban_ui/DESIGN.md`](../../../services/agent_kanban_ui/DESIGN.md).

## 1. Objective & definition of done

- **KAN-26**: chat surfaces are runtime-agnostic — a Claude, Codex, or
  GatewayCore message differs only by a small badge, never by bubble
  geometry or component; tool calls/evidence are collapsed insets, never raw
  JSON dumps.
- **KAN-4**: nothing forces page-level horizontal scroll at 390px; the chat
  pickers fit the viewport.
- **KAN-8**: board cards expose one **Open in chat** action plus a compact
  runtime picker, sourced from the live harness list — not hardcoded ids.

Done when: `npm run build` exit 0; new pure-helper tests pass under the
existing `node:test` runner; no page-level horizontal scroll at 390px; no new
hardcoded hex colors; the three card-action buttons are replaced by one
action + picker.

## 2. Research (verified seam map, 2026-07-23 read-only sweep)

All line numbers are `services/agent_kanban_ui/web/src/`.

**Two structurally separate chat renderers — the core KAN-26 defect:**
- GatewayCore: `ChatLine` (App.tsx 8901-8933) → `.cl` / `.cl.you` /
  `.cl.tool` / `.cl.res`; `max-width: 90%` (styles.css 389-397).
- Agent (Claude *and* Codex, rendered identically to each other):
  `buildAgentTranscript` (8969-9099) + `AgentTranscript` (9101-9134) →
  `.agent-bubble`; `max-width: 78%` (styles.css 2350-2356).
- **No runtime attribution on ANY message bubble** — the runtime appears only
  in the header id-chip (9873-9876) and composer footer (10106-10109).
- Two duplicate composers: gateway 11211-11244, agent 10050-10120 (both
  duplicate the auto-grow logic verbatim at 10086 / 11222).
- The single per-runtime switch: App.tsx 11177-11244.

**Tool/evidence rendering (DESIGN.md:79 violation confirmed):**
- `ChatLine` `default` branch (8931) does
  `<div className="cl">{JSON.stringify(ev)}</div>` — raw JSON into the
  bubble for any unrecognized event.
- `ThreadTimeline` (10545) does the same for non-tool events.
- The agent lane is already correct: `<details className="agent-activity">`
  collapsed inset (9115-9127) — **this is the pattern to converge on.**

**KAN-4 width root causes:**
- `.select` (styles.css 48-51) has **no `max-width` and no `min-width: 0`**;
  a native select sizes to its widest option. Picker B (App.tsx 11041-11046,
  11064-11069) builds options like
  `anthropic/claude-sonnet-4.5 — ~$0.0123/turn · 3.4s median · 87% suite pass (no key)`.
  `.chat-header` (366-369) is `flex-wrap` with no `min-width: 0` on children,
  so the select can't shrink. **This is the "way too wide" dropdown.**
- `.roles-grid { min-width: 300px }` (2453) sits in normal flow in the header.
- `.agent-settings-body` (2465-2468) is `position: absolute; min-width: 260px`
  nested *inside* the already-absolute `.popover-menu` (2592,
  `max-width: 340px`) — it escapes both the popover box and the clamp.
- `.attach-menu { min-width: 300px }` (2663) exceeds the ≤620px popover clamp
  (2621, `min-width: 180px`).
- **No `overflow-x` guard anywhere** on `html` / `body` / `.main`.
- No breakpoint below 480px exists; the single ≤480px rule (631-635) is dead
  (`.chat-bar-hint` unused). Other dead rules: `.chat-bar .select` (612),
  `.chat-input` (2424).

**KAN-8 card actions:** `DomainCardTile` 4595-4610 renders three buttons;
`Ask Claude` / `Ask Codex` pass **hardcoded** `agent:claude_code_local` /
`agent:codex_agent` — never checked against `fetchAgentHarnesses()`, so a card
can target an unavailable harness. Handler `chatAboutCard` (4554-4562) has no
pending state during its `fetchDomainCardProgress` await. Prop chain:
`DomainsView` 8381-8382 / 8407-8408 → `openChatWithPrompt` (11620-11626).

**Test capability (decisive constraint):** `web/package.json` has **no React
test runner** — no vitest/jest/testing-library/jsdom. `npm test` runs four
`.mjs` files under the built-in `node:test`, each transpiling a **pure helper
module** in-process (`src/researchProgress.ts`, `researchAnalysis.ts`,
`todoStoryRequest.ts`, `bookLibrary.ts`). `App.tsx` exports only `App`; every
chat component is module-private. **⇒ The packet must extract its logic into
pure helper modules to be testable** — exactly the KAN-3 `loadResilience.ts`
pattern. Adding a component-test runner is out of scope here (own packet).

## 3. KPIs & baseline

| KPI | Baseline | Target |
| --- | --- | --- |
| Chat message components per runtime | 2 divergent (`.cl` 90% / `.agent-bubble` 78%) | 1 shared shell + runtime badge |
| Raw-JSON dump sites in chat | 2 (App.tsx 8931, 10545) | 0 |
| `.select` max-width rules | 0 | bounded, fits 390px |
| Hardcoded harness ids in card actions | 2 | 0 (live harness list) |
| Card chat buttons | 3 | 1 + picker |
| Pure-helper tests for chat logic | 0 | ≥1 new `.mjs` suite green |
| `overflow-x` page guard | none | present |

## 4. Plan (bounded, incremental — each step independently buildable)

1. **`src/chatPresentation.ts` (new pure module)** — the testable core:
   `runtimeLabel(target)` → `{ id, label, kind }` for GatewayCore / each
   agent harness; `describeChatEvent(ev)` → a discriminated
   `{ kind: "message" | "activity" | "error", role, text, collapsedDetail? }`
   so **unknown events become a collapsed activity row, never a JSON dump**;
   `optionLabel(model)` → a short primary label + separate `title` detail
   (so the select stops sizing to a 90-char string).
2. **Converge the renderers**: `ChatLine` and `AgentTranscript` both render a
   shared bubble shell (same geometry) with a small runtime `Badge`; keep the
   agent `<details className="agent-activity">` inset as THE evidence pattern
   and route gateway tool/tool_result/unknown events through it via (1).
3. **KAN-4 CSS**: bound `.select` (`max-width: min(100%, 320px)`,
   `min-width: 0`, `text-overflow: ellipsis`), add `min-width: 0` to
   `.chat-field`/`.chat-header` children, clamp `.roles-grid` /
   `.attach-menu` / `.agent-settings-body` with `min()` against the viewport,
   un-nest the double-absolute settings body, add the `overflow-x` guard, and
   delete the three dead rules (612, 631-635, 2424). Full option text moves to
   `title=` (KPI: no information lost).
4. **KAN-8**: `DomainCardTile` renders **one** `Open in chat` + a compact
   `<select>` of runtimes built from the harnesses already fetched by the app
   (pass the list down; if unavailable, show GatewayCore only — never a
   hardcoded id). Add a pending state to `chatAboutCard`.
5. **Tests**: new `web/tests/chatPresentation.test.mjs` in the existing
   `node:test` + in-process-transpile style: unknown event → collapsed
   activity (never JSON), runtime labels for all three kinds, option label
   short-form + title detail.

**Allowed files**: `web/src/chatPresentation.ts` (new), `web/src/App.tsx`,
`web/src/styles.css`, `web/tests/chatPresentation.test.mjs` (new),
`docs/projects/kan-26-chat-layout/RUNDOC.md`. **Forbidden**: `web/package.json`
(no new deps/runners), api.ts contract changes, backend, configs.

## 5. Decisions (defaults taken; adjust anytime)

1. One packet for all three cards — same components, one review.
2. No new test runner (own packet later); testability comes from extracting
   pure helpers.
3. Runtime shown as a small badge on the bubble, not a color/shape change —
   per DESIGN.md's "differ only by a badge" rule.
4. Long model detail moves to `title=`, never deleted.

## 6. Model allocation (resolve live at execution)

- Implementation: `throughput` → current lowest-priority Sol model resolved
  via `codex debug models` at launch (2026-07-23 resolution: gpt-5.6-sol),
  effort **high** (bounded UI refactor, no durable-state risk), isolated
  worktree off origin/main, detached launch, fail-closed rules.
- Independent review: Fable (non-author) against the DESIGN.md checklist.

## 7. Links

- Cards: KAN-26, KAN-4, KAN-8 in
  [`docs/todos/GRAND_TODO_LIST.md`](../../todos/GRAND_TODO_LIST.md)
- Contract: [`DESIGN.md`](../../../services/agent_kanban_ui/DESIGN.md)
- Precedent: [KAN-3 run-doc](../kan-3-load-performance/RUNDOC.md) (pure-helper
  extraction pattern)

## 8. Execution log

- 2026-07-23 — Run-doc created from the seam-map sweep; packet launching.
- 2026-07-23 — Reviewer host verification (Codex fail-closed correctly: its
  sandbox blocked esbuild's child process with `spawn EPERM`, so it refused
  to commit an unverified build): `npm ci` exit 0, `npm run build` exit 0,
  `npm test` exit 0 with **41 tests passing** (38 existing + 3 new). No new
  hardcoded hex colors. `.agent-bubble` / `.cl.you` / `.cl.final` fully
  retired with zero orphaned references in TSX or CSS.
- 2026-07-23 — **Packet-design error found and fixed by the reviewer**: the
  packet forbade `package.json` edits (to block dependency/runner changes),
  which also blocked *registering* the new suite — `npm test` hardcodes its
  four filenames, so `chatPresentation.test.mjs` existed but never ran. Fixed
  by adding it to the `test` script (script-only change, zero dependency
  changes). Lesson for future UI packets: forbid `dependencies`/
  `devDependencies`, not the whole file.
- 2026-07-23 — Independent review (Fable, non-author, DESIGN.md checklist):
  **APPROVED.**
  - KAN-26: one `ChatBubbleShell` now renders every lane (9 call sites across
    gateway, agent, and story views) with a runtime badge — geometry is
    identical across runtimes, satisfying "differ only by a badge". Both
    raw-JSON dump sites are gone from the chat renderers.
  - Unknown-event handling is *stricter* than the packet asked: known-schema
    tool args still render in the collapsed inset, but unknown-shape payloads
    are named (`activity: <type>`) and withheld rather than rendered, since an
    unrecognized payload could carry credentials. Accepted as the safer line
    and pinned by a test; the event type still gives the diagnostic signal,
    and Diagnostics retains full unfiltered truth.
  - KAN-4: root causes fixed (`.select` bounded with `max-width: min(100%,
    320px)` + `min-width: 0` + ellipsis; `min-width: 0` on all chat-header
    flex children; `.roles-grid`/`.attach-menu`/`.agent-settings-body` clamped
    with `min()` against the viewport; the double-absolute settings body
    un-nested to `position: static`). The `overflow-x` guards on `html`/
    `.shell` sit *on top of* those real fixes as a backstop, not as a cover —
    verified each source was addressed independently. Three dead rules
    deleted (`.chat-bar .select`, the `.chat-bar-hint` ≤480px block,
    `.chat-input`). Long model detail preserved in `title=`, never dropped.
  - KAN-8: three buttons → one pending-aware `Open in chat` + a runtime
    `<select>` built from the **live** harness list, with unavailable
    harnesses disabled and their reason in `title`. Zero hardcoded harness ids
    remain in card actions.
  - Out of scope, deliberately untouched (recorded as follow-ups): the
    research-handoff entry point still hardcodes `agent:codex_agent`
    (different feature), and `EventRow` still serializes mission payloads
    (missions view, not chat).
- 2026-07-23 — **CI caught a real verification gap in MY process** (PR #81
  `lint-test` red): `tests/test_card_chat_context.py` is a **backend pytest
  that reads `App.tsx` as source text** and pinned the old three-button
  design (`"Ask Claude" in src`, `chatAboutCard("agent:claude_code_local")`).
  I had verified this frontend packet with `npm run build` + `npm test` only.
  **Lesson (now standing): a frontend-only packet still requires the full
  backend suite, because backend guardrail tests assert over frontend
  source.** Recorded in WORKLOG.
  Resolution — contract moved, not deleted (the invariant "every card can
  open chat on the lane the user picks" is still valuable): the two obsolete
  assertions were rewritten to pin the NEW, stricter contract —
  `test_every_card_has_one_open_in_chat_action_plus_a_runtime_picker`
  (one action + `card-runtime-select`, and the old button labels must be
  ABSENT), `test_card_runtime_picker_is_built_from_the_live_harness_list`
  (picker enumerates fetched harnesses, unavailable ones disabled, GatewayCore
  always offered), and a new
  `test_card_actions_never_hardcode_an_agent_harness_id` that scopes to the
  `DomainCardTile` function body so a literal harness id in a card action is
  itself a failure. The two tests that still held (chat_prompt seeding,
  draft-target honoring) were left untouched and still pass.
- 2026-07-23 — Full re-verification after the fix: **entire backend suite
  `pytest tests/` exit 0**, `ruff check src` clean, `npm run build` exit 0,
  `npm test` exit 0 (41 passing).
- 2026-07-23 — Implemented Sections 4.1–4.5 in the five allowed files. No
  DESIGN.md deviation was required. GatewayCore and native-agent messages now
  share one bubble shell/runtime badge; tool, result, and unknown events use
  collapsed activity rows; model option detail is preserved in `title`; the
  390px width constraints are bounded; and card chat actions use the lifted
  live harness catalog with a pending-aware single action.
- 2026-07-23 — Incremental verification: after each implementation step,
  `npm run build` reached and passed `tsc`; every attempt then stopped in Vite
  because this Windows sandbox rejects esbuild's child-process launch with
  `Error: spawn EPERM`. The final `npm run build` therefore exited 1 and is
  **not claimed green**. Standalone `node_modules\.bin\tsc.cmd --noEmit`
  exited 0.
- 2026-07-23 — Required install command
  `npm ci --no-audit --no-fund` exited 1 with `npm error syscall spawn` /
  `EPERM`, matching the packet's documented sandbox limitation. Fallback
  `npm ci --ignore-scripts --no-audit --no-fund` exited 0 and installed 114
  packages, enabling typecheck and pure-helper tests without postinstall
  process launches.
- 2026-07-23 — `npm test` exited 0: all four package-script suites passed (38
  tests). The frozen `package.json` script explicitly enumerates only those
  four pre-existing suites, so the new allowed-file suite was also run
  directly: `node tests\chatPresentation.test.mjs` exited 0 (3/3 tests).
  `package.json` was not changed.
- 2026-07-23 — PowerShell has no `grep` executable; the equivalent
  `rg -n -g '*.tsx' -g '*.ts' '#[0-9a-f]{6}' src` found no matches (exit 1
  from `rg`, normalized to verification exit 0). No new hardcoded hex colors
  were introduced. `git diff --check` exited 0. A static 390px audit passed
  (366px mobile content width, 320px select cap, viewport-clamped popovers),
  but browser rendering was not run because the Vite build/server process is
  blocked as above.
- 2026-07-23 — Fail-closed outcome: no commit was created because the required
  `npm run build` could not exit 0 in this sandbox. Changes remain confined to
  the allowed files for verification and commit in an environment that permits
  esbuild child processes.
