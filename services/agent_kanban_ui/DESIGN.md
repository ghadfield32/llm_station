# DESIGN.md — Agent Kanban Cockpit design system

The single visual-language contract for the cockpit (`agent_kanban_ui`).
**Every agent (Claude Code, Codex, Copilot, human) generating or editing
cockpit UI MUST read this file first and conform to it** — this is the
portable DESIGN.md convention (à la Open Design / awesome-claude-design)
adopted 2026-07-23 per operator direction on AGT-7. Canonical tokens live in
[`web/src/styles.css`](web/src/styles.css) `:root`; this doc explains intent.

## Identity

Cline-style dark console: slate surfaces, quiet chrome, monospace accents,
status dots. Dense but calm — an operator instrument, not a marketing page.
One theme (dark); do not introduce a light theme in a component-local way.

## Tokens (authoritative — never hardcode these values elsewhere)

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#0d1117` | page background |
| `--panel` | `#161b22` | sidebar / raised panels |
| `--col` | `#11161d` | column / inset wells, inputs |
| `--card` | `#1c232c` | cards, active nav |
| `--border` | `#2a313c` | all hairlines (1px) |
| `--fg` | `#e6edf3` | primary text |
| `--muted` | `#8b949e` | secondary text, labels |
| `--accent` | `#4c8eff` | selection, focus, links, running state |
| `--ok` / `--warn` / `--bad` / `--run` | `#3fb950` / `#d29922` / `#f85149` / `#4c8eff` | status semantics ONLY |

Rules: new colors require a new token here first. Status colors are for
status, never decoration. Error surfaces use the `.error` pattern
(12%-alpha `--bad` fill + `--bad` border), not raw red text.

## Typography & spacing

- Body: 14px/1.5 system sans (`-apple-system, "Segoe UI", Roboto`).
- Section headers (`h3`): 12px uppercase, 0.05em tracking, `--muted`.
- Timestamps/ids/code: `ui-monospace` at 11-12px.
- Radii: 7-8px on interactive elements; spacing rhythm 4/6/8/12/16/20px.
- Small text is 12px, tiny metadata 11px — never below 11px.

## Layout invariants

- Shell = sticky 200px sidebar (`--panel`) + `.main` (max-width 1180px).
- **Fit-to-screen is a hard rule (KAN-4)**: no component may force page-level
  horizontal scroll. Wide content (boards, tables) scrolls inside its own
  `.scrollframe` with `overscroll-behavior-x: contain`. Mobile/PWA first:
  everything usable at 390px width; touch targets ≥32px;
  `touch-action: manipulation` on all tappables.
- Dropdowns/popovers must fit the viewport (`max-width: min(92vw, 480px)`)
  — the chat dropdown width bug class (KAN-4) must not recur.

## Component conventions (reuse, don't reinvent)

- Nav: `.navitem` (+`.nav-on`), sub-lists `.nav-subitem`, counts `.navcount`.
- Tabs/filters: `.tab`/`.tab-on`, `.filterbar` with `.search`/`.select`.
- Cards: `.domain-card` pattern — title, `Badge` pills, muted metadata line.
- Buttons: `.actbtn` for actions; destructive actions get confirm affordance
  and are human-only where governance says so (KAN-9).
- Status: dot (`.hopdot ok|bad`) or pill (`Badge`/`.status-pill`) — pick one
  per context, never both.
- Errors: `.error` block per surface; transient staleness uses a quiet
  muted "stale since HH:MM" chip, NEVER the `.error` block (KAN-3 rule).

## Chat surfaces (the cross-agent priority)

The chat is shared by multiple assistant runtimes (GatewayCore models,
Claude, Codex, and future runtimes). Requirements:

- **Runtime-agnostic chrome**: the message list, composer, and picker render
  identically regardless of which assistant produced a message; the runtime
  is shown as a small `Badge` on the message, not a different bubble style.
- Assistant/model pickers are compact selects (`.select`), fit-to-viewport,
  with the active choice visible in the composer at all times.
- Streaming/running state uses `--run` accent + a subtle progress affordance;
  errors from a runtime render as an in-thread `.error` block with the
  runtime badge, never a toast-only failure.
- Tool calls / evidence render collapsed-by-default in monospace insets
  (`--col` background), expandable; never dump raw JSON into the bubble.
- Repo/board context chips (registered repo, linked card) sit in a single
  metadata row above the composer (KAN-13 lands the repo dropdown here).

## Agent workflow rules

1. Read this file before any cockpit UI change; cite deviations in the PR.
2. New patterns: add the token/convention HERE in the same commit.
3. Verification for UI packets: `npm run build` green + fit-to-screen check
   at 390px + no new hardcoded colors (`grep -E "#[0-9a-f]{6}" src` diff).
4. This file is versioned with the code — changing the design means changing
   this contract first, then the CSS.

## Provenance

Adopted 2026-07-23 (AGT-7 follow-through: Open Design's DESIGN.md convention,
see docs/todos/reference/RESEARCH_NOTES_2026-07.md). Tokens extracted
verbatim from `web/src/styles.css` the same day.
