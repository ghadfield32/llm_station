// Typed client for the read-only backend. Errors are surfaced to the UI, never
// swallowed into an empty board (the backend returns 502 when the Ledger is down).

export interface MissionCard {
  id: string;
  action: string;
  repo: string;
  risk: string;
  status: string;
  created_at: string;
}
export interface Column {
  name: string;
  cards: MissionCard[];
}
export interface BoardData {
  columns: Column[];
  total: number;
}
export interface ToolStat {
  tool: string;
  calls: number;
  errors: number;
  error_rate: number;
  p50_ms: number;
}
export interface Metrics {
  log_file: string;
  total_calls: number;
  by_surface: Record<string, number>;
  error_rate: number;
  redundant_rate: number;
  board_mutations: number;
  intent_verb_calls: number;
  generic_mutator_calls: number;
  intent_verb_share: number | null;
  per_tool: ToolStat[];
}

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(body.detail ?? `request failed (${r.status})`);
  }
  return r.json() as Promise<T>;
}

// AppFlowy board snapshot (produced on the worker, read-only here).
export interface BoardCard {
  title: string;
  meta: string;
  fields?: Record<string, string | number>;
}
export interface BoardColumn { name: string; cards: BoardCard[]; }
export interface AppFlowyBoard {
  board: string;
  statuses?: string[];          // full legal columns — the "Move to…" targets
  columns?: BoardColumn[];
  error?: string;
}
export interface BoardSnapshot {
  generated_at: string;
  live?: boolean;               // true when read live from AppFlowy (console)
  boards: AppFlowyBoard[];
}

export interface ActivityCall {
  ts: string; surface: string; tool: string;
  ok: boolean; ms: number; detail: string;
}
export interface Activity { calls: ActivityCall[]; }

// Mission detail (Ledger passthrough) — shape is loose; we read events/approvals.
export interface MissionEvent { kind: string; payload?: unknown; ts?: string; }
export interface MissionDetail {
  mission?: Record<string, unknown>;
  events?: MissionEvent[];
  approvals?: Record<string, unknown>[];
  [k: string]: unknown;
}

export const fetchMissions = () => getJSON<BoardData>("/api/missions");
export const fetchMetrics = () => getJSON<Metrics>("/api/metrics");
export const fetchBoards = () => getJSON<BoardSnapshot>("/api/boards");
export const fetchBoardsLive = () => getJSON<BoardSnapshot>("/api/boards/live");
export const fetchActivity = () => getJSON<Activity>("/api/activity");
export const fetchMission = (id: string) =>
  getJSON<MissionDetail>(`/api/mission/${encodeURIComponent(id)}`);

// Router / model lanes (read-only, from models.yaml / judges.yaml).
export interface ModelCandidate {
  alias: string; model: string; priority: number; canary_weight: number;
}
export interface ModelRole { role: string; candidates: ModelCandidate[]; }
export interface Executor { name: string; family: string; priority: number; }
export interface JudgeStage { stage: string; judges: string[]; }
export interface ModelLanes {
  roles: ModelRole[];
  executors: Executor[];
  judge_stages: JudgeStage[];
}
export const fetchModels = () => getJSON<ModelLanes>("/api/models");

// Console capability + chat (the UI as a channel).
export interface UIConfig {
  ledger_ui: string;
  chat_enabled: boolean;
  model_roles: string[];
}
export const fetchConfig = () => getJSON<UIConfig>("/api/config");

export interface Status { hops: Record<string, string>; targets?: Record<string, string>; }
export const fetchStatus = () => getJSON<Status>("/api/status");

export interface RuntimeProbe {
  ok: boolean;
  url?: string;
  status_code?: number;
  error_type?: string;
  error?: string;
}
export interface RuntimeDns {
  ok: boolean;
  host: string;
  addresses?: string[];
  error?: string;
}
export interface RuntimePath {
  path: string;
  exists: boolean;
  is_file: boolean;
  is_dir: boolean;
}
export interface RuntimeDebug {
  mode: { chat_enabled: boolean; cwd: string };
  ledger: {
    base_url: string;
    health_url: string;
    dns: RuntimeDns;
    health: RuntimeProbe;
    host_run_hint: string;
  };
  paths: Record<string, RuntimePath>;
}
export const fetchRuntimeDebug = () => getJSON<RuntimeDebug>("/api/debug/runtime");

// Typed domain surfaces (config-driven card grammars — /api/domains et al).
// `kind` is omitted in the config for plain text fields, so it is optional here
// and every renderer defaults it to "text".
export type FieldKind =
  | "text" | "badge" | "score" | "money" | "url"
  | "datetime" | "markdown" | "list" | "progress";
export interface FieldSpec { name: string; label: string; kind?: FieldKind; }
export interface EmptyState { title?: string; hint?: string; command?: string; }
export interface DomainSpec {
  domain_id: string;
  title: string;
  card_component: string;   // job_application | linkedin_post | … — open so a
  source: string;           // new config entry falls back to the generic card
  board_id?: string;
  columns?: string[];
  column_actions?: Record<string, string>;
  summary_fields: FieldSpec[];
  drawer_fields: FieldSpec[];
  allowed_actions: string[];
  empty_state: EmptyState;
}
// Cards are plain objects whose keys match the spec's field names; values are
// whatever the source stored (string/number/list/null) — coerce, never assume.
export interface DomainCard {
  card_id?: string | number | null;
  status?: string | null;
  [k: string]: unknown;
}
export type DomainOrigin = "fixtures" | "board_store" | "ledger";
export interface DomainCards {
  domain_id: string;
  origin: DomainOrigin;
  board_id?: string;
  columns?: string[];
  // one-step machine: legal next lanes per current lane (board_store domains)
  transitions?: Record<string, string[]>;
  cards: DomainCard[];
  empty_state: EmptyState;
  generated_at?: string;
  note?: string;
}
export interface DomainCardDetail {
  domain_id: string; card: DomainCard; drawer_fields: FieldSpec[];
}
export interface DomainActions {
  domain_id: string; allowed_actions: string[]; dispatch_enabled: boolean;
  write_ready?: boolean; write_blockers?: string[];
}
export interface DomainMoveResult {
  status: string;
  domain_id: string;
  card_id: string;
  from_status?: string | null;
  to_status?: string;
  card?: DomainCard;
  event?: Record<string, unknown>;
  side_effect?: Record<string, unknown> | null;
}
export interface DomainProgressStep {
  id: string;
  label: string;
  state: "done" | "current" | "waiting" | string;
  detail?: string;
}
export interface DomainProgressEvent {
  event_id: string;
  created_at: string;
  headline: string;
  action?: string;
  status_before?: string | null;
  status_after?: string | null;
  actor_type?: string;
  source_surface?: string;
}
export interface DomainCardProgress {
  domain_id: string;
  card_id: string;
  status?: string | null;
  steps: DomainProgressStep[];
  events: DomainProgressEvent[];
  application: Record<string, unknown>;
  chat_prompt: string;
}
export const fetchDomains = () =>
  getJSON<{ domains: DomainSpec[] }>("/api/domains");
export interface DomainSchema {
  schema_version: string;
  config_path: string;
  config_writable: boolean;
  writable: boolean;
  write_gate: string;
  domains: DomainSpec[];
}
export const fetchDomainSchema = () => getJSON<DomainSchema>("/api/domain-schema");
export const createDomainSchema = (domain: DomainSpec) =>
  postJSON<DomainSchema>("/api/domain-schema", domain, "POST");
export const updateDomainSchema = (domainId: string, domain: DomainSpec) =>
  postJSON<DomainSchema>(`/api/domain-schema/${encodeURIComponent(domainId)}`, domain, "PUT");
export const deleteDomainSchema = (domainId: string) =>
  postJSON<DomainSchema>(`/api/domain-schema/${encodeURIComponent(domainId)}`, {}, "DELETE");
export const fetchDomainCards = (id: string) =>
  getJSON<DomainCards>(`/api/domain/${encodeURIComponent(id)}/cards`);
export const fetchDomainCard = (id: string, cardId: string) =>
  getJSON<DomainCardDetail>(
    `/api/domain/${encodeURIComponent(id)}/card/${encodeURIComponent(cardId)}`);
export const fetchDomainCardProgress = (id: string, cardId: string) =>
  getJSON<DomainCardProgress>(
    `/api/domain/${encodeURIComponent(id)}/card/${encodeURIComponent(cardId)}/progress`);
export const fetchDomainActions = (id: string) =>
  getJSON<DomainActions>(`/api/domain/${encodeURIComponent(id)}/actions`);
export const moveDomainCard = (id: string, cardId: string, status: string) =>
  postJSON<DomainMoveResult>(`/api/domain/${encodeURIComponent(id)}/move`, {
    card_id: cardId, status,
  });
export interface DomainNoteResult {
  status: string;
  domain_id: string;
  card_id: string;
  application_id: string;
  note: Record<string, unknown>;
  event?: Record<string, unknown> | null;
  card: DomainCard;
  progress: DomainCardProgress;
}
export const addDomainCardNote = (
  id: string, cardId: string, type: string, text: string, source = "cockpit",
) =>
  postJSON<DomainNoteResult>(
    `/api/domain/${encodeURIComponent(id)}/card/${encodeURIComponent(cardId)}/note`,
    { type, text, source },
  );

// Application packet review loop (job_application cards): view the generated
// materials + agent trace, request changes (regenerates via the agent writer),
// and approve & submit (validation-gated governed Completed move + email record).
export interface PacketCheck {
  id: string; label: string; ok: boolean; level: string; detail: string;
}
export interface PacketValidation {
  ok: boolean; errors: string[]; warnings: string[]; checks: PacketCheck[];
}
export interface AgentTraceMessage { role: string; content: string; }
export interface AgentTraceEntry {
  ts: string; step: string; attempt: number; model: string;
  base_url?: string;
  messages?: AgentTraceMessage[];
  response?: string;
  ok?: boolean; error?: string;
  duration_ms?: number;
  claim_ids?: string[];
  problems?: string[];
  usage?: Record<string, unknown> | null;
}
export interface EmailConfigStatus {
  configured: boolean; missing: string[]; to?: string | null;
}
export interface JobStoryEntry {
  ts: string;
  kind: "board" | "note" | "agent" | "submission" | string;
  title: string;
  summary: string;
  detail?: string | null;
}
export interface JobPacket {
  domain_id: string;
  card_id: string;
  application_id: string;
  path: string;
  record: Record<string, unknown>;
  files: Record<string, string | null>;
  agent_trace: AgentTraceEntry[];
  story: JobStoryEntry[];
  validation: PacketValidation;
  email: EmailConfigStatus;
  submission_record?: Record<string, unknown> | null;
}
export const fetchJobPacket = (id: string, cardId: string) =>
  getJSON<JobPacket>(
    `/api/domain/${encodeURIComponent(id)}/card/${encodeURIComponent(cardId)}/packet`);
export interface PacketChangesResult {
  status: string;
  regenerate_error?: string | null;
  domain_id: string; card_id: string; application_id: string;
  packet: JobPacket;
  progress: DomainCardProgress;
}
export const requestPacketChanges = (
  id: string, cardId: string, notes: string, regenerate = true,
) =>
  postJSON<PacketChangesResult>(
    `/api/domain/${encodeURIComponent(id)}/card/${encodeURIComponent(cardId)}/packet/request-changes`,
    { notes, regenerate });
export interface PacketFileResult {
  status: string; file: string;
  domain_id: string; card_id: string; application_id: string;
  packet: JobPacket;
  progress: DomainCardProgress;
}
export const updateJobPacketFile = (
  id: string, cardId: string, file: string, content: string,
) =>
  postJSON<PacketFileResult>(
    `/api/domain/${encodeURIComponent(id)}/card/${encodeURIComponent(cardId)}/packet/file`,
    { file, content }, "PUT");
export interface PacketSubmitResult {
  status: string;
  domain_id: string; card_id: string;
  from_status?: string | null; to_status?: string;
  event?: Record<string, unknown>;
  side_effect?: Record<string, unknown> | null;
  card?: DomainCard;
  progress?: DomainCardProgress;
}
export const submitJobApplication = (id: string, cardId: string) =>
  postJSON<PacketSubmitResult>(
    `/api/domain/${encodeURIComponent(id)}/card/${encodeURIComponent(cardId)}/packet/submit`,
    { confirm: true });

export interface JobProfileControls {
  writable: boolean;
  write_gate: string;
  application_questions: {
    default_policy: string;
    review_required: string[];
    draft_defaults: Record<string, string>;
    never_auto_answer: string[];
  };
  application_questions_source: string;
  source_paths: Record<string, string>;
  job_search: {
    enabled: boolean;
    timezone: string;
    daily_run_time: string;
    require_geoff_selection: boolean;
    submit_without_geoff_selection: boolean;
    auto_submit_enabled: boolean;
    max_suggested_jobs_per_day: number;
    max_bot_possible_suggestions_per_day: number;
    max_manual_required_suggestions_per_day: number;
    max_selected_jobs_per_day: number;
    board_name: string;
    data_root: string;
    digest_path: string;
  };
  ranking: Record<string, number>;
  job_search_config_source: string;
  job_search_settings_source: string;
  job_search_settings_writable: boolean;
  resume_variants: string[];
  job_categories: {
    id: string;
    resume_variant: string;
    keywords: string[];
    role_focus: string;
  }[];
  company_targets: Record<string, string[]>;
  executor_fallback: Record<string, string>;
  standing_answers: {
    answers: StandingAnswer[];
    source: string;
    coverage_note: string;
  };
  dag: {
    dag_id: string;
    schedule: string;
    daily_targets: {
      suggested: number;
      bot_possible: number;
      manual_required: number;
      selected: number;
    };
    targets_adjustable_via: string;
    digest_path: string;
    last_digest_at: string | null;
    note: string;
  };
}
export interface StandingAnswer {
  topic: string;
  question?: string;
  answer: string;
  answer_rule?: string;
  covers?: string[];
}
export const fetchJobProfileControls = () =>
  getJSON<JobProfileControls>("/api/job-search/profile-controls");
export const updateStandingAnswer = (body: {
  topic: string; answer: string; question?: string; covers?: string[];
}) =>
  postJSON<{
    status: string;
    topic: string;
    source: string;
    standing_answers: JobProfileControls["standing_answers"];
  }>("/api/job-search/profile-controls/standing-answer", body, "PUT");
export const removeJobSearchCategory = (categoryId: string) =>
  postJSON<{
    status: string;
    source: string;
    job_categories: JobProfileControls["job_categories"];
  }>(`/api/job-search/profile-controls/category/${encodeURIComponent(categoryId)}`,
     undefined, "DELETE");
export interface ReclassifyResult {
  status: string;
  cards_scanned: number;
  counts: Record<string, number>;
  changed: {
    card_id: string; application_id: string; company: string;
    role_title: string; before: string; after: string;
    auto_answered: string[];
  }[];
  errors: { card_id: string; application_id: string; error: string }[];
}
export const reclassifyJobApplications = () =>
  postJSON<ReclassifyResult>("/api/job-search/reclassify", {});
export interface BulkSelectResult {
  status: string;
  automation_class: string;
  target: string;
  moved_count: number;
  moved: { card_id: string; company: string; role_title: string }[];
}
export const bulkSelectSuggested = (
  automation_class = "bot_possible", target = "Selected by Geoff",
) =>
  postJSON<BulkSelectResult>("/api/job-search/bulk-select",
    { automation_class, target });
export const updateJobSearchRuntime = (body: Partial<JobProfileControls["job_search"]>) =>
  postJSON<{
    status: string;
    source: string;
    job_search: JobProfileControls["job_search"];
    ranking: JobProfileControls["ranking"];
    job_categories: JobProfileControls["job_categories"];
  }>("/api/job-search/profile-controls/runtime", body, "PUT");
export const updateJobSearchCategory = (
  categoryId: string,
  body: { role_focus?: string; keywords?: string[]; resume_variant?: string },
) =>
  postJSON<{
    status: string;
    source: string;
    job_search: JobProfileControls["job_search"];
    ranking: JobProfileControls["ranking"];
    job_categories: JobProfileControls["job_categories"];
  }>(`/api/job-search/profile-controls/category/${encodeURIComponent(categoryId)}`, body, "PUT");
export const updateDraftDefault = (key: string, value: string) =>
  postJSON<{
    status: string;
    key: string;
    source: string;
    application_questions: JobProfileControls["application_questions"];
  }>("/api/job-search/profile-controls/draft-default", { key, value }, "PUT");

export interface BoardRegistryBoard {
  board_id: string;
  provider: string;
  workspace_ref: string;
  board_ref: string;
  repo_ids: string[];
  status_mapping: Record<string, string>;
  required_fields: string[];
  allowed_agent_verbs: string[];
  forbidden_agent_verbs: string[];
  blockers: string[];
}
export interface BoardRegistry {
  schema_version: string;
  config_path: string;
  config_writable: boolean;
  boards: BoardRegistryBoard[];
}
export const fetchBoardRegistry = () => getJSON<BoardRegistry>("/api/board-registry");

export interface ChatRuntime {
  enabled: boolean;
  harness: string;
  transport_surface: string;
  model_gateway: string;
  chat_role: ModelRole | null;
  roles?: ModelRole[];
  executors: Executor[];
  executor_note?: string;
  frontier_models?: FrontierModelOption[];
  frontier_note?: string;
  local_frontier_models?: LocalFrontierModelOption[];
  local_frontier_note?: string;
  stream_endpoint: string;
  action_endpoint: string;
  activity_endpoint: string;
  conversations_endpoint?: string;
  repos?: { repo_id: string; remote_url: string }[];
  provider_note?: string;
  chat_memory_note?: string;
  external_chats?: {
    name: string; active: boolean; url: string | null;
    env_var?: string; reason?: string; kind?: string; best_for?: string;
  }[];
}
// The paid, opt-in escalation lane (GLM-5.2 / DeepSeek V4 Pro / Kimi K2.6 today) —
// read-only pricing/availability signal; `selectable` is false until an operator
// sets budgets.default.enabled=true AND the provider key.
// Real measured results from the last `make frontier-router-benchmark LIVE=1`
// run (frontier_benchmark.summarize) — absent until that has been run once.
export interface FrontierMeasuredResult {
  cases_scored: number;
  cases_blocked: number;
  pass_rate: number | null;
  median_latency_ms: number | null;
  measured_cost_usd: number;
  block_reasons: string[];
}
export interface FrontierModelOption {
  model_id: string;
  provider: string;
  estimated_cost_per_turn_usd: number | null;
  context_tokens: number | null;
  lane_enabled: boolean;
  key_present: boolean;
  selectable: boolean;
  measured?: FrontierMeasuredResult | null;
}
// The free, experimental, loopback-only lane (colibrì / GLM-5.2 744B today) — `selectable`
// is false until an operator enables configs/local-frontier-providers.yaml AND the server's
// /health probe returns ready. No cost field: there is no $ cost, only a wall-clock one.
export interface LocalFrontierThroughputEstimate {
  low: number;
  high: number;
  source: string;
}
export interface LocalFrontierCapabilities {
  text: boolean;
  streaming: boolean;
  tools: boolean;
  json_mode: boolean;
  vision: boolean;
  audio: boolean;
}
// Real measured results from the last `make colibri-benchmark LIVE=1` run
// (local_frontier_benchmark.summarize) — absent until that has been run once.
export interface LocalFrontierMeasuredResult {
  cases_scored: number;
  cases_blocked: number;
  pass_rate: number | null;
  median_tokens_per_second: number | null;
  block_reasons: string[];
}
export interface LocalFrontierModelOption {
  model_id: string;
  provider: string;
  lane_enabled: boolean;
  health: string;
  selectable: boolean;
  capabilities: LocalFrontierCapabilities;
  context_tokens: number | null;
  disk_footprint_gb: number | null;
  expected_tokens_per_second: LocalFrontierThroughputEstimate | null;
  kv_slots: number;
  max_queue: number;
  measured?: LocalFrontierMeasuredResult | null;
}
export const fetchChatRuntime = () => getJSON<ChatRuntime>("/api/chat/runtime");

// Deep-context counterpart to a domain card's chat_prompt, for the "registered
// repo" chat entry point: the manifest, a live read-only repo-verify pass, and
// recent Ledger missions against this repo, plus the assembled chat_prompt.
export interface RepoChatContext {
  repo_id: string;
  manifest: Record<string, unknown>;
  verify: { status?: string; blockers?: string[]; [k: string]: unknown };
  recent_missions: Record<string, unknown>[];
  chat_prompt: string;
}
export const fetchRepoChatContext = (repoId: string) =>
  getJSON<RepoChatContext>(`/api/chat/repo-context/${encodeURIComponent(repoId)}`);

// Register a new work repo (mirrors `cc repo-register`). apply=false only
// validates + previews the manifest block; apply=true commits it to
// configs/autonomy.yaml (requires KANBAN_UI_DOMAIN_CONFIG_WRITES=1). Either
// way the manifest starts autonomous_edits_enabled=false.
export interface RepoRegisterResult {
  status: "validated_dry_run" | "registered" | "blocked";
  repo_id?: string;
  blockers?: string[];
  next?: string;
  manifest_block?: string;
  local_path_env?: string;
  local_path_runtime_value?: string;
}
export const registerRepo = (body: {
  repo_id: string; local_path: string; remote_url: string;
  kanban_board: string; apply: boolean;
}) => postJSON<RepoRegisterResult>("/api/repos/register", body);

// The review index: every conversation the flight recorder has seen, across
// all surfaces, merged with the shared thread shortcuts.
export interface ChatConversation {
  conversation_id: string;
  turns: number;
  last_ts: string;
  surfaces: string[];
  last_user_text: string;
  title: string | null;
}
export interface ChatConversationsResponse {
  conversations: ChatConversation[];
  total: number;
}
export const fetchChatConversations = () =>
  getJSON<ChatConversationsResponse>("/api/chat/conversations");

// Clears ONE conversation's chat history (thread shortcut + transcript file).
// Card/board history lives in the governed event log and is untouched.
export async function deleteChatConversation(conversationId: string) {
  const r = await fetch(
    `/api/chat/threads/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail ?? `delete failed (${r.status})`);
  }
  return r.json() as Promise<{
    status: string; conversation_id: string;
    transcript_removed: boolean; threads: ChatThread[];
  }>;
}

export interface ChatEvent { type: string; [k: string]: unknown; }
export interface ChatThread {
  conversation_id: string;
  id?: string;
  title: string;
  updated_at: string;
  target?: string;
  last_prompt?: string;
  model?: string;
}
export interface ChatThreadsResponse {
  threads: ChatThread[];
  source: string;
  writable?: boolean;
  storage?: string;
  transcripts?: { enabled: boolean; dir: string; endpoint: string };
}
export const fetchChatThreads = () => getJSON<ChatThreadsResponse>("/api/chat/threads");

// The flight-recorder story of one conversation: per-turn context provenance,
// FULL tool args/results (the SSE stream truncates; this never does), final answer.
export interface TranscriptEvent {
  type: string;          // "round" | "tool" | "tool_result"
  ts?: string;
  n?: number;
  name?: string;
  args?: string;
  result?: string;
}
// All fields optional: a corrupt_line row (partial JSONL append) carries none
// of the normal keys, and the UI must render around it, not crash on it.
export interface TranscriptTurn {
  ts?: string;
  conversation_id?: string;
  surface?: string;
  model_role?: string;
  user_text?: string;
  context_blocks?: string[];
  events?: TranscriptEvent[];
  final?: string | null;
  corrupt_line?: string;
}
export interface ChatTranscriptResponse {
  conversation_id: string;
  turns: TranscriptTurn[];
  turn_count: number;
  total_turns?: number;
  offset?: number;
  // card-scoped chats (domain:card ids) also carry the card's board/agent
  // history — same row shape as the packet story
  card_story?: JobStoryEntry[];
  source: string;
  recording_enabled: boolean;
}
export const fetchChatTranscript = (conversationId: string, limit?: number) =>
  getJSON<ChatTranscriptResponse>(
    `/api/chat/threads/${encodeURIComponent(conversationId)}/transcript`
    + (limit ? `?limit=${limit}` : ""));

// Agent Sessions (Claude Agent / Codex Agent, via the cockpit's proxy to the
// host `cc agent-worker` — see agent_worker_client.py). Structurally separate
// from GatewayCore chat above: never routed through streamChat/`/api/chat/*`,
// never entering GatewayCore.dispatch. See WORKLOG.md "Agent-session chat
// integration" for why that boundary is load-bearing (a frontier model once
// leaked a tool_calls field into local dispatch when GatewayCore trusted a
// field it never offered — an agent session's tool surface is much bigger,
// so nothing here treats a harness's output as pre-validated either).
export interface AgentHarnessOption {
  harness_id: string;
  label: string;
  production: boolean;
  available: boolean;
  detail: string;
  supported_modes: string[];
}
export const fetchAgentHarnesses = () => getJSON<AgentHarnessOption[]>("/api/agent-harnesses");

export interface AgentSessionRecord {
  session_id: string;
  conversation_id: string;
  harness: string;
  provider_profile: string;
  model: string | null;
  external_session_id: string | null;
  repo_id: string;
  workspace_path: string | null;
  worktree_path: string | null;
  branch: string | null;
  base_branch: string | null;
  permission_profile: string;
  worker_id: string | null;
  status: string;   // starting | active | idle | interrupted | failed | closed
  created_at: string;
  updated_at: string;
  last_event_sequence: number;
  cost_usd: number;
}
export interface AgentSessionCreate {
  harness_id: string;
  conversation_id: string;
  repo_id: string;
  mode: string;
  provider_profile?: string;
  model?: string | null;
  permission_profile?: string;
}
export const createAgentSession = (body: AgentSessionCreate) =>
  postJSON<AgentSessionRecord>("/api/agent-sessions", body);
export const fetchAgentSession = (sessionId: string) =>
  getJSON<AgentSessionRecord>(`/api/agent-sessions/${encodeURIComponent(sessionId)}`);

export interface AgentMessageAck { session_id: string; status: string; }
export const sendAgentMessage = (sessionId: string, prompt: string) =>
  postJSON<AgentMessageAck>(
    `/api/agent-sessions/${encodeURIComponent(sessionId)}/messages`, { prompt });

// Same 16-type vocabulary as events.py's EventType — kept as `string` (not a
// union literal) so an unrecognized future event type degrades to the
// generic renderer instead of a TypeScript build break.
export interface AgentEvent {
  type: string;
  sequence: number | null;
  ts: string | null;
  payload: Record<string, unknown>;
}
export const fetchAgentEvents = (sessionId: string, afterSequence = 0) =>
  getJSON<AgentEvent[]>(
    `/api/agent-sessions/${encodeURIComponent(sessionId)}/events`
    + `?after_sequence=${afterSequence}`);

export interface AgentApprovalAck { session_id: string; approval_id: string; }
export const resolveAgentApproval = (
  sessionId: string, approvalId: string, approved: boolean, reason = "",
) =>
  postJSON<AgentApprovalAck>(
    `/api/agent-sessions/${encodeURIComponent(sessionId)}/approvals/`
    + encodeURIComponent(approvalId),
    { approved, reason });

export interface AgentStatusAck { session_id: string; status: string; }
export const interruptAgentSession = (sessionId: string) =>
  postJSON<AgentStatusAck>(
    `/api/agent-sessions/${encodeURIComponent(sessionId)}/interrupt`, {});
export const resumeAgentSession = (sessionId: string) =>
  postJSON<AgentStatusAck>(
    `/api/agent-sessions/${encodeURIComponent(sessionId)}/resume`, {});
export async function closeAgentSession(sessionId: string): Promise<AgentStatusAck> {
  const r = await fetch(`/api/agent-sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail ?? `close failed (${r.status})`);
  }
  return r.json() as Promise<AgentStatusAck>;
}

// Browser-facing agent-session SSE. Native EventSource (not a manual fetch
// reader like streamChat above) — a plain GET stream gets Last-Event-ID
// reconnect for free from the browser, and comment-only heartbeat lines
// (`: heartbeat`) are ignored automatically without any special-casing here.
// `transport_error` frames are a DISTINCT callback, never forwarded through
// onEvent — a worker/transport failure must never be rendered as if it were
// a real AgentEvent (matches the backend's own framing discipline).
export function streamAgentEvents(
  sessionId: string,
  afterSequence: number,
  onEvent: (e: AgentEvent) => void,
  onTransportError: (detail: string) => void,
): () => void {
  const es = new EventSource(
    `/api/agent-sessions/${encodeURIComponent(sessionId)}/events/stream`
    + `?after_sequence=${afterSequence}`);
  es.addEventListener("agent_event", (raw) => {
    try { onEvent(JSON.parse((raw as MessageEvent).data) as AgentEvent); }
    catch (e) { onTransportError(`malformed event from stream: ${String(e)}`); }
  });
  es.addEventListener("transport_error", (raw) => {
    try {
      const body = JSON.parse((raw as MessageEvent).data) as { detail?: string };
      onTransportError(body.detail ?? "agent worker transport error");
    } catch {
      onTransportError("agent worker transport error");
    }
  });
  // EventSource retries transparently on a dropped connection (with
  // Last-Event-ID) — nothing to surface here; the caller's own transport
  // error / status polling covers a genuinely dead session.
  return () => es.close();
}

async function postJSON<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const r = await fetch(path, {
    method, headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail ?? `request failed (${r.status})`);
  }
  return r.json() as Promise<T>;
}

export const postAction = (action: string, params: Record<string, unknown>) =>
  postJSON<{ result: string }>("/api/action", { action, params });
export const saveChatThread = (body: {
  conversation_id: string;
  title?: string;
  target?: string;
  last_prompt?: string;
  model?: string;
}) => postJSON<ChatThreadsResponse>("/api/chat/threads", body);

// Usage & Limits — the shared metering layer across chat models AND agents.
// Mirrors command_center.usage RuntimeUsageStatus.to_dict(); nullable fields are
// honestly nullable (a missing cost is null, never 0, never a fake quota).
export interface UsageLimit {
  bucket_id: string;
  scope: "provider" | "internal_budget";
  source: string;
  state: "ok" | "near_limit" | "exhausted" | "unknown";
  label: string;
  used_percent: number | null;
  used_amount: number | null;
  limit_amount: number | null;
  remaining_amount: number | null;
  unit: string;
  window_seconds: number | null;
  reset_at: string | null;
  plan_type: string | null;
  credits_remaining: number | null;
  runtime_availability?: string;   // present on /api/model-limits rows
  runtime_stale?: boolean;
}
export interface UsageRollup {
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  calls: number;
  sessions: number;
  tool_calls: number;
  duration_ms: number;
  cost_usd: number | null;
  cost_source: string;
}
export interface UsageStatus {
  runtime_id: string;
  availability: string;
  availability_reason: string;
  availability_observed_at: string | null;
  limits: UsageLimit[];
  rolled_usage: UsageRollup | null;
  stale: boolean;
  generated_at: string;
}
export interface CollectorHealth {
  collector_id: string;
  never_ran: boolean;
  auth_state: string;
  consecutive_failures: number;
  last_success_at?: string | null;
  last_error?: string | null;
  updated_at?: string;
}
export interface UsageRefreshResult {
  collectors_run: number;
  results: { collector_id: string; runtimes: string[]; alerts_fired: number }[];
}
export const fetchModelUsage = () => getJSON<UsageStatus[]>("/api/model-usage");
export const fetchCollectorHealth = () =>
  getJSON<CollectorHealth[]>("/api/model-usage/collector-health");
export const refreshModelUsage = () =>
  postJSON<UsageRefreshResult>("/api/model-usage/refresh", {});

// Stream a chat turn (SSE over fetch): each event (round/tool/tool_result/final)
// is delivered as it arrives. Errors are surfaced as an event, never swallowed.
export async function streamChat(
  body: { text: string; conversation_id?: string; model?: string },
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const r = await fetch("/api/chat/stream", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok || !r.body) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail ?? `chat failed (${r.status})`);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const frames = buf.split("\n\n");
    buf = frames.pop() ?? "";
    for (const f of frames) {
      const line = f.trim();
      if (!line.startsWith("data:")) continue;
      try { onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent); }
      catch (e) { onEvent({ type: "error", message: String(e) }); }
    }
  }
}
