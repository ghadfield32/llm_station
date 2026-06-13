# Worklog

Compact running log of what's done / in-progress / next, per topic. One–two
liners. Newest notes at the top of each topic. Full design lives in
`docs/growth-os-engineering.md` + `docs/autonomy-idea-map.md`; this is the
fast "has this been done?" index. Dates are when the line was written.

## Channels / gateways (Discord, Slack, Telegram, WhatsApp)
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
