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

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(path, { signal });
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }));
    throw new ApiError(r.status, body.detail ?? `request failed (${r.status})`);
  }
  return r.json() as Promise<T>;
}

// First-party board snapshot (produced on the worker, read-only here).
export interface BoardCard {
  title: string;
  meta: string;
  fields?: Record<string, string | number>;
}
export interface BoardColumn { name: string; cards: BoardCard[]; }
export interface WorkspaceBoard {
  board: string;
  statuses?: string[];          // full legal columns — the "Move to…" targets
  columns?: BoardColumn[];
  error?: string;
}
export interface BoardSnapshot {
  generated_at: string;
  live?: boolean;               // true when read from the live local board store (console)
  boards: WorkspaceBoard[];
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

// Universal Capture — save a rough thought as a durable, recoverable intake
// record BEFORE it becomes work. Capturing never starts work.
export interface CaptureRecord {
  capture_id: string; raw_content: string; source_type: string;
  requested_mode: string; batch_id?: string | null; captured_at: string;
  current_board_id?: string | null; conversation_id?: string | null;
}
export interface CaptureView {
  record: CaptureRecord; processing_status: string;
  classification?: unknown; event_count: number; updated_at: string;
}
export interface InboxCaptureCard {
  capture_id: string; preview: string; source_type: string;
  requested_mode: string; processing_status: string; batch_id?: string | null;
  capture_kind?: string | null; suggested_board_id?: string | null;
  captured_at: string; updated_at: string;
}
export interface InboxData {
  columns: { name: string; captures: InboxCaptureCard[] }[]; total: number;
}
export interface CaptureIn {
  raw_content: string; source_type?: string; source_ref?: string;
  current_board_id?: string; current_card_id?: string; conversation_id?: string;
  requested_mode?: string;
}
export const createCapture = (body: CaptureIn) =>
  postJSON<CaptureView>("/api/captures", body, "POST");
export const createCaptureBatch = (
  text: string, extra: Partial<CaptureIn> = {}) =>
  postJSON<{ count: number; batch_id: string | null; captures: CaptureView[] }>(
    "/api/captures/batch", { text, source_type: "list", ...extra }, "POST");
export const fetchCapture = (captureId: string) =>
  getJSON<CaptureView>(`/api/captures/${encodeURIComponent(captureId)}`);
export interface CapturePrepareAction {
  id: "continue_in_chat" | "route_to_todos" | "choose_existing_board" | "create_new_board" | string;
  label: string;
  description: string;
}
export interface CapturePrepareResult {
  capture_id: string;
  conversation_id: string;
  processing_status: string;
  chat_prompt: string;
  available_actions: CapturePrepareAction[];
}
export const prepareCapture = (captureId: string) =>
  postJSON<CapturePrepareResult>(
    `/api/captures/${encodeURIComponent(captureId)}/prepare`, {});
export const fetchInbox = () => getJSON<InboxData>("/api/intake/inbox");

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
export type DomainIntakeValue = boolean | number | string | string[];
export interface DomainIntake {
  producer: string;
  mode: "manual" | "scheduled" | "event" | "projection" | "external";
  summary: string;
  schedule: string;
  source_refs: string[];
  parameters: Record<string, DomainIntakeValue>;
  editable: boolean;
}
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
  intake: DomainIntake;
  archived?: boolean;
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
  data_quality?: {
    quarantined_empty_imports: number;
    retained_in_store: boolean;
    reason: string;
  };
  source_sync?: {
    state: string;
    source_available: boolean;
    source_sha256: string;
    projected_sha256: string;
    write_on_read: boolean;
  };
}
export interface DomainCardDetail {
  domain_id: string; card: DomainCard; drawer_fields: FieldSpec[];
}
export interface RegisteredRepository {
  repo_id: string;
  remote_url: string;
  kanban_board_id?: string | null;
  risk_ceiling: string;
  autonomous_edits_enabled: boolean;
  research_capabilities: string[];
  scan_reason: string;
}
export interface RegisteredRepositoryCatalog {
  repositories: RegisteredRepository[];
  source: string;
}
export const fetchRegisteredRepositories = () =>
  getJSON<RegisteredRepositoryCatalog>("/api/repos");
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
export interface DomainIntakeResponse {
  domain_id: string;
  intake: DomainIntake;
  revision: string;
  writable: boolean;
  write_gate: string;
}
export const fetchDomainIntake = (domainId: string) =>
  getJSON<DomainIntakeResponse>(
    `/api/domain/${encodeURIComponent(domainId)}/intake`);
export const syncGrandTodoSource = (domainId: string) =>
  postJSON<{
    status: string; domain_id: string; source_sha256: string;
    counts: Record<string, number>;
  }>(`/api/domain/${encodeURIComponent(domainId)}/sync`, {});
export const updateDomainIntake = (
  domainId: string, intake: DomainIntake, expectedRevision: string,
) => postJSON<DomainIntakeResponse>(
  `/api/domain/${encodeURIComponent(domainId)}/intake`,
  { intake, expected_revision: expectedRevision },
  "PUT",
);
export interface ResearchAnalysisCounts {
  total: number;
  titled: number;
  complete: number;
  pending: number;
  missing_title: number;
}
export interface ResearchRefreshState {
  schema_version: string;
  request_id?: string;
  state: "idle" | "queued" | "running" | "complete" | "blocked" | string;
  requested_at?: string;
  requested_sources?: string[];
  ingested_sources?: string[];
  message?: string;
  error?: string;
  analysis?: Record<string, Record<string, unknown>>;
}
export interface ResearchCategoryOption { value: string; label: string; }
export interface ResearchSettingsResponse {
  topics: string[];
  topic_suggestions: string[];
  category_options: ResearchCategoryOption[];
  paper: DomainIntakeResponse;
  repo: DomainIntakeResponse;
  refresh: ResearchRefreshState;
}
export interface ResearchSourceSettings {
  enabled: boolean;
  top_n: number;
  lookback_days: number;
  analysis_batch_size: number;
  categories?: string[];
  min_stars?: number;
}
export const fetchResearchSettings = () =>
  getJSON<ResearchSettingsResponse>("/api/research/settings");
export const updateResearchSettings = (value: {
  topics: string[];
  paper: ResearchSourceSettings;
  repo: ResearchSourceSettings;
  expected_revisions: { paper: string; repo: string };
  refresh: boolean;
}) => postJSON<ResearchSettingsResponse>("/api/research/settings", value, "PUT");
export const requestResearchRefresh = (sources: ("paper" | "repo")[]) =>
  postJSON<{ refresh: ResearchRefreshState }>(
    "/api/research/refresh", { sources });
export const fetchResearchRefresh = () => getJSON<{
  refresh: ResearchRefreshState;
}>("/api/research/refresh");
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
export const archiveDomainSchema = (domainId: string) =>
  postJSON<DomainSchema>(`/api/domain-schema/${encodeURIComponent(domainId)}`, {}, "DELETE");
export const restoreDomainSchema = (domainId: string) =>
  postJSON<DomainSchema>(`/api/domain-schema/${encodeURIComponent(domainId)}/restore`, {});

export interface TodoBoardLink {
  board_id: string;
  domain_id: string;
  is_primary: boolean;
  placement_id?: string | null;
  source_projection?: boolean;
  repo_ids: string[];
  href: string;
}
export interface TodoRow {
  todo_id: string;
  work_item_id?: string | null;
  source_kind: string;
  source_id: string;
  raw_preview: string | null;
  title: string | null;
  description: string | null;
  kind: string | null;
  status: string | null;
  raw_status: string | null;
  assigned: boolean;
  boards: TodoBoardLink[];
  repo_ids: string[];
  created_at?: string | null;
  updated_at?: string | null;
  source_href: string;
  assignable: boolean;
  integrity: { missing_fields: string[] };
}
export interface TodoBoardOption {
  board_id: string;
  domain_id: string;
  title: string;
  columns: string[];
}
export interface TodoInventory {
  rows: TodoRow[];
  registered_repos: {
    repo_id: string;
    remote_url: string;
  }[];
  filtered_total: number;
  inventory_total: number;
  has_more: boolean;
  offset: number;
  limit: number;
  routable_boards: TodoBoardOption[];
  filter_catalogs: {
    kinds: string[]; statuses: string[]; sources: string[];
    boards: { board_id: string; domain_id: string; title: string }[];
  };
  completeness: {
    complete: boolean;
    source_counts: { work_items: number; captures: number; board_cards: number };
    emitted_total: number;
    deduplicated_projections: number;
    unassigned_total: number;
    error_count: number;
    errors: { source: string; code: string; message: string }[];
    watermark: string;
    checked_at: string;
  };
}
export interface TodoStoryError {
  source: string;
  code: string;
  message: string;
}
export interface TodoStoryItem {
  work_item_id: string;
  title: string;
  description: string;
  canonical_status: string;
  updated_at: string;
  [key: string]: unknown;
}
export interface TodoDetail {
  requested_identity: {
    todo_id: string;
    kind: "work" | "capture" | "card";
    source_id: string;
    state: "emitted" | "not_materialized" | "folded_into_work_items";
    is_emitted_master_todo: boolean;
    missing_linked_work_item_ids: string[];
  };
  emitted_todo: TodoRow | null;
  aggregate_todos: TodoRow[];
  canonical_item: TodoStoryItem | null;
  linked_work_items: TodoStoryItem[];
  raw_captures: Array<{
    record: Record<string, unknown> & { capture_id: string; raw_content: string };
    processing_status: string;
    classification: Record<string, unknown> | null;
    events: Array<Record<string, unknown>>;
  }>;
  source: {
    kind: string;
    card: Record<string, unknown> | null;
    audit: Record<string, unknown>;
    exact_board_pairs: Array<{ board_id: string; card_id: string }>;
  };
  repositories: Array<{ repo_id: string; remote_url: string }>;
  placements: Array<Record<string, unknown> & {
    placement_id: string; board_id: string; domain_id: string;
    active: boolean; role: string; href: string; repo_ids: string[];
  }>;
  relationships: Array<Record<string, unknown> & {
    edge: Record<string, unknown>; active: boolean; direction: string;
    related_item: TodoStoryItem | null;
  }>;
  routing: {
    classifications: Array<Record<string, unknown>>;
    corrections: Array<Record<string, unknown>>;
  };
  conversations: Array<{ conversation_id: string; href: string }>;
  work_events: Array<Record<string, unknown>>;
  board_events: Array<Record<string, unknown>>;
  missions: Array<Record<string, unknown>>;
  completion_evidence: Array<Record<string, unknown> & { evidence_ref: string }>;
  timeline: Array<Record<string, unknown> & {
    at: string | null; source: string; kind: string; ref: string | null;
  }>;
  archive_history: Array<Record<string, unknown>>;
  completeness: {
    complete: boolean;
    error_count: number;
    errors: TodoStoryError[];
    board_event_join_state: "exact" | "not_linked";
  };
}
export const fetchTodos = (params: {
  q?: string; kind?: string; status?: string; source?: string;
  assigned?: boolean; board_id?: string; offset?: number; limit?: number;
} = {}, signal?: AbortSignal) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  const suffix = query.size ? `?${query.toString()}` : "";
  return getJSON<TodoInventory>(`/api/todos${suffix}`, signal);
};
export const fetchTodoDetail = (todoId: string, signal?: AbortSignal) =>
  getJSON<TodoDetail>(`/api/todos/${encodeURIComponent(todoId)}`, signal);
export const updateWorkItemDescription = (
  workItemId: string,
  body: {
    description: string;
    expected_updated_at: string;
    expected_description: string;
  },
  signal?: AbortSignal,
) => postJSON<{ item: TodoStoryItem }>(
  `/api/work-items/${encodeURIComponent(workItemId)}/description`, body, "PUT",
  signal,
);
export const assignTodo = (
  todoId: string,
  body: {
    board_id?: string;
    domain_id?: string;
    new_board_title?: string;
    canonical_title?: string;
    canonical_description?: string;
    canonical_kind?: string;
    confirm_canonical_fields?: boolean;
  },
  signal?: AbortSignal,
) => postJSON<{
  status: string; todo: TodoRow; board: TodoBoardOption;
}>(`/api/todos/${encodeURIComponent(todoId)}/assign`, body, "POST", signal);

export interface KanbanMaintenanceSuggestion {
  suggestion_id: string;
  kind: string;
  board_ids: string[];
  title: string;
  reason: string;
  evidence: Record<string, unknown>;
  status: string;
  suggested_at?: string;
  decided_at?: string;
  work_item_id?: string;
}
export interface KanbanMaintenanceReview {
  open: KanbanMaintenanceSuggestion[];
  pending: KanbanMaintenanceSuggestion[];
  history: KanbanMaintenanceSuggestion[];
  event_count: number;
  destructive_actions_performed: false;
  scan?: { candidate_count: number; created_count: number };
}
export const fetchKanbanMaintenance = () =>
  getJSON<KanbanMaintenanceReview>("/api/kanban-maintenance");
export const scanKanbanMaintenance = () =>
  postJSON<KanbanMaintenanceReview>("/api/kanban-maintenance/scan", {});
export const decideKanbanMaintenance = (
  suggestionId: string, decision: "accept" | "reject", reasonNote?: string,
) => postJSON<Record<string, unknown>>(
  `/api/kanban-maintenance/${encodeURIComponent(suggestionId)}/decision`,
  { decision, reason_note: reasonNote ?? null },
);

// Create a whole board MODULE (kanban board + generic_task domain surface) from
// one typed request — the guided Create-Board flow. Safe governance defaults.
export type ExecutionScope = "life" | "repository" | "hybrid";
export interface BoardModuleIn {
  title: string;
  description?: string;
  icon?: string;
  execution_scope?: ExecutionScope;
  repo_ids?: string[];
  columns?: string[];
  chat_enabled?: boolean;
}
export interface BoardModuleResult {
  board_id: string;
  domain_id: string;
  title: string;
  provider: string;
  execution_scope: ExecutionScope;
  card_component: string;
  columns: string[];
  repo_ids: string[];
  chat_enabled: boolean;
}
export const createBoardModule = (body: BoardModuleIn) =>
  postJSON<BoardModuleResult>("/api/board-module", body, "POST");
export const boardIdFromTitle = (title: string) =>
  title.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "");
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
export const moveDomainCard = (
  id: string, cardId: string, status: string,
  reason?: { reason_code?: string; reason_note?: string },
) =>
  postJSON<DomainMoveResult>(`/api/domain/${encodeURIComponent(id)}/move`, {
    card_id: cardId, status, ...(reason ?? {}),
  });
export interface BookFieldsInput {
  author?: string | null;
  description?: string | null;
  tier?: string | null;
  type?: string | null;
  genre?: string | null;
  module?: string | null;
  section?: string | null;
  hours?: string | null;
  isbn?: string | null;
  notes?: string | null;
  current_chapter?: string | null;
  current_page?: number | null;
  total_pages?: number | null;
  progress_percent?: number | null;
}
export interface BookCreateInput extends BookFieldsInput {
  title: string;
  status: string;
}
export interface BookUpdateInput extends BookFieldsInput {
  title?: string | null;
}
export interface BookNote {
  note_id: string;
  sequence: number;
  author: string;
  text: string;
  chapter?: string;
  page?: number;
  total_pages?: number;
  progress_percent?: number;
  created_at: string;
}
export interface BookNoteInput {
  author: string;
  text: string;
  chapter?: string | null;
  page?: number | null;
  total_pages?: number | null;
  progress_percent?: number | null;
}
export interface BookMutationResult {
  status: string;
  domain_id: "book";
  card_id: string;
  card: DomainCard;
  event?: Record<string, unknown> | null;
  note?: BookNote;
}
export const createBookCard = (body: BookCreateInput) =>
  postJSON<BookMutationResult>("/api/domain/book/cards", body);
export const updateBookCard = (cardId: string, body: BookUpdateInput) =>
  postJSON<BookMutationResult>(
    `/api/domain/book/card/${encodeURIComponent(cardId)}`, body, "PUT");
export const addBookNote = (
  cardId: string, body: BookNoteInput,
) =>
  postJSON<BookMutationResult>(
    `/api/domain/book/card/${encodeURIComponent(cardId)}/notes`, body);
export const archiveBookCard = (cardId: string) =>
  postJSON<BookMutationResult>(
    `/api/domain/book/card/${encodeURIComponent(cardId)}`, {}, "DELETE");
export interface GrandTodoEditResult {
  status: string;
  card: DomainCard;
  sync: Record<string, number>;
}
export const updateGrandTodoCard = (
  domainId: string, cardId: string, rawMarkdown: string,
  expectedSourceSha256: string,
) =>
  postJSON<GrandTodoEditResult>(
    `/api/domain/${encodeURIComponent(domainId)}/card/${encodeURIComponent(cardId)}`,
    { raw_markdown: rawMarkdown, expected_source_sha256: expectedSourceSha256 },
    "PUT",
  );
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
  furthersProcess = false,
) =>
  postJSON<DomainNoteResult>(
    `/api/domain/${encodeURIComponent(id)}/card/${encodeURIComponent(cardId)}/note`,
    { type, text, source, furthers_process: furthersProcess },
  );

export interface LinkedInComposerAccount {
  id: string;
  kind: string;
  label: string;
}
export interface LinkedInComposerOptions {
  accounts: LinkedInComposerAccount[];
  max_characters: number;
  desktop_fold_characters: number;
  mobile_fold_characters: number;
  write_ready: boolean;
  write_blockers: string[];
}
export interface LinkedInDraftIn {
  account: string;
  body: string;
  tags?: string[];
  source_ref?: string;
  scheduled_for?: string | null;
}
export interface LinkedInDraftResult {
  status: string;
  domain_id: string;
  card_id: string;
  card: DomainCard;
  event: Record<string, unknown>;
  warnings: { level: string; code: string; message: string }[];
}
export const fetchLinkedInComposer = () =>
  getJSON<LinkedInComposerOptions>("/api/domain/linkedin_post/composer");
export const createLinkedInPostDraft = (body: LinkedInDraftIn) =>
  postJSON<LinkedInDraftResult>("/api/domain/linkedin_post/drafts", body);

// Application packet review loop (job_application cards): view the generated
// materials + agent trace, request changes (regenerates via the agent writer),
// and record a submission completed externally (validation-gated governed
// Completed move + email record; this client never submits an employer form).
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
  retention: {
    rich_application_cache_days: number;
    extend_when_active: boolean;
    purge_rich_files: boolean;
    active_statuses: string[];
  };
  executor_fallback: Record<string, string>;
  locations: JobLocations;
  languages: JobLanguages;
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

export interface JobRelationship {
  relationship_id: string;
  name: string;
  company: string;
  role_title?: string | null;
  relationship_kind?: string | null;
  linkedin_url?: string | null;
  notes?: string | null;
  active: boolean;
  provenance: string;
  created_at: string;
  updated_at: string;
}
export interface JobQuestionCandidate {
  category_id: string;
  answer: string;
  created_at: string;
  updated_at: string;
}
export interface JobQuestionLibraryEntry {
  question_id: string;
  question: string;
  categories: string[];
  occurrence_count: number;
  candidate_answers: JobQuestionCandidate[];
}
export interface JobOutreachDraft {
  relationship_id: string;
  kind: string;
  subject: string;
  body: string;
}
export type JobOutreachContact = Pick<
  JobRelationship,
  "relationship_id" | "name" | "company" | "role_title" |
  "relationship_kind" | "linkedin_url" | "active"
>;
export interface JobOutreach {
  draft_only: true;
  card_id: string;
  application_id: string | null;
  company: string;
  role_title: string;
  known_contacts: JobOutreachContact[];
  drafts: JobOutreachDraft[];
  recommended_role_searches: string[];
}
export const fetchJobRelationships = (active?: boolean) =>
  getJSON<{ relationships: JobRelationship[] }>(
    `/api/job-search/relationships${active === undefined ? "" : `?active=${active}`}`,
  );
export const putJobRelationship = (
  relationshipId: string,
  body: {
    name: string; company: string; role_title?: string;
    relationship_kind?: string; linkedin_url?: string; notes?: string;
    active?: boolean;
  },
) => postJSON<{ status: "created" | "updated" | "unchanged"; relationship: JobRelationship }>(
  `/api/job-search/relationships/${encodeURIComponent(relationshipId)}`, body, "PUT",
);
export const fetchJobQuestionLibrary = (categoryId?: string) =>
  getJSON<{ questions: JobQuestionLibraryEntry[] }>(
    `/api/job-search/question-library${categoryId ? `?category_id=${encodeURIComponent(categoryId)}` : ""}`,
  );
export const captureJobQuestion = (cardId: string, question: string) =>
  postJSON<{
    status: "created" | "recorded" | "unchanged";
    question: JobQuestionLibraryEntry;
    occurrence: { application_id: string; card_id: string; category_id: string };
  }>("/api/job-search/question-library", { card_id: cardId, question });
export const putJobQuestionCandidate = (
  questionId: string, categoryId: string, answer: string,
) => postJSON<{
  status: "created" | "updated" | "unchanged";
  candidate_answer: JobQuestionCandidate;
}>(
  `/api/job-search/question-library/${encodeURIComponent(questionId)}/candidate/${encodeURIComponent(categoryId)}`,
  { answer }, "PUT",
);
export const fetchJobOutreach = (cardId: string) =>
  getJSON<JobOutreach>(`/api/job-search/cards/${encodeURIComponent(cardId)}/outreach`);
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
export const updateJobSearchCompanyTargets = (
  body: JobProfileControls["company_targets"],
) =>
  postJSON<{
    status: string;
    source: string;
    company_targets: JobProfileControls["company_targets"];
  }>("/api/job-search/profile-controls/company-targets", body, "PUT");
export const updateJobSearchRetention = (richApplicationCacheDays: number) =>
  postJSON<{
    status: string;
    source: string;
    retention: JobProfileControls["retention"];
  }>("/api/job-search/profile-controls/retention", {
    rich_application_cache_days: richApplicationCacheDays,
  }, "PUT");
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

// ---- location + language filters (hybrid geo/language gate) ----------------
export interface JobLocations {
  mode: "worldwide" | "countries" | "regions" | string;
  remote_ok: boolean;
  remote_types_allowed: string[];
  employment_types_allowed: string[];
  countries: string[];
  regions: string[];
}
export interface JobLanguages {
  spoken: string[];
  require_spoken_for_apply: boolean;
}
export const updateJobSearchLocations = (body: Partial<JobLocations>) =>
  postJSON<{ status: string; source: string; locations: JobLocations }>(
    "/api/job-search/profile-controls/locations", body, "PUT");
export const updateJobSearchLanguages = (body: Partial<JobLanguages>) =>
  postJSON<{ status: string; source: string; languages: JobLanguages }>(
    "/api/job-search/profile-controls/languages", body, "PUT");

// ---- background packet-prep queue ------------------------------------------
export interface PrepStatus {
  operation: string;
  pending: boolean;
  running: boolean;
  runs_completed: number;
  requests_total: number;
  last_finished_at: string | null;
  last_error: string | null;
  last_result: Record<string, unknown> | null;
}
export const fetchPrepStatus = () =>
  getJSON<PrepStatus>("/api/job-search/prep-status");

// ---- rejection feedback loop -----------------------------------------------
export interface RejectionSuggestion {
  priority: string;
  area: string;
  suggestion: string;
  evidence: unknown;
}
export interface RejectionsReport {
  operation: string;
  total_rejections: number;
  counts_by_reason: Record<string, number>;
  reason_labels: Record<string, string>;
  suggestions: RejectionSuggestion[];
  source: string;
}
export const fetchRejectionsReport = () =>
  getJSON<RejectionsReport>("/api/job-search/rejections-report");
// mirrors command_center.job_search.rejections.REASON_CODES
export const REJECT_REASONS: { code: string; label: string }[] = [
  { code: "location", label: "Location / geography wrong" },
  { code: "remote", label: "Work arrangement wrong (remote/hybrid/onsite)" },
  { code: "language", label: "Language requirement I don't meet" },
  { code: "seniority", label: "Seniority mismatch (too junior / too senior)" },
  { code: "salary", label: "Salary too low or not listed" },
  { code: "domain", label: "Wrong domain / industry" },
  { code: "role_type", label: "Wrong kind of work" },
  { code: "company", label: "Company-specific reason" },
  { code: "duplicate", label: "Duplicate / already applied" },
  { code: "stale", label: "Posting expired or stale" },
  { code: "low_fit", label: "Low overall fit" },
  { code: "other", label: "Other (see note)" },
];

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
  repos?: RegisteredRepository[];
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
  usage_summary?: UsageStatus;               // live availability/limits for a badge
  models_endpoint?: string;
  // True when this harness ships repo contents to a PAID EXTERNAL API
  // (OpenRouter). The composer must show a "context leaves the machine"
  // confirmation before the first send; local runtimes leave this false.
  external_egress?: boolean;
}
export const fetchAgentHarnesses = () => getJSON<AgentHarnessOption[]>("/api/agent-harnesses");

// Runtime-discovered model + effort catalog for the picker (Codex live SDK
// models incl. supported efforts; Claude validated aliases).
export interface AgentModelOption {
  id: string;
  display_name: string;
  is_default: boolean;
  description?: string;
  default_effort?: string | null;
  supported_efforts: string[];
  context_options: string[];
  available: boolean;
}
export interface AgentModelCatalog {
  harness_id: string;
  models: AgentModelOption[];
  error?: string;
}
export const fetchHarnessModels = (harnessId: string) =>
  getJSON<AgentModelCatalog>(`/api/agent-harnesses/${encodeURIComponent(harnessId)}/models`);

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
  effort?: string | null;
  context_mode?: string | null;
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

// "Track as mission" — record this read-only session as a Ledger tracking mission.
// Reuses the existing session (no restart); grants no writes. Returns the mission id.
export interface AgentPromoteResult {
  mission_id: string;
  status: string;
  session_id: string;
  conversation_id: string;
}
export const promoteAgentSession = (sessionId: string, summary = "") =>
  postJSON<AgentPromoteResult>(
    `/api/agent-sessions/${encodeURIComponent(sessionId)}/promote`, { summary });

// Bounded hand-off (Claude <-> Codex <-> OpenRouter). The worker assembles a
// briefing from the source session's stored events (never the whole transcript)
// and records handoff_started evidence; `prompt` seeds the target assistant.
export interface AgentHandoffResult {
  packet: Record<string, unknown>;
  prompt: string;
}
export const buildAgentHandoff = (
  sessionId: string, toHarness: string, goal?: string,
) =>
  postJSON<AgentHandoffResult>(
    `/api/agent-sessions/${encodeURIComponent(sessionId)}/handoff`,
    { to_harness: toHarness, goal: goal ?? null, open_questions: [] });

// Typed chat attachments — resolved + safety-checked on the HOST (secret paths
// and escapes refused; blocked ones surfaced, never dropped). Path kinds resolve
// against the selected context (repo); resource kinds by id.
export interface AttachmentReq {
  attachment_id: string;
  kind: string;
  rel_path?: string | null;
  resource_id?: string | null;
  display_name: string;
}
export interface ResolvedAttachment {
  attachment: {
    attachment_id: string; kind: string; display_name: string;
    resource_id: string | null; path_ref: string | null;
    content_digest: string | null; size_bytes: number | null;
    provenance: string; sensitivity: string; egress_allowed: boolean;
  } | null;
  refusal: { requested: string; kind: string; reason: string } | null;
}
export interface AttachmentsResolveResult {
  resolutions: ResolvedAttachment[];
  summary: {
    count: number; total_bytes: number;
    blocked: { requested: string; kind: string; reason: string }[];
    any_leaves_machine: boolean;
  };
}
export const resolveAttachments = (
  repoId: string | null, externalEgress: boolean, items: AttachmentReq[],
) =>
  postJSON<AttachmentsResolveResult>("/api/attachments/resolve",
    { repo_id: repoId, external_egress: externalEgress, items });

// Board-format change (columns) — structured spec in, server-computed before/
// after + preview out (no browser-generated YAML). apply_payload is opaque and
// echoed to /api/board-changes/apply with a proposal-bound token.
export interface BoardFormatTarget {
  domain_id: string; title: string; columns: string[];
}
export const fetchBoardFormatTargets = () =>
  getJSON<{ boards: BoardFormatTarget[] }>("/api/board-changes/format-boards");

export interface BoardFormatPlan {
  proposal_id: string;
  target_board: string;
  before_columns: string[];
  after_columns: string[];
  diff: { added: string[]; removed: string[]; reordered: string[] };
  preview: { validates: boolean; validation_error: string | null; warnings: string[] };
  apply_payload: Record<string, unknown>;
}
export const planBoardFormat = (
  domainId: string, columns: string[], rationale = "",
) =>
  postJSON<BoardFormatPlan>("/api/board-changes/plan-format",
    { domain_id: domainId, columns, rationale });

export const mintBoardApproval = (proposalId: string, operator: string) =>
  postJSON<{ approval_token: string; proposal_id: string }>(
    "/api/board-changes/approval-token", { proposal_id: proposalId, operator });

export const applyBoardChange = (
  applyPayload: Record<string, unknown>, approvalToken: string,
) =>
  postJSON<{ receipt: Record<string, unknown> }>("/api/board-changes/apply",
    { ...applyPayload, approval_token: approvalToken });

// "Track as mission" for a GatewayCore conversation (no agent session). Same
// inert tracking mission; grants no writes. Returns the mission id.
export interface ChatPromoteResult {
  mission_id: string;
  status: string;
  conversation_id: string;
}
export const promoteChat = (conversationId: string, summary = "") =>
  postJSON<ChatPromoteResult>(
    "/api/chat/promote", { conversation_id: conversationId, summary });
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

async function postJSON<T>(
  path: string, body: unknown, method = "POST", signal?: AbortSignal,
): Promise<T> {
  const r = await fetch(path, {
    method, headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body), signal,
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new ApiError(r.status, d.detail ?? `request failed (${r.status})`);
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
export interface UsageKpis {
  average_tokens_per_call: number | null;
  average_output_tokens_per_call: number | null;
  output_share_percent: number | null;
  cached_input_share_percent?: number | null;
  average_duration_ms: number | null;
  success_rate_percent: number | null;
  cost_per_call_usd: number | null;
}
export interface UsageRecentActivity {
  purpose: string;
  observed_at: string | null;
  model?: string | null;
  effort?: string | null;
  context_mode?: string | null;
  input_tokens: number;
  cached_input_tokens?: number;
  output_tokens: number;
  total_tokens: number;
  duration_ms: number | null;
  cost_usd: number | null;
  cost_source?: string;
  status?: string;
}
export interface UsagePurposeBreakdown {
  purpose: string;
  calls: number;
  share_percent: number;
}
export interface ModelUsageEntry {
  lane: "local" | "openrouter";
  provider: string;
  model_id: string;
  status: "active" | "observed";
  roles: string[];
  aliases: string[];
  source_id: string;
  cost_source: string;
  calls: number | null;
  failed_calls: number | null;
  outcome_observed_calls: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  duration_ms: number | null;
  cost_usd: number | null;
  last_used_at: string | null;
  kpis: UsageKpis;
  purpose_breakdown: UsagePurposeBreakdown[];
  recent_activity: UsageRecentActivity[];
}
export interface UsageSourceHealth {
  source_id: string;
  label: string;
  state: "ok" | "empty" | "degraded" | "unavailable";
  row_count: number;
  included_row_count: number;
  retained_row_count?: number | null;
  latest_observed_at?: string | null;
  detail: string;
}
export type UsageWindowId = "day" | "week" | "month" | "all";
export interface UsageWindow {
  id: UsageWindowId;
  label: string;
  start_at: string | null;
  end_at: string;
}
export interface ModelUsagePortfolio {
  generated_at: string;
  window: UsageWindow;
  models: ModelUsageEntry[];
  sources: UsageSourceHealth[];
}
export interface UsageDriverRow {
  key: string;
  metric_value: number;
  share: number;
  sample_count: number;
}
export interface UsageDrivers {
  runtime_id: string;
  dimension: string;
  metric: string;
  rows: UsageDriverRow[];
}
export interface AgentUsageDetail {
  runtime_id: string;
  window: UsageWindow;
  kpis: UsageKpis;
  rows: UsageRecentActivity[];
}
export const fetchModelUsage = (window: UsageWindowId) =>
  getJSON<UsageStatus[]>("/api/model-usage?window=" + encodeURIComponent(window));
export const fetchCollectorHealth = () =>
  getJSON<CollectorHealth[]>("/api/model-usage/collector-health");
export const fetchModelUsagePortfolio = (window: UsageWindowId) =>
  getJSON<ModelUsagePortfolio>(
    "/api/model-usage/portfolio?window=" + encodeURIComponent(window));
export const fetchModelUsageDrivers = (
  runtimeId: string, window: UsageWindowId,
) =>
  getJSON<UsageDrivers>(
    "/api/model-usage/top-drivers?runtime_id=" + encodeURIComponent(runtimeId)
    + "&dimension=model&metric=total_tokens&limit=8&window="
    + encodeURIComponent(window),
  );
export const fetchRecentAgentUsage = (
  runtimeId: string, window: UsageWindowId,
) =>
  getJSON<AgentUsageDetail>(
    "/api/model-usage/recent-activity?runtime_id="
    + encodeURIComponent(runtimeId) + "&limit=8&window="
    + encodeURIComponent(window),
  );
export const refreshModelUsage = () =>
  postJSON<UsageRefreshResult>("/api/model-usage/refresh", {});

// ── Canonical work graph — one WorkItem, many board placements, typed edges ────
// A task on three boards is ONE work item with three placements, never three
// unrelated cards. Every navigable href is BACKEND-generated (ResourceLink.href)
// and rendered verbatim — the frontend never assembles a work route itself. Any
// endpoint returns 503 when the work graph is disabled; getJSON surfaces that as
// a thrown error, never as an empty graph.
export type WorkItemKind =
  | "note" | "todo" | "research" | "post" | "paper" | "project" | "bug"
  | "feature" | "decision" | "maintenance";
export type CanonicalStatus =
  | "backlog" | "ready" | "in_progress" | "blocked" | "awaiting_approval"
  | "done" | "rejected" | "archived";
export type WorkRelation =
  | "parent_of" | "blocks" | "related_to" | "implements" | "informs"
  | "derived_from" | "duplicates" | "supersedes" | "supports";
export interface WorkItem {
  work_item_id: string;
  title: string;
  description: string;
  kind: WorkItemKind;
  canonical_status: CanonicalStatus;
  primary_board_id: string | null;
  owner: string | null;
  priority: string | null;
  due_at: string | null;
  capture_id: string | null;
  capture_batch_id: string | null;
  packet_id: string | null;
  conversation_id: string | null;
  mission_id: string | null;
  created_at: string;
  updated_at: string;
}
// A projection of one WorkItem onto one board — the card the user sees IS a
// placement, not a separate task. placement_stage is a board-local visual stage,
// distinct from the item's canonical_status.
export interface WorkPlacement {
  placement_id: string;
  work_item_id: string;
  board_id: string;
  domain_id: string;
  is_primary: boolean;
  placement_stage: string | null;
  card_component: string;
  local_fields: Record<string, unknown>;
  created_at: string;
  removed_at: string | null;
}
export interface WorkEdge {
  edge_id: string;
  from_work_item_id: string;
  to_work_item_id: string;
  relation: WorkRelation;
  blocking: boolean;
  reason: string | null;
  evidence_refs: string[];
  created_by: string | null;
  created_at: string;
  removed_at: string | null;
}
// A backend-generated navigation receipt. Render `href` VERBATIM as an <a href>;
// NEVER assemble a route URL from an assumed format. `kind` orders the Connected
// Work list; `relation` distinguishes a primary board placement from a secondary.
export interface ResourceLink {
  kind:
    | "work_item" | "board" | "placement" | "chat" | "mission" | "packet"
    | "graph" | "evidence";
  resource_id: string;
  label: string;
  href: string;
  relation: string | null;
}
// A resolved neighbourhood around a root work item (or the whole graph): the
// items, their placements, and the edges among them. root_work_item_id is null
// for the whole graph.
export interface WorkGraph {
  root_work_item_id: string | null;
  items: WorkItem[];
  placements: WorkPlacement[];
  edges: WorkEdge[];
}
export interface PlanBoardRef {
  board_id: string;
  domain_id: string;
  card_component?: string;
  placement_stage?: string | null;
}
export interface WorkPlanItem {
  ref: string;
  title: string;
  kind: WorkItemKind;
  description?: string;
  primary_board: PlanBoardRef | null;
  secondary_boards?: PlanBoardRef[];
  owner?: string | null;
  priority?: string | null;
  due_at?: string | null;
}
export interface WorkPlan {
  conversation_id?: string | null;
  capture_id?: string | null;
  capture_batch_id?: string | null;
  items: WorkPlanItem[];
  edges: {
    from_ref: string; to_ref: string; relation: WorkRelation; reason?: string | null;
  }[];
}
export interface RoutableBoard {
  board_id: string;
  domain_id: string;
  title: string;
  columns: string[];
  status_mapping: Record<string, string>;
}
export interface RoutingQuestion {
  ref: string;
  question: string;
  options: string[];
}
export interface RoutingProposal {
  conversation_id: string | null;
  capture_id: string | null;
  plan: WorkPlan;
  summary: {
    item_count: number;
    placement_count: number;
    boards: string[];
    items_without_board: number;
    edge_count: number;
    warnings: string[];
  } | null;
  board_suggestions: { ref: string; board_id: string; reason: string }[];
  needs_confirmation: RoutingQuestion[];
  duplicate_candidates: {
    ref: string; existing_work_item_id: string; existing_title: string; reason: string;
  }[];
  duplicate_reports: { ref: string; report: DuplicateReport }[];
  notes: string[];
  routable_boards: RoutableBoard[];
}
export interface DuplicateEvidence {
  kind: string; detail: string; source: string;
}
export interface ExpansionDelta {
  delta_id: string;
  kind: string;
  text: string;
  proposed_target: string;
  selected: boolean;
}
export interface SubjectGroupSuggestion {
  subject_tokens: string[];
  member_work_item_ids: string[];
  member_titles: string[];
  existing_parent_id: string | null;
  existing_parent_title: string | null;
  suggested_group_title: string | null;
  detail: string;
}
export interface BoardFitSuggestion {
  board_id: string;
  matching_item_count: number;
  detail: string;
}
export type MatchClass =
  | "exact_same" | "likely_same" | "possible_same" | "repeat_occurrence"
  | "expands_existing" | "subtask_of_existing" | "parent_of_existing"
  | "same_subject_related" | "same_project_cluster" | "board_fit_only"
  | "unrelated";
export interface DuplicateFinding {
  existing_work_item_id: string;
  title: string;
  canonical_status: string;
  board_ids: string[];
  primary_board_id: string | null;
  match_class: MatchClass;
  evidence: DuplicateEvidence[];
  last_activity_at: string | null;
  completion_at: string | null;
  occurrence_count: number;
  expansion_deltas: ExpansionDelta[];
  suggested_parent_id: string | null;
  suggested_relation: string | null;
  allowed_resolutions: string[];
}
export interface DuplicateReport {
  text: string;
  normalized: string;
  findings: DuplicateFinding[];
  subject_groups: SubjectGroupSuggestion[];
  board_fit: BoardFitSuggestion[];
  semantic_backend: string;
}
export interface DuplicateResolutionResult {
  resolution: string;
  decision: { payload: Record<string, unknown> };
  linked_work_item_id?: string;
  occurrence_count?: number;
  canonical_status?: string;
  capture_status?: string;
  applied_delta_ids?: string[];
  created_children?: string[];
  created_work_item_id?: string;
  parent_work_item_id?: string;
  project_work_item_id?: string;
  member_work_item_ids?: string[];
  created_work_item_ids?: string[];
}
export const checkCaptureDuplicates = (captureId: string) =>
  postJSON<DuplicateReport>(
    `/api/captures/${encodeURIComponent(captureId)}/duplicate-check`, {});
export const checkTextDuplicates = (text: string) =>
  postJSON<DuplicateReport>("/api/work-items/duplicate-check", { text });
export const resolveCaptureDuplicate = (captureId: string, body: {
  existing_work_item_id: string;
  resolution: string;
  note?: string;
  quantity?: number;
  unit?: string;
  match_class?: string;
  evidence_kinds?: string[];
  selected_delta_ids?: string[];
  board_id?: string;
  domain_id?: string;
  group_title?: string;
  member_work_item_ids?: string[];
  capture_as_parent?: boolean;
  canonical_title?: string;
  canonical_description?: string;
  canonical_kind?: string;
  confirm_canonical_fields?: boolean;
  canonical_project_title?: string;
  canonical_project_description?: string;
  canonical_project_kind?: string;
  confirm_canonical_project?: boolean;
  canonical_children?: Record<string, {
    title: string; description: string; kind: string;
  }>;
}) => postJSON<DuplicateResolutionResult>(
  `/api/captures/${encodeURIComponent(captureId)}/resolve-duplicate`, body);
export const fetchCaptureMatches = (captureId: string) =>
  postJSON<DuplicateReport>(
    `/api/captures/${encodeURIComponent(captureId)}/matches`, {});
export const archiveCapture = (captureId: string, reason: string) =>
  postJSON<Record<string, unknown>>(
    `/api/captures/${encodeURIComponent(captureId)}/archive`, { reason });
export const fetchWorkOccurrences = (workItemId: string) =>
  getJSON<{ occurrences: { ts: string; payload: Record<string, unknown> }[];
            occurrence_count: number }>(
    `/api/work-items/${encodeURIComponent(workItemId)}/occurrences`);
export interface TaskCreationReceipt {
  work_item: {
    work_item_id: string;
    title: string;
    kind: string;
    canonical_status: string;
    primary_board_id: string | null;
  };
  links: ResourceLink[];
  warnings: string[];
}
export interface TaskBatchReceipt {
  conversation_id: string | null;
  capture_id: string | null;
  preview: boolean;
  created: TaskCreationReceipt[];
  linked_existing: TaskCreationReceipt[];
  warnings: string[];
}
export const routeWorkText = (text: string, conversationId?: string) =>
  postJSON<RoutingProposal>("/api/work-items/route", {
    text, conversation_id: conversationId ?? null,
  });
export const routeCapture = (captureId: string) =>
  postJSON<RoutingProposal>(
    `/api/captures/${encodeURIComponent(captureId)}/route`, {});
export const commitChatWork = (plan: WorkPlan) =>
  postJSON<TaskBatchReceipt>("/api/chat/work-items/commit", plan);
export const convertCaptureToWork = (captureId: string, plan: WorkPlan) =>
  postJSON<TaskBatchReceipt>(
    `/api/captures/${encodeURIComponent(captureId)}/convert`,
    { items: plan.items, edges: plan.edges, conversation_id: plan.conversation_id });
export const addWorkPlacement = (workItemId: string, board: PlanBoardRef) =>
  postJSON<WorkPlacement>(
    `/api/work-items/${encodeURIComponent(workItemId)}/placements`,
    { ...board, is_primary: true });
export const recordRoutingCorrection = (body: {
  title: string;
  ref?: string;
  suggested_board_id?: string | null;
  chosen_board_id?: string | null;
  matched_keywords?: string[];
  conversation_id?: string | null;
  capture_id?: string | null;
  source?: string;
}) => postJSON<Record<string, unknown>>("/api/routing-corrections", body);
export const getWorkGraph = () => getJSON<WorkGraph>("/api/work-graph");
export const getWorkGraphNeighbourhood = (id: string, depth = 1) =>
  getJSON<WorkGraph>(
    `/api/work-graph/${encodeURIComponent(id)}?depth=${depth}`);
export const listWorkItems = () => getJSON<WorkItem[]>("/api/work-items");
export interface WorkItemDetail {
  item: WorkItem;
  placements: WorkPlacement[];
  links: ResourceLink[];
}
export const getWorkItem = (id: string) =>
  getJSON<WorkItemDetail>(`/api/work-items/${encodeURIComponent(id)}`);
export const getWorkItemLinks = (id: string) =>
  getJSON<ResourceLink[]>(`/api/work-items/${encodeURIComponent(id)}/links`);

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
export interface AssistantRoutingCandidateView {
  assistant_id: string;
  preference: number;
  display_name: string;
  availability: string;
  unavailable_reason: string | null;
  in_catalog: boolean;
}
export interface AssistantRoutingView {
  enabled: boolean;
  default_mode: string;
  config_path: string;
  categories: {
    category_id: string;
    capability_profile: string;
    risk_ceiling: string;
    candidates: AssistantRoutingCandidateView[];
  }[];
}
export const fetchAssistantRouting = () =>
  getJSON<AssistantRoutingView>("/api/assistant-routing");

// Life Center Launch — the read-only "portal" over the service catalog joined
// with the three Life Center Kanban boards (admission/overview/operations).
// Mirrors command_center.mcp.life_center_launch.LaunchView.to_dict(); nullable
// fields are honestly nullable. See GET /api/life-center/launch.
export type LifeCenterLinkKind =
  "app" | "setup" | "docs" | "runbook" | "status" | "native";
export type LifeCenterHealthStatus = "healthy" | "attention" | "down" | "unknown";
export interface LifeCenterLink {
  kind: LifeCenterLinkKind;
  label: string;
  href: string | null;
}
export interface LifeCenterAdmission {
  lane: string;
  owner: string;
}
export interface LifeCenterHealth {
  status: LifeCenterHealthStatus;
  last_check: string | null;
  stale: boolean;
}
export interface LifeCenterSetup {
  required: boolean;
  completed: boolean;
  operations_card_id: string | null;
  evidence_refs: string;
}
export interface LifeCenterService {
  service_id: string;
  application: string;
  category: string;
  short_description: string;
  lifecycle: string;
  risk_tier: string;
  sort_order: number;
  primary_action_label: string;
  admission: LifeCenterAdmission;
  health: LifeCenterHealth;
  setup: LifeCenterSetup;
  links: LifeCenterLink[];
  service_action_ids: string[];
}
export interface LifeCenterSummary {
  total: number;
  healthy: number;
  attention: number;
  setup_pending: number;
  unknown: number;
}
export interface LifeCenterLaunch {
  schema_version: string;
  generated_at: string;
  catalog_digest: string;
  status_generated_at: string | null;
  status_stale: boolean;
  summary: LifeCenterSummary;
  global_action_ids: string[];
  services: LifeCenterService[];
}
export interface LifeCenterRunbook {
  service_id: string;
  runbook_path: string;
  content: string;
}
// The dispatch result is rendered honestly: `status` may be "error"/"rejected"
// (e.g. Docker-CLI-dependent actions in the containerized cockpit) — never
// assume success. `result` is an opaque object, `error` a human-readable string.
export interface LifeCenterDispatchResult {
  action_id: string;
  request_id: string;
  status: "ok" | "error" | "rejected" | string;
  result: Record<string, unknown>;
  error: string | null;
}
export const fetchLifeCenterLaunch = () =>
  getJSON<LifeCenterLaunch>("/api/life-center/launch");
export const fetchLifeCenterService = (serviceId: string) =>
  getJSON<LifeCenterService>(
    `/api/life-center/services/${encodeURIComponent(serviceId)}`);
export const fetchLifeCenterRunbook = (serviceId: string) =>
  getJSON<LifeCenterRunbook>(
    `/api/life-center/services/${encodeURIComponent(serviceId)}/runbook`);
export const dispatchLifeCenterAction = (body: {
  action_id: string;
  service_id?: string;
  idempotency_key?: string;
  parameters?: Record<string, unknown>;
}) => postJSON<LifeCenterDispatchResult>(
  "/api/life-center/actions/dispatch", body);
