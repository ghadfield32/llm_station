# Todos and guided job-hunt validation — 2026-07-16

## Outcome

The deployed cockpit passes a new read-only, provenance-linked acceptance
validator: **14/14 checks**. The validator connects the reviewed source, the
five exact immutable captures, their five distinct canonical work items, the
live Todos projection, private job-search controls, OpenAPI constraints, and
the exact shipped JavaScript asset. The client issues no state-changing HTTP
method, and the observed run changed no live workflow state. A server GET may
still perform its own pre-existing crash-journal recovery.

The matching hermetic acceptance matrix is **237/237 passing**. A repository-wide
run completed with 1,970 passed, 3 skipped, and 12 transient cross-test
shared-state/lock failures; all 12 failing node IDs passed together in a clean
serial rerun. This is recorded as a broad-suite flake, not as a green broad
command.

## Scope and review allocation

- Objective: add varied, reproducible validation for the Todos routing and five
  guided job-hunt capabilities already implemented and deployed.
- Non-goals: no product behavior change, live kanban mutation, external job
  submission, LinkedIn lookup/send, deployment, generated-evidence cleanup, or
  Git staging.
- Base branch/SHA: `main` at
  `963b0631844b8549cf6ca4cda416400890231e34`; the worktree already contained
  extensive operator-owned changes.
- Validation risk: treated with the high-risk review sequence because the proof
  spans public APIs, private profile data, durable Ledger state, and a deployed
  artifact even though the new code itself is read-only.
- Required capability profile: `strategic_steward` for validation design and
  `generalist` for the bounded test/runner implementation.
- Resolved harness/model: active Codex GPT-5-family session at high reasoning;
  the exact server model ID is not exposed by the session.
- Independent review: fresh, read-only Codex verifier. Cross-family review was
  unavailable, so independence is reduced and explicitly compensated by
  deterministic hermetic, build, API, provenance, privacy, and live gates.
- Review closeout: the fresh plan review and semantic review returned GO after
  their findings were resolved. Two fresh final-diff reviewer sessions stalled
  without returning a verdict, so no independent final-diff verdict is claimed;
  the semantic reviewer reconciled the final hardening changes as GO, and all
  affected deterministic gates were rerun.
- Plan-review finding resolved: the Worklog's second capture ID was corrected
  from nonexistent `cap-971b8b8b51cf` to live `cap-971b8b8b51`; the validator
  GETs each full capture because Inbox previews truncate at 160 characters.

## Requirements-to-evidence matrix

| Promise | Hermetic behavioral evidence | Deployed read-only evidence | Result |
| --- | --- | --- | --- |
| Prominent Todos destination; Prepare now opens a stable capture-scoped chat with Todos, existing-kanban, and new-kanban choices without creating work | `tests/test_intake_capture.py::test_prepare_is_idempotent_and_keeps_full_raw_capture`; `tests/test_agent_kanban_ui_capture.py::test_prepare_opens_stable_chat_without_creating_work`; `tests/test_capture_ledger_store.py::test_prepare_survives_restart_and_replay_is_idempotent` | `prepare_chat_gate`, `todos_schema`, `shipped_ui_markers` | Pass |
| Compatible existing-kanban choices and write-gated new-kanban creation | `tests/test_todo_routing_workflow.py::test_unmatched_todo_lists_every_compatible_existing_and_new_board_option`; `::test_varied_new_kanbans_are_governed_empty_and_immediately_offered`; `::test_frontend_exposes_reviewed_chat_and_capture_routing_flow` | `new_kanban_write_gate`, OpenAPI/UI marker checks | Pass |
| Work through an application one visible page at a time with provenance and secret/protected-question stops | `tests/test_packet_endpoints.py::test_job_chat_prompt_is_page_scoped_safe_and_provenance_complete` | exact shipped `work page-by-page in chat` marker | Pass |
| Known-contact follow-up drafts and connection-search suggestions, without invented people or sending | `tests/job_search/test_job_search_memory.py::test_outreach_is_exact_deterministic_draft_only_and_offline` | GET-only outreach OpenAPI contract, private contacts endpoint, exact shipped offline/search-phrase markers | Pass |
| Editable company watchlists feed bounded rotating discovery and survive per-query failures | `tests/test_packet_endpoints.py::test_company_targets_and_retention_controls_reload_and_reject_unknowns`; `tests/job_search/test_job_search_mvp.py::test_daily_discovery_includes_every_company_watchlist_target`; `tests/job_search/test_live_sources.py::test_remotive_failure_is_recorded_and_later_queries_survive` | `editable_company_watchlists`, exact shipped company-watchlist marker | Pass |
| Learn explicit non-sensitive unanswered questions by job type; candidate answers remain inert until human Standing Answer review | `tests/job_search/test_job_search_memory.py::test_question_candidates_are_category_scoped_and_restart_durable`; `::test_sensitive_capture_and_answer_are_rejected_without_leakage`; `::test_candidate_answers_do_not_change_automation_or_rendering` | `private_question_and_contact_memory`, `private_no_store`, exact shipped question-library/review markers | Pass |
| Applied-job-only minimal outcome memory, adjustable 1–365 days, extended only by explicit process-furthering communication | `tests/job_search/test_job_search_mvp.py::test_retention_dry_run_mutates_nothing_and_apply_archives_stale`; `::test_only_explicit_process_furthering_note_refreshes_retention`; `::test_unsubmitted_packet_never_enters_applied_job_ledger`; `::test_concurrent_notes_preserve_every_event_and_qualifying_retention` | `current_retention_posture`, `retention_1_to_365_contract`, exact shipped furthering marker | Pass |
| Five requested tasks were received, converted once, and completed on Todos | validator unit defect matrix plus capture/work-graph contracts in `tests/test_todo_job_hunt_validation.py` | exact full source for five captures; exact reviewed title/work-item ID; one `work_graph` card each on `personal_todos`; all `Done`; five distinct work IDs; exact capture-scoped chat link | Pass |

## Validator safety and failure behavior

[`scripts/validate_todo_job_hunt.py`](../../scripts/validate_todo_job_hunt.py)
is deliberately narrower than a general crawler:

- only `GET` is available through its transport;
- loopback is the default and a remote host requires `--allow-remote`;
- requests, redirects, and the JavaScript asset must remain same-origin;
- each response is limited to 1 MiB and each request to 10 seconds by default;
- exact source comparison uses the full capture endpoint, never a truncated
  Inbox preview;
- private profile, relationship, question, and standing-answer response bodies
  are inspected only for shapes/gates, discarded, and never copied to output;
- reports contain only check names, fixed non-private summaries, counts, and the
  reviewed asset filename;
- malformed JSON, oversized responses, changed API methods, changed retention
  bounds, missing UI controls, wrong build asset, and cross-origin behavior fail
  closed with redacted error codes.

Run it against the reviewed local deployment with:

```powershell
uv run python scripts/validate_todo_job_hunt.py `
  --expected-asset index-BTMq668F.js
```

An intentional cockpit rebuild normally changes the hashed asset filename.
Review the new build first, then update the expected filename supplied by the
operator; do not silently accept any asset as the reviewed deployment.

## Deterministic evidence

| Command | Exit/result |
| --- | --- |
| `uv run pytest tests/test_todo_job_hunt_validation.py` | 0; 14 passed |
| `uv run pytest tests/test_intake_capture.py tests/test_agent_kanban_ui_capture.py tests/test_capture_ledger_store.py tests/test_todo_routing_workflow.py tests/test_packet_endpoints.py tests/test_todo_job_hunt_validation.py tests/job_search` | 0; 237 passed, 1 deprecation warning |
| `uv run python scripts/validate_todo_job_hunt.py --expected-asset index-BTMq668F.js` | 0; 14/14 live checks pass |
| `npm --prefix services/agent_kanban_ui/web run build` | 0; TypeScript + Vite, 32 modules, `index-BTMq668F.js` |
| `uv run cc lint` | 0; pass |
| `uv run cc validate` | 0; config validation, cross-references, configured-provider posture pass |
| `uv run pytest` | 1; 1,970 passed, 3 skipped, 12 transient failures in 892.16s |
| exact rerun of the 12 failed node IDs | 0; 12 passed, 1 deprecation warning |
| `uv run cc doctor` | 1; 20 pass, 1 inherited `dirty_generated_evidence` failure |

The first attempted acceptance batch ran tests concurrently with `cc validate`,
which renders generated configuration and contaminated two lock-sensitive tests.
That run is discarded. The reported 237-test result is the clean serial rerun.

## Known limitations

- The JavaScript marker check proves the reviewed controls shipped; behavioral
  claims come from hermetic API/domain tests, not string presence alone.
- The application helper is conversational and page-scoped. It does not
  co-browse, enter credentials, bypass CAPTCHA/MFA, or submit employer forms.
- LinkedIn support is offline and operator-entered: exact-company known contacts
  can receive deterministic unsent drafts, while new-person recommendations are
  search phrases. There is no LinkedIn lookup or send integration.
- Rich application-file deletion remains disabled. The retention setting is an
  applied-record eligibility clock plus an idempotent minimal SQLite outcome;
  it is not a physical 30-day disk-growth bound.
- The broad suite has a known cross-test board/config lock and module-state
  isolation flake. Its exact failures passed serially, but the broad command
  itself is not represented as green.
- `cc doctor` still fails only on pre-existing dirty generated/evaluation
  evidence. This pass did not clean or stage operator-owned artifacts.
- The final-diff reviewer harness stalled twice without a verdict. This is a
  disclosed review-process limitation; it is not represented as a completed
  independent final-diff approval.

## Files added or corrected by this validation pass

- `scripts/validate_todo_job_hunt.py`
- `tests/test_todo_job_hunt_validation.py`
- `docs/reviews/2026-07-16-todo-job-hunt-validation.md`
- `WORKLOG.md` (capture-ID correction and validation summary only)

No product source, configuration contract, dependency, live kanban record, or
deployment was observed to change during this pass.
