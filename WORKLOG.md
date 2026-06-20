# Worklog

Compact running log of what's done / in-progress / next, per topic. One–two
liners. Newest notes at the top of each topic. Full design lives in
`docs/growth-os-engineering.md` + `docs/autonomy-idea-map.md`; this is the
fast "has this been done?" index. Dates are when the line was written.

## Channels / gateways (Discord, Slack, Telegram, WhatsApp)
- CAPABILITY 06-13: full-capability pass so the bot works at every tier, not just
  board hygiene. Scope data-derived (grepped tool usage); repo-work loop was
  already wired, so only 3 real gaps. Wall intact (bot DRAFTS+MONITORS only).
- ADD 06-13: `read_item(database, title)` (actions.py + TOOL_FNS) — read-only full
  detail of ONE row (abstract/score/suggested-for/url) so the bot can EXPLAIN a
  paper/repo, not just list titles. Exact→else candidates (no silent guess).
  Verified live: bot called read_item, summarized a paper + flagged betts relevance.
- ADD 06-13: capability-tiered `build_system` (core.py) — enumerates boards /
  research / awareness / repo-work tiers + HOW to drive repo work (add_mission_card
  → Approved drag → gated mission → executor → mission_status). Verified: asked to
  fix a failing betts DAG, bot drafted a DAGs/betts_basketball card w/ measurable
  acceptance + L2 + approve-handoff (write intercepted, no junk card).
- ADD 06-13: `cc notify` / `make notify` (cli/notify.py) — proactive Discord push
  of brief headline + active Ledger missions (active = board_state.LIVE_COLUMNS,
  no literal). Fail-loud on missing creds/Ledger. Verified: real 1237-char push.
- DONE 06-13: `cc notify` schedule DOCUMENTED (run-yourself schtasks/cron one-liner
  in docs/channels.md, mirrors kanban-bridge/snapshot) — agents don't self-install
  host persistence (§13), so you run the one command. Only open item is running it.
- DONE 06-13: `read_item` extended to `notes` (READABLE_DBS = STATUSES|{notes});
  verified live. kanban.yaml risk strings = NO change: RiskTier values ARE
  L0_read_only..L4_dangerous, so `L2_local_edits` is canonical (shortening breaks
  the KanbanSection contract); earlier "tidy" note was speculative.
- ROOT-CAUSED+FIXED 06-13: Discord replied with raw `<function=..>` XML instead
  of acting. Cause: channels used role `triage`=qwen3-coder; its Ollama native
  `PARSER qwen3-coder` DROPS a tool call when the model narrates before it
  (prose+XML land in `content`, `tool_calls` empty) → `core.py` forwards it.
  Measured (narration induced): qwen3-coder 7/8 (ollama) + 6/6 (litellm) leak;
  qwen3:30b 0/8. NOT a LiteLLM bug (passthrough is faithful) — model/parser only.
- FIX 06-13: new `chat` role (qwen3:30b, tool-robust, off-limits to qwen3-coder)
  in models.yaml; channels.yaml all `triage`→`chat`; rendered + restarted litellm
  (`chat` live in /v1/models). Verified e2e via model=chat: 0/4 leak, tools fire.
- FIX 06-13: `core.py` finals run `_clean()` (strip `<think>`, parity w/ assistant);
  fail-loud `_leaked_tool_call` tripwire refuses to forward unparsed tool-call
  markup (logs evidence, returns diagnostic naming cause+fix) — future fragile-model
  regression is loud, never silent.
- FIX 06-13: `planner` moved off qwen3-coder → qwen3:30b (+devstral failover) —
  Hermes (HERMES_DEFAULT_MODEL=planner) tool-calls through it, same parser bug.
  Scope is data-derived: grepped all model calls — only core.py(chat) + Hermes(planner)
  pass tools; judge_gate is JSON-mode (no tools); triage/coder/judges keep qwen3-coder.
- FIX 06-13: `check_cross_refs.check_tool_safe_roles` makes it self-enforcing —
  `make validate` FAILS if a channel role or `planner` is backed by a qwen3-coder
  (prefix match). Verified live: model=chat + model=planner 0 leaks / 23 calls.
  Tests: test_gateway_toolcall.py (5) + test_tool_safe_roles.py (5); validate green.
  (full suite: 503 pass; test_verifier flakes only under full-suite load — passes
  in isolation + in a 47-test batch; unrelated, touches no changed code.)
- DONE 06-13: bot busy rules in `channels/core.py` — one in-flight turn per
  conversation (2nd concurrent msg gets "still working" reply, no history
  corruption / no doubled GPU call) + global `max_concurrency` semaphore
  (env GATEWAY_MAX_CONCURRENCY|OLLAMA_NUM_PARALLEL, default 1). Tested live.
- DONE 06-13: "route to more GPU" MECHANISM — `ModelCandidate.api_base_env`
  (contracts.py) + render emits per-candidate `api_base`; lower-priority
  role candidates can sit on a 2nd Ollama endpoint, LiteLLM load-balances
  (simple-shuffle) + retries survivor. Validates + renders unchanged
  (default OLLAMA_API_BASE). Decision: **fully local, NO Modal** — fail-closed
  invariant kept.
- BLOCKED (user): 5080 failover not live — `msi:11434` unreachable (Ollama off
  or bound to 127.0.0.1), and 5080 is 16GB so it needs devstral:24b (~14GB),
  NOT qwen3-coder:30b (~19GB). Candidate sits COMMENTED in models.yaml; enable:
  on msi `OLLAMA_HOST=0.0.0.0` + run Ollama + `ollama pull devstral:24b`; set
  `OLLAMA_API_BASE_5080` in .env; uncomment triage-5080; `make models`.
- DONE 06-12: Discord bot live again — root cause was **no process running**
  (not config); brains (litellm/ollama) were up the whole time.
- DONE 06-12: canonical runner is `python -m command_center.channels` (reads
  `configs/channels.yaml`, discord-main enabled). Old `services/discord_gateway/`
  is superseded — do NOT run both (two bots on one token).
- DONE 06-12: fixed logging-silence defect — `__main__.main()` now calls
  `logging.basicConfig(INFO)` before adapters; `client.start()` (vs `.run()`)
  installs no handler, so without this the gateway ran blind.
- VERIFIED 06-12: end-to-end `GatewayCore.run_turn` → LiteLLM `triage` → tools
  → AppFlowy returns real answers ("7 open todos"); loop-breaker preserved in
  `core.py` (repeat-call guard + forced final answer).
- DONE 06-13: durable + reusable manager `scripts/gateway.ps1`
  (start/stop/status/restart/autostart) over a hidden self-restarting loop
  (`start_gateway.cmd` via `start_gateway.vbs`). No admin, crash-restart
  proven, autostart registered (Startup\CC Gateway.lnk). schtasks onlogon
  needs admin ("Access denied") — Startup-folder route used instead.
  Reuse for any service: copy the trio, change the module in the .cmd.
- NEXT: enable Slack/Telegram/WhatsApp = set enabled:true in channels.yaml +
  tokens in .env (adapters built, untested live).

## AppFlowy boards / views
- DONE 06-12: removed 5 per-tier library boards (couldn't set their filter via
  REST → showed empty). Read curriculum by tier via the **Tier Board** instead.
- VERIFIED 06-12: server has exactly one board per database, zero duplicates.
- KNOWN (upstream, not us): AppFlowy REST cannot delete/reorder fields or set
  view group/filter/sort — UI-only. Boards auto-group by first single-select,
  which is the junk default `Type` (0 options) until you delete `Type`+`Done`
  columns in the UI; then boards group by `Status` automatically.
- STALE-CLIENT: trashed/changed boards may still show in the app until a hard
  refresh (Ctrl+Shift+R) — server is source of truth. Same class as notes UI.
- NEVER rename Status options — curator/retention/20 tools write exact strings.

## In-app AppFlowy AI
- BLOCKED (upstream): `appflowy_ai` license-walls every request ("commercial
  license not yet available"). Wiring to LiteLLM verified correct; container
  stopped. Use Discord/chat/Claude for AI; revisit when AppFlowy ships license.

## Knowledge watchers (papers/repos/signals/guidelines/packages/dags)
- LIVE 06-12: curate(+enrich) + airflow_sync hourly; brief/guidelines/packages
  /retention daily after 06:00 (curator container loop).
- LIVE: airflow_sync writes live DAG state + root-cause failure summaries;
  drafts a Backlog fix-card per newly-broken DAG (dispatch still human-gated).
- LIVE: `Suggested` annotation ("useful for <project>") on newly kept items.
- Retention: Inbox rows > 7d → Archived (human-triaged rows untouched).

## Kanban → mission loop
- LIVE: bridge applies Approved-only → Ledger mission + CardKey writeback;
  scheduled q15min ("CC kanban bridge" task). Wall proven (L4 held).
- Tools (20): triage/todos/dags/cards/lessons/books + project_status,
  network_health, dag_health, mission_status, book_note. selftest.py = 22/22.

## Registry / adding projects
- `config/projects.yaml` (observe) + `configs/kanban.yaml` (dispatch) — never
  merge. New repo: block in projects.yaml [+ `new_project.py` for a board].

## Proactive ops lane / Judge Gate
- ROOT-CAUSED 06-13: proactive-runner exited 1 every boot via judge-gate 502 on
  `/proactive/judge`. NOT max_tokens (instrumented: finish_reason=stop, 65 tok,
  valid JSON 15/15 — my earlier "bump to 1500" was refuted). Two real causes.
- CAUSE A: `_llm` was blind+lossy (no finish_reason check, content capped 300c)
  → any model hiccup became an opaque "did not return JSON" 502, undiagnosable.
- CAUSE B (base): `run_check` FABRICATED evidence (`<dag_runs for airflow>`); the
  judge ruled on fakes, and once JSON parsed it would open RCA missions off fake
  data. The 502 was the only thing blocking garbage missions.
- FIXED A 06-13: judge_gate `_llm` logs model/finish_reason/usage every call +
  full raw output on failure; reports truncation (finish=length) vs non-JSON
  distinctly. No max_tokens change (not the cause).
- FIXED B 06-13: proactive_runner uses `collectors.py` registry — a check whose
  evidence keys aren't all wired is SKIPPED (no judge call, no mission), never
  fabricated. Empty registry today → all 6 checks skip, runner exits 0.
- TESTS 8/8: tests/test_proactive_runner.py (skip-unwired / judge-when-wired),
  tests/test_judge_gate_llm.py (truncation vs non-JSON vs upstream-error).
- VERIFIED: rebuilt both; runner exit 0 all-skipped; missions 2→2 (no garbage);
  judge-gate logs finish_reason; valid /proactive/judge still 200.
- NEXT: wire real collectors to activate checks (local-first: `ledger_mission_stats`
  + `litellm_spend_api` for usage-digest-weekly; `ruff_report`/`tree` for
  *-standards). Until wired the lane is an honest no-op, not fake-green.

## Desktop automation / timing (appflowy_browser_staging)

- ROOT-CAUSED 06-20: `desktop-timing-derive` derived `action_timeout_seconds` from
  read-only no-op timing (snapshot reads ~15–33 ms) — not real action latency —
  and labeled it `proposed`; schema (`int ≥ 1`) can't even accept sub-second, so
  it was misleading, never enabling.
- FIX 06-20: added `DesktopActionLatencyCanarySpec` + `cc desktop-action-canary` —
  measures a reversible SANDBOX AppFlowy `direct_api` create→delete row round-trip
  (`action_create_ms`/`delete_ms`/`roundtrip_ms`); env-ref creds only; FAILS CLOSED
  (`representative_action_source_not_configured`) when unset. No GUI lib, no
  production board (guarded by `forbidden_targets`), reversible (row deleted).
- FIX 06-20: `desktop-timing-derive` now: read-only = observation-only → `blocked`
  (`action_latency_evidence_required_for_production_candidates`), not `proposed`;
  `action_timeout` from max action round-trip (ceil sec, no multiplier); `ttl_minutes`
  flagged `ttl_evidence_required_from_session_durations` (session lifetime ≠ action
  latency — never fabricated).
- TESTS 06-20: tests/test_desktop_action_canary.py (fail-closed / measured / forbidden-
  target) + updated test_desktop_noop_canary derive tests (read-only→blocked,
  action-latency→action_timeout). Full suite green.
- STATE 06-20: `enable_desktop_target...` correctly still BLOCKED — no AppFlowy sandbox
  wired → no action-latency evidence; ttl has no evidence source.
- NEXT: wire `APPFLOWY_SANDBOX_*` env to a real sandbox board → run `cc desktop-action-
  canary` N times for real evidence; then design a session-duration evidence source
  for `ttl_minutes` before any enablement.

## Kanban registry (boards) — Phase 2

- ADD 06-20: `configs/kanban_boards.yaml` (`KanbanBoardsConfig`) — provider-agnostic
  board registry (provider appflowy|command_center_ui) mapping board_id → repos,
  canonical status workflow, required fields, agent verb contract. Both providers
  share one action contract by construction.
- CONTRACT 06-20: wall verbs (approve_card/merge/deploy/delete_card/delete_board) must
  be forbidden on every board; allowed only grants add/stage/start/finish/block/reject;
  appflowy workspace_ref must be `env:` (no inline secret).
- CMDS 06-20: `cc kanban-verify` (contract + snapshot dup-MissionID/secret check, NOT_RUN
  w/o snapshot), `cc kanban-register` (dry-run default, --apply writes), `cc kanban-sync
  --dry-run` (read-only plan; mutation stays with kanban-bridge). No writes/approves/merges.
- TESTS 06-20: tests/test_kanban_registry.py (15) — schema contract + verify/register/sync.
- DONE (Phase 3): see Repo registry topic below.

## Repo registry (onboarding local repos) — Phase 3

- ADD 06-20: RepoManifest += `kanban_board_id` (binds to a kanban_boards.yaml board) +
  `local_path_ref` (`self`/`env:NAME` only — never a committed absolute path). Enabling
  autonomy now also requires both. llm_station manifest updated accordingly.
- CMDS 06-20: `cc repo-register` (disabled manifest + blockers, dry-run default, local
  path stored as env: ref, --apply inserts+revalidates), `cc repo-verify` (gates:
  devcontainer/CI/CODEOWNERS/board-mapping/local_path_ref/github-app-installed/branch-
  protection/secret-policy + branch-mission & pr-check evidence PASS, NOT_RUN if absent),
  `cc repo-enable-autonomy` (refuses unless all gates pass; --apply flips the flag).
- TESTS 06-20: tests/test_repo_registry.py (12) — gate failures + schema invariants +
  register dry-run/duplicate. repo-verify llm_station PASS.
- DONE (Phase 5): see Cross-conversation memory topic below.

## Cross-conversation / project memory — Phase 5

- ADD 06-20: `command_center.memory` (store + MemoryRecord/MemoryConfig) — durable layer
  the gateway lacked (it kept only an ephemeral per-conversation deque). Scopes:
  conversation/project/board/user_preference/artifact.
- RECALL 06-20: `inject` returns a record only if approved_by_human + inject_policy!=never
  + not stale + scope/subject namespace match → unapproved never recalled; repo memory
  can't leak across repos; each result cites source_ref.
- SAFETY 06-20: MemoryRecord rejects secret-bearing values; source_ref required; confidential
  must be redacted; project/board subject must be stable-id namespace. Store is runtime state
  (generated/memory/, gitignored), not committed. Staleness is per-record retention_policy
  (keep_until_superseded | expire_after_days:N) — no global threshold.
- CMDS 06-20: `cc memory-add` (pending until --approved-by), memory-review/prune/verify.
- TESTS 06-20: tests/test_cross_conversation_memory.py (11). distinct from growthos.memory.
- DONE (Phase 4): see Daily self-improvement topic below.

## Daily self-improvement (observer/draft-only) — Phase 4

- ADD 06-20: cc self-improvement-scan/daily/report (cli/self_improvement.py) over the existing
  discovery pipeline + ObserverCharter (the self_improvement_daily DAG's engine). scan/report =
  zero writes; daily --draft-kanban true drafts Proposed cards only.
- WALL 06-20: daily --apply true (code changes) REFUSED (code_apply_not_supported...); charter
  structurally forbids promote/canary/merge/deploy/set_status (CharterViolation). Drafted cards
  are always Proposed — human approval at the kanban wall turns one into a Ledger mission.
- EVIDENCE 06-20: self-improvement-daily.json (date, findings, drafted ids, applied_code_changes
  false). Offline (network-free) scanners by default — deterministic, no creds.
- TESTS 06-20: tests/test_self_improvement.py (5) — observer-no-writes, draft-only-Proposed,
  code-apply refused, charter forbids promote/merge, report-without-drafting.
- NEXT (Phase 6): real desktop action-latency evidence (needs sandbox board) → enablement gates.
