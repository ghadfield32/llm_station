# Worklog

Compact running log of what's done / in-progress / next, per topic. One–two
liners. Newest notes at the top of each topic. Full design lives in
`docs/growth-os/growth-os-engineering.md` + `docs/MASTER.md` (system architecture);
this is the fast "has this been done?" index. Dates are when the line was written.

## Unified runtime Usage / Limits / Availability (src/command_center/usage/)
- PHASE 3 — USAGE & LIMITS COCKPIT API + UI 07-12 (same branch
  `feat/codex-usage-collector`, extends PR #35). The backend layer becomes a
  real operator surface. NEW `usage/cockpit_views.py` = PURE view builders over
  a UsageService (no FastAPI, no SDK) so the cockpit handlers are one-liners and
  the view logic unit-tests alone: usage_overview / runtime_detail /
  limits_overview (each bucket tagged with its runtime availability+staleness,
  provider vs internal_budget kept distinct) / alerts_view / top_drivers (from
  recorded driver facts, "(unattributed)" is explicit) / collector_health (uses
  per-collector get_collection_state so it works on BOTH stores — no new Ledger
  endpoint) / refresh (runs every registered collector via the tracked path).
  Cockpit (`services/agent_kanban_ui/app.py`): 7 read routes —
  GET /api/model-usage, /api/model-usage/{runtime_id}, /api/model-limits,
  /api/model-alerts, /api/model-usage/collector-health,
  /api/model-usage/top-drivers, POST /api/model-usage/refresh (literal paths
  declared BEFORE the {runtime_id} catch-all so FastAPI ordering doesn't swallow
  them). In-process `UsageService(UsageStore())` lazy singleton +
  `_require_usage()` gate; OFF by default (KANBAN_UI_USAGE_ENABLED), with
  KANBAN_UI_USAGE_CODEX (registers the real Codex collector for refresh) /
  KANBAN_UI_USAGE_FAKE (deterministic demo) toggles. Honest-empty: enabled but
  unpolled returns [] and an unseen runtime returns UNKNOWN — never fabricated.
  UI (`web/src/App.tsx` + `api.ts` + `styles.css`): new "Usage & Limits" nav +
  self-contained `UsageView` (own fetch/refresh — no 503-spam of the global 5s
  poll when the feature is off), per-runtime cards (availability badge, provider
  buckets + internal budget as separate bars with used%/reset/credits, rolled
  usage with honest cost — "subscription (not $-metered)"/"cost unknown", never
  $0.00), a stale badge, and a collector-health table. +15 tests
  (test_usage_cockpit_views.py = 9 pure, test_agent_kanban_ui_usage.py = 6
  TestClient: disabled 503, honest-empty, fake-refresh populates, route ordering
  vs {runtime_id}, bad-dimension 400). ruff + `mypy src/command_center/usage/`
  clean; existing cockpit suites still green; `tsc && vite build` clean. NOT yet
  built: SSE live push (/events/stream), reconciliation + routing-decisions
  routes, and enriching /api/chat/runtime + /api/agent-harnesses with a
  usage_summary field (deferred to the next slice).
- PHASE 2.1 — CODEX COLLECTOR COMPLETED (multi-bucket) 07-12 (same branch
  `feat/codex-usage-collector`, extends PR #35). Grounded by a fresh LIVE SDK
  introspection (read-only), which CORRECTED two assumptions in the roadmap
  doc: (1) **`account/rateLimits/read` returns TWO views** — the single-bucket
  compatibility `rate_limits` AND a **`rate_limits_by_limit_id`** dict keyed by
  limit_id (the default `codex` limit PLUS per-model limits, e.g.
  `codex_bengalfox` = "GPT-5.3-Codex-Spark"), each with camelCase
  `primary`/`secondary` windows, its own `credits` (balance/hasCredits/
  unlimited) and a `limitName`. The collector now imports EVERY named bucket:
  the default limit keeps the bare `primary`/`secondary` bucket_ids (so it
  DEDUPES the compat windows — never double-counted), other limits are
  namespaced `{limit_id}_primary/_secondary`, credits import only when
  hasCredits (else None, never a misleading 0.0), and availability takes the
  worst used% across ALL buckets. Live smoke now returns **4 provider_native
  buckets** (was 2). (2) **There is NO `account/usage/read` in the pinned
  app-server** — the JSON-RPC server rejects it as an unknown variant (valid
  account methods: rateLimits/read, read, login/*, logout,
  sendAddCreditsNudgeEmail). So there is no account-level token/daily-bucket
  summary to poll; per-turn token usage flows through the adapter's
  `ThreadTokenUsage` events (NOT re-emitted here → no double-count). Also:
  `account/rateLimits/updated` is a server NOTIFICATION, not a request — the
  worker wires it (and every reconnect) to a fresh `collect()` refresh (one
  code path, no payload-parsing drift). +3 tests (multi-bucket enumeration +
  compat dedup, credits gating, worst-window availability) = 13 collector
  tests; existing 10 compat tests unchanged (fake's empty by_limit_id → compat
  path). ruff + `mypy src/command_center/usage/` clean.
- PHASE 2 — FIRST REAL PROVIDER COLLECTOR DONE 07-12 (branch
  `feat/codex-usage-collector`, stacked on `feat/unified-runtime-usage`/PR #34):
  `collectors/codex_app_server.py` turns the Codex app-server's account +
  rate-limit surface into canonical schemas, source=PROVIDER_NATIVE (so it
  DISPLACES any earlier estimate for the same bucket — proven by test). Every
  field was verified by LIVE SDK introspection: rate limits come from the raw
  RPC `account/rateLimits/read` (no named SDK wrapper) via the underlying
  AsyncCodexClient.request(...), returning a RateLimitSnapshot with
  `primary`/`secondary` RateLimitWindow(used_percent, resets_at EPOCH,
  window_duration_mins) + plan_type + rate_limit_reached_type. Maps each
  window to a PROVIDER-scope LimitSnapshot (bucket_id primary/secondary,
  epoch→ISO reset, window_seconds), derives an AvailabilityEvent from
  rate_limit_reached_type / worst used_percent (available/near/limited/
  exhausted). Emits LIMITS + AVAILABILITY ONLY — per-turn TOKEN usage is
  already captured by the agent-session adapter's own `usage` events, so
  re-emitting here would double-count (Phase 1.1 SampleKind). Never raises for
  an expected provider condition: SDK-absent→UNAVAILABLE, auth/account
  failure→AUTHENTICATION_REQUIRED, rateLimits/read failure→still AVAILABLE +
  a warning (all as CollectorResult warnings + availability events).
  `UsageService.run_collector_tracked()` wraps a collect() in a durable
  CollectionState checkpoint (a genuine crash increments consecutive_failures
  + records last_error; a clean run resets them; auth_state reflects an
  AUTHENTICATION_REQUIRED availability). LIVE SMOKE PASSED against the real
  prolite account (primary 0%/18000s, secondary 0%/604800s, provider_native,
  collection_state auth=ok, 0 alerts). +10 hermetic tests (fake openai_codex
  SDK in sys.modules — translation, availability derivation, all failure
  modes, tracked success/failure state, provider_native beats a prior
  estimate). Added a mypy override for the optional un-stubbed `openai_codex.*`
  (also clears the pre-existing adapter/preflight import-not-found noise).
  ruff clean; `mypy src/command_center/usage/` clean; full repo suite green.
- PHASE 1.1 HARDENING DONE 07-12 (same branch, extends PR #34, before any
  real provider collector is trusted): four correctness fixes over the raw
  foundation. (A) UNKNOWN COST IS NEVER $0.00 — `UsageSample.cost_usd` is now
  nullable and `cost_source` is a real enum (provider_reported / estimated /
  subscription_not_metered / unknown / mixed); subscription Codex/Claude
  activity is `subscription_not_metered` with cost None, shown as "dollar
  cost unavailable", never zero. `summarize_cost()` rolls cost honestly
  (None stays None). (B) NO CROSS-COLLECTOR DOUBLE-COUNTING — new `SampleKind`
  (request_delta / session_total / provider_window_total /
  provider_lifetime_total / daily_bucket / reconciliation_observation); ONLY
  request_delta is additive, so the roll-up sums just those — the same
  activity seen as a request_delta AND a provider_window_total AND a ccusage
  reconciliation_observation counts ONCE, not 3x (provider totals are a
  separate authoritative view). Added window_start/end + aggregation_key. (C)
  ATTRIBUTION DRIVER FACTS on UsageSample (reasoning_tokens, repository_scans,
  test_runs, retries, failed_calls, worker_restarts, session_resumes) so
  "what used the most?" is answered from recorded fact. (D) COLLECTOR
  CHECKPOINTS — new `model_usage_collection_state` table + CollectionState
  (last_cursor/last_success_at/consecutive_failures/next_eligible_at/
  auth_state) so a real collector resumes instead of re-importing a range and
  its failures are visible; plus 7 DDL indexes (runtime/observed, mission,
  repo, user, session, bucket) and a retention policy
  (`UsageRetention`: request_sample_days 90 / keep_aggregates_days 730 /
  keep_alerts_and_routing_indefinitely — the evidence behind a routing
  decision is NEVER pruned) with a `prune_samples()` store method +
  /model-usage/prune endpoint. Same usage.v1 (unmerged, so the DDL is still
  being finalized in place — additive columns, no ALTER needed) — canonical
  DDL + byte-mirror updated together, drift test still green. +12 tests
  (test_usage_hardening.py + cross-backend collection-state/prune/hardening-
  field round-trips) = 50 usage tests; ruff+mypy clean; make validate PASS;
  full repo suite green.
- PHASE 1 FOUNDATION DONE 07-12 (branch `feat/unified-runtime-usage`, stacked
  on `feat/agent-session-runtime`): one SHARED usage layer across every chat
  model AND coding agent, NOT a second control plane. Keeps four concepts
  rigorously distinct so historical usage is never shown as remaining
  provider quota: Usage (observed tokens/calls/cost/duration), Provider
  limits (provider-REPORTED buckets + resets), Availability (installed/
  authed/busy/limited/exhausted/unavailable/unknown), Internal budget (our
  own caps). Investigated the repo FIRST (dedicated Explore pass) — reuses
  `improvement/router_cost.py` for cost math and mirrors the agent_sessions
  Ledger-extension pattern rather than rebuilding either.
- LOAD-BEARING INVARIANTS, each proven by a test (not just asserted):
  provider quota is NEVER overwritten by an estimate (source-priority:
  PROVIDER_NATIVE > PROVIDER_DERIVED > RECONCILER > FAKE > ESTIMATE — a fresh
  estimate loses to a stale provider value); UNKNOWN stays UNKNOWN and stale
  is visibly stale, never coerced to 0%; multiple provider buckets stay
  SEPARATE (never flattened to one %); ingestion is idempotent by
  `source_hash`; alerts dedup by (runtime, subject, kind, threshold, reset)
  so a 30s poll fires an alert ONCE; credentials / raw provider responses /
  raw ccusage logs NEVER enter the Ledger — only normalized rows, traceable
  to tenant/user/session/mission/repo.
- MODULES: `schemas.py` (UsageSample/LimitSnapshot/AvailabilityEvent/
  UsageAlert/RoutingDecision + the composite RuntimeUsageStatus + Attribution
  + source-rank), `protocol.py` (CollectorProtocol/UsageStoreProtocol),
  `store.py` (in-memory + shared `select_latest_*` source-priority selectors),
  `alerts.py` (threshold+dedup, never alerts on UNKNOWN), `attribution.py`
  ("what used the most?" ranked from recorded fact, explicit "(unattributed)"
  bucket), `reconciliation.py` (cross-source mismatch, higher authority wins,
  gap often = usage outside the metered surfaces), `service.py` (the single
  ingest→dedup-alert→roll-up orchestrator), `collectors/fake.py` (a
  deterministic collector — same role as FakeHarness; real Codex/Claude/
  OpenRouter/LiteLLM/Ollama/ccusage collectors are later phases).
- DURABILITY: 5 Ledger tables via the proven mirrored-DDL pattern —
  `usage/ledger_schema.py` (canonical `SCHEMA_VERSION = "usage.v1"`,
  UNIQUE source_hash/dedup_key at the SQL layer so a repeat is a real no-op),
  byte-mirrored into `services/ledger/app.py` (+ init_db block +
  /model-usage* endpoints with fixed column allowlists) and drift-tested.
  `LedgerUsageStore` is a sync drop-in for the in-memory store (injected
  httpx.Client), applying the SAME `select_latest_*` selectors so both
  backends pick the identical winner — proven by a real cross-backend run of
  the same scenarios (idempotency, source-priority, alert dedup, roll-up)
  plus restart-recovery against the same db.
- CONFIG: `configs/usage-monitoring.yaml` + `UsageMonitoringConfig`
  (registered in CONFIG_CONTRACTS, `make validate` covers it). The contract
  STRUCTURALLY refuses `routing.allow_silent_fallback: true` (KPI: silent
  fallbacks = 0), same fail-closed discipline as the frontier budget's
  require_redaction; critical_percent must be >= warning_percent.
- TESTS 07-12: 38 across test_usage_{store,service,attribution,
  monitoring_config,ledger_store,ledger_schema}.py — source-priority both
  directions, UNKNOWN-never-coerced, alert threshold matrix + dedup, honest
  staleness, attribution ranking + unattributed bucket, reconciliation
  mismatch, config invariants, schema drift + additive migration, and
  cross-backend parity + restart recovery against a real Ledger TestClient.
  ruff + mypy clean on all 12 usage source files; full repo suite green.
- NEXT (later phases, explicitly NOT in this branch): the real provider
  collectors (Codex app-server account/rateLimits/usage, Claude
  RateLimitEvent, OpenRouter key endpoint, LiteLLM /spend/logs, Ollama
  health, ccusage reconciler), the /api/model-usage cockpit routes + Usage &
  Limits UI (badges/overview/top-drivers/reset-timeline/alert-center), and
  evidence-based executor routing that consumes model_routing_decisions.

## Agent-session chat integration (Claude Agent / Codex Agent)
- CLAUDE CODE LOCAL (SUBSCRIPTION-LOGIN) ADAPTER DONE + LIVE-PROVEN 07-12 (same
  branch `feat/claude-agent-readonly`, extends PR #36). **The key correction to
  the SDK adapter below: this machine can run Claude with NO ANTHROPIC_API_KEY**
  by driving the installed `claude` CLI with the operator's existing `claude auth
  login` subscription. New `adapters/claude_code_local.py` (harness_id
  `claude_code_local`, label "Claude Agent (local subscription)") is now the
  DEFAULT Claude lane; the SDK adapter stays as the optional API lane (relabeled
  "Claude Agent (API key)"). Both behind the same AgentHarness contract. Verified
  LIVE against the installed CLI (v2.1.207): `claude auth status` →
  `loggedIn:true, authMethod:"claude.ai", apiProvider:"firstParty",
  subscriptionType:"max"`; a real `claude -p ... --output-format stream-json`
  turn ran with `apiKeySource:"none"`. Captured the EXACT stream-json envelope
  (newline-delimited `{"type":...}`): system(subtype=init, carries session_id +
  apiKeySource) → **rate_limit_event**(rate_limit_info: status/resetsAt/
  rateLimitType/overageStatus — camelCase, no utilization) → assistant(message.
  content blocks) → result(session_id, is_error, total_cost_usd = API-EQUIVALENT,
  not real spend). Adapter: each turn is a fresh `claude -p` subprocess (session
  continuity via the CLI's persisted sessions + `--resume <external_session_id>`,
  captured from the init event — restart-safe, no long-lived process). Read-only
  = DEFENSE IN DEPTH: `--tools Read Glob Grep` (actual capability limit) +
  `--disallowedTools` writelist + `--permission-mode plan` + `--strict-mcp-config`
  (no --mcp-config → zero MCP) + `--disable-slash-commands`; **NEVER `--bare`** (it
  forces API-key auth); and the subprocess env has ANTHROPIC_API_KEY STRIPPED so a
  stray key can't silently switch to metered billing. rate_limit_event → the
  existing `rate_limit` AgentEvent, normalized camelCase→snake, feeding
  ClaudeRateLimitCollector. Cost recorded honestly (cost_usd=None, cost_source=
  subscription_not_metered, api_equivalent_cost_usd=<reported>). **LIVE
  ZERO-MUTATION PROOF PASSED**: real read-only turn against a throwaway git repo
  used Glob+Read, gave a real answer, captured a real rate_limit event + session
  UUID, mutation_proof before/after diff EMPTY. +18 hermetic tests (fake
  `_stream_cli` seam + pure `_translate_line`). ruff + mypy clean; full suite
  green. NOT built: workspace/write mode, worker→collector.feed() wiring, cockpit
  selectability, the full 14-item live battery (one live turn proven). GOTCHA:
  introspect the real CLI flags (`claude --help`) — docs' `--tools`/`--safe-mode`
  differ by version; `--permission-mode` choices on 2.1.207 are acceptEdits/auto/
  bypassPermissions/manual/dontAsk/plan.
- CLAUDE AGENT READ-ONLY ADAPTER + RATELIMIT COLLECTOR DONE 07-12 (branch
  `feat/claude-agent-readonly`, stacked on `feat/codex-usage-collector`/PR #35).
  Grounded by a read-only live introspection of the pinned `claude-agent-sdk`
  (0.2.116, `agent-claude` extra) — every class/field verified, NOT guessed:
  ClaudeSDKClient(options).connect/query/receive_response/interrupt/disconnect;
  ClaudeAgentOptions(allowed_tools/disallowed_tools/can_use_tool/permission_mode/
  setting_sources/mcp_servers/plugins/resume/session_id/cwd/model/max_budget_usd);
  messages AssistantMessage(content blocks)/ResultMessage(session_id,total_cost_usd,
  is_error)/SystemMessage/UserMessage/RateLimitEvent(rate_limit_info); RateLimitInfo
  (status allowed/allowed_warning/rejected, rate_limit_type five_hour/seven_day/
  seven_day_opus/seven_day_sonnet/overage, resets_at epoch, utilization, overage_*);
  PermissionResultAllow/Deny. THREE deep-research corrections baked in: (1) NAME =
  "Claude Agent" (never "Claude Code") + ANTHROPIC_API_KEY auth (Anthropic forbids
  claude.ai-login for embedded products) behind --allow-agent-session-egress
  (still `claude_agent: false` in agent-session-budgets.yaml — operator decision).
  (2) `allowed_tools` is a PRE-APPROVE list, NOT a strict allowlist, so read-only
  is DEFENSE-IN-DEPTH: allowed_tools={Read,Glob,Grep} + a disallowed_tools
  writelist + a deny-by-default `can_use_tool` (the authoritative gate: allow iff
  in the read set) + setting_sources=None (isolated) + empty mcp/plugins. (3)
  limits are EVENT-DRIVEN: a RateLimitEvent → a normalized `rate_limit` AgentEvent
  (new event type) whose payload the worker forwards to
  `usage/collectors/claude_agent.py::ClaudeRateLimitCollector.feed()`; that
  collector's `collect()` returns honest UNKNOWN ("no RateLimitEvent observed
  yet") until fed, and maps status→availability + rate_limit_type→a PROVIDER_NATIVE
  bucket (never infers quota from tokens). Adapter mirrors the Codex adapter:
  durable external_session_id (captured from the message stream) + resume=id on a
  restarted instance, per-turn message→AgentEvent translation (dispatch on class
  NAME, never prose), real interrupt, cost capture, close/shutdown. registry.py
  now wires the real ClaudeAgentHarness (deferred import) replacing NotBuiltHarness;
  9 pre-existing tests that used claude_agent as THE "unbuilt harness" example
  updated (both real harnesses now probe the environment honestly — a concrete
  SDK/key blocker, never generic "unavailable"; NotBuiltHarness tested directly).
  +26 hermetic tests (18 adapter via a fake claude_agent_sdk, 8 collector). ruff +
  mypy clean (openai_codex/claude_agent_sdk mypy override). **LIVE ACCEPTANCE
  DEFERRED** — unlike Codex (which reused an existing `codex login`), Claude needs
  ANTHROPIC_API_KEY + egress enablement, neither on this host; built to the
  verified surface + hermetically proven, live end-to-end run is the operator's
  next step. NOT built: workspace/write mode (refused in start_session), the
  worker→collector.feed() wiring, cockpit selectability of claude_agent.
- DECISION 07-11: Claude/Codex will be agent-session harnesses (own SDK, own auth, own
  worktree), never GatewayCore model aliases — no `/chat/completions`-shaped call, no
  entry into GatewayCore.dispatch. Confirmed correct by the frontier tool_calls incident
  above: even a small, explicitly-tool-less integration leaked real local execution the
  moment the harness trusted a field it never offered.
- PLAN 07-11: 8 phases (protocol+fake harness -> Claude read-only -> Codex read-only -> UI
  -> worktrees -> OpenRouter provider profiles -> mission integration -> parallel agents).
  Full doc in-conversation; this log tracks what's actually landed, not the whole plan.
- PHASE 0 DONE 07-11: `cc agent-preflight --harness all` (`cli/agent_preflight.py`) —
  evidence-only, zero routing change, zero writes, zero network calls. Real findings on
  this host (verified, not guessed):
    - `claude` CLI installed (npm, 1.0.119); `claude_agent_sdk` Python package NOT
      installed (`pip install claude-agent-sdk`, verified real via code.claude.com docs).
      ANTHROPIC_API_KEY not set.
    - `codex` CLI installed (0.125.0); `openai_codex` Python package NOT installed
      (`pip install openai-codex`, verified real via raw PyPI JSON — author=OpenAI).
      OPENAI_API_KEY not set, but a real `codex login` session already exists
      (~/.codex/auth.json) — openai-codex's SDK documents reusing that session
      automatically (`login_chatgpt`/`login_chatgpt_device_code`/`login_api_key` all
      supported), so Codex may not need OPENAI_API_KEY at all.
    - **check_forbidden_providers.py's FORBIDDEN_KEYS has ANTHROPIC_API_KEY and
      OPENAI_API_KEY in it, and neither is ever exemptable by
      --allow-frontier-router-egress (only OPENROUTER_API_KEY/ZAI_API_KEY can be) —
      verified by reading the source, not paraphrased.** Anthropic's own Agent SDK docs
      explicitly forbid OAuth/claude.ai-login passthrough for third-party products
      ("use the API key authentication methods... instead"), so a Claude Agent harness
      structurally REQUIRES ANTHROPIC_API_KEY and WILL fail `cc validate` today with no
      existing flag that helps. This is a real, unresolved policy fork — not something
      Phase 2 can code its way around; needs an explicit operator decision (new
      `--allow-agent-session-egress`-style gate, or something else).
    - PyPI naming trap found while verifying: `codex-sdk` on PyPI is Cleanlab's unrelated
      product ("refer to cleanlab-codex instead") — NOT OpenAI's. The real package is
      `openai-codex`. A preflight that assumed the "obvious" name would have silently
      installed the wrong package.
- TESTS 07-11: tests/test_agent_preflight.py (14) — every probe hermetic (no real
  network/SDK/subprocess needed to pass), the forbidden-provider cross-check reads the
  real FORBIDDEN_KEYS/ROUTER_LANE_KEYS constants so it fails loudly if that policy ever
  changes instead of silently drifting, a read-only guarantee test.
- DECIDED 07-11 (Geoff): add a new, separately-gated egress flag for ANTHROPIC_API_KEY/
  OPENAI_API_KEY scoped ONLY to the agent-session subsystem (mirrors
  --allow-frontier-router-egress; never touches the local LiteLLM lane) — not designed/
  built yet, needed before Phase 2. Continue to Phase 1 now.
- PHASE 1 DONE 07-11: `src/command_center/agent_sessions/` — `events.py` (normalized
  AgentEvent, 16-type vocabulary, deliberately distinct from GatewayCore's chat event
  shape), `protocol.py` (runtime_checkable AgentHarness Protocol: probe/start_session/
  send/resolve_approval/interrupt/resume/close), `store.py` (in-memory SessionStore —
  store owns sequence/ts assignment, never trusts a harness-supplied sequence;
  events_since(id, after_sequence) is the reconnect primitive), `fake_harness.py`
  (deterministic FakeHarness — no SDK/subprocess/network; probe() reports itself
  honestly as a test double). No FastAPI endpoints yet (still Phase 4) and no real
  Claude/Codex adapter (Phase 2/3) — this is protocol-level only, by design.
- TESTS 07-11: tests/test_agent_sessions.py (13) — full lifecycle (start -> send ->
  approval required/resolved -> interrupt -> resume -> close), sequence numbers
  monotonic+gapless, events_since reconnect returns exactly the gap (no dupes/misses),
  unknown-session raises loud, mismatched-session approval rejected, FakeHarness
  satisfies the Protocol via isinstance. mypy + ruff clean; full non-job-search suite
  green.
- CORRECTED 07-11: an incoming plan claimed the connected GitHub repo didn't recognize
  8d4b775/650ab35 (history "still begins with 0e7ffa4"). Verified via `git branch -vv`:
  false — that's `origin/main`'s state (irrelevant; this work was never on main). The
  actual branch `feat/research-digest-intake-hygiene-main` already tracked
  `origin/feat/research-digest-intake-hygiene-main`, just 6 commits ahead. Fixed with a
  plain `git push` (no new worktree/branch needed) — pushed clean, 0 ahead now.
- EGRESS GATE DONE 07-11 (`check_forbidden_providers.py`): `AGENT_SESSION_KEYS =
  {ANTHROPIC_API_KEY, OPENAI_API_KEY}` + `agent_session_egress_ready()` +
  `--allow-agent-session-egress`, mirroring `frontier_egress_ready()`/
  `--allow-frontier-router-egress` exactly but fully independent — neither flag ever
  exempts the other's keys (4 tests prove this both directions), and
  check_models_yaml/check_litellm_config (the local LiteLLM lane) stay unconditional
  regardless of either flag (dedicated test mocks them and asserts they still ran).
  Gated by new `configs/agent-session-budgets.yaml` (`default.enabled: false`,
  per-harness `codex_agent`/`claude_agent` toggles — enabled:true with every harness
  off is correctly treated as NOT ready). `make agent-session-egress-check` mirrors
  `frontier-router-egress-check`. Live-smoke-tested against real repo state: correctly
  FAILs today (budgets file disabled by default) — exactly as designed, no key exempted
  by default. 8 new tests in test_forbidden_providers_egress.py; full suite green.
- NEXT (Phase 2, not started — explicitly deferred this session, real infra/quota
  consequences): flip `configs/agent-session-budgets.yaml` for the chosen harness,
  install `openai-codex`/`claude-agent-sdk` in a dedicated optional-deps group (pin a
  real version, not floating), build the real read-only adapter(s), prove no repo
  mutation via hash-before/after. Codex may not need the new egress flag at all if it
  authenticates via the existing `codex login` session instead of OPENAI_API_KEY —
  verify that with a real SDK call before relying on the preflight's static finding.
- STACKED BRANCH 07-11: PR #32 (`feat/research-digest-intake-hygiene-main` -> main)
  verified real via `gh pr view` — its title/body genuinely only describe research-
  digest/log-hygiene/skills/card-deps, not any cockpit/frontier/job-search/agent-
  session work landed on the branch since. Rather than keep growing that PR, new work
  moves to a stacked worktree/branch (`C:\tmp\cc-agent-runtime`,
  `feat/agent-session-runtime`, based on `origin/feat/research-digest-intake-hygiene-
  main`) — this and every entry below is committed there, not on the main branch.
- DURABLE STORE DONE 07-11 (Milestone 1, part 1): investigated Ledger first, as
  required, before building anything new — real verdict: Ledger IS in-repo
  (`services/ledger/app.py`, SQLite, durable) with an established extension pattern
  already proven for the experiment registry (mirrored DDL + drift test, since the
  container can't import command_center). Reused that exact pattern instead of a
  second database: new `agent_sessions`/`agent_session_events` tables
  (`src/command_center/agent_sessions/ledger_schema.py`, mirrored into
  `services/ledger/app.py` as `AGENT_SESSION_SCHEMA_SQL`, drift-tested) + 6 new Ledger
  endpoints (`POST /agent-session`, `GET /agent-sessions`, `GET|POST /agent-session/
  {sid}[/event|/events|/status]`) — the Ledger, not the caller, assigns event sequence
  numbers transactionally with the insert (same "never trust a vendor-supplied
  ordering" discipline as store.py). New `LedgerSessionStore`
  (`agent_sessions/ledger_store.py`) is a SYNC drop-in for the Phase-1 in-memory
  `SessionStore` — same 5-method surface, so FakeHarness needs zero changes to run
  against either backend. Proved this for real: `FakeHarness(LedgerSessionStore(...))`
  runs the exact same lifecycle assertions (start/send/approval/interrupt/resume,
  events_since reconnect, unknown-session KeyError) against a REAL Ledger app
  instance, not a mock. A real bug caught by adding a payload round-trip test before
  trusting the endpoint: the events-list endpoint was returning the payload column as
  a double-encoded JSON string instead of a real object — fixed to decode server-side,
  matching how `get_experiment` already avoids the same trap.
- TESTS 07-11: test_agent_session_ledger_schema.py (3, drift-detection, mirrors
  test_ledger_experiment_schema.py), test_agent_session_ledger_rest.py (8, incl. a
  real restart-recovery test — a second app instance opened against the same db file
  recovers every session/event and continues sequences correctly, not resetting),
  test_agent_sessions_ledger_store.py (5, cross-backend FakeHarness parity). mypy +
  ruff clean on every changed file; full suite (including job_search — this worktree
  has none of the concurrent session's uncommitted files) green in this clean
  worktree.
- DURABLE APPROVALS DONE 07-11 (Milestone 1, part 2, prerequisite before registry/
  service): `FakeHarness._pending_approvals` was still an in-memory dict a restart
  would silently drop — moved into the store as a proper `ApprovalRecord`
  (approval_id/session_id/action/status/requested_at/resolved_at/approved/reason),
  same durability contract as sessions/events. New `agent_session_approvals` Ledger
  table (mirrored + drift-tested like the other two) + 3 endpoints (create/get/
  resolve) — resolve is session-bound and one-use (replay returns 409, wrong-session
  returns 403) — matches `create_session`, the server (not the caller) generates
  `approval_id`. `SessionStore`/`LedgerSessionStore` both gained
  `create_approval`/`get_approval`/`resolve_approval`; `FakeHarness` now holds NO
  session-scoped state of its own at all (interrupted status reads `store.get(...)
  .status` instead of a local set too) — a fresh FakeHarness instance pointed at the
  same store behaves identically to the original, which is exactly the recovery
  contract a real adapter must satisfy later.
- REGISTRY + SERVICE DONE 07-11 (rest of Milestone 1, still zero real SDK):
  `registry.py` — `HarnessRegistry`/`HarnessDescriptor`, `default_registry(store)`
  wires `fake` (production=False) + `codex_agent`/`claude_agent` as `NotBuiltHarness`
  placeholders whose `probe()` reports an exact, specific blocker (never a generic
  "unavailable") without importing any SDK — verified by a test that `openai_codex`/
  `claude_agent_sdk` never enter `sys.modules` just from listing harnesses.
  `service.py` — `AgentSessionService` is the sole lifecycle owner (start/send/
  events/approve/interrupt/resume/close/list_harnesses); `_active_harnesses` is an
  explicit PROCESS-LOCAL cache only, never trusted as the source of truth — every
  method reconstructs a harness from the registry when the cache is empty, so a
  restarted service serves a FakeHarness session identically (proved with a real
  test: brand-new service, fresh store client, fresh in-process cache, same Ledger
  db — recovers full history AND the session is still live/usable, sequence
  continues correctly). New `SessionStoreProtocol` (mirrors `AgentHarness`'s
  `runtime_checkable` pattern) lets the service accept either backend without
  hardcoding a type. Also added a structural guardrail test:
  `issubclass(GatewayCore, AgentHarness)` is False — the two execution systems
  cannot be confused even by accident.
- TESTS 07-11: test_agent_session_approvals.py (11, parameterized across both
  backends incl. pending-approval-survives-restart), test_agent_session_registry.py
  (8), test_agent_session_service.py (16, parameterized across both backends incl.
  service-level restart recovery + the GatewayCore guardrail). 71 agent-session
  tests total now pass together; mypy + ruff clean on all 9 package files; full repo
  suite green in the clean worktree.
- HOST WORKER DONE 07-11 (`cc agent-worker`, `agent_sessions/worker_app.py` +
  `cli/agent_worker.py`): standalone FastAPI+uvicorn process, binds 127.0.0.1 by
  default (`--host`/`AGENT_WORKER_HOST` to override), port 8791 by default
  (`AGENT_WORKER_PORT`). `build_app()` requires BOTH `AGENT_WORKER_TOKEN` and
  `LEDGER_BASE_URL` and refuses to start without them — no silently-generated
  token, no silent in-memory-store fallback if Ledger isn't configured (a worker
  that silently degraded to non-durable storage would undo the entire durable-
  store milestone). Every `/api/*` route requires `Authorization: Bearer
  <token>` (401 otherwise); `/health` is deliberately unauthed for basic
  liveness probing. Exposes the exact 8-route surface from the plan
  (`GET /api/agent-harnesses`, `POST /api/agent-sessions`, `GET/POST` per-
  session routes for messages/events/approvals/interrupt/resume, `DELETE` to
  close) as a thin, fully-tested wrapper around `AgentSessionService` — store-
  layer `KeyError`/`ValueError`/`RuntimeError` map to 404/409/400 respectively,
  never swallowed into a fabricated 200. Plain JSON GET for `/events` (not SSE)
  — this is the internal worker-to-cockpit hop, not the browser-facing one; SSE
  is scoped to the cockpit's own proxy layer, next.
- TESTS 07-11: test_agent_worker.py (11) — full lifecycle over real HTTP calls
  (not direct service calls), token auth enforced on every /api/* route and
  bypassed on /health, unknown-harness 404 / unavailable-harness 400 with the
  exact blocker text, approval replay 409, unknown-session 404 on every route,
  and both no-token/no-ledger-url startup refusals. A real mypy catch while
  wiring this in: `registry.py`/`fake_harness.py` still typed their store
  parameter as the concrete `SessionStore` instead of the new
  `SessionStoreProtocol`, which would have silently broken passing a
  `LedgerSessionStore` through — fixed before it became a runtime bug. 96
  agent-session tests total; mypy+ruff clean on all 11 package files; full repo
  suite green (confirmed twice — the first full-suite run hit a one-off flake
  in an unrelated experiment-registry test caused by editing WORKLOG.md while
  pytest was mid-run in the same worktree; reran untouched and it passed clean,
  confirming it wasn't a real regression).
- ASYNC EXECUTION CORRECTION 07-11 (before the cockpit proxy, as required): the
  worker's `POST /messages` originally drained the harness's full async
  generator and returned every event in one JSON response — fine for
  FakeHarness's instant completion, wrong for a real multi-minute Codex/Claude
  turn (the HTTP call would block for the whole turn, with no way to
  interrupt). Now: `POST /messages` validates the session (404/400/409 —
  closed / interrupted-or-failed requiring `/resume` first / already has an
  active turn), schedules a background `asyncio.Task`, returns 202
  immediately. A process-local `active_runs: {session_id: Task}` dict is the
  ONLY source of truth for "is a turn genuinely running" — this forced a real
  fix to the status vocabulary: `start_session()`/`resume()` now set `"idle"`
  (ready, no task running), not `"active"` — `"active"` is set EXCLUSIVELY by
  the worker's task wrapper while a turn is genuinely in flight, and back to
  `"idle"`/`"failed"`/`"interrupted"` when it ends. This distinction is what
  makes restart reconciliation unambiguous: a fresh worker process's
  `active_runs` is always empty, so ANY session still reading `"active"` at
  startup is, by definition, orphaned — `_reconcile_orphaned_sessions()` marks
  it `failed` with an honest reason before serving any request. New
  `list_sessions(status=...)` on `SessionStoreProtocol`/both backends (the
  Ledger endpoint already existed from the durable-store milestone; only the
  client method was missing). `/interrupt` now cancels the real task if one
  exists; `/close` cancels-and-awaits before setting the final `closed` status
  so the two writes can't race.
- REAL BUG FOUND VIA TESTING 07-11: `starlette.testclient.TestClient` bridges
  sync test code to the async app via a portal running in its own thread — a
  task spawned with `asyncio.create_task()` during one `.post()` call was
  empirically found NOT to reliably survive to a LATER `.post()` call on that
  same portal (it came back cancelled/"interrupted" even with a thread-safe
  `threading.Event` gate, ruling out a naive cross-thread-signal explanation).
  This is a `TestClient`-specific artifact of its per-call task-group
  boundary, not a bug in the worker — a real uvicorn process has no such
  boundary. Confirmed by rewriting the concurrency test on
  `httpx.AsyncClient(transport=ASGITransport(...))` with everything on ONE
  event loop (no thread/portal at all): passes cleanly. Lesson for future
  agent-session tests: anything that needs a background task to survive
  across multiple separate HTTP calls must use the single-event-loop
  AsyncClient pattern, not TestClient.
- TESTS 07-11: test_agent_worker.py grew to 15 (was 11) — concurrent-turn 409
  (via a controllable `_SlowHarness` gated on an `asyncio.Event`, the only way
  to make the race deterministic instead of hoping FakeHarness stays "slow
  enough"), message-to-interrupted-session 409 until `/resume`,
  message-to-closed-session 400, and a dedicated worker-restart-reconciliation
  test (force a session to `"active"` with no backing task, build a second
  `build_app()` against the same store, confirm it's marked `failed` with the
  exact reason). `build_app()` gained an optional `registry` parameter
  specifically so tests can inject a controllable non-FakeHarness harness
  without touching production wiring. 100 agent-session tests total; mypy+ruff
  clean; full repo suite green (confirmed undisturbed this time — no file
  edits while pytest was running).
- COCKPIT PROXY + SSE DONE 07-11 (Commit 1 of the two-commit cockpit plan): new
  `services/agent_kanban_ui/agent_worker_client.py` — the cockpit's ONLY path
  to the host worker (owns base URL/token/timeouts; sync httpx.Client, matching
  the service's existing convention, since FastAPI runs plain `def` routes in a
  threadpool). `app.py` gained `AGENT_SESSIONS_ENABLED`/`FAKE_AGENT_ENABLED`/
  `AGENT_WORKER_URL`/`AGENT_WORKER_TOKEN` (all default off/unset, matching
  `CHAT_ENABLED`'s gating pattern), the full 8-route proxy surface (harnesses/
  create/get/messages[202]/events/approvals/interrupt/resume/close) mapping
  worker `AgentWorkerUnavailable` -> 502 and worker 4xx/error bodies -> the
  same status+detail (never swallowed into a fabricated 200), Fake Agent
  filtered out of `/api/agent-harnesses` and 403'd on create unless
  `FAKE_AGENT_ENABLED`, and `agent_worker` added to `/api/status` +
  `/api/debug/runtime` probes (token deliberately never included in either).
  Every agent-session route is a straight proxy — none of them ever construct
  or call GatewayCore (a dedicated test monkeypatches `_get_core` to raise if
  called, hits 4 agent routes, asserts clean).
- TWO REAL INFRA GAPS CAUGHT BEFORE THEY SHIPPED: (1) `Dockerfile` only
  explicitly `COPY`s `app.py`, not sibling modules — would have silently
  broken the container build the moment `agent_worker_client.py` existed;
  fixed with an explicit second `COPY` line. (2) the test harness loads
  `app.py` via `importlib.util.spec_from_file_location`, which does NOT add
  the file's own directory to `sys.path` — a plain `import
  agent_worker_client` would fail under pytest despite working fine under
  real `uvicorn app:app`; fixed with an explicit `sys.path.insert(0,
  str(Path(__file__).resolve().parent))` guard at the top of `app.py`, ahead
  of the import, so both loaders agree.
- SSE FRAMING DONE 07-11: `GET /api/agent-sessions/{id}/events/stream` mirrors
  the existing `/api/events/kanban` convention exactly — `id: <sequence>\n
  event: agent_event\ndata: {...}\n\n`, `Last-Event-ID` header wins over
  `?after_sequence` (extracted into a standalone `_resolve_sse_checkpoint()`,
  clamped non-negative), a `: heartbeat\n\n` comment line every
  `_AGENT_EVENT_HEARTBEAT_SECONDS` (15s) of no new events, and worker
  transport/4xx failures surfaced as a distinct `event: transport_error` frame
  — never persisted as a fabricated `AgentEvent`. The actual polling loop is
  `_agent_event_frames(client, session_id, checkpoint, is_disconnected)`, a
  standalone generator taking disconnect-checking as an injectable async
  callable; the route itself is a 2-line wrapper.
- REAL TEST-INFRA BUG FOUND VIA TESTING 07-11 (second time this arc): driving
  a genuinely long-lived SSE generator through `TestClient.stream(...)` hung
  the entire pytest process indefinitely — even with an early `break` after
  the assertions passed and exiting the `with` block, the surrounding process
  never returned. Reproduced twice, each requiring a hard kill of the
  background test run. Root-caused as the same class of `TestClient` portal/
  lifecycle limitation as the async-execution-correction entry above (a
  different symptom, same underlying cause: TestClient's sync/async bridging
  does not behave like a real ASGI server for anything long-lived). Fixed the
  same way: bypass TestClient entirely for this logic. `_agent_event_frames`
  and `_resolve_sse_checkpoint` are tested by calling them directly via
  `asyncio.run()` with a bounded fake `is_disconnected` (`_disconnect_after(n)`
  — False for n calls, then True), never through HTTP. Lesson reinforced:
  TestClient is unreliable for anything that spans multiple calls or runs
  indefinitely; test the underlying async logic directly instead.
- TESTS 07-11: `tests/test_agent_kanban_ui_agent_sessions.py` (19) — disabled-
  by-default 503, worker-unreachable 502, worker 404/409/400 preserved
  verbatim, 202 on message accept, token never appears in any response body
  (harnesses/debug-runtime/status, checked via `.text` substring), Fake Agent
  filtered/blocked/visible correctly across 4 tests, GatewayCore-never-
  constructed across 4 routes, `_resolve_sse_checkpoint` header-wins/query-
  fallback/non-numeric-fallback/never-negative (4 assertions), ordered SSE
  events, reconnect-from-checkpoint with no duplicates, worker-unavailable and
  worker-4xx both becoming `transport_error` (never an `agent_event`), and
  heartbeat firing with zero real events emitted. Pre-existing
  `tests/test_agent_kanban_ui.py` (47) still green unchanged. ruff clean on
  all 3 changed/new files (mypy doesn't apply — `services/` is outside
  `[tool.mypy] files = ["src"]`). Full repo suite green, run alone with no
  concurrent file edits.
- AGENT SESSIONS UI DONE 07-11 (Commit 2, FakeHarness cockpit interface —
  frontend-only, no backend changes): `api.ts` gained typed
  `AgentHarnessOption`/`AgentSessionRecord`/`AgentEvent` contracts + client
  functions for the full lifecycle (create/get/send/events/approve/interrupt/
  resume/close) plus `streamAgentEvents` — native browser `EventSource`
  rather than a manual fetch-reader (unlike `streamChat`'s POST-body stream,
  this is a plain GET, so `EventSource` gets `Last-Event-ID` reconnect for
  free and silently ignores heartbeat comment lines with no special-casing).
  `App.tsx`'s chat target changed from a bare `target` string to a real
  discriminated union (`ChatTarget = {kind:"gateway"} | {kind:"agent",
  harnessId} | {kind:"external", name}`) via `decodeChatTarget` — every one
  of the ~15 existing `target === "GatewayCore"`-style comparisons in
  `ChatView` now switches on `.kind` instead. A new "Agent Sessions" optgroup
  in the existing agent/target `<select>` lists live harnesses from
  `fetchAgentHarnesses()`; Fake only appears when the BACKEND included it
  (`KANBAN_UI_FAKE_AGENT_ENABLED` — no separate frontend dev flag needed,
  the backend is the single source of truth), Codex/Claude always render as
  disabled options carrying their real `NotBuiltHarness` blocker text as the
  tooltip (never a generic "unavailable").
- NEW `AgentSessionPanel` + `AgentEventCard` components: session creation
  form (repo/mode — `permission_profile` hardcoded `read_only`, workspace
  write-mode explicitly out of scope) when no session exists yet; once one
  does, a dedicated per-event-type renderer (never inferring tool activity
  from prose — matches the backend's own "an agent session's tool surface is
  much bigger, don't trust it implicitly" discipline), a derived pending-
  approvals list (any `approval_required` without a later matching
  `approval_resolved` in the event log) with approve/deny buttons, and
  interrupt/resume/close controls gated on real session status.
- REFRESH RECOVERY DONE 07-11: agent-session metadata (`agentSessionId`,
  `agentHarnessId`, `agentRepoId`, `agentMode`, `agentPermissionProfile`,
  `agentLastSeenSequence`) was added to the LOCAL `ChatThread` type only —
  deliberately never sent through `persistThread`/`saveChatThread`
  (GatewayCore's flight-recorder thread store), matching the "structurally
  separate execution path" rule everywhere else in this subsystem. A new
  small `activeThread` localStorage pointer (conversationId + target)
  restores the last-open thread/lane across a real browser reload; on mount,
  `AgentSessionPanel` re-verifies a persisted session against the real
  worker (`fetchAgentSession`), replays full history
  (`fetchAgentEvents(id, 0)`), then resumes the live stream from the last
  real sequence — never trusts the persisted state blindly.
- VERIFIED 07-11: `npm run build` (`tsc && vite build`) clean with ZERO type
  errors on the first attempt despite the ~550-line diff across a
  discriminated-union refactor of ~15 call sites — no backend changes in this
  commit, so `tests/test_agent_kanban_ui.py` (47) + `test_agent_kanban_ui_
  agent_sessions.py` (19) re-run unchanged/green, full repo suite green
  (run alone, no concurrent edits). Docker build caught a REAL verification
  gap on the first attempt: a `docker build` from the wrong `cwd` (the Bash
  tool's cwd had silently drifted back to the main checkout — the same
  recurring gotcha from earlier this session) produced an image that
  "succeeded" entirely from BuildKit cache and contained NONE of the new
  frontend code; caught by grepping the built JS bundle for a known new
  string ("Agent Sessions") and finding nothing, not by trusting a green
  `docker build` exit code. Rebuilt from the correct worktree path — the web
  build step genuinely re-ran this time, and the built bundle was confirmed
  to contain the new UI strings and `agent_worker_client.py` before deleting
  the test image.
- 20-ITEM ACCEPTANCE GATE RUN 07-11 (live, not mocked): a real `cc
  agent-worker`-equivalent process (real FakeHarness, real in-memory
  SessionStore, real uvicorn on a real socket) driven end-to-end through the
  cockpit's real `app.py` routes — disabled-mode 503, unreachable-worker 502,
  token-redaction across 3 endpoints, Fake-Agent gating both directions,
  Codex/Claude's concrete blocker text, full session lifecycle (create ->
  get -> send [202, non-blocking] -> ordered events -> "write ..." producing
  a real `approval_required` -> approve -> `approval_resolved` -> replay
  rejected 409 -> interrupt -> blocked-until-resume 409 -> resume -> message
  accepted again -> SSE reconnect via `Last-Event-ID` mid-stream delivering
  only the gap (the real `_agent_event_frames` generator against the real
  worker, not a stub) -> close -> further message rejected 400), GatewayCore
  never constructed anywhere in the run (every response checked for a
  surfaced 500 from the `_get_core` guard), and a real heartbeat firing on
  an idle stream against the real worker. 20/20 passed. A first attempt at
  running the cockpit itself as a second real uvicorn subprocess (rather than
  `TestClient`) was abandoned after proving flaky to orchestrate from this
  shell on Windows (silent startup failures with no readable error) — same
  production code path either way (`AgentWorkerClient` makes genuine HTTP
  calls to the real worker process regardless), so `TestClient`-over-a-real-
  worker was used instead, matching the pytest suite's own proven-reliable
  pattern. Scratch script, not committed.
- NEXT: Commit 2 is code-complete and verified; real Codex/Claude adapters,
  worktree write mode, mission executor routing, and OpenRouter agent
  provider profiles remain explicitly out of scope (Phase 2/3+, not started).
- NEXT: the cockpit's `/api/agent-sessions/*` proxy+SSE endpoints (talking to
  this worker over `host.docker.internal:8791`, matching the existing Ollama/
  AppFlowy pattern in docker-compose.yml) and the Agent Sessions UI — still
  entirely FakeHarness-backed, still zero paid/authenticated calls. Real Codex/
  Claude adapters remain explicitly out of scope until that vertical slice
  works end-to-end and a human decides to proceed.
- INCIDENT 07-11 (real, contained, fully recovered): a Bash tool cwd silently
  drifted from this worktree (`C:\tmp\cc-agent-runtime`) back to the main
  `llm_station` checkout mid-session (the same class of drift documented
  earlier this arc for `docker build`/`git status`). A throwaway proof `.env`
  write and a `docker compose up` — both intended for an isolated worktree-
  only proof — ran from the wrong directory instead, overwriting the REAL
  `.env` and recreating the REAL `llm_station-ledger-1`/`llm_station-agent-
  kanban-ui-1` production containers with disposable secrets and shifted
  ports. Caught immediately (container names were `llm_station-*`, not
  `cc-agent-runtime-*`), fully recovered: Ledger `PRAGMA integrity_check` =
  `ok` with every real table intact, zero Docker volume changes across the
  whole incident (before/after `docker volume ls` diff empty), and — better
  than expected — the real, complete, current `.env` was recovered from VS
  Code's own Local History (a snapshot ~22h before the incident, cross-
  verified byte-for-byte-equivalent `LITELLM_MASTER_KEY`/`POSTGRES_PASSWORD`
  against the untouched live `litellm`/`litellm-db` containers), so no secret
  needed rotating. Full evidence trail preserved outside the repo. Root cause
  was structural, not "be more careful": nothing verified the actual Docker/
  filesystem target before a destructive-capable command ran.
- SAFETY TOOLING DONE 07-11 (the structural fix, before any further live
  proof work): `scripts/run_agent_deployment_proof.ps1` is now the ONLY
  sanctioned way to bring up an isolated ledger+cockpit pair for a live
  agent-session proof. Refuses to run (exit 1, `REFUSED: ...`) unless every
  invariant holds — resolved git root matches the expected worktree, current
  branch matches, proof-env project name is never `llm_station` and must
  self-document as disposable (contains "proof"), the proof `.env` path must
  live INSIDE the worktree and must never be named `.env`, and (checked again
  AFTER container creation, not just before) no resulting container name may
  start with `llm_station-`. `-DryRun` runs every check with zero Docker/
  filesystem side effects — this is what the test suite exercises, so the
  guarantees are provable without a daemon. No-clobber env generation
  (`-GenerateEnv`): an existing proof `.env` is never regenerated or
  overwritten, verified by a real test that plants a sentinel value and
  confirms it survives. `docker-compose.agent-proof.yml` is a documentation/
  defense-in-depth override (`restart: "no"` for the two proof services) —
  the REAL volume-isolation guarantee is Compose's own automatic project-name
  volume namespacing (verified: `docker-compose.yml`'s `ledger_data` has no
  `name:`/`external:` override, so a distinct `-p` value alone guarantees a
  distinct volume, never `llm_station_ledger_data`).
- TESTS 07-11: `tests/test_agent_deployment_proof_safety.py` (10, 1 skipped
  when no second fixed-path git repo is available for the synthetic root-
  mismatch case — the realistic incident scenario, wrong root AND wrong
  branch together, is covered by the branch-mismatch test instead, which is
  what actually caught the real incident) — shells out to the real script via
  `pwsh`/`powershell` (skips cleanly if neither is on PATH), asserts refusal
  for: `llm_station` project name, a project name without "proof" in it,
  wrong branch, `.env`-named proof path, proof path outside the worktree,
  missing proof env without `-GenerateEnv`; asserts success + zero side
  effects for the happy path and for no-clobber. First test run caught a
  real test-design bug (not a script bug): three tests used pytest's own
  `tmp_path`, which lives outside the worktree — the script correctly
  refused per its own "must be inside worktree" invariant; fixed by adding an
  `in_worktree_proof_env` fixture instead of weakening the script.
- DURABLE SESSION METADATA DONE 07-11 (prerequisite for the real Codex
  adapter, deliberately its own commit — no Codex-specific code in this
  one): a real harness adapter has real vendor identity to persist
  (`external_session_id`, `worker_id`, `model`, `provider_profile`,
  `cost_usd`) that FakeHarness never needed. New `update_session()` on both
  `SessionStore` and `LedgerSessionStore` — every parameter optional, only
  supplied fields change, mirrored by a new Ledger `POST /agent-session/
  {sid}/fields` endpoint (same partial-update discipline, 404 on an unknown
  session). `list_sessions()` gained `conversation_id`/`repo_id` filters on
  both backends plus the Ledger's `GET /agent-sessions` query params, so a
  session can be found without already knowing its id — new worker route
  `GET /api/agent-sessions` and matching cockpit proxy route expose this to
  the browser (session discovery without relying exclusively on local
  browser storage). No schema change (existing columns, new endpoint only),
  so no drift test needed here.
- TESTS 07-11: cross-backend parity proven the same way the original
  durable-store milestone did — identical assertions run against BOTH the
  in-memory store (`test_agent_sessions.py`) and a real Ledger instance
  (`test_agent_sessions_ledger_store.py`), plus direct REST coverage
  (`test_agent_session_ledger_rest.py`: partial-update semantics, 404 on
  unknown session, filter combinations including a no-match case) and the
  worker/cockpit HTTP surface (`test_agent_worker.py`,
  `test_agent_kanban_ui_agent_sessions.py` — the latter needed a
  `list_sessions` method added to the test suite's `_FakeWorkerClient`
  stub). ruff clean; mypy clean on the `src/` files touched.
- HOST WORKER DEPLOYMENT WIRING 07-11: `scripts/start_agent_worker.ps1`
  (start/stop/restart/status/autostart, mirrors gateway.ps1's conventions —
  runs `cc agent-worker` hidden on the HOST, loads AGENT_WORKER_TOKEN from
  .env, refuses to start without it). `docker-compose.yml`'s agent-kanban-ui
  service gained the `AGENT_WORKER_URL`/`AGENT_WORKER_TOKEN`/
  `KANBAN_UI_AGENT_SESSIONS_ENABLED`/`KANBAN_UI_FAKE_AGENT_ENABLED` env
  (worker reached via `host.docker.internal:8791`, same pattern as Ollama/
  AppFlowy — all default OFF). `.env.example` documents the agent-worker
  block (empty placeholders only, no secrets). This is FakeHarness-era ops
  wiring — how to RUN the worker — committed separately from the Codex
  adapter (what it runs).
- REAL CODEX READ-ONLY ADAPTER DONE 07-11 (`adapters/codex_agent.py`, the
  audited/hardened version of the pre-incident prototype). Backed by the
  pinned `openai-codex==0.1.0b3` (`agent-codex` optional-deps extra;
  `openai-codex-cli-bin==0.137.0a4` bundled). Every SDK type used was
  verified by LIVE introspection against the pinned package (see the
  introspection findings below), never guessed from docs. Real live probe
  passed end-to-end against Geoff's actual `codex login` session (auth,
  read-only thread, first turn, same-thread follow-up, resume-by-id via a
  fresh instance, interrupt, ZERO filesystem mutation via mutation_proof.py's
  before/after snapshot). Read-only analysis mode ONLY; workspace/full-access
  refused. `configs/agent-session-budgets.yaml` flips `codex_agent: true`
  (Geoff-authorized; note Codex auth is ChatGPT-session, sets no forbidden
  vendor key, so this gate doesn't actually exempt any key for Codex).
- REAL SDK FINDINGS baked into the adapter (each a live discovery, not a
  doc claim): (1) auth reuses the existing `codex login` session — no
  OPENAI_API_KEY, consumes subscription quota. (2) `handle.stream()` yields a
  generic `Notification(method, payload)` envelope; the concrete typed event
  is `.payload`. (3) `ThreadItem` (and other nested types) are pydantic
  RootModel wrappers — real fields live on `.root`, accessed via a `_unwrap`
  helper. (4) a global `~/.codex/config.toml` model/effort newer than the
  pinned CLI build breaks `thread_start` ("gpt-5.6-sol requires a newer
  Codex") — fixed WITHOUT touching the operator's global config, via a
  per-session `config_overrides=("model_reasoning_effort=medium",)` plus
  dynamic model validation. (5) the SDK exposes NO programmatic hook to
  resolve a Guardian approval review — decisions are auto (`auto_review`) or
  blanket (`deny_all`); this harness uses `deny_all`.
- AUDIT HARDENING (each a specific fix over the raw prototype): (A) preflight
  `overall` is truthful for codex-only runs — the ANTHROPIC/OPENAI forbidden-
  provider policy probe is Claude-specific and no longer BLOCKs a
  `--harness codex --live` run, AND `codex_api_key_present` is now
  informational (its NOT_CONFIGURED is the EXPECTED existing-login state, so
  it no longer drags overall to NOT_CONFIGURED). Result: a real
  `cc agent-preflight --harness codex --live --repo llm_station` now reports
  `overall: PASS` (verified live, 14/14 gating checks pass, zero mutation).
  (B) dynamic model validation
  (`configs/agent-session-models.yaml`: preferred_model + reasoning_effort +
  allow_sdk_default_fallback) — never a hardcoded model trusted blind; the
  configured/requested model is checked against the SDK's OWN live
  `client.models()` list, falls back to the SDK-designated default, and the
  selected model + selection reason are recorded on `session_started`.
  (C+D) per-turn `_TurnState` coalesces assistant deltas by item_id (a
  completed agentMessage whose text already streamed is NOT re-emitted) and
  dedupes terminal failures (a non-retryable ErrorNotification followed by
  TurnCompletedNotification(failed) yields ONE session_failed; a retryable
  error is a `warning`, not terminal). (E) `interactive_approvals = False`
  is a real, registry-surfaced capability (probes() reports it), not a
  UI-only assumption — resolve_approval records an audit-only,
  `effective: False` event. (F) repo resolution reuses
  `repo_registry.resolve_repo_local_path` (extracted, canonical — one place
  for path/env-ref policy), eliminating a duplicated resolver. (G) zero new
  mypy failures: `types-PyYAML` added to dev deps (fixes the yaml-stub gap
  repo-wide as a bonus) AND codex_agent.py's own repo resolution no longer
  imports yaml directly. (H) `shutdown()` on the harness + a worker
  `lifespan` handler interrupt active turns and close the SDK client on
  worker stop, so no orphan `codex_bin` app-server process is left behind —
  walks EVERY per-session cached harness instance (service caches one per
  session, not one per type).
- TESTS 07-11: `tests/test_codex_agent_adapter.py` (38, all against a FAKE
  SDK installed into sys.modules — no real package/network/account): SDK-
  absent & auth-failure unavailability, analysis-only/read-only rejection,
  thread-id persistence + follow-up reuse, resume-after-restart via
  thread_resume, interrupt reaching the active handle, unknown native events
  → visible warning (never inferred from prose), usage attribution, no-secret
  probe output, non-causal approval recording, close→archive, canonical
  repo resolver reuse, the full `_resolve_model` matrix (explicit/preferred/
  SDK-default/fallback-disallowed/no-models), delta coalescing + terminal
  dedup + retryable-error distinction, interactive_approvals capability, and
  shutdown cleanup (incl. close() raising / no client ever built). Plus
  `test_agent_preflight.py` (codex-only truthful overall), worker shutdown
  tests, and the pre-existing registry/service/worker suites updated for
  codex_agent now being a REAL adapter (their "unbuilt placeholder"
  assertions moved to claude_agent, which genuinely still is one). Full repo
  suite green; ruff clean; mypy clean across all 14 touched agent-session +
  preflight files.
- LIVE COCKPIT ACCEPTANCE 07-12 (Codex enablement gate — the real "is it
  usable in the interface" proof, done through the ISOLATED deployment-proof
  project, never production): `scripts/run_agent_deployment_proof.ps1`
  brought up `cc-agent-runtime-proof-{ledger,agent-kanban-ui}` on ports
  8092/8788 with a dedicated `cc-agent-runtime-proof_ledger_data` volume
  (post-create check confirmed no `llm_station-*` container touched; the
  production stack + `llm_station_ledger_data` stayed up 13h untouched
  throughout, verified before AND after). Host worker started against the
  proof ledger; the deployed cockpit CONTAINER reached it via
  `host.docker.internal:8791` and reported `codex_agent available: true`
  (authenticated as the real account, `interactive_approvals: false`). A
  real read-only Codex session driven entirely through the cockpit's HTTP
  proxy (browser-equivalent: cockpit → worker → SDK → real `codex login`)
  passed 14/14: create→idle with a real external thread id, a real streamed
  response (Codex ran 5 real read-only shell commands, all surfaced as
  structured `command_started`/`command_finished` events), NO duplicate
  assistant_message for an already-streamed item (Fix C proven LIVE),
  model+selection-reason recorded, session recovery (GET + list by
  conversation_id), follow-up reusing the SAME external thread, interrupt,
  close, and ZERO repo mutation (git HEAD/branch/status byte-identical
  before+after). Fresh `cc agent-preflight --harness codex --live --repo
  llm_station` also reports `overall: PASS` now (Fix A complete). Acceptance
  driver was a throwaway script — durable coverage is the 38 unit tests.
  A real robustness bug surfaced and was fixed during this proof: Docker's
  `./.env` bind-mount creates an empty `.env` DIRECTORY in a checkout with no
  real .env, which crashed the worker script's dotenv loader (fixed with
  `Test-Path -PathType Leaf`).
- STILL OUT OF SCOPE (explicit): Claude read-only adapter, writable/worktree
  mode, mission executor routing, cross-agent review, OpenRouter agent
  provider profiles — all gated behind the Codex read-only slice merging
  first.

## Frontier-router chat lane — untrusted tool_calls dispatch
- BUG 07-11: real incident, live transcript (job_application:job_5bfc9d483a1d). deepseek-v4-pro
  (frontier lane, no `tools` ever sent — verified in frontier_client.py body) returned a
  structured tool_calls entry for project_status(project_name=...) anyway; GatewayCore's
  `calls = msg.get("tool_calls") or []` trusted it unconditionally and dispatched a REAL local
  function call (TypeError, since the guessed kwarg was wrong). Round 2 then hallucinated 4 more
  "successful" tool calls in plain text that never ran — a second, distinct honesty bug.
- ROOT CAUSE: (1) build_system() sends the full verb catalogue in prose to every surface,
  frontier included, priming a model with no tools schema to try calling things; (2)
  GatewayCore._completion never checked is_frontier before trusting msg["tool_calls"] — the
  "zero tools" guarantee was enforced on the request, never on the response.
- FIX 07-11: `core.py` — build_system(surface, tools_available=bool) now sends a short,
  tools-free prompt when False (frontier only); GatewayCore.__init__ wires
  tools_available=not self.is_frontier. New `_frontier_tool_call_diagnostic()` hard-blocks
  dispatch in `_completion`'s frontier branch — any tool_calls in a frontier response gets
  neutralized + replaced with an operator-facing "gateway safety stop" message (same pattern as
  the existing qwen3-coder `_leak_diagnostic`), never silently dispatched, never silently dropped.
- TESTS 07-11: tests/test_gateway_frontier.py +2 — frontier system prompt carries no tool
  vocabulary (regression), a reconstructed leaked tool_calls response is never dispatched and
  produces the safety-stop message. Full non-job-search suite green.
- OPEN: the round-1/round-2 inconsistency (same prose pattern, only round 1 got auto-parsed into
  tool_calls) suggests OpenRouter routes deepseek-v4-pro to different backing infra per call —
  non-deterministic, can't be relied on to "not happen." Not yet verified whether sending
  `tool_choice: "none"` would suppress it provider-side (would need a live paid smoke-test);
  the harness-side block above does not depend on that working.

## Kanban emission = default sync path
- WHY 06-20: live-sync engine merged (#19) but emission was opt-in (KANBAN_EMIT_EVENTS=1).
  North-star wants it as the STANDARD path for every governed kanban write.
- ADD 06-20: GatewayCore._wire_kanban_events now ON BY DEFAULT. States: default=active once a
  board resolves (sole board or KANBAN_PRIMARY_BOARD_ID); multi-board-no-primary=inactive+reason
  (no guess/crash); =0 opt-out; =1 w/o board = loud raise. kanban_emission_status() helper.
- SURFACE 06-20: cc setup reports emission ACTIVE/inactive + board + reason + what to set.
  Forbidden taxonomy aligned (kanban.merge_by_agent/deploy_by_agent). Tests:
  test_kanban_emission_default.py (6).
- RECONCILE 06-20: rest of the north star already merged (#16 memory, #17 daily DAG, #18 demo+docs,
  #19 live-sync engine, #20 wrappers, #21-23 betts). This closed the one gap.

## Generic bounded-loop prover
- WHY 06-20: pr-check-verify is llm_station-specific (replays the fastapi [dev]-extra fix
  against llm_station's pyproject). Can't prove an arbitrary repo's loop (blocked on betts:
  "pyproject dev extra does not contain pytest marker").
- ADD 06-20: cc repo-loop-proof (cli/repo_loop_proof.py) — repo-agnostic. App opens a feature
  branch + trivial CI-safe marker file -> draft PR -> repo's OWN required checks run -> verify
  they succeed AND App did NOT merge -> close PR + delete branch -> redacted evidence. 4 tests.
  repo-verify loop gate posture-aware (external = live PR loop; branch-mission self-only).
- BETTS 06-20: prover worked end-to-end (PR #7 opened, polled, no-merge verified, cleaned up) but
  BLOCKED — betts Unit Tests is RED on main (pre-existing; Bayesian/GBDT/Schemathesis/Autoswagger
  pass). Prover correctly refuses to certify a red required check (no fake). To enable betts:
  fix betts Unit Tests green. betts#6 (CODEOWNERS) also still pending.

## Merge-wall postures (local pre-push guard)
- WHY 06-20: GitHub blocks branch protection/rulesets on PRIVATE repos on a FREE plan
  (betts 403 "Upgrade to Pro or make public"; llm_station works because it's PUBLIC). So
  private+free repos can't have a server-side merge wall.
- ADD 06-20: RepoManifest.merge_wall (github_branch_protection | local_pre_push_and_human_merge).
  cli/merge_guard.py: cc repo-merge-guard install|verify writes/verifies a real pre-push hook that
  rejects pushes to protected branches (tested: main push exit 1, feature exit 0). repo-verify gate
  renamed branch_protection_verified -> merge_wall_verified, posture-aware.
- POSTURE 06-20: local_pre_push_and_human_merge = local belt + agent PR-only (structural) + human
  merge. LOWER ASSURANCE (no server backstop) — recorded as such, NEVER faked as branch protection.
- BETTS 06-20: merge_wall=local_pre_push_and_human_merge + auth_mode github_app (App verified);
  guard installed on the local betts checkout; merge_wall_verified PASSES. Tests:
  test_merge_guard.py (4) + repo-registry posture test.
- NEXT: CODEOWNERS (betts#6 merge + git pull) + bounded-loop proof (adapt branch-mission for
  external repos: target-repo file/worktree resolution + betts's real local ci_commands) -> run ->
  cc repo-enable-autonomy --apply.

## Enabling betts_basketball (gates)
- APP 06-20: user added betts to the existing llm-station-command-center App install; VERIFIED
  via read-back (betts-scoped App token reads betts 200). selected_repositories += betts (true,
  not faked) -> github_app_installed gate PASSES.
- CHECKS 06-20: RepoManifest.required_status_check_contexts + pr_check_verify.required_checks_for()
  -> per-repo CI checks (betts uses "Unit Tests"; self falls back to global validate/lint-test). Test added.
- CODEOWNERS 06-20: opened betts_basketball#6 (App, feature branch + PR; direct main push correctly
  blocked by guardrail). Human merges + git -C betts pull -> codeowners gate flips (reads local checkout).
- BLOCKED 06-20: branch protection — GITHUB_OWNER_ADMIN_TOKEN (fine-grained PAT) 403s on betts
  Administration (llm_station 404=has-admin vs betts 403=lacks-it). User grants Administration on
  betts to the token, or sets protection in UI. branch_protection_verification NOT updated (honest).
- NEXT: adapt branch-mission for external repos (target-repo file/worktree resolution + auth_mode),
  then run branch-mission + pr-check-verify on betts -> loop evidence under RUN_ID/betts_basketball/;
  set protection; flip attestation; cc repo-enable-autonomy --apply. AppFlowy board needs APPFLOWY_* creds.

## Multi-repo onboarding (second repo: betts_basketball)
- ADD 06-20: betts_basketball onboarded DISABLED (autonomy.yaml; auth_mode github_app_pending;
  local_path_ref env:BETTS_BASKETBALL_LOCAL_PATH; blocker repo_autonomy_not_yet_verified).
- BOARDS 06-20: two boards registered (kanban-verify PASS) — betts_basketball (command_center_ui,
  validated live-working: event->fold->UI projection, wall holds) + betts_basketball_appflowy
  (appflowy, env refs; write-through fail-closed degraded w/o creds — NOT faked).
- BUGFIX 06-20: repo-verify gates were control-repo-scoped — devcontainer/codeowners resolved
  against the control repo + loop evidence read control repo's, so external repos falsely
  inherited llm_station's files/proof. Now target-repo-aware (local_path resolution) + per-repo
  evidence under RUN_ID/<repo_id>/. self unchanged. betts now honest: 5 real blockers.
- FIX 06-20: cc onboard repo loaded env={} for verify (under-reported gates) -> loads merged .env.
- EVIDENCE 06-20: betts-onboarding.json (redacted, no abs path). Test: test_repo_registry
  test_external_repo_gates_check_target_not_control_repo.
- NEXT (to enable betts): CODEOWNERS + App repo-selection + branch protection + per-repo loop proof.
  AppFlowy board live needs APPFLOWY_* + BETTS_APPFLOWY_BOARD_REF.

## Operator command wrappers (keep it simple)
- ADD 06-20: cc setup (cli/setup.py) = real doctor (exit code returned, never masked)
  + registry summary + live-sync activation env + next steps. cc onboard repo|kanban
  (cli/onboard.py) = friendly sugar over repo-register/kanban-register (dry-run) +
  *-verify; infers repo-id/remote/board; writes nothing without --apply; appflowy
  demands env: refs; local path stored as env: ref.
- FRIENDLY SET 06-20: doctor/setup/onboard/operate/improve/demo. Lower-level evidence
  commands all kept. Docs: docs/operations/OPERATOR_COMMANDS.md. Tests: test_operator_wrappers.py (7).
- FIX 06-20: setup output is ASCII (Windows cp1252 console can't encode box-drawing).
- NEXT: onboard a 2nd real local repo in disabled mode (needs a real repo path).

## Live kanban sync / projection engine
- ADD 06-20: command_center.kanban_sync (events/projection/wiring) — KanbanEvent
  schema + append-only event log (generated/kanban-events.jsonl, gitignored) +
  emit_event = the ONLY legal writer. Source of truth; surfaces are projections.
- WALL 06-20: wall on the ACTION (approve_card/merge/deploy/delete_* raise
  GovernanceViolation) AND the STATUS VALUE (emit_event + KanbanEvent validator +
  write_through all reject a human-owned approval status, case/space/underscore-folded).
- PROJECT 06-20: project_cards folds events->state; verify_projection (PASS/BLOCKED/
  DEGRADED); reconcile = drift (repairable) vs conflict (review_required) for human
  approval (case-folded incl. lowercase 'approved'), terminal re-open, card-not-in-log.
  --apply repairs drift to the FOLD target only; write_through fails closed w/o env.
- WIRE 06-20: GatewayCore funnels every governed card/todo verb (Discord/SMS/UI via
  wrap_governed_dispatch) through emit_event. Opt-in: KANBAN_EMIT_EVENTS=1 +
  KANBAN_PRIMARY_BOARD_ID (fails loud if unresolvable). UI /api/action covered (surface app).
- UI 06-20: GET /api/events/kanban (SSE, id:/Last-Event-ID resume, no replay) +
  /api/events/kanban/snapshot. stage_card on any surface -> UI without refresh (Level 1).
- CLI 06-20: cc kanban-emit/kanban-project/kanban-verify-projection/kanban-reconcile +
  high-level cc operate verify --all. Lower-level commands kept.
- REVIEW 06-20: 6-dimension adversarial workflow (36 agents) -> 2 critical wall holes
  (lowercase 'approved' unprotected; status_after bypass) + integration-island gap all
  FIXED before commit. Tests: test_kanban_sync (19) + test_kanban_wiring (4) +
  test_kanban_ui_events (4). Docs: docs/kanban/LIVE_KANBAN_SYNC.md + MASTER §14.
- NEXT: persistent push (WebSocket) if poll-stream insufficient; AppFlowy read-back
  needs sandbox creds (degraded w/o); Phase 6 desktop (gated on APPFLOWY_SANDBOX_*).

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
  in docs/architecture/channels.md, mirrors kanban-bridge/snapshot) — agents don't self-install
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
- DONE (Phase 8/9): see Demo + docs topic below.

## Full-loop demo + docs — Phase 8/9

- ADD 06-20: `cc demo full-loop --repo --board` (cli/demo.py) — verifies board+repo (read-only)
  and documents the 14-step loop with VERIFY/AUTOMATABLE/HUMAN_GATE markers. No writes; merge is
  NEVER automated (steps 5/9/10/14 are human gates). tests/test_demo.py (3).
- DOCS 06-20: GETTING_STARTED, INSTALL_WINDOWS, INSTALL_WSL, ADDING_A_REPO, ADDING_A_KANBAN,
  RUNNING_DAILY_SELF_IMPROVEMENT, SECURITY_MODEL, OPERATIONS_RUNBOOK, TROUBLESHOOTING + MASTER §14.
  Known gotchas documented (no workflows:write; workflow PRs need human creds; dev/gateway extras;
  most-recent-push approval rule; retrieval-equivalence file-write flake).
- STATE 06-20: Phases 2–5 + 8/9 done. Remaining: Phase 6 (live desktop) — correctly blocked until
  APPFLOWY_SANDBOX_* is wired so action-latency evidence is measured, not fabricated.
