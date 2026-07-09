# Work Log

Compact repo-level notes for active work. Keep entries short and grouped so a
future session can see what was already diagnosed before changing code.

## Agent Kanban UI / Cockpit

- 2026-07-08: Added typed Domains cockpit surfaces; Jobs reads `job_search_pipeline_internal`, fixture-backed domains show demo origin.
- 2026-07-08: Diagnosed local cockpit error: host-run uvicorn used Docker-only `http://ledger:8090`; host Ledger URL is `http://127.0.0.1:8091`.
- 2026-07-08: Added `/api/debug/runtime`, target URLs in `/api/status`, and per-surface frontend failures so setup errors are explicit.
- 2026-07-08: Promoted typed Domains to visible sidebar sections with counts and lane-backed kanban columns; Jobs now shows all 8 pipeline stages from config.
- 2026-07-08: Added write-gated domain drag/drop for board_store domains, Jobs preset drawer, and chat runtime reporting (`GatewayCore` + LiteLLM; Orca/Omnigent inactive).
- 2026-07-08: Fixed cwd-relative cockpit paths after GatewayCore/live-board startup; `configs` now resolves at process startup, and Jobs drawer exposes progress steps + chat handoff.
- 2026-07-08: Diagnosed `WinError 10048` on port 8787 as stale Docker `llm_station-agent-kanban-ui-1`; rebuilt/recreated container and verified new `/api/debug/runtime`, `/api/domains`, Jobs, and chat endpoints.
- 2026-07-08: Diagnosed Jobs drag 500 as `/snapshot` mounted read-only; made full-console `./generated:/snapshot` writable, added write preflight diagnostics, and validated all Jobs lanes with `job_57b63f145aa3`.
- 2026-07-08: Added mobile/PWA cockpit layer: manifest, static-only service worker, bottom phone nav, full-screen drawers, and tap `Move to...` menus for generic/domain cards.
- 2026-07-09: Fixed Docker cockpit fixture packaging; non-Job sections now load demo cards from `/app/domain_fixtures.json` after rebuild.
- 2026-07-09: Added Tailscale cockpit route `https://vengeance.taile6a055.ts.net:8787`; phone validation waits on `iphone-12` coming online in Tailscale.
- 2026-07-09: Added concrete 192/512/maskable/Apple PNG PWA icons and rebuilt the live cockpit container; local manifest/icon endpoints pass.
- 2026-07-09: Collapsed primary nav to All Boards + Controls, added profile-backed job-search overrides, and made mobile topbar non-sticky.
- 2026-07-09: Mounted `./data/job_search` into the cockpit container and exposed it in `/api/debug/runtime`; Jobs progress drawers now see prepared packets and followups.
- 2026-07-09: Made Jobs chat handoff card-specific with authoritative domain context and per-card conversation ids; runtime remains GatewayCore/LiteLLM, with Orca/Omnigent inactive by design.
- 2026-07-09: Added no-ID Jobs completion and note capture; dragging a prepared job to `Completed` marks application memory submitted, and card notes refresh communications/followups.
- 2026-07-09: Rebuilt cockpit container and live-validated `/api/domain/.../note` on Ruby Labs Senior Data Analyst; chat smoke test returned through GatewayCore/LiteLLM.
- 2026-07-09: Added Jobs automation queue chips/dropdown (`bot_possible`, `manual_required`, `prepare_only`) so desktop/mobile can split the 25/25 review queues without IDs.
- 2026-07-09: Re-ran DAG-equivalent discovery (Jobicy/Remotive/RemoteOK); 74 eligible jobs above threshold, 12 bot-possible, no unprepared bot cards left after publish.
- 2026-07-09: Chat runtime now reports optional external chat links from `ORCA_CHAT_URL`, `OMNIGENT_CHAT_URL`, or `OMNIAGENT_CHAT_URL` instead of a bare inactive status.
- 2026-07-09: Validated scoped Jobs chat handoff on Ruby Labs Senior Data Analyst; chat used card progress/events/application memory and returned the correct `Needs Geoff` next action.
- 2026-07-09: Added top mobile scrollbars for All Boards lanes/tabs and a gated Controls editor for `configs/domain_surfaces.yaml` add/update/remove board schema changes.
- 2026-07-09: Split Jobs into Bot Board / Manual Board / All Jobs views, added Jobs lane scrollbar under filters, and rebuilt the live cockpit container.
- 2026-07-09: Removed confusing Jobs `Split Boards` mode; Jobs now defaults to Manual Board with Bot Board and All Jobs as explicit focused views.
- 2026-07-09: Added Chat specialist metadata/cards for ORCA, OmniAgent/Omnigent, and OxyGent, plus shared recent chat shortcuts with mobile top-scrollbar navigation.
- 2026-07-09: Polished mobile scrolling across All Boards, Controls, and Chat: momentum scroll, proximity snap, contained bottom nav, wrapped Controls code paths, and no document-level horizontal overflow in mobile browser checks.
- 2026-07-09: Added the Packet Review modal (Overview/Resume/Cover Letter/Answers/Recruiter Msg/Follow-ups/Checklist/JD/Agent Trace tabs) opened from the Jobs drawer; shows validation checklist, email-record status, request-changes box, and Approve & Submit.
- 2026-07-09: New endpoints: GET `.../packet`, POST `.../packet/request-changes` (notes + agent regeneration), POST `.../packet/submit` (validation-gated governed Completed move); drag-to-Completed now runs the same finalize gate before emitting the event.
- 2026-07-09: Live-validated in the rebuilt container on Ruby Labs `job_5bfc9d483a1d`: packet fetch, real in-container regeneration (revision 2, mode agent, trace served), progress `packet_review` step, and the confirm/validation submit gates.
- Next: when testing locally, set `LEDGER_BASE_URL`, `KANBAN_BOARD_SNAPSHOT`, `KANBAN_EVENT_LOG`, and `KANBAN_BOARD_STORE` explicitly before launching uvicorn.

## Job Search

- 2026-07-08: Internal backend publishes suggestions, waits for Geoff selection, then routes prepared applications to `Needs Geoff`.
- 2026-07-09: `process-selected` now also processes unprepared `In Progress` cards from UI drag, while ignoring already prepared cards to prevent duplicates.
- 2026-07-09: Processed five live job cards with `--executor codex`; all have generated packets and are parked in `Needs Geoff` for manual review/submission.
- 2026-07-09: Ran public RemoteOK/Jobicy validation; published live suggestions and processed Meta `bot_possible` through Codex packet generation into `Needs Geoff`.
- 2026-07-09: Fixed sports keyword substring scoring (`NFL` in `influence`), stale suggested-card retirement below score threshold, and generated reason-field refreshes.
- 2026-07-09: Diagnosed `digest` JSONDecodeError as concurrent read of directly-written suggestion cache; added atomic JSON cache writes and path-specific corrupt-cache errors.
- 2026-07-09: Added `cc job-search discover-live` with Jobicy/RemoteOK parsers; Airflow DAG now runs Jobicy discovery before digest when Airflow is available.
- 2026-07-09: Added apply-URL duplicate retirement; stale duplicate Suggested cards are routed to `Rejected / Skip` while user-owned/prepared cards remain authoritative.
- 2026-07-09: Raised daily targets to 50 surfaced suggestions and 25 selected/prepared cards per run; board publishing/processing now enforce those config limits.
- 2026-07-09: Ran RemoteOK + Jobicy live discovery; published 50 ranked suggestions and processed 3 bot-possible live jobs (Ruby Labs + two Truelogic) through Codex packet generation into `Needs Geoff`.
- 2026-07-09: Diagnosed bot queue shortage as score-ranked manual jobs crowding out bot-possible jobs; publisher now targets 25 bot-possible + 25 manual-required suggestions before filler.
- 2026-07-09: Added Jobicy industry discovery, invalid tag diagnostics, and Remotive live source; broad live sweep found 74 eligible jobs but only 12 bot-possible above the 70 threshold.
- 2026-07-09: Processed 4 more bot-possible cards through Codex; board now has 11 prepared bot-possible packets in `Needs Geoff` and 25+ manual-required suggestions ready for Geoff.
- 2026-07-09: Airflow `job_search_daily` now runs broader Jobicy/Remotive/RemoteOK discovery, publishes the balanced internal board, and processes only Geoff-selected cards.
- 2026-07-09: Fixed same-company/same-title application ID collisions by appending `job_key`; repaired two Ruby Labs Senior AI Engineer cards to distinct material folders.
- 2026-07-09: Validated Scorpion manual path end-to-end: drag to `In Progress` generated packet, routed to `Needs Geoff` for disability/veteran blockers, and scoped chat reported the correct next action.
- 2026-07-09: Jobs move endpoint now auto-runs packet prep for real unprepared `Selected by Geoff` / `In Progress` cards; live-validated NBCUniversal into `Needs Geoff` with materials and no submit.
- 2026-07-09: Materials are now agent-written by default via LiteLLM (`agent_writer.py`, role `chat`): full achievement bank + STAR stories in the prompt, claim-ID validation with one corrective retry, full prompts/outputs persisted to `agent_trace.jsonl`; failures fall back to templates recorded as `generation.mode=template_fallback` (never silent).
- 2026-07-09: Added review loop primitives: `request_changes`/`regenerate_materials` (review_notes.md, revision bump, `review_state` gate), `packet_validation.py` (8 checks; errors block, warnings surface), `finalize.py` (validate → mark_submitted → email record → `submission_record.json` evidence), `record_email.py` (always writes `submission_email.html`; real SMTP send via `DISCOVERY_SMTP_*` + `JOB_SEARCH_EMAIL_TO`, attachments included; missing vars reported verbatim).
- 2026-07-09: CLI parity: `cc job-search packet [--trace]`, `request-changes --notes`, `finalize`; suite-wide `tests/conftest.py` pins `JOB_SEARCH_AGENT_WRITER=0` so tests never hit the live model.
- 2026-07-09: Proved real generation end-to-end: Ruby Labs regenerate via CLI and via the container endpoint both returned revision 2 agent materials honoring reviewer notes in ~51s; caught the model writing a derived "6+ years" total and added a prompt rule against derived totals.
- Next: SMTP is unconfigured — set `DISCOVERY_SMTP_HOST/USER/PASSWORD/FROM` + `JOB_SEARCH_EMAIL_TO` to turn the on-disk email records into real sends.
- Next: investigate a governed bot-submit path for low-risk portals, including portal terms, sensitive-question detection, review checkpoints, evidence capture, and rollback/error reporting.
- Next: PDF/ATS checks, Gmail matching, rich-file purge, storage report, and prose-level fact checking of agent resumes (claim IDs are validated; derived phrasing is Geoff's review) remain open.
