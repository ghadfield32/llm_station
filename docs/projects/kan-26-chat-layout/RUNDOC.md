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
