import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addDomainCardNote,
  Activity, AppFlowyBoard, BoardCard, BoardData, BoardSnapshot, ChatEvent,
  BoardRegistry, BoardRegistryBoard,
  ChatRuntime, DomainActions, DomainCard, DomainCardDetail, DomainCardProgress,
  DomainCards, DomainSchema, DomainSpec,
  FieldSpec, JobProfileControls,
  createDomainSchema, deleteDomainSchema,
  fetchBoardRegistry,
  MissionDetail, MissionEvent, Metrics, ModelLanes, Status, UIConfig, fetchActivity,
  fetchBoards, fetchBoardsLive, fetchChatRuntime, fetchConfig, fetchDomainActions,
  fetchChatThreads, fetchChatTranscript, ChatTranscriptResponse, TranscriptTurn,
  ChatConversation, fetchChatConversations, deleteChatConversation,
  fetchDomainCard, fetchDomainCardProgress, fetchDomainCards, fetchDomains,
  fetchJobPacket, JobPacket, JobStoryEntry, PacketValidation, AgentTraceEntry,
  requestPacketChanges, submitJobApplication, updateJobPacketFile,
  fetchDomainSchema, fetchJobProfileControls, fetchMetrics, fetchMission, fetchMissions, fetchModels,
  fetchRepoChatContext, registerRepo, RepoRegisterResult,
  fetchRuntimeDebug, fetchStatus, moveDomainCard, postAction, RuntimeDebug, streamChat,
  saveChatThread, updateDomainSchema, updateDraftDefault, updateJobSearchCategory, updateJobSearchRuntime,
  StandingAnswer, updateStandingAnswer, removeJobSearchCategory,
  reclassifyJobApplications, ReclassifyResult, bulkSelectSuggested,
} from "./api";

type View = "missions" | "boards" | "domains" | "settings" | "router" | "diagnostics" | "observability" | "activity" | "chat";
const NAV: { id: View; label: string }[] = [
  { id: "domains", label: "All Boards" },
  { id: "settings", label: "Controls" },
  { id: "router", label: "Router" },
  { id: "diagnostics", label: "Status" },
  { id: "observability", label: "Metrics" },
  { id: "activity", label: "Activity" },
];
const VIEW_IDS: ReadonlySet<string> = new Set([
  ...NAV.map((n) => n.id),
  "missions",
  "boards",
  "chat",
]);
type DomainNavItem = {
  id: string;
  title: string;
  count: number;
  origin?: string;
  error?: string;
};
type JobBoardMode = "bot" | "manual" | "all";
const RISK_CLASS: Record<string, string> = {
  L0: "risk-l0", L1: "risk-l1", L2: "risk-l2", L3: "risk-l3", L4: "risk-l4",
};
const POLL_MS = 5000;

const pct = (x: number | null) => (x === null ? "—" : `${(x * 100).toFixed(0)}%`);
const matches = (q: string, ...parts: (string | undefined)[]) =>
  !q || parts.filter(Boolean).join(" ").toLowerCase().includes(q.toLowerCase());
const WALL_VERBS = new Set(["approve", "approve_card", "merge", "deploy", "delete", "delete_card", "delete_board"]);

function initialViewFromUrl(): View {
  const value = new URLSearchParams(window.location.search).get("view");
  return value && VIEW_IDS.has(value) ? value as View : "domains";
}

function initialDomainFromUrl(): string {
  return new URLSearchParams(window.location.search).get("domain") || "job_application";
}

// ---- filter bar (shared) --------------------------------------------------
function FilterBar({
  q, setQ, risk, setRisk, risks,
}: {
  q: string; setQ: (s: string) => void;
  risk: string; setRisk: (s: string) => void; risks: boolean;
}) {
  return (
    <div className="filterbar">
      <input className="search" placeholder="filter…" value={q}
        onChange={(e) => setQ(e.target.value)} />
      {risks && (
        <select className="select" value={risk} onChange={(e) => setRisk(e.target.value)}>
          <option value="">any risk</option>
          {["L0", "L1", "L2", "L3", "L4"].map((r) => <option key={r}>{r}</option>)}
        </select>
      )}
      {(q || risk) && <button className="clear" onClick={() => { setQ(""); setRisk(""); }}>clear</button>}
    </div>
  );
}

function HorizontalScroller({ className, children, ariaLabel }: {
  className: string; children: ReactNode; ariaLabel?: string;
}) {
  const topRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const innerRef = useRef<HTMLDivElement | null>(null);
  const [scrollWidth, setScrollWidth] = useState(0);
  const syncing = useRef(false);
  const syncWidth = useCallback(() => {
    const next = Math.max(
      contentRef.current?.scrollWidth ?? 0,
      innerRef.current?.scrollWidth ?? 0,
    );
    setScrollWidth((prev) => (prev === next ? prev : next));
  }, []);
  useEffect(() => { syncWidth(); });
  useEffect(() => {
    syncWidth();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(syncWidth) : null;
    if (ro && contentRef.current) ro.observe(contentRef.current);
    if (ro && innerRef.current) ro.observe(innerRef.current);
    window.addEventListener("resize", syncWidth);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", syncWidth);
    };
  }, [syncWidth]);
  // Touch devices scroll the content natively (buttery momentum). The dual
  // top-scrollbar sync below WRITES scrollLeft on every scroll event, which
  // interrupts iOS momentum and is the "super sticky" feel — so it is a
  // POINTER-FINE (mouse/trackpad) affordance only. `coarse` is read once.
  const coarse = useRef(
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      && window.matchMedia("(pointer: coarse)").matches);
  function syncFromTop() {
    if (coarse.current || syncing.current || !topRef.current || !contentRef.current) return;
    syncing.current = true;
    contentRef.current.scrollLeft = topRef.current.scrollLeft;
    syncing.current = false;
  }
  function syncFromContent() {
    if (coarse.current || syncing.current || !topRef.current || !contentRef.current) return;
    syncing.current = true;
    topRef.current.scrollLeft = contentRef.current.scrollLeft;
    syncing.current = false;
  }
  // Mouse-wheel → horizontal scroll: a wide board (8 job lanes) or a long tab
  // strip only scrolled via the scrollbar/trackpad before. A native
  // non-passive listener is required to preventDefault; React's onWheel is
  // passive. Vertical scrolling INSIDE a column body is respected until it
  // hits its top/bottom edge, then the wheel moves the board sideways. Skipped
  // on touch (native momentum handles it).
  useEffect(() => {
    const el = contentRef.current;
    if (!el || coarse.current) return;
    const onWheel = (e: WheelEvent) => {
      if (el.scrollWidth <= el.clientWidth + 1) return;       // nothing to scroll
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;    // already horizontal
      const col = (e.target as HTMLElement).closest?.(
        ".domain-column-body, .column-body") as HTMLElement | null;
      if (col && col.scrollHeight > col.clientHeight + 1) {
        const up = e.deltaY < 0;
        const atTop = col.scrollTop <= 0;
        const atBottom = col.scrollTop + col.clientHeight >= col.scrollHeight - 1;
        if (!((atTop && up) || (atBottom && !up))) return;    // let the column scroll
      }
      el.scrollLeft += e.deltaY;
      e.preventDefault();
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);
  return (
    <div className="scrollframe">
      <div className="top-scrollbar" ref={topRef} onScroll={syncFromTop} aria-hidden="true">
        <div style={{ width: scrollWidth, height: 1 }} />
      </div>
      <div className={`${className} scrollframe-content`} ref={contentRef}
        onScroll={syncFromContent} aria-label={ariaLabel}>
        <div className="scrollframe-inner" ref={innerRef}>{children}</div>
      </div>
    </div>
  );
}

// ---- missions view --------------------------------------------------------
function MissionsView({ data, onOpen }: { data: BoardData; onOpen: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [risk, setRisk] = useState("");
  const columns = useMemo(() => data.columns.map((col) => ({
    ...col,
    cards: col.cards.filter((c) =>
      matches(q, c.id, c.action, c.repo) && (!risk || c.risk === risk)),
  })), [data, q, risk]);
  const shown = columns.reduce((n, c) => n + c.cards.length, 0);
  return (
    <>
      <FilterBar q={q} setQ={setQ} risk={risk} setRisk={setRisk} risks />
      <div className="muted small">{shown} of {data.total} missions · gated execution lane —
        open one to approve / kill in the Ledger (to move work freely, use the Boards → mission_intake cards)</div>
      <HorizontalScroller className="board">
        {columns.filter((c) => c.cards.length).map((col) => (
          <div className="column" key={col.name}>
            <div className="column-head">
              <span className={`dot status-${col.name}`} />{col.name}
              <span className="count">{col.cards.length}</span>
            </div>
            <div className="column-body">
              {col.cards.map((c) => (
                <div className="card card-click" key={c.id} onClick={() => onOpen(c.id)}>
                  <div className="card-top">
                    <span className="card-id">{c.id}</span>
                    <span className={`risk ${RISK_CLASS[c.risk] ?? ""}`}>{c.risk || "—"}</span>
                  </div>
                  <div className="card-action">{c.action || "(no description)"}</div>
                  {c.repo && <div className="card-repo">{c.repo}</div>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </HorizontalScroller>
    </>
  );
}

// ---- AppFlowy boards view -------------------------------------------------
function BoardsView({ snap, canAct, onOpenCard, onMoved }: {
  snap: BoardSnapshot; canAct: boolean;
  onOpenCard: (board: string, c: BoardCard, statuses: string[]) => void;
  onMoved: () => void;
}) {
  const [active, setActive] = useState(snap.boards[0]?.board ?? "");
  const [q, setQ] = useState("");
  const [dragged, setDragged] = useState<string | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const board: AppFlowyBoard | undefined =
    snap.boards.find((b) => b.board === active) ?? snap.boards[0];
  // ALL legal columns (so you can drop into an empty target too), each filtered.
  const columns = (board?.statuses ?? []).map((name) => ({
    name,
    cards: (board?.columns?.find((c) => c.name === name)?.cards ?? [])
      .filter((c) => matches(q, c.title, c.meta)),
  }));

  async function moveBoardCard(title: string, status: string) {
    if (!board || !title || !status) return;
    setToast(null);
    try {
      const r = await postAction("move_item",
        { database: board.board, title, status });
      setToast(r.result);          // governed result (e.g. Approved → refusal)
      onMoved();
    } catch (e) { setToast("⚠ " + (e as Error).message); }
  }

  async function drop(status: string) {
    const title = dragged;
    setOverCol(null); setDragged(null);
    if (!title) return;
    await moveBoardCard(title, status);
  }

  return (
    <>
      <HorizontalScroller className="tabs tabs-strip" ariaLabel="AppFlowy boards">
        {snap.boards.map((b) => (
          <button key={b.board} className={`tab ${b.board === active ? "tab-on" : ""}`}
            onClick={() => setActive(b.board)}>{b.board}{b.error ? " ⚠" : ""}</button>
        ))}
        <span className="snap-time">
          {snap.generated_at.slice(0, 19)}{snap.live ? " · live" : " · snapshot"}
        </span>
      </HorizontalScroller>
      <FilterBar q={q} setQ={setQ} risk="" setRisk={() => {}} risks={false} />
      {canAct && <div className="muted small">drag a card between columns, or use the Move to menu on touch screens</div>}
      {toast && <div className="actmsg">{toast}</div>}
      {!board ? <div className="empty">No boards.</div>
        : board.error ? <div className="error">⚠ {board.board}: {board.error}</div>
        : (
          <HorizontalScroller className="board">
            {columns.map((col) => (
              <div className={`column ${overCol === col.name ? "col-over" : ""}`} key={col.name}
                onDragOver={(e) => { if (canAct && dragged) { e.preventDefault(); setOverCol(col.name); } }}
                onDragLeave={() => setOverCol((c) => (c === col.name ? null : c))}
                onDrop={() => drop(col.name)}>
                <div className="column-head">
                  <span className={`dot status-${col.name}`} />{col.name}
                  <span className="count">{col.cards.length}</span>
                </div>
                <div className="column-body">
                  {col.cards.map((c, i) => (
                    <div className={`card card-click ${canAct ? "draggable" : ""}`}
                      key={`${c.title}-${i}`} draggable={canAct}
                      onDragStart={() => setDragged(c.title)}
                      onDragEnd={() => { setDragged(null); setOverCol(null); }}
                      onClick={() => onOpenCard(board.board, c, board.statuses ?? [])}>
                      <div className="card-action">{c.title || "(untitled)"}</div>
                      {c.meta && <div className="card-repo">{c.meta}</div>}
                      {canAct && (board.statuses ?? []).length > 0 && (
                        <select className="touch-move" aria-label={`Move ${c.title} to column`}
                          value=""
                          onPointerDown={(e) => e.stopPropagation()}
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => e.stopPropagation()}
                          onChange={(e) => {
                            const target = e.target.value;
                            if (target) void moveBoardCard(c.title, target);
                          }}>
                          <option value="">Move to...</option>
                          {(board.statuses ?? []).filter((s) => s !== col.name)
                            .map((s) => <option key={s}>{s}</option>)}
                        </select>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </HorizontalScroller>
        )}
    </>
  );
}

// ---- router view ----------------------------------------------------------
function RouterView({ lanes }: { lanes: ModelLanes }) {
  return (
    <div className="router">
      <p className="muted small">How a request reaches a model — local roles (ranked candidates),
        coding executors, and the judge stages. Per-mission routing is in each mission's drawer.</p>
      <h3>Model roles → ranked local candidates</h3>
      {lanes.roles.map((r) => (
        <div className="lane" key={r.role}>
          <div className="lane-name">{r.role}</div>
          <div className="lane-cands">
            {r.candidates.sort((a, b) => a.priority - b.priority).map((c) => (
              <span className="chip" key={c.alias} title={c.model}>
                <b>#{c.priority}</b> {c.alias}
                {c.canary_weight > 0 && <em> canary {Math.round(c.canary_weight * 100)}%</em>}
              </span>
            ))}
          </div>
        </div>
      ))}
      {lanes.executors.length > 0 && (
        <>
          <h3>Coding executors</h3>
          <div className="lane-cands">
            {lanes.executors.sort((a, b) => a.priority - b.priority).map((e) => (
              <span className="chip" key={e.name}><b>#{e.priority}</b> {e.name} <em>{e.family}</em></span>
            ))}
          </div>
        </>
      )}
      {lanes.judge_stages.length > 0 && (
        <>
          <h3>Judge stages</h3>
          <div className="stages">
            {lanes.judge_stages.map((s) => (
              <div className="stage" key={s.stage}>
                <div className="stage-name">{s.stage}</div>
                <div className="stage-judges">{s.judges.join(" · ") || "—"}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---- observability view ---------------------------------------------------
function ObservabilityView({ m }: { m: Metrics }) {
  return (
    <>
      <div className="metrics-row">
        <Metric label="tool calls" value={`${m.total_calls}`} />
        <Metric label="error rate" value={pct(m.error_rate)} />
        <Metric label="redundant calls" value={pct(m.redundant_rate)}
          hint="Consecutive identical calls — board re-injection should drive this down." />
        <Metric label="intent-verb adoption" value={pct(m.intent_verb_share)}
          hint={`${m.intent_verb_calls} verb vs ${m.generic_mutator_calls} generic set_status`} />
      </div>
      {m.per_tool.length > 0 && (
        <table className="tool-table">
          <thead><tr><th>tool</th><th>calls</th><th>err%</th><th>p50 ms</th></tr></thead>
          <tbody>
            {m.per_tool.map((t) => (
              <tr key={t.tool}>
                <td>{t.tool}</td><td>{t.calls}</td>
                <td>{(t.error_rate * 100).toFixed(0)}%</td><td>{t.p50_ms}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="obs-foot">source: {m.log_file}</div>
    </>
  );
}
function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metric" title={hint}>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

// ---- activity view --------------------------------------------------------
function ActivityView({ a }: { a: Activity }) {
  const [q, setQ] = useState("");
  const calls = a.calls.filter((c) => matches(q, c.tool, c.surface, c.detail));
  if (a.calls.length === 0) return <div className="empty">No agent activity logged yet.</div>;
  return (
    <>
      <FilterBar q={q} setQ={setQ} risk="" setRisk={() => {}} risks={false} />
      <div className="activity">
        {calls.map((c, i) => (
          <div className="act-row" key={`${c.ts}-${i}`}>
            <span className={`act-dot ${c.ok ? "ok" : "bad"}`} />
            <span className="act-time">{(c.ts ?? "").slice(11, 19)}</span>
            <span className="act-surface">{c.surface}</span>
            <span className="act-tool">{c.tool}</span>
            {!c.ok && <span className="act-detail">{c.detail}</span>}
            <span className="act-ms">{Math.round(c.ms)}ms</span>
          </div>
        ))}
      </div>
    </>
  );
}

// ---- diagnostics view -----------------------------------------------------
function ProbePill({ ok }: { ok: boolean }) {
  return <span className={`status-pill ${ok ? "pill-ok" : "pill-bad"}`}>{ok ? "ok" : "error"}</span>;
}

function DiagnosticsView({ debug, surfaceErrors, boardsNote, lanesNote }: {
  debug: RuntimeDebug | null;
  surfaceErrors: Record<string, string>;
  boardsNote: string | null;
  lanesNote: string | null;
}) {
  if (!debug) return <div className="loading">...</div>;
  const failures = [
    ...Object.entries(surfaceErrors).map(([name, msg]) => ({ name, msg })),
    ...(boardsNote ? [{ name: "boards", msg: boardsNote }] : []),
    ...(lanesNote ? [{ name: "router", msg: lanesNote }] : []),
  ];
  return (
    <div className="diagnostics">
      <div className="diag-grid">
        <div className="metric diag-card">
          <div className="diag-head">Ledger</div>
          <div className="diag-row"><span>base URL</span><code>{debug.ledger.base_url}</code></div>
          <div className="diag-row"><span>DNS</span><ProbePill ok={debug.ledger.dns.ok} /></div>
          {!debug.ledger.dns.ok && <div className="diag-error">{debug.ledger.dns.error}</div>}
          <div className="diag-row"><span>health</span><ProbePill ok={debug.ledger.health.ok} /></div>
          {!debug.ledger.health.ok && <div className="diag-error">{debug.ledger.health.error}</div>}
          <div className="muted small">{debug.ledger.host_run_hint}</div>
        </div>
        <div className="metric diag-card">
          <div className="diag-head">Mode</div>
          <div className="diag-row"><span>chat/writes</span>
            <span className={`status-pill ${debug.mode.chat_enabled ? "pill-run" : ""}`}>
              {debug.mode.chat_enabled ? "enabled" : "read-only"}
            </span>
          </div>
          <div className="diag-row"><span>cwd</span><code>{debug.mode.cwd}</code></div>
        </div>
      </div>
      <h3>Mounted paths</h3>
      <div className="diag-table">
        {Object.entries(debug.paths).map(([name, info]) => (
          <div className="diag-row" key={name}>
            <span>{name}</span>
            <ProbePill ok={info.exists} />
            <code>{info.path}</code>
          </div>
        ))}
      </div>
      <h3>Surface failures</h3>
      {failures.length === 0 ? <div className="empty">No surface failures in the last refresh.</div>
        : failures.map((f) => <div className="error" key={f.name}>{f.name}: {f.msg}</div>)}
    </div>
  );
}

// ---- typed domain surfaces ------------------------------------------------
function valText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(valText).filter(Boolean).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function valList(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(valText).filter(Boolean);
  const s = valText(v);
  return s ? [s] : [];
}
function valNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function cardId(card: DomainCard): string {
  return valText(card.card_id ?? card.id ?? card.title ?? card.role_title ?? card.dag_id ?? card.repo_id);
}
function dateText(v: unknown): string {
  const s = valText(v);
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString([], {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}
function scoreTone(n: number | null): string {
  if (n === null) return "score-gray";
  if (n >= 85) return "score-green";
  if (n >= 70) return "score-amber";
  return "score-gray";
}
function statusClass(status: string): string {
  const s = status.toLowerCase();
  if (["done", "completed", "healthy", "success", "active", "green"].some((x) => s.includes(x))) return "pill-ok";
  if (["blocked", "failed", "rejected", "skip", "broken", "overdue"].some((x) => s.includes(x))) return "pill-bad";
  if (["running", "progress", "queue", "selected", "interview"].some((x) => s.includes(x))) return "pill-run";
  if (["manual", "needs", "draft", "backlog"].some((x) => s.includes(x))) return "pill-warn";
  return "";
}
function statusToken(status: string): string {
  return status.replace(/[^A-Za-z0-9_-]+/g, "-");
}
function titleToken(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
function domainTitle(card: DomainCard, spec: DomainSpec): string {
  switch (spec.card_component) {
    case "job_application":
      return [card.company, card.role_title].map(valText).filter(Boolean).join(" - ") || cardId(card);
    case "linkedin_post": return valText(card.hook || card.account || cardId(card));
    case "book": return valText(card.title || cardId(card));
    case "paper": return valText(card.title || cardId(card));
    case "repo": return valText(card.repo_id || cardId(card));
    case "dag": return valText(card.dag_id || cardId(card));
    case "machine_upkeep": return valText(card.task || cardId(card));
    case "mission": return valText(card.action || cardId(card));
    default: return valText(card.title || card.task || cardId(card));
  }
}
function cardMatchesDomain(card: DomainCard, q: string, status: string): boolean {
  const cardStatus = valText(card.status);
  if (status && cardStatus !== status) return false;
  if (!q) return true;
  const hay = Object.values(card).map(valText).join(" ").toLowerCase();
  return hay.includes(q.toLowerCase());
}
function domainActionParams(action: string, title: string): Record<string, unknown> {
  if (["start_todo", "finish_todo", "block_todo"].includes(action)) return { task: title };
  return { title };
}
function StatusPill({ value }: { value: unknown }) {
  const s = valText(value);
  if (!s) return null;
  return <span className={`status-pill ${statusClass(s)}`}>{s}</span>;
}
function Badge({ value, tone = "" }: { value: unknown; tone?: string }) {
  const s = valText(value);
  if (!s) return null;
  return <span className={`domain-badge ${tone}`}>{s}</span>;
}
function ScoreChip({ value }: { value: unknown }) {
  const n = valNumber(value);
  return <span className={`score-chip ${scoreTone(n)}`}>{n === null ? "-" : n}</span>;
}
function ProgressBar({ value }: { value: unknown }) {
  const n = Math.max(0, Math.min(100, valNumber(value) ?? 0));
  return <div className="progress-wrap"><span style={{ width: `${n}%` }} /><em>{n}%</em></div>;
}
function ChipList({ values }: { values: unknown }) {
  const list = valList(values);
  if (!list.length) return null;
  return <div className="chip-list">{list.map((x, i) => <span className="chip" key={`${x}-${i}`}>{x}</span>)}</div>;
}
function FieldValue({ field, value }: { field: FieldSpec; value: unknown }) {
  const kind = field.kind ?? "text";
  if (kind === "badge") return <Badge value={value} />;
  if (kind === "score") return <ScoreChip value={value} />;
  if (kind === "progress") return <ProgressBar value={value} />;
  if (kind === "list") return <ChipList values={value} />;
  if (kind === "datetime") return <span>{dateText(value) || "-"}</span>;
  if (kind === "url") {
    const href = valText(value);
    return href ? <a href={href} target="_blank" rel="noreferrer">{href}</a> : <span>-</span>;
  }
  if (kind === "markdown") return <MarkdownText value={value} />;
  return <span>{valText(value) || "-"}</span>;
}
function MarkdownText({ value }: { value: unknown }) {
  const text = valText(value);
  if (!text) return <span className="muted">-</span>;
  return (
    <div className="md-lite">
      {text.split(/\n\s*\n/).map((block, i) => {
        const lines = block.split(/\n/).map((x) => x.trim()).filter(Boolean);
        if (lines.length && lines.every((x) => x.startsWith("- "))) {
          return <ul key={i}>{lines.map((x, j) => <li key={j}>{x.slice(2)}</li>)}</ul>;
        }
        return <p key={i}>{block}</p>;
      })}
    </div>
  );
}

// Inline markdown: **bold**, `code`, and *italic* → JSX, so a resume/cover
// letter reads like a real document instead of raw asterisks.
function renderInline(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0; let m: RegExpExecArray | null; let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<strong key={k++}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) parts.push(<code key={k++}>{tok.slice(1, -1)}</code>);
    else parts.push(<em key={k++}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

// A polished document view for the employer-facing packet files (resume,
// cover letter, answers). Renders headings, bullets, and the contact/skills
// lines as a clean paper-like layout — this is what "nicely formatted" means
// for review: it should read the way a hiring manager will see it.
function DocumentView({ text, kind = "doc" }: { text: string; kind?: string }) {
  if (!text.trim()) return <div className="muted">not generated for this packet</div>;
  const lines = text.replace(/\r/g, "").split("\n");
  const out: React.ReactNode[] = [];
  let bullets: string[] = [];
  let key = 0;
  const flush = () => {
    if (bullets.length) {
      out.push(<ul key={key++} className="doc-bullets">
        {bullets.map((b, i) => <li key={i}>{renderInline(b)}</li>)}</ul>);
      bullets = [];
    }
  };
  // everything above the first "## " section in a resume is the header block
  // (name, contact lines, role headline) — grouped and centered like a real
  // resume. headerCount tracks OUTPUT nodes, not line indices, so bullets or
  // blank lines can't desync the split.
  const firstSection = lines.findIndex((l) => l.trim().startsWith("## "));
  const headerEndLine = kind === "resume" && firstSection > 0 ? firstSection : 0;
  let headerCount = 0;
  lines.forEach((raw, idx) => {
    const line = raw.trimEnd();
    const t = line.trim();
    if (!t) { flush(); return; }
    if (t.startsWith("## ")) { flush(); out.push(<h4 key={key++} className="doc-h2">{renderInline(t.slice(3))}</h4>); return; }
    if (t.startsWith("# ")) {
      flush(); out.push(<h3 key={key++} className="doc-name">{renderInline(t.slice(2))}</h3>);
      if (idx < headerEndLine) headerCount = out.length;
      return;
    }
    if (/^[-*•]\s+/.test(t)) { bullets.push(t.replace(/^[-*•]\s+/, "")); return; }
    flush();
    if (idx < headerEndLine) {
      // contact lines carry an email / phone / URL; the role headline (often
      // pipe-delimited too) has none of those, so classify by content
      const isContact = /@|https?:|\.com|\.io|\d{3}[.\s-]?\d{3}/.test(t);
      out.push(<p key={key++} className={isContact ? "doc-contact" : "doc-headline"}>
        {renderInline(t)}</p>);
      headerCount = out.length;
      return;
    }
    out.push(<p key={key++} className="doc-p">{renderInline(t)}</p>);
  });
  flush();
  return (
    <div className={`document-view document-${kind}`}>
      {headerCount > 0
        ? <><div className="doc-header">{out.slice(0, headerCount)}</div>{out.slice(headerCount)}</>
        : out}
    </div>
  );
}

function LinkedInBody({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/).filter(Boolean);
  return (
    <div className="li-body">
      {blocks.map((block, i) => {
        const lines = block.split(/\n/).map((x) => x.trim()).filter(Boolean);
        if (lines.length && lines.every((x) => x.startsWith("- "))) {
          return <ul key={i}>{lines.map((x, j) => <li key={j}>{x.slice(2)}</li>)}</ul>;
        }
        return <p key={i}>{i === 0 ? <b>{block}</b> : block}</p>;
      })}
    </div>
  );
}
function LinkedInPreview({ card, mobile = false }: { card: DomainCard; mobile?: boolean }) {
  const name = valText(card.author_name || card.account || "Geoff Hadfield");
  const initials = name.split(/\s+/).slice(0, 2).map((x) => x[0]).join("").toUpperCase();
  return (
    <div className={`li-card ${mobile ? "li-mobile" : ""}`}>
      <div className="li-head">
        <div className="li-avatar">{initials || "GH"}</div>
        <div>
          <div className="li-name">{name}</div>
          <div className="li-line">{valText(card.author_headline || card.account)}</div>
          <div className="li-meta">1h · Public</div>
        </div>
      </div>
      <LinkedInBody text={valText(card.body || card.hook)} />
      <div className="li-tags">{valList(card.tags).map((t) => <span key={t}>{t}</span>)}</div>
      <div className="li-foot"><span>Like</span><span>Comment</span><span>Repost</span><span>Send</span></div>
    </div>
  );
}

function JobApplicationCard({ card }: { card: DomainCard }) {
  const manualReason = valText(card.manual_reason);
  const automationClass = valText(card.automation_class);
  const handoffReason = automationClass === "bot_possible" && manualReason.includes("MVP submit path is disabled")
    ? "Bot-prepared handoff: the packet is ready, but automatic submit is disabled. Geoff can take over, submit, then move this to Completed."
    : manualReason;
  const nextAction = valText(card.next_action);
  return (
    <div className="job-card domain-card-body">
      <div className="domain-card-top">
        <div>
          <div className="domain-title">{valText(card.company) || "Unknown company"}</div>
          <div className="domain-subtitle">{valText(card.role_title) || "Untitled role"}</div>
        </div>
        <ScoreChip value={card.fit_score} />
      </div>
      <div className="domain-meta-row">
        <span>{valText(card.salary_text) || "salary not listed"}</span>
        <StatusPill value={card.status} />
      </div>
      <div className="domain-badges">
        <Badge value={card.automation_class} />
        <Badge value={card.resume_variant} />
      </div>
      {handoffReason && <div className="job-card-note">{handoffReason}</div>}
      {nextAction && <div className="job-card-next">{nextAction}</div>}
    </div>
  );
}
function BookCard({ card }: { card: DomainCard }) {
  return (
    <div className="domain-card-body">
      <div className="domain-title">{valText(card.title)}</div>
      <div className="domain-subtitle">{valText(card.author)}</div>
      <ProgressBar value={card.progress} />
      <ChipList values={card.tags} />
      <StatusPill value={card.status} />
    </div>
  );
}
function PaperCard({ card }: { card: DomainCard }) {
  return (
    <div className="domain-card-body">
      <div className="domain-title">{valText(card.title)}</div>
      <div className="domain-badges"><Badge value={card.venue} /><Badge value={card.year} /><Badge value={card.useful_for} /></div>
      <div className="domain-clamp">{valText(card.abstract)}</div>
      <StatusPill value={card.status} />
    </div>
  );
}
function RepoCard({ card }: { card: DomainCard }) {
  const blockers = valList(card.blockers);
  return (
    <div className="domain-card-body">
      <div className="domain-title">{valText(card.repo_id)}</div>
      <div className="domain-badges">
        <Badge value={card.branch} />
        <Badge value={card.autonomy} tone={valText(card.autonomy) === "enabled" ? "good" : ""} />
        <Badge value={card.checks} tone={valText(card.checks) === "green" ? "good" : ""} />
        <Badge value={`${valText(card.open_prs) || 0} PRs`} />
      </div>
      {blockers.length > 0 && <ul className="blockers">{blockers.map((b) => <li key={b}>{b}</li>)}</ul>}
      <StatusPill value={card.status} />
    </div>
  );
}
function DagCard({ card }: { card: DomainCard }) {
  const state = valText(card.state);
  const tone = state === "success" ? "good" : state === "failed" ? "bad" : state === "running" ? "run" : "";
  return (
    <div className="domain-card-body">
      <div className="domain-title">{valText(card.dag_id)}</div>
      <div className="domain-badges"><Badge value={state} tone={tone} /><Badge value={card.owner} /></div>
      <div className="domain-kv">last <b>{dateText(card.last_run) || "-"}</b></div>
      <div className="domain-kv">next <b>{dateText(card.next_run) || "-"}</b></div>
      <StatusPill value={card.status} />
    </div>
  );
}
function MachineUpkeepCard({ card }: { card: DomainCard }) {
  const n = valList(card.checklist).length;
  return (
    <div className="domain-card-body">
      <div className="domain-title">{valText(card.task)}</div>
      <div className="domain-badges"><Badge value={card.cadence} /><Badge value={card.health} tone={valText(card.health) === "ok" ? "good" : "bad"} /></div>
      <div className="domain-kv">{n} checks · last {dateText(card.last_done) || "-"}</div>
      <StatusPill value={card.status} />
    </div>
  );
}
function MissionDomainCard({ card }: { card: DomainCard }) {
  const risk = valText(card.risk);
  return (
    <div className="domain-card-body">
      <div className="domain-title clamp-2">{valText(card.action)}</div>
      <div className="domain-badges"><Badge value={card.repo} /><Badge value={risk} tone={risk === "L4" ? "bad" : risk === "L3" ? "warn" : ""} /></div>
      <div className="domain-kv">{dateText(card.created_at)}</div>
      <StatusPill value={card.status} />
    </div>
  );
}
function GenericTaskCard({ card }: { card: DomainCard }) {
  const due = valText(card.due);
  const overdue = due && new Date(due).getTime() < Date.now();
  return (
    <div className="domain-card-body">
      <div className="domain-title">{valText(card.title || card.task)}</div>
      <div className="domain-badges">
        <Badge value={card.priority} />
        <Badge value={dateText(card.due)} tone={overdue ? "bad" : ""} />
      </div>
      <StatusPill value={card.status} />
    </div>
  );
}
function DomainCardTile({
  spec, card, onOpen, canDrag = false, onDragStart, moveTargets = [], onMove, onOpenPacket,
}: {
  spec: DomainSpec; card: DomainCard; onOpen: () => void;
  canDrag?: boolean; onDragStart?: () => void;
  moveTargets?: string[]; onMove?: (status: string) => void;
  onOpenPacket?: () => void;
}) {
  let body: ReactNode;
  switch (spec.card_component) {
    case "job_application": body = <JobApplicationCard card={card} />; break;
    case "linkedin_post": body = <LinkedInPreview card={card} />; break;
    case "book": body = <BookCard card={card} />; break;
    case "paper": body = <PaperCard card={card} />; break;
    case "repo": body = <RepoCard card={card} />; break;
    case "dag": body = <DagCard card={card} />; break;
    case "machine_upkeep": body = <MachineUpkeepCard card={card} />; break;
    case "mission": body = <MissionDomainCard card={card} />; break;
    default: body = <GenericTaskCard card={card} />; break;
  }
  return (
    <div className={`domain-card ${canDrag ? "draggable" : ""}`} role="button"
      tabIndex={0} draggable={canDrag}
      onDragStart={(e) => { if (canDrag) { e.dataTransfer.effectAllowed = "move"; onDragStart?.(); } }}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(); }}>
      {body}
      {onOpenPacket && (
        <button className="actbtn card-packet-btn"
          title="open the application packet: resume, cover letter, story, approve & submit"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); onOpenPacket(); }}>
          review packet
        </button>
      )}
      {moveTargets.length > 0 && (
        <div className="move-buttons" onPointerDown={(e) => e.stopPropagation()}>
          {moveTargets.map((s, i) => (
            <button key={s} className={`move-btn ${i === 0 ? "move-fwd" : "move-back"}`}
              onClick={(e) => { e.stopPropagation(); onMove?.(s); }}
              title={`Move to ${s}`}>
              {i === 0 ? "→ " : ""}{s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
function DomainEmpty({ spec }: { spec: DomainSpec }) {
  return (
    <div className="domain-empty">
      <div className="domain-empty-mark" />
      <h3>{spec.empty_state.title}</h3>
      <p>{spec.empty_state.hint}</p>
      {spec.empty_state.command && <code>{spec.empty_state.command}</code>}
    </div>
  );
}

function DraftDefaultRow({ name, value, writable, onSaved }: {
  name: string; value: string; writable: boolean; onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateDraftDefault(name, draft);
      setEditing(false);
      onSaved();
      setMsg("updated");
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="preset-row">
      <div className="preset-row-head">
        <code>{name}</code>
        {writable && !editing && <button className="editbtn" onClick={() => setEditing(true)}>edit</button>}
      </div>
      {editing ? (
        <>
          <textarea value={draft} disabled={busy}
            onChange={(e) => setDraft(e.target.value)} />
          <div className="preset-actions">
            <button className="actbtn" disabled={busy} onClick={save}>save</button>
            <button className="clear" disabled={busy} onClick={() => { setDraft(value); setEditing(false); }}>cancel</button>
          </div>
        </>
      ) : <p>{value}</p>}
      {msg && <div className={msg === "updated" ? "actmsg" : "error"}>{msg}</div>}
    </div>
  );
}

function StandingAnswerRow({ row, writable, onSaved }: {
  row: StandingAnswer; writable: boolean; onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(row.answer);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateStandingAnswer({ topic: row.topic, answer: draft });
      setEditing(false); onSaved(); setMsg("updated");
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="preset-row">
      <div className="preset-row-head">
        <b>{row.question ?? row.topic}</b>
        {writable && !editing &&
          <button className="editbtn" onClick={() => setEditing(true)}>edit</button>}
      </div>
      {editing ? (
        <>
          <textarea value={draft} disabled={busy}
            onChange={(e) => setDraft(e.target.value)} />
          <div className="preset-actions">
            <button className="actbtn" disabled={busy} onClick={save}>save</button>
            <button className="clear" disabled={busy}
              onClick={() => { setDraft(row.answer); setEditing(false); }}>cancel</button>
          </div>
        </>
      ) : (
        <div className="preset-value">{row.answer}
          {row.answer_rule && <span className="muted"> · rule: upper end of posted range when known</span>}
        </div>
      )}
      {(row.covers?.length ?? 0) > 0 && (
        <div className="preset-covers">
          <span className="muted">auto-answers:</span> <ChipList values={row.covers} />
        </div>
      )}
      {msg && <div className="muted">{msg}</div>}
    </div>
  );
}

function JobCategoryRow({ cat, writable, onSaved }: {
  cat: JobProfileControls["job_categories"][number];
  writable: boolean; onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [keywords, setKeywords] = useState(cat.keywords.join(", "));
  const [focus, setFocus] = useState(cat.role_focus);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchCategory(cat.id, {
        keywords: keywords.split(",").map((s) => s.trim()).filter(Boolean),
        role_focus: focus,
      });
      setEditing(false); onSaved();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!window.confirm(`Remove search category "${cat.id}"? The daily search stops looking for it (re-addable later).`)) return;
    setBusy(true); setMsg(null);
    try { await removeJobSearchCategory(cat.id); onSaved(); }
    catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="preset-category" key={cat.id}>
      <div className="preset-row-head">
        <b>{cat.id}</b>
        {writable && !editing && (
          <span className="preset-actions">
            <button className="editbtn" onClick={() => setEditing(true)}>edit</button>
            <button className="editbtn" disabled={busy} onClick={remove}>remove</button>
          </span>
        )}
      </div>
      {editing ? (
        <>
          <label className="muted">keywords (comma-separated)</label>
          <textarea value={keywords} disabled={busy}
            onChange={(e) => setKeywords(e.target.value)} />
          <label className="muted">focus{" "}
            <select value={focus} disabled={busy}
              onChange={(e) => setFocus(e.target.value)}>
              <option value="primary">primary (always-on search)</option>
              <option value="secondary">secondary (target companies)</option>
            </select>
          </label>
          <div className="preset-actions">
            <button className="actbtn" disabled={busy} onClick={save}>save</button>
            <button className="clear" disabled={busy}
              onClick={() => setEditing(false)}>cancel</button>
          </div>
        </>
      ) : (
        <>
          <span>{cat.role_focus} · {cat.resume_variant}</span>
          <ChipList values={cat.keywords} />
        </>
      )}
      {msg && <div className="error">ERR {msg}</div>}
    </div>
  );
}

function AddCategoryForm({ variants, onSaved }: {
  variants: string[]; onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [variant, setVariant] = useState(variants[0] ?? "");
  const [keywords, setKeywords] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (!open) {
    return <button className="actbtn" onClick={() => setOpen(true)}>+ add job type</button>;
  }
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchCategory(id.trim().replace(/\s+/g, "_").toLowerCase(), {
        keywords: keywords.split(",").map((s) => s.trim()).filter(Boolean),
        resume_variant: variant,
      });
      setOpen(false); setId(""); setKeywords(""); onSaved();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="preset-category">
      <b>New job type</b>
      <label className="muted">id (e.g. quant_researcher)</label>
      <input value={id} disabled={busy} onChange={(e) => setId(e.target.value)} />
      <label className="muted">resume variant{" "}
        <select value={variant} disabled={busy}
          onChange={(e) => setVariant(e.target.value)}>
          {variants.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </label>
      <label className="muted">keywords (comma-separated)</label>
      <textarea value={keywords} disabled={busy}
        onChange={(e) => setKeywords(e.target.value)} />
      <div className="preset-actions">
        <button className="actbtn" disabled={busy || !id.trim() || !keywords.trim()}
          onClick={save}>create</button>
        <button className="clear" disabled={busy} onClick={() => setOpen(false)}>cancel</button>
      </div>
      {msg && <div className="error">ERR {msg}</div>}
    </div>
  );
}

function DailyTargetRow({ label, name, value, writable, onSaved }: {
  label: string; name: string; value: number; writable: boolean;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState(String(value));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchRuntime({ [name]: Number(draft) });
      onSaved(); setMsg("saved");
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="settings-row">
      <span>{label}</span>
      <span className="preset-actions">
        <input className="num-input" type="number" value={draft} disabled={busy || !writable}
          onChange={(e) => setDraft(e.target.value)} />
        {writable && Number(draft) !== value &&
          <button className="actbtn" disabled={busy} onClick={save}>save</button>}
        {msg && <span className="muted">{msg}</span>}
      </span>
    </div>
  );
}

function ReclassifyPanel({ writable }: { writable: boolean }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReclassifyResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function run() {
    setBusy(true); setErr(null); setResult(null);
    try { setResult(await reclassifyJobApplications()); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="reclassify-panel">
      <button className="actbtn" disabled={busy || !writable} onClick={run}>
        {busy ? "re-sorting..." : "Re-sort all applications with current answers"}
      </button>
      <p className="muted">
        Applies your standing answers and search rules to the jobs already on
        the board — a job whose only blockers are now answered moves to the Bot
        board.
      </p>
      {err && <div className="error">ERR {err}</div>}
      {result && (
        <div className="reclassify-result">
          <div className="muted">
            scanned {result.cards_scanned} · bot {result.counts.bot_possible ?? 0}
            {" "}· manual {result.counts.manual_required ?? 0}
            {" "}· prepare-only {result.counts.prepare_only ?? 0}
          </div>
          {result.changed.length === 0
            ? <div className="muted">no cards changed board</div>
            : result.changed.map((c) => (
                <div className="reclassify-row" key={c.card_id}>
                  <b>{c.company}</b> {c.role_title}
                  <span className="chip">{c.before} → {c.after}</span>
                  {c.auto_answered.length > 0 &&
                    <span className="muted"> (answered: {c.auto_answered.join(", ")})</span>}
                </div>
              ))}
        </div>
      )}
    </div>
  );
}

function JobPresetDrawer({ onClose }: { onClose: () => void }) {
  const [controls, setControls] = useState<JobProfileControls | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showPolicy, setShowPolicy] = useState(false);
  const load = useCallback(() => {
    setErr(null);
    fetchJobProfileControls().then(setControls)
      .catch((e) => setErr((e as Error).message));
  }, []);
  useEffect(() => { load(); }, [load]);
  const questions = controls?.application_questions;
  const dag = controls?.dag;
  return (
    <DrawerShell title="Job Search Settings" onClose={onClose}>
      {err && <div className="error">ERR {err}</div>}
      {!controls && !err && <div className="loading">...</div>}
      {controls && questions && (
        <div className="presets">
          <div className="preset-source">
            <span className={`status-pill ${controls.writable ? "pill-run" : "pill-warn"}`}>
              {controls.writable ? "editable" : "read-only"}
            </span>
            <span>{controls.write_gate}</span>
          </div>

          <ReclassifyPanel writable={controls.writable} />

          <h3>Standing Answers</h3>
          <p className="muted">
            Your answers to the common application questions. A question
            covered here is auto-answered into each packet&apos;s App Answers
            file instead of blocking the bot.
          </p>
          {(controls.standing_answers?.answers ?? []).map((row) => (
            <StandingAnswerRow key={row.topic} row={row}
              writable={controls.writable} onSaved={load} />
          ))}
          {!(controls.standing_answers?.answers ?? []).length && (
            <div className="muted">
              none on file — {controls.standing_answers?.source}
            </div>
          )}

          <h3>Job Types Searched</h3>
          <p className="muted">
            The daily discovery searches these keywords (primary types always;
            secondary at target companies). Edit, remove, or add types here —
            the DAG picks up changes on its next run.
          </p>
          <div className="preset-category-list">
            {controls.job_categories.map((cat) => (
              <JobCategoryRow key={cat.id} cat={cat}
                writable={controls.writable} onSaved={load} />
            ))}
          </div>
          {controls.writable &&
            <AddCategoryForm variants={controls.resume_variants} onSaved={load} />}

          <h3>Daily Targets &amp; Schedule</h3>
          <div className="settings-list">
            <DailyTargetRow label="Bot-possible suggestions / day"
              name="max_bot_possible_suggestions_per_day"
              value={controls.job_search.max_bot_possible_suggestions_per_day}
              writable={controls.writable} onSaved={load} />
            <DailyTargetRow label="Manual-required suggestions / day"
              name="max_manual_required_suggestions_per_day"
              value={controls.job_search.max_manual_required_suggestions_per_day}
              writable={controls.writable} onSaved={load} />
            <DailyTargetRow label="Total suggestions / day"
              name="max_suggested_jobs_per_day"
              value={controls.job_search.max_suggested_jobs_per_day}
              writable={controls.writable} onSaved={load} />
            <DailyTargetRow label="Selected / prepared per day"
              name="max_selected_jobs_per_day"
              value={controls.job_search.max_selected_jobs_per_day}
              writable={controls.writable} onSaved={load} />
            {dag && (
              <>
                <div className="settings-row">
                  <span>pipeline</span>
                  <code>{dag.dag_id} · {dag.schedule}</code>
                </div>
                <div className="settings-row">
                  <span>last digest</span>
                  <code>{dag.last_digest_at ? dateText(dag.last_digest_at) : "no digest visible from this deployment"}</code>
                </div>
              </>
            )}
          </div>
          {dag && <p className="muted">{dag.note}</p>}

          <h3>
            <button className="editbtn" onClick={() => setShowPolicy(!showPolicy)}>
              {showPolicy ? "hide" : "show"} question policy &amp; control files
            </button>
          </h3>
          {showPolicy && (
            <>
              <div className="diag-table">
                <div className="diag-row"><span>default</span><code>{questions.default_policy}</code></div>
                <div className="diag-row"><span>source</span><code>{controls.application_questions_source}</code></div>
                <div className="diag-row"><span>standing answers</span><code>{controls.standing_answers?.source}</code></div>
              </div>
              <h3>Draft Defaults</h3>
              {Object.entries(questions.draft_defaults).map(([name, value]) => (
                <DraftDefaultRow key={name} name={name} value={value}
                  writable={controls.writable} onSaved={load} />
              ))}
              <h3>Review Required</h3>
              <ChipList values={questions.review_required} />
              <h3>Never Auto-answer</h3>
              <ChipList values={questions.never_auto_answer} />
              <h3>Control Files</h3>
              <div className="diag-table">
                {Object.entries(controls.source_paths).map(([name, path]) => (
                  <div className="diag-row" key={name}><span>{name}</span><code>{path}</code></div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </DrawerShell>
  );
}

function RuntimeControlsPanel({ status, runtime }: {
  status: Status | null; runtime: ChatRuntime | null;
}) {
  return (
    <section className="settings-card">
      <div className="settings-card-head">
        <h3>Runtime APIs</h3>
        <span className={`status-pill ${runtime?.enabled ? "pill-run" : "pill-warn"}`}>
          {runtime?.enabled ? "enabled" : "read-only"}
        </span>
      </div>
      <div className="settings-list">
        {Object.entries(status?.hops ?? {}).map(([name, state]) => (
          <div className="settings-row" key={name}>
            <span><span className={`hopdot ${state === "ok" ? "ok" : "bad"}`} />{name}</span>
            <code>{status?.targets?.[name] ?? state}</code>
          </div>
        ))}
        <div className="settings-row">
          <span>chat runtime</span>
          <code>{runtime?.harness ?? "unavailable"} / {runtime?.model_gateway ?? "unknown"}</code>
        </div>
        <div className="settings-row">
          <span>action endpoint</span>
          <code>{runtime?.action_endpoint ?? "/api/action"}</code>
        </div>
      </div>
      <h3>External Runtimes</h3>
      <div className="settings-list">
        <div className="settings-row">
          <span>GatewayCore</span>
          <span className="status-pill pill-run">active</span>
        </div>
        <div className="settings-row">
          <span>OxyGent / ORCA / Omnigent</span>
          <span className="status-pill pill-warn">watch-list</span>
        </div>
      </div>
    </section>
  );
}

const CARD_COMPONENTS = [
  "job_application", "linkedin_post", "book", "paper", "repo", "dag",
  "machine_upkeep", "mission", "generic_task",
];
const DOMAIN_SOURCES = ["fixtures", "board_store", "ledger_missions"];
const GRANTABLE_ACTIONS = ["add_mission_card", "stage_card", "start_todo", "finish_todo", "block_card", "reject_card"];
const FIELD_KINDS: NonNullable<FieldSpec["kind"]>[] = [
  "text", "badge", "score", "money", "url", "datetime", "markdown", "list", "progress",
];

function linesToList(text: string): string[] {
  return text.split(/\r?\n|,/).map((s) => s.trim()).filter(Boolean);
}
function listToLines(values: string[] = []): string {
  return values.join("\n");
}
function fieldsToText(fields: FieldSpec[] = []): string {
  return fields.map((field) =>
    [field.name, field.label, field.kind ?? "text"].join(" | ")).join("\n");
}
function fieldsFromText(text: string): FieldSpec[] {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const [rawName, rawLabel, rawKind] = line.split("|").map((part) => part.trim());
    const name = rawName || "field";
    const label = rawLabel || titleToken(name);
    const kind = FIELD_KINDS.includes(rawKind as NonNullable<FieldSpec["kind"]>)
      ? rawKind as NonNullable<FieldSpec["kind"]>
      : "text";
    return { name, label, kind };
  });
}
function columnActionsToText(actions: Record<string, string> = {}): string {
  return Object.entries(actions).map(([column, action]) => `${column} | ${action}`).join("\n");
}
function columnActionsFromText(text: string): Record<string, string> {
  return Object.fromEntries(text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    .map((line) => line.split("|").map((part) => part.trim()))
    .filter(([column, action]) => column && action)
    .map(([column, action]) => [column, action]));
}
function nextDomainId(domains: DomainSpec[]): string {
  const ids = new Set(domains.map((domain) => domain.domain_id));
  if (!ids.has("new_board")) return "new_board";
  for (let i = 2; i < 100; i += 1) {
    const id = `new_board_${i}`;
    if (!ids.has(id)) return id;
  }
  return `new_board_${Date.now()}`;
}
function newDomainSpec(domains: DomainSpec[]): DomainSpec {
  return {
    domain_id: nextDomainId(domains),
    title: "New Board",
    card_component: "generic_task",
    source: "fixtures",
    columns: ["Backlog", "Ready", "In Progress", "Done", "Blocked"],
    column_actions: {
      Ready: "stage_card",
      "In Progress": "start_todo",
      Done: "finish_todo",
      Blocked: "block_card",
    },
    summary_fields: [
      { name: "title", label: "Title", kind: "text" },
      { name: "priority", label: "Priority", kind: "badge" },
    ],
    drawer_fields: [{ name: "notes", label: "Notes", kind: "markdown" }],
    allowed_actions: ["stage_card", "start_todo", "finish_todo", "block_card", "reject_card"],
    empty_state: {
      title: "No cards yet",
      hint: "Cards appear when this board is connected to a source.",
    },
  };
}

function DomainSchemaEditor({ initial, mode, editable, onClose, onSaved }: {
  initial: DomainSpec;
  mode: "create" | "update";
  editable: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState({
    domain_id: initial.domain_id,
    title: initial.title,
    card_component: initial.card_component,
    source: initial.source,
    board_id: initial.board_id ?? "",
    columns: listToLines(initial.columns ?? []),
    column_actions: columnActionsToText(initial.column_actions ?? {}),
    summary_fields: fieldsToText(initial.summary_fields ?? []),
    drawer_fields: fieldsToText(initial.drawer_fields ?? []),
    allowed_actions: (initial.allowed_actions ?? []).join(", "),
    empty_title: initial.empty_state?.title ?? "",
    empty_hint: initial.empty_state?.hint ?? "",
    empty_command: initial.empty_state?.command ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    setDraft({
      domain_id: initial.domain_id,
      title: initial.title,
      card_component: initial.card_component,
      source: initial.source,
      board_id: initial.board_id ?? "",
      columns: listToLines(initial.columns ?? []),
      column_actions: columnActionsToText(initial.column_actions ?? {}),
      summary_fields: fieldsToText(initial.summary_fields ?? []),
      drawer_fields: fieldsToText(initial.drawer_fields ?? []),
      allowed_actions: (initial.allowed_actions ?? []).join(", "),
      empty_title: initial.empty_state?.title ?? "",
      empty_hint: initial.empty_state?.hint ?? "",
      empty_command: initial.empty_state?.command ?? "",
    });
  }, [initial]);
  const payload = (): DomainSpec => ({
    domain_id: draft.domain_id.trim(),
    title: draft.title.trim(),
    card_component: draft.card_component,
    source: draft.source,
    board_id: draft.source === "board_store" ? draft.board_id.trim() : undefined,
    columns: linesToList(draft.columns),
    column_actions: columnActionsFromText(draft.column_actions),
    summary_fields: fieldsFromText(draft.summary_fields),
    drawer_fields: fieldsFromText(draft.drawer_fields),
    allowed_actions: linesToList(draft.allowed_actions),
    empty_state: {
      title: draft.empty_title.trim(),
      hint: draft.empty_hint.trim(),
      command: draft.empty_command.trim() || undefined,
    },
  });
  async function save() {
    setBusy(true); setMsg(null);
    try {
      const domain = payload();
      if (mode === "create") await createDomainSchema(domain);
      else await updateDomainSchema(initial.domain_id, domain);
      setMsg("updated");
      onSaved();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (mode !== "update") return;
    if (!window.confirm(`Remove ${initial.title} from All Boards?`)) return;
    setBusy(true); setMsg(null);
    try {
      await deleteDomainSchema(initial.domain_id);
      setMsg("removed");
      onSaved();
      onClose();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="schema-editor">
      <div className="settings-card-head">
        <h3>{mode === "create" ? "Add Board" : `Edit ${initial.title}`}</h3>
        <button className="editbtn" onClick={onClose}>close</button>
      </div>
      <div className="schema-form-grid">
        <label>Board ID<input value={draft.domain_id} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, domain_id: e.target.value }))} /></label>
        <label>Title<input value={draft.title} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, title: e.target.value }))} /></label>
        <label>Card type<select className="select" value={draft.card_component} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, card_component: e.target.value }))}>
          {CARD_COMPONENTS.map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <label>Source<select className="select" value={draft.source} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, source: e.target.value }))}>
          {DOMAIN_SOURCES.map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <label>Board store ID<input value={draft.board_id}
          disabled={!editable || busy || draft.source !== "board_store"}
          onChange={(e) => setDraft((m) => ({ ...m, board_id: e.target.value }))} /></label>
      </div>
      <div className="schema-form-grid schema-form-grid-wide">
        <label>Columns<textarea value={draft.columns} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, columns: e.target.value }))} /></label>
        <label>Column Actions<textarea value={draft.column_actions} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, column_actions: e.target.value }))} /></label>
        <label>Summary Fields<textarea value={draft.summary_fields} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, summary_fields: e.target.value }))} /></label>
        <label>Drawer Fields<textarea value={draft.drawer_fields} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, drawer_fields: e.target.value }))} /></label>
      </div>
      <div className="schema-form-grid schema-form-grid-wide">
        <label>Allowed Actions<textarea value={draft.allowed_actions} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, allowed_actions: e.target.value }))} /></label>
        <label>Empty Title<input value={draft.empty_title} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, empty_title: e.target.value }))} /></label>
        <label>Empty Hint<textarea value={draft.empty_hint} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, empty_hint: e.target.value }))} /></label>
        <label>Empty Command<input value={draft.empty_command} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, empty_command: e.target.value }))} /></label>
      </div>
      <div className="schema-action-picks">
        {GRANTABLE_ACTIONS.map((action) => <span className="chip" key={action}>{action}</span>)}
      </div>
      <div className="preset-actions">
        <button className="actbtn" disabled={!editable || busy} onClick={save}>save board</button>
        {mode === "update" && <button className="editbtn danger" disabled={!editable || busy} onClick={remove}>remove</button>}
        {msg && <span className={msg === "updated" || msg === "removed" ? "actmsg" : "error-inline"}>{msg}</span>}
      </div>
    </div>
  );
}

function BoardControlsPanel({ schema, registry, err, onSaved }: {
  schema: DomainSchema | null; registry: BoardRegistry | null; err: string | null;
  onSaved: () => void;
}) {
  const domains = schema?.domains ?? [];
  const editable = !!schema?.writable;
  const [editing, setEditing] = useState<{ mode: "create" | "update"; domain: DomainSpec } | null>(null);
  return (
    <section className="settings-card settings-card-wide">
      <div className="settings-card-head">
        <h3>All Boards</h3>
        <div className="settings-head-actions">
          <span className={`status-pill ${editable ? "pill-run" : "pill-warn"}`}>
            {editable ? "editable" : "read-only"}
          </span>
          <span className="status-pill">{domains.length} boards</span>
          <button className="actbtn" disabled={!editable}
            onClick={() => setEditing({ mode: "create", domain: newDomainSpec(domains) })}>
            add board
          </button>
        </div>
      </div>
      {err && <div className="error">ERR {err}</div>}
      {schema && (
        <div className="diag-table">
          <div className="diag-row"><span>schema</span><code>{schema.config_path}</code></div>
          <div className="diag-row"><span>write gate</span><code>{schema.write_gate}</code></div>
        </div>
      )}
      {editing && (
        <DomainSchemaEditor initial={editing.domain} mode={editing.mode} editable={editable}
          onClose={() => setEditing(null)} onSaved={onSaved} />
      )}
      <div className="settings-board-grid">
        {domains.map((domain) => (
          <div className="settings-board" key={domain.domain_id}>
            <div className="settings-board-title">
              <b>{domain.title}</b>
              <span className="status-pill">{domain.source}</span>
            </div>
            <div className="muted small">{domain.card_component}</div>
            <div className="chip-list">
              {(domain.columns ?? []).slice(0, 5).map((col) => <Badge key={col} value={col} />)}
              {(domain.columns?.length ?? 0) > 5 && <Badge value={`+${(domain.columns?.length ?? 0) - 5}`} />}
            </div>
            <div className="muted small">{domain.summary_fields.length} summary fields · {domain.drawer_fields.length} drawer fields</div>
            <div className="preset-actions">
              <button className="editbtn" disabled={!editable}
                onClick={() => setEditing({ mode: "update", domain })}>edit</button>
            </div>
          </div>
        ))}
      </div>
      {registry && (
        <>
          <h3>Provider Registry</h3>
          <div className="diag-table">
            <div className="diag-row"><span>source</span><code>{registry.config_path}</code></div>
            <div className="diag-row"><span>editable</span><code>{String(registry.config_writable)}</code></div>
          </div>
          <div className="settings-list">
            {registry.boards.map((board) => (
              <div className="settings-row settings-row-tall" key={board.board_id}>
                <span>
                  <b>{board.board_id}</b>
                  <small>{board.provider} · {board.board_ref}</small>
                </span>
                <code>{Object.values(board.status_mapping).join(" / ")}</code>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function JobRuntimeControls({ controls, onSaved }: {
  controls: JobProfileControls; onSaved: () => void;
}) {
  const [draft, setDraft] = useState({
    daily_run_time: controls.job_search.daily_run_time,
    max_suggested_jobs_per_day: String(controls.job_search.max_suggested_jobs_per_day),
    max_bot_possible_suggestions_per_day: String(controls.job_search.max_bot_possible_suggestions_per_day),
    max_manual_required_suggestions_per_day: String(controls.job_search.max_manual_required_suggestions_per_day),
    max_selected_jobs_per_day: String(controls.job_search.max_selected_jobs_per_day),
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    setDraft({
      daily_run_time: controls.job_search.daily_run_time,
      max_suggested_jobs_per_day: String(controls.job_search.max_suggested_jobs_per_day),
      max_bot_possible_suggestions_per_day: String(controls.job_search.max_bot_possible_suggestions_per_day),
      max_manual_required_suggestions_per_day: String(controls.job_search.max_manual_required_suggestions_per_day),
      max_selected_jobs_per_day: String(controls.job_search.max_selected_jobs_per_day),
    });
  }, [controls]);
  const editable = controls.writable && controls.job_search_settings_writable;
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchRuntime({
        daily_run_time: draft.daily_run_time,
        max_suggested_jobs_per_day: Number(draft.max_suggested_jobs_per_day),
        max_bot_possible_suggestions_per_day: Number(draft.max_bot_possible_suggestions_per_day),
        max_manual_required_suggestions_per_day: Number(draft.max_manual_required_suggestions_per_day),
        max_selected_jobs_per_day: Number(draft.max_selected_jobs_per_day),
      });
      setMsg("updated");
      onSaved();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="settings-form">
      <div className="settings-form-grid">
        <label>Daily time<input value={draft.daily_run_time} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, daily_run_time: e.target.value }))} /></label>
        <label>Total/day<input type="number" min="1" max="100"
          value={draft.max_suggested_jobs_per_day} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, max_suggested_jobs_per_day: e.target.value }))} /></label>
        <label>Bot/day<input type="number" min="0" max="100"
          value={draft.max_bot_possible_suggestions_per_day} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, max_bot_possible_suggestions_per_day: e.target.value }))} /></label>
        <label>Manual/day<input type="number" min="0" max="100"
          value={draft.max_manual_required_suggestions_per_day} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, max_manual_required_suggestions_per_day: e.target.value }))} /></label>
        <label>Selected/day<input type="number" min="1" max="25"
          value={draft.max_selected_jobs_per_day} disabled={!editable || busy}
          onChange={(e) => setDraft((m) => ({ ...m, max_selected_jobs_per_day: e.target.value }))} /></label>
      </div>
      <div className="preset-actions">
        <button className="actbtn" disabled={!editable || busy} onClick={save}>save search limits</button>
        {msg && <span className={msg === "updated" ? "actmsg" : "error-inline"}>{msg}</span>}
      </div>
      <div className="diag-row"><span>override</span><code>{controls.job_search_settings_source}</code></div>
    </div>
  );
}

function CategorySettingRow({ category, editable, onSaved }: {
  category: JobProfileControls["job_categories"][number];
  editable: boolean;
  onSaved: () => void;
}) {
  const [focus, setFocus] = useState(category.role_focus);
  const [keywords, setKeywords] = useState(category.keywords.join(", "));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    setFocus(category.role_focus);
    setKeywords(category.keywords.join(", "));
  }, [category]);
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchCategory(category.id, {
        role_focus: focus,
        keywords: keywords.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setMsg("updated");
      onSaved();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="preset-category">
      <div className="category-edit-head">
        <b>{category.id}</b>
        <select className="select" value={focus} disabled={!editable || busy}
          onChange={(e) => setFocus(e.target.value)}>
          <option value="primary">primary</option>
          <option value="secondary">secondary</option>
        </select>
      </div>
      <div className="muted small">{category.resume_variant}</div>
      <textarea className="settings-textarea" value={keywords} disabled={!editable || busy}
        onChange={(e) => setKeywords(e.target.value)} />
      <div className="preset-actions">
        <button className="actbtn" disabled={!editable || busy} onClick={save}>save category</button>
        {msg && <span className={msg === "updated" ? "actmsg" : "error-inline"}>{msg}</span>}
      </div>
    </div>
  );
}

function JobSearchControlsPanel({ controls, onSaved }: {
  controls: JobProfileControls; onSaved: () => void;
}) {
  const editable = controls.writable && controls.job_search_settings_writable;
  return (
    <section className="settings-card settings-card-wide">
      <div className="settings-card-head">
        <h3>Job Search</h3>
        <span className={`status-pill ${editable ? "pill-run" : "pill-warn"}`}>
          {editable ? "editable" : "read-only"}
        </span>
      </div>
      <JobRuntimeControls controls={controls} onSaved={onSaved} />
      <h3>Role Focus</h3>
      <div className="preset-category-list">
        {controls.job_categories.map((category) => (
          <CategorySettingRow key={category.id} category={category}
            editable={editable} onSaved={onSaved} />
        ))}
      </div>
      <h3>Own Info</h3>
      <div className="diag-table">
        {Object.entries(controls.source_paths).map(([name, path]) => (
          <div className="diag-row" key={name}><span>{name}</span><code>{path}</code></div>
        ))}
      </div>
      <h3>Draft Defaults</h3>
      {Object.entries(controls.application_questions.draft_defaults).map(([name, value]) => (
        <DraftDefaultRow key={name} name={name} value={value}
          writable={controls.writable} onSaved={onSaved} />
      ))}
    </section>
  );
}

function SettingsView({ status, runtime }: {
  status: Status | null; runtime: ChatRuntime | null;
}) {
  const [domainSchema, setDomainSchema] = useState<DomainSchema | null>(null);
  const [registry, setRegistry] = useState<BoardRegistry | null>(null);
  const [controls, setControls] = useState<JobProfileControls | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    setErr(null);
    try {
      const [schemaBody, boardBody, jobControls] = await Promise.all([
        fetchDomainSchema(),
        fetchBoardRegistry(),
        fetchJobProfileControls(),
      ]);
      setDomainSchema(schemaBody);
      setRegistry(boardBody);
      setControls(jobControls);
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="settings">
      <div className="domain-head settings-head">
        <div>
          <h2>Controls</h2>
          <div className="muted small">All Boards, job search, profile defaults, and runtime APIs</div>
        </div>
      </div>
      {err && <div className="error">ERR {err}</div>}
      {!controls && !err && <div className="loading">...</div>}
      <div className="settings-grid">
        <RuntimeControlsPanel status={status} runtime={runtime} />
        <BoardControlsPanel schema={domainSchema} registry={registry} err={null} onSaved={load} />
        {controls && <JobSearchControlsPanel controls={controls} onSaved={load} />}
      </div>
    </div>
  );
}

function ProgressCheck({ state }: { state: string }) {
  const symbol = state === "done" ? "✓" : state === "current" ? "!" : "·";
  return <span className={`progress-check progress-${state}`}>{symbol}</span>;
}

function DomainProgressPanel({ progress, onOpenChat, onProgressChanged, onOpenPacket }: {
  progress: DomainCardProgress;
  onOpenChat?: (prompt: string, conversationId?: string) => void;
  onProgressChanged?: (progress: DomainCardProgress) => void;
  onOpenPacket?: () => void;
}) {
  const conversationId = `${progress.domain_id}:${progress.card_id}`;
  const canAddJobNote = progress.domain_id === "job_application" && !!progress.application?.exists;
  const [noteType, setNoteType] = useState("recruiter_email");
  const [noteText, setNoteText] = useState("");
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteMsg, setNoteMsg] = useState<string | null>(null);
  async function saveNote() {
    const text = noteText.trim();
    if (!text || !canAddJobNote) return;
    setNoteBusy(true); setNoteMsg(null);
    try {
      const result = await addDomainCardNote(
        progress.domain_id, progress.card_id, noteType, text,
        noteType.includes("email") ? "email" : "cockpit",
      );
      setNoteText("");
      setNoteMsg(result.event ? "note saved · moved to Interviewing" : "note saved");
      onProgressChanged?.(result.progress);
    } catch (e) { setNoteMsg("ERR " + (e as Error).message); }
    finally { setNoteBusy(false); }
  }
  return (
    <div className="domain-progress-panel">
      <div className="domain-section-head">
        <h3>Progress</h3>
        {progress.domain_id === "job_application" && (
          <button className="actbtn"
            onClick={() => onOpenPacket?.()}
            disabled={!onOpenPacket || !progress.application?.exists}
            title={progress.application?.exists
              ? "read the resume/cover letter/answers, leave notes, approve & submit"
              : "materials are generated after you move the card to In Progress"}>
            review packet
          </button>
        )}
        <button className="actbtn"
          onClick={() => onOpenChat?.(progress.chat_prompt, conversationId)}
          disabled={!onOpenChat || !progress.chat_prompt}>
          open in chat
        </button>
      </div>
      <div className="progress-steps">
        {progress.steps.map((step) => (
          <details className={`progress-step progress-step-${step.state}`} key={step.id}
            open={step.state !== "waiting"}>
            <summary>
              <ProgressCheck state={step.state} />
              <span>{step.label}</span>
              <Badge value={step.state} />
            </summary>
            <div className="progress-detail">{step.detail || "No detail recorded."}</div>
          </details>
        ))}
      </div>
      {progress.events.length > 0 && (
        <details className="progress-events">
          <summary>{progress.events.length} governed event(s)</summary>
          {progress.events.map((ev) => (
            <div className="progress-event" key={ev.event_id}>
              <div><b>{ev.headline}</b></div>
              <div className="muted small">
                {dateText(ev.created_at)} · {ev.actor_type || "actor"} · {ev.source_surface || "surface"}
              </div>
            </div>
          ))}
        </details>
      )}
      {progress.domain_id === "job_application" && (
        <div className="job-note-panel">
          <div className="domain-section-head">
            <h3>Next-Step Notes</h3>
          </div>
          <div className="note-controls">
            <select className="select" value={noteType}
              disabled={!canAddJobNote || noteBusy}
              onChange={(e) => setNoteType(e.target.value)}>
              <option value="recruiter_email">recruiter email</option>
              <option value="recruiter_call">recruiter call</option>
              <option value="interview_note">interview note</option>
              <option value="portal_question">portal question</option>
              <option value="salary_note">salary note</option>
              <option value="manual_note">manual note</option>
            </select>
            <textarea value={noteText}
              disabled={!canAddJobNote || noteBusy}
              placeholder={canAddJobNote ? "paste email, recruiter notes, portal questions, or next steps" : "materials must exist before notes can attach"}
              onChange={(e) => setNoteText(e.target.value)} />
            <div className="note-actions">
              <button className="actbtn" disabled={!canAddJobNote || noteBusy || !noteText.trim()}
                onClick={saveNote}>{noteBusy ? "saving..." : "save note"}</button>
              {noteMsg && <span className={noteMsg.startsWith("ERR") ? "error-inline" : "muted small"}>{noteMsg}</span>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---- application packet review (resume/cover letter/answers + agent trace) --
const PACKET_TABS: { key: string; label: string; file?: string; editable?: boolean }[] = [
  { key: "overview", label: "Overview" },
  { key: "story", label: "Story" },
  { key: "resume", label: "Resume", file: "resume", editable: true },
  { key: "resume_ats", label: "ATS Text", file: "resume_ats" },
  { key: "cover_letter", label: "Cover Letter", file: "cover_letter", editable: true },
  { key: "application_answers", label: "App Answers", file: "application_answers", editable: true },
  { key: "answer_bank", label: "Interview Answers", file: "answer_bank", editable: true },
  { key: "recruiter_message", label: "Outreach", file: "recruiter_message", editable: true },
  { key: "followups", label: "Follow-ups", file: "followups" },
  { key: "manual_checklist", label: "Checklist", file: "manual_checklist" },
  { key: "job_description", label: "Job Description", file: "job_description" },
  { key: "agent_trace", label: "Agent Trace" },
];

function StoryView({ story, onOpenAt }: {
  story: JobStoryEntry[];
  onOpenAt?: (ts: string) => void;
}) {
  if (!story.length) {
    return <div className="muted">No story recorded for this card yet.</div>;
  }
  return (
    <div className="packet-story">
      {story.map((s, i) => {
        const head = (
          <>
            <span className="story-time">{dateText(s.ts)}</span>
            <Badge value={s.kind} />
            <b>{s.title}</b>
            <span className="muted small">{s.summary}</span>
            {onOpenAt && s.ts && (
              <button className="clear story-jump"
                title="open the chat timeline at this moment"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onOpenAt(s.ts); }}>
                open in chat
              </button>
            )}
          </>
        );
        return s.detail ? (
          <details className={`story-row story-${s.kind}`} key={i}>
            <summary>{head}</summary>
            <pre className="packet-doc">{s.detail}</pre>
          </details>
        ) : (
          <div className={`story-row story-${s.kind}`} key={i}>{head}</div>
        );
      })}
    </div>
  );
}

function PacketChecklist({ validation }: { validation: PacketValidation }) {
  return (
    <div className="packet-checks">
      {validation.checks.map((c) => {
        // "not_already_submitted" failing means the app WAS submitted — that is
        // a completed state, not a defect. Render it as a positive so a
        // successful submission never looks like a red error.
        const submitted = c.id === "not_already_submitted" && !c.ok;
        const cls = submitted ? "packet-check-ok"
          : c.ok ? "packet-check-ok"
          : c.level === "error" ? "packet-check-fail" : "packet-check-warn";
        const mark = submitted ? "✓" : c.ok ? "✓" : c.level === "error" ? "✗" : "!";
        const label = submitted ? "Application submitted" : c.label;
        return (
          <div key={c.id} className={`packet-check ${cls}`}>
            <span className="packet-check-mark">{mark}</span>
            <div>
              <div>{label}</div>
              <div className="muted small">{c.detail}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AgentTraceView({ entries }: { entries: AgentTraceEntry[] }) {
  if (!entries.length) {
    return (
      <div className="muted">
        No agent trace yet — this packet was rendered from templates. Use
        “request changes” to regenerate it with the agent writer; every prompt
        and model output will be recorded here.
      </div>
    );
  }
  return (
    <div className="packet-trace">
      {entries.map((t, i) => (
        <details key={i} className="packet-trace-entry" open={i === entries.length - 1}>
          <summary>
            <Badge value={t.ok === false ? "failed" : "ok"} />
            <b>{t.step}</b> · attempt {t.attempt} · {t.model}
            {typeof t.duration_ms === "number" && ` · ${(t.duration_ms / 1000).toFixed(1)}s`}
            <span className="muted small"> {dateText(t.ts)}</span>
          </summary>
          {t.error && <div className="error-inline">ERR {t.error}</div>}
          {!!t.problems?.length && (
            <div className="error-inline">problems: {t.problems.join("; ")}</div>
          )}
          {!!t.claim_ids?.length && (
            <div className="muted small">claims used: {t.claim_ids.join(", ")}</div>
          )}
          {(t.messages ?? []).map((m, j) => (
            <details key={j} className="packet-trace-msg">
              <summary>context sent → {m.role} ({m.content.length.toLocaleString()} chars)</summary>
              <pre className="packet-doc">{m.content}</pre>
            </details>
          ))}
          {t.response && (
            <details className="packet-trace-msg" open>
              <summary>model output ({t.response.length.toLocaleString()} chars)</summary>
              <pre className="packet-doc">{t.response}</pre>
            </details>
          )}
        </details>
      ))}
    </div>
  );
}

function PacketReviewModal({ spec, card, onClose, onChanged, onOpenChatAt }: {
  spec: DomainSpec; card: DomainCard; onClose: () => void; onChanged: () => void;
  onOpenChatAt?: (ts: string) => void;
}) {
  const id = cardId(card);
  const [packet, setPacket] = useState<JobPacket | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState("overview");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<"changes" | "submit" | "edit" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<Record<string, unknown> | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  useEffect(() => {
    let live = true;
    fetchJobPacket(spec.domain_id, id)
      .then((p) => { if (live) setPacket(p); })
      .catch((e) => { if (live) setErr((e as Error).message); });
    return () => { live = false; };
  }, [spec.domain_id, id]);

  async function sendChanges(text: string) {
    setBusy("changes");
    setMsg(text
      ? "notes recorded — regenerating with the agent writer (this can take a minute)..."
      : "regenerating with the current writer (this can take a minute)...");
    try {
      const result = await requestPacketChanges(spec.domain_id, id, text);
      setPacket(result.packet);
      setNotes("");
      setMsg(result.regenerate_error
        ? `ERR ${text ? "notes recorded, but " : ""}regeneration failed: ${result.regenerate_error}`
        : `regenerated — revision ${String(result.packet.record.revision)} is ready for review`);
      onChanged();
    } catch (e) { setMsg("ERR " + (e as Error).message); }
    finally { setBusy(null); }
  }

  async function saveEdit(fileKey: string) {
    setBusy("edit"); setMsg(null);
    try {
      const result = await updateJobPacketFile(spec.domain_id, id, fileKey, editText);
      setPacket(result.packet);
      setEditing(null);
      setMsg(`${fileKey.replace(/_/g, " ")} saved — recorded as a manual edit in the story`);
      onChanged();
    } catch (e) { setMsg("ERR " + (e as Error).message); }
    finally { setBusy(null); }
  }

  async function approveAndSubmit() {
    const company = valText(packet?.record.company);
    if (!window.confirm(
      `Submit the ${company} application? This marks it applied, moves the card to `
      + "Completed, and emails/stores the full record.")) return;
    setBusy("submit"); setMsg(null);
    try {
      const result = await submitJobApplication(spec.domain_id, id);
      setSubmitted(result.side_effect ?? {});
      const email = (result.side_effect as {
        email?: { status?: string; detail?: string; error?: string; to?: string };
      } | null)?.email;
      const emailNote = email?.status === "sent" ? ` to ${email?.to}`
        : (email?.detail || email?.error) ? ` (${email.detail ?? email.error})` : "";
      setMsg(`submitted — card moved to Completed; email record: ${email?.status ?? "unknown"}${emailNote}`);
      onChanged();
    } catch (e) { setMsg("ERR " + (e as Error).message); setBusy(null); return; }
    finally { setBusy(null); }
    // refresh is best-effort: a failed refetch must not overwrite the
    // submit-succeeded message above
    try { setPacket(await fetchJobPacket(spec.domain_id, id)); } catch { /* keep result */ }
  }

  const record = packet?.record ?? {};
  const validation = packet?.validation;
  // applied_at is the durable submit marker — status mutates later (e.g. a
  // recruiter note flips it to recruiter_contact) and must not re-arm submit
  const alreadyApplied = !!record.applied_at || valText(record.status) === "applied";
  const canSubmit = !!validation?.ok && !alreadyApplied && !busy;
  const title = `${valText(record.company) || valText(card.company)} — ${valText(record.role_title) || valText(card.role_title)}`;

  return (
    <div className="drawer-bg packet-bg" onClick={onClose}>
      <div className="packet-modal" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>Application packet · {title}</h2>
          <button className="x" onClick={onClose} aria-label="Close packet review">✕</button>
        </div>
        {err && <div className="error">ERR {err}</div>}
        {!packet && !err && <div className="loading">loading packet...</div>}
        {packet && (
          <>
            <HorizontalScroller className="packet-tabs">
              {PACKET_TABS.map((t) => (
                <button key={t.key} className={`tab ${tab === t.key ? "tab-on" : ""}`}
                  onClick={() => setTab(t.key)}>{t.label}</button>
              ))}
            </HorizontalScroller>
            {msg && <div className={msg.startsWith("ERR") ? "error" : "packet-msg"}>{msg}</div>}
            {alreadyApplied && (
              <div className="packet-submitted-banner">
                ✓ Submitted{record.applied_at ? ` on ${valText(record.applied_at)}` : ""}
                {" "}— this application is complete and the record is saved. The
                validation list below shows it can&apos;t be re-submitted (that&apos;s
                expected), not an error.
              </div>
            )}
            {tab === "overview" && (
              <div className="packet-overview">
                <div className="packet-facts">
                  <div><b>Fit</b> {valText(record.fit && (record.fit as { score?: number }).score)}/100 · {valText(record.resume_variant)}</div>
                  <div><b>Status</b> {valText(record.status)} / {valText(record.stage)} · revision {valText(record.revision) || "1"}</div>
                  <div><b>Generation</b> {valText((record.generation as { mode?: string } | undefined)?.mode) || "unknown"}
                    {(record.generation as { model?: string } | undefined)?.model
                      ? ` (${(record.generation as { model?: string }).model})` : ""}</div>
                  <div><b>Review</b> {valText(record.review_state) || "ready_for_review"}</div>
                  <div><b>Apply URL</b> <a href={valText(record.apply_url)} target="_blank" rel="noreferrer">{valText(record.apply_url)}</a></div>
                  <div><b>Email record</b> {packet.email.configured
                    ? `configured → ${packet.email.to}`
                    : `not configured — set ${packet.email.missing.join(", ")}; the record is still saved to disk on submit`}</div>
                </div>
                <h3>Validation</h3>
                {validation && <PacketChecklist validation={validation} />}
                {packet.submission_record && (
                  <details className="packet-submission">
                    <summary>submission record (evidence)</summary>
                    <pre className="packet-doc">{JSON.stringify(packet.submission_record, null, 2)}</pre>
                  </details>
                )}
                {!!packet.files.review_notes && (
                  <details className="packet-submission">
                    <summary>review notes so far</summary>
                    <pre className="packet-doc">{packet.files.review_notes}</pre>
                  </details>
                )}
                <h3>Not ready? Request changes</h3>
                <div className="note-controls">
                  <textarea value={notes} disabled={!!busy || alreadyApplied}
                    placeholder="what should the agent fix? e.g. 'lead with the NBA platform work, tighten the summary to 2 sentences'"
                    onChange={(e) => setNotes(e.target.value)} />
                  <div className="note-actions">
                    <button className="actbtn" disabled={!!busy || !notes.trim() || alreadyApplied}
                      onClick={() => void sendChanges(notes.trim())}>
                      {busy === "changes" ? "regenerating..." : "request changes & regenerate"}
                    </button>
                    <button className="actbtn" disabled={!!busy || alreadyApplied}
                      title="rewrite the materials with the current writer and existing notes — no new note is recorded"
                      onClick={() => void sendChanges("")}>
                      regenerate (no new notes)
                    </button>
                  </div>
                </div>
                <h3>Ready? Approve &amp; submit</h3>
                <div className="note-actions">
                  <button className="actbtn packet-submit" disabled={!canSubmit}
                    onClick={() => void approveAndSubmit()}
                    title={alreadyApplied ? "already submitted"
                      : validation?.ok ? "validate, mark applied, move to Completed, email the record"
                      : "fix the failed validation checks first"}>
                    {busy === "submit" ? "submitting..."
                      : alreadyApplied || submitted ? "submitted ✓"
                      : "approve & submit"}
                  </button>
                  <span className="muted small">
                    {alreadyApplied
                      ? "this application is already marked applied"
                      : validation?.ok
                        ? "runs validation, marks applied, moves the card to Completed, and emails/stores the full record"
                        : "blocked: " + (validation?.errors ?? []).join(", ")}
                  </span>
                </div>
              </div>
            )}
            {tab === "story" && <StoryView story={packet.story ?? []}
              onOpenAt={onOpenChatAt} />}
            {PACKET_TABS.filter((t) => t.file).map((t) => tab === t.key && (
              <div key={t.key} className="packet-body">
                {t.editable && !alreadyApplied && (
                  <div className="note-actions packet-edit-bar">
                    {editing === t.file ? (
                      <>
                        <button className="actbtn" disabled={busy === "edit" || !editText.trim()}
                          onClick={() => void saveEdit(t.file as string)}>
                          {busy === "edit" ? "saving..." : "save changes"}
                        </button>
                        <button className="actbtn" disabled={busy === "edit"}
                          onClick={() => setEditing(null)}>cancel</button>
                      </>
                    ) : (
                      <button className="actbtn"
                        onClick={() => {
                          setEditing(t.file as string);
                          setEditText(packet.files[t.file as string] ?? "");
                        }}>
                        edit {t.label.toLowerCase()}
                      </button>
                    )}
                  </div>
                )}
                {editing === t.file
                  ? <textarea className="packet-edit" value={editText}
                      onChange={(e) => setEditText(e.target.value)} />
                  : packet.files[t.file as string]
                    // resume_ats and job_description are deliberately plain
                    // text (what an ATS parser sees) — keep them monospace;
                    // everything else renders as a formatted document
                    ? (t.key === "resume_ats" || t.key === "job_description"
                        ? <pre className="packet-doc">{packet.files[t.file as string]}</pre>
                        : <DocumentView text={packet.files[t.file as string] ?? ""}
                            kind={t.key === "resume" ? "resume" : "doc"} />)
                    : <div className="muted">not generated for this packet</div>}
              </div>
            ))}
            {tab === "agent_trace" && <AgentTraceView entries={packet.agent_trace} />}
          </>
        )}
      </div>
    </div>
  );
}

function DomainDrawer({
  spec, card, actions, moveTargets = [], onMove, onChanged, onClose, onOpenChat, onOpenPacket,
  refreshTick = 0,
}: {
  spec: DomainSpec; card: DomainCard; actions?: DomainActions;
  moveTargets?: string[]; onMove?: (status: string) => void;
  onChanged: () => void; onClose: () => void;
  onOpenChat?: (prompt: string, conversationId?: string) => void;
  onOpenPacket?: () => void;
  refreshTick?: number;
}) {
  const [detail, setDetail] = useState<DomainCardDetail | null>(null);
  const [progress, setProgress] = useState<DomainCardProgress | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [progressErr, setProgressErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [mobile, setMobile] = useState(false);
  const id = cardId(card);

  useEffect(() => {
    let live = true;
    setDetail(null); setProgress(null); setErr(null); setProgressErr(null);
    if (!id) return () => { live = false; };
    fetchDomainCard(spec.domain_id, id)
      .then((d) => { if (live) setDetail(d); })
      .catch((e) => { if (live) setErr((e as Error).message); });
    fetchDomainCardProgress(spec.domain_id, id)
      .then((d) => { if (live) setProgress(d); })
      .catch((e) => { if (live) setProgressErr((e as Error).message); });
    return () => { live = false; };
    // refreshTick: packet review actions (regenerate/submit) bump it so the
    // open drawer refetches instead of showing pre-action progress
  }, [spec.domain_id, id, refreshTick]);

  const activeCard = detail?.card ?? card;
  const fields = detail?.drawer_fields ?? spec.drawer_fields;
  const verbs = (actions?.allowed_actions ?? []).filter((v) => !WALL_VERBS.has(v));
  const title = domainTitle(activeCard, spec);
  async function run(action: string) {
    setBusy(true); setMsg(null);
    try {
      const r = await postAction(action, domainActionParams(action, title));
      setMsg(r.result);
      onChanged();
    } catch (e) { setMsg("ERR " + (e as Error).message); }
    finally { setBusy(false); }
  }

  const hasPacket = spec.domain_id === "job_application" && !!activeCard.application_id;
  return (
    <DrawerShell title={title || id || spec.title} onClose={onClose}>
      {err && <div className="error">ERR {err}</div>}
      {hasPacket && onOpenPacket && (
        <div className="packet-banner">
          <div className="packet-banner-text">
            <b>Application packet ready</b>
            <span className="muted small">
              {valText(activeCard.company)} · {valText(activeCard.role_title)}
              {activeCard.automation_class ? ` · ${valText(activeCard.automation_class)}` : ""}
            </span>
          </div>
          <button className="actbtn packet-banner-btn" onClick={() => onOpenPacket()}>
            Review Packet →
          </button>
        </div>
      )}
      {spec.card_component === "linkedin_post" && (
        <>
          <div className="drawer-toggle">
            <button className={`tab ${!mobile ? "tab-on" : ""}`} onClick={() => setMobile(false)}>desktop</button>
            <button className={`tab ${mobile ? "tab-on" : ""}`} onClick={() => setMobile(true)}>mobile</button>
          </div>
          <LinkedInPreview card={activeCard} mobile={mobile} />
        </>
      )}
      {moveTargets.length > 0 && (
        <div className="actions drawer-move">
          <select className="select" value="" disabled={busy}
            aria-label={`Move ${title} to lane`}
            onChange={(e) => {
              const target = e.target.value;
              if (target) onMove?.(target);
            }}>
            <option value="">Move to...</option>
            {moveTargets.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
      )}
      <div className="domain-drawer-fields">
        {fields.map((f) => (
          <div className="domain-field" key={f.name}>
            <div className="domain-field-label">{f.label}</div>
            <div className="domain-field-value"><FieldValue field={f} value={activeCard[f.name]} /></div>
          </div>
        ))}
      </div>
      {progress && <DomainProgressPanel progress={progress} onOpenChat={onOpenChat}
        onOpenPacket={onOpenPacket}
        onProgressChanged={(p) => { setProgress(p); onChanged(); }} />}
      {progressErr && <div className="error">progress: {progressErr}</div>}
      {verbs.length > 0 && (
        <>
          <h3>Actions</h3>
          <div className="actions">
            {verbs.map((verb) => actions?.dispatch_enabled ? (
              <button className="actbtn" key={verb} disabled={busy}
                onClick={() => run(verb)}>{verb.replace(/_/g, " ")}</button>
            ) : (
              <button className="actbtn" key={verb} disabled title="read-only deployment">
                {verb.replace(/_/g, " ")}
              </button>
            ))}
            {msg && <div className="actmsg">{msg}</div>}
          </div>
        </>
      )}
    </DrawerShell>
  );
}
function DomainsView({ refreshKey, activeDomain, onActiveDomainChange, onOpenChat }: {
  refreshKey: string;
  activeDomain: string;
  onActiveDomainChange: (domainId: string) => void;
  onOpenChat?: (prompt: string, conversationId?: string, storyTs?: string) => void;
}) {
  const [domains, setDomains] = useState<DomainSpec[]>([]);
  const [cards, setCards] = useState<Record<string, DomainCards>>({});
  const [actions, setActions] = useState<Record<string, DomainActions>>({});
  const [domainErrs, setDomainErrs] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [qByDomain, setQByDomain] = useState<Record<string, string>>({});
  const [statusByDomain, setStatusByDomain] = useState<Record<string, string>>({});
  const [automationByDomain, setAutomationByDomain] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<{ spec: DomainSpec; card: DomainCard } | null>(null);
  const [dragged, setDragged] = useState<{ spec: DomainSpec; card: DomainCard } | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showJobPresets, setShowJobPresets] = useState(false);
  const [jobBoardMode, setJobBoardMode] = useState<JobBoardMode>("manual");
  const [packetFor, setPacketFor] = useState<{ spec: DomainSpec; card: DomainCard } | null>(null);
  const [drawerTick, setDrawerTick] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const body = await fetchDomains();
      setDomains(body.domains);
      const cardPairs = await Promise.all(body.domains.map(async (d) => {
        try { return [d.domain_id, await fetchDomainCards(d.domain_id), ""] as const; }
        catch (e) { return [d.domain_id, null, (e as Error).message] as const; }
      }));
      const actionPairs = await Promise.all(body.domains.map(async (d) => {
        try { return [d.domain_id, await fetchDomainActions(d.domain_id)] as const; }
        catch { return [d.domain_id, { domain_id: d.domain_id, allowed_actions: [], dispatch_enabled: false }] as const; }
      }));
      setCards(Object.fromEntries(cardPairs.filter(([, pack]) => pack).map(([id, pack]) => [id, pack as DomainCards])));
      setActions(Object.fromEntries(actionPairs));
      setDomainErrs(Object.fromEntries(cardPairs.filter(([, , err]) => err).map(([id, , err]) => [id, err])));
    } catch (e) {
      setDomainErrs({ _registry: (e as Error).message });
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (loading && domains.length === 0) return <div className="loading">...</div>;
  if (domainErrs._registry) return <div className="error">ERR {domainErrs._registry}</div>;
  const spec = domains.find((d) => d.domain_id === activeDomain) ?? domains[0];
  if (!spec) return <div className="empty">No domain registry entries.</div>;
  const pack = cards[spec.domain_id];
  const q = qByDomain[spec.domain_id] ?? "";
  const status = statusByDomain[spec.domain_id] ?? "";
  const automationClass = automationByDomain[spec.domain_id] ?? "";
  const allCards = pack?.cards ?? [];
  const isJobDomain = spec.domain_id === "job_application";
  const statuses = Array.from(new Set(allCards.map((c) => valText(c.status)).filter(Boolean))).sort();
  const automationValues = isJobDomain
    ? Array.from(new Set(allCards.map((c) => valText(c.automation_class)).filter(Boolean))).sort()
    : [];
  const baseShown = allCards.filter((c) => cardMatchesDomain(c, q, status));
  const shown = baseShown.filter((c) =>
    !automationClass || valText(c.automation_class) === automationClass);
  const jobQueueSummary = isJobDomain
    ? ["bot_possible", "manual_required", "prepare_only"].map((value) => {
      const matching = allCards.filter((c) => valText(c.automation_class) === value);
      return {
        value,
        total: matching.length,
        suggested: matching.filter((c) => valText(c.status) === "Suggested Jobs").length,
        needsGeoff: matching.filter((c) => valText(c.status) === "Needs Geoff").length,
      };
    }).filter((row) => row.total > 0)
    : [];
  const configuredColumns = pack?.columns?.length ? pack.columns : spec.columns ?? [];
  const columnNames = [
    ...configuredColumns,
    ...statuses.filter((s) => !configuredColumns.includes(s)),
  ];
  const sectionCards = (classes: string[]) =>
    baseShown.filter((c) => classes.includes(valText(c.automation_class)));
  const jobSections = isJobDomain
    ? jobBoardMode === "bot"
      ? [{
        key: "bot",
        title: "Bot Board",
        hint: "Use this for jobs that can be prepared automatically. Take over in Needs Geoff to review, submit, and move to Completed.",
        cards: sectionCards(["bot_possible"]),
      }]
      : jobBoardMode === "manual"
      ? [{
        key: "manual",
        title: "Manual Board",
        hint: "Use this for jobs where the system found manual questions, portal blockers, or unclear workflows.",
        cards: sectionCards(["manual_required", "prepare_only"]),
      }]
      : [{
        key: "all",
        title: "All Jobs",
        hint: "Full pipeline view across every automation class.",
        cards: shown,
      }]
    : [{
      key: spec.domain_id,
      title: spec.title,
      hint: "",
      cards: shown,
    }];
  const activeSections = jobSections.filter((section) => section.cards.length > 0);
  const visibleCards = jobSections.reduce((n, section) => n + section.cards.length, 0);
  const hasUnstaged = jobSections.some((section) => section.cards.some((c) => !valText(c.status)));
  const boardColumns = hasUnstaged ? [...columnNames, "Unstaged"] : columnNames;
  const cardsForColumn = (cardsInSection: DomainCard[], name: string) => cardsInSection.filter((card) => {
    const cardStatus = valText(card.status);
    return name === "Unstaged" ? !cardStatus : cardStatus === name;
  });
  const domainActions = actions[spec.domain_id];
  const canMove = pack?.origin === "board_store" && !!domainActions?.dispatch_enabled;
  const writeBlockers = domainActions?.write_blockers ?? [];
  const moveHint = pack?.origin !== "board_store"
    ? "fixture and ledger domains are read-only"
    : writeBlockers.length
      ? `write blocked: ${writeBlockers[0]}`
      : domainActions?.dispatch_enabled
      ? "drag cards between configured lanes, or use Move to on mobile"
      : "dragging needs console mode: set KANBAN_UI_CHAT_ENABLED=1";
  const moveTargetsFor = (card: DomainCard) => {
    if (!canMove) return [];
    const status = valText(card.status);
    // one-step machine: the backend names the only legal next steps per lane
    // (jobs: found -> agent complete -> me complete, plus reject/undo)
    const allowed = pack?.transitions?.[status];
    if (allowed) return allowed;
    return boardColumns.filter((name) => name !== "Unstaged" && name !== status);
  };
  async function moveDomainCardTo(card: DomainCard, statusName: string) {
    if (!card || !canMove || statusName === "Unstaged") return;
    const id = cardId(card);
    setToast(null);
    try {
      const result = await moveDomainCard(spec.domain_id, id, statusName);
      const sideEffect = result.side_effect;
      const actualStatus = valText(result.card?.status) || statusName;
      const processed = sideEffect?.operation === "process_selected"
        ? Number(sideEffect.selected_count ?? 0)
        : 0;
      setToast(processed > 0
        ? `${result.card_id} -> ${actualStatus}; prepared ${processed} application packet${processed === 1 ? "" : "s"}`
        : `${result.card_id} -> ${actualStatus}`);
      await load();
    } catch (e) { setToast("ERR " + (e as Error).message); }
  }
  async function drop(statusName: string) {
    const card = dragged?.card;
    setOverCol(null); setDragged(null);
    if (!card) return;
    await moveDomainCardTo(card, statusName);
  }
  async function bulkAddBotJobs(count: number) {
    if (!window.confirm(
      `Move all ${count} bot-possible suggested job${count === 1 ? "" : "s"} to `
      + "Selected by Geoff? They'll queue for packet preparation.")) return;
    setToast(null);
    try {
      const r = await bulkSelectSuggested("bot_possible", "Selected by Geoff");
      setToast(`added ${r.moved_count} bot job${r.moved_count === 1 ? "" : "s"} to Selected by Geoff`);
      await load();
    } catch (e) { setToast("ERR " + (e as Error).message); }
  }

  return (
    <>
      <HorizontalScroller className="domain-tabs">
        {domains.map((d) => (
          <button key={d.domain_id} className={`tab ${d.domain_id === spec.domain_id ? "tab-on" : ""}`}
            onClick={() => onActiveDomainChange(d.domain_id)}>
            {d.title}<span className="tab-count">{cards[d.domain_id]?.cards.length ?? 0}</span>
          </button>
        ))}
      </HorizontalScroller>
      <div className="domain-head">
        <div>
          <h2>{spec.title}</h2>
          <div className="muted small">{visibleCards} of {allCards.length} cards · {spec.card_component}</div>
          <div className="muted small">{moveHint}</div>
        </div>
        {isJobDomain && (
          <button className="actbtn" onClick={() => setShowJobPresets(true)}>
            Search &amp; answers settings
          </button>
        )}
        {pack?.origin === "fixtures" && <span className="demo-badge">demo data</span>}
        {pack?.origin === "board_store" && <span className="live-badge">board store</span>}
        {pack?.origin === "ledger" && <span className="live-badge">ledger</span>}
      </div>
      {isJobDomain && (
        <HorizontalScroller className="job-board-controls" ariaLabel="Job board mode">
          {([
            ["manual", "Manual Board"],
            ["bot", "Bot Board"],
            ["all", "All Jobs"],
          ] as [JobBoardMode, string][]).map(([mode, label]) => (
            <button key={mode}
              className={`tab ${jobBoardMode === mode ? "tab-on" : ""}`}
              onClick={() => {
                setJobBoardMode(mode);
                if (mode !== "all") {
                  setAutomationByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
                }
              }}>
              {label}
            </button>
          ))}
        </HorizontalScroller>
      )}
      {jobQueueSummary.length > 0 && (
        <div className="job-queue-summary" aria-label="Job automation queues">
          {jobQueueSummary.map((row) => (
            <button key={row.value}
              className={`queue-chip ${
                (row.value === "bot_possible" && jobBoardMode === "bot")
                || (row.value !== "bot_possible" && jobBoardMode === "manual")
                  ? "queue-chip-on" : ""}`}
              onClick={() => {
                setJobBoardMode(row.value === "bot_possible" ? "bot" : "manual");
                setAutomationByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
              }}>
              <b>{titleToken(row.value)}</b>
              <span>{row.total} total</span>
              <span>{row.suggested} suggested</span>
              <span>{row.needsGeoff} needs Geoff</span>
            </button>
          ))}
        </div>
      )}
      {isJobDomain && (
        <div className="job-workflow-help">
          <div>
            <b>Needs Geoff</b>
            <span>Prepared packet is ready. Take over here, review materials, submit if right, then move to Completed.</span>
          </div>
          <div>
            <b>Bot Board</b>
            <span>Bot handles ranking and packet prep. Geoff handles final submit until a governed submit path is built.</span>
          </div>
          <div>
            <b>Manual Board</b>
            <span>Use this when self-ID, authorization, portal, salary, or unclear workflow questions require manual answers.</span>
          </div>
        </div>
      )}
      {toast && <div className={toast.startsWith("ERR") ? "error" : "actmsg"}>{toast}</div>}
      <div className="filterbar">
        <input className="search" placeholder="filter domain..." value={q}
          onChange={(e) => setQByDomain((m) => ({ ...m, [spec.domain_id]: e.target.value }))} />
        <select className="select" value={status}
          onChange={(e) => setStatusByDomain((m) => ({ ...m, [spec.domain_id]: e.target.value }))}>
          <option value="">any status</option>
          {statuses.map((s) => <option key={s}>{s}</option>)}
        </select>
        {automationValues.length > 0 && jobBoardMode === "all" && (
          <select className="select" value={automationClass}
            aria-label="Filter jobs by automation class"
            onChange={(e) => setAutomationByDomain((m) => ({ ...m, [spec.domain_id]: e.target.value }))}>
            <option value="">any automation</option>
            {automationValues.map((value) => <option key={value} value={value}>{titleToken(value)}</option>)}
          </select>
        )}
        {(q || status || automationClass || (isJobDomain && jobBoardMode !== "manual")) && (
          <button className="clear" onClick={() => {
            setQByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
            setStatusByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
            setAutomationByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
            setJobBoardMode("manual");
          }}>clear</button>
        )}
      </div>
      {domainErrs[spec.domain_id] ? <div className="error">ERR {domainErrs[spec.domain_id]}</div>
        : visibleCards === 0 ? <DomainEmpty spec={spec} />
        : boardColumns.length > 0 ? (
          <div className="domain-board-stack">
            {activeSections.map((section) => {
              return (
                <section className="domain-board-section" key={section.key}>
                  {isJobDomain && (() => {
                    // Bot Board: offer a one-click "add all" for the bot jobs
                    // still sitting unselected in Suggested Jobs
                    const botSuggested = section.key === "bot" && canMove
                      ? section.cards.filter((c) => valText(c.status) === "Suggested Jobs").length
                      : 0;
                    return (
                      <div className="domain-board-section-head">
                        <div>
                          <h3>{section.title}</h3>
                          <p>{section.hint}</p>
                        </div>
                        <div className="section-head-actions">
                          {botSuggested > 0 && (
                            <button className="actbtn"
                              onClick={() => void bulkAddBotJobs(botSuggested)}>
                              + Add all {botSuggested} bot job{botSuggested === 1 ? "" : "s"}
                            </button>
                          )}
                          <span>{section.cards.length} cards</span>
                        </div>
                      </div>
                    );
                  })()}
                  <HorizontalScroller className="domain-kanban"
                    ariaLabel={`${section.title} lane scroll`}>
                    {boardColumns.map((name) => {
                      const colCards = cardsForColumn(section.cards, name);
                      return (
                        <div className={`domain-column ${overCol === name ? "col-over" : ""}`} key={name}
                          onDragOver={(e) => {
                            if (canMove && dragged && name !== "Unstaged") {
                              e.preventDefault(); setOverCol(name);
                            }
                          }}
                          onDragLeave={() => setOverCol((cur) => (cur === name ? null : cur))}
                          onDrop={() => drop(name)}>
                          <div className="domain-column-head">
                            <span className={`dot status-${statusToken(name)}`} />{name}
                            <span className="count">{colCards.length}</span>
                          </div>
                          <div className="domain-column-body">
                            {colCards.map((card) => (
                              <DomainCardTile key={cardId(card)} spec={spec} card={card}
                                canDrag={canMove} onDragStart={() => setDragged({ spec, card })}
                                moveTargets={moveTargetsFor(card)}
                                onMove={(target) => void moveDomainCardTo(card, target)}
                                onOpenPacket={isJobDomain && card.application_id
                                  ? () => setPacketFor({ spec, card })
                                  : undefined}
                                onOpen={() => setSelected({ spec, card })} />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </HorizontalScroller>
                </section>
              );
            })}
          </div>
        )
        : (
          <div className="domain-grid">
            {shown.map((card) => (
              <DomainCardTile key={cardId(card)} spec={spec} card={card}
                canDrag={canMove} onDragStart={() => setDragged({ spec, card })}
                moveTargets={moveTargetsFor(card)}
                onMove={(target) => void moveDomainCardTo(card, target)}
                onOpenPacket={isJobDomain && card.application_id
                  ? () => setPacketFor({ spec, card })
                  : undefined}
                onOpen={() => setSelected({ spec, card })} />
            ))}
          </div>
        )}
      {selected && (
        <DomainDrawer spec={selected.spec} card={selected.card}
          actions={actions[selected.spec.domain_id]}
          moveTargets={selected.spec.domain_id === spec.domain_id ? moveTargetsFor(selected.card) : []}
          onMove={(target) => void moveDomainCardTo(selected.card, target)}
          onChanged={load}
          refreshTick={drawerTick}
          onClose={() => setSelected(null)} onOpenChat={onOpenChat}
          onOpenPacket={selected.spec.domain_id === "job_application"
            ? () => setPacketFor(selected)
            : undefined} />
      )}
      {packetFor && (
        <PacketReviewModal spec={packetFor.spec} card={packetFor.card}
          onChanged={() => { setDrawerTick((t) => t + 1); void load(); }}
          onOpenChatAt={onOpenChat
            ? (ts) => {
              onOpenChat("",
                `${packetFor.spec.domain_id}:${cardId(packetFor.card)}`, ts);
              setPacketFor(null);
            }
            : undefined}
          onClose={() => setPacketFor(null)} />
      )}
      {showJobPresets && <JobPresetDrawer onClose={() => setShowJobPresets(false)} />}
    </>
  );
}

// ---- drawers --------------------------------------------------------------
function EventRow({ ev }: { ev: MissionEvent }) {
  return (
    <div className="event">
      <div className="event-head">
        <span className={`tag tag-${ev.kind}`}>{ev.kind}</span>
        {ev.ts && <span className="muted small">{String(ev.ts).slice(11, 19)}</span>}
      </div>
      <pre>{JSON.stringify(ev.payload ?? {}, null, 0).slice(0, 400)}</pre>
    </div>
  );
}

function MissionDrawer({ id, ledgerUi, onClose }: {
  id: string; ledgerUi: string; onClose: () => void;
}) {
  const [detail, setDetail] = useState<MissionDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetchMission(id).then((d) => live && setDetail(d))
      .catch((e) => live && setErr((e as Error).message));
    return () => { live = false; };
  }, [id]);
  const events = detail?.events ?? [];
  const mission = (detail?.mission ?? {}) as Record<string, unknown>;
  const approvals = detail?.approvals ?? [];
  const chain = events.filter((e) => ["model_call", "judge_verdict"].includes(e.kind));
  const risk = String(mission.risk ?? "");
  const needsApproval = ["L3", "L4"].includes(risk) ||
    String(mission.status ?? "") === "awaiting_approval";
  return (
    <DrawerShell title={id} onClose={onClose}>
      {err && <div className="error">⚠ {err}</div>}
      {!detail && !err && <div className="loading">…</div>}
      {detail && (
        <>
          <div className="kv">status <b>{String(mission.status ?? "—")}</b> · risk{" "}
            <b className={`risk ${RISK_CLASS[risk] ?? ""}`}>{risk || "—"}</b>
            {mission.repo ? <> · <b>{String(mission.repo)}</b></> : null}</div>
          <div className="card-action">{String(mission.action ?? "")}</div>
          {needsApproval && ledgerUi && (
            <a className="ledger-link" href={ledgerUi} target="_blank" rel="noreferrer">
              Open in Ledger to approve / kill ↗
            </a>
          )}
          {needsApproval && !ledgerUi && (
            <div className="muted small">approve / kill is signed in the Ledger UI (set LEDGER_UI_URL to link it)</div>
          )}
          {chain.length > 0 && (
            <>
              <h3>Routing / agent chain ({chain.length})</h3>
              <div className="events">{chain.map((ev, i) => <EventRow key={i} ev={ev} />)}</div>
            </>
          )}
          {approvals.length > 0 && (
            <>
              <h3>Approvals ({approvals.length})</h3>
              <div className="events">
                {approvals.map((a, i) => (
                  <div className="event" key={i}><pre>{JSON.stringify(a, null, 0).slice(0, 300)}</pre></div>
                ))}
              </div>
            </>
          )}
          <h3>Timeline ({events.length})</h3>
          <div className="events">
            {events.length === 0 && <div className="muted">no events yet</div>}
            {events.map((ev, i) => <EventRow key={i} ev={ev} />)}
          </div>
        </>
      )}
    </DrawerShell>
  );
}

const ACTIONS: Record<string, { verb: string; label: string }[]> = {
  mission_intake: [
    { verb: "stage_card", label: "Stage → Ready" },
    { verb: "block_card", label: "Block" },
    { verb: "reject_card", label: "Reject" },
  ],
  todos: [
    { verb: "start_todo", label: "Start" },
    { verb: "finish_todo", label: "Finish" },
    { verb: "block_todo", label: "Block" },
  ],
};

// Fields the console can't edit via set_item_field (Status has the move control;
// keys/writeback are server-refused anyway — we just don't offer an editor).
const UNEDITABLE = new Set(["Status", "CardKey", "MissionID", "LastSync"]);

function FieldRow({ board, title, name, value, canAct, onResult }: {
  board: string; title: string; name: string; value: string;
  canAct: boolean; onResult: (r: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);
  const [shown, setShown] = useState(value);   // optimistic display after a save
  const [busy, setBusy] = useState(false);
  const editable = canAct && !UNEDITABLE.has(name);
  async function save() {
    setBusy(true);
    try {
      const r = await postAction("set_item_field",
        { database: board, title, field: name, value: val });
      onResult(r.result);
      setShown(val); setEditing(false);   // source of truth re-fetches behind us
    } catch (e) { onResult("⚠ " + (e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <tr>
      <td className="fk">{name}</td>
      <td>
        {!editing ? (
          <span className="fieldval">
            {shown}
            {editable && <button className="editbtn" onClick={() => { setVal(shown); setEditing(true); }}>edit</button>}
          </span>
        ) : (
          <span className="fieldedit">
            <input value={val} onChange={(e) => setVal(e.target.value)} disabled={busy}
              onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}
              autoFocus />
            <button onClick={save} disabled={busy}>save</button>
            <button onClick={() => setEditing(false)}>cancel</button>
          </span>
        )}
      </td>
    </tr>
  );
}

function CardDrawer({ board, card, statuses, canAct, onChanged, onClose }: {
  board: string; card: BoardCard; statuses: string[]; canAct: boolean;
  onChanged: () => void; onClose: () => void;
}) {
  const fields = card.fields ?? {};
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const verbs = ACTIONS[board] ?? [];
  const current = String(fields.Status ?? "");
  function result(r: string) { setMsg(r); onChanged(); }
  async function call(action: string, params: Record<string, unknown>) {
    setBusy(true); setMsg(null);
    try { result((await postAction(action, params)).result); }
    catch (e) { setMsg("⚠ " + (e as Error).message); }
    finally { setBusy(false); }
  }
  const runVerb = (verb: string) =>
    call(verb, board === "todos" ? { task: card.title } : { title: card.title });
  const moveTo = (status: string) =>
    call("move_item", { database: board, title: card.title, status });
  const addNote = () => {
    if (!note.trim()) return;
    call("annotate_item", { database: board, title: card.title, note });
    setNote("");
  };
  return (
    <DrawerShell title={card.title || "(untitled)"} onClose={onClose}>
      <div className="kv">board <b>{board}</b>{current && <> · status <b>{current}</b></>}</div>
      {canAct && (
        <div className="actions">
          {verbs.map((v) => (
            <button key={v.verb} className="actbtn" disabled={busy}
              onClick={() => runVerb(v.verb)}>{v.label}</button>
          ))}
          {statuses.length > 0 && (
            <select className="select" disabled={busy} value=""
              onChange={(e) => e.target.value && moveTo(e.target.value)}>
              <option value="">Move to…</option>
              {statuses.filter((s) => s !== current).map((s) => <option key={s}>{s}</option>)}
            </select>
          )}
          {msg && <div className="actmsg">{msg}</div>}
        </div>
      )}
      <h3>Fields {canAct && <span className="muted small">— click edit to change a field</span>}</h3>
      <table className="fields">
        <tbody>
          {Object.entries(fields).map(([k, v]) => (
            <FieldRow key={k} board={board} title={card.title} name={k}
              value={String(v)} canAct={canAct} onResult={result} />
          ))}
          {Object.keys(fields).length === 0 && (
            <tr><td className="muted">no extra fields</td></tr>
          )}
        </tbody>
      </table>
      {canAct && (
        <div className="noteadd">
          <input value={note} placeholder="add a dated note…"
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") addNote(); }} />
          <button onClick={addNote} disabled={busy || !note.trim()}>+ Note</button>
        </div>
      )}
    </DrawerShell>
  );
}

function DrawerShell({ title, onClose, children }: {
  title: string; onClose: () => void; children: ReactNode;
}) {
  return (
    <div className="drawer-bg" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <span className="card-id">{title}</span>
          <button className="x" onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ---- chat (the console as a channel) --------------------------------------
type ChatThread = {
  id: string;
  title: string;
  updatedAt: string;
  target?: string;
  lastPrompt?: string;
};
const CHAT_THREADS_KEY = "agent-kanban-cockpit.chatThreads.v1";

function loadChatThreads(): ChatThread[] {
  try {
    const raw = window.localStorage.getItem(CHAT_THREADS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((t) => t && typeof t.id === "string" && typeof t.title === "string")
      .slice(0, 12);
  } catch {
    return [];
  }
}

function saveChatThreads(threads: ChatThread[]) {
  try { window.localStorage.setItem(CHAT_THREADS_KEY, JSON.stringify(threads.slice(0, 12))); }
  catch { /* browser storage can be unavailable in private modes */ }
}

function chatTitle(text: string) {
  const trimmed = text.replace(/\s+/g, " ").trim();
  if (!trimmed) return "Cockpit chat";
  return trimmed.length > 54 ? `${trimmed.slice(0, 51)}...` : trimmed;
}

function upsertChatThread(threads: ChatThread[], next: ChatThread) {
  return [next, ...threads.filter((t) => t.id !== next.id)].slice(0, 12);
}

function mergeChatThreads(...groups: ChatThread[][]) {
  const merged = new Map<string, ChatThread>();
  groups.flat().forEach((thread) => {
    if (!thread.id) return;
    const prev = merged.get(thread.id);
    if (!prev || thread.updatedAt > prev.updatedAt) merged.set(thread.id, thread);
  });
  return [...merged.values()]
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    .slice(0, 12);
}

function serverThreadToLocal(thread: {
  conversation_id?: string; id?: string; title: string; updated_at: string;
  target?: string; last_prompt?: string; model?: string;
}): ChatThread {
  return {
    id: thread.conversation_id || thread.id || "app",
    title: thread.title,
    updatedAt: thread.updated_at,
    target: thread.target || "GatewayCore",
    lastPrompt: thread.last_prompt,
  };
}

function newConversationId() {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  return `cockpit-${stamp}`;
}

function fmtThreadTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function ChatLine({ ev }: { ev: ChatEvent }) {
  switch (ev.type) {
    case "history": return <div className="cl round">{String(ev.content)}</div>;
    case "you": return <div className="cl you">{String(ev.content)}</div>;
    case "final": return <div className="cl final">{String(ev.content)}</div>;
    case "error": return <div className="cl err">⚠ {String(ev.message ?? ev.detail)}</div>;
    case "round": return <div className="cl round">— round {String(ev.n)} —</div>;
    case "tool": {
      let a = String(ev.args ?? "");
      try { a = Object.values(JSON.parse(a)).map(String).join(", "); }
      catch { /* not JSON — show the raw arg string as-is */ }
      return <div className="cl tool">▸ <b>{String(ev.name)}</b> {a}</div>;
    }
    case "tool_result":
      return <div className="cl res">← {String(ev.result)}</div>;
    default: return <div className="cl">{JSON.stringify(ev)}</div>;
  }
}

// which task family a conversation belongs to, from its scoped id
// (job_application:job_x -> jobs; repo:llm_station -> repo; plain ids -> chat)
const CONV_KINDS: Record<string, string> = {
  job_application: "job", linkedin_post: "post", paper: "paper", book: "book",
  repo: "repo", dag: "dag", machine_upkeep: "upkeep", mission: "mission",
};
function conversationKind(id: string): string {
  if (!id.includes(":")) return "chat";
  return CONV_KINDS[id.split(":", 1)[0]] ?? "chat";
}

function ChatRuntimePanel({ runtime, conversations, activeId, onOpenConversation, onStartRepoChat, onDeleteConversation }: {
  runtime: ChatRuntime | null;
  conversations: ChatConversation[];
  activeId: string;
  onOpenConversation: (id: string) => void;
  onStartRepoChat: (repo: { repo_id: string; remote_url: string }) => void;
  onDeleteConversation: (id: string) => void;
}) {
  if (!runtime) return <div className="loading">loading chat runtime...</div>;
  const candidates = runtime.chat_role?.candidates ?? [];
  const repos = runtime.repos ?? [];
  return (
    <div className="chat-runtime">
      <div className="metric diag-card">
        <div className="diag-head">All Chats</div>
        <p className="muted small">
          Every recorded conversation, across every surface — tap one to read
          its full story. Scoped chats carry their task badge.
        </p>
        {conversations.length === 0 && (
          <div className="muted small">
            Nothing recorded yet — send a message anywhere (cockpit, Discord,
            CLI) and it lands here.
          </div>
        )}
        <div className="conv-list">
          {conversations.map((c) => (
            <div
              className={`conv-row ${c.conversation_id === activeId ? "thread-on" : ""}`}
              key={c.conversation_id}>
              <button className="conv-open"
                onClick={() => onOpenConversation(c.conversation_id)}>
                <span className="conv-title">
                  <Badge value={conversationKind(c.conversation_id)} />
                  {c.title || c.conversation_id}
                </span>
                <span className="muted small">
                  {c.turns} turn{c.turns === 1 ? "" : "s"}
                  {c.surfaces.length ? ` · ${c.surfaces.join("/")}` : ""}
                  {c.last_ts ? ` · ${fmtThreadTime(c.last_ts)}` : ""}
                </span>
                {c.last_user_text && (
                  <span className="conv-preview muted small">{c.last_user_text}</span>
                )}
              </button>
              <button className="conv-del"
                title="delete this chat's history (thread + transcript). Card and board history stays."
                onClick={() => onDeleteConversation(c.conversation_id)}>
                ×
              </button>
            </div>
          ))}
        </div>
      </div>
      <div className="metric diag-card">
        <div className="diag-head">New Scoped Chat</div>
        <p className="muted small">
          Start a conversation anchored to a registered repo — everything the
          agents do for it stays reviewable under one thread.
        </p>
        <div className="conv-list">
          {repos.map((r) => (
            <div className="conv-row" key={r.repo_id}>
              <button className="conv-open" onClick={() => onStartRepoChat(r)}>
                <span className="conv-title"><Badge value="repo" />{r.repo_id}</span>
                <span className="muted small">{r.remote_url || "local"}</span>
              </button>
            </div>
          ))}
          {repos.length === 0 && (
            <div className="muted small">
              No registered repos — <code>uv run cc onboard repo --path &lt;path&gt;</code>
            </div>
          )}
        </div>
        <RegisterRepoCard />
      </div>
      <div className="metric diag-card">
        <div className="diag-head">Models + Runtime</div>
        <div className="diag-row"><span>harness</span><code>{runtime.harness}</code></div>
        <div className="diag-row"><span>gateway</span><code>{runtime.model_gateway}</code></div>
        <div className="diag-row"><span>stream</span><code>{runtime.stream_endpoint}</code></div>
        <div className="domain-badges">
          {candidates.map((c) => <Badge key={c.alias} value={`${c.alias}: ${c.model}`} />)}
        </div>
        <p className="muted small">{runtime.provider_note}</p>
      </div>
      <div className="metric diag-card">
        <div className="diag-head">Frontier lane (paid, opt-in)</div>
        <p className="muted small">{runtime.frontier_note}</p>
        <div className="conv-list">
          {(runtime.frontier_models ?? []).map((f) => (
            <div className="conv-row" key={f.model_id}>
              <div className="conv-open" style={{ cursor: "default" }}>
                <span className="conv-title">
                  <Badge value={f.selectable ? "ready" : "not enabled"}
                    tone={f.selectable ? "good" : "warn"} />
                  {f.model_id}
                </span>
                <span className="muted small">
                  {f.provider}
                  {f.estimated_cost_per_turn_usd != null
                    ? ` · ~$${f.estimated_cost_per_turn_usd.toFixed(4)}/turn est.`
                    : ""}
                  {f.context_tokens ? ` · ${(f.context_tokens / 1000).toFixed(0)}k ctx` : ""}
                </span>
              </div>
            </div>
          ))}
          {(runtime.frontier_models ?? []).length === 0 && (
            <div className="muted small">
              No frontier candidates configured — see configs/frontier-router-providers.yaml.
            </div>
          )}
        </div>
      </div>
      <div className="metric diag-card">
        <div className="diag-head">Local Frontier lane (experimental)</div>
        <p className="muted small">{runtime.local_frontier_note}</p>
        <div className="conv-list">
          {(runtime.local_frontier_models ?? []).map((f) => (
            <div className="conv-row" key={f.model_id}>
              <div className="conv-open" style={{ cursor: "default" }}>
                <span className="conv-title">
                  <Badge value={f.selectable ? "ready" : f.health}
                    tone={f.selectable ? "good" : "warn"} />
                  {f.model_id}
                </span>
                <span className="muted small">
                  {f.provider} · local · text only · no tools
                  {f.context_tokens ? ` · ${(f.context_tokens / 1000).toFixed(0)}k ctx` : ""}
                  {f.disk_footprint_gb ? ` · ${f.disk_footprint_gb}GB on disk` : ""}
                  {f.measured?.median_tokens_per_second != null
                    ? ` · measured ${f.measured.median_tokens_per_second.toFixed(2)} tok/s`
                    : f.expected_tokens_per_second
                    ? ` · ${f.expected_tokens_per_second.low}-${f.expected_tokens_per_second.high} tok/s (unverified, self-reported)`
                    : ""}
                </span>
              </div>
            </div>
          ))}
          {(runtime.local_frontier_models ?? []).length === 0 && (
            <div className="muted small">
              No local-frontier candidates configured — see configs/local-frontier-providers.yaml.
            </div>
          )}
        </div>
      </div>
      <div className="metric diag-card">
        <div className="diag-head">Executors (not chat models)</div>
        <p className="muted small">{runtime.executor_note}</p>
        <div className="domain-badges">
          {runtime.executors.map((e) => <Badge key={e.name} value={`${e.name} #${e.priority}`} />)}
        </div>
      </div>
    </div>
  );
}

// Register a new work repo without leaving the cockpit — mirrors `cc
// repo-register`. Collapsed by default so the repo list stays the focus;
// "preview" always works (validates + shows the manifest block, writes
// nothing), "commit" needs the same KANBAN_UI_DOMAIN_CONFIG_WRITES=1 opt-in
// as every other config editor in the cockpit and surfaces that requirement
// as a plain error if it isn't set, rather than hiding the button.
function RegisterRepoCard() {
  const [open, setOpen] = useState(false);
  const [boards, setBoards] = useState<BoardRegistryBoard[]>([]);
  const [repoId, setRepoId] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [remoteUrl, setRemoteUrl] = useState("");
  const [board, setBoard] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RepoRegisterResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    fetchBoardRegistry()
      .then((r) => {
        setBoards(r.boards);
        setBoard((current) => current || r.boards[0]?.board_id || "");
      })
      .catch(() => {});
  }, [open]);

  const canSubmit = !!(repoId.trim() && localPath.trim() && remoteUrl.trim() && board);

  async function run(apply: boolean) {
    setBusy(true);
    setErr(null);
    try {
      setResult(await registerRepo({
        repo_id: repoId.trim(), local_path: localPath.trim(),
        remote_url: remoteUrl.trim(), kanban_board: board, apply,
      }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="clear" onClick={() => setOpen(true)}>+ register a repo</button>
    );
  }
  return (
    <div className="settings-form">
      <label>repo_id
        <input value={repoId} onChange={(e) => setRepoId(e.target.value)}
          placeholder="my-other-repo" />
      </label>
      <label>local path (kept out of git — stored as an env var name only)
        <input value={localPath} onChange={(e) => setLocalPath(e.target.value)}
          placeholder="C:\path\to\repo" />
      </label>
      <label>remote_url
        <input value={remoteUrl} onChange={(e) => setRemoteUrl(e.target.value)}
          placeholder="https://github.com/owner/repo" />
      </label>
      <label>kanban board
        <select className="select" value={board} onChange={(e) => setBoard(e.target.value)}>
          {boards.length === 0 && <option value="">no boards registered yet</option>}
          {boards.map((b) => <option key={b.board_id} value={b.board_id}>{b.board_id}</option>)}
        </select>
      </label>
      <div className="preset-actions">
        <button className="actbtn" disabled={busy || !canSubmit}
          onClick={() => run(false)}>preview</button>
        {result?.status === "validated_dry_run" && (
          <button className="actbtn" disabled={busy}
            title="commits the disabled manifest to configs/autonomy.yaml"
            onClick={() => run(true)}>commit</button>
        )}
        <button className="clear" disabled={busy}
          onClick={() => { setOpen(false); setResult(null); setErr(null); }}>close</button>
      </div>
      {err && <div className="error small">ERR {err}</div>}
      {result && (
        <div className="muted small">
          <div>status: <b>{result.status}</b></div>
          {!!result.blockers?.length && <div>blockers: {result.blockers.join(", ")}</div>}
          {result.next && <div>next: {result.next}</div>}
          {result.status === "registered" && (
            <div>
              Registered (disabled until verified). Set <code>{result.local_path_env}</code>
              {"="}{result.local_path_runtime_value} in .env, then run{" "}
              <code>cc repo-verify --repo-id {result.repo_id}</code>.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Replay recorded turns as live-log events (same truncation as the SSE
// stream) so reopening a thread shows its conversation instead of a blank
// log; the Full story view keeps the untruncated record.
function turnsToEvents(turns: TranscriptTurn[]): ChatEvent[] {
  const events: ChatEvent[] = [];
  for (const turn of turns) {
    if (turn.corrupt_line) continue;   // partial JSONL append — nothing to replay
    if (turn.user_text) events.push({ type: "you", content: turn.user_text });
    for (const ev of turn.events ?? []) {
      if (ev.type === "tool") {
        events.push({ type: "tool", name: ev.name, args: (ev.args ?? "").slice(0, 200) });
      } else if (ev.type === "tool_result") {
        events.push({ type: "tool_result", name: ev.name, result: (ev.result ?? "").slice(0, 300) });
      }
    }
    events.push({ type: "final", content: turn.final ?? "(no final answer recorded)" });
  }
  return events;
}

function ThreadTimeline({ transcript, loading, error, onRefresh, onLoadAll,
  focusTs, onFocused }: {
  transcript: ChatTranscriptResponse | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onLoadAll?: (totalTurns: number) => void;
  focusTs?: string | null;
  onFocused?: () => void;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // card-story click-through: land ON that moment in the timeline
    if (!focusTs || !transcript) return;
    const nodes = Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>("[data-ts]") ?? []);
    const target = nodes.find((el) => (el.dataset.ts ?? "") >= focusTs)
      ?? nodes[nodes.length - 1] ?? null;
    if (!target) return;
    if (target instanceof HTMLDetailsElement) target.open = true;
    target.scrollIntoView({ block: "center" });
    target.classList.add("story-focus");
    onFocused?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusTs, transcript]);
  if (error) return <div className="muted">ERR {error}</div>;
  if (!transcript) return <div className="muted">{loading ? "loading the full story..." : "no story loaded"}</div>;
  const total = transcript.total_turns ?? transcript.turn_count;
  const cardStory = transcript.card_story ?? [];
  // one chronological timeline: card history (board moves, agent attempts,
  // submission evidence) interleaved with the recorded chat turns
  const rows = [
    ...transcript.turns.map((turn, idx) => (
      { ts: turn.ts ?? "", kind: "turn" as const, turn, idx })),
    ...cardStory.map((entry) => (
      { ts: entry.ts ?? "", kind: "story" as const, entry })),
  ].sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  return (
    <div className="chat-story" ref={rootRef}>
      <div className="chat-story-head muted small">
        <span>
          full story — {total} recorded turn{total === 1 ? "" : "s"}
          {cardStory.length ? ` + ${cardStory.length} card moment${cardStory.length === 1 ? "" : "s"}` : ""}
          {transcript.turn_count < total ? ` (newest ${transcript.turn_count} shown)` : ""}
          {" "}(flight recorder{transcript.recording_enabled ? "" : " — recording OFF (GATEWAY_TRANSCRIPTS=0)"})
        </span>
        <span>
          {transcript.turn_count < total && onLoadAll && (
            <button className="clear" disabled={loading}
              onClick={() => onLoadAll(total)}>show all {total}</button>
          )}
          <button className="clear" onClick={onRefresh} disabled={loading}>
            {loading ? "…" : "refresh"}
          </button>
        </span>
      </div>
      {rows.length === 0 && (
        <div className="muted">
          Nothing recorded for this thread yet. Turns are recorded from the moment the
          flight recorder shipped — older conversations are not back-filled. Send a
          message, then refresh.
        </div>
      )}
      {rows.map((row, i) => {
        if (row.kind === "story") {
          const s = row.entry;
          const head = (
            <>
              <span className="story-time">{fmtThreadTime(s.ts)}</span>
              <Badge value={s.kind} />
              <b>{s.title}</b>
              <span className="muted small">{s.summary}</span>
            </>
          );
          return s.detail ? (
            <details className={`story-row story-${s.kind}`} key={i}
              data-ts={s.ts}>
              <summary>{head}</summary>
              <pre className="packet-doc">{s.detail}</pre>
            </details>
          ) : (
            <div className={`story-row story-${s.kind}`} key={i}
              data-ts={s.ts}>{head}</div>
          );
        }
        const { turn, idx: turnIdx } = row;
        if (turn.corrupt_line) {
          return (
            <div className="story-row story-note muted small" key={i}>
              one recorded line was corrupt (partial write) and was skipped
            </div>
          );
        }
        const turnEvents = turn.events ?? [];
        const blocks = turn.context_blocks ?? [];
        const tools = turnEvents.filter((ev) => ev.type === "tool").length;
        return (
          <details className="story-row story-turn" key={i}
            data-ts={turn.ts ?? ""}
            open={turnIdx === transcript.turns.length - 1}>
            <summary>
              <span className="story-time">{fmtThreadTime(turn.ts ?? "")}</span>
              <Badge value={turn.surface || "app"} />
              <b>{turn.user_text ? (turn.user_text.length > 90 ? turn.user_text.slice(0, 87) + "..." : turn.user_text) : "(no user text)"}</b>
              <span className="muted small">{turn.model_role}{tools ? ` · ${tools} tool call${tools === 1 ? "" : "s"}` : ""}</span>
            </summary>
            <div className="story-turn-body">
              {blocks.length > 0 && (
                <div className="muted small">context injected: {blocks.join(", ")}</div>
              )}
              {turn.user_text && <pre className="packet-doc story-user">{turn.user_text}</pre>}
              {turnEvents.map((ev, j) => {
                if (ev.type === "round") {
                  return <div className="muted small story-round" key={j}>— round {ev.n} —</div>;
                }
                if (ev.type === "tool" || ev.type === "tool_result") {
                  const payload = ev.type === "tool" ? ev.args : ev.result;
                  return (
                    <details className="story-ev" key={j}>
                      <summary>
                        <span className="story-time">{fmtThreadTime(ev.ts ?? "")}</span>
                        <Badge value={ev.type === "tool" ? "call" : "result"} />
                        <code>{ev.name}</code>
                      </summary>
                      <pre>{payload || "(empty)"}</pre>
                    </details>
                  );
                }
                return (
                  <details className="story-ev" key={j}>
                    <summary><Badge value={ev.type} /></summary>
                    <pre>{JSON.stringify(ev, null, 2)}</pre>
                  </details>
                );
              })}
              <div className="story-row story-final">
                <b>final</b>
                <pre className="packet-doc">{turn.final ?? "(no final answer recorded)"}</pre>
              </div>
            </div>
          </details>
        );
      })}
    </div>
  );
}

function ChatView({ roles, runtime, draft, onBack }: {
  roles: string[];
  runtime: ChatRuntime | null;
  draft?: { text: string; nonce: number; conversationId?: string;
            storyTs?: string } | null;
  onBack?: () => void;
}) {
  const [model, setModel] = useState(roles.includes("chat") ? "chat" : roles[0] ?? "");
  const [conversationId, setConversationId] = useState("app");
  const [historyOpen, setHistoryOpen] = useState(false);
  // which agent we're talking to: GatewayCore (in-app) or a configured
  // external specialist (ORCA/OmniAgent/OxyGent) opened in its own tab
  const [target, setTarget] = useState("GatewayCore");
  const [input, setInput] = useState("");
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>(() => loadChatThreads());
  const [busy, setBusy] = useState(false);
  const [chatMode, setChatMode] = useState<"live" | "story">("live");
  const [story, setStory] = useState<ChatTranscriptResponse | null>(null);
  const [storyLoading, setStoryLoading] = useState(false);
  const [storyError, setStoryError] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [focusTs, setFocusTs] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  // guards hydration races: a slow transcript fetch for a thread the user has
  // already left must not fill the current thread's log
  const conversationIdRef = useRef(conversationId);
  useEffect(() => { conversationIdRef.current = conversationId; }, [conversationId]);
  useEffect(() => { endRef.current?.scrollIntoView(); }, [events]);
  function loadConversations() {
    fetchChatConversations()
      .then((body) => setConversations(body.conversations))
      .catch(() => { /* the review index is optional; chat works without it */ });
  }
  useEffect(() => { loadConversations(); }, []);
  useEffect(() => {
    if (!roles.length) return;
    setModel((current) => (
      roles.includes(current) ? current : roles.includes("chat") ? "chat" : roles[0]
    ));
  }, [roles]);
  useEffect(() => {
    let cancelled = false;
    fetchChatThreads()
      .then((body) => {
        if (cancelled) return;
        const serverThreads = body.threads.map(serverThreadToLocal);
        setThreads((current) => {
          const next = mergeChatThreads(serverThreads, current);
          saveChatThreads(next);
          return next;
        });
      })
      .catch(() => { /* localStorage remains the fallback cache */ });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    if (draft?.text) setInput(draft.text);
    if (!draft?.conversationId) return;
    const changed = draft.conversationId !== conversationIdRef.current;
    if (changed) {
      conversationIdRef.current = draft.conversationId;
      setConversationId(draft.conversationId);
      setEvents([]);
      setStory(null);
      setStoryError(null);
    }
    if (draft.storyTs) {
      // a card-story click-through: open the full story AT that moment
      setFocusTs(draft.storyTs);
      setChatMode("story");
      void loadStory(draft.conversationId);
    } else if (changed) {
      setChatMode("live");
      void hydrateThread(draft.conversationId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.conversationId, draft?.nonce, draft?.text, draft?.storyTs]);
  useEffect(() => {
    // first mount: replay whatever the flight recorder has for the default
    // thread, so a reload (or another device) still shows the conversation
    void hydrateThread(conversationIdRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function hydrateThread(id: string) {
    try {
      const t = await fetchChatTranscript(id);
      if (conversationIdRef.current !== id) return;   // user moved on
      setStory(t);
      if (!t.turns.length) return;
      setEvents((current) => current.length ? current : [
        { type: "history", content: "replayed from the flight recorder — open full story for tool-level detail" },
        ...turnsToEvents(t.turns),
      ]);
    } catch { /* recorder is optional — live chat works without it */ }
  }

  function persistThread(thread: ChatThread, modelRole = model) {
    void saveChatThread({
      conversation_id: thread.id,
      title: thread.title,
      target: thread.target,
      // server metadata keeps a 2000-char preview; longer pastes would 422
      last_prompt: (thread.lastPrompt ?? "").slice(0, 2000),
      model: modelRole,
    })
      .then((body) => {
        const serverThreads = body.threads.map(serverThreadToLocal);
        setThreads((current) => {
          const next = mergeChatThreads(serverThreads, current);
          saveChatThreads(next);
          return next;
        });
      })
      .catch(() => { /* server thread sync is best-effort; chat still works */ });
  }

  function rememberThread(id: string, text: string, target = "GatewayCore") {
    const thread = {
      id,
      title: chatTitle(text),
      updatedAt: new Date().toISOString(),
      target,
      lastPrompt: text,
    };
    setThreads((current) => {
      const next = upsertChatThread(current, thread);
      saveChatThreads(next);
      return next;
    });
    persistThread(thread);
  }

  function startNewChat() {
    const id = newConversationId();
    conversationIdRef.current = id;
    setConversationId(id);
    setInput("");
    setEvents([]);
    setChatMode("live");
    setStory(null);
    setStoryError(null);
    const thread = {
      id,
      title: "New cockpit chat",
      updatedAt: new Date().toISOString(),
      target: "GatewayCore",
    };
    setThreads((current) => {
      const next = upsertChatThread(current, thread);
      saveChatThreads(next);
      return next;
    });
    // local chip only — the server thread is persisted on the first send
    // (rememberThread), so abandoned empty chats don't pile up cross-device
  }

  function openThread(thread: ChatThread, mode: "live" | "story" = chatMode) {
    conversationIdRef.current = thread.id;
    setConversationId(thread.id);
    if (thread.lastPrompt) setInput(thread.lastPrompt);
    setEvents([]);
    setStory(null);
    setStoryError(null);
    setFocusTs(null);
    setChatMode(mode);
    if (mode === "story") void loadStory(thread.id);
    else void hydrateThread(thread.id);
  }

  function openConversation(id: string) {
    // review-first: any conversation from the index opens on its full story
    const thread = threads.find((t) => t.id === id)
      ?? { id, title: id, updatedAt: "", target: "GatewayCore" };
    openThread(thread, "story");
  }

  async function deleteConversation(id: string) {
    if (!window.confirm(
      `Delete the chat history for "${id}"?\n\nThis removes the thread and its `
      + "recorded transcript. Card/board history (the governed event log) is "
      + "kept.")) return;
    try {
      const result = await deleteChatConversation(id);
      const local = threads.filter((t) => t.id !== id);
      setThreads(local);
      saveChatThreads(local);
      setConversations((current) =>
        current.filter((c) => c.conversation_id !== id));
      void result;
      if (conversationIdRef.current === id) startNewChat();
      loadConversations();
    } catch (e) {
      window.alert(`delete failed: ${(e as Error).message}`);
    }
  }

  function startRepoChat(repo: { repo_id: string; remote_url: string }) {
    // one stable thread per repo: everything agents do for it accumulates
    // in a single reviewable story
    const id = `repo:${repo.repo_id}`;
    conversationIdRef.current = id;
    setConversationId(id);
    setEvents([]);
    setStory(null);
    setStoryError(null);
    setChatMode("live");
    // the chat is usable the instant it opens: a short placeholder goes in
    // first, then the deep context (manifest + live verify + recent
    // missions) swaps in once it loads — but only if the operator hasn't
    // already started typing over it
    const placeholder = `Working on registered repo ${repo.repo_id}`
      + (repo.remote_url ? ` (${repo.remote_url})` : "") + ". ";
    setInput(placeholder);
    void hydrateThread(id);
    fetchRepoChatContext(repo.repo_id)
      .then((ctx) => {
        if (conversationIdRef.current !== id) return;   // user moved to another thread
        setInput((prev) => (prev === placeholder ? ctx.chat_prompt : prev));
      })
      .catch(() => {});   // deep context is a nice-to-have; the placeholder already works
  }

  async function loadStory(id = conversationId, limit?: number) {
    setStoryLoading(true);
    try {
      const t = await fetchChatTranscript(id, limit);
      if (conversationIdRef.current !== id) return;   // user moved on
      setStory(t);
      setStoryError(null);
      setStoryLoading(false);
    } catch (e) {
      if (conversationIdRef.current !== id) return;
      setStoryError((e as Error).message);
      setStoryLoading(false);
    }
  }

  function setMode(mode: "live" | "story") {
    setChatMode(mode);
    if (mode === "story") void loadStory();   // always fresh on entry
    // coming back to live for a thread with no live events yet: replay the
    // recorded history instead of dead-ending on the empty state
    else if (!events.length) void hydrateThread(conversationIdRef.current);
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    const id = conversationId;   // pin: stream events must not follow a thread switch
    setInput("");
    setChatMode("live");   // watch the turn stream; the story view is for review
    setEvents((e) => [...e, { type: "you", content: text }]);
    rememberThread(id, text);
    setBusy(true);
    try {
      await streamChat({ text, model, conversation_id: id },
        (ev) => { if (conversationIdRef.current === id) setEvents((e) => [...e, ev]); });
    } catch (e) {
      if (conversationIdRef.current === id) {
        setEvents((ev) => [...ev, { type: "error", message: (e as Error).message }]);
      }
    } finally {
      setBusy(false);
      void loadStory(id);   // keep the full-story badge/timeline current
      loadConversations();  // and the All Chats index
    }
  }

  const externalChats = runtime?.external_chats ?? [];
  const activeExternal = externalChats.find((c) => c.name === target);
  return (
    <div className="chat">
      <div className="chat-layout">
        <section className="chat-workspace">
          {/* Row 1: navigation — back, target/agent, model, thread */}
          <div className="chat-header">
            <div className="chat-header-left">
              {onBack && (
                <button className="chat-back" onClick={onBack} title="back to the board">
                  ← Back
                </button>
              )}
              <label className="chat-field">
                <span className="muted small">agent</span>
                <select className="select" value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  title="GatewayCore runs in-app; specialists open in their own tab">
                  <option value="GatewayCore">GatewayCore (in-app)</option>
                  {externalChats.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}{c.active ? "" : " (not configured)"}
                    </option>
                  ))}
                </select>
              </label>
              {target === "GatewayCore" && (
                <label className="chat-field">
                  <span className="muted small">model</span>
                  <select className="select" value={model}
                    onChange={(e) => setModel(e.target.value)}
                    title="Local roles route free through LiteLLM/Ollama. Frontier models are a paid, opt-in escalation lane. Local Frontier models are a free but experimental, very slow, loopback-only lane. Claude Code/Codex are agentic coding executors, launched from missions — never a chat model.">
                    <optgroup label="Local (free)">
                      {roles.map((r) => {
                        const backing = runtime?.roles?.find((x) => x.role === r)?.candidates?.[0]?.model;
                        return <option key={r} value={r}>{backing ? `${r} — ${backing}` : r}</option>;
                      })}
                    </optgroup>
                    {(runtime?.frontier_models ?? []).length > 0 && (
                      <optgroup label="Frontier (paid, opt-in)">
                        {(runtime?.frontier_models ?? []).map((f) => {
                          const m = f.measured;
                          const resultsBits: string[] = [];
                          if (f.estimated_cost_per_turn_usd != null) {
                            resultsBits.push(`~$${f.estimated_cost_per_turn_usd.toFixed(4)}/turn`);
                          }
                          if (m) {
                            if (m.median_latency_ms != null) resultsBits.push(`${(m.median_latency_ms / 1000).toFixed(1)}s median`);
                            if (m.pass_rate != null) resultsBits.push(`${Math.round(m.pass_rate * 100)}% suite pass`);
                          }
                          return (
                            <option key={f.model_id} value={`frontier:${f.model_id}`}
                              disabled={!f.selectable}>
                              {f.model_id}
                              {resultsBits.length ? ` — ${resultsBits.join(" · ")}` : ""}
                              {f.selectable ? "" : !f.lane_enabled ? " (lane disabled)" : " (no key)"}
                            </option>
                          );
                        })}
                      </optgroup>
                    )}
                    {(runtime?.local_frontier_models ?? []).length > 0 && (
                      <optgroup label="Local Frontier — experimental, may take minutes">
                        {(runtime?.local_frontier_models ?? []).map((f) => {
                          const m = f.measured;
                          const resultsBits: string[] = [];
                          if (m?.median_tokens_per_second != null) {
                            resultsBits.push(`measured ${m.median_tokens_per_second.toFixed(2)} tok/s`);
                          } else if (f.expected_tokens_per_second) {
                            resultsBits.push(
                              `${f.expected_tokens_per_second.low}-${f.expected_tokens_per_second.high} tok/s (unverified)`);
                          }
                          if (m?.pass_rate != null) resultsBits.push(`${Math.round(m.pass_rate * 100)}% suite pass`);
                          return (
                            <option key={f.model_id} value={`local-frontier:${f.model_id}`}
                              disabled={!f.selectable}>
                              {f.model_id}
                              {resultsBits.length ? ` — ${resultsBits.join(" · ")}` : ""}
                              {f.selectable ? "" : !f.lane_enabled ? " (lane disabled)" : ` (${f.health})`}
                            </option>
                          );
                        })}
                      </optgroup>
                    )}
                    <optgroup label="Executors — from missions, not here">
                      {(runtime?.executors ?? []).map((e) => (
                        <option key={e.name} value={`executor:${e.name}`} disabled>
                          {e.name} ({e.family}) — start from a mission, not this dropdown
                        </option>
                      ))}
                    </optgroup>
                  </select>
                </label>
              )}
            </div>
            <div className="chat-header-right">
              <button className="chat-history-toggle"
                aria-expanded={historyOpen}
                onClick={() => setHistoryOpen((v) => !v)}
                title="recent chats & all conversations">
                History {historyOpen ? "▾" : "▸"}
              </button>
              <button className="clear" onClick={startNewChat}>new chat</button>
            </div>
          </div>
          {/* External specialist: hand off, don't fake an in-app chat */}
          {target !== "GatewayCore" && activeExternal && (
            <div className="chat-external">
              <div><b>{activeExternal.name}</b> — {activeExternal.kind || "external specialist"}</div>
              {activeExternal.best_for && <p className="muted">{activeExternal.best_for}</p>}
              {activeExternal.active && activeExternal.url ? (
                <a className="actbtn" href={activeExternal.url} target="_blank" rel="noreferrer">
                  Open {activeExternal.name} ↗
                </a>
              ) : (
                <div className="muted">
                  Not configured — set <code>{activeExternal.env_var}</code> to enable the handoff.
                  {" "}Meanwhile, GatewayCore handles this in-app.
                </div>
              )}
            </div>
          )}
          {/* Row 2: thread id + live/story toggle (only for GatewayCore) */}
          {target === "GatewayCore" && (
          <div className="chat-subbar">
            <span className="muted small">thread <code>{conversationId}</code></span>
            <div className="chat-mode-toggle" role="tablist" aria-label="Chat view mode">
              <button role="tab" aria-selected={chatMode === "live"}
                className={chatMode === "live" ? "mode-on" : ""}
                onClick={() => setMode("live")}>live</button>
              <button role="tab" aria-selected={chatMode === "story"}
                className={chatMode === "story" ? "mode-on" : ""}
                title="everything recorded for this thread: full tool args/results, injected context, final answers"
                onClick={() => setMode("story")}>
                full story{story && story.conversation_id === conversationId
                  ? ` · ${story.total_turns ?? story.turn_count}` : ""}
              </button>
            </div>
            {events.length > 0 && chatMode === "live" && (
              <button className="clear" onClick={() => setEvents([])}>clear</button>
            )}
          </div>
          )}
          {/* Collapsible history: recent chats, tucked away until opened */}
          {historyOpen && (
            <div className="chat-threads">
              <div className="muted small">recent chats</div>
              <HorizontalScroller className="thread-strip" ariaLabel="Recent cockpit chats">
                {threads.length === 0 && (
                  <button className="thread-chip thread-empty" disabled>No recent cockpit chats</button>
                )}
                {threads.map((thread) => (
                  <div
                    className={`thread-chip ${thread.id === conversationId ? "thread-on" : ""}`}
                    key={thread.id}>
                    <button className="thread-open" onClick={() => openThread(thread)}>
                      <span>{thread.title}</span>
                      <small>{thread.target ?? "GatewayCore"} {fmtThreadTime(thread.updatedAt)}</small>
                    </button>
                    <button className="thread-story"
                      title="open this thread's full story (flight recorder)"
                      onClick={() => openThread(thread, "story")}>
                      story
                    </button>
                  </div>
                ))}
              </HorizontalScroller>
            </div>
          )}
          {target !== "GatewayCore" ? null : chatMode === "story" ? (
            <div className="chat-log chat-log-story">
              <ThreadTimeline transcript={story} loading={storyLoading}
                error={storyError} onRefresh={() => void loadStory()}
                onLoadAll={(total) => void loadStory(conversationId, total)}
                focusTs={focusTs} onFocused={() => setFocusTs(null)} />
            </div>
          ) : (
            <div className="chat-log">
              {events.length === 0 && <div className="muted">Ask the agent to do something — e.g. "stage the odds_promote card", "what's blocked?", "archive the oldest paper".</div>}
              {events.map((ev, i) => <ChatLine key={i} ev={ev} />)}
              <div ref={endRef} />
            </div>
          )}
          {target === "GatewayCore" && (
            <div className="chat-input">
              <input value={input} placeholder="ask the agent…"
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
              <button onClick={send} disabled={busy}>{busy ? "…" : "send"}</button>
            </div>
          )}
        </section>
        {/* History is a side drawer now — hidden until toggled, so the chat
            itself is not bunched up against the conversation index */}
        {historyOpen && (
          <aside className="chat-runtime-wrap">
            <ChatRuntimePanel runtime={runtime} conversations={conversations}
              activeId={conversationId} onOpenConversation={openConversation}
              onStartRepoChat={startRepoChat}
              onDeleteConversation={(id) => void deleteConversation(id)} />
          </aside>
        )}
      </div>
    </div>
  );
}

// ---- app ------------------------------------------------------------------
export function App() {
  const [view, setView] = useState<View>(() => initialViewFromUrl());
  const [board, setBoard] = useState<BoardData | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [boards, setBoards] = useState<BoardSnapshot | null>(null);
  const [boardsNote, setBoardsNote] = useState<string | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [lanes, setLanes] = useState<ModelLanes | null>(null);
  const [lanesNote, setLanesNote] = useState<string | null>(null);
  const [cfg, setCfg] = useState<UIConfig | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [runtimeDebug, setRuntimeDebug] = useState<RuntimeDebug | null>(null);
  const [chatRuntime, setChatRuntime] = useState<ChatRuntime | null>(null);
  const [chatDraft, setChatDraft] =
    useState<{ text: string; nonce: number; conversationId?: string;
               storyTs?: string } | null>(null);
  // where the chat was opened from, so the chat's Back button can return there
  const [chatReturnView, setChatReturnView] = useState<View>("domains");
  const [domainNav, setDomainNav] = useState<DomainNavItem[]>([]);
  const [activeDomain, setActiveDomain] = useState(() => initialDomainFromUrl());
  const [updated, setUpdated] = useState<string>("");
  const [selMission, setSelMission] = useState<string | null>(null);
  const [selCard, setSelCard] =
    useState<{ board: string; card: BoardCard; statuses: string[] } | null>(null);
  const [surfaceErrors, setSurfaceErrors] = useState<Record<string, string>>({});
  const chatRef = useRef(false);   // so reloadBoards can pick live vs snapshot

  // Console: read boards LIVE from AppFlowy (a write reflects at once); read-only:
  // the worker snapshot. Explicit capability switch, not a silent fallback.
  const reloadBoards = useCallback(async () => {
    try {
      setBoards(await (chatRef.current ? fetchBoardsLive() : fetchBoards()));
      setBoardsNote(null);
    } catch (e) { setBoards(null); setBoardsNote((e as Error).message); }
  }, []);

  const reloadDomainNav = useCallback(async () => {
    try {
      const body = await fetchDomains();
      const items = await Promise.all(body.domains.map(async (domain) => {
        try {
          const pack = await fetchDomainCards(domain.domain_id);
          return {
            id: domain.domain_id,
            title: domain.title,
            count: pack.cards.length,
            origin: pack.origin,
          } satisfies DomainNavItem;
        } catch (e) {
          return {
            id: domain.domain_id,
            title: domain.title,
            count: 0,
            error: (e as Error).message,
          } satisfies DomainNavItem;
        }
      }));
      setDomainNav(items);
      if (items.length && !items.some((item) => item.id === activeDomain)) {
        setActiveDomain(items[0].id);
      }
    } catch {
      setDomainNav([]);
    }
  }, [activeDomain]);

  const refresh = useCallback(async () => {
    const errs: Record<string, string> = {};
    try { setBoard(await fetchMissions()); }
    catch (e) { setBoard(null); errs.missions = (e as Error).message; }
    try { setMetrics(await fetchMetrics()); }
    catch (e) { setMetrics(null); errs.observability = (e as Error).message; }
    try { setActivity(await fetchActivity()); }
    catch (e) { setActivity(null); errs.activity = (e as Error).message; }
    setSurfaceErrors(errs);
    await reloadBoards();
    await reloadDomainNav();
    try { setLanes(await fetchModels()); setLanesNote(null); }
    catch (e) { setLanes(null); setLanesNote((e as Error).message); }
    // status drives the topbar dots; if the probe endpoint itself is unreachable,
    // clear the dots (their absence is the signal) rather than show stale health.
    try { setStatus(await fetchStatus()); } catch { setStatus(null); }
    try { setRuntimeDebug(await fetchRuntimeDebug()); } catch { setRuntimeDebug(null); }
    try { setChatRuntime(await fetchChatRuntime()); } catch { setChatRuntime(null); }
    setUpdated(new Date().toLocaleTimeString());
  }, [reloadBoards, reloadDomainNav]);

  useEffect(() => {
    fetchConfig().then((c) => { setCfg(c); chatRef.current = !!c.chat_enabled; })
      .catch(() => setCfg(null));   // capability probe (once)
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {   // Escape closes whichever drawer is open
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setSelMission(null); setSelCard(null); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const chatOn = !!cfg?.chat_enabled;
  const openChatWithPrompt = useCallback(
    (prompt: string, conversationId?: string, storyTs?: string) => {
      setChatDraft({ text: prompt, conversationId, storyTs, nonce: Date.now() });
      // remember where we came from so Chat's Back button returns there
      setView((prev) => { if (prev !== "chat") setChatReturnView(prev); return "chat"; });
    }, []);
  const nav = [...NAV, { id: "chat" as View, label: "Chat" }];
  const domainNavCount = domainNav.reduce((total, item) => total + item.count, 0);
  const counts: Partial<Record<View, number>> = {
    router: lanes?.roles.length, activity: activity?.calls.length,
  };
  if (domainNavCount > 0) counts.domains = domainNavCount;
  const surfaceFailureCount = Object.keys(surfaceErrors).length +
    (boardsNote ? 1 : 0) + (lanesNote ? 1 : 0);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Agent Kanban</div>
        <nav>
          {nav.map((n) => (
            <button key={n.id} className={`navitem ${view === n.id ? "nav-on" : ""}`}
              onClick={() => setView(n.id)}>
              {n.label}
              {counts[n.id] !== undefined && <span className="navcount">{counts[n.id]}</span>}
            </button>
          ))}
        </nav>
        {domainNav.length > 0 && (
          <div className="domain-nav-section">
            <div className="nav-section-label">Boards</div>
            {domainNav.filter((item) => item.id !== "mission").map((item) => (
              <button key={item.id}
                className={`navitem nav-subitem ${view === "domains" && activeDomain === item.id ? "nav-on" : ""}`}
                title={item.error ?? `${item.origin ?? "domain"} source`}
                onClick={() => { setActiveDomain(item.id); setView("domains"); }}>
                {item.title}
                <span className="navcount">{item.error ? "ERR" : item.count}</span>
              </button>
            ))}
          </div>
        )}
        <div className="badge">{chatOn ? "console · chat + governed writes" : "read-only · Ledger + log + snapshot"}</div>
      </aside>
      <main className="main">
        <div className="topbar">
          <div className="hops">
            {Object.entries(status?.hops ?? {}).map(([name, state]) => (
              <span className="hop" key={name} title={`${state} ${status?.targets?.[name] ?? ""}`.trim()}>
                <span className={`hopdot ${state === "ok" ? "ok" : "bad"}`} />{name}
              </span>
            ))}
          </div>
          <div className="topright">
            {updated && <span className="muted small">updated {updated}</span>}
            <button className="refresh" onClick={refresh} title="refresh now">↻</button>
          </div>
        </div>
        {surfaceFailureCount > 0 && (
          <div className="surface-errors">
            {Object.entries(surfaceErrors).map(([name, msg]) => (
              <div className="error" key={name}>{name}: {msg}</div>
            ))}
            {boardsNote && <div className="error">boards: {boardsNote}</div>}
            {lanesNote && <div className="error">router: {lanesNote}</div>}
          </div>
        )}
        {view === "missions" && (board
          ? <MissionsView data={board} onOpen={setSelMission} />
          : <div className="empty">{surfaceErrors.missions ?? "..."}</div>)}
        {view === "boards" && (boards
          ? <BoardsView snap={boards} canAct={chatOn} onMoved={reloadBoards}
              onOpenCard={(b, c, st) => setSelCard({ board: b, card: c, statuses: st })} />
          : <div className="empty">{boardsNote ?? "…"}</div>)}
        {view === "domains" && (
          <DomainsView refreshKey={updated} activeDomain={activeDomain}
            onActiveDomainChange={setActiveDomain} onOpenChat={openChatWithPrompt} />
        )}
        {view === "settings" && <SettingsView status={status} runtime={chatRuntime} />}
        {view === "router" && (lanes
          ? <RouterView lanes={lanes} />
          : <div className="empty">{lanesNote ?? "…"}</div>)}
        {view === "diagnostics" &&
          <DiagnosticsView debug={runtimeDebug} surfaceErrors={surfaceErrors}
            boardsNote={boardsNote} lanesNote={lanesNote} />}
        {view === "observability" && (metrics
          ? <ObservabilityView m={metrics} /> : <div className="loading">…</div>)}
        {view === "activity" && (activity
          ? <ActivityView a={activity} /> : <div className="loading">…</div>)}
        {/* chat stays MOUNTED so the conversation persists across view switches */}
        {chatOn && (
          <div style={{ display: view === "chat" ? "block" : "none" }}>
            <ChatView roles={cfg?.model_roles ?? []} runtime={chatRuntime} draft={chatDraft}
              onBack={() => setView(chatReturnView)} />
          </div>
        )}
        {view === "chat" && !chatOn &&
          <div className="chat">
            <div className="empty">chat is not enabled in this deployment. Set `KANBAN_UI_CHAT_ENABLED=1` to use the streaming GatewayCore chat and governed actions.</div>
          </div>}
      </main>
      {selMission && (
        <MissionDrawer id={selMission} ledgerUi={cfg?.ledger_ui ?? ""}
          onClose={() => setSelMission(null)} />
      )}
      {selCard && (
        <CardDrawer board={selCard.board} card={selCard.card}
          statuses={selCard.statuses} canAct={chatOn} onChanged={reloadBoards}
          onClose={() => setSelCard(null)} />
      )}
    </div>
  );
}
