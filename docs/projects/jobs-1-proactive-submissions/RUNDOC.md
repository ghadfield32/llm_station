# RUNDOC — JOBS-1 · Proactive job submissions (link + brief list → quick review)

Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop.

## 1. Objective & definition of done

The system proactively sends me a short list with per-item review links when
new job suggestions/prepared packets are ready, so I review quickly and each
still terminates at the existing human-approved, validation-gated submit —
NO new autosubmit path. Done (packet A) when: a jobs digest endpoint returns
a reviewable list (per item: company/role/fit + apply URL + packet
review deep-link); a daily push step emits that list through the existing
channel transport (recorded_only when unconfigured, like the email path);
the human submit gate is untouched; suites green.

## 2. Research (verified seam map, 2026-07-24; origin/main)

- The three ingredients already exist, unconnected:
  1. Per-card `apply_url` + `_claude_review_url` (board.py:384) and the full
     packet-review surface (`PacketReviewModal`, 12 tabs = everything the
     employer sees; `GET /api/domain/{d}/card/{c}/packet` app.py:8385).
  2. Push transport: `cc notify` (cli/notify.py) + `channels/` — but it
     reads Ledger missions, NOT jobs. `compose_digest` is pure/testable.
  3. The self-improvement pattern to copy: `discovery/delivery/ping.py`
     `render_ping(report, board_url, report_url)` → one nudge line, emitted
     from the self-improvement DAG's `finish()`.
- The existing jobs digest is FILE-only, no links: `job_search/digest.py`
  `write_digest()` → `generated/job-search-digest.md` ("Suggested Jobs"
  count + first 5, "Needs Geoff" static pointer — no apply URLs, no packet
  deep-links). Surfaced to cockpit only as `last_digest_at` mtime
  (app.py:8738).
- Daily DAG: `dags/job_search_daily.py` (cron 0 8 * * *, tag "no-submit"),
  terminal task `emit_digest` (:168) calls `write_digest()`. A push step
  registers as a new terminal `@task` after it.
- **The submit gate is triple-enforced and MUST remain the only submit
  path**: `finalize.py` FinalizeBlocked; app.py:8536 submit endpoint
  (confirm=true + Needs-Geoff-only + human actor; "Geoff pressing this
  button IS the human approval — no bot self-approval path exists");
  `packet_validation.py` blocking checks. Config: `auto_submit_enabled:
  false`, `require_geoff_selection: true` stay false/true.
- Test anchors: tests/test_notify.py (compose/send pattern),
  tests/job_search/test_packet_review.py (recorded_only), the digest tests
  in tests/job_search/.

## 3. KPIs & baseline

- Baseline: the digest is a flat MD file with 0 apply URLs and 0 packet
  review deep-links; no push emits job items; review requires manually
  opening the board.
- Target (packet A): a structured digest (JSON) with, per item, company/role
  /fit + apply_url + packet review deep-link; one push line summarizing "N
  new to review · → link"; recorded_only when the channel is unconfigured;
  the submit gate byte-identical.

## 4. Plan (bounded — packet A: backend + DAG, no frontend)

1. `job_search/digest.py`: add a structured `build_digest_items()` (pure) →
   list of `{company, role, fit_score, automation_class, apply_url,
   review_href, column}` for Suggested + Needs-Geoff cards; keep
   `write_digest()` writing the MD but source it from the structured items
   (per-item apply URL + review link now included).
2. New `job_search/proactive.py` (pure): `render_job_digest_ping(items,
   board_url)` → one short line "N new job(s) to review · top: <company —
   role> · → <board_url>" (mirrors ping.py). No I/O.
3. `app.py`: `GET /api/job-search/digest` (job-domain-gated, read-only)
   returns the structured items + counts + generated_at — the reviewable
   list with links. (No submit capability.)
4. DAG: a terminal `@task push_digest` in `dags/job_search_daily.py` after
   `emit_digest`, calling the existing channel send with
   `render_job_digest_ping`; recorded_only + logged when unconfigured (never
   raises). Guard so it never runs a submit.
5. Tests: `tests/job_search/test_proactive_digest.py` — structured items
   include apply_url + review_href; ping line format; empty → no push;
   the submit gate tests stay green (regression proof the gate is untouched).

Allowed files: src/command_center/job_search/digest.py,
src/command_center/job_search/proactive.py (new),
services/agent_kanban_ui/app.py, dags/job_search_daily.py,
tests/job_search/test_proactive_digest.py (new), this RUNDOC. Forbidden:
finalize.py / packet_validation.py / the submit endpoint (the gate is
immutable here), configs (no threshold changes), web/ (a cockpit digest
card is packet B, after the viewer/nav packets).

## 5. Decisions (defaults)

1. Proactive = notify + review link ONLY; submission stays the existing
   human-clicked, validation-gated path. No autosubmit, ever, in this packet.
2. Channel-unconfigured → recorded_only (write the would-send line to a
   log/file), exactly like the email record path — never a hard failure.
3. Review link = the existing packet-review deep link (Needs-Geoff cards) or
   the apply URL (Suggested cards); no new review surface invented.

## 6. Model allocation (resolved live 2026-07-24)

- Implementation: `throughput` → current lowest-priority Sol model resolved
  at launch via `codex debug models`, effort high (bounded backend + DAG),
  isolated worktree off origin/main, detached, fail-closed.
- Independent review: Fable (non-author), with a gate-integrity lens (prove
  no new submit path).

## 7. Links

- Card: JOBS-1 · Seam map: this doc §2 · Human-gate precedent:
  tests/test_packet_endpoints.py::test_submit_requires_confirm.

## 8. Execution log

- 2026-07-24 — Run-doc created from the seam-map sweep; packet A launching.
- 2026-07-24 — Packet A implemented in the bounded backend/DAG scope:
  `build_digest_items` now projects Suggested Jobs + Needs Geoff board cards
  with apply/review links; the Markdown digest consumes those items; the
  strict read-only `/api/job-search/digest` endpoint reports items/counts/time;
  and the terminal `push_digest` task sends the one-line nudge through the
  existing Discord transport or records the exact would-send line as
  `recorded_only` when the channel is unconfigured. No submit capability was
  added and the DAG retains its `no-submit` tag.
- 2026-07-24 — Verification: the requested pytest command collected 187 tests
  but the managed Windows sandbox blocked every test during fixture setup with
  `PermissionError: [WinError 5] Access is denied` while pytest tried to create
  `C:\Users\ghadf\AppData\Local\Temp\pytest-of-ghadf`; an explicit
  `C:\tmp` basetemp retry was blocked by the same filesystem policy. No pytest
  test body ran, so the suite is **not claimed green**. Read-only fallback
  verification passed the four new test functions directly plus an in-memory
  `GET /api/job-search/digest` response/schema smoke (including
  `extra="forbid"`), and AST parsing passed for all five changed Python files.
  Ruff passed on all changed Python files and `git diff --check` passed.
- 2026-07-24 — Submit-gate integrity: `finalize.py` remains origin/main blob
  `5591a58285850b2c5d1eef31e2356be4ecf66e53`; `packet_validation.py`
  remains origin/main blob `c41d6dbc49180a7dcc0b0ca56822b0b9e9945a25`;
  and the submit endpoint block remains SHA-256
  `ac8517e6fcbf39320a5dded2625504b91b9fe4b3ec95af0058ba99e0430184a2`
  (identical to the pre-edit baseline).
- 2026-07-24 — Git staging/commit was sandbox-blocked. The explicit allowlisted
  `git add` failed before staging with `Unable to create
  'C:/Users/ghadf/vscode_projects/docker_projects/llm_station/.git/worktrees/
  jobs1-proactive/index.lock': Permission denied`. No commit was created and
  nothing was pushed. Pytest's blocked cache attempts also left four
  inaccessible, untracked `pytest-cache-files-*` directories at the worktree
  root; the managed policy rejected their cleanup. They contain no staged or
  tracked changes and are not part of the packet.
