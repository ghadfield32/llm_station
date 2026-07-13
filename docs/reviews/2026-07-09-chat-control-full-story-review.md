# Chat control + full-story review: decision (2026-07-09)

Evaluated: first-party flight recorder vs LiteLLM built-ins vs observability
layers (Langfuse/Phoenix/Helicone/Lunary) vs prebuilt chat UIs (Open WebUI /
LibreChat), through three judge lenses (governance/security,
operator-experience, engineering-cost). Method: 4 research dossiers -> 3
independent judges -> synthesis. Companion to
[2026-07-08-cockpit-decision.md](2026-07-08-cockpit-decision.md).

## 1. Decision

We compose rather than switch. **Primary (control + authoritative full
story):** the first-party stack — GatewayCore governed action verbs + the
cockpit (`agent_kanban_ui`) for control, and the TurnRecorder flight recorder
(`generated/chat-transcripts/*.jsonl`: full tool args/results, injected
context provenance, per-completion token usage, final answers, both turn
loops) read through `GET /api/chat/threads/{id}/transcript` and the cockpit
Chat "full story" timeline, over the existing loopback + Tailscale PWA.
**Cross-surface audit net (adopted now, config-only):** LiteLLM's built-in
`general_settings.store_prompts_in_spend_logs: true`, with GatewayCore passing
`litellm_session_id = surface:conversation_id` so spend logs, transcripts, and
`agent_calls.jsonl` all join on one key; this captures every surface
(app/Discord/Slack/SMS/Telegram/WhatsApp) server-side at the single proxy
choke point and independently cross-checks the fail-open recorder.
**Optional / watch-list:** a dedicated observability layer only if
cross-conversation search/eval/session analytics outgrow the first two —
single-container Arize Phoenix preferred over 6-container Langfuse v3 on this
RAM-constrained single Windows box. **Rejected:** prebuilt chat UIs
(Open WebUI / LibreChat) as either control or review surface — they are blind
to non-app surfaces, lossy exactly where the flight recorder matters, and ship
approval-less agent/tool/MCP layers that constitute the forbidden second
control plane.

## 2. Options considered

| Option | Role it could play | Verdict | Why (one line) |
|---|---|---|---|
| First-party: TurnRecorder + GatewayCore + cockpit timeline | Control surface + authoritative full-story record | **Adopt (primary)** — judges 56–59/70 | Only option capturing untruncated tool args/results + context provenance at the seam where they exist; it *is* the governed control plane; near-zero marginal cost. |
| LiteLLM `store_prompts_in_spend_logs` + Admin UI Logs | Cross-surface LLM-traffic audit net + token/latency analytics | **Adopt (net)** — judges 52–53/70 | One YAML line at the choke point every surface already transits; server-side, zero client changes; not sufficient alone (wire-level only, silent truncation, version-bug history). |
| Observability layer: Phoenix first, Langfuse v3 later, via LiteLLM callback | Drill-down/analytics lens on LLM calls | **Defer (optional)** — judges 47–48/70 | Best detail depth, but Langfuse v3 needs 6 containers incl. ClickHouse contending with Ollama RAM; still blind to app-side tool execution and Ledger events; Phoenix (1 container) is the entry point if the need materializes. |
| Prebuilt chat UI: Open WebUI / LibreChat on LiteLLM | Chat client / review UI | **Reject** — judges 25–28/70 | Database-of-record UIs that cannot see Discord/Slack/SMS turns, flatten mirrored chats to role/content text (no slot for tool calls/context), and ship an approval-less second execute plane (in-process Python tools, MCP, agents, code interpreter) by default. |

ORCA / OmniAgent / OxyGent were out of scope by prior decision: they stay
optional handoff links only (see `/api/chat/runtime`); GatewayCore + LiteLLM
stays the runtime.

## 3. Key facts that drove the decision

- TurnRecorder writes one JSONL line per turn with FULL tool args, FULL tool
  results, context-block provenance, rounds, per-completion `usage`, and final
  answer, fail-open with a visible write-failure counter, on **both** turn
  loops (streaming cockpit SSE and non-streaming Discord/Slack/etc.) —
  `src/command_center/channels/transcript.py`,
  `src/command_center/channels/core.py`.
- The untruncated, paginated read endpoint
  `GET /api/chat/threads/{conversation_id}/transcript` sits behind the same
  `_require_chat` gate as all chat endpoints; compose wires
  `GATEWAY_TRANSCRIPT_DIR=/snapshot/chat-transcripts` +
  `GATEWAY_TRANSCRIPTS=1` on the gitignored `./generated` host mount.
- The `conversation_id` contextvar joins into `agent_calls.jsonl`
  (`growthos/observability.py`), giving thread <-> tool-call joinability.
- LiteLLM does not store request/response content by default; enabling is
  config-only via `general_settings.store_prompts_in_spend_logs: true`
  (https://docs.litellm.ai/docs/proxy/ui_logs — key present and un-deprecated
  in mid-2026 docs). Spend logging is automatic/server-side for every proxied
  request once a DB is configured (https://docs.litellm.ai/docs/proxy/cost_tracking);
  session grouping requires the caller to pass `litellm_session_id`
  (https://docs.litellm.ai/docs/proxy/ui_logs_sessions).
- **Known breakage history for this exact feature**: v1.77.2 stored empty
  `{}` columns (litellm#15641); v1.82.1 UI showed "Request/Response Data Not
  Available" (litellm#23636). Behavior on **our pinned digest must be
  smoke-tested** — one plain turn + one tool-call turn, checked in the Admin
  UI Logs page and `SELECT messages, response FROM "LiteLLM_SpendLogs"`.
- Large prompts/responses are truncated before DB insert (threshold tunable
  via `MAX_STRING_LENGTH_PROMPT_IN_DB`, litellm#14042). TurnRecorder therefore
  remains the only lossless record.
- Spend-log auto-retention (`maximum_spend_logs_retention_period`) is
  enterprise-marked (https://docs.litellm.ai/docs/proxy/spend_logs_deletion),
  so render.py deliberately omits it; prune manually:
  `DELETE FROM "LiteLLM_SpendLogs" WHERE "startTime" < now() - interval '30 days';`
- Langfuse v3 self-host mandates six services (web, worker, Postgres,
  ClickHouse, Redis, MinIO; ~4-core/16 GiB guidance). Arize Phoenix runs as a
  single container with a native LiteLLM `arize_phoenix` callback.
- Any LiteLLM-side observer sees only LLM round-trips — GatewayCore tool
  execution results, context assembly, and Ledger events never cross that
  wire, so no proxy-side option can be "the full story" on its own.
- Open WebUI ships in-process Python Tools/Functions and native MCP (its own
  docs flag arbitrary host command execution over stdio); LibreChat bundles
  Agents + MCP + OpenAPI Actions + Code Interpreter and has no admin
  chat-review UI. Open WebUI relicensed at v0.6.6 (branding clause + CLA).

## 4. Implemented now vs later

**Landed on this branch (2026-07-09):**
1. Flight recorder module + hooks in both GatewayCore loops (fail-open, with
   write-failure counter), `usage` capture per completion, repo-root-anchored
   default transcript dir (a cwd-relative default would have written
   conversation content to an un-gitignored path after `load_tool_layer`'s
   `os.chdir`).
2. Transcript read endpoint with newest-first pagination + storage flag on
   `/api/chat/threads` + cockpit Chat "full story" timeline (desktop + phone).
3. `litellm_session_id = surface:conversation_id` on every proxy call, set
   from the same contextvar the recorder owns — one join key everywhere.
4. `store_prompts_in_spend_logs: true` grafted into the rendered LiteLLM
   config (render.py), UTF-8-safe render, retention documented as manual.
5. Tests: fidelity (untruncated args/results), durability (append per turn),
   fail-open (+counter), kill switch (GATEWAY_TRANSCRIPTS=0), join key
   (during turn / reset after), session-id pass-through, endpoint wall
   (503 when chat disabled), sanitized conversation-id file paths.

**Still pending (hard gate before trusting the net):** smoke-test
store-prompts on the pinned digest (known version bugs above) after the next
`docker compose up -d` — verify a tool-call turn appears with content in the
Admin UI Logs page.

**Later / optional (explicit switch path):** if cross-conversation search,
evals, or analytics become a felt need, add **Arize Phoenix first** — one
pinned container, `litellm_settings.callbacks: ["arize_phoenix"]` +
`PHOENIX_COLLECTOR_ENDPOINT`, reversible by deleting the callback line.
Escalate to Langfuse v3 only if Phoenix proves insufficient AND it can run on
separate hardware; tracing-only policy (prompt management/playground stay
off). Because the join key and callback wiring are shared, spend-logs-only ->
Phoenix -> Langfuse is additive config, never a migration.

**Never (for this mission):** Open WebUI / LibreChat as control or review
surfaces.

## 5. Security boundaries preserved

- **No second control plane.** Control stays exclusively in GatewayCore's
  governed `ACTION_VERBS` dispatch behind the human-only Approved wall.
  Everything adopted here is read-only observability: the transcript endpoint
  sits behind `_require_chat`; LiteLLM spend logs are passive, post-response,
  and cannot invoke, approve, merge, deploy, or publish.
- **No second gateway.** LiteLLM (pinned by digest) remains the only model
  path; observability attaches at that choke point.
- **Transcripts stay private.** Full-fidelity content lives only in
  `generated/chat-transcripts/` (gitignored) and the LiteLLM Postgres volume —
  loopback + Tailscale only. Keep the litellm-db volume out of any
  unencrypted off-machine backup; it is now the richest plaintext store.
  Open item: per-thread delete/rotation (kill switch is all-or-nothing).
- **No new API keys, no new exposure.** Every adopted piece uses existing
  local credentials; nothing binds beyond loopback; Tailscale Serve only,
  never Funnel. LiteLLM Admin UI stays operator-only (its UI toggles can
  override YAML config-as-code).
- **Everything reviewable, everything reversible.** Plain JSONL/JSON/SQL on
  owned infrastructure, joined by one key; every component detaches via a
  single flag, env var, or callback line.
