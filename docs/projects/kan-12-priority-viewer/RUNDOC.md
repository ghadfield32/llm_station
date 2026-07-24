# RUNDOC — KAN-12 · Priority / impact / timeline as first-class fields + the priority viewer

Through the [`TODO_PROCESS.md`](../../todos/TODO_PROCESS.md) loop. Split into
two packets because the unmerged chat/layout PR owns `App.tsx`:
**Packet A (this run): backend + config + data — no frontend files.**
Packet B (after the chat PR merges): the viewer strip UI.

## 1. Objective & definition of done

Every tracked todo carries priority (and optionally business impact +
timeline) as REAL card fields — parsed from the canonical markdown, visible
as board badges, present in `/api/todos` rows, and filterable — so the
56-item backlog is navigable by priority everywhere. Done (packet A) when:
importer parses the fields; grand_todo cards carry `priority`; `/api/todos`
rows expose + filter by it; board badge shows it; all suites green.

## 2. Research (verified seam map, 2026-07-23; origin/main @ e4f2e1e)

- Canonical format already promises this: GRAND_TODO_LIST.md L29-31 —
  "Business impact and timeline fields roll out with KAN-12". Every item has
  `**Priority:** P1|P2|P3` (or `_TBD_`).
- Importer does NOT parse it (zero matches in grand_todo_import.py); the
  exact precedent is `**Repo:**` → `_REPO_LINE_RE` (L116) → SourceCard field
  (L119-134) → `_source_fields` (L298-335). Priority must be added the same
  way, including in `edit_grand_todo_card`'s re-parse (L681-717) so
  round-trips keep it.
- Frontend ALREADY auto-detects it: `CARD_PRIORITY_FIELDS = ["research_priority",
  "priority","risk","tier","severity"]` + `cardPriority()` (App.tsx L179-205)
  — once cards carry `priority`, existing card disclosure shows it with ZERO
  frontend changes. `personal_todos` domain already declares a `priority`
  badge (domain_surfaces.yaml L883-885) — the config precedent.
- `/api/todos`: `TodoRowOut` (app.py L3039-3059, extra="forbid") has no
  priority; `_card_todo_row` (L3673-3725) doesn't read one; filters
  (L3908-3911) have no priority param; `filter_catalogs` (L3129-3135) has no
  priorities list. Pinned by
  `test_todo_routing_workflow.py::test_all_todos_lists_unassigned_and_every_board_link_with_filters`
  (L866) — must be extended, not broken.
- Viewer mount point (packet B): above `domain-tabs` in DomainsView
  (App.tsx L8071) + AllTodosView filter-bar precedent
  (AllTodosView.tsx L357-393); Work Map link = `setView("work-map")`.

## 3. KPIs & baseline

- Baseline: `priority` exists on 0 board-card fields for grand_todo; 0
  API rows expose it; 0 filters accept it.
- Target (packet A): 100% of grand_todo tracked cards carry parsed
  `priority` (plus `impact`/`timeline` when present in the markdown);
  `/api/todos?priority=P1` filters; catalogs list priorities; suites green.

## 4. Plan (bounded — packet A)

1. `grand_todo_import.py`: `_PRIORITY_LINE_RE` (matches `**Priority:** P1` etc.,
   value normalized to `P1|P2|P3` or absent for `_TBD_`), optional
   `_IMPACT_LINE_RE` / `_TIMELINE_LINE_RE` (`**Impact:**`, `**Timeline:**`
   free-short-text); SourceCard fields + `_source_fields` emission (exactly
   the repo_id pattern). Tests in test_grand_todo_import.py (parse, absent
   → no field/None, round-trip through edit_grand_todo_card).
2. `configs/domain_surfaces.yaml`: add `priority` badge to grand_todo
   summary_fields + drawer (mirror personal_todos L883-885); keep betts
   domain untouched.
3. `app.py /api/todos`: `priority` on TodoRowOut (+ impact/timeline optional),
   `_card_todo_row` reads card `priority` (fall back to the existing
   `cardPriority`-style key list server-side: priority → research_priority →
   tier → severity), `priority` query param filter, `priorities` in
   filter_catalogs. Extend the pinned workflow test for the new field +
   filter; `make validate` for the config change.
4. Canonical doc: GRAND_TODO_LIST format note gains the `**Impact:**` /
   `**Timeline:**` optional-line convention (docs change rides packet B's
   tracker sync to avoid another squash-cut race — record here).

Allowed files: src/command_center/cli/grand_todo_import.py,
services/agent_kanban_ui/app.py, configs/domain_surfaces.yaml,
tests/test_grand_todo_import.py, tests/test_todo_routing_workflow.py,
tests/test_domain_surfaces.py (only if the domain-shape test needs the new
field), this RUNDOC. Forbidden: web/ (packet B), docs/todos content edits.

## 5. Decisions (defaults)

1. Priority values normalized to `P1|P2|P3`; `_TBD_`/absent → field absent
   (never invent a default priority).
2. Impact/timeline are free short text, optional, parsed only when present.
3. Server-side fallback key order mirrors the frontend's existing
   CARD_PRIORITY_FIELDS so non-grand-todo boards get rows populated too.

## 6. Model allocation (resolved live 2026-07-23)

- Implementation: `deep_code` → Codex gpt-5.6-sol effort xhigh (importer +
  durable projection seams), isolated worktree off origin/main, detached,
  fail-closed rules.
- Independent review: Fable (non-author).

## 7. Links

- Card: KAN-12 · Seams: this doc §2 · Viewer (packet B) follows #81 merge.

## 8. Execution log

- 2026-07-23 — Run-doc created from the seam-map sweep; packet A queued
  behind the KAN-3 packet-2 instrumentation run (never two pytest
  processes concurrently).
- 2026-07-23 — Packet A implemented in the bounded backend/config seams:
  GRAND TODO parsing and projection now carry optional `priority`, `impact`,
  and `timeline`; the master domain exposes the priority badge and all three
  drawer fields; `/api/todos` exposes, filters, and catalogs priority with the
  documented server-side fallback order. No `web/`, Betts-domain config, or
  canonical tracker content was changed.
- 2026-07-23 — Verification: the requested four-file pytest command was
  attempted unchanged, but the managed Windows sandbox denied pytest access
  to `C:\Users\ghadf\AppData\Local\Temp\pytest-of-ghadf`; redirecting
  `TEMP`/`TMP` and an explicit `--basetemp` still hit pytest's inaccessible
  `mode=0o700` directory ACL. The same interpreter and exact four test files
  were then run with a process-local `Path.mkdir` mode shim (no repository
  file change): **176 passed**. Config validation reported
  `validate: PASS`; Ruff reported `All checks passed!` for all four changed
  Python files; `git diff --check` passed. The sandbox-created pytest temp
  directories could not be removed after exit because their ACLs also denied
  cleanup; they are not staged or included in the commit.
- 2026-07-23 — Commit packaging was attempted with an explicit allowlist of
  the six changed Packet A files, but `git add` failed closed before staging
  anything: the sandbox denied creation of
  `C:/Users/ghadf/vscode_projects/docker_projects/llm_station/.git/worktrees/kan12-priority/index.lock`.
  No commit was created and nothing was pushed; the verified working-tree
  changes remain ready for staging outside this sandbox.
