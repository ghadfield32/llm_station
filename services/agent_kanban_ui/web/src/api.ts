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

export interface Status { hops: Record<string, string>; }
export const fetchStatus = () => getJSON<Status>("/api/status");

export interface ChatEvent { type: string; [k: string]: unknown; }

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
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


