import { Component, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AllTodosView } from "./AllTodosView";
import { exactResearchProgressCounts } from "./researchProgress";
import {
  researchAnalysisComplete, researchDetailBadge, researchProjectFits,
  researchScore,
} from "./researchAnalysis";
import {
  BOOK_GROUP_FIELDS, BOOK_SORT_FIELDS,
  EMPTY_BOOK_FILTERS, bookFacetOptions,
  bookHours, bookMatchesLibraryFilters, bookProgress, sortBooks,
  type BookLibraryFilterState, type BookNoteFilter, type BookReadingFilter,
  type BookSortDirection, type BookSortField,
} from "./bookLibrary";
import {
  addBookNote, archiveBookCard,
  addDomainCardNote,
  Activity, WorkspaceBoard, BoardCard, BoardData, BoardSnapshot, ChatEvent,
  BoardRegistry, BoardRegistryBoard,
  BookNote, ChatRuntime, DomainActions, DomainCard, DomainCardDetail, DomainCardProgress,
  DomainCards, DomainIntake, DomainIntakeResponse, DomainIntakeValue, DomainSchema, DomainSpec,
  FieldSpec, JobProfileControls, RegisteredRepository,
  ResearchAnalysisCounts, ResearchSettingsResponse,
  ExecutionScope,
  archiveDomainSchema, boardIdFromTitle, createBoardModule, createDomainSchema,
  restoreDomainSchema,
  fetchBoardRegistry,
  InboxData, CaptureView,
  MissionDetail, MissionEvent, Metrics, ModelLanes, Status, UIConfig,
  createBookCard, createCapture, createCaptureBatch, fetchActivity, fetchCapture, prepareCapture,
  fetchBoards, fetchBoardsLive, fetchChatRuntime, fetchConfig, fetchDomainActions,
  fetchDomainIntake, fetchInbox,
  fetchResearchRefresh, fetchResearchSettings,
  fetchChatThreads, fetchChatTranscript, ChatTranscriptResponse, TranscriptTurn,
  ChatConversation, fetchChatConversations, deleteChatConversation,
  fetchDomainCard, fetchDomainCardProgress, fetchDomainCards, fetchDomains,
  createLinkedInPostDraft, fetchLinkedInComposer, LinkedInComposerOptions,
  fetchJobPacket, JobPacket, JobStoryEntry, PacketValidation, AgentTraceEntry,
  requestPacketChanges, submitJobApplication, updateJobPacketFile,
  fetchDomainSchema, fetchJobProfileControls, fetchMetrics, fetchMission, fetchMissions, fetchModels,
  fetchRepoChatContext, registerRepo, RepoRegisterResult,
  fetchRegisteredRepositories, fetchRuntimeDebug, fetchStatus,
  moveDomainCard, postAction, RuntimeDebug, streamChat,
  updateBookCard, updateGrandTodoCard,
  saveChatThread, updateDomainIntake, updateDomainSchema, updateDraftDefault, updateJobSearchCategory, updateJobSearchRuntime,
  requestResearchRefresh, updateResearchSettings,
  syncGrandTodoSource,
  updateJobSearchCompanyTargets, updateJobSearchRetention,
  StandingAnswer, updateStandingAnswer, removeJobSearchCategory,
  JobRelationship, JobQuestionLibraryEntry, JobOutreach,
  fetchJobRelationships, putJobRelationship, fetchJobQuestionLibrary,
  captureJobQuestion, putJobQuestionCandidate, fetchJobOutreach,
  reclassifyJobApplications, ReclassifyResult, bulkSelectSuggested,
  updateJobSearchLocations, updateJobSearchLanguages,
  fetchPrepStatus, fetchRejectionsReport, RejectionsReport,
  REJECT_REASONS,
  AgentEvent, AgentHarnessOption, AgentSessionRecord, AgentModelOption,
  AgentSessionSpecSummary,
  buildAgentHandoff, resolveAttachments, AttachmentReq,
  fetchBoardFormatTargets, planBoardFormat, mintBoardApproval, applyBoardChange,
  BoardFormatTarget, BoardFormatPlan,
  closeAgentSession, createAgentSession, fetchAgentEvents, fetchAgentHarnesses,
  fetchAgentSessionSpecs,
  fetchAgentSession, fetchHarnessModels, interruptAgentSession, promoteAgentSession,
  promoteChat, resolveAgentApproval, resumeAgentSession, sendAgentMessage, streamAgentEvents,
  UsageStatus, UsageLimit, CollectorHealth, ModelUsageEntry, ModelUsagePortfolio,
  AgentUsageDetail, UsageDriverRow, UsageKpis, UsageRecentActivity, UsageWindowId,
  fetchModelUsage, fetchCollectorHealth, fetchModelUsageDrivers,
  fetchModelUsagePortfolio, fetchRecentAgentUsage, refreshModelUsage,
  WorkGraph, WorkEdge, ResourceLink,
  RoutingProposal, TaskCreationReceipt, WorkPlanItem,
  AssistantRoutingView, fetchAssistantRouting,
  LifeCenterLaunch, LifeCenterService, LifeCenterLink, LifeCenterDispatchResult,
  fetchLifeCenterLaunch, fetchLifeCenterRunbook, dispatchLifeCenterAction,
  DuplicateFinding, DuplicateReport, resolveCaptureDuplicate,
  addWorkPlacement, convertCaptureToWork,
  getWorkGraph, getWorkGraphNeighbourhood, getWorkItem, getWorkItemLinks,
  recordRoutingCorrection, routeCapture, routeWorkText,
} from "./api";
import {
  createLoadResilienceState, recordLoadFailure, recordLoadSuccess,
  type LoadResilienceState,
} from "./loadResilience";
import {
  describeChatEvent, optionLabel, runtimeLabel, type RuntimeTarget,
} from "./chatPresentation";
import { agentSessionSpecOptionLabel } from "./agentSessionSpecs";

type View = "missions" | "boards" | "domains" | "todos" | "settings" | "router" | "diagnostics" | "observability" | "activity" | "usage" | "chat" | "inbox" | "work-map" | "life-center";
const NAV: { id: View; label: string }[] = [
  { id: "domains", label: "Kanban Boards" },
  { id: "life-center", label: "Life Center" },
  { id: "todos", label: "Master TODO List" },
  { id: "work-map", label: "Work Map" },
  { id: "inbox", label: "Inbox" },
  { id: "settings", label: "Controls" },
  { id: "router", label: "Router" },
  { id: "diagnostics", label: "Status" },
  { id: "observability", label: "Metrics" },
  { id: "usage", label: "Usage & Limits" },
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
  count: number | null;
  origin?: string;
  error?: string;
};
type JobBoardMode = "bot" | "manual" | "all";
type ResilientSurface =
  "missions" | "boards" | "router" | "observability" | "activity" | "repositories";
const RESILIENT_SURFACES: ResilientSurface[] = [
  "missions", "boards", "router", "observability", "activity", "repositories",
];
const createSurfaceLoadStates = (): Record<ResilientSurface, LoadResilienceState> => ({
  missions: createLoadResilienceState(),
  boards: createLoadResilienceState(),
  router: createLoadResilienceState(),
  observability: createLoadResilienceState(),
  activity: createLoadResilienceState(),
  repositories: createLoadResilienceState(),
});
const formatStaleTime = (timestamp: number) =>
  new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
const RISK_CLASS: Record<string, string> = {
  L0: "risk-l0", L1: "risk-l1", L2: "risk-l2", L3: "risk-l3", L4: "risk-l4",
};
const POLL_MS = 5000;
export const GRAND_TODO_DOMAIN_IDS: ReadonlySet<string> = new Set([
  "betts_basketball_grand_todo",
  "grand_todo",
]);
const isGrandTodoDomain = (domainId: string) =>
  GRAND_TODO_DOMAIN_IDS.has(domainId);

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

// The selected work item (a WorkItem.work_item_id) — drives the Work Map's
// neighbourhood fetch and every backend `?...&work=<id>` deep link.
function initialWorkFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("work") || null;
}

// Work-graph neighbourhood depth (hops from the selected item); default 1.
function initialDepthFromUrl(): number {
  const raw = new URLSearchParams(window.location.search).get("depth");
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(n) && n > 0 ? n : 1;
}

// The canonical query string for the current navigation state. view + domain are
// always present (matching the pre-existing readers); work/depth only when set,
// so a plain board view stays a clean `?view=…&domain=…`.
function navSearch(view: View, domain: string, work: string | null, depth: number): string {
  const p = new URLSearchParams();
  p.set("view", view);
  p.set("domain", domain);
  if (work) p.set("work", work);
  if (depth !== 1) p.set("depth", String(depth));
  return "?" + p.toString();
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

const CARD_PRIORITY_FIELDS = [
  "research_priority", "priority", "risk", "tier", "severity",
];
const CARD_ESTIMATE_FIELDS = [
  "estimated_effort",
  "estimated_duration", "estimated_time", "time_estimate", "estimate",
  "est_time", "est_length", "estimated_hours", "estimate_hours", "hours",
  "duration", "effort",
];
const CARD_DESCRIPTION_FIELDS = [
  "description", "summary", "details", "notes", "source_notes", "abstract",
  "why_apply", "next_action", "manual_reason", "body",
];

function firstRecordedValue(card: Record<string, unknown>, fields: string[]): {
  field: string; value: string;
} | null {
  for (const field of fields) {
    const value = valText(card[field]).trim();
    if (value) return { field, value };
  }
  return null;
}

function cardPriority(card: Record<string, unknown>): string {
  return firstRecordedValue(card, CARD_PRIORITY_FIELDS)?.value ?? "";
}

function cardEstimate(card: Record<string, unknown>): string {
  const found = firstRecordedValue(card, CARD_ESTIMATE_FIELDS);
  if (!found) return "";
  if (
    ["estimated_hours", "estimate_hours", "hours"].includes(found.field)
    && /^\d+(?:\.\d+)?$/.test(found.value)
  ) {
    return `${found.value}h`;
  }
  return found.value;
}

function cardDescription(
  card: Record<string, unknown>,
  extraFields: string[] = [],
  fallback = "",
): string {
  return firstRecordedValue(
    card,
    [...CARD_DESCRIPTION_FIELDS, ...extraFields],
  )?.value ?? fallback;
}

function CardDisclosure({
  title, priority, estimate, description, expanded, onToggle, onOpen, children,
}: {
  title: string;
  priority: string;
  estimate: string;
  description: string;
  expanded: boolean;
  onToggle: () => void;
  onOpen: () => void;
  children?: ReactNode;
}) {
  const shownTitle = title || "Untitled card";
  return (
    <>
      <button type="button" className="card-summary-toggle"
        aria-expanded={expanded}
        aria-label={`${expanded ? "Collapse" : "Expand"} details for ${shownTitle}`}
        onClick={onToggle}>
        <span className="card-summary-heading">
          <span className="card-summary-title">{shownTitle}</span>
          <span className="card-summary-chevron" aria-hidden="true">
            {expanded ? "▴" : "▾"}
          </span>
        </span>
        <span className="card-summary-facts">
          <span><small>Priority</small><b>{priority || "Not set"}</b></span>
          <span className="card-summary-separator" aria-hidden="true">|</span>
          <span><small>Estimate</small><b>{estimate || "Not set"}</b></span>
        </span>
      </button>
      {expanded && (
        <div className="card-inline-details">
          <p className="card-inline-description">
            {description || "No additional description has been recorded."}
          </p>
          <button type="button" className="actbtn card-open-details"
            onClick={onOpen}>
            Open full details
          </button>
          {children}
        </div>
      )}
    </>
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
  const [expandedCard, setExpandedCard] = useState<string | null>(null);
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
              {col.cards.map((c) => {
                const record = c as unknown as Record<string, unknown>;
                return (
                <div className={`card card-click card-disclosure-card ${expandedCard === c.id ? "card-expanded" : ""}`}
                  key={c.id}>
                  <CardDisclosure
                    title={c.action || c.id}
                    priority={c.risk}
                    estimate={cardEstimate(record)}
                    description={cardDescription(
                      record, [], [c.repo && `Repository: ${c.repo}`, `Status: ${c.status}`]
                        .filter(Boolean).join(" · "))}
                    expanded={expandedCard === c.id}
                    onToggle={() => setExpandedCard((current) => current === c.id ? null : c.id)}
                    onOpen={() => onOpen(c.id)}>
                    <div className="card-inline-meta">
                      <span className="card-id">{c.id}</span>
                      {c.repo && <span>{c.repo}</span>}
                      <span>{c.status}</span>
                    </div>
                  </CardDisclosure>
                </div>
                );
              })}
            </div>
          </div>
        ))}
      </HorizontalScroller>
    </>
  );
}

// ---- Workspace boards view -------------------------------------------------
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
  const [expandedCard, setExpandedCard] = useState<string | null>(null);
  const board: WorkspaceBoard | undefined =
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
      <HorizontalScroller className="tabs tabs-strip" ariaLabel="Workspace boards">
        {snap.boards.map((b) => (
          <button key={b.board} className={`tab ${b.board === active ? "tab-on" : ""}`}
            onClick={() => { setActive(b.board); setExpandedCard(null); }}>
            {b.board}{b.error ? " ⚠" : ""}
          </button>
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
                  {col.cards.map((c, i) => {
                    const key = `${board.board}:${col.name}:${c.title}:${i}`;
                    const record: Record<string, unknown> = {
                      ...(c.fields ?? {}), meta: c.meta,
                    };
                    return (
                    <div className={`card card-click card-disclosure-card ${canAct ? "draggable" : ""} ${expandedCard === key ? "card-expanded" : ""}`}
                      key={key} draggable={canAct}
                      onDragStart={() => setDragged(c.title)}
                      onDragEnd={() => { setDragged(null); setOverCol(null); }}>
                      <CardDisclosure
                        title={c.title}
                        priority={cardPriority(record)}
                        estimate={cardEstimate(record)}
                        description={cardDescription(record, [], c.meta)}
                        expanded={expandedCard === key}
                        onToggle={() => setExpandedCard((current) => current === key ? null : key)}
                        onOpen={() => onOpenCard(board.board, c, board.statuses ?? [])}>
                        {c.meta && <div className="card-inline-meta">{c.meta}</div>}
                        {canAct && (board.statuses ?? []).length > 0 && (
                          <select className="touch-move" aria-label={`Move ${c.title} to column`}
                            value=""
                            onChange={(e) => {
                              const target = e.target.value;
                              if (target) void moveBoardCard(c.title, target);
                            }}>
                            <option value="">Move to...</option>
                            {(board.statuses ?? []).filter((s) => s !== col.name)
                              .map((s) => <option key={s}>{s}</option>)}
                          </select>
                        )}
                      </CardDisclosure>
                    </div>
                    );
                  })}
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
// concise, text-only live badge for a harness <option> (options can't hold DOM):
// surfaces a non-available availability state or the worst limit bucket ≥50%.
function harnessBadgeText(h: AgentHarnessOption): string {
  const u = h.usage_summary;
  if (!u) return "";
  if (u.availability && u.availability !== "available" && u.availability !== "unknown")
    return ` · ${u.availability.replace(/_/g, " ")}`;
  const pcts = (u.limits ?? [])
    .map((l) => l.used_percent).filter((p): p is number => p != null);
  if (pcts.length) {
    const worst = Math.max(...pcts);
    if (worst >= 50) return ` · ${worst.toFixed(0)}% used`;
  }
  return "";
}
function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metric" title={hint}>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

// ---- Usage & Limits view --------------------------------------------------
// Self-contained (fetches on mount + manual refresh) so a deployment with the
// feature OFF never 503-spams the global 5s poll. Keeps coding-agent quota
// windows distinct from model-level local/OpenRouter usage, with source health,
// UNKNOWN/stale state, and missing cost surfaced instead of fabricated.
const AVAIL_CLASS: Record<string, string> = {
  available: "ok", near_limit: "warn", busy: "warn", limited: "bad",
  exhausted: "bad", authentication_required: "bad", unavailable: "muted",
  unknown: "muted",
};
function fmtInt(n: number): string { return n.toLocaleString(); }
function fmtReset(iso: string | null): string {
  if (!iso) return "—";
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return iso;
  if (ms <= 0) return "due";
  const m = Math.round(ms / 60000);
  if (m < 60) return `in ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `in ${h}h ${m % 60}m`;
  return `in ${Math.floor(h / 24)}d`;
}
function fmtCost(cost: number | null, source: string): string {
  if (cost !== null) return `$${cost.toFixed(4)}`;
  if (source === "subscription_not_metered") return "Subscription plan";
  return "Not reported";
}
const RUNTIME_LABELS: Record<string, string> = {
  claude_code_local: "Claude Code",
  codex_agent: "Codex CLI",
};
function humanLabel(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(
    /\b\w/g, (letter) => letter.toUpperCase(),
  );
}
function humanText(value: string): string {
  return value.replace(/_/g, " ");
}
function fmtDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} sec`;
  const minutes = Math.floor(ms / 60000);
  return `${minutes} min ${Math.round((ms % 60000) / 1000)} sec`;
}
function fmtObserved(iso: string | null): string {
  if (!iso) return "Time not recorded";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return iso;
  return value.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
function fmtKpi(value: number | null | undefined, suffix = ""): string {
  if (value === null || value === undefined) return "Not recorded";
  return `${value.toLocaleString()}${suffix}`;
}
function isRetiredCodexLimit(limit: UsageLimit): boolean {
  const identity = `${limit.bucket_id} ${limit.label}`.toLowerCase();
  return identity.includes("codex_bengalfox")
    || identity.includes("gpt-5.3-codex-spark");
}
// What each Match & Organize resolution DOES, in plain language. The second
// string is shown as the button title so the exact result is never a surprise.
const RESOLUTION_LABELS: Record<string, [string, string]> = {
  add_occurrence: ["Add progress to it",
    "Appends an update to the existing item (badge +1) and links this capture. No new task."],
  reopen_existing: ["Reopen it",
    "Moves the existing item back to Ready and links this capture. No new task."],
  reuse_existing: ["Use existing",
    "Links this capture to the existing item. Nothing new is created."],
  expand_existing: ["Add selected details",
    "Appends the checked details to the existing item (title and description stay untouched); checked subtasks become child tasks."],
  add_child: ["Add as a child task",
    "Creates this as ONE new task under the existing item, on the same board."],
  group_under_existing: ["Group under it",
    "Creates this as a new task inside that project. Both keep their own status."],
  create_project_group: ["Create project group",
    "Creates one project item connecting the related tasks. A project is NOT a new board — nothing moves."],
  discard_capture: ["Discard this capture",
    "Archives this capture — its text and history stay recoverable. The existing item is untouched."],
  create_separate: ["Create separate anyway",
    "Records your choice, then continues creating a new, separate item."],
  link_related: ["Link as related",
    "Records the relation choice; the new item is still created separately."],
};
const MATCH_CLASS_LABELS: Record<string, string> = {
  exact_same: "Same work",
  likely_same: "Very likely the same work",
  possible_same: "Possibly the same work",
  repeat_occurrence: "Repeated progress on existing work",
  expands_existing: "Expands existing work",
  subtask_of_existing: "Looks like a step of an existing project",
  parent_of_existing: "Looks like a project containing existing work",
  same_subject_related: "Same subject, different task",
};
// which single action leads for each match class ("Use recommendation")
const RECOMMENDED: Record<string, string> = {
  exact_same: "reuse_existing",
  likely_same: "reuse_existing",
  possible_same: "reuse_existing",
  repeat_occurrence: "add_occurrence",
  expands_existing: "expand_existing",
  subtask_of_existing: "add_child",
  parent_of_existing: "create_project_group",
  same_subject_related: "link_related",
};

type ResolveExtras = {
  selected_delta_ids?: string[];
  group_title?: string;
  member_work_item_ids?: string[];
  capture_as_parent?: boolean;
  existing_work_item_id?: string;   // override target (e.g. group parent)
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
};

// Match & Organize: one evidence-first review for "is this the same work /
// progress / an expansion / a related subject / a grouping opportunity?".
// One recommended button leads; everything else sits under More choices.
// Resolutions are explicit — nothing merges, discards, or groups silently.
function MatchOrganizePanel({ report, finding, busy, captureMode,
  onResolve, onDismiss }: {
  report: DuplicateReport;
  finding: DuplicateFinding;
  busy: boolean;
  captureMode: boolean;
  onResolve: (resolution: string, extras?: ResolveExtras) => void;
  onDismiss: () => void;
}) {
  const [deltaSel, setDeltaSel] = useState<Record<string, boolean>>(
    () => Object.fromEntries(
      finding.expansion_deltas.map((d) => [d.delta_id, d.selected])));
  const [canonicalTitle, setCanonicalTitle] = useState("");
  const [canonicalDescription, setCanonicalDescription] = useState("");
  const [canonicalKind, setCanonicalKind] = useState("");
  const [projectTitle, setProjectTitle] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [projectKind, setProjectKind] = useState("");
  const [deltaCanonical, setDeltaCanonical] = useState<Record<string, {
    title: string; description: string; kind: string;
  }>>({});
  const terminal = captureMode
    ? ["add_occurrence", "reopen_existing", "reuse_existing",
       "expand_existing", "add_child", "group_under_existing",
       "create_project_group", "discard_capture"]
    : ["reuse_existing"];
  const extrasFor = (resolution: string): ResolveExtras | undefined => {
    const childFields = {
      canonical_title: canonicalTitle,
      canonical_description: canonicalDescription,
      canonical_kind: canonicalKind,
      confirm_canonical_fields: true,
    };
    if (resolution === "expand_existing") {
      const selected_delta_ids = Object.entries(deltaSel)
        .filter(([, on]) => on).map(([id]) => id);
      return {
        selected_delta_ids,
        canonical_children: Object.fromEntries(
          selected_delta_ids.filter((id) =>
            finding.expansion_deltas.find((d) => d.delta_id === id)
              ?.proposed_target === "child")
            .map((id) => [id, deltaCanonical[id] ?? {
              title: "", description: "", kind: "",
            }]),
        ),
      };
    }
    if (resolution === "create_project_group") {
      return {
        canonical_project_title: projectTitle,
        canonical_project_description: projectDescription,
        canonical_project_kind: projectKind,
        confirm_canonical_project: true,
        ...(finding.match_class === "parent_of_existing"
          ? { capture_as_parent: true }
          : { group_title: projectTitle, ...childFields }),
      };
    }
    if (resolution === "add_child" || resolution === "group_under_existing") {
      return childFields;
    }
    return undefined;
  };
  const complete = (title: string, kind: string) => !!title.trim() && !!kind;
  const canResolve = (resolution: string, extras?: ResolveExtras) => {
    if (resolution === "add_child" || resolution === "group_under_existing") {
      return complete(canonicalTitle, canonicalKind);
    }
    if (resolution === "create_project_group") {
      return complete(projectTitle, projectKind)
        && (extras?.capture_as_parent || complete(canonicalTitle, canonicalKind));
    }
    if (resolution === "expand_existing") {
      const selected = extras?.selected_delta_ids ?? [];
      return selected.length > 0 && selected.every((id) => {
        const delta = finding.expansion_deltas.find((row) => row.delta_id === id);
        if (delta?.proposed_target !== "child") return true;
        const fields = deltaCanonical[id];
        return !!fields && complete(fields.title, fields.kind);
      });
    }
    return true;
  };
  const recommended = RECOMMENDED[finding.match_class];
  const recommendedOk = !!recommended
    && finding.allowed_resolutions.includes(recommended)
    && terminal.includes(recommended);
  const others = finding.allowed_resolutions.filter((r) =>
    terminal.includes(r) && RESOLUTION_LABELS[r] && r !== recommended);
  const group = report.subject_groups[0];
  return (
    <div className="dup-panel">
      <div className="dup-head">
        <span className={`status-pill dup-class-${finding.match_class}`}>
          {MATCH_CLASS_LABELS[finding.match_class] ?? finding.match_class}
        </span>
        <b>{finding.title}</b>
      </div>
      <div className="muted small">
        {finding.canonical_status}
        {finding.primary_board_id ? ` · ${finding.primary_board_id}` : ""}
        {finding.board_ids.filter((b) => b !== finding.primary_board_id)
          .map((b) => ` · also on ${b}`).join("")}
        {finding.occurrence_count > 0 &&
          ` · ${finding.occurrence_count} progress update${finding.occurrence_count === 1 ? "" : "s"}`}
        {finding.last_activity_at &&
          ` · last activity ${new Date(finding.last_activity_at).toLocaleDateString()}`}
      </div>
      {finding.expansion_deltas.length > 0 && (
        <div className="dup-deltas">
          <b className="small">New information detected — choose what to add</b>
          {finding.expansion_deltas.map((d) => (
            <label className="capture-check" key={d.delta_id}>
              <input type="checkbox" checked={!!deltaSel[d.delta_id]}
                disabled={busy}
                onChange={(e) => setDeltaSel((s) => ({
                  ...s, [d.delta_id]: e.target.checked }))} />
              <span><span className="chip">{d.kind.replace(/_/g, " ")}</span>{" "}
                {d.text}</span>
            </label>
          ))}
          <div className="muted small">
            The existing title and description are never replaced — checked
            items are appended; checked subtasks become child tasks.
          </div>
          {finding.expansion_deltas.filter((delta) =>
            delta.proposed_target === "child" && deltaSel[delta.delta_id],
          ).map((delta) => {
            const fields = deltaCanonical[delta.delta_id] ?? {
              title: "", description: "", kind: "",
            };
            const update = (field: "title" | "description" | "kind", value: string) =>
              setDeltaCanonical((current) => ({
                ...current, [delta.delta_id]: { ...fields, [field]: value },
              }));
            return <div className="schema-form-grid" key={`canonical-${delta.delta_id}`}>
              <label>Child title<input value={fields.title} disabled={busy}
                placeholder="human-confirmed permanent title"
                onChange={(event) => update("title", event.target.value)} /></label>
              <label>Child kind<select className="select" value={fields.kind}
                disabled={busy} onChange={(event) => update("kind", event.target.value)}>
                <option value="">choose one</option>
                {["note", "todo", "research", "post", "paper", "project", "bug",
                  "feature", "decision", "maintenance"].map((kind) =>
                  <option key={kind}>{kind}</option>)}
              </select></label>
              <label className="schema-form-wide">Organized description
                <textarea value={fields.description} disabled={busy}
                  onChange={(event) => update("description", event.target.value)} />
              </label>
            </div>;
          })}
        </div>
      )}
      {captureMode && finding.allowed_resolutions.some((resolution) =>
        ["add_child", "group_under_existing", "create_project_group"].includes(resolution),
      ) && <div className="schema-form-grid">
        <b className="schema-form-wide small">Canonical child fields (never copied from raw capture text)</b>
        <label>Child title<input value={canonicalTitle} disabled={busy}
          onChange={(event) => setCanonicalTitle(event.target.value)} /></label>
        <label>Child kind<select className="select" value={canonicalKind}
          disabled={busy} onChange={(event) => setCanonicalKind(event.target.value)}>
          <option value="">choose one</option>
          {["note", "todo", "research", "post", "paper", "project", "bug",
            "feature", "decision", "maintenance"].map((kind) =>
            <option key={kind}>{kind}</option>)}
        </select></label>
        <label className="schema-form-wide">Organized child description
          <textarea value={canonicalDescription} disabled={busy}
            onChange={(event) => setCanonicalDescription(event.target.value)} />
        </label>
      </div>}
      {captureMode && finding.allowed_resolutions.includes("create_project_group")
        && <div className="schema-form-grid">
          <b className="schema-form-wide small">Canonical project fields</b>
          <label>Project title<input value={projectTitle} disabled={busy}
            onChange={(event) => setProjectTitle(event.target.value)} /></label>
          <label>Project kind<select className="select" value={projectKind}
            disabled={busy} onChange={(event) => setProjectKind(event.target.value)}>
            <option value="">choose one</option>
            {["project", "todo", "feature", "maintenance"].map((kind) =>
              <option key={kind}>{kind}</option>)}
          </select></label>
          <label className="schema-form-wide">Organized project description
            <textarea value={projectDescription} disabled={busy}
              onChange={(event) => setProjectDescription(event.target.value)} />
          </label>
        </div>}
      {recommendedOk && (
        <button className="actbtn capture-primary"
          disabled={busy || !canResolve(recommended, extrasFor(recommended))}
          title={RESOLUTION_LABELS[recommended][1]}
          onClick={() => onResolve(recommended, extrasFor(recommended))}>
          ✓ {RESOLUTION_LABELS[recommended][0]} (recommended)
        </button>
      )}
      <details className="dup-more">
        <summary>More choices ▾</summary>
        <div className="dup-actions">
          {others.map((r) => (
            <button key={r} className="actbtn"
              disabled={busy || !canResolve(r, extrasFor(r))}
              title={RESOLUTION_LABELS[r][1]}
              onClick={() => onResolve(r, extrasFor(r))}>
              {RESOLUTION_LABELS[r][0]}</button>
          ))}
          <button className="editbtn" disabled={busy}
            title={RESOLUTION_LABELS.create_separate[1]}
            onClick={onDismiss}>{RESOLUTION_LABELS.create_separate[0]}</button>
        </div>
      </details>
      {captureMode && group && (
        <div className="dup-group">
          <b className="small">{group.detail}</b>
          <div className="muted small">{group.member_titles.join(" · ")}</div>
          {group.existing_parent_id ? (
            <button className="editbtn"
              title={RESOLUTION_LABELS.group_under_existing[1]}
              disabled={busy || !canResolve("group_under_existing",
                extrasFor("group_under_existing"))}
              onClick={() => onResolve("group_under_existing", {
                ...extrasFor("group_under_existing"),
                existing_work_item_id: group.existing_parent_id! })}>
              Group under “{group.existing_parent_title}”
            </button>
          ) : (
            <button className="editbtn" disabled={busy || !canResolve(
              "create_project_group", extrasFor("create_project_group"))}
              title={RESOLUTION_LABELS.create_project_group[1]}
              onClick={() => onResolve("create_project_group", {
                ...extrasFor("create_project_group"),
                member_work_item_ids: group.member_work_item_ids })}>
              Create “{group.suggested_group_title}” project
            </button>
          )}
        </div>
      )}
      {report.board_fit.length > 0 && (
        <div className="muted small">
          📌 {report.board_fit[0].detail} — a hint for the board choice below,
          never automatic.
        </div>
      )}
      <details className="dup-more">
        <summary>Why?</summary>
        <ul className="dup-evidence">
          {finding.evidence.map((e, i) => <li key={i}>{e.detail}</li>)}
          <li className="muted">semantic matching: {report.semantic_backend
            === "unavailable_lexical_only"
            ? "unavailable — exact and lexical results only" : "local"}</li>
        </ul>
      </details>
    </div>
  );
}

// Human-confirmed TODO routing: deterministic proposal -> explicit board choice
// -> one durable capture-backed item at a time. A failed later item leaves prior
// receipts and its capture id visible to recovery; no automatic retry occurs.
function TodoRoutingWizard({ text, capture, conversationId, onClose, onCommitted }: {
  text?: string;
  capture?: CaptureView;
  conversationId?: string;
  onClose: () => void;
  onCommitted: () => void;
}) {
  const [proposal, setProposal] = useState<RoutingProposal | null>(null);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [duplicateChoices, setDuplicateChoices] =
    useState<Record<string, "use_existing" | "create_separate" | "">>({});
  const [canonicalConfirmed, setCanonicalConfirmed] =
    useState<Record<string, boolean>>({});
  const [reviewedQuestions, setReviewedQuestions] = useState(false);
  const [creatingBoard, setCreatingBoard] = useState(false);
  const [boardCreateGate, setBoardCreateGate] = useState({
    ready: false,
    writable: false,
    reason: "Checking whether new kanbans can be created…",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [receipts, setReceipts] = useState<TaskCreationReceipt[]>([]);
  const [completedRefs, setCompletedRefs] = useState<string[]>([]);
  const [captureByRef, setCaptureByRef] = useState<Record<string, string>>({});
  const [rawByRef, setRawByRef] = useState<Record<string, string>>({});
  const [dismissedDups, setDismissedDups] = useState<string[]>([]);
  const [resolutionMsg, setResolutionMsg] = useState<string | null>(null);
  const sourceText = capture?.record.raw_content ?? text ?? "";

  const load = useCallback(async () => {
    setError(null);
    try {
      const next = capture
        ? await routeCapture(capture.record.capture_id)
        : await routeWorkText(sourceText, conversationId);
      if (capture && next.plan.items.length > 1) {
        throw new Error(
          "This capture contains multiple TODOs. Keep it safely in the Inbox, "
          + "then recapture it with 'bulk list' so each TODO keeps independent provenance.");
      }
      setProposal(next);
      setSelections(Object.fromEntries(next.plan.items.map((item) => [
        item.ref, item.primary_board?.board_id ?? "",
      ])));
      setDuplicateChoices(Object.fromEntries(
        next.duplicate_candidates.map((dup) => [dup.ref, ""])));
      setCanonicalConfirmed(Object.fromEntries(
        next.plan.items.map((item) => [item.ref, false])));
      setRawByRef(Object.fromEntries(
        next.plan.items.map((item) => [item.ref, item.title])));
    } catch (e) { setError((e as Error).message); }
  }, [capture, conversationId, sourceText]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    let live = true;
    fetchDomainSchema().then((schema) => {
      if (live) setBoardCreateGate({
        ready: true, writable: schema.writable, reason: schema.write_gate,
      });
    }).catch((cause) => {
      if (live) setBoardCreateGate({
        ready: true, writable: false,
        reason: `New-kanban availability could not be checked: ${(cause as Error).message}`,
      });
    });
    return () => { live = false; };
  }, []);

  const unresolvedQuestions = (proposal?.needs_confirmation ?? []).filter((question) =>
    !question.question.startsWith("Which board")
    && !question.question.includes("matches existing work")
    && !question.question.includes("looks like existing work")
    && !question.question.includes("sounds like progress on"));
  const allBoardsChosen = !!proposal && proposal.plan.items.every(
    (item) => !!selections[item.ref]);
  const allDuplicatesChosen = !!proposal && proposal.duplicate_candidates.every(
    (dup) => completedRefs.includes(dup.ref)
      || dismissedDups.includes(dup.ref) || !!duplicateChoices[dup.ref]);
  const allCanonicalConfirmed = !!proposal && proposal.plan.items.every((item) =>
    completedRefs.includes(item.ref)
      || duplicateChoices[item.ref] === "use_existing"
      || canonicalConfirmed[item.ref]);
  const matchFor = (ref: string):
      { report: DuplicateReport; finding: DuplicateFinding } | undefined => {
    const report = proposal?.duplicate_reports?.find(
      (row) => row.ref === ref)?.report;
    return report?.findings[0]
      ? { report, finding: report.findings[0] } : undefined;
  };

  async function resolveDuplicate(ref: string, finding: DuplicateFinding,
                                  resolution: string,
                                  extras?: ResolveExtras) {
    if (!capture) {          // chat flow: only reuse-existing maps to legacy
      setDuplicateChoices((c) => ({ ...c, [ref]: "use_existing" }));
      setDismissedDups((d) => [...d, ref]);
      return;
    }
    setBusy(true); setError(null);
    try {
      const result = await resolveCaptureDuplicate(capture.record.capture_id, {
        existing_work_item_id: finding.existing_work_item_id, resolution,
        match_class: finding.match_class,
        evidence_kinds: finding.evidence.map((e) => e.kind),
        ...extras,
      });
      setCompletedRefs((current) => [...current, ref]);
      setResolutionMsg(
        resolution === "add_occurrence"
          ? `Progress added to “${finding.title}” — now ${result.occurrence_count} update${result.occurrence_count === 1 ? "" : "s"}.`
          : resolution === "reopen_existing"
          ? `“${finding.title}” reopened (Ready); this capture is linked to it.`
          : resolution === "reuse_existing"
          ? `Linked to existing “${finding.title}” — nothing new created.`
          : resolution === "expand_existing"
          ? `Added ${result.applied_delta_ids?.length ?? 0} detail${(result.applied_delta_ids?.length ?? 0) === 1 ? "" : "s"} to “${finding.title}”${result.created_children?.length ? ` (+${result.created_children.length} child task${result.created_children.length === 1 ? "" : "s"})` : ""}. Title and description untouched.`
          : resolution === "add_child"
          ? `Added as a child task under “${finding.title}”.`
          : resolution === "group_under_existing"
          ? "Grouped into the project — both keep their own status."
          : resolution === "create_project_group"
          ? "Project group created — related tasks are now connected. No new board was made."
          : `Capture discarded safely — “${finding.title}” untouched; the text stays recoverable.`);
      onCommitted();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function dismissDuplicate(ref: string, finding: DuplicateFinding) {
    if (capture) {
      try {   // record-only decision; creation still flows through /convert
        await resolveCaptureDuplicate(capture.record.capture_id, {
          existing_work_item_id: finding.existing_work_item_id,
          resolution: "create_separate", match_class: finding.match_class,
        });
      } catch (e) {
        setWarnings((w) => [...w,
          "Decision telemetry failed (creation still proceeds): "
          + (e as Error).message]);
      }
    }
    setDuplicateChoices((c) => ({ ...c, [ref]: "create_separate" }));
    setDismissedDups((d) => [...d, ref]);
  }
  const canCommit = !!proposal && proposal.plan.items.length > 0
    && allBoardsChosen && allDuplicatesChosen && allCanonicalConfirmed
    && (!unresolvedQuestions.length || reviewedQuestions)
    && completedRefs.length < proposal.plan.items.length;
  const todosBoard = proposal?.routable_boards.find((board) =>
    board.board_id === "personal_todos" || board.domain_id === "generic_task");

  function boardFor(item: WorkPlanItem) {
    const boardId = selections[item.ref];
    return proposal?.routable_boards.find((board) => board.board_id === boardId);
  }

  function updateCanonicalItem(
    ref: string, field: "title" | "description" | "kind", value: string,
  ) {
    setCanonicalConfirmed((current) => ({ ...current, [ref]: false }));
    setProposal((current) => current ? {
      ...current,
      plan: {
        ...current.plan,
        items: current.plan.items.map((item) =>
          item.ref === ref ? { ...item, [field]: value } : item),
      },
    } : current);
  }

  async function commit() {
    if (!proposal || !canCommit || busy) return;
    setBusy(true); setError(null); setWarnings([]);
    const newWarnings: string[] = [];
    try {
      for (const item of proposal.plan.items) {
        if (completedRefs.includes(item.ref)) continue;
        const board = boardFor(item);
        if (!board) throw new Error("Choose a valid board for " + item.title);
        const primary = {
          board_id: board.board_id,
          domain_id: board.domain_id,
          card_component: "generic_task",
        };
        const duplicate = proposal.duplicate_candidates.find((d) => d.ref === item.ref);
        let created: TaskCreationReceipt[] = [];
        let durableCaptureId = capture?.record.capture_id ?? captureByRef[item.ref];
        if (duplicate && duplicateChoices[item.ref] === "use_existing") {
          if (capture) {
            throw new Error(
              "A capture can reuse work only when repairing its own interrupted "
              + "conversion. Choose 'create separate' or leave it safely in the Inbox.");
          }
          await addWorkPlacement(duplicate.existing_work_item_id, primary);
          const detail = await getWorkItem(duplicate.existing_work_item_id);
          created = [{
            work_item: {
              work_item_id: duplicate.existing_work_item_id,
              title: detail.item.title,
              kind: detail.item.kind,
              canonical_status: detail.item.canonical_status,
              primary_board_id: detail.item.primary_board_id,
            },
            links: await getWorkItemLinks(duplicate.existing_work_item_id),
            warnings: ["reused existing exact-title work; no duplicate was created"],
          }];
        } else {
          if (!durableCaptureId) {
            const saved = await createCapture({
              raw_content: rawByRef[item.ref],
              source_type: "chat",
              conversation_id: proposal.conversation_id ?? conversationId,
              requested_mode: "create_task",
            });
            durableCaptureId = saved.record.capture_id;
            setCaptureByRef((current) => ({
              ...current, [item.ref]: saved.record.capture_id,
            }));
          }
          const oneItemPlan = {
            conversation_id: proposal.conversation_id,
            capture_id: durableCaptureId,
            items: [{ ...item, primary_board: primary }],
            edges: [],
          };
          const result = await convertCaptureToWork(durableCaptureId, oneItemPlan);
          created = [...result.created, ...result.linked_existing];
          newWarnings.push(...result.warnings);
        }
        setReceipts((current) => [...current, ...created]);
        setCompletedRefs((current) => [...current, item.ref]);
        const suggestion = proposal.board_suggestions.find((s) => s.ref === item.ref);
        try {
          await recordRoutingCorrection({
            title: item.title,
            ref: created[0]?.work_item.work_item_id
              ? `work:${created[0].work_item.work_item_id}` : item.ref,
            suggested_board_id: suggestion?.board_id ?? null,
            chosen_board_id: board.board_id,
            conversation_id: proposal.conversation_id,
            capture_id: durableCaptureId,
            source: capture ? "capture" : "chat",
          });
        } catch (e) {
          newWarnings.push(
            "Work was created, but routing-learning evidence failed: "
            + (e as Error).message);
        }
      }
      setWarnings(newWarnings);
      onCommitted();
    } catch (e) {
      setWarnings(newWarnings);
      setError(
        (e as Error).message
        + " Previous receipts and saved chat captures are durable. Nothing was "
        + "auto-retried; choose Repair / create remaining to roll forward safely.");
    } finally { setBusy(false); }
  }

  function addCreatedBoard(boardId: string) {
    setProposal((current) => current ? {
      ...current,
      routable_boards: [...current.routable_boards, {
        board_id: boardId,
        domain_id: boardId,
        title: boardId.replace(/_/g, " "),
        columns: ["Backlog", "Ready", "In Progress", "Done", "Blocked", "Rejected", "Awaiting Approval"],
        status_mapping: {
          backlog: "Backlog", ready: "Ready", in_progress: "In Progress",
          done: "Done", blocked: "Blocked", rejected: "Rejected",
          awaiting_approval: "Awaiting Approval",
        },
      }],
    } : current);
    setSelections((current) => {
      const next = { ...current };
      for (const item of proposal?.plan.items ?? []) {
        if (!next[item.ref]) next[item.ref] = boardId;
      }
      return next;
    });
    setCreatingBoard(false);
  }

  return (
    <div className="capture-overlay" onClick={onClose}>
      <div className="capture-composer todo-router" onClick={(e) => e.stopPropagation()}>
        <div className="settings-card-head">
          <div>
            <h3>Match & Organize</h3>
            <div className="muted small">
              {proposal ? `${proposal.plan.items.length} item${proposal.plan.items.length === 1 ? "" : "s"} · nothing is created until you confirm`
                : "checking for matches…"}
            </div>
          </div>
          <button className="editbtn" onClick={onClose}>close</button>
        </div>
        {!proposal && !error && <div className="loading">splitting and checking for matching work…</div>}
        {proposal && (
          <>
            <div className="todo-destination-help">
              <b>General Todos</b> is home for everyday work — or pick an existing kanban,
              or create a new one. Possible duplicates and related work show up
              inline before anything is written.
            </div>
            {boardCreateGate.ready && !boardCreateGate.writable && (
              <div className="muted small">New kanban unavailable: {boardCreateGate.reason}</div>
            )}
            <div className="todo-route-list">
              {proposal.plan.items.map((item) => {
                const duplicate = proposal.duplicate_candidates.find((d) => d.ref === item.ref);
                const suggestion = proposal.board_suggestions.find((s) => s.ref === item.ref);
                const done = completedRefs.includes(item.ref);
                return (
                  <section className={"todo-route-item " + (done ? "todo-route-done" : "")}
                    key={item.ref}>
                    <div className="todo-route-title">
                      <b>{item.title}</b>
                      <span className="chip">{item.kind}</span>
                      {done && <span className="status-pill pill-run">created</span>}
                    </div>
                    {!done && duplicateChoices[item.ref] !== "use_existing" && (
                      <div className="schema-form-grid">
                        <div className="schema-form-wide muted small">
                          Immutable raw wording: {rawByRef[item.ref]}
                        </div>
                        <label>Canonical title<input value={item.title} disabled={busy}
                          onChange={(event) => updateCanonicalItem(
                            item.ref, "title", event.target.value)} /></label>
                        <label>Canonical kind<select className="select" value={item.kind}
                          disabled={busy} onChange={(event) => updateCanonicalItem(
                            item.ref, "kind", event.target.value)}>
                          {["note", "todo", "research", "post", "paper", "project",
                            "bug", "feature", "decision", "maintenance"].map((kind) =>
                            <option key={kind}>{kind}</option>)}
                        </select></label>
                        <label className="schema-form-wide">Organized description
                          <textarea value={item.description} disabled={busy}
                            onChange={(event) => updateCanonicalItem(
                              item.ref, "description", event.target.value)} />
                        </label>
                        <label className="capture-check schema-form-wide">
                          <input type="checkbox" checked={!!canonicalConfirmed[item.ref]}
                            disabled={busy || !item.title.trim() || !item.kind}
                            onChange={(event) => setCanonicalConfirmed((current) => ({
                              ...current, [item.ref]: event.target.checked,
                            }))} />
                          I confirm these permanent WorkItem fields. Raw capture/chat text remains separate.
                        </label>
                      </div>
                    )}
                    {suggestion && !done && (
                      <div className="todo-suggestion" title={suggestion.reason}>
                        <span>💡 Suggested board:{" "}
                          <b>{proposal.routable_boards.find((b) =>
                            b.board_id === suggestion.board_id)?.title
                            ?? suggestion.board_id}</b></span>
                        <button className="editbtn" disabled={busy}
                          onClick={() => setSelections((current) => ({
                            ...current, [item.ref]: suggestion.board_id,
                          }))}>Use it</button>
                      </div>
                    )}
                    <div className="todo-destination-choices">
                      <button className={`editbtn choice-chip ${todosBoard && selections[item.ref] === todosBoard.board_id ? "choice-on" : ""}`}
                        disabled={!todosBoard || done || busy}
                        onClick={() => todosBoard && setSelections((current) => ({
                          ...current, [item.ref]: todosBoard.board_id,
                        }))}>
                        📋 General Todos
                      </button>
                      {proposal.routable_boards.filter((board) =>
                        board.board_id !== todosBoard?.board_id)
                        .slice(0, 3).map((board) => (
                        <button key={board.board_id}
                          className={`editbtn choice-chip ${selections[item.ref] === board.board_id ? "choice-on" : ""}`}
                          disabled={done || busy}
                          onClick={() => setSelections((current) => ({
                            ...current, [item.ref]: board.board_id,
                          }))}>
                          {board.title}
                        </button>
                      ))}
                      <button className="editbtn choice-chip"
                        title={boardCreateGate.writable ? "Create a new kanban" : boardCreateGate.reason}
                        disabled={done || busy || !boardCreateGate.writable}
                        onClick={() => setCreatingBoard(true)}>＋ New kanban</button>
                    </div>
                    {proposal.routable_boards.length > 4 && (
                      <label className="chat-field"><span className="muted small">all kanbans</span>
                        <select className="select" value={selections[item.ref] ?? ""}
                          disabled={done || busy}
                          onChange={(e) => setSelections((current) => ({
                            ...current, [item.ref]: e.target.value,
                          }))}>
                          <option value="">Choose an existing kanban…</option>
                          {proposal.routable_boards.map((board) => (
                            <option key={board.board_id} value={board.board_id}>
                              {board.title}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {duplicate && !done && !dismissedDups.includes(item.ref)
                      && (() => {
                        const match = matchFor(item.ref);
                        return match ? (
                          <MatchOrganizePanel report={match.report}
                            finding={match.finding} busy={busy}
                            captureMode={!!capture}
                            onResolve={(resolution, extras) =>
                              void resolveDuplicate(item.ref, match.finding,
                                resolution, extras)}
                            onDismiss={() =>
                              void dismissDuplicate(item.ref, match.finding)} />
                        ) : (
                          <label className="chat-field">
                            <span className="muted small">
                              exact duplicate {duplicate.existing_work_item_id}
                            </span>
                            <select className="select"
                              value={duplicateChoices[item.ref] ?? ""}
                              disabled={busy}
                              onChange={(e) => setDuplicateChoices((current) => ({
                                ...current,
                                [item.ref]: e.target.value as "use_existing" | "create_separate",
                              }))}>
                              <option value="">Choose deliberately…</option>
                              {!capture && <option value="use_existing">Reuse existing work</option>}
                              <option value="create_separate">Create separate work</option>
                            </select>
                          </label>
                        );
                      })()}
                    {resolutionMsg && completedRefs.includes(item.ref) && (
                      <div className="actmsg">{resolutionMsg}</div>
                    )}
                  </section>
                );
              })}
            </div>
            <button className="editbtn"
              title={boardCreateGate.writable ? "Create a new kanban" : boardCreateGate.reason}
              disabled={busy || !boardCreateGate.writable}
              onClick={() => setCreatingBoard(true)}>+ Create a new kanban</button>
            {creatingBoard && boardCreateGate.writable && (
              <CreateBoardWizard editable={boardCreateGate.writable} routingMode
                onClose={() => setCreatingBoard(false)}
                onCreated={addCreatedBoard} />
            )}
            {unresolvedQuestions.length > 0 && (
              <label className="capture-check todo-route-review">
                <input type="checkbox" checked={reviewedQuestions}
                  onChange={(e) => setReviewedQuestions(e.target.checked)} />
                I reviewed these questions and want to create without inferred dependency edges:
                <ul>{unresolvedQuestions.map((q) => <li key={q.ref + q.question}>{q.question}</li>)}</ul>
              </label>
            )}
          </>
        )}
        {error && <div className="error">ERR {error}</div>}
        {warnings.map((warning, i) => (
          <div className="muted small" key={i}>⚠ {warning}</div>
        ))}
        {receipts.length > 0 && (
          <div className="todo-route-receipts">
            <b>Created / linked</b>
            {receipts.map((receipt) => (
              <div key={receipt.work_item.work_item_id}>
                {receipt.work_item.title}
                {receipt.links.map((link) => (
                  <a key={link.kind + link.resource_id} href={link.href}>
                    {link.label}
                  </a>
                ))}
              </div>
            ))}
          </div>
        )}
        <div className="settings-head-actions">
          <button className="actbtn" disabled={!canCommit || busy}
            onClick={() => void commit()}>
            {busy ? "creating one at a time…" : receipts.length || error
              ? "Repair / create remaining" : "Confirm & create"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Global Capture composer — a rough thought becomes a durable, recoverable
// intake record. Capturing NEVER starts work; it's saved to the Inbox for later
// classification/routing. A bulk paste is split into one capture per idea.
function CaptureComposer({ context, onClose, onCaptured, onOpenChat }: {
  context?: string; onClose: () => void; onCaptured: () => void;
  onOpenChat?: (prompt: string, conversationId?: string) => void;
}) {
  const [text, setText] = useState("");
  const [bulk, setBulk] = useState(false);
  const [mode, setMode] = useState("save_only");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [routeQueue, setRouteQueue] = useState<CaptureView[]>([]);
  async function save(chosenMode: string) {
    if (!text.trim() || busy) return;
    setMode(chosenMode);
    setBusy(true); setMsg(null);
    const extra = { requested_mode: chosenMode, current_board_id: context };
    try {
      let saved: CaptureView[] = [];
      if (bulk) {
        const r = await createCaptureBatch(text, extra);
        saved = r.captures;
        setMsg(`saved ${r.count} capture${r.count === 1 ? "" : "s"} to the Inbox`);
      } else {
        saved = [await createCapture({ raw_content: text, ...extra })];
        setMsg("saved to the Inbox");
      }
      setText("");
      onCaptured();
      if (chosenMode === "prepare_now") {
        const prepared = [];
        for (const capture of saved) {
          prepared.push(await prepareCapture(capture.record.capture_id));
        }
        if (prepared[0] && onOpenChat) {
          onOpenChat(prepared[0].chat_prompt, prepared[0].conversation_id);
          onClose();
        } else {
          setRouteQueue(saved);
        }
      } else if (chosenMode === "create_task") {
        setRouteQueue(saved);
      }
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  if (routeQueue.length > 0) {
    const current = routeQueue[0];
    return (
      <TodoRoutingWizard capture={current} onClose={() => {
        setRouteQueue([]);
        if (mode === "prepare_now") onClose();
      }}
        onCommitted={() => {
          if (routeQueue.length === 1) {
            setRouteQueue([]);
            onClose();
          } else {
            setRouteQueue((queue) => queue.slice(1));
          }
        }} />
    );
  }
  return (
    <div className="capture-overlay" onClick={onClose}>
      <div className="capture-composer" onClick={(e) => e.stopPropagation()}>
        <div className="settings-card-head">
          <h3>Capture{context ? ` · ${context}` : ""}</h3>
          <button className="editbtn" onClick={onClose}>close</button>
        </div>
        <textarea className="capture-text" value={text} autoFocus rows={5}
          placeholder="What are you thinking about? (a note, todo, idea, post, paper, or a repo task)"
          onChange={(e) => setText(e.target.value)} />
        <label className="capture-check">
          <input type="checkbox" checked={bulk}
            onChange={(e) => setBulk(e.target.checked)} /> bulk list (one capture per line/bullet)
        </label>
        <div className="capture-actions">
          {onOpenChat ? (
            <button className="actbtn capture-primary"
              disabled={busy || !text.trim()}
              title="Save it, then open a chat that routes it to General Todos, an existing kanban, or a new one"
              onClick={() => void save("prepare_now")}>
              {busy && mode === "prepare_now" ? "opening chat…" : "⚡ Prepare now → chat"}
            </button>
          ) : (
            <button className="actbtn capture-primary"
              disabled={busy || !text.trim()}
              title="Save it, then choose a board and confirm"
              onClick={() => void save("create_task")}>
              {busy && mode === "create_task" ? "saving…" : "Create a task → choose board"}
            </button>
          )}
          <div className="capture-secondary">
            <button className="linkbtn" disabled={busy || !text.trim()}
              title="Just save it to the Inbox — nothing runs and nothing is routed"
              onClick={() => void save("save_only")}>Save only</button>
            <span className="capture-sep">·</span>
            <button className="linkbtn" disabled={busy || !text.trim()}
              title="Save it and let the daily prepare pass route it later"
              onClick={() => void save("prepare_later")}>Prepare later</button>
            {onOpenChat && (
              <>
                <span className="capture-sep">·</span>
                <button className="linkbtn" disabled={busy || !text.trim()}
                  title="Save it, then pick a board and confirm each task — no chat"
                  onClick={() => void save("create_task")}>Create a task</button>
              </>
            )}
          </div>
        </div>
        <div className="muted small capture-hint">
          {onOpenChat
            ? "Saved first, then a capture-scoped chat opens with General Todos, existing-kanban, and new-kanban choices."
            : "Chat is disabled in this deployment — “Create a task” saves it, then lets you pick a board and confirm. Nothing runs until you choose."}
          {msg && <> · {msg}</>}
        </div>
      </div>
    </div>
  );
}

// The Universal Inbox — every capture, grouped into its lane. Recoverable here
// even after it's routed. Read-only for now (classification/routing are later).
function InboxView({ refreshKey, onOpenChat }: {
  refreshKey: number;
  onOpenChat?: (prompt: string, conversationId?: string, storyTs?: string, target?: string) => void;
}) {
  const [inbox, setInbox] = useState<InboxData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [activeCapture, setActiveCapture] = useState<CaptureView | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  useEffect(() => {
    let live = true;
    fetchInbox().then((d) => live && setInbox(d)).catch((e) => live && setErr((e as Error).message));
    return () => { live = false; };
  }, [refreshKey, reloadNonce]);
  async function prepareNow(captureId: string) {
    if (!onOpenChat) {
      setActionMsg("Chat is not enabled in this deployment; choose a destination instead.");
      return;
    }
    setActionBusy(captureId); setActionMsg(null);
    try {
      const prepared = await prepareCapture(captureId);
      setReloadNonce((n) => n + 1);
      onOpenChat?.(prepared.chat_prompt, prepared.conversation_id);
    } catch (e) { setActionMsg((e as Error).message); }
    finally { setActionBusy(null); }
  }
  async function routeNow(captureId: string) {
    setActionBusy(captureId); setActionMsg(null);
    try { setActiveCapture(await fetchCapture(captureId)); }
    catch (e) { setActionMsg((e as Error).message); }
    finally { setActionBusy(null); }
  }
  if (activeCapture) {
    return <TodoRoutingWizard capture={activeCapture}
      onClose={() => setActiveCapture(null)}
      onCommitted={() => {
        setActiveCapture(null);
        setReloadNonce((n) => n + 1);
      }} />;
  }
  if (err) return <div className="error">Inbox unavailable — {err}</div>;
  if (!inbox) return <div className="loading">…</div>;
  if (inbox.total === 0) {
    return <div className="empty">No captures yet. Use <b>+ Capture</b> to save an idea, todo, or note.</div>;
  }
  return (
    <div className="inbox-view">
      <div className="muted small">{inbox.total} capture{inbox.total === 1 ? "" : "s"} · saved, not started</div>
      {actionMsg && <div className="error">ERR {actionMsg}</div>}
      <div className="inbox-columns">
        {inbox.columns.map((col) => (
          <section className="inbox-col" key={col.name}>
            <h3>{col.name.replace(/_/g, " ")} <span className="status-pill">{col.captures.length}</span></h3>
            {col.captures.map((c) => (
              <div className="inbox-card" key={c.capture_id}>
                <div className="inbox-card-body">{c.preview}</div>
                <div className="inbox-card-meta muted small">
                  {c.capture_kind ?? "unclassified"}
                  {c.suggested_board_id ? ` → ${c.suggested_board_id}` : ""}
                  {c.batch_id ? " · batch" : ""} · {c.requested_mode.replace(/_/g, " ")}
                  <span className="status-pill">{c.processing_status.replace(/_/g, " ")}</span>
                </div>
                <div className="inbox-card-actions">
                  {!["routed", "archived"].includes(c.processing_status) ? (
                    <>
                      <button className="actbtn"
                        title={onOpenChat ? "Prepare in chat" : "Chat is disabled in this deployment"}
                        disabled={!onOpenChat || actionBusy === c.capture_id}
                        onClick={() => void prepareNow(c.capture_id)}>
                        {actionBusy === c.capture_id ? "opening…" : "Prepare in chat"}
                      </button>
                      <button className="editbtn" disabled={actionBusy === c.capture_id}
                        onClick={() => void routeNow(c.capture_id)}>Choose destination</button>
                    </>
                  ) : <span className="muted small">Destination already recorded.</span>}
                </div>
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}

// ── Life Center Launch ────────────────────────────────────────────────────
// A read-only launcher tab over the service catalog joined with the three Life
// Center Kanban boards (GET /api/life-center/launch). This replaces the old
// temp-file HTML launcher with a real tab inside the SPA. Tiles + a details
// drawer; dispatched actions render their raw status/error honestly (several
// are Docker-CLI-dependent and intentionally return errors in-container).
const LC_HEALTH_META: Record<string, { label: string; tone: string }> = {
  healthy: { label: "Healthy", tone: "good" },
  attention: { label: "Attention", tone: "warn" },
  down: { label: "Down", tone: "bad" },
  unknown: { label: "Unknown", tone: "" },
};
function lcHealthMeta(status: string): { label: string; tone: string } {
  return LC_HEALTH_META[status] ?? { label: status || "Unknown", tone: "" };
}
function lcCapitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}
// Non-http hrefs (runbook / repo-relative doc paths) are resolved by the
// backend, not the browser — only real URLs become <a href> "Open" buttons.
function lcIsUrl(href: string | null): href is string {
  return !!href && /^https?:\/\//i.test(href);
}
function lcNeedsSetup(svc: LifeCenterService): boolean {
  return svc.setup.required && !svc.setup.completed;
}
function lcNeedsAttention(svc: LifeCenterService): boolean {
  return svc.health.status === "attention" || svc.health.status === "down";
}
function lcActionLabel(id: string): string {
  return lcCapitalize(id.replace(/^life_center\./, "").replace(/_/g, " "));
}

// One dispatch button that owns its own busy/result state. The returned status
// (ok | error | rejected) and error string are shown verbatim — dispatch is
// never assumed to succeed.
function LifeCenterActionButton({ actionId, serviceId, label }: {
  actionId: string; serviceId?: string; label: string;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<LifeCenterDispatchResult | null>(null);
  const [err, setErr] = useState("");
  const run = useCallback(async () => {
    setBusy(true); setErr("");
    try {
      const r = await dispatchLifeCenterAction({
        action_id: actionId, service_id: serviceId,
        idempotency_key: `${actionId}:${serviceId ?? "global"}:${Date.now()}`,
      });
      setResult(r);
    } catch (e) {
      setErr((e as Error).message); setResult(null);
    } finally {
      setBusy(false);
    }
  }, [actionId, serviceId]);
  const hasResultBody = !!result && Object.keys(result.result ?? {}).length > 0;
  return (
    <div className="lc-action">
      <button className="actbtn" onClick={() => void run()} disabled={busy}>
        {busy ? "Running…" : label}
      </button>
      {err && <div className="actmsg lc-status-error">request failed: {err}</div>}
      {result && (
        <div className={`actmsg lc-status-${result.status}`}>
          <b>{result.status}</b>{result.error ? ` — ${result.error}` : ""}
          {!result.error && hasResultBody && (
            <pre className="lc-result-json">{JSON.stringify(result.result, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}

// A runbook is a link kind whose href is a repo path, so it is fetched through
// the backend runbook endpoint and rendered as markdown with the shared
// MarkdownText component (no second renderer, no markdown dependency).
function LifeCenterRunbookViewer({ serviceId }: { serviceId: string }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const toggle = useCallback(async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (content !== null || busy) return;
    setBusy(true); setErr("");
    try {
      setContent((await fetchLifeCenterRunbook(serviceId)).content);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [open, content, busy, serviceId]);
  return (
    <div className="lc-runbook">
      <button className="actbtn" onClick={() => void toggle()}>
        {open ? "Hide runbook" : "View runbook"}
      </button>
      {open && (
        busy ? <div className="loading">…</div>
          : err ? <div className="error">{err}</div>
            : content !== null
              ? <div className="lc-runbook-body"><MarkdownText value={content} /></div>
              : null
      )}
    </div>
  );
}

function LifeCenterLinkButton({ link, svc, onOpen }: {
  link: LifeCenterLink; svc: LifeCenterService; onOpen: () => void;
}) {
  const label = link.kind === "app" ? svc.primary_action_label : lcCapitalize(link.kind);
  if (lcIsUrl(link.href)) {
    return <a className="actbtn" href={link.href} target="_blank" rel="noreferrer">{label}</a>;
  }
  // href is a backend-resolved path (e.g. a runbook) — open the drawer, which
  // renders it inline, instead of pointing a browser at a non-URL.
  return (
    <button className="actbtn" onClick={onOpen} title="Opens in Details">{label}</button>
  );
}

function LifeCenterTile({ svc, onOpen }: {
  svc: LifeCenterService; onOpen: () => void;
}) {
  const health = lcHealthMeta(svc.health.status);
  return (
    <div className="lc-tile">
      <div className="lc-tile-head">
        <span className="lc-tile-title">{svc.application}</span>
        <span className={`domain-badge ${health.tone}`}>{health.label}</span>
      </div>
      {svc.short_description
        ? <p className="lc-tile-desc">{svc.short_description}</p>
        : <p className="lc-tile-desc muted">No description provided.</p>}
      <div className="domain-badges">
        <span className="domain-badge">Risk: {svc.risk_tier || "unknown"}</span>
        {lcNeedsSetup(svc) && <span className="domain-badge warn">Needs setup</span>}
        {svc.health.stale && <span className="domain-badge">Status stale</span>}
      </div>
      <div className="lc-tile-actions">
        {svc.links.map((link) => (
          <LifeCenterLinkButton key={link.kind} link={link} svc={svc} onOpen={onOpen} />
        ))}
        <button className="actbtn lc-details-btn" onClick={onOpen}>Details</button>
      </div>
    </div>
  );
}

function LifeCenterServiceDrawer({ svc, onClose }: {
  svc: LifeCenterService; onClose: () => void;
}) {
  const health = lcHealthMeta(svc.health.status);
  const runbookLink = svc.links.find((l) => l.kind === "runbook");
  return (
    <DrawerShell title={svc.application} onClose={onClose}>
      <div className="lc-drawer">
        <div className="domain-badges lc-drawer-badges">
          <span className={`domain-badge ${health.tone}`}>{health.label}</span>
          <span className="domain-badge">Risk: {svc.risk_tier || "unknown"}</span>
          <span className="domain-badge">{svc.category || "uncategorized"}</span>
          {lcNeedsSetup(svc) && <span className="domain-badge warn">Needs setup</span>}
        </div>

        <section className="lc-section">
          <h3>Overview</h3>
          {svc.short_description
            ? <p>{svc.short_description}</p>
            : <p className="muted">No description provided.</p>}
          <div className="kv">Lifecycle: <b>{svc.lifecycle || "—"}</b></div>
          <div className="kv">
            Admission lane: <b>{svc.admission.lane || "—"}</b>
            {svc.admission.owner ? <> · owner <b>{svc.admission.owner}</b></> : null}
          </div>
          <div className="kv">
            Last health check: <b>{svc.health.last_check ? dateText(svc.health.last_check) : "never"}</b>
            {svc.health.stale ? " (stale)" : ""}
          </div>
          <p className="muted small">
            The launch API exposes no long-form description field (no
            <code> long_description</code>) — showing the catalog short description only.
          </p>
        </section>

        <section className="lc-section">
          <h3>Setup</h3>
          {svc.setup.required ? (
            <>
              <div className="kv">
                Required: <b>Yes</b> · Completed: <b>{svc.setup.completed ? "Yes" : "No"}</b>
              </div>
              {svc.setup.evidence_refs && (
                <div className="kv">Evidence: <b>{svc.setup.evidence_refs}</b></div>
              )}
              {svc.setup.operations_card_id
                ? <div className="kv">
                    Operations card: <code>{svc.setup.operations_card_id}</code>{" "}
                    <span className="muted small">on the life_center_operations board</span>
                  </div>
                : <div className="muted">No operations card linked yet.</div>}
            </>
          ) : <div className="muted">No setup required for this service.</div>}
        </section>

        <section className="lc-section">
          <h3>Access</h3>
          {svc.links.length === 0 ? (
            <div className="muted">No links registered.</div>
          ) : (
            <div className="lc-tile-actions">
              {svc.links.map((link) => lcIsUrl(link.href)
                ? <a key={link.kind} className="actbtn" href={link.href}
                    target="_blank" rel="noreferrer">
                    {link.kind === "app" ? svc.primary_action_label : lcCapitalize(link.kind)}
                  </a>
                : <span key={link.kind} className="lc-link-path">
                    <b>{lcCapitalize(link.kind)}:</b> <code>{link.href ?? "—"}</code>
                  </span>)}
            </div>
          )}
          {runbookLink && <LifeCenterRunbookViewer serviceId={svc.service_id} />}
        </section>

        <section className="lc-section">
          <h3>Recovery</h3>
          <div className="muted">
            Structured recovery data is not yet surfaced by the launch API.
            {runbookLink ? " See the service runbook above (under Access) for operational recovery steps." : ""}
          </div>
        </section>

        <section className="lc-section">
          <h3>Automation</h3>
          {svc.service_action_ids.length === 0 ? (
            <div className="muted">No service actions.</div>
          ) : (
            <div className="lc-actions-col">
              {svc.service_action_ids.map((id) => (
                <LifeCenterActionButton key={id} actionId={id}
                  serviceId={svc.service_id} label={lcActionLabel(id)} />
              ))}
            </div>
          )}
          <p className="muted small">
            Some actions require Docker CLI access the containerized cockpit
            intentionally does not have and will return an error — the raw
            result is shown exactly as returned.
          </p>
        </section>

        <section className="lc-section">
          <h3>History</h3>
          <div className="muted">No receipt history is recorded for Life Center actions yet.</div>
        </section>
      </div>
    </DrawerShell>
  );
}

function LifeCenterView() {
  const [launch, setLaunch] = useState<LifeCenterLaunch | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [onlySetup, setOnlySetup] = useState(false);
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      setLaunch(await fetchLifeCenterLaunch());
    } catch (e) {
      setError((e as Error).message); setLaunch(null);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const services = launch?.services ?? [];
  const categories = useMemo(
    () => Array.from(new Set(services.map((s) => s.category).filter(Boolean))).sort(),
    [services]);
  const q = query.trim().toLowerCase();
  const filtered = useMemo(() => services.filter((svc) => {
    if (category !== "all" && svc.category !== category) return false;
    if (onlySetup && !lcNeedsSetup(svc)) return false;
    if (onlyAttention && !lcNeedsAttention(svc)) return false;
    if (q && !`${svc.application} ${svc.short_description}`.toLowerCase().includes(q)) return false;
    return true;
  }), [services, category, onlySetup, onlyAttention, q]);

  // Group by category, sort within each by sort_order then application name.
  // (The backend already sorts services this way, but grouping re-partitions
  // them, so we re-sort defensively rather than assume order survives.)
  const groups = useMemo(() => {
    const m = new Map<string, LifeCenterService[]>();
    for (const svc of filtered) {
      const key = svc.category || "uncategorized";
      const list = m.get(key);
      if (list) list.push(svc); else m.set(key, [svc]);
    }
    return Array.from(m.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([cat, list]) => [cat, list.slice().sort(
        (x, y) => x.sort_order - y.sort_order || x.application.localeCompare(y.application),
      )] as const);
  }, [filtered]);

  const selected = selectedId
    ? services.find((s) => s.service_id === selectedId) ?? null
    : null;

  if (loading && !launch) return <div className="loading">Loading Life Center…</div>;
  if (error && !launch) {
    return (
      <div className="lc-view">
        <div className="error">Life Center unavailable: {error}</div>
        <button className="actbtn" onClick={() => void load()}>Retry</button>
      </div>
    );
  }
  if (!launch) return <div className="empty">No Life Center data.</div>;

  const s = launch.summary;
  const summaryCells: { label: string; value: number; tone: string }[] = [
    { label: "Total", value: s.total, tone: "" },
    { label: "Healthy", value: s.healthy, tone: "good" },
    { label: "Attention", value: s.attention, tone: "warn" },
    { label: "Setup pending", value: s.setup_pending, tone: "warn" },
    { label: "Unknown", value: s.unknown, tone: "" },
  ];

  return (
    <div className="lc-view">
      <div className="lc-header">
        <div className="lc-summary">
          {summaryCells.map((cell) => (
            <div className={`lc-summary-cell ${cell.tone}`} key={cell.label}>
              <span className="lc-summary-value">{cell.value}</span>
              <span className="lc-summary-label">{cell.label}</span>
            </div>
          ))}
        </div>
        <div className="lc-global">
          <div className="lc-global-actions">
            {launch.global_action_ids.map((id) => (
              <LifeCenterActionButton key={id} actionId={id} label={lcActionLabel(id)} />
            ))}
            <button className="actbtn" onClick={() => void load()}>Reload</button>
          </div>
          <div className="obs-foot">
            status {launch.status_stale ? "stale" : "current"}
            {launch.status_generated_at ? ` · updated ${dateText(launch.status_generated_at)}` : ""}
          </div>
        </div>
      </div>

      <div className="filterbar">
        <input className="search" placeholder="Filter by name or description…"
          value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="select" value={category}
          onChange={(e) => setCategory(e.target.value)}>
          <option value="all">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button className={`chip-check ${onlySetup ? "chip-on" : ""}`}
          aria-pressed={onlySetup} onClick={() => setOnlySetup((v) => !v)}>
          Setup pending
        </button>
        <button className={`chip-check ${onlyAttention ? "chip-on" : ""}`}
          aria-pressed={onlyAttention} onClick={() => setOnlyAttention((v) => !v)}>
          Needs attention
        </button>
        {(query || category !== "all" || onlySetup || onlyAttention) && (
          <button className="clear" onClick={() => {
            setQuery(""); setCategory("all"); setOnlySetup(false); setOnlyAttention(false);
          }}>clear</button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div className="empty">No services match the current filters.</div>
      ) : (
        groups.map(([cat, list]) => (
          <section className="lc-group" key={cat}>
            <h3>{cat} <span className="muted">({list.length})</span></h3>
            <div className="lc-grid">
              {list.map((svc) => (
                <LifeCenterTile key={svc.service_id} svc={svc}
                  onOpen={() => setSelectedId(svc.service_id)} />
              ))}
            </div>
          </section>
        ))
      )}

      {selected && (
        <LifeCenterServiceDrawer svc={selected} onClose={() => setSelectedId(null)} />
      )}
    </div>
  );
}

type AgentUsageDetailLoad =
  | { state: "loading" }
  | { state: "ready"; detail: AgentUsageDetail }
  | { state: "error"; error: string };

function UsageView() {
  const [windowId, setWindowId] = useState<UsageWindowId>("week");
  const [lane, setLane] = useState<"all" | "agents" | "local" | "openrouter">("all");
  const [query, setQuery] = useState("");
  const [statuses, setStatuses] = useState<UsageStatus[] | null>(null);
  const [portfolio, setPortfolio] = useState<ModelUsagePortfolio | null>(null);
  const [portfolioError, setPortfolioError] = useState("");
  const [agentModels, setAgentModels] = useState<Record<string, UsageDriverRow[]>>({});
  const [agentDetailLoads, setAgentDetailLoads] = useState<
    Record<string, AgentUsageDetailLoad>
  >({});
  const [health, setHealth] = useState<CollectorHealth[]>([]);
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState<string | null>(null);
  const loadSequence = useRef(0);

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setError("");
    try {
      const [usageRows, portfolioLoad] = await Promise.all([
        fetchModelUsage(windowId),
        fetchModelUsagePortfolio(windowId).then(
          (value) => ({ value, error: "" }),
          (reason: unknown) => ({
            value: null,
            error: reason instanceof Error ? reason.message : String(reason),
          }),
        ),
      ]);
      if (sequence !== loadSequence.current) return;
      setStatuses(usageRows);
      setPortfolio(portfolioLoad.value);
      setPortfolioError(portfolioLoad.error);
      setAgentDetailLoads((current) => Object.fromEntries(usageRows.map((status) => [
        status.runtime_id, current[status.runtime_id] ?? { state: "loading" },
      ] as const)));
      const driverPairs = await Promise.all(usageRows.map(async (status) => {
        try {
          const drivers = await fetchModelUsageDrivers(status.runtime_id, windowId);
          return [status.runtime_id,
            drivers.rows.map((row) => (
              row.key === "(unattributed)"
                ? { ...row, key: "Model not recorded" }
                : row
            ))] as const;
        } catch {
          return [status.runtime_id, []] as const;
        }
      }));
      if (sequence !== loadSequence.current) return;
      setAgentModels(Object.fromEntries(driverPairs));
      const detailPairs = await Promise.all(usageRows.map(async (
        status,
      ): Promise<readonly [string, AgentUsageDetailLoad]> => {
        try {
          return [status.runtime_id,
            { state: "ready",
              detail: await fetchRecentAgentUsage(status.runtime_id, windowId) }];
        } catch (e) {
          return [status.runtime_id,
            { state: "error", error: (e as Error).message }];
        }
      }));
      if (sequence !== loadSequence.current) return;
      setAgentDetailLoads(Object.fromEntries(detailPairs));
      try { setHealth(await fetchCollectorHealth()); } catch { setHealth([]); }
      if (sequence !== loadSequence.current) return;
      setLastCheckedAt(new Date().toISOString());
    } catch (e) {
      if (sequence !== loadSequence.current) return;
      setStatuses(null);
      setPortfolio(null);
      setAgentDetailLoads({});
      setError((e as Error).message);
    }
  }, [windowId]);
  useEffect(() => {
    setStatuses(null);
    setPortfolio(null);
    setAgentModels({});
    setAgentDetailLoads({});
    void load();
    const timer = window.setInterval(() => { void load(); }, 30_000);
    return () => {
      window.clearInterval(timer);
      loadSequence.current += 1;
    };
  }, [load]);

  const doRefresh = useCallback(async () => {
    setBusy(true);
    try { await refreshModelUsage(); await load(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }, [load]);

  const normalizedQuery = query.trim().toLowerCase();
  const matchesQuery = (...values: (string | null | undefined)[]) => (
    !normalizedQuery || values.some((value) => (
      value ?? "").toLowerCase().includes(normalizedQuery))
  );
  const visibleStatuses = (statuses ?? [])
    .filter((status) => !(
      status.runtime_id === "claude_agent"
      && status.limits.length === 0
      && status.rolled_usage === null
    ))
    .map((status) => ({
      ...status,
      limits: status.limits.filter((limit) => !isRetiredCodexLimit(limit)),
    }))
    .filter((_status) => lane === "all" || lane === "agents")
    .filter((status) => matchesQuery(
      status.runtime_id,
      RUNTIME_LABELS[status.runtime_id],
      ...((agentModels[status.runtime_id] ?? []).map((model) => model.key)),
    ));
  const modelMatches = (model: ModelUsageEntry) => matchesQuery(
    model.provider, model.model_id, ...model.roles, ...model.aliases,
    ...model.purpose_breakdown.map((purpose) => purpose.purpose),
  );
  const localModels = portfolio?.models.filter(
    (model) => model.lane === "local"
      && (lane === "all" || lane === "local")
      && modelMatches(model),
  ) ?? [];
  const openRouterModels = portfolio?.models.filter(
    (model) => model.lane === "openrouter"
      && (lane === "all" || lane === "openrouter")
      && modelMatches(model),
  ) ?? [];
  const observedModels = [...localModels, ...openRouterModels].filter(
    (model) => model.calls !== null && model.calls > 0,
  );
  const visibleAgentModels = visibleStatuses.flatMap(
    (status) => (agentModels[status.runtime_id] ?? []).filter(
      (model) => matchesQuery(model.key)),
  );
  const modelIdentities = new Set([
    ...observedModels.map((model) => model.provider + model.model_id),
    ...visibleAgentModels.filter(
      (model) => model.key !== "Model not recorded",
    ).map((model) => model.key),
  ]);
  const totalTokens = observedModels.reduce(
    (total, model) => total + (model.total_tokens ?? 0), 0,
  ) + visibleStatuses.reduce(
    (total, status) => total + (status.rolled_usage?.total_tokens ?? 0), 0,
  );
  const totalCalls = observedModels.reduce(
    (total, model) => total + (model.calls ?? 0), 0,
  ) + visibleStatuses.reduce(
    (total, status) => total + (status.rolled_usage?.calls ?? 0), 0,
  );
  const openRouterSpend = openRouterModels.reduce(
    (total, model) => total + (model.cost_usd ?? 0), 0,
  );
  const completeSources = portfolio?.sources.filter(
    (source) => source.state === "ok" || source.state === "empty",
  ).length ?? 0;
  const periodLabel = portfolio?.window.label ?? (
    { day: "Past 24 hours", week: "Past 7 days",
      month: "Past 30 days", all: "All retained" }[windowId]);

  return (
    <div className="usage-view">
      <div className="usage-head">
        <div>
          <div className="usage-kicker">Full-stack model telemetry</div>
          <h2>Usage &amp; Limits</h2>
          <p>Recorded model activity, current subscription limits, and source
            freshness in one evidence-backed view.</p>
          <div className="usage-live-line">
            <span className="usage-live-dot" />
            Reads live sources every 30 seconds
            <span>Last checked {fmtObserved(lastCheckedAt)}</span>
          </div>
        </div>
        <button className="btn" onClick={() => void doRefresh()} disabled={busy}>
          {busy ? "refreshing…" : "Refresh"}
        </button>
      </div>
      <div className="usage-toolbar" aria-label="Usage filters">
        <div className="usage-window-tabs" role="group" aria-label="Usage period">
          {([
            ["day", "24 hours"], ["week", "7 days"],
            ["month", "30 days"], ["all", "All retained"],
          ] as [UsageWindowId, string][]).map(([value, label]) => (
            <button key={value} type="button"
              className={windowId === value ? "active" : ""}
              aria-pressed={windowId === value}
              onClick={() => setWindowId(value)}>{label}</button>
          ))}
        </div>
        <label className="usage-filter-field">
          <span>Lane</span>
          <select value={lane} onChange={(event) => setLane(
            event.target.value as typeof lane)}>
            <option value="all">All providers</option>
            <option value="agents">Coding agents</option>
            <option value="local">Local models</option>
            <option value="openrouter">OpenRouter</option>
          </select>
        </label>
        <label className="usage-filter-field usage-search">
          <span>Find</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)}
            placeholder="Model, role, or purpose" />
        </label>
      </div>
      {error && <div className="usage-note bad">{error}</div>}
      {portfolioError && (
        <div className="usage-note bad">Model portfolio unavailable: {portfolioError}</div>
      )}
      {statuses && portfolio && (
        <div className="usage-summary">
          <div className="usage-summary-item">
            <span>Recorded tokens · {periodLabel}</span><strong>{fmtInt(totalTokens)}</strong>
          </div>
          <div className="usage-summary-item">
            <span>Recorded calls · {periodLabel}</span><strong>{fmtInt(totalCalls)}</strong>
          </div>
          <div className="usage-summary-item">
            <span>Identified models active</span><strong>{fmtInt(modelIdentities.size)}</strong>
          </div>
          <div className="usage-summary-item">
            <span>Estimated OpenRouter cost</span>
            <strong>${openRouterSpend.toFixed(4)}</strong>
          </div>
          <div className="usage-summary-item">
            <span>Complete source reads</span>
            <strong>{completeSources}/{portfolio?.sources.length ?? 0}</strong>
          </div>
        </div>
      )}
      {statuses && (lane === "all" || lane === "agents")
        && visibleStatuses.length === 0 && !error && (
        <div className="usage-note muted">
          No coding-agent cards match this period and filter.
          Empty inactive lanes stay hidden.
        </div>
      )}
      {(lane === "all" || lane === "agents") && visibleStatuses.length > 0 && (
        <section className="usage-section">
          <div className="usage-section-head">
            <div><span>Coding subscriptions</span><h3>Coding agents</h3></div>
            <b>{visibleStatuses.length}</b>
          </div>
          <div className="usage-cards">
            {visibleStatuses.map((status) => (
              <UsageCard key={status.runtime_id} s={status}
                models={agentModels[status.runtime_id] ?? []}
                detailLoad={agentDetailLoads[status.runtime_id] ?? { state: "loading" }} />
            ))}
          </div>
        </section>
      )}
      {portfolio && (
        <>
          {(lane === "all" || lane === "local") && (
            <ModelUsageSection title="Local models" eyebrow="Ollama and local frontier"
              models={localModels}
              emptyText="No local models match these filters in the selected period." />
          )}
          {(lane === "all" || lane === "openrouter") && (
            <ModelUsageSection title="OpenRouter usage" eyebrow="Paid frontier routing"
              models={openRouterModels}
              emptyText="No OpenRouter models match these filters in the selected period." />
          )}
        </>
      )}
      {portfolio && (
        <section className="usage-section usage-source-section">
          <div className="usage-section-head">
            <div><span>Evidence freshness</span><h3>Data sources</h3></div>
          </div>
          <div className="usage-sources">
            {portfolio.sources.map((source) => (
              <div className="usage-source" key={source.source_id}>
                <span className={`usage-source-dot ${source.state}`} />
                <div>
                  <strong>{source.label}</strong>
                  <small>{source.detail}</small>
                  {source.included_row_count !== source.row_count && (
                    <small>{fmtInt(source.included_row_count)} calls attributed
                      to displayed models</small>
                  )}
                  <small>Newest event {fmtObserved(source.latest_observed_at ?? null)}</small>
                </div>
                <b>{humanLabel(source.state)}</b>
              </div>
            ))}
          </div>
        </section>
      )}
      {health.length > 0 && (
        <details className="usage-health">
          <summary>Collector diagnostics <span>{health.length}</span></summary>
          <div className="usage-table-wrap">
            <table className="tool-table">
              <thead><tr><th>Collector</th><th>Authentication</th><th>Failures</th><th>Last success</th><th>Last error</th></tr></thead>
              <tbody>
                {health.map((item) => (
                  <tr key={item.collector_id}>
                    <td>{humanLabel(item.collector_id)}</td>
                    <td>{item.never_ran ? "Never ran" : humanLabel(item.auth_state)}</td>
                    <td>{item.consecutive_failures}</td>
                    <td>{item.last_success_at ? fmtReset(item.last_success_at) : "—"}</td>
                    <td className="usage-err">{humanText(item.last_error ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
function ModelUsageSection({ title, eyebrow, models, emptyText }: {
  title: string; eyebrow: string; models: ModelUsageEntry[]; emptyText: string;
}) {
  return (
    <section className="usage-section">
      <div className="usage-section-head">
        <div><span>{eyebrow}</span><h3>{title}</h3></div>
        <b>{models.length}</b>
      </div>
      {models.length === 0 ? (
        <div className="usage-note muted">{emptyText}</div>
      ) : (
        <div className="usage-model-grid">
          {models.map((model) => (
            <ModelUsageCard key={model.provider + model.model_id} model={model} />
          ))}
        </div>
      )}
    </section>
  );
}
function UsageKpiGrid({ kpis }: { kpis: UsageKpis }) {
  const metrics = [
    ["Average tokens / call", fmtKpi(kpis.average_tokens_per_call)],
    ["Average output / call", fmtKpi(kpis.average_output_tokens_per_call)],
    ["Output share", fmtKpi(kpis.output_share_percent, "%")],
    ["Average runtime", fmtDuration(kpis.average_duration_ms)],
  ];
  if (kpis.success_rate_percent !== null) {
    metrics.push([
      "Recorded success rate", fmtKpi(kpis.success_rate_percent, "%"),
    ]);
  }
  if (kpis.cached_input_share_percent !== undefined) {
    metrics.push([
      "Cached input share", fmtKpi(kpis.cached_input_share_percent, "%"),
    ]);
  }
  if (kpis.cost_per_call_usd !== null) {
    metrics.push([
      "Tracked cost / call", "$" + kpis.cost_per_call_usd.toFixed(6),
    ]);
  }
  return (
    <div className="usage-kpi-grid">
      {metrics.map(([label, value]) => (
        <div key={label}><span>{label}</span><strong>{value}</strong></div>
      ))}
    </div>
  );
}
function RecentUsageList({ rows }: { rows: UsageRecentActivity[] }) {
  if (rows.length === 0) {
    return <div className="usage-model-empty">No recent attributed usage is recorded.</div>;
  }
  return (
    <div className="usage-recent-list">
      {rows.map((row, index) => (
        <div className="usage-recent-row"
          key={(row.observed_at ?? "unknown") + row.purpose + index}>
          <div className="usage-recent-purpose">
            <strong>{humanText(row.purpose)}</strong>
            <span>{fmtObserved(row.observed_at)}
              {row.model ? " · " + row.model : ""}
              {row.effort ? " · " + humanLabel(row.effort) + " effort" : ""}
            </span>
          </div>
          <div className="usage-recent-metrics">
            <span><b>{fmtInt(row.total_tokens)}</b> tokens</span>
            <span><b>{fmtInt(row.output_tokens)}</b> output</span>
            {row.duration_ms !== null && <span><b>{fmtDuration(row.duration_ms)}</b></span>}
            {row.cost_usd !== null && (
              <span><b>${row.cost_usd.toFixed(6)}</b>
                {row.cost_source === "estimated_from_recorded_tokens"
                  ? " estimated" : ""}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
function PurposeBreakdown({ model }: { model: ModelUsageEntry }) {
  if (model.purpose_breakdown.length === 0) return null;
  return (
    <div className="usage-purpose-list">
      {model.purpose_breakdown.map((purpose) => (
        <div key={purpose.purpose}>
          <span>{humanLabel(purpose.purpose)}</span>
          <strong>{purpose.calls} calls · {purpose.share_percent}%</strong>
        </div>
      ))}
    </div>
  );
}
function ModelUsageCard({ model }: { model: ModelUsageEntry }) {
  const sourceUnavailable = model.calls === null;
  const hasUsage = model.calls !== null && model.calls > 0;
  const observed = model.last_used_at
    ? "Newest call " + fmtObserved(model.last_used_at)
    : "No calls in selected period";
  return (
    <details className={"usage-model-card " + model.lane}>
      <summary className="usage-model-summary">
        <div className="usage-model-head">
          <div>
            <span>{model.provider}</span>
            <strong>{model.model_id}</strong>
          </div>
          <span className={"usage-badge " + (hasUsage ? "ok" : "muted")}>
            {sourceUnavailable ? "Source unavailable" : hasUsage ? "Observed" : "Configured"}
          </span>
        </div>
        {!sourceUnavailable && (
          <div className="usage-model-primary">
            <div><span>Period tokens</span><strong>{fmtInt(model.total_tokens ?? 0)}</strong></div>
            <div><span>Calls</span><strong>{fmtInt(model.calls ?? 0)}</strong></div>
          </div>
        )}
        <span className="usage-expand-label">
          <span>Recent use and KPIs</span><b aria-hidden="true">⌄</b>
        </span>
      </summary>
      <div className="usage-model-expanded">
        {model.roles.length > 0 && (
          <div className="usage-model-roles">
            {model.roles.map((role) => <span key={role}>{humanLabel(role)}</span>)}
          </div>
        )}
        {sourceUnavailable ? (
          <div className="usage-model-empty">
            Usage could not be read. Check the data-source status below.
          </div>
        ) : (
          <>
            <div className="usage-model-details">
              <span><b>{fmtInt(model.input_tokens ?? 0)}</b> total input</span>
              <span><b>{fmtInt(model.output_tokens ?? 0)}</b> total output</span>
              <span><b>{fmtDuration(model.duration_ms)}</b> total runtime</span>
              <span><b>{model.lane === "openrouter"
                ? fmtCost(model.cost_usd, model.cost_source)
                : "No provider API charge"}</b> {model.lane === "openrouter"
                  ? "estimated from recorded tokens"
                  : "hardware cost not measured"}</span>
            </div>
            <div className="usage-sub">Usage KPIs</div>
            <UsageKpiGrid kpis={model.kpis} />
            <div className="usage-sub">What it has been used for</div>
            <PurposeBreakdown model={model} />
            <div className="usage-sub">Recent activity</div>
            <RecentUsageList rows={model.recent_activity} />
            {model.calls !== null && model.calls > 0
              && model.outcome_observed_calls < model.calls && (
              <div className="usage-model-caveat">
                Success rate is not shown because this source records completed
                usage, not every failed attempt.
              </div>
            )}
            {(model.failed_calls ?? 0) > 0 && (
              <div className="usage-model-warning">
                {fmtInt(model.failed_calls ?? 0)} failed calls retained
              </div>
            )}
          </>
        )}
        <div className="usage-model-foot">
          <span>{observed}</span>
          <span>{model.aliases.map(humanLabel).join(" · ")}</span>
        </div>
      </div>
    </details>
  );
}
function UsageCard({ s, models, detailLoad }: {
  s: UsageStatus; models: UsageDriverRow[]; detailLoad: AgentUsageDetailLoad;
}) {
  const provider = s.limits.filter((l) => l.scope === "provider");
  const budget = s.limits.filter((l) => l.scope === "internal_budget");
  const u = s.rolled_usage;
  return (
    <details className="usage-card">
      <summary className="usage-agent-summary">
        <div className="usage-card-head">
          <div className="usage-runtime-group">
            <span>Subscription runtime</span>
            <strong className="usage-runtime">
              {RUNTIME_LABELS[s.runtime_id] ?? humanLabel(s.runtime_id)}
            </strong>
          </div>
          <span className={`usage-badge ${AVAIL_CLASS[s.availability] ?? "muted"}`}>
            {humanLabel(s.availability)}
          </span>
          {s.stale && <span className="usage-badge muted"
            title="freshest signal is stale">stale</span>}
        </div>
        <div className="usage-reason">{humanText(s.availability_reason)}</div>
        {provider.map((limit) => <UsageBucket key={limit.bucket_id} l={limit} />)}
        <span className="usage-expand-label">
          <span>Recent use and KPIs</span><b aria-hidden="true">⌄</b>
        </span>
      </summary>
      <div className="usage-agent-expanded">
        {u && (
          <div className="usage-rollup">
            <div><span>Period tokens</span><strong>{fmtInt(u.total_tokens)}</strong></div>
            <div><span>Calls</span><strong>{fmtInt(u.calls)}</strong></div>
            <div><span>Cost</span><strong>{fmtCost(
              u.cost_usd,
              s.runtime_id === "codex_agent" && u.cost_usd === null
                ? "subscription_not_metered" : u.cost_source,
            )}</strong></div>
          </div>
        )}
        {detailLoad.state === "ready" && (
          <>
            <div className="usage-sub">Usage KPIs</div>
            <UsageKpiGrid kpis={detailLoad.detail.kpis} />
          </>
        )}
        {models.length > 0 && (
          <div className="usage-agent-models">
            <div className="usage-sub">Model activity</div>
            {models.map((model) => (
              <div className="usage-agent-model" key={model.key}>
                <strong>{model.key}</strong>
                <span>{fmtInt(model.metric_value)} tokens · {Math.round(model.share * 100)}%</span>
              </div>
            ))}
          </div>
        )}
        <div className="usage-sub">Recent activity</div>
        {detailLoad.state === "loading" && (
          <div className="usage-model-empty">Loading recent usage…</div>
        )}
        {detailLoad.state === "error" && (
          <div className="usage-note bad" role="alert">
            Recent usage unavailable: {detailLoad.error}
          </div>
        )}
        {detailLoad.state === "ready" && (
          <RecentUsageList rows={detailLoad.detail.rows} />
        )}
        {budget.length > 0 && (
          <>
            <div className="usage-sub">Internal budget</div>
            {budget.map((limit) => <UsageBucket key={limit.bucket_id} l={limit} />)}
          </>
        )}
      </div>
    </details>
  );
}
function UsageBucket({ l }: { l: UsageLimit }) {
  const pctText = l.used_percent === null ? "unknown" : `${l.used_percent.toFixed(0)}%`;
  const stateClass = l.state === "exhausted" ? "bad"
    : l.state === "near_limit" ? "warn"
    : l.state === "unknown" ? "muted" : "ok";
  return (
    <div className="usage-bucket">
      <div className="usage-bucket-top">
        <span className="usage-bucket-label">{l.label || humanLabel(l.bucket_id)}</span>
        <span className={`usage-pct ${stateClass}`}>{pctText}</span>
      </div>
      <div className="usage-bar">
        <div className={`usage-bar-fill ${stateClass}`}
          style={{ width: `${l.used_percent === null ? 0 : Math.min(100, l.used_percent)}%` }} />
      </div>
      <div className="usage-bucket-foot">
        <span>resets {fmtReset(l.reset_at)}</span>
        {l.credits_remaining !== null && <span>credits {l.credits_remaining}</span>}
      </div>
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
type ResearchFilters = {
  workAreas: string[];
  useCases: string[];
  projects: string[];
  priorities: string[];
  detailState: "" | "complete" | "pending";
  minRelevance: number;
  minImpact: number;
  minReadiness: number;
  minConfidence: number;
  minProjectFit: number;
};
const EMPTY_RESEARCH_FILTERS: ResearchFilters = {
  workAreas: [], useCases: [], projects: [], priorities: [],
  detailState: "", minRelevance: 0, minImpact: 0, minReadiness: 0,
  minConfidence: 0, minProjectFit: 0,
};
function researchPriorityTone(priority: unknown): string {
  const value = valText(priority);
  return value === "high" ? "bad" : value === "medium" ? "warn"
    : value === "low" ? "good" : "";
}
function domainTitle(card: DomainCard, spec: DomainSpec): string {
  switch (spec.card_component) {
    case "job_application":
      return [card.company, card.role_title].map(valText).filter(Boolean).join(" - ") || cardId(card);
    case "linkedin_post": return valText(card.hook || card.account || cardId(card));
    case "book": return valText(card.title || cardId(card));
    case "paper": return valText(card.title || cardId(card));
    case "repo": return valText(card.title || card.repo_id) || "Repository title unavailable";
    case "dag": return valText(card.dag_id || cardId(card));
    case "machine_upkeep": return valText(card.task || cardId(card));
    case "mission": return valText(card.action || cardId(card));
    default: return valText(card.title || card.task || cardId(card));
  }
}
function domainCardDescription(card: DomainCard, spec: DomainSpec): string {
  return cardDescription(
    card,
    [
      ...spec.drawer_fields.map((field) => field.name),
      ...spec.summary_fields.map((field) => field.name),
    ],
  );
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
function LinkList({ values }: { values: unknown }) {
  const links = valList(values);
  if (!links.length) return <span className="muted">-</span>;
  return (
    <ul className="link-list">
      {links.map((href) => (
        <li key={href}><a href={href} target="_blank" rel="noreferrer">{href}</a></li>
      ))}
    </ul>
  );
}
function FieldValue({ field, value }: { field: FieldSpec; value: unknown }) {
  const kind = field.kind ?? "text";
  if (kind === "badge") return <Badge value={value} />;
  if (kind === "score") return <ScoreChip value={value} />;
  if (kind === "progress") return <ProgressBar value={value} />;
  if (kind === "list") {
    return field.name.endsWith("_links")
      ? <LinkList values={value} />
      : <ChipList values={value} />;
  }
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

function LinkedInPostComposer({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: (card: DomainCard, warningCount: number) => void;
}) {
  const [options, setOptions] = useState<LinkedInComposerOptions | null>(null);
  const [account, setAccount] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");
  const [mobile, setMobile] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchLinkedInComposer()
      .then((result) => {
        if (!live) return;
        setOptions(result);
        setAccount((current) => current || result.accounts[0]?.id || "");
      })
      .catch((e) => { if (live) setError((e as Error).message); });
    return () => { live = false; };
  }, []);

  const maxCharacters = options?.max_characters ?? 3000;
  const tagList = tags.split(/[\s,]+/).map((tag) => tag.trim()).filter(Boolean);
  const accountLabel = options?.accounts.find((row) => row.id === account)?.label ?? account;
  const preview: DomainCard = {
    account: accountLabel,
    author_name: accountLabel,
    body: body || "Your post preview appears here as you type.",
    hook: body.split(/\n/, 1)[0],
    tags: tagList,
  };
  const blockers = options?.write_blockers ?? [];
  const canSave = !!options?.write_ready && !!account && !!body.trim()
    && body.length <= maxCharacters && !busy;

  async function save() {
    if (!canSave) return;
    setBusy(true); setError(null);
    try {
      const result = await createLinkedInPostDraft({
        account,
        body,
        tags: tagList,
        source_ref: "cockpit/manual",
        scheduled_for: scheduledFor
          ? new Date(scheduledFor).toISOString()
          : null,
      });
      onCreated(result.card, result.warnings.length);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="drawer-bg packet-bg" role="dialog" aria-modal="true"
      aria-label="Create LinkedIn post draft">
      <div className="packet-modal post-composer">
        <div className="drawer-head">
          <div>
            <h2>New post</h2>
            <div className="muted small">Write the exact copy, inspect the live LinkedIn preview, then save a Draft card.</div>
          </div>
          <button className="x" onClick={onClose} aria-label="Close">x</button>
        </div>
        {error && <div className="error">ERR {error}</div>}
        {blockers.length > 0 && (
          <div className="error">Draft creation is blocked: {blockers.join("; ")}</div>
        )}
        <div className="post-composer-grid">
          <div className="post-compose-fields">
            <label>
              <span>Account</span>
              <select className="select" value={account}
                onChange={(e) => setAccount(e.target.value)}>
                {(options?.accounts ?? []).map((row) => (
                  <option key={row.id} value={row.id}>{row.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Post</span>
              <textarea value={body} rows={16}
                placeholder={"Lead with the point.\n\nAdd the evidence and useful context.\n\nEnd with a genuine question."}
                onChange={(e) => setBody(e.target.value)} />
              <span className={body.length > maxCharacters ? "error small" : "muted small"}>
                {body.length}/{maxCharacters} characters
              </span>
            </label>
            <label>
              <span>Hashtags</span>
              <input value={tags} placeholder="#AI, #SportsAnalytics"
                onChange={(e) => setTags(e.target.value)} />
            </label>
            <label>
              <span>Schedule (optional)</span>
              <input type="datetime-local" value={scheduledFor}
                onChange={(e) => setScheduledFor(e.target.value)} />
            </label>
            <button className="actbtn" disabled={!canSave} onClick={() => void save()}>
              {busy ? "saving..." : "Save draft"}
            </button>
          </div>
          <div className="post-compose-preview">
            <div className="drawer-toggle">
              <button className={`tab ${!mobile ? "tab-on" : ""}`}
                onClick={() => setMobile(false)}>desktop</button>
              <button className={`tab ${mobile ? "tab-on" : ""}`}
                onClick={() => setMobile(true)}>mobile</button>
            </div>
            <LinkedInPreview card={preview} mobile={mobile} />
          </div>
        </div>
      </div>
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
  // The background prep worker has not produced a packet yet: the card sits in
  // a selected lane with no application_id/materials_path. Shown so a queued
  // move reads as "working" rather than stuck.
  const status = valText(card.status);
  const isPreparing =
    (status === "Selected by Geoff" || status === "In Progress")
    && !valText(card.application_id) && !valText(card.materials_path);
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
        {isPreparing && <span className="badge job-prep-badge">preparing packet…</span>}
      </div>
      {handoffReason && <div className="job-card-note">{handoffReason}</div>}
      {nextAction && <div className="job-card-next">{nextAction}</div>}
    </div>
  );
}
function BookCard({ card }: { card: DomainCard }) {
  const parsed = parseBookNotes(card);
  const legacyNotes = valText(card.notes);
  const latest = parsed.notes[parsed.notes.length - 1];
  const notePreview = latest?.text || legacyNotes;
  const progress = bookProgress(card);
  const location = [
    valText(card.current_chapter),
    card.current_page !== null && card.current_page !== undefined
      ? "page " + valText(card.current_page)
        + (card.total_pages ? " of " + valText(card.total_pages) : "")
      : "",
  ].filter(Boolean);
  const details = [
    valText(card.module),
    card.hours ? `${valText(card.hours)}h` : "",
  ].filter(Boolean);
  return (
    <div className="domain-card-body book-card-body">
      <span className="book-spine" aria-hidden="true" />
      <div className="book-card-heading">
        <div>
          <div className="domain-title book-title">
            {valText(card.title) || "Title missing - migration repair required"}
          </div>
          <div className="domain-subtitle book-byline">
            {valText(card.author) ? `by ${valText(card.author)}` : "Author not listed"}
          </div>
        </div>
        <StatusPill value={card.status} />
      </div>
      <div className="domain-badges book-badges">
        <Badge value={card.tier} />
        <Badge value={card.genre} />
        {valText(card.section) && <Badge value={`Section ${valText(card.section)}`} />}
      </div>
      {details.length > 0 && <div className="book-details-line">{details.join(" · ")}</div>}
      {(progress !== null || location.length > 0) && (
        <div className="book-reading-progress">
          <div>
            <span>{location.join(" · ") || "Reading progress"}</span>
            <b>{progress !== null ? progress + "%" : "position saved"}</b>
          </div>
          {progress !== null && (
            <div className="book-progress-track" role="progressbar"
              aria-label="Reading progress" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={progress}>
              <span style={{ width: progress + "%" }} />
            </div>
          )}
        </div>
      )}
      {parsed.error && <div className="book-data-error">{parsed.error}</div>}
      {notePreview && (
        <div className="book-note-preview">
          <div className="book-note-preview-head">
            <span>{parsed.notes.length ? `${parsed.notes.length} ordered note${parsed.notes.length === 1 ? "" : "s"}` : "Notes"}</span>
            {latest && <b>#{latest.sequence}</b>}
          </div>
          <p>{notePreview}</p>
        </div>
      )}
    </div>
  );
}

function parseBookNotes(card: DomainCard): { notes: BookNote[]; error: string | null } {
  if (!Object.prototype.hasOwnProperty.call(card, "book_notes")) {
    return { notes: [], error: null };
  }
  const raw = card.book_notes;
  if (!Array.isArray(raw)) {
    return { notes: [], error: "Ordered notes data is invalid; open the card for details." };
  }
  const notes: BookNote[] = [];
  const seenIds = new Set<string>();
  for (let index = 0; index < raw.length; index += 1) {
    const row = raw[index];
    if (!row || typeof row !== "object") {
      return { notes: [], error: `Ordered note ${index + 1} is not an object.` };
    }
    const note = row as Record<string, unknown>;
    if (
      typeof note.note_id !== "string"
      || !/^book-note-[a-f0-9]{16}$/.test(note.note_id)
      || note.sequence !== index + 1
      || typeof note.author !== "string"
      || !note.author.trim()
      || typeof note.text !== "string"
      || !note.text.trim()
      || typeof note.created_at !== "string"
      || !/(?:Z|[+-]\d{2}:\d{2})$/.test(note.created_at)
      || !Number.isFinite(Date.parse(note.created_at))
      || (note.chapter !== undefined && (
        typeof note.chapter !== "string" || !note.chapter.trim()
      ))
      || (note.page !== undefined && (
        !Number.isInteger(note.page) || Number(note.page) < 0
      ))
      || (note.total_pages !== undefined && (
        !Number.isInteger(note.total_pages) || Number(note.total_pages) < 1
      ))
      || (note.progress_percent !== undefined && (
        !Number.isInteger(note.progress_percent)
        || Number(note.progress_percent) < 0
        || Number(note.progress_percent) > 100
      ))
      || (
        note.page !== undefined
        && note.total_pages !== undefined
        && Number(note.page) > Number(note.total_pages)
      )
    ) {
      return { notes: [], error: `Ordered note ${index + 1} has an invalid contract.` };
    }
    if (seenIds.has(note.note_id)) {
      return { notes: [], error: `Ordered note ${index + 1} repeats note ID ${note.note_id}.` };
    }
    seenIds.add(note.note_id);
    notes.push(note as unknown as BookNote);
  }
  return { notes, error: null };
}

function BookNotesTimeline({ card }: { card: DomainCard }) {
  const parsed = parseBookNotes(card);
  const legacy = valText(card.notes);
  const [query, setQuery] = useState("");
  const tokens = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const noteMatches = (note: BookNote) => {
    const haystack = [
      note.author, note.text, note.chapter,
      note.page === undefined ? "" : "page " + note.page,
      note.progress_percent === undefined ? "" : note.progress_percent + "%",
    ].filter(Boolean).join(" ").toLocaleLowerCase();
    return tokens.every((token) => haystack.includes(token));
  };
  const shownNotes = parsed.notes.filter(noteMatches);
  const legacyMatches = !tokens.length
    || tokens.every((token) => legacy.toLocaleLowerCase().includes(token));
  return (
    <section className="book-notes-section" aria-label="Book notes">
      <div className="book-section-heading">
        <div>
          <span className="eyebrow">Reading record</span>
          <h3>Notes</h3>
        </div>
        <span className="book-note-count">
          {tokens.length ? shownNotes.length + " of " : ""}{parsed.notes.length} ordered
        </span>
      </div>
      {(legacy || parsed.notes.length > 0) && (
        <label className="book-note-search">
          <span>Search this book's notes</span>
          <input value={query} placeholder="Keyword, chapter, page, author..."
            onChange={(event) => setQuery(event.target.value)} />
        </label>
      )}
      {legacy && legacyMatches && (
        <article className="book-legacy-note">
          <div className="book-note-meta"><b>Existing notes</b><span>Imported / editable overview</span></div>
          <MarkdownText value={legacy} />
        </article>
      )}
      {parsed.error && <div className="error">ERR {parsed.error}</div>}
      {shownNotes.map((note) => {
        const context = [
          note.chapter,
          note.page === undefined
            ? ""
            : "page " + note.page + (
              note.total_pages === undefined ? "" : " of " + note.total_pages),
          note.progress_percent === undefined ? "" : note.progress_percent + "%",
        ].filter(Boolean);
        return (
        <article className="book-timeline-note" key={note.note_id}>
          <div className="book-note-sequence">{note.sequence}</div>
          <div>
            <div className="book-note-meta">
              <b>{note.author}</b>
              <span>{new Date(note.created_at).toLocaleString()}</span>
            </div>
            {context.length > 0 && (
              <div className="book-note-context">{context.join(" · ")}</div>
            )}
            <p>{note.text}</p>
          </div>
        </article>
        );
      })}
      {tokens.length > 0 && shownNotes.length === 0 && !legacyMatches && (
        <div className="book-notes-empty">No notes match these keywords.</div>
      )}
      {!legacy && !parsed.notes.length && !parsed.error && (
        <div className="book-notes-empty">No notes yet. Add the first observation below or from the Books toolbar.</div>
      )}
    </section>
  );
}

function BookLibraryFilters({
  cards, query, status, statuses, filters, resultCount,
  onQuery, onStatus, onFilters, onClear,
}: {
  cards: DomainCard[];
  query: string;
  status: string;
  statuses: string[];
  filters: BookLibraryFilterState;
  resultCount: number;
  onQuery: (value: string) => void;
  onStatus: (value: string) => void;
  onFilters: (value: BookLibraryFilterState) => void;
  onClear: () => void;
}) {
  const recordedHours = cards.flatMap((card) => {
    const value = bookHours(card);
    return value === null ? [] : [value];
  });
  const recordedProgress = cards.flatMap((card) => {
    const value = bookProgress(card);
    return value === null ? [] : [value];
  });
  const hoursMax = Math.max(1, Math.ceil(Math.max(0, ...recordedHours)));
  const minHours = filters.minHours ?? 0;
  const maxHours = filters.maxHours ?? hoursMax;
  const minProgress = filters.minProgress ?? 0;
  const maxProgress = filters.maxProgress ?? 100;
  const lengthActive = filters.minHours !== null || filters.maxHours !== null;
  const progressActive = (
    filters.minProgress !== null || filters.maxProgress !== null);
  const activeFacetCount = Object.values(filters.facets).filter(Boolean).length;
  const hasFilters = !!(
    query || status || activeFacetCount || filters.noteState
    || filters.readingState || lengthActive || progressActive
    || filters.sortBy !== "title" || filters.sortDirection !== "asc"
  );
  const update = (patch: Partial<BookLibraryFilterState>) =>
    onFilters({ ...filters, ...patch });
  const updateFacet = (field: string, value: string) =>
    onFilters({
      ...filters,
      facets: { ...filters.facets, [field]: value },
    });

  return (
    <details className="book-filter-disclosure">
      <summary className="book-filter-summary">
        <span>
          <span className="eyebrow">Library filters</span>
          <span className="book-filter-summary-title">Filter and sort books</span>
        </span>
        <span className="book-filter-summary-meta">
          <span>{resultCount} of {cards.length}</span>
          <span>{hasFilters ? "Filtered" : "Optional"}</span>
          <span className="book-filter-chevron" aria-hidden="true">⌄</span>
        </span>
      </summary>
      <section className="book-filter-shelf" aria-label="Filter and sort books">
      <div className="book-filter-heading">
        <div>
          <span className="eyebrow">Library filters</span>
          <h3>Filter every useful grouping</h3>
          <p>Priority, author, genre, collection, section, format, notes,
            length, and progress all combine.</p>
        </div>
        <div className="book-filter-result">
          <b>{resultCount}</b><span>of {cards.length} shown</span>
        </div>
      </div>
      <div className="book-filter-primary">
        <label className="book-filter-search">
          <span>Keyword search</span>
          <input className="search" value={query}
            placeholder="Search titles, authors, notes, chapters..."
            onChange={(event) => onQuery(event.target.value)} />
        </label>
        <label><span>Status</span><select value={status}
          onChange={(event) => onStatus(event.target.value)}>
          <option value="">any status</option>
          {statuses.map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <label><span>Sort field</span><select value={filters.sortBy}
          onChange={(event) => update({
            sortBy: event.target.value as BookSortField,
          })}>
          {BOOK_SORT_FIELDS.map((field) => (
            <option value={field.key} key={field.key}>{field.label}</option>
          ))}
        </select></label>
        <label><span>Direction</span><select value={filters.sortDirection}
          onChange={(event) => update({
            sortDirection: event.target.value as BookSortDirection,
          })}>
          <option value="asc">A-Z / low-high</option>
          <option value="desc">Z-A / high-low</option>
        </select></label>
      </div>
      <div className="book-filter-facets">
        {BOOK_GROUP_FIELDS.map((field) => {
          const options = bookFacetOptions(cards, field.key);
          return (
            <label key={field.key}><span>{field.label}</span>
              <select value={filters.facets[field.key] ?? ""}
                onChange={(event) => updateFacet(field.key, event.target.value)}>
                <option value="">{`any ${field.label.toLocaleLowerCase()}`}</option>
                {options.map((option) => (
                  <option value={option.value} key={option.value}>
                    {option.label} ({option.count})
                  </option>
                ))}
              </select>
            </label>
          );
        })}
        <label><span>Notes</span><select value={filters.noteState}
          onChange={(event) => update({ noteState: event.target.value as BookNoteFilter })}>
          <option value="">any notes</option>
          <option value="with">has notes</option>
          <option value="without">no notes yet</option>
        </select></label>
        <label><span>Reading position</span><select value={filters.readingState}
          onChange={(event) => update({
            readingState: event.target.value as BookReadingFilter,
          })}>
          <option value="">any position</option>
          <option value="started">position recorded</option>
          <option value="not-started">not started / unset</option>
        </select></label>
      </div>
      <div className="book-range-filters">
        <div className="book-length-filter">
          <div className="book-length-heading">
            <div><b>Estimated length</b>
              <span>{lengthActive
                ? minHours + "-" + maxHours + " hours"
                : "Any recorded length (up to " + hoursMax + "h)"}</span>
            </div>
            <span>{recordedHours.length}/{cards.length} books have estimates</span>
          </div>
          <div className="book-range-pair">
            <label><span>Minimum {minHours}h</span>
              <input type="range" min={0} max={hoursMax} step={1}
                value={Math.min(minHours, maxHours)}
                aria-label="Minimum estimated reading hours"
                onChange={(event) => {
                  const value = Math.min(Number(event.target.value), maxHours);
                  update({ minHours: value === 0 ? null : value });
                }} />
            </label>
            <label><span>Maximum {maxHours}h</span>
              <input type="range" min={0} max={hoursMax} step={1}
                value={Math.max(maxHours, minHours)}
                aria-label="Maximum estimated reading hours"
                onChange={(event) => {
                  const value = Math.max(Number(event.target.value), minHours);
                  update({ maxHours: value === hoursMax ? null : value });
                }} />
            </label>
          </div>
          {lengthActive && (
            <span className="muted small">
              Books without a recorded estimate are hidden for this range.
            </span>
          )}
        </div>
        <div className="book-length-filter">
          <div className="book-length-heading">
            <div><b>Reading progress</b>
              <span>{progressActive
                ? minProgress + "-" + maxProgress + "%"
                : "Any recorded progress"}</span>
            </div>
            <span>{recordedProgress.length}/{cards.length} books have progress</span>
          </div>
          <div className="book-range-pair">
            <label><span>Minimum {minProgress}%</span>
              <input type="range" min={0} max={100} step={1}
                value={Math.min(minProgress, maxProgress)}
                aria-label="Minimum reading progress"
                onChange={(event) => {
                  const value = Math.min(Number(event.target.value), maxProgress);
                  update({ minProgress: value === 0 ? null : value });
                }} />
            </label>
            <label><span>Maximum {maxProgress}%</span>
              <input type="range" min={0} max={100} step={1}
                value={Math.max(maxProgress, minProgress)}
                aria-label="Maximum reading progress"
                onChange={(event) => {
                  const value = Math.max(Number(event.target.value), minProgress);
                  update({ maxProgress: value === 100 ? null : value });
                }} />
            </label>
          </div>
          {progressActive && (
            <span className="muted small">
              Books without recorded or exactly derived progress are hidden.
            </span>
          )}
        </div>
      </div>
      <div className="book-filter-footer">
        <span className="muted small">
          “Not set” finds incomplete metadata without filling anything in.
          {activeFacetCount > 0 ? ` ${activeFacetCount} grouping filter(s) active.` : ""}
        </span>
        {hasFilters && <button className="clear" onClick={onClear}>Clear library filters</button>}
      </div>
      </section>
    </details>
  );
}

type SelfImprovementFilters = {
  repoId: string;
  pillar: string;
  risk: string;
  source: string;
  minScore: number;
};
const EMPTY_SELF_IMPROVEMENT_FILTERS: SelfImprovementFilters = {
  repoId: "", pillar: "", risk: "", source: "", minScore: 0,
};
function improvementRepoIds(card: DomainCard): string[] {
  return Array.isArray(card.repo_ids)
    ? card.repo_ids.map(valText).filter(Boolean)
    : valText(card.repo_ids).split(",").map((value) => value.trim()).filter(Boolean);
}
function selfImprovementCardMatches(
  card: DomainCard, filters: SelfImprovementFilters,
): boolean {
  return (
    (!filters.repoId || improvementRepoIds(card).includes(filters.repoId))
    && (!filters.pillar || valText(card.pillar) === filters.pillar)
    && (!filters.risk || valText(card.risk) === filters.risk)
    && (!filters.source || valText(card.source) === filters.source)
    && ((valNumber(card.score) ?? 0) >= filters.minScore)
  );
}

function SelfImprovementToolbar({
  repositories, allCards, shownCards, query, status, statuses, filters,
  onQuery, onStatus, onFilters, onClear,
}: {
  repositories: RegisteredRepository[];
  allCards: DomainCard[];
  shownCards: DomainCard[];
  query: string;
  status: string;
  statuses: string[];
  filters: SelfImprovementFilters;
  onQuery: (value: string) => void;
  onStatus: (value: string) => void;
  onFilters: (value: SelfImprovementFilters) => void;
  onClear: () => void;
}) {
  const selectedRepo = repositories.find((repo) => repo.repo_id === filters.repoId);
  const distinct = (field: string) => Array.from(new Set(
    allCards.map((card) => valText(card[field])).filter(Boolean))).sort();
  const pillars = distinct("pillar");
  const risks = distinct("risk");
  const sources = distinct("source");
  const scores = shownCards.map((card) => valNumber(card.score))
    .filter((value): value is number => value !== null);
  const averageScore = scores.length
    ? (scores.reduce((total, value) => total + value, 0) / scores.length).toFixed(1)
    : "—";
  const blocked = shownCards.filter((card) =>
    valText(card.status).toLocaleLowerCase().includes("blocked")).length;
  const active = shownCards.filter((card) =>
    ["ready", "in progress", "awaiting approval"].includes(
      valText(card.status).toLocaleLowerCase())).length;
  const backlog = shownCards.filter((card) =>
    valText(card.status).toLocaleLowerCase() === "backlog").length;
  const filterCount = [
    query, status, filters.pillar, filters.risk, filters.source,
    filters.minScore > 0 ? String(filters.minScore) : "",
  ].filter(Boolean).length;
  const repoCount = (repoId: string) => allCards.filter((card) =>
    improvementRepoIds(card).includes(repoId)).length;

  return (
    <section className="improvement-overview" aria-label="Self Improvement repository view">
      <div className="improvement-repo-head">
        <div>
          <span className="eyebrow">Registered repository coverage</span>
          <h3>{selectedRepo?.repo_id ?? "All repositories"}</h3>
          <p>{selectedRepo?.scan_reason
            ?? "Review cross-system opportunities and every registered repository together."}</p>
          {selectedRepo?.research_capabilities.length ? (
            <div className="chip-list">
              {selectedRepo.research_capabilities.map((capability) =>
                <span className="chip" key={capability}>{capability}</span>)}
            </div>
          ) : null}
        </div>
        {selectedRepo?.remote_url && (
          <a href={selectedRepo.remote_url} target="_blank" rel="noreferrer">
            repository ↗
          </a>
        )}
      </div>
      <HorizontalScroller className="improvement-repo-tabs"
        ariaLabel="Registered repository tabs">
        <button className={`tab ${!filters.repoId ? "tab-on" : ""}`}
          aria-pressed={!filters.repoId}
          onClick={() => onFilters({ ...filters, repoId: "" })}>
          All <span className="tab-count">{allCards.length}</span>
        </button>
        {repositories.map((repo) => (
          <button key={repo.repo_id}
            className={`tab ${filters.repoId === repo.repo_id ? "tab-on" : ""}`}
            aria-pressed={filters.repoId === repo.repo_id}
            title={repo.scan_reason}
            onClick={() => onFilters({ ...filters, repoId: repo.repo_id })}>
            {repo.repo_id}<span className="tab-count">{repoCount(repo.repo_id)}</span>
          </button>
        ))}
      </HorizontalScroller>
      <div className="improvement-kpis" aria-label="Self Improvement KPIs">
        <div><span>Shown</span><b>{shownCards.length}</b></div>
        <div><span>Backlog</span><b>{backlog}</b></div>
        <div><span>Active / review</span><b>{active}</b></div>
        <div><span>Blocked</span><b>{blocked}</b></div>
        <div><span>Average score</span><b>{averageScore}</b></div>
      </div>
      <details className="improvement-filter-disclosure">
        <summary className="improvement-filter-summary">
          <span><b>Filters</b><small>Search and narrow improvement evidence</small></span>
          <span className="status-pill">{filterCount ? `${filterCount} active` : "all evidence"}</span>
        </summary>
        <div className="improvement-filter-grid">
          <label>Search
            <input value={query} placeholder="title, evidence, rationale…"
              onChange={(event) => onQuery(event.target.value)} />
          </label>
          <label>Status
            <select value={status} onChange={(event) => onStatus(event.target.value)}>
              <option value="">any status</option>
              {statuses.map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>Pillar
            <select value={filters.pillar}
              onChange={(event) => onFilters({ ...filters, pillar: event.target.value })}>
              <option value="">any pillar</option>
              {pillars.map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>Risk
            <select value={filters.risk}
              onChange={(event) => onFilters({ ...filters, risk: event.target.value })}>
              <option value="">any risk</option>
              {risks.map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>Source
            <select value={filters.source}
              onChange={(event) => onFilters({ ...filters, source: event.target.value })}>
              <option value="">any source</option>
              {sources.map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>Minimum score
            <input type="number" min="0" step="0.1" value={filters.minScore || ""}
              onChange={(event) => onFilters({
                ...filters, minScore: Math.max(0, Number(event.target.value) || 0),
              })} />
          </label>
        </div>
        <div className="preset-actions">
          <button className="clear" disabled={!filterCount} onClick={onClear}>
            clear filters
          </button>
        </div>
      </details>
    </section>
  );
}

const EMPTY_BOOK_DRAFT = {
  title: "", author: "", description: "", tier: "", type: "", genre: "",
  module: "", section: "", hours: "", isbn: "", notes: "",
  current_chapter: "", current_page: "", total_pages: "", progress_percent: "",
};

function optionalBookInteger(value: string): number | null {
  return value.trim() ? Number(value) : null;
}

function BookWorkbench({ cards, columns, writable, onSaved }: {
  cards: DomainCard[];
  columns: string[];
  writable: boolean;
  onSaved: (message: string, card: DomainCard) => void;
}) {
  const [mode, setMode] = useState<"book" | "note">("book");
  const [draft, setDraft] = useState(EMPTY_BOOK_DRAFT);
  const addStatuses = columns.filter((column) => column !== "Archived");
  const [status, setStatus] = useState(
    addStatuses.includes("To read") ? "To read" : addStatuses[0] ?? "");
  const activeBooks = [...cards]
    .filter((card) => valText(card.status) !== "Archived")
    .sort((a, b) => valText(a.title).localeCompare(valText(b.title)));
  const [noteCardId, setNoteCardId] = useState("");
  const [noteBookQuery, setNoteBookQuery] = useState("");
  const [noteAuthor, setNoteAuthor] = useState("");
  const [noteText, setNoteText] = useState("");
  const [noteChapter, setNoteChapter] = useState("");
  const [notePage, setNotePage] = useState("");
  const [noteTotalPages, setNoteTotalPages] = useState("");
  const [noteProgress, setNoteProgress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!addStatuses.includes(status)) {
      setStatus(addStatuses.includes("To read") ? "To read" : addStatuses[0] ?? "");
    }
  }, [addStatuses.join("|"), status]);

  const noteBookTokens = noteBookQuery.toLocaleLowerCase()
    .split(/\s+/).filter(Boolean);
  const selectableBooks = activeBooks.filter((card) => {
    if (cardId(card) === noteCardId) return true;
    const haystack = [
      valText(card.title), valText(card.author), valText(card.genre),
      valText(card.module),
    ].join(" ").toLocaleLowerCase();
    return noteBookTokens.every((token) => haystack.includes(token));
  });

  function selectNoteBook(cardIdValue: string) {
    setNoteCardId(cardIdValue);
    const selected = activeBooks.find((card) => cardId(card) === cardIdValue);
    if (!selected) return;
    setNoteChapter(valText(selected.current_chapter));
    setNotePage(valText(selected.current_page));
    setNoteTotalPages(valText(selected.total_pages));
    setNoteProgress(valText(selected.progress_percent));
  }

  async function saveBook() {
    if (!draft.title.trim() || !status) return;
    setBusy(true); setError(null);
    try {
      const {
        current_page, total_pages, progress_percent, ...textFields
      } = draft;
      const result = await createBookCard({
        ...textFields,
        current_page: optionalBookInteger(current_page),
        total_pages: optionalBookInteger(total_pages),
        progress_percent: optionalBookInteger(progress_percent),
        status,
      });
      setDraft(EMPTY_BOOK_DRAFT);
      onSaved(
        `${valText(result.card.title)} added to ${valText(result.card.status)}`,
        result.card,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    if (!noteCardId || !noteAuthor.trim() || !noteText.trim()) return;
    setBusy(true); setError(null);
    try {
      const result = await addBookNote(noteCardId, {
        author: noteAuthor,
        text: noteText,
        chapter: noteChapter.trim() || null,
        page: optionalBookInteger(notePage),
        total_pages: optionalBookInteger(noteTotalPages),
        progress_percent: optionalBookInteger(noteProgress),
      });
      setNoteText("");
      onSaved(
        `Note #${result.note?.sequence ?? ""} added to ${valText(result.card.title)}`,
        result.card,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="book-workbench">
      <summary className="book-workbench-summary">
        <span>
          <span className="eyebrow">Library desk</span>
          <span className="book-workbench-summary-title">Add a book or reading note</span>
        </span>
        <span className="book-workbench-summary-meta">
          Optional <span className="book-workbench-chevron" aria-hidden="true">⌄</span>
        </span>
      </summary>
      <div className="book-workbench-content">
        <p className="book-workbench-help">
          Pick an entry type below. Book details stay editable, and notes remain in the order added.
        </p>
        <div className="book-workbench-tabs" role="tablist" aria-label="Books quick entry mode">
        <button className={`tab ${mode === "book" ? "tab-on" : ""}`}
          role="tab" aria-selected={mode === "book"} onClick={() => setMode("book")}>
          + Add book
        </button>
        <button className={`tab ${mode === "note" ? "tab-on" : ""}`}
          role="tab" aria-selected={mode === "note"} onClick={() => setMode("note")}>
          + Add note
        </button>
        </div>
        {!writable && <div className="muted small">Book changes need console write mode.</div>}
        {error && <div className="error">ERR {error}</div>}
        {mode === "book" ? (
          <div className="book-entry-grid">
          <label className="book-field-wide">Book title <input value={draft.title}
            placeholder="The actual title" disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
          <label>Author <input value={draft.author} placeholder="Author name"
            disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, author: e.target.value })} /></label>
          <label>Status <select value={status} disabled={!writable || busy}
            onChange={(e) => setStatus(e.target.value)}>
            {addStatuses.map((column) => <option key={column}>{column}</option>)}
          </select></label>
          <label>Priority <input value={draft.tier}
            placeholder="Essential, companion, optional..."
            disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, tier: e.target.value })} /></label>
          <label>Genre <input value={draft.genre} list="book-genres-top"
            placeholder="History, science, fiction..."
            disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, genre: e.target.value })} />
            <datalist id="book-genres-top">
              <option value="Biography" /><option value="Business" />
              <option value="Fiction" /><option value="History" />
              <option value="Philosophy" /><option value="Science" />
              <option value="Technology" />
            </datalist>
          </label>
          <label>Format / source label <input value={draft.type}
            placeholder="Hardcover, audiobook..."
            disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, type: e.target.value })} /></label>
          <label>Module / collection <input value={draft.module}
            disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, module: e.target.value })} /></label>
          <label>Section <input value={draft.section} disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, section: e.target.value })} /></label>
          <label>Estimated hours <input value={draft.hours} inputMode="decimal"
            placeholder="8.5" disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, hours: e.target.value })} /></label>
          <label>ISBN <input value={draft.isbn} disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, isbn: e.target.value })} /></label>
          <label>Current chapter <input value={draft.current_chapter}
            placeholder="Optional starting point" disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, current_chapter: e.target.value })} /></label>
          <label>Current page <input type="number" min={0}
            value={draft.current_page} disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, current_page: e.target.value })} /></label>
          <label>Total pages <input type="number" min={1}
            value={draft.total_pages} disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, total_pages: e.target.value })} /></label>
          <label className="book-progress-field">
            <span>Progress {draft.progress_percent
              ? draft.progress_percent + "%"
              : "not set"}</span>
            <input type="range" min={0} max={100} step={1}
              value={draft.progress_percent || "0"} disabled={!writable || busy}
              onChange={(e) => setDraft({
                ...draft, progress_percent: e.target.value,
              })} />
          </label>
          <label className="book-field-wide">Details <textarea value={draft.description}
            rows={3} placeholder="Edition, why it matters, or a short description"
            disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
          <label className="book-field-wide">Starting notes <textarea value={draft.notes}
            rows={3} placeholder="Optional overview; ordered observations can be added separately"
            disabled={!writable || busy}
            onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
          <button className="actbtn book-primary-action" disabled={
            !writable || busy || !draft.title.trim() || !status
          } onClick={() => void saveBook()}>
            {busy ? "Adding…" : "Add to library"}
          </button>
          </div>
        ) : (
          <div className="book-note-entry">
          <label className="book-field-wide">Find a book
            <input value={noteBookQuery}
              placeholder="Filter by title, author, genre, or collection"
              disabled={!writable || busy}
              onChange={(e) => setNoteBookQuery(e.target.value)} />
          </label>
          <label>Book <select value={noteCardId} disabled={!writable || busy}
            onChange={(e) => selectNoteBook(e.target.value)}>
            <option value="">Choose a book…</option>
            {selectableBooks.map((card) => (
              <option key={cardId(card)} value={cardId(card)}>
                {valText(card.title) || `Title missing — ${cardId(card)}`}
                {card.author ? ` — ${valText(card.author)}` : ""}
              </option>
            ))}
          </select></label>
          <label>Added by <input value={noteAuthor} list="book-note-authors-top"
            placeholder="Required" disabled={!writable || busy}
            onChange={(e) => setNoteAuthor(e.target.value)} />
            <datalist id="book-note-authors-top"><option value="Geoff" /><option value="Assistant" /></datalist>
          </label>
          <label>Chapter <input value={noteChapter}
            placeholder="Optional chapter or section"
            disabled={!writable || busy}
            onChange={(e) => setNoteChapter(e.target.value)} /></label>
          <label>Page <input type="number" min={0} value={notePage}
            disabled={!writable || busy}
            onChange={(e) => setNotePage(e.target.value)} /></label>
          <label>Total pages <input type="number" min={1} value={noteTotalPages}
            disabled={!writable || busy}
            onChange={(e) => setNoteTotalPages(e.target.value)} /></label>
          <label className="book-progress-field">
            <span>Progress {noteProgress ? noteProgress + "%" : "not set"}</span>
            <input type="range" min={0} max={100} step={1}
              value={noteProgress || "0"} disabled={!writable || busy}
              onChange={(e) => setNoteProgress(e.target.value)} />
          </label>
          <label className="book-field-wide">Note <textarea value={noteText} rows={4}
            placeholder="What stood out, what to revisit, or a question to explore"
            disabled={!writable || busy}
            onChange={(e) => setNoteText(e.target.value)} /></label>
          <button className="actbtn book-primary-action" disabled={
            !writable || busy || !noteCardId || !noteAuthor.trim() || !noteText.trim()
          } onClick={() => void saveNote()}>
            {busy ? "Adding…" : "Add ordered note"}
          </button>
          </div>
        )}
      </div>
    </details>
  );
}

function BookDrawerControls({ card, writable, onCardChanged, onRestore }: {
  card: DomainCard;
  writable: boolean;
  onCardChanged: (card: DomainCard, message: string) => void;
  onRestore?: () => void;
}) {
  const makeDraft = (source: DomainCard) => ({
    title: valText(source.title),
    author: valText(source.author),
    description: valText(source.description),
    tier: valText(source.tier),
    type: valText(source.type),
    genre: valText(source.genre),
    module: valText(source.module),
    section: valText(source.section),
    hours: valText(source.hours),
    isbn: valText(source.isbn),
    notes: valText(source.notes),
  });
  const makePosition = (source: DomainCard) => ({
    current_chapter: valText(source.current_chapter),
    current_page: valText(source.current_page),
    total_pages: valText(source.total_pages),
    progress_percent: valText(source.progress_percent),
  });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => makeDraft(card));
  const [position, setPosition] = useState(() => makePosition(card));
  const [author, setAuthor] = useState("");
  const [text, setText] = useState("");
  const [noteChapter, setNoteChapter] = useState(valText(card.current_chapter));
  const [notePage, setNotePage] = useState(valText(card.current_page));
  const [noteTotalPages, setNoteTotalPages] = useState(valText(card.total_pages));
  const [noteProgress, setNoteProgress] = useState(valText(card.progress_percent));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = cardId(card);
  const archived = valText(card.status) === "Archived";

  useEffect(() => {
    if (!editing) setDraft(makeDraft(card));
  }, [id, card.updated_at, editing]);
  useEffect(() => {
    const next = makePosition(card);
    setPosition(next);
    setNoteChapter(next.current_chapter);
    setNotePage(next.current_page);
    setNoteTotalPages(next.total_pages);
    setNoteProgress(next.progress_percent);
  }, [id, card.updated_at]);

  async function save() {
    if (!draft.title.trim()) return;
    setBusy(true); setError(null);
    try {
      const result = await updateBookCard(id, draft);
      setEditing(false);
      onCardChanged(result.card, "Book details updated.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function appendNote() {
    if (!author.trim() || !text.trim()) return;
    setBusy(true); setError(null);
    try {
      const result = await addBookNote(id, {
        author,
        text,
        chapter: noteChapter.trim() || null,
        page: optionalBookInteger(notePage),
        total_pages: optionalBookInteger(noteTotalPages),
        progress_percent: optionalBookInteger(noteProgress),
      });
      setText("");
      onCardChanged(
        result.card,
        `Ordered note #${result.note?.sequence ?? ""} added.`,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function savePosition() {
    const currentPage = optionalBookInteger(position.current_page);
    const totalPages = optionalBookInteger(position.total_pages);
    if (
      currentPage !== null && totalPages !== null && currentPage > totalPages
    ) {
      setError("Current page cannot exceed total pages.");
      return;
    }
    setBusy(true); setError(null);
    try {
      const result = await updateBookCard(id, {
        current_chapter: position.current_chapter.trim() || null,
        current_page: currentPage,
        total_pages: totalPages,
        progress_percent: optionalBookInteger(position.progress_percent),
      });
      onCardChanged(result.card, "Reading position updated.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function clearPosition() {
    setBusy(true); setError(null);
    try {
      const result = await updateBookCard(id, {
        current_chapter: null,
        current_page: null,
        total_pages: null,
        progress_percent: null,
      });
      onCardChanged(result.card, "Reading position cleared.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(
      `Remove "${valText(card.title)}" from the active library? `
      + "This archives the card and keeps every detail, note, and history event.",
    )) return;
    setBusy(true); setError(null);
    try {
      const result = await archiveBookCard(id);
      onCardChanged(result.card, "Book archived. It can be restored at any time.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="book-drawer-controls">
      <div className="book-drawer-hero">
        <div>
          <span className="eyebrow">Library record</span>
          <h3>{valText(card.title) || "Title missing"}</h3>
          <p>{valText(card.author) ? `by ${valText(card.author)}` : "Author not listed"}</p>
        </div>
        <div className="book-drawer-actions">
          {!editing && !archived && (
            <button className="actbtn" disabled={!writable || busy}
              onClick={() => { setDraft(makeDraft(card)); setEditing(true); }}>
              Edit book
            </button>
          )}
          {!archived ? (
            <button className="book-remove-btn" disabled={!writable || busy}
              onClick={() => void remove()}>Remove book</button>
          ) : (
            <button className="actbtn" disabled={!writable || busy || !onRestore}
              onClick={onRestore}>Restore to To read</button>
          )}
        </div>
      </div>
      <div className="book-archive-explainer">
        Remove means archive: the card, notes, provenance, and history are retained.
      </div>
      {error && <div className="error">ERR {error}</div>}
      {!archived && (
        <section className="book-position-panel" aria-label="Reading position">
          <div className="book-section-heading">
            <div>
              <span className="eyebrow">Current place</span>
              <h3>Reading position</h3>
            </div>
            <span className="book-position-percent">
              {position.progress_percent
                ? position.progress_percent + "%"
                : "not set"}
            </span>
          </div>
          <div className="book-position-grid">
            <label className="book-field-wide">Chapter or section
              <input value={position.current_chapter}
                placeholder="e.g. Chapter 4 - The argument"
                disabled={!writable || busy}
                onChange={(e) => setPosition({
                  ...position, current_chapter: e.target.value,
                })} />
            </label>
            <label>Current page <input type="number" min={0}
              value={position.current_page} disabled={!writable || busy}
              onChange={(e) => setPosition({
                ...position, current_page: e.target.value,
              })} /></label>
            <label>Total pages <input type="number" min={1}
              value={position.total_pages} disabled={!writable || busy}
              onChange={(e) => setPosition({
                ...position, total_pages: e.target.value,
              })} /></label>
            <label className="book-position-slider book-field-wide">
              <span>Progress</span>
              <input type="range" min={0} max={100} step={1}
                value={position.progress_percent || "0"}
                disabled={!writable || busy}
                onChange={(e) => setPosition({
                  ...position, progress_percent: e.target.value,
                })} />
            </label>
          </div>
          <div className="actions">
            <button className="actbtn book-primary-action"
              disabled={!writable || busy} onClick={() => void savePosition()}>
              {busy ? "Saving..." : "Save reading position"}
            </button>
            <button className="clear" disabled={!writable || busy}
              onClick={() => void clearPosition()}>Clear position</button>
          </div>
        </section>
      )}
      {editing && (
        <div className="book-edit-panel">
          <div className="book-entry-grid">
            <label className="book-field-wide">Book title <input value={draft.title}
              disabled={busy}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
            <label>Author <input value={draft.author} disabled={busy}
              onChange={(e) => setDraft({ ...draft, author: e.target.value })} /></label>
            <label>Priority <input value={draft.tier} disabled={busy}
              onChange={(e) => setDraft({ ...draft, tier: e.target.value })} /></label>
            <label>Genre <input value={draft.genre} list="book-genres-drawer"
              disabled={busy}
              onChange={(e) => setDraft({ ...draft, genre: e.target.value })} />
              <datalist id="book-genres-drawer">
                <option value="Biography" /><option value="Business" />
                <option value="Fiction" /><option value="History" />
                <option value="Philosophy" /><option value="Science" />
                <option value="Technology" />
              </datalist>
            </label>
            <label>Format / source label <input value={draft.type} disabled={busy}
              onChange={(e) => setDraft({ ...draft, type: e.target.value })} /></label>
            <label>Module / collection <input value={draft.module} disabled={busy}
              onChange={(e) => setDraft({ ...draft, module: e.target.value })} /></label>
            <label>Section <input value={draft.section} disabled={busy}
              onChange={(e) => setDraft({ ...draft, section: e.target.value })} /></label>
            <label>Estimated hours <input value={draft.hours} inputMode="decimal"
              disabled={busy}
              onChange={(e) => setDraft({ ...draft, hours: e.target.value })} /></label>
            <label>ISBN <input value={draft.isbn} disabled={busy}
              onChange={(e) => setDraft({ ...draft, isbn: e.target.value })} /></label>
            <label className="book-field-wide">Details <textarea value={draft.description}
              rows={4} disabled={busy}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
            <label className="book-field-wide">Existing notes / overview
              <textarea value={draft.notes} rows={6} disabled={busy}
                onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
          </div>
          <div className="actions">
            <button className="actbtn book-primary-action" disabled={busy || !draft.title.trim()}
              onClick={() => void save()}>{busy ? "Saving…" : "Save changes"}</button>
            <button className="clear" disabled={busy}
              onClick={() => { setEditing(false); setDraft(makeDraft(card)); }}>Cancel</button>
          </div>
        </div>
      )}
      <BookNotesTimeline card={card} />
      {!archived && (
        <div className="book-drawer-note-entry">
          <div className="book-section-heading">
            <div><span className="eyebrow">Next in sequence</span><h3>Add a note</h3></div>
          </div>
          <div className="book-note-entry">
            <label>Added by <input value={author} list="book-note-authors-drawer"
              placeholder="Required" disabled={!writable || busy}
              onChange={(e) => setAuthor(e.target.value)} />
              <datalist id="book-note-authors-drawer"><option value="Geoff" /><option value="Assistant" /></datalist>
            </label>
            <label>Chapter <input value={noteChapter}
              placeholder="Optional chapter or section"
              disabled={!writable || busy}
              onChange={(e) => setNoteChapter(e.target.value)} /></label>
            <label>Page <input type="number" min={0} value={notePage}
              disabled={!writable || busy}
              onChange={(e) => setNotePage(e.target.value)} /></label>
            <label>Total pages <input type="number" min={1}
              value={noteTotalPages} disabled={!writable || busy}
              onChange={(e) => setNoteTotalPages(e.target.value)} /></label>
            <label className="book-progress-field">
              <span>Progress {noteProgress ? noteProgress + "%" : "not set"}</span>
              <input type="range" min={0} max={100} step={1}
                value={noteProgress || "0"} disabled={!writable || busy}
                onChange={(e) => setNoteProgress(e.target.value)} />
            </label>
            <label className="book-field-wide">Note <textarea value={text} rows={4}
              placeholder="Add the next observation in order"
              disabled={!writable || busy}
              onChange={(e) => setText(e.target.value)} /></label>
            <button className="actbtn book-primary-action" disabled={
              !writable || busy || !author.trim() || !text.trim()
            } onClick={() => void appendNote()}>
              {busy ? "Adding…" : "Add ordered note"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
function PaperCard({ card, registeredProjects }: {
  card: DomainCard; registeredProjects: string[];
}) {
  const title = valText(card.title);
  const detailBadge = researchDetailBadge(card, registeredProjects);
  const relevance = researchScore(card.relevance_score);
  const impact = researchScore(card.potential_impact_score);
  const projectFit = researchScore(card.best_project_fit_score);
  return (
    <div className="domain-card-body">
      <div className={`domain-title ${title ? "" : "missing-title"}`}>
        {title || "Paper title unavailable"}
      </div>
      <div className="domain-badges">
        <Badge value={card.research_priority ? `${titleToken(valText(card.research_priority))} priority` : ""}
          tone={researchPriorityTone(card.research_priority)} />
        <Badge value={relevance === null ? "" : `Relevance ${relevance}/100`} />
        <Badge value={impact === null ? "" : `Impact ${impact}/100`} />
        <Badge value={card.best_project && projectFit !== null
          ? `${valText(card.best_project)} ${projectFit}/100` : ""} />
        <Badge value={detailBadge.label} tone={detailBadge.tone} />
      </div>
      <div className="domain-badges"><Badge value={card.venue} /><Badge value={card.year} /><Badge value={card.useful_for} /></div>
      <div className="domain-clamp">{valText(card.abstract)}</div>
      <StatusPill value={card.status} />
    </div>
  );
}
function RepoCard({ card, registeredProjects }: {
  card: DomainCard; registeredProjects: string[];
}) {
  const title = valText(card.title || card.repo_id);
  const detailBadge = researchDetailBadge(card, registeredProjects);
  const relevance = researchScore(card.relevance_score);
  const readiness = researchScore(card.implementation_readiness_score);
  const projectFit = researchScore(card.best_project_fit_score);
  return (
    <div className="domain-card-body">
      <div className={`domain-title ${title ? "" : "missing-title"}`}>
        {title || "Repository title unavailable"}
      </div>
      <div className="domain-badges">
        <Badge value={card.research_priority ? `${titleToken(valText(card.research_priority))} priority` : ""}
          tone={researchPriorityTone(card.research_priority)} />
        <Badge value={relevance === null ? "" : `Relevance ${relevance}/100`} />
        <Badge value={readiness === null ? "" : `Ready ${readiness}/100`} />
        <Badge value={card.best_project && projectFit !== null
          ? `${valText(card.best_project)} ${projectFit}/100` : ""} />
        <Badge value={detailBadge.label} tone={detailBadge.tone} />
      </div>
      <div className="domain-badges">
        <Badge value={card.language} />
        <Badge value={card.stars === undefined ? "" : `${valText(card.stars)} stars`} />
        <Badge value={card.license} />
      </div>
      <div className="domain-clamp">{valText(card.why)}</div>
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
  onOpenChat, chatHarnesses = null, researchProjects = [],
}: {
  spec: DomainSpec; card: DomainCard; onOpen: () => void;
  canDrag?: boolean; onDragStart?: () => void;
  moveTargets?: string[]; onMove?: (status: string) => void;
  onOpenPacket?: () => void;
  // (prompt, target) — target undefined = GatewayCore, "agent:<harness>" = Claude/Codex
  onOpenChat?: (prompt: string, target?: string) => void;
  chatHarnesses?: AgentHarnessOption[] | null;
  researchProjects?: string[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [chatTarget, setChatTarget] = useState("GatewayCore");
  const [chatPending, setChatPending] = useState(false);
  // Seed the chat with this card's full context (the same authoritative
  // chat_prompt the drawer uses), then open on the chosen assistant lane.
  async function chatAboutCard(target?: string) {
    if (chatPending) return;
    setChatPending(true);
    const cid = card.card_id;
    const fallback = `About ${spec.title}${cid != null ? ` card ${cid}` : ""}:`;
    try {
      if (cid == null) {
        onOpenChat?.(fallback, target);
        return;
      }
      try {
        const prog = await fetchDomainCardProgress(spec.domain_id, String(cid));
        onOpenChat?.(prog.chat_prompt || fallback, target);
      } catch {
        onOpenChat?.(fallback, target);
      }
    } finally {
      setChatPending(false);
    }
  }
  let body: ReactNode;
  switch (spec.card_component) {
    case "job_application": body = <JobApplicationCard card={card} />; break;
    case "linkedin_post": body = <LinkedInPreview card={card} />; break;
    case "book": body = <BookCard card={card} />; break;
    case "paper": body = <PaperCard card={card}
      registeredProjects={researchProjects} />; break;
    case "repo": body = <RepoCard card={card}
      registeredProjects={researchProjects} />; break;
    case "dag": body = <DagCard card={card} />; break;
    case "machine_upkeep": body = <MachineUpkeepCard card={card} />; break;
    case "mission": body = <MissionDomainCard card={card} />; break;
    default: body = <GenericTaskCard card={card} />; break;
  }
  return (
    <div className={`domain-card card-disclosure-card ${canDrag ? "draggable" : ""} ${expanded ? "card-expanded" : ""}`}
      draggable={canDrag}
      onDragStart={(e) => {
        if (canDrag) {
          e.dataTransfer.effectAllowed = "move";
          onDragStart?.();
        }
      }}>
      <CardDisclosure
        title={domainTitle(card, spec)}
        priority={cardPriority(card)}
        estimate={cardEstimate(card)}
        description={domainCardDescription(card, spec)}
        expanded={expanded}
        onToggle={() => setExpanded((current) => !current)}
        onOpen={onOpen}>
        <div className="card-inline-preview">{body}</div>
        {onOpenChat && (
          <div className="card-chat-actions">
            <button className="actbtn" title="Open this card in chat with its full context"
              disabled={chatPending}
              onClick={() => void chatAboutCard(chatTarget)}>
              {chatPending ? "Opening…" : "Open in chat"}
            </button>
            <select className="select card-runtime-select" value={chatTarget}
              disabled={chatPending} aria-label="Chat runtime"
              onChange={(event) => setChatTarget(event.target.value)}>
              <option value="GatewayCore">GatewayCore</option>
              {chatHarnesses?.map((harness) => {
                const runtime = runtimeLabel(harness);
                return (
                  <option key={harness.harness_id}
                    value={`agent:${harness.harness_id}`}
                    disabled={!harness.available} title={harness.detail}>
                    {runtime.label}
                  </option>
                );
              })}
            </select>
          </div>
        )}
        {onOpenPacket && (
          <button className="actbtn card-packet-btn"
            title="open the application packet: resume, cover letter, story, and external-submission record"
            onClick={onOpenPacket}>
            review packet
          </button>
        )}
        {moveTargets.length > 0 && (
          <div className="move-buttons">
            {moveTargets.map((s, i) => (
              <button key={s} className={`move-btn ${i === 0 ? "move-fwd" : "move-back"}`}
                onClick={() => onMove?.(s)}
                title={`Move to ${s}`}>
                {i === 0 ? "→ " : ""}{s}
              </button>
            ))}
          </div>
        )}
      </CardDisclosure>
    </div>
  );
}

function IntakeParameterInput({ name, value, disabled, onChange }: {
  name: string; value: DomainIntakeValue; disabled: boolean;
  onChange: (value: DomainIntakeValue) => void;
}) {
  if (typeof value === "boolean") {
    return (
      <label className="intake-param intake-param-check">
        <span>{titleToken(name)}</span>
        <input type="checkbox" checked={value} disabled={disabled}
          onChange={(e) => onChange(e.target.checked)} />
      </label>
    );
  }
  if (typeof value === "number") {
    return (
      <label className="intake-param">
        <span>{titleToken(name)}</span>
        <input type="number" min={0} value={value} disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))} />
      </label>
    );
  }
  if (Array.isArray(value)) {
    return (
      <div className="intake-param intake-param-wide">
        <CreatableTagPicker label={titleToken(name)} values={value}
          suggestions={value} disabled={disabled} placeholder={`Add ${titleToken(name).toLowerCase()}`}
          help="Type a value or choose an existing one; press Enter to add a bubble."
          onChange={(next) => onChange(next)} />
      </div>
    );
  }
  return (
    <label className="intake-param intake-param-wide">
      <span>{titleToken(name)}</span>
      <textarea value={value} disabled={disabled}
        onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function CreatableTagPicker({ label, help, values, suggestions, disabled, placeholder,
  labels = {}, allowCreate = true, onChange }: {
  label: string;
  help: string;
  values: string[];
  suggestions: string[];
  disabled: boolean;
  placeholder: string;
  labels?: Record<string, string>;
  allowCreate?: boolean;
  onChange: (values: string[]) => void;
}) {
  const [input, setInput] = useState("");
  const listId = useMemo(
    () => `tag-options-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    [label],
  );
  const inputId = `${listId}-input`;
  const helpId = `${listId}-help`;
  const key = (value: string) => value.trim().replace(/\s+/g, " ").toLowerCase();
  function add(raw: string) {
    const typed = raw.trim().replace(/\s+/g, " ");
    if (!typed) return;
    const suggested = suggestions.find((value) => key(value) === key(typed));
    if (!suggested && !allowCreate) {
      setInput("");
      return;
    }
    const next = suggested ?? typed;
    if (!values.some((value) => key(value) === key(next))) {
      onChange([...values, next]);
    }
    setInput("");
  }
  const remaining = suggestions.filter((suggestion) =>
    !values.some((value) => key(value) === key(suggestion)));
  return (
    <div className="research-tag-field">
      <label className="research-field-label" htmlFor={inputId}>{label}</label>
      <span className="muted small" id={helpId}>{help}</span>
      <div className={`tag-combobox ${disabled ? "tag-combobox-disabled" : ""}`}>
        <div className="tag-bubbles">
          {values.map((value) => (
            <span className="tag-bubble" key={key(value)}>
              <span>{labels[value] ?? value}</span>
              {!disabled && (
                <button type="button" aria-label={`Remove ${value}`}
                  onClick={() => onChange(values.filter((item) => key(item) !== key(value)))}>
                  ×
                </button>
              )}
            </span>
          ))}
          <input id={inputId} value={input} disabled={disabled} list={listId}
            aria-describedby={helpId}
            placeholder={values.length ? "Add another..." : placeholder}
            onChange={(event) => {
              const next = event.target.value;
              setInput(next);
              if (suggestions.some((value) => key(value) === key(next))) add(next);
            }}
            onBlur={() => add(input)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault(); add(input);
              } else if (event.key === "Backspace" && !input && values.length) {
                onChange(values.slice(0, -1));
              }
            }} />
          <datalist id={listId}>
            {remaining.map((value) => (
              <option key={value} value={value}>{labels[value] ?? value}</option>
            ))}
          </datalist>
          {!disabled && allowCreate && input.trim() && (
            <button className="tag-add" type="button" onMouseDown={(event) => {
              event.preventDefault(); add(input);
            }}>Add</button>
          )}
        </div>
      </div>
    </div>
  );
}

type ResearchSourceDraft = {
  enabled: boolean;
  top_n: number;
  lookback_days: number;
  analysis_batch_size: number;
  categories?: string[];
  min_stars?: number;
};
type ResearchDraft = {
  topics: string[];
  paper: ResearchSourceDraft;
  repo: ResearchSourceDraft;
};

function researchDraft(value: ResearchSettingsResponse): ResearchDraft {
  const paper = value.paper.intake.parameters;
  const repo = value.repo.intake.parameters;
  const numberValue = (candidate: DomainIntakeValue | undefined, fallback: number) =>
    typeof candidate === "number" ? candidate : fallback;
  return {
    topics: value.topics,
    paper: {
      enabled: paper.enabled === true,
      top_n: numberValue(paper.top_n, 12),
      lookback_days: numberValue(paper.lookback_days, 3),
      analysis_batch_size: numberValue(paper.analysis_batch_size, 25),
      categories: Array.isArray(paper.categories) ? paper.categories : [],
    },
    repo: {
      enabled: repo.enabled === true,
      top_n: numberValue(repo.top_n, 10),
      lookback_days: numberValue(repo.lookback_days, 7),
      analysis_batch_size: numberValue(repo.analysis_batch_size, 25),
      min_stars: numberValue(repo.min_stars, 25),
    },
  };
}

function AnalysisProgress({ label, counts }: {
  label: string; counts: ResearchAnalysisCounts;
}) {
  const ratio = counts.total ? counts.complete / counts.total : 0;
  return (
    <div className="research-progress-card">
      <div><b>{label}</b><span>{counts.complete} / {counts.total} fully detailed</span></div>
      {counts.total > 0 ? (
        <div className="research-progress-track" aria-label={`${label} detail coverage`}
          role="progressbar" aria-valuemin={0} aria-valuemax={counts.total}
          aria-valuenow={counts.complete}
          aria-valuetext={`${counts.complete} of ${counts.total} fully detailed`}>
          <span style={{ width: `${Math.round(ratio * 100)}%` }} />
        </div>
      ) : (
        <div className="research-progress-empty" role="status">
          No visible cards to analyze
        </div>
      )}
      <small>{counts.total === 0
        ? "No visible cards to analyze yet"
        : counts.complete === counts.total
        ? "Every card has a title and complete analysis"
        : `${counts.pending} waiting for full analysis${counts.missing_title ? ` · ${counts.missing_title} missing titles` : ""}`}</small>
    </div>
  );
}

function researchAnalysisCounts(
  cards: DomainCard[], registeredProjects: string[],
): ResearchAnalysisCounts {
  const titled = cards.filter((card) => valText(card.title));
  const complete = titled.filter(
    (card) => researchAnalysisComplete(card, registeredProjects)).length;
  return {
    total: cards.length,
    titled: titled.length,
    complete,
    pending: titled.length - complete,
    missing_title: cards.length - titled.length,
  };
}

function sortedResearchValues(cards: DomainCard[], field: string): string[] {
  return Array.from(new Set(cards.flatMap((card) => valList(card[field]))))
    .sort((a, b) => a.localeCompare(b));
}
function researchFiltersActive(value: ResearchFilters): boolean {
  return (
    value.workAreas.length > 0 || value.useCases.length > 0
    || value.projects.length > 0 || value.priorities.length > 0
    || !!value.detailState || value.minRelevance > 0 || value.minImpact > 0
    || value.minReadiness > 0 || value.minConfidence > 0
    || value.minProjectFit > 0
  );
}
function researchCardMatchesFilters(
  card: DomainCard, filters: ResearchFilters, registeredProjects: string[],
): boolean {
  const includesAny = (selected: string[], available: string[]) =>
    !selected.length || selected.some((value) => available.includes(value));
  if (!includesAny(filters.workAreas, valList(card.work_areas))) return false;
  if (!includesAny(filters.useCases, valList(card.use_cases))) return false;
  if (!includesAny(filters.priorities, [valText(card.research_priority)])) return false;
  const complete = researchAnalysisComplete(card, registeredProjects);
  if (filters.detailState === "complete" && !complete) return false;
  if (filters.detailState === "pending" && complete) return false;
  const scoreMinimums: [string, number][] = [
    ["relevance_score", filters.minRelevance],
    ["potential_impact_score", filters.minImpact],
    ["implementation_readiness_score", filters.minReadiness],
    ["evidence_confidence_score", filters.minConfidence],
  ];
  if (scoreMinimums.some(([field, minimum]) => {
    if (!minimum) return false;
    const score = researchScore(card[field]);
    return score === null || score < minimum;
  })) return false;
  const fits = researchProjectFits(card);
  if (filters.projects.length) {
    if (!filters.projects.some((project) =>
      fits.some((fit) =>
        fit.project === project && fit.fit_score >= filters.minProjectFit))) {
      return false;
    }
  } else if (filters.minProjectFit > 0) {
    const best = researchScore(card.best_project_fit_score);
    if (best === null || best < filters.minProjectFit) return false;
  }
  return true;
}

function ResearchMinimum({ label, value, onChange }: {
  label: string; value: number; onChange: (value: number) => void;
}) {
  return (
    <label className="research-score-filter">
      <span>{label}<b>{value ? `${value}+` : "Any"}</b></span>
      <input type="range" min={0} max={100} step={5} value={value}
        aria-label={`Minimum ${label.toLowerCase()}`}
        onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function ResearchFilterPanel({ cards, projectSuggestions = [], value, onChange }: {
  cards: DomainCard[];
  projectSuggestions?: string[];
  value: ResearchFilters;
  onChange: (value: ResearchFilters) => void;
}) {
  const workAreas = sortedResearchValues(cards, "work_areas");
  const useCases = sortedResearchValues(cards, "use_cases");
  const projects = Array.from(new Set([
    ...projectSuggestions,
    ...cards.flatMap((card) =>
      researchProjectFits(card).map((fit) => fit.project)),
  ]))
    .sort((a, b) => a.localeCompare(b));
  const priorities = ["high", "medium", "low", "watch"];
  return (
    <section className="research-filter-panel" aria-label="Research KPI filters">
      <div className="research-filter-head">
        <div>
          <span className="eyebrow">Review controls</span>
          <h3>Filter by our use case and KPI scores</h3>
          <p>Type to search, then select an existing value. Bubbles are OR within a field and AND across fields.</p>
        </div>
        {researchFiltersActive(value) && (
          <button className="clear" onClick={() => onChange({ ...EMPTY_RESEARCH_FILTERS })}>
            Clear KPI filters
          </button>
        )}
      </div>
      <div className="research-filter-tags">
        <CreatableTagPicker label="Areas of work" values={value.workAreas}
          suggestions={workAreas} disabled={false} allowCreate={false}
          placeholder="Search existing work areas"
          help="Search and select an existing work area."
          onChange={(workAreas) => onChange({ ...value, workAreas })} />
        <CreatableTagPicker label="Use cases" values={value.useCases}
          suggestions={useCases} disabled={false} allowCreate={false}
          placeholder="Search existing use cases"
          help="Search and select an existing application."
          onChange={(useCases) => onChange({ ...value, useCases })} />
        <CreatableTagPicker label="Registered folders" values={value.projects}
          suggestions={projects} disabled={false} allowCreate={false}
          placeholder="Search registered folders"
          help="Search and select a registered folder with a scored fit."
          onChange={(next) => onChange({ ...value, projects: next })} />
        <CreatableTagPicker label="Priorities" values={value.priorities}
          suggestions={priorities} disabled={false} allowCreate={false}
          placeholder="Search priorities"
          help="High, medium, low, or watch."
          labels={{ high: "High", medium: "Medium", low: "Low", watch: "Watch" }}
          onChange={(next) => onChange({ ...value, priorities: next })} />
      </div>
      <div className="research-filter-bottom">
        <label className="research-detail-filter">
          <span>Detail coverage</span>
          <select className="select" value={value.detailState}
            onChange={(event) => onChange({
              ...value,
              detailState: event.target.value as ResearchFilters["detailState"],
            })}>
            <option value="">All detail states</option>
            <option value="complete">Complete details only</option>
            <option value="pending">Incomplete details only</option>
          </select>
        </label>
        <div className="research-score-filters">
          <ResearchMinimum label="Relevance" value={value.minRelevance}
            onChange={(minRelevance) => onChange({ ...value, minRelevance })} />
          <ResearchMinimum label="Impact" value={value.minImpact}
            onChange={(minImpact) => onChange({ ...value, minImpact })} />
          <ResearchMinimum label="Readiness" value={value.minReadiness}
            onChange={(minReadiness) => onChange({ ...value, minReadiness })} />
          <ResearchMinimum label="Confidence" value={value.minConfidence}
            onChange={(minConfidence) => onChange({ ...value, minConfidence })} />
          <ResearchMinimum label="Folder fit" value={value.minProjectFit}
            onChange={(minProjectFit) => onChange({ ...value, minProjectFit })} />
        </div>
      </div>
    </section>
  );
}

function ResearchSetupPanel({ activeSource, analysis, onSaved }: {
  activeSource: "paper" | "repo";
  analysis: { paper: ResearchAnalysisCounts; repo: ResearchAnalysisCounts };
  onSaved: () => void;
}) {
  const [settings, setSettings] = useState<ResearchSettingsResponse | null>(null);
  const [draft, setDraft] = useState<ResearchDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetchResearchSettings().then((value) => {
      if (!live) return;
      setSettings(value); setDraft(researchDraft(value));
    }).catch((error) => live && setMsg((error as Error).message));
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!settings || !["queued", "running"].includes(settings.refresh.state)) return;
    const timer = window.setInterval(() => {
      fetchResearchRefresh().then((value) => {
        setSettings((current) => current ? ({
          ...current,
          refresh: value.refresh,
        }) : current);
        if (["complete", "blocked"].includes(value.refresh.state)) onSaved();
      }).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [settings?.refresh.state, onSaved]);
  if (!settings || !draft) {
    return <div className="board-intake research-setup"><div className="loading">Loading research setup...</div></div>;
  }
  const currentSettings = settings;
  const progressCounts = (source: "paper" | "repo") => (
    exactResearchProgressCounts(analysis[source])
  );
  const writable = currentSettings.paper.writable && currentSettings.repo.writable;
  const categoryLabels = Object.fromEntries(
    currentSettings.category_options.map((option) => [option.value, `${option.value} · ${option.label}`]));
  const updateSource = (
    source: "paper" | "repo", patch: Partial<ResearchSourceDraft>,
  ) => setDraft((current) => current ? ({
    ...current, [source]: { ...current[source], ...patch },
  }) : current);
  async function save() {
    if (!draft) return;
    setBusy(true); setMsg(null);
    try {
      const value = await updateResearchSettings({
        topics: draft.topics,
        paper: draft.paper,
        repo: draft.repo,
        expected_revisions: {
          paper: currentSettings.paper.revision,
          repo: currentSettings.repo.revision,
        },
        refresh: true,
      });
      setSettings(value); setDraft(researchDraft(value));
      setMsg("Saved. A fresh source pull and complete-detail backfill are queued.");
      onSaved();
    } catch (error) { setMsg((error as Error).message); }
    finally { setBusy(false); }
  }
  async function refreshNow() {
    setBusy(true); setMsg(null);
    try {
      const value = await requestResearchRefresh(["paper", "repo"]);
      setSettings({ ...currentSettings, refresh: value.refresh });
      setMsg("Refresh queued for Papers and Repos.");
    } catch (error) { setMsg((error as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <section className="board-intake research-setup" aria-label="Research topics and intake">
      <div className="research-setup-head">
        <div>
          <span className="eyebrow">Shared research setup</span>
          <h3>What are we looking for?</h3>
          <p>Each topic becomes its own review board in both Papers and Repos. Type a topic or pick an existing one; provider query syntax is added automatically.</p>
        </div>
        <button className="actbtn" disabled={busy || !writable}
          title={writable ? "Pull new results and continue missing card details" : settings.paper.write_gate}
          onClick={() => void refreshNow()}>Refresh both now</button>
      </div>
      <CreatableTagPicker label="Research topics" values={draft.topics}
        suggestions={settings.topic_suggestions} disabled={busy || !writable}
        placeholder="e.g. Agent evaluation"
        help="Use one readable topic per bubble; source search syntax is handled automatically."
        onChange={(topics) => setDraft({
          ...draft,
          topics,
          paper: { ...draft.paper, top_n: Math.max(draft.paper.top_n, topics.length) },
          repo: { ...draft.repo, top_n: Math.max(draft.repo.top_n, topics.length) },
        })} />
      <div className="research-source-grid">
        {(["paper", "repo"] as const).map((source) => {
          const value = draft[source];
          const label = source === "paper" ? "Paper sources" : "Repository sources";
          return (
            <fieldset className={`research-source-card ${activeSource === source ? "research-source-active" : ""}`}
              key={source} disabled={busy || !writable}>
              <legend>{label}</legend>
              <label className="research-toggle">
                <input type="checkbox" checked={value.enabled}
                  onChange={(event) => updateSource(source, { enabled: event.target.checked })} />
                <span>Pull new {source === "paper" ? "papers" : "repos"}</span>
              </label>
              <div className="research-number-grid">
                <label><span>Results per pull</span><input type="number" min={1} max={500}
                  value={value.top_n} onChange={(event) => updateSource(source, { top_n: Number(event.target.value) })} /></label>
                <label><span>Look back (days)</span><input type="number" min={0} max={365}
                  value={value.lookback_days} onChange={(event) => updateSource(source, { lookback_days: Number(event.target.value) })} /></label>
                <label><span>Details per batch</span><input type="number" min={1} max={200}
                  value={value.analysis_batch_size} onChange={(event) => updateSource(source, { analysis_batch_size: Number(event.target.value) })} /></label>
                {source === "repo" && <label><span>Minimum stars</span><input type="number" min={0}
                  value={value.min_stars ?? 0} onChange={(event) => updateSource(source, { min_stars: Number(event.target.value) })} /></label>}
              </div>
              {source === "paper" && (
                <CreatableTagPicker label="arXiv areas" values={value.categories ?? []}
                  suggestions={settings.category_options.map((option) => option.value)}
                  labels={categoryLabels} disabled={busy || !writable}
                  placeholder="Select or enter an arXiv area"
                  help="Optional source areas broaden discovery beyond the topic wording."
                  onChange={(categories) => updateSource("paper", { categories })} />
              )}
            </fieldset>
          );
        })}
      </div>
      <div className="research-progress-grid">
        <AnalysisProgress label={`Papers${["queued", "running"].includes(settings.refresh.state) ? " · existing-card backfill" : ""}`}
          counts={progressCounts("paper")} />
        <AnalysisProgress label={`Repos${["queued", "running"].includes(settings.refresh.state) ? " · existing-card backfill" : ""}`}
          counts={progressCounts("repo")} />
      </div>
      <div className={`research-refresh-state refresh-${settings.refresh.state}`}
        role="status" aria-live="polite">
        <Badge value={settings.refresh.state} />
        <span>{settings.refresh.message ?? "No refresh is currently running."}</span>
      </div>
      <div className="preset-actions">
        <button className="actbtn" disabled={busy || !writable || draft.topics.length === 0}
          onClick={() => void save()}>{busy ? "Working..." : "Save and refresh"}</button>
        <span className="muted small">Saving applies the same topic boards to both sources and starts a fresh pull.</span>
      </div>
      {msg && <div className={/saved|queued/i.test(msg) ? "actmsg" : "error"}>{msg}</div>}
    </section>
  );
}

function BoardIntakePanel({ spec, onSaved }: {
  spec: DomainSpec; onSaved: () => void;
}) {
  const [state, setState] = useState<DomainIntakeResponse | null>(null);
  const [draft, setDraft] = useState<DomainIntake>(spec.intake);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setDraft(spec.intake);
    setEditing(false);
    fetchDomainIntake(spec.domain_id)
      .then((value) => {
        if (!live) return;
        setState(value);
        setDraft(value.intake);
      })
      .catch((e) => live && setMsg((e as Error).message));
    return () => { live = false; };
  }, [spec.domain_id, spec.intake]);
  const shown = state?.intake ?? spec.intake;
  function setParameter(name: string, value: DomainIntakeValue) {
    setDraft((current) => ({
      ...current,
      parameters: { ...current.parameters, [name]: value },
    }));
  }
  async function save() {
    if (!state) return;
    setBusy(true); setMsg(null);
    try {
      const next = await updateDomainIntake(
        spec.domain_id, draft, state.revision);
      setState(next); setDraft(next.intake); setEditing(false);
      setMsg("intake updated; the next producer run will use these inputs");
      onSaved();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <details className="board-intake">
      <summary>
        <span>What this Kanban pulls in</span>
        <Badge value={shown.producer} />
        <span className="muted small">{shown.schedule}</span>
      </summary>
      <div className="board-intake-body">
        {!editing ? (
          <>
            <p>{shown.summary}</p>
            <div className="domain-badges">
              <Badge value={shown.mode} />
              {shown.source_refs.map((ref) => <code key={ref}>{ref}</code>)}
            </div>
            <div className="intake-parameters">
              {Object.entries(shown.parameters).map(([name, value]) => (
                <div className="intake-read-row" key={name}>
                  <b>{titleToken(name)}</b>
                  <span>{Array.isArray(value) ? value.join(", ") : String(value)}</span>
                </div>
              ))}
            </div>
            <button className="actbtn" disabled={!state?.writable}
              title={state?.write_gate ?? "loading intake write gate"}
              onClick={() => { setDraft(shown); setEditing(true); setMsg(null); }}>
              Adjust intake
            </button>
          </>
        ) : (
          <>
            <label className="intake-param intake-param-wide">
              <span>What belongs here</span>
              <textarea value={draft.summary} disabled={busy}
                onChange={(e) => setDraft({ ...draft, summary: e.target.value })} />
            </label>
            <label className="intake-param">
              <span>Schedule <small>registry-owned</small></span>
              <input value={draft.schedule} disabled
                title="Cadence is operational wiring and cannot be changed from the board." />
            </label>
            <div className="intake-parameter-grid">
              {Object.entries(draft.parameters).map(([name, value]) => (
                <IntakeParameterInput key={name} name={name} value={value}
                  disabled={busy} onChange={(next) => setParameter(name, next)} />
              ))}
            </div>
            <div className="preset-actions">
              <button className="actbtn" disabled={busy || !draft.summary.trim()}
                onClick={() => void save()}>{busy ? "saving..." : "Save intake"}</button>
              <button className="clear" disabled={busy}
                onClick={() => { setDraft(shown); setEditing(false); }}>cancel</button>
            </div>
          </>
        )}
        {msg && <div className={msg.startsWith("intake updated") ? "actmsg" : "error"}>{msg}</div>}
      </div>
    </details>
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
          <span>OxyGent / ORCA / OmniAgent</span>
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
    intake: {
      producer: "manual",
      mode: "manual",
      summary: "Cards are added directly from this board.",
      schedule: "on demand",
      source_refs: [],
      parameters: { instructions: "Describe what belongs on this board." },
      editable: true,
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
    intake: initial.intake,
    archived: initial.archived ?? false,
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
  async function archive() {
    if (mode !== "update") return;
    if (!window.confirm(`Archive ${initial.title}? Its cards and history remain intact and the board becomes read-only until restored.`)) return;
    setBusy(true); setMsg(null);
    try {
      await archiveDomainSchema(initial.domain_id);
      setMsg("archived");
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
        {mode === "update" && !initial.archived && <button className="editbtn danger" disabled={!editable || busy} onClick={archive}>archive</button>}
        {msg && <span className={msg === "updated" || msg === "archived" ? "actmsg" : "error-inline"}>{msg}</span>}
      </div>
    </div>
  );
}

// Guided Create-Board flow: name → optional repos → preview → create.
// Produces a whole board module (kanban board + generic_task surface) via the
// typed /api/board-module endpoint. Generic-first; the user can upgrade the card
// component + fields later with the "edit" (DomainSchemaEditor) flow.
function CreateBoardWizard({ editable, onClose, onCreated }: {
  editable: boolean;
  routingMode?: boolean;
  onClose: () => void;
  onCreated: (boardId: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState("");
  const [scope, setScope] = useState<ExecutionScope>("life");
  const [reposText, setReposText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const boardId = boardIdFromTitle(title);
  const repoIds = reposText.split(",").map((s) => s.trim()).filter(Boolean);
  const needsRepo = scope !== "life";
  async function create() {
    if (!boardId || busy) return;
    setBusy(true); setMsg(null);
    try {
      const res = await createBoardModule({
        title: title.trim(), description: description.trim(), icon: icon.trim(),
        execution_scope: scope, repo_ids: repoIds,
        columns: [],
      });
      onCreated(res.board_id);
      onClose();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="schema-editor">
      <div className="settings-card-head">
        <h3>Create Board</h3>
        <button className="editbtn" onClick={onClose}>close</button>
      </div>
      <div className="schema-form-grid">
        <label>Name<input value={title} disabled={!editable || busy} autoFocus
          placeholder="e.g. Books, Health, Papers"
          onChange={(e) => setTitle(e.target.value)} /></label>
        <label>Icon<input value={icon} disabled={!editable || busy}
          placeholder="emoji (optional)" onChange={(e) => setIcon(e.target.value)} /></label>
        <label className="schema-form-wide">Description
          <input value={description} disabled={!editable || busy}
            placeholder="what this board is for (optional)"
            onChange={(e) => setDescription(e.target.value)} /></label>
        <label>Kind<select className="select" value={scope} disabled={!editable || busy}
          onChange={(e) => setScope(e.target.value as ExecutionScope)}>
          <option value="life">life — personal, no repository</option>
          <option value="repository">repository — drives repo work</option>
          <option value="hybrid">hybrid — notes + repo work</option>
        </select></label>
        <label>Repositories<input value={reposText} disabled={!editable || busy || !needsRepo}
          placeholder={needsRepo ? "repo ids, comma-separated (required)" : "not used for a life board"}
          onChange={(e) => setReposText(e.target.value)} /></label>
      </div>
      <div className="schema-preview">
        <div className="muted small">Preview — a new {scope} board module:</div>
        <ul className="muted small">
          <li>board id <code>{boardId || "—"}</code> · generic-task cards · chat enabled</li>
          <li>columns: Backlog, Ready, In Progress, Done, Blocked, Rejected, Awaiting Approval</li>
          <li>repos: {needsRepo ? (repoIds.length ? repoIds.join(", ") : "⚠ name at least one") : "none (life board)"}</li>
          <li>governance: wall verbs (approve / merge / deploy / delete) stay forbidden; human approval unchanged</li>
        </ul>
      </div>
      {msg && <div className="error">ERR {msg}</div>}
      <div className="settings-head-actions">
        <button className="actbtn" disabled={!editable || busy || !boardId} onClick={() => void create()}>
          {busy ? "creating…" : "Create board"}
        </button>
      </div>
    </div>
  );
}

function BoardControlsPanel({ schema, registry, err, onSaved }: {
  schema: DomainSchema | null; registry: BoardRegistry | null; err: string | null;
  onSaved: () => void;
}) {
  const domains = schema?.domains ?? [];
  const activeDomains = domains.filter((domain) => !domain.archived);
  const archivedDomains = domains.filter((domain) => domain.archived);
  const editable = !!schema?.writable;
  const [editing, setEditing] = useState<{ mode: "create" | "update"; domain: DomainSpec } | null>(null);
  const [wizard, setWizard] = useState(false);
  const [restoreMsg, setRestoreMsg] = useState<string | null>(null);
  async function restore(domain: DomainSpec) {
    setRestoreMsg(null);
    try {
      await restoreDomainSchema(domain.domain_id);
      setRestoreMsg(`${domain.title} restored`);
      onSaved();
    } catch (e) { setRestoreMsg((e as Error).message); }
  }
  return (
    <section className="settings-card settings-card-wide">
      <div className="settings-card-head">
        <h3>Kanban Boards</h3>
        <div className="settings-head-actions">
          <span className={`status-pill ${editable ? "pill-run" : "pill-warn"}`}>
            {editable ? "editable" : "read-only"}
          </span>
          <span className="status-pill">{activeDomains.length} active</span>
          <span className="status-pill">{archivedDomains.length} archived</span>
          <button className="actbtn" disabled={!editable} onClick={() => setWizard(true)}>
            Create board
          </button>
          <button className="editbtn" disabled={!editable}
            onClick={() => setEditing({ mode: "create", domain: newDomainSpec(domains) })}>
            advanced
          </button>
        </div>
      </div>
      {wizard && (
        <CreateBoardWizard editable={editable} onClose={() => setWizard(false)}
          onCreated={() => onSaved()} />
      )}
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
        {activeDomains.map((domain) => (
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
      {archivedDomains.length > 0 && (
        <>
          <h3>Archived boards</h3>
          <div className="muted small">Archived boards and all their cards/history are retained read-only. Restore explicitly to edit or route new work.</div>
          <div className="settings-board-grid">
            {archivedDomains.map((domain) => (
              <div className="settings-board" key={domain.domain_id}>
                <div className="settings-board-title"><b>{domain.title}</b><span className="status-pill">archived</span></div>
                <div className="muted small"><code>{domain.domain_id}</code> · {domain.source}</div>
                <button className="editbtn" disabled={!editable}
                  onClick={() => void restore(domain)}>restore</button>
              </div>
            ))}
          </div>
          {restoreMsg && <div className="actmsg">{restoreMsg}</div>}
        </>
      )}
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

const US_STATE_NAMES = [
  "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
  "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
  "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
  "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
  "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
  "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
  "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
  "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
  "Washington", "West Virginia", "Wisconsin", "Wyoming",
  "District of Columbia",
];

function JobFilterSettings({ controls, editable, onSaved }: {
  controls: JobProfileControls; editable: boolean; onSaved: () => void;
}) {
  const loc = controls.locations;
  const lang = controls.languages;
  const [spoken, setSpoken] = useState(lang.spoken.join(", "));
  const [requireSpoken, setRequireSpoken] = useState(lang.require_spoken_for_apply);
  const [mode, setMode] = useState(loc.mode);
  const [remoteOk, setRemoteOk] = useState(loc.remote_ok);
  const [arrangements, setArrangements] = useState<string[]>(loc.remote_types_allowed);
  const [fullTime, setFullTime] = useState(loc.employment_types_allowed.includes("full_time"));
  const [countries, setCountries] = useState(loc.countries.join(", "));
  const [states, setStates] = useState<string[]>(
    US_STATE_NAMES.filter((s) => loc.regions.some((r) => r.toLowerCase() === s.toLowerCase())));
  const [customRegions, setCustomRegions] = useState(
    loc.regions.filter((r) => !US_STATE_NAMES.some((s) => s.toLowerCase() === r.toLowerCase())).join(", "));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    const l = controls.languages, c = controls.locations;
    setSpoken(l.spoken.join(", "));
    setRequireSpoken(l.require_spoken_for_apply);
    setMode(c.mode);
    setRemoteOk(c.remote_ok);
    setArrangements(c.remote_types_allowed);
    setFullTime(c.employment_types_allowed.includes("full_time"));
    setCountries(c.countries.join(", "));
    setStates(US_STATE_NAMES.filter((s) => c.regions.some((r) => r.toLowerCase() === s.toLowerCase())));
    setCustomRegions(c.regions.filter((r) => !US_STATE_NAMES.some((s) => s.toLowerCase() === r.toLowerCase())).join(", "));
  }, [controls]);

  const disabled = !editable || busy;
  const toggle = (list: string[], value: string) =>
    (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  const splitCsv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  async function saveLanguages() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchLanguages({
        spoken: splitCsv(spoken), require_spoken_for_apply: requireSpoken });
      setMsg("languages saved"); onSaved();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }
  async function saveLocations() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchLocations({
        mode, remote_ok: remoteOk,
        remote_types_allowed: arrangements,
        employment_types_allowed: fullTime ? ["full_time"] : [],
        countries: splitCsv(countries),
        regions: [...states, ...splitCsv(customRegions)],
      });
      setMsg("locations saved"); onSaved();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="settings-form job-filter-settings">
      <h3>Languages I speak</h3>
      <div className="settings-form-grid">
        <label>Spoken (comma-separated)
          <input value={spoken} disabled={disabled}
            onChange={(e) => setSpoken(e.target.value)} /></label>
        <label className="chip-check">
          <input type="checkbox" checked={requireSpoken} disabled={disabled}
            onChange={(e) => setRequireSpoken(e.target.checked)} />
          hide jobs that require a language I don't speak</label>
      </div>
      <div className="preset-actions">
        <button className="actbtn" disabled={disabled} onClick={saveLanguages}>save languages</button>
      </div>

      <h3>Locations & work arrangement</h3>
      <div className="settings-form-grid">
        <label>Match mode
          <select value={mode} disabled={disabled} onChange={(e) => setMode(e.target.value)}>
            <option value="worldwide">worldwide (anywhere)</option>
            <option value="countries">countries only</option>
            <option value="regions">specific states / metros</option>
          </select></label>
        <label className="chip-check">
          <input type="checkbox" checked={remoteOk} disabled={disabled}
            onChange={(e) => setRemoteOk(e.target.checked)} /> accept remote anywhere</label>
      </div>
      <div className="filter-toggle-row">
        <span className="filter-toggle-label">Work arrangement:</span>
        {["remote", "hybrid", "onsite"].map((a) => (
          <label key={a} className={`chip-check ${arrangements.includes(a) ? "chip-on" : ""}`}>
            <input type="checkbox" checked={arrangements.includes(a)} disabled={disabled}
              onChange={() => setArrangements((cur) => toggle(cur, a))} />{a}</label>
        ))}
        <label className={`chip-check ${fullTime ? "chip-on" : ""}`}>
          <input type="checkbox" checked={fullTime} disabled={disabled}
            onChange={(e) => setFullTime(e.target.checked)} /> full-time only</label>
      </div>
      <label className="filter-wide">Countries (comma-separated)
        <input value={countries} disabled={disabled}
          onChange={(e) => setCountries(e.target.value)} /></label>
      <div className="filter-states">
        <span className="filter-toggle-label">States / DC checklist:</span>
        <div className="state-chip-grid">
          {US_STATE_NAMES.map((s) => (
            <label key={s} className={`chip-check ${states.includes(s) ? "chip-on" : ""}`}>
              <input type="checkbox" checked={states.includes(s)} disabled={disabled}
                onChange={() => setStates((cur) => toggle(cur, s))} />{s}</label>
          ))}
        </div>
      </div>
      <label className="filter-wide">Other places (metros / free text, comma-separated)
        <input value={customRegions} disabled={disabled}
          onChange={(e) => setCustomRegions(e.target.value)} /></label>
      <div className="preset-actions">
        <button className="actbtn" disabled={disabled} onClick={saveLocations}>save locations</button>
        {msg && <span className={msg.endsWith("saved") ? "actmsg" : "error-inline"}>{msg}</span>}
      </div>
      <div className="filter-note">
        Clear mismatches (onsite/hybrid outside these places, or a job requiring a
        language you don't speak) are hidden from Suggested Jobs; unclear postings
        stay visible, ranked lower.
      </div>
    </div>
  );
}

function RejectionInsights() {
  const [report, setReport] = useState<RejectionsReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    fetchRejectionsReport().then(setReport)
      .catch((e) => setErr((e as Error).message));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (err) return <div className="error-inline">rejections: {err}</div>;
  if (!report) return <div className="muted">loading rejection insights…</div>;
  return (
    <div className="rejection-insights">
      <div className="preset-actions">
        <span>{report.total_rejections} rejection{report.total_rejections === 1 ? "" : "s"} recorded</span>
        <button className="actbtn" onClick={load}>refresh</button>
      </div>
      {Object.keys(report.counts_by_reason).length > 0 && (
        <div className="domain-badges">
          {Object.entries(report.counts_by_reason).map(([code, n]) => (
            <span key={code} className="badge">{report.reason_labels[code] ?? code}: {n}</span>
          ))}
        </div>
      )}
      {report.suggestions.length === 0
        ? <div className="muted">No suggestions yet — reject a few jobs with a reason to build signal.</div>
        : (
          <ul className="rejection-suggestions">
            {report.suggestions.map((s, i) => (
              <li key={i} className={`rej-sugg rej-${s.priority}`}>
                <span className="rej-area">[{s.priority}] {s.area}</span> {s.suggestion}
              </li>
            ))}
          </ul>
        )}
      <div className="diag-row"><span>source</span><code>{report.source}</code></div>
    </div>
  );
}

const COMPANY_TARGET_GROUPS = [
  ["faang", "Major technology"],
  ["major_other", "Other priority companies"],
  ["sports_tech_companies", "Sports technology"],
  ["sports_teams_keywords", "Teams and leagues"],
] as const;

function CompanyWatchlistSettings({ controls, editable, onSaved }: {
  controls: JobProfileControls; editable: boolean; onSaved: () => void;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    setDraft(Object.fromEntries(COMPANY_TARGET_GROUPS.map(([key]) => [
      key, (controls.company_targets[key] ?? []).join("\n"),
    ])));
  }, [controls.company_targets]);
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchCompanyTargets(Object.fromEntries(
        COMPANY_TARGET_GROUPS.map(([key]) => [
          key,
          (draft[key] ?? "").split(/\r?\n|,/).map((s) => s.trim()).filter(Boolean),
        ]),
      ));
      setMsg("watchlist saved"); onSaved();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="settings-form company-watchlist">
      <p className="muted">
        Add any company you want the daily search and fit ranking to keep watching.
        Use one company per line; the groups only control how broadly roles are searched.
      </p>
      <div className="company-target-grid">
        {COMPANY_TARGET_GROUPS.map(([key, label]) => (
          <label key={key}>{label}
            <textarea className="settings-textarea" value={draft[key] ?? ""}
              disabled={!editable || busy}
              placeholder="One company per line"
              onChange={(e) => setDraft((current) => ({
                ...current, [key]: e.target.value,
              }))} />
          </label>
        ))}
      </div>
      <div className="preset-actions">
        <button className="actbtn" disabled={!editable || busy} onClick={save}>
          save company watchlist
        </button>
        {msg && <span className={msg.endsWith("saved") ? "actmsg" : "error-inline"}>{msg}</span>}
      </div>
    </div>
  );
}

function JobRetentionSettings({ controls, editable, onSaved }: {
  controls: JobProfileControls; editable: boolean; onSaved: () => void;
}) {
  const [days, setDays] = useState(String(controls.retention.rich_application_cache_days));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    setDays(String(controls.retention.rich_application_cache_days));
  }, [controls.retention.rich_application_cache_days]);
  async function save() {
    setBusy(true); setMsg(null);
    try {
      await updateJobSearchRetention(Number(days));
      setMsg("retention saved"); onSaved();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  const valid = Number.isInteger(Number(days)) && Number(days) >= 1 && Number(days) <= 365;
  return (
    <div className="settings-form retention-settings">
      <label>Rich application details (days)
        <input className="num-input" type="number" min="1" max="365"
          value={days} disabled={!editable || busy}
          onChange={(e) => setDays(e.target.value)} />
      </label>
      <p className="muted">
        The clock starts when an application is recorded. Only a note you explicitly
        mark as furthering the process refreshes it. The minimal outcome database is
        retained; this control never deletes rich files automatically.
      </p>
      <div className="preset-actions">
        <button className="actbtn" disabled={!editable || busy || !valid} onClick={save}>
          save retention window
        </button>
        {msg && <span className={msg.endsWith("saved") ? "actmsg" : "error-inline"}>{msg}</span>}
      </div>
    </div>
  );
}

function RelationshipRow({ row, editable, onChanged }: {
  row: JobRelationship; editable: boolean; onChanged: () => void;
}) {
  const [draft, setDraft] = useState({
    name: row.name, company: row.company, role_title: row.role_title ?? "",
    relationship_kind: row.relationship_kind ?? "known contact",
    linkedin_url: row.linkedin_url ?? "", notes: row.notes ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function save(active = row.active) {
    setBusy(true); setMsg(null);
    try {
      const result = await putJobRelationship(row.relationship_id, { ...draft, active });
      setMsg(result.status); onChanged();
    } catch (e) { setMsg("ERR " + (e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className={`relationship-row ${row.active ? "" : "relationship-archived"}`}>
      <div className="relationship-grid">
        <label>Name<input value={draft.name} disabled={!editable || busy}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label>Company<input value={draft.company} disabled={!editable || busy}
          onChange={(e) => setDraft({ ...draft, company: e.target.value })} /></label>
        <label>Role<input value={draft.role_title} disabled={!editable || busy}
          onChange={(e) => setDraft({ ...draft, role_title: e.target.value })} /></label>
        <label>Relationship<input value={draft.relationship_kind} disabled={!editable || busy}
          onChange={(e) => setDraft({ ...draft, relationship_kind: e.target.value })} /></label>
        <label>LinkedIn URL<input value={draft.linkedin_url} disabled={!editable || busy}
          onChange={(e) => setDraft({ ...draft, linkedin_url: e.target.value })} /></label>
      </div>
      <label>Private notes<textarea value={draft.notes} disabled={!editable || busy}
        onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
      <div className="preset-actions">
        <button className="actbtn" disabled={!editable || busy || !draft.name.trim() || !draft.company.trim()}
          onClick={() => save(row.active)}>save contact</button>
        <button className="clear" disabled={!editable || busy}
          onClick={() => save(!row.active)}>{row.active ? "archive" : "restore"}</button>
        <span className="muted small">private console · {row.active ? "active" : "archived"}</span>
        {msg && <span className={msg.startsWith("ERR") ? "error-inline" : "actmsg"}>{msg}</span>}
      </div>
    </div>
  );
}

function LinkedInRelationshipSettings({ editable }: { editable: boolean }) {
  const [rows, setRows] = useState<JobRelationship[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [draft, setDraft] = useState({ name: "", company: "", role_title: "", relationship_kind: "known contact", linkedin_url: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => {
    setMsg(null);
    fetchJobRelationships(showArchived ? undefined : true)
      .then((body) => setRows(body.relationships))
      .catch((e) => setMsg("ERR " + (e as Error).message));
  }, [showArchived]);
  useEffect(() => { load(); }, [load]);
  async function add() {
    setBusy(true); setMsg(null);
    try {
      await putJobRelationship(crypto.randomUUID(), { ...draft, active: true });
      setDraft({ name: "", company: "", role_title: "", relationship_kind: "known contact", linkedin_url: "", notes: "" });
      setMsg("contact saved"); load();
    } catch (e) { setMsg("ERR " + (e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="settings-form relationship-settings">
      <p className="muted">
        Add only people you actually know. These private records support exact-company,
        unsent follow-up drafts; the cockpit never searches LinkedIn or invents names.
      </p>
      <label className="capture-check"><input type="checkbox" checked={showArchived}
        onChange={(e) => setShowArchived(e.target.checked)} /> include archived contacts</label>
      {rows.map((row) => <RelationshipRow key={row.relationship_id} row={row}
        editable={editable} onChanged={load} />)}
      {!rows.length && !msg && <div className="muted">No operator-entered contacts yet.</div>}
      <div className="relationship-row relationship-new">
        <b>Add a known contact</b>
        <div className="relationship-grid">
          <label>Name<input value={draft.name} disabled={!editable || busy}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label>Company<input value={draft.company} disabled={!editable || busy}
            onChange={(e) => setDraft({ ...draft, company: e.target.value })} /></label>
          <label>Role<input value={draft.role_title} disabled={!editable || busy}
            onChange={(e) => setDraft({ ...draft, role_title: e.target.value })} /></label>
          <label>Relationship<input value={draft.relationship_kind} disabled={!editable || busy}
            onChange={(e) => setDraft({ ...draft, relationship_kind: e.target.value })} /></label>
          <label>LinkedIn URL<input value={draft.linkedin_url} disabled={!editable || busy}
            onChange={(e) => setDraft({ ...draft, linkedin_url: e.target.value })} /></label>
        </div>
        <label>Private notes<textarea value={draft.notes} disabled={!editable || busy}
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
        <button className="actbtn" disabled={!editable || busy || !draft.name.trim() || !draft.company.trim()}
          onClick={add}>add known contact</button>
      </div>
      {msg && <div className={msg.startsWith("ERR") ? "error" : "actmsg"}>{msg}</div>}
    </div>
  );
}

function QuestionLibraryRow({ row, categories, editable, onChanged }: {
  row: JobQuestionLibraryEntry;
  categories: JobProfileControls["job_categories"];
  editable: boolean;
  onChanged: () => void;
}) {
  const initialCategory = row.categories[0] ?? categories[0]?.id ?? "";
  const [category, setCategory] = useState(initialCategory);
  const existing = row.candidate_answers.find((answer) => answer.category_id === category);
  const [answer, setAnswer] = useState(existing?.answer ?? "");
  const [reviewing, setReviewing] = useState(false);
  const [topic, setTopic] = useState(`learned_${row.question_id.slice(0, 8)}`);
  const [covers, setCovers] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    setAnswer(row.candidate_answers.find((item) => item.category_id === category)?.answer ?? "");
    setReviewing(false);
  }, [category, row.candidate_answers]);
  async function saveCandidate() {
    setBusy(true); setMsg(null);
    try {
      const result = await putJobQuestionCandidate(row.question_id, category, answer.trim());
      setMsg(`${result.status} candidate — not used automatically`); onChanged();
    } catch (e) { setMsg("ERR " + (e as Error).message); }
    finally { setBusy(false); }
  }
  async function saveStanding() {
    setBusy(true); setMsg(null);
    try {
      await updateStandingAnswer({
        topic: topic.trim(), question: row.question, answer: answer.trim(),
        covers: covers.split(/\r?\n|,/).map((value) => value.trim()).filter(Boolean),
      });
      setReviewing(false); setMsg("standing answer saved after explicit review"); onChanged();
    } catch (e) { setMsg("ERR " + (e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="question-library-row">
      <div><b>{row.question}</b></div>
      <div className="muted small">seen {row.occurrence_count} time(s) · {row.categories.join(", ") || "uncategorized"}</div>
      <div className="question-answer-grid">
        <label>Job type<select value={category} disabled={!editable || busy}
          onChange={(e) => setCategory(e.target.value)}>
          {categories.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
        </select></label>
        <label>Candidate answer<textarea value={answer} disabled={!editable || busy}
          placeholder="Saved for this job type only; never auto-used"
          onChange={(e) => setAnswer(e.target.value)} /></label>
      </div>
      <div className="preset-actions">
        <button className="actbtn" disabled={!editable || busy || !category || !answer.trim()}
          onClick={saveCandidate}>save candidate only</button>
        <button className="clear" disabled={!editable || busy || !answer.trim()}
          onClick={() => setReviewing(true)}>review for Standing Answers</button>
      </div>
      {reviewing && (
        <div className="standing-review">
          <b>Explicit Standing Answer review</b>
          <p className="muted small">Saving here can affect future packets. Review the answer and add covers yourself; none are inferred.</p>
          <label>Topic<input value={topic} disabled={busy}
            onChange={(e) => setTopic(e.target.value)} /></label>
          <label>Question<input value={row.question} readOnly /></label>
          <label>Answer<textarea value={answer} disabled={busy}
            onChange={(e) => setAnswer(e.target.value)} /></label>
          <label>Covered question phrases (one per line)<textarea value={covers} disabled={busy}
            onChange={(e) => setCovers(e.target.value)} /></label>
          <div className="preset-actions">
            <button className="actbtn" disabled={busy || !topic.trim() || !answer.trim()}
              onClick={saveStanding}>save as Standing Answer</button>
            <button className="clear" disabled={busy} onClick={() => setReviewing(false)}>cancel</button>
          </div>
        </div>
      )}
      {msg && <div className={msg.startsWith("ERR") ? "error" : "actmsg"}>{msg}</div>}
    </div>
  );
}

function QuestionLibrarySettings({ controls, editable, onSaved }: {
  controls: JobProfileControls; editable: boolean; onSaved: () => void;
}) {
  const [rows, setRows] = useState<JobQuestionLibraryEntry[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => {
    setMsg(null);
    fetchJobQuestionLibrary().then((body) => setRows(body.questions))
      .catch((e) => setMsg("ERR " + (e as Error).message));
  }, []);
  useEffect(() => { load(); }, [load]);
  function changed() { load(); onSaved(); }
  return (
    <div className="settings-form question-library">
      <p className="muted">
        Add a non-sensitive portal question from its job card after saving the note.
        Candidate answers stay isolated by job type until you separately promote one.
      </p>
      {rows.map((row) => <QuestionLibraryRow key={row.question_id} row={row}
        categories={controls.job_categories} editable={editable} onChanged={changed} />)}
      {!rows.length && !msg && <div className="muted">No reusable application questions yet.</div>}
      {msg && <div className="error">{msg}</div>}
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
      <JobFilterSettings controls={controls} editable={editable} onSaved={onSaved} />
      <h3>Company Watchlist</h3>
      <CompanyWatchlistSettings controls={controls} editable={editable} onSaved={onSaved} />
      <h3>Application Retention</h3>
      <JobRetentionSettings controls={controls} editable={editable} onSaved={onSaved} />
      <h3>Known LinkedIn Relationships</h3>
      <LinkedInRelationshipSettings editable={editable} />
      <h3>Application Question Library</h3>
      <QuestionLibrarySettings controls={controls} editable={editable} onSaved={onSaved} />
      <h3>Role Focus</h3>
      <div className="preset-category-list">
        {controls.job_categories.map((category) => (
          <CategorySettingRow key={category.id} category={category}
            editable={editable} onSaved={onSaved} />
        ))}
      </div>
      <h3>Rejections & weaknesses</h3>
      <RejectionInsights />
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
          <div className="muted small">Kanban Boards, job search, profile defaults, and runtime APIs</div>
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
  const [furthersProcess, setFurthersProcess] = useState(false);
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteMsg, setNoteMsg] = useState<string | null>(null);
  const [savedPortalQuestion, setSavedPortalQuestion] = useState<string | null>(null);
  const [questionBusy, setQuestionBusy] = useState(false);
  const [questionMsg, setQuestionMsg] = useState<string | null>(null);
  const [outreach, setOutreach] = useState<JobOutreach | null>(null);
  const [outreachBusy, setOutreachBusy] = useState(false);
  const [outreachMsg, setOutreachMsg] = useState<string | null>(null);
  useEffect(() => {
    setSavedPortalQuestion(null); setQuestionMsg(null);
    setOutreach(null); setOutreachMsg(null);
  }, [progress.card_id]);
  async function saveNote() {
    const text = noteText.trim();
    if (!text || !canAddJobNote) return;
    setNoteBusy(true); setNoteMsg(null);
    try {
      const result = await addDomainCardNote(
        progress.domain_id, progress.card_id, noteType, text,
        noteType.includes("email") ? "email" : "cockpit",
        furthersProcess,
      );
      setSavedPortalQuestion(noteType === "portal_question" ? text : null);
      setQuestionMsg(null);
      setNoteText("");
      setFurthersProcess(false);
      setNoteMsg(result.event ? "note saved · moved to Interviewing" : "note saved");
      onProgressChanged?.(result.progress);
    } catch (e) { setNoteMsg("ERR " + (e as Error).message); }
    finally { setNoteBusy(false); }
  }
  async function addSavedQuestion() {
    if (!savedPortalQuestion) return;
    setQuestionBusy(true); setQuestionMsg(null);
    try {
      const result = await captureJobQuestion(progress.card_id, savedPortalQuestion);
      setQuestionMsg(`${result.status} in question library`);
      setSavedPortalQuestion(null);
    } catch (e) {
      setQuestionMsg("ERR Question was not added: " + (e as Error).message);
    } finally { setQuestionBusy(false); }
  }
  async function loadOutreach() {
    setOutreachBusy(true); setOutreachMsg(null);
    try { setOutreach(await fetchJobOutreach(progress.card_id)); }
    catch (e) { setOutreachMsg("ERR " + (e as Error).message); }
    finally { setOutreachBusy(false); }
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
              ? "read the resume, cover letter, answers, outreach, and checklist"
              : "materials are generated after you move the card to In Progress"}>
            review packet
          </button>
        )}
        <button className="actbtn"
          onClick={() => onOpenChat?.(progress.chat_prompt, conversationId)}
          disabled={!onOpenChat || !progress.chat_prompt}>
          {progress.domain_id === "job_application"
            ? "work page-by-page in chat" : "open in chat"}
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
            <label className="capture-check process-furthering-check">
              <input type="checkbox" checked={furthersProcess}
                disabled={!canAddJobNote || noteBusy}
                onChange={(e) => setFurthersProcess(e.target.checked)} />
              This communication furthers the process — refresh the retention window.
            </label>
            <div className="note-actions">
              <button className="actbtn" disabled={!canAddJobNote || noteBusy || !noteText.trim()}
                onClick={saveNote}>{noteBusy ? "saving..." : "save note"}</button>
              {noteMsg && <span className={noteMsg.startsWith("ERR") ? "error-inline" : "muted small"}>{noteMsg}</span>}
            </div>
            {savedPortalQuestion && (
              <div className="explicit-question-capture">
                <p className="muted small">
                  The portal note is saved. Adding it to the reusable library is a
                  separate private write and rejects protected/sensitive questions.
                </p>
                <button className="actbtn" disabled={questionBusy}
                  onClick={addSavedQuestion}>
                  {questionBusy ? "adding..." : "Add this non-sensitive question to library"}
                </button>
              </div>
            )}
            {questionMsg && <div className={questionMsg.startsWith("ERR") ? "error" : "actmsg"}>{questionMsg}</div>}
          </div>
        </div>
      )}
      {progress.domain_id === "job_application" && (
        <div className="job-outreach-panel">
          <div className="domain-section-head">
            <div>
              <h3>LinkedIn Follow-up</h3>
              <div className="muted small">exact-company matches · private · draft only · never sent</div>
            </div>
            <button className="actbtn" disabled={outreachBusy} onClick={loadOutreach}>
              {outreachBusy ? "checking..." : outreach ? "refresh drafts" : "check known contacts"}
            </button>
          </div>
          {outreachMsg && <div className="error">{outreachMsg}</div>}
          {outreach && (
            <div className="outreach-results">
              {outreach.known_contacts.length === 0 ? (
                <div className="muted">No operator-entered contact exactly matches {outreach.company}.</div>
              ) : outreach.known_contacts.map((contact) => (
                <div className="outreach-contact" key={contact.relationship_id}>
                  <b>{contact.name}</b>
                  <span>{contact.role_title || contact.relationship_kind || "known contact"} · {contact.company}</span>
                </div>
              ))}
              {outreach.drafts.map((draft) => (
                <div className="outreach-draft" key={`${draft.relationship_id}:${draft.kind}`}>
                  <div><Badge value="unsent draft" /> <b>{draft.kind}</b></div>
                  {draft.subject && <div><span className="muted">Subject:</span> {draft.subject}</div>}
                  <pre>{draft.body}</pre>
                </div>
              ))}
              <div className="recommended-searches">
                <b>People to look for on LinkedIn</b>
                <p className="muted small">Search phrases only; no named people are invented or looked up.</p>
                <ChipList values={outreach.recommended_role_searches} />
              </div>
            </div>
          )}
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
      `Confirm that you already submitted the ${company} application on its external `
      + "portal. This cockpit does not submit it. Continue to mark it applied, move "
      + "the card to Completed, and email/store the record?")) return;
    setBusy("submit"); setMsg(null);
    try {
      const result = await submitJobApplication(spec.domain_id, id);
      setSubmitted(result.side_effect ?? {});
      const email = (result.side_effect as {
        email?: { status?: string; detail?: string; error?: string; to?: string };
      } | null)?.email;
      const emailNote = email?.status === "sent" ? ` to ${email?.to}`
        : (email?.detail || email?.error) ? ` (${email.detail ?? email.error})` : "";
      setMsg(`external submission recorded — card moved to Completed; email record: ${email?.status ?? "unknown"}${emailNote}`);
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
                <h3>After you submit on the employer&apos;s site</h3>
                <div className="note-actions">
                  <button className="actbtn packet-submit" disabled={!canSubmit}
                    onClick={() => void approveAndSubmit()}
                    title={alreadyApplied ? "already submitted"
                      : validation?.ok ? "validate, mark applied, move to Completed, email the record"
                      : "fix the failed validation checks first"}>
                    {busy === "submit" ? "recording..."
                      : alreadyApplied || submitted ? "external submission recorded ✓"
                      : "I submitted externally — record it"}
                  </button>
                  <span className="muted small">
                    {alreadyApplied
                      ? "this application is already marked applied"
                      : validation?.ok
                        ? "does not submit the employer portal; it validates, marks applied, moves the card to Completed, and emails/stores the record"
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

function ResearchImplementationHandoff({ spec, card, repos, onOpenChat }: {
  spec: DomainSpec;
  card: DomainCard;
  repos: RegisteredRepository[];
  onOpenChat?: (
    prompt: string, conversationId?: string, storyTs?: string,
    target?: string, repoId?: string,
  ) => void;
}) {
  const [repoId, setRepoId] = useState(repos[0]?.repo_id ?? "");
  useEffect(() => {
    if (!repos.some((repo) => repo.repo_id === repoId)) {
      setRepoId(repos[0]?.repo_id ?? "");
    }
  }, [repos, repoId]);
  const status = valText(card.analysis_status) || "not_analyzed";
  function openHandoff() {
    if (!repoId || !onOpenChat) return;
    const prompt = [
      `Evaluate this ${spec.card_component} for registered repo ${repoId}.`,
      "Use only the source-backed card record below plus live read-only inspection of that registered repo.",
      "Separate source facts from local-model analysis. Verify every dependency, API, license, benchmark, and code link before relying on it.",
      "Prepare a bounded implementation packet with: fit for this repo, pros/cons, prerequisites, smallest experiment, files likely affected, validation/KPIs, risks, rollback, and explicit unknowns.",
      "This session is read-only. Do not edit the repo, create a mission, or claim implementation. Geoff can explicitly track/approve the next step after reviewing the packet.",
      "",
      "RESEARCH CARD",
      JSON.stringify(card, null, 2),
    ].join("\n");
    onOpenChat(
      prompt,
      `research:${spec.domain_id}:${cardId(card)}:${repoId}`,
      undefined,
      "agent:codex_agent",
      repoId,
    );
  }
  return (
    <section className="research-handoff">
      <div className="domain-section-head">
        <div>
          <h3>Use this in one of our repos</h3>
          <p className="muted small">
            Analysis status: <b>{status}</b>. Pros, cons, and implementation notes
            are local-model analysis; links and paper/repo metadata are source-derived.
          </p>
        </div>
      </div>
      <div className="research-handoff-controls">
        <select className="select" value={repoId}
          aria-label="Registered repository for research implementation handoff"
          onChange={(e) => setRepoId(e.target.value)}>
          {repos.length === 0 && <option value="">No registered repos</option>}
          {repos.map((repo) => (
            <option key={repo.repo_id} value={repo.repo_id}>{repo.repo_id}</option>
          ))}
        </select>
        <button className="actbtn" disabled={!repoId || !onOpenChat}
          onClick={openHandoff}>Prepare implementation handoff</button>
      </div>
      {repos.length === 0 && (
        <div className="muted small">
          Register a repo first with <code>uv run cc onboard repo --path &lt;path&gt;</code>.
        </div>
      )}
    </section>
  );
}

function DomainDrawer({
  spec, card, actions, moveTargets = [], onMove, onChanged, onClose, onOpenChat, onOpenPacket,
  registeredRepos = [],
  refreshTick = 0,
}: {
  spec: DomainSpec; card: DomainCard; actions?: DomainActions;
  moveTargets?: string[]; onMove?: (status: string) => void;
  onChanged: (committedCard?: DomainCard) => void; onClose: () => void;
  onOpenChat?: (
    prompt: string, conversationId?: string, storyTs?: string,
    target?: string, repoId?: string,
  ) => void;
  onOpenPacket?: () => void;
  registeredRepos?: RegisteredRepository[];
  refreshTick?: number;
}) {
  const [detail, setDetail] = useState<DomainCardDetail | null>(null);
  const [progress, setProgress] = useState<DomainCardProgress | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [progressErr, setProgressErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [mobile, setMobile] = useState(false);
  const [editingGrandTodo, setEditingGrandTodo] = useState(false);
  const [grandTodoText, setGrandTodoText] = useState("");
  const [grandTodoEditBaseSha, setGrandTodoEditBaseSha] = useState("");
  const [grandTodoIgnoredBaseSha, setGrandTodoIgnoredBaseSha] = useState("");
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

  // A move/edit response is already the committed server projection. Keep an
  // open drawer aligned with that card instead of letting its earlier detail
  // fetch shadow the newly committed status or fields.
  useEffect(() => {
    setDetail((current) => (
      current && cardId(current.card) === id
        ? { ...current, card: { ...current.card, ...card } }
        : current
    ));
  }, [card, id]);

  const activeCard = detail?.card ?? card;
  const incomingGrandTodoSha = valText(card.source_sha256);
  useEffect(() => {
    if (
      !isGrandTodoDomain(spec.domain_id)
      || editingGrandTodo
    ) return;
    if (grandTodoIgnoredBaseSha && incomingGrandTodoSha === grandTodoIgnoredBaseSha) {
      return;
    }
    if (grandTodoIgnoredBaseSha) setGrandTodoIgnoredBaseSha("");
    setDetail((current) => current ? { ...current, card } : current);
  }, [
    spec.domain_id, card, editingGrandTodo,
    grandTodoIgnoredBaseSha, incomingGrandTodoSha,
  ]);
  useEffect(() => {
    if (
      editingGrandTodo
      && grandTodoEditBaseSha
      && incomingGrandTodoSha
      && incomingGrandTodoSha !== grandTodoEditBaseSha
    ) {
      setMsg(
        "Canonical source changed while you were editing. "
        + "Cancel and reopen to merge the latest revision; Save will not overwrite it.",
      );
    }
  }, [editingGrandTodo, grandTodoEditBaseSha, incomingGrandTodoSha]);
  const fields = detail?.drawer_fields ?? spec.drawer_fields;
  // Book lane actions must always use the exact card-scoped move endpoint.
  // Generic action verbs address global mission/todo titles and therefore do
  // not belong in a book drawer.
  const verbs = spec.domain_id === "book"
    ? []
    : (actions?.allowed_actions ?? []).filter((v) => !WALL_VERBS.has(v));
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
  const isResearchCard = (
    spec.card_component === "paper" || spec.card_component === "repo"
  );
  const hasCompleteResearchAnalysis = (
    isResearchCard && researchAnalysisComplete(
      activeCard, registeredRepos.map((repo) => repo.repo_id))
  );
  const researchAnalysisStatus = valText(activeCard.analysis_status)
    || "not_analyzed";
  const canEditGrandTodo = (
    isGrandTodoDomain(spec.domain_id)
    && activeCard.source_kind === "tracked_item"
    && actions?.dispatch_enabled
  );
  async function saveGrandTodo() {
    setBusy(true); setMsg(null);
    try {
      const result = await updateGrandTodoCard(
        spec.domain_id,
        id,
        grandTodoText,
        grandTodoEditBaseSha,
      );
      setDetail((current) => current ? { ...current, card: result.card } : current);
      setGrandTodoIgnoredBaseSha(grandTodoEditBaseSha);
      setEditingGrandTodo(false);
      setGrandTodoEditBaseSha("");
      setMsg("Saved to the canonical GRAND TODO and synchronized.");
      onChanged();
    } catch (e) {
      setMsg("ERR " + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }
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
      {spec.domain_id === "book" && (
        <>
          <BookDrawerControls
            card={activeCard}
            writable={!!actions?.dispatch_enabled}
            onCardChanged={(nextCard, message) => {
              setDetail((current) => current
                ? { ...current, card: nextCard }
                : { domain_id: "book", card: nextCard, drawer_fields: fields });
              setMsg(message);
              onChanged(nextCard);
            }}
            onRestore={valText(activeCard.status) === "Archived"
              ? () => {
                setDetail(null);
                onMove?.("To read");
              }
              : undefined}
          />
          {msg && <div className="actmsg">{msg}</div>}
        </>
      )}
      {canEditGrandTodo && (
        <div className="grand-todo-editor">
          {!editingGrandTodo ? (
            <button className="actbtn" disabled={busy} onClick={() => {
              setGrandTodoText(valText(activeCard.description));
              setGrandTodoEditBaseSha(valText(activeCard.source_sha256));
              setGrandTodoIgnoredBaseSha("");
              setMsg(null);
              setEditingGrandTodo(true);
            }}>Edit canonical task</button>
          ) : (
            <>
              <textarea className="packet-edit" value={grandTodoText}
                aria-label="Canonical GRAND TODO task Markdown"
                onChange={(e) => setGrandTodoText(e.target.value)} />
              <div className="actions">
                <button className="actbtn" disabled={busy || !grandTodoText.trim()}
                  onClick={() => void saveGrandTodo()}>Save and sync</button>
                <button className="actbtn" disabled={busy}
                  onClick={() => {
                    setEditingGrandTodo(false);
                    setGrandTodoEditBaseSha("");
                  }}>Cancel</button>
              </div>
            </>
          )}
          {msg && <div className="actmsg">{msg}</div>}
        </div>
      )}
      {isResearchCard && !hasCompleteResearchAnalysis && (
        <div className="research-analysis-notice" role="status">
          <b>{researchAnalysisStatus === "failed"
            ? "Detailed KPI analysis failed"
            : researchAnalysisStatus === "unavailable"
              ? "Detailed KPI analysis is unavailable"
              : researchAnalysisStatus === "complete"
                ? "KPI analysis upgrade is pending"
                : "Detailed KPI analysis is pending"}</b>
          <span>
            The source title, abstract/description, authorship, and links below are
            available now. {researchAnalysisStatus === "failed"
              ? "The last attempt did not pass the strict contract; fix the reported model issue and choose Refresh both now to retry."
              : researchAnalysisStatus === "unavailable"
                ? "The local analysis service was unavailable; restore it and choose Refresh both now."
                : "Pros, cons, use cases, priority, scores, and registered-folder fit will appear only after the strict contract passes."}
          </span>
          {valText(activeCard.analysis_error_code) && (
            <small>Last attempt: {titleToken(valText(activeCard.analysis_error_code))}</small>
          )}
        </div>
      )}
      {isResearchCard && hasCompleteResearchAnalysis && (
        <div className="research-analysis-notice research-analysis-complete" role="status">
          <b>Complete KPI analysis</b>
          <span>
            Scores and recommendations are local-model judgments grounded in the
            source record and registered project folders; source facts remain separate.
          </span>
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
      {(spec.card_component === "paper" || spec.card_component === "repo") && (
        <ResearchImplementationHandoff spec={spec} card={activeCard}
          repos={registeredRepos} onOpenChat={onOpenChat} />
      )}
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
function PriorityStrip({
  cards, query, priority, onQuery, onPriority, onOpenView,
}: {
  cards: DomainCard[];
  query: string;
  priority: string;
  onQuery: (value: string) => void;
  onPriority: (value: string) => void;
  onOpenView: (view: View) => void;
}) {
  const counts = ["P1", "P2", "P3"].map((level) => ({
    level,
    count: cards.filter((card) => cardPriority(card) === level).length,
  }));
  return (
    <div className="filterbar priority-strip" aria-label="Priority board filters">
      <div className="priority-counts" aria-label="Priority counts">
        {counts.map(({ level, count }) => (
          <span className="priority-count-chip" key={level}>
            <b>{level}</b>{count}
          </span>
        ))}
      </div>
      <select className="select" value={priority}
        aria-label="Filter cards by priority"
        onChange={(e) => onPriority(e.target.value)}>
        <option value="">All</option>
        {["P1", "P2", "P3"].map((level) => (
          <option key={level} value={level}>{level}</option>
        ))}
      </select>
      <input className="search" type="search" placeholder="search cards…" value={query}
        aria-label="Search cards"
        onChange={(e) => onQuery(e.target.value)} />
      <button className="actbtn priority-work-map" type="button"
        onClick={() => onOpenView("work-map")}>
        Work Map
      </button>
      {(query || priority) && (
        <button className="clear" type="button"
          onClick={() => { onQuery(""); onPriority(""); }}>
          clear
        </button>
      )}
    </div>
  );
}

function DomainsView({ refreshKey, activeDomain, onActiveDomainChange, onOpenView, onOpenChat,
  chatHarnesses = null, registeredRepos = [], onDomainResult }: {
  refreshKey: string;
  activeDomain: string;
  onActiveDomainChange: (domainId: string) => void;
  onOpenView: (view: View) => void;
  onOpenChat?: (
    prompt: string, conversationId?: string, storyTs?: string,
    target?: string, repoId?: string,
  ) => void;
  chatHarnesses?: AgentHarnessOption[] | null;
  registeredRepos?: RegisteredRepository[];
  onDomainResult?: (
    specs: DomainSpec[], packs: Record<string, DomainCards>, errors: Record<string, string>,
  ) => void;
}) {
  const [domains, setDomains] = useState<DomainSpec[]>([]);
  const [cards, setCards] = useState<Record<string, DomainCards>>({});
  const [actions, setActions] = useState<Record<string, DomainActions>>({});
  const [domainErrs, setDomainErrs] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [qByDomain, setQByDomain] = useState<Record<string, string>>({});
  const [statusByDomain, setStatusByDomain] = useState<Record<string, string>>({});
  const [priorityByDomain, setPriorityByDomain] = useState<Record<string, string>>({});
  const [automationByDomain, setAutomationByDomain] = useState<Record<string, string>>({});
  const [topicByDomain, setTopicByDomain] = useState<Record<string, string>>({});
  const [bookFilters, setBookFilters] = useState<BookLibraryFilterState>(
    { ...EMPTY_BOOK_FILTERS });
  const [researchFiltersByDomain, setResearchFiltersByDomain] = useState<
    Record<string, ResearchFilters>
  >({});
  const [selfImprovementFilters, setSelfImprovementFilters] =
    useState<SelfImprovementFilters>({ ...EMPTY_SELF_IMPROVEMENT_FILTERS });
  const [selected, setSelected] = useState<{ spec: DomainSpec; card: DomainCard } | null>(null);
  const [dragged, setDragged] = useState<{ spec: DomainSpec; card: DomainCard } | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showJobPresets, setShowJobPresets] = useState(false);
  const [showPostComposer, setShowPostComposer] = useState(false);
  const [jobBoardMode, setJobBoardMode] = useState<JobBoardMode>("manual");
  const [packetFor, setPacketFor] = useState<{ spec: DomainSpec; card: DomainCard } | null>(null);
  const [drawerTick, setDrawerTick] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const body = await fetchDomains();
      const activeDomains = body.domains.filter((domain) => !domain.archived);
      setDomains(activeDomains);
      const cardPairs = await Promise.all(activeDomains.map(async (d) => {
        try { return [d.domain_id, await fetchDomainCards(d.domain_id), ""] as const; }
        catch (e) { return [d.domain_id, null, (e as Error).message] as const; }
      }));
      const actionPairs = await Promise.all(activeDomains.map(async (d) => {
        try { return [d.domain_id, await fetchDomainActions(d.domain_id)] as const; }
        catch { return [d.domain_id, { domain_id: d.domain_id, allowed_actions: [], dispatch_enabled: false }] as const; }
      }));
      const nextCards = Object.fromEntries(
        cardPairs.filter(([, pack]) => pack).map(([id, pack]) => [id, pack as DomainCards]));
      const nextErrors = Object.fromEntries(
        cardPairs.filter(([, , err]) => err).map(([id, , err]) => [id, err]));
      setCards(nextCards);
      setSelected((current) => {
        if (!current) return current;
        const refreshed = nextCards[current.spec.domain_id]?.cards.find(
          (card) => cardId(card) === cardId(current.card),
        );
        return refreshed ? { ...current, card: refreshed } : current;
      });
      setActions(Object.fromEntries(actionPairs));
      setDomainErrs(nextErrors);
      onDomainResult?.(activeDomains, nextCards, nextErrors);
    } catch (e) {
      setDomainErrs({ _registry: (e as Error).message });
    } finally { setLoading(false); }
  }, [onDomainResult]);

  const refreshDomain = useCallback(async (domainId: string) => {
    try {
      const pack = await fetchDomainCards(domainId);
      setCards((current) => ({ ...current, [domainId]: pack }));
      setDomainErrs((current) => {
        const next = { ...current };
        delete next[domainId];
        return next;
      });
      setSelected((current) => {
        if (!current || current.spec.domain_id !== domainId) return current;
        const refreshed = pack.cards.find(
          (card) => card.card_id === current.card.card_id,
        );
        return refreshed ? { ...current, card: refreshed } : current;
      });
      const spec = domains.find((domain) => domain.domain_id === domainId);
      if (spec) onDomainResult?.([spec], { [domainId]: pack }, {});
    } catch (e) {
      setDomainErrs((current) => ({
        ...current, [domainId]: (e as Error).message,
      }));
    }
  }, [domains, onDomainResult]);
  const applyCommittedDomainCard = useCallback((
    domainId: string,
    committedCard: DomainCard,
  ) => {
    const committedId = cardId(committedCard);
    setCards((current) => {
      const pack = current[domainId];
      if (!pack) return current;
      const exists = pack.cards.some((card) => cardId(card) === committedId);
      const nextCards = exists
        ? pack.cards.map((card) =>
          cardId(card) === committedId ? committedCard : card)
        : [...pack.cards, committedCard];
      return {
        ...current,
        [domainId]: { ...pack, cards: nextCards },
      };
    });
    setSelected((current) => (
      current
      && current.spec.domain_id === domainId
      && cardId(current.card) === committedId
        ? { ...current, card: committedCard }
        : current
    ));
  }, []);
  useEffect(() => {
    if (domains.length > 0) {
      onDomainResult?.(domains, cards, domainErrs);
    }
  }, [cards, domainErrs, domains, onDomainResult]);

  useEffect(() => { load(); }, [load, refreshKey]);
  useEffect(() => {
    if (!isGrandTodoDomain(activeDomain)) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      await refreshDomain(activeDomain);
      if (!cancelled) timer = window.setTimeout(() => { void poll(); }, 15000);
    };
    timer = window.setTimeout(() => { void poll(); }, 15000);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeDomain, refreshDomain]);
  useEffect(() => {
    const active = domains.find((domain) => domain.domain_id === activeDomain);
    if (
      !active
      || isGrandTodoDomain(active.domain_id)
      || active.source !== "board_store"
      || active.card_component !== "generic_task"
    ) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      await refreshDomain(active.domain_id);
      if (!cancelled) timer = window.setTimeout(() => { void poll(); }, 15000);
    };
    timer = window.setTimeout(() => { void poll(); }, 15000);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeDomain, domains, refreshDomain]);

  if (loading && domains.length === 0) return <div className="loading">...</div>;
  if (domainErrs._registry) return <div className="error">ERR {domainErrs._registry}</div>;
  const spec = domains.find((d) => d.domain_id === activeDomain) ?? domains[0];
  if (!spec) return <div className="empty">No domain registry entries.</div>;
  const pack = cards[spec.domain_id];
  const q = qByDomain[spec.domain_id] ?? "";
  const status = statusByDomain[spec.domain_id] ?? "";
  const priority = priorityByDomain[spec.domain_id] ?? "";
  const automationClass = automationByDomain[spec.domain_id] ?? "";
  const allCards = pack?.cards ?? [];
  const hasPriority = allCards.some((card) => Boolean(cardPriority(card)));
  const isJobDomain = spec.domain_id === "job_application";
  const isBookDomain = spec.domain_id === "book";
  const isResearchDomain = spec.card_component === "paper" || spec.card_component === "repo";
  const isSelfImprovementDomain = spec.domain_id === "self_improvement";
  const registeredProjectIds = registeredRepos.map((repo) => repo.repo_id);
  const researchFilters = researchFiltersByDomain[spec.domain_id]
    ?? EMPTY_RESEARCH_FILTERS;
  const selectedTopic = topicByDomain[spec.domain_id] ?? "";
  const configuredTopics = isResearchDomain && Array.isArray(spec.intake.parameters.review_topics)
    ? spec.intake.parameters.review_topics
    : [];
  const activeTopic = configuredTopics.includes(selectedTopic) ? selectedTopic : "";
  const researchTopics = configuredTopics.map((topic) => ({
    topic,
    count: allCards.filter((card) =>
      Array.isArray(card.review_topics) && card.review_topics.includes(topic)).length,
  }));
  const statuses = Array.from(new Set(allCards.map((c) => valText(c.status)).filter(Boolean))).sort();
  const automationValues = isJobDomain
    ? Array.from(new Set(allCards.map((c) => valText(c.automation_class)).filter(Boolean))).sort()
    : [];
  const baseShown = allCards.filter((card) =>
    (isBookDomain
      ? (!status || valText(card.status) === status)
        && bookMatchesLibraryFilters(card, q, bookFilters)
      : cardMatchesDomain(card, q, status))
    && (!isResearchDomain || researchCardMatchesFilters(
      card, researchFilters, registeredProjectIds))
    && (!activeTopic || (
      Array.isArray(card.review_topics) && card.review_topics.includes(activeTopic)
    ))
    && (!isSelfImprovementDomain
      || selfImprovementCardMatches(card, selfImprovementFilters))
    && (!priority || cardPriority(card) === priority));
  const unsortedShown = baseShown.filter((c) =>
    !automationClass || valText(c.automation_class) === automationClass);
  const shown = isBookDomain
    ? sortBooks(unsortedShown, bookFilters.sortBy, bookFilters.sortDirection)
    : unsortedShown;
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
    if (
      isGrandTodoDomain(spec.domain_id)
      && card.source_kind !== "tracked_item"
    ) return [];
    const status = valText(card.status);
    // one-step machine: the backend names the only legal next steps per lane
    // (jobs: found -> agent complete -> me complete, plus reject/undo)
    const allowed = pack?.transitions?.[status];
    if (allowed) return allowed;
    return boardColumns.filter((name) => name !== "Unstaged" && name !== status);
  };
  // After a queued prep, the card advances to Needs Geoff on the background
  // worker. Poll prep-status and refresh the board so it advances on screen
  // without a manual reload; stop once the queue is idle (or after ~30s).
  function pollPrepUntilIdle() {
    let ticks = 0;
    const timer = window.setInterval(async () => {
      ticks += 1;
      try {
        const st = await fetchPrepStatus();
        await refreshDomain("job_application");
        if ((!st.pending && !st.running) || ticks > 20) window.clearInterval(timer);
      } catch { window.clearInterval(timer); }
    }, 1500);
  }
  async function moveDomainCardTo(card: DomainCard, statusName: string) {
    if (!card || !canMove || statusName === "Unstaged") return;
    const id = cardId(card);
    const isJobs = spec.domain_id === "job_application";
    let reason: { reason_code?: string; reason_note?: string } | undefined;
    if (isJobs && statusName === "Rejected / Skip") {
      const menu = REJECT_REASONS.map((r, i) => `${i + 1}. ${r.label}`).join("\n");
      const raw = window.prompt(
        "Why reject this job? Enter a number — this feeds the rejection report "
        + "so the filters can be tuned:\n" + menu, String(REJECT_REASONS.length));
      if (raw === null) return;   // cancelled: leave the card where it is
      const picked = REJECT_REASONS[parseInt(raw.trim(), 10) - 1];
      const code = picked ? picked.code : "other";
      let note: string | undefined;
      if (code === "other" || code === "company") {
        note = window.prompt("Add a short note (optional):") ?? undefined;
      }
      reason = { reason_code: code, reason_note: note || undefined };
    }
    setToast(null);
    try {
      const result = await moveDomainCard(spec.domain_id, id, statusName, reason);
      if (!result.card) {
        throw new Error("move response omitted the committed card");
      }
      applyCommittedDomainCard(spec.domain_id, result.card);
      const sideEffect = result.side_effect;
      const actualStatus = valText(result.card?.status) || statusName;
      const op = sideEffect?.operation;
      if (op === "process_selected_queued") {
        setToast(`${result.card_id} -> ${actualStatus}; packet prep queued...`);
        pollPrepUntilIdle();
      } else if (op === "rejection_recorded") {
        setToast(`${result.card_id} rejected (${String(sideEffect?.reason_code ?? "other")}) - noted for the filter report`);
      } else {
        setToast(`${result.card_id} -> ${actualStatus}`);
      }
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
      setToast(`added ${r.moved_count} bot job${r.moved_count === 1 ? "" : "s"} to Selected by Geoff; packets preparing...`);
      await load();
      if (r.moved_count > 0) pollPrepUntilIdle();
    } catch (e) { setToast("ERR " + (e as Error).message); }
  }
  async function syncGrandTodo() {
    setToast("synchronizing canonical GRAND TODO...");
    try {
      const result = await syncGrandTodoSource(spec.domain_id);
      setToast(`GRAND TODO synchronized · ${result.counts.update ?? 0} updated · ${result.counts.conflict ?? 0} conflicts`);
      await refreshDomain(spec.domain_id);
    } catch (e) { setToast("ERR " + (e as Error).message); }
  }

  return (
    <>
      {hasPriority && (
        <PriorityStrip
          cards={allCards}
          query={q}
          priority={priority}
          onQuery={(value) => setQByDomain((current) => ({
            ...current, [spec.domain_id]: value,
          }))}
          onPriority={(value) => setPriorityByDomain((current) => ({
            ...current, [spec.domain_id]: value,
          }))}
          onOpenView={onOpenView}
        />
      )}
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
        {isGrandTodoDomain(spec.domain_id) && (
          <button className="actbtn" disabled={!domainActions?.dispatch_enabled}
            title={domainActions?.dispatch_enabled
              ? "Explicitly reconcile the canonical source into the board"
              : "GRAND TODO sync requires full-console write mode"}
            onClick={() => void syncGrandTodo()}>
            Sync canonical source
          </button>
        )}
        {spec.domain_id === "linkedin_post" && (
          <button className="actbtn" onClick={() => setShowPostComposer(true)}>
            + New post
          </button>
        )}
        {pack?.origin === "fixtures" && <span className="demo-badge">demo data</span>}
        {pack?.origin === "board_store" && <span className="live-badge">board store</span>}
        {pack?.origin === "ledger" && <span className="live-badge">ledger</span>}
        {pack?.source_sync && (
          <span className={pack.source_sync.state === "current" ? "live-badge" : "demo-badge"}>
            source {pack.source_sync.state.replace(/_/g, " ")}
          </span>
        )}
      </div>
      {isSelfImprovementDomain && (
        <SelfImprovementToolbar
          repositories={registeredRepos}
          allCards={allCards}
          shownCards={shown}
          query={q}
          status={status}
          statuses={statuses}
          filters={selfImprovementFilters}
          onQuery={(value) => setQByDomain((current) => ({
            ...current, [spec.domain_id]: value,
          }))}
          onStatus={(value) => setStatusByDomain((current) => ({
            ...current, [spec.domain_id]: value,
          }))}
          onFilters={setSelfImprovementFilters}
          onClear={() => {
            setQByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
            setStatusByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
            setPriorityByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
            setSelfImprovementFilters({ ...EMPTY_SELF_IMPROVEMENT_FILTERS });
          }}
        />
      )}
      {isResearchDomain
        ? <ResearchSetupPanel activeSource={spec.card_component as "paper" | "repo"}
            analysis={{
              paper: researchAnalysisCounts(
                cards.paper?.cards ?? [], registeredProjectIds),
              repo: researchAnalysisCounts(
                cards.repo?.cards ?? [], registeredProjectIds),
            }}
            onSaved={load} />
        : <BoardIntakePanel spec={spec} onSaved={load} />}
      {isResearchDomain && !!pack?.data_quality?.quarantined_empty_imports && (
        <div className="research-data-quality" role="status">
          <b>{pack.data_quality.quarantined_empty_imports} empty legacy import{
            pack.data_quality.quarantined_empty_imports === 1 ? "" : "s"
          } retained outside this board</b>
          <span>{pack.data_quality.reason} Nothing was deleted or fabricated.</span>
        </div>
      )}
      {isResearchDomain && (
        <div className="research-board-picker">
          <div>
            <span className="eyebrow">Topic boards</span>
            <b>{activeTopic || "All research"}</b>
          </div>
          <HorizontalScroller className="research-topic-tabs" ariaLabel="Research topic boards">
            <button className={`topic-board-tab ${!activeTopic ? "topic-board-tab-on" : ""}`}
              aria-pressed={!activeTopic}
              onClick={() => setTopicByDomain((current) => ({ ...current, [spec.domain_id]: "" }))}>
              All <span>{allCards.length}</span>
            </button>
            {researchTopics.map(({ topic, count }) => (
              <button key={topic}
                className={`topic-board-tab ${activeTopic === topic ? "topic-board-tab-on" : ""}`}
                aria-pressed={activeTopic === topic}
                onClick={() => setTopicByDomain((current) => ({ ...current, [spec.domain_id]: topic }))}>
                {topic} <span>{count}</span>
              </button>
            ))}
          </HorizontalScroller>
        </div>
      )}
      {isResearchDomain && (
        <ResearchFilterPanel cards={allCards}
          projectSuggestions={registeredProjectIds}
          value={researchFilters}
          onChange={(value) => setResearchFiltersByDomain((current) => ({
            ...current, [spec.domain_id]: value,
          }))} />
      )}
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
      {isBookDomain && (
        <>
          <BookLibraryFilters
            cards={allCards}
            query={q}
            status={status}
            statuses={statuses}
            filters={bookFilters}
            resultCount={visibleCards}
            onQuery={(value) => setQByDomain((current) => ({
              ...current, [spec.domain_id]: value,
            }))}
            onStatus={(value) => setStatusByDomain((current) => ({
              ...current, [spec.domain_id]: value,
            }))}
            onFilters={setBookFilters}
            onClear={() => {
              setQByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
              setStatusByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
              setPriorityByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
              setBookFilters({ ...EMPTY_BOOK_FILTERS, facets: {} });
            }}
          />
          <BookWorkbench
            cards={allCards}
            columns={configuredColumns}
            writable={canMove}
            onSaved={(message, committedCard) => {
              setToast(message);
              applyCommittedDomainCard("book", committedCard);
            }}
          />
        </>
      )}
      {toast && <div className={toast.startsWith("ERR") ? "error" : "actmsg"}>{toast}</div>}
      {!isBookDomain && !isSelfImprovementDomain && <div className="filterbar">
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
        {(q || status || priority || automationClass || researchFiltersActive(researchFilters)
          || (isJobDomain && jobBoardMode !== "manual")) && (
          <button className="clear" onClick={() => {
            setQByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
            setStatusByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
            setPriorityByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
            setAutomationByDomain((m) => ({ ...m, [spec.domain_id]: "" }));
            setResearchFiltersByDomain((m) => ({
              ...m, [spec.domain_id]: { ...EMPTY_RESEARCH_FILTERS },
            }));
            setJobBoardMode("manual");
          }}>clear</button>
        )}
      </div>}
      {domainErrs[spec.domain_id] ? <div className="error">ERR {domainErrs[spec.domain_id]}</div>
        : visibleCards === 0 && allCards.length > 0 ? (
          <div className="domain-empty">
            <div className="domain-empty-mark" />
            <h3>No cards match this view</h3>
            <p>{activeTopic
              ? `No ${spec.title.toLowerCase()} currently match “${activeTopic}” and these filters.`
              : "Try clearing the current search and status filters."}</p>
            <button className="actbtn" onClick={() => {
              setQByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
              setStatusByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
              setPriorityByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
              setAutomationByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
              setTopicByDomain((current) => ({ ...current, [spec.domain_id]: "" }));
              setResearchFiltersByDomain((current) => ({
                ...current, [spec.domain_id]: { ...EMPTY_RESEARCH_FILTERS },
              }));
              setBookFilters({ ...EMPTY_BOOK_FILTERS });
              setSelfImprovementFilters({ ...EMPTY_SELF_IMPROVEMENT_FILTERS });
            }}>Show all {spec.title.toLowerCase()}</button>
          </div>
        ) : visibleCards === 0 ? <DomainEmpty spec={spec} />
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
                                researchProjects={registeredProjectIds}
                                chatHarnesses={chatHarnesses}
                                canDrag={canMove} onDragStart={() => setDragged({ spec, card })}
                                moveTargets={moveTargetsFor(card)}
                                onMove={(target) => void moveDomainCardTo(card, target)}
                                onOpenPacket={isJobDomain && card.application_id
                                  ? () => setPacketFor({ spec, card })
                                  : undefined}
                                onOpenChat={onOpenChat
                                  ? (prompt, target) => onOpenChat(prompt, undefined, undefined, target)
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
                researchProjects={registeredProjectIds}
                chatHarnesses={chatHarnesses}
                canDrag={canMove} onDragStart={() => setDragged({ spec, card })}
                moveTargets={moveTargetsFor(card)}
                onMove={(target) => void moveDomainCardTo(card, target)}
                onOpenPacket={isJobDomain && card.application_id
                  ? () => setPacketFor({ spec, card })
                  : undefined}
                onOpenChat={onOpenChat
                  ? (prompt, target) => onOpenChat(prompt, undefined, undefined, target)
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
          onChanged={isGrandTodoDomain(selected.spec.domain_id)
            ? () => { void refreshDomain(selected.spec.domain_id); }
            : (committedCard) => {
              if (committedCard) {
                applyCommittedDomainCard(selected.spec.domain_id, committedCard);
              } else {
                void refreshDomain(selected.spec.domain_id);
              }
            }}
          refreshTick={drawerTick}
          onClose={() => setSelected(null)} onOpenChat={onOpenChat}
          registeredRepos={registeredRepos}
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
      {showPostComposer && (
        <LinkedInPostComposer
          onClose={() => setShowPostComposer(false)}
          onCreated={(card, warningCount) => {
            setShowPostComposer(false);
            setToast(
              `${cardId(card)} saved as Draft`
              + (warningCount ? ` - ${warningCount} preview note${warningCount === 1 ? "" : "s"}` : ""));
            void load();
          }} />
      )}
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

// Compact, inline "the conversation IS the mission journey" strip — shown inside
// a chat once its thread is tracked as a mission. Shows the live mission status
// and the last few governed events, so the journey is visible without leaving
// the conversation. Read-only; the full timeline stays in MissionDrawer.
function MissionProgressStrip({ missionId }: { missionId: string }) {
  const [detail, setDetail] = useState<MissionDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setDetail(null); setErr(null);
    fetchMission(missionId).then((d) => live && setDetail(d))
      .catch((e) => live && setErr((e as Error).message));
    return () => { live = false; };
  }, [missionId]);
  const mission = (detail?.mission ?? {}) as Record<string, unknown>;
  const status = String(mission.status ?? (detail ? "open" : "…"));
  const events = detail?.events ?? [];
  const recent = events.slice(-3);
  return (
    <div className="mission-strip" title="This conversation is tracked as a Ledger mission">
      <span className="usage-badge muted">mission {missionId} · {status}</span>
      {err && <span className="muted small">⚠ {err}</span>}
      {recent.map((ev, i) => (
        <span className="tag" key={i}>{ev.kind}</span>
      ))}
      {events.length > recent.length && (
        <span className="muted small">+{events.length - recent.length} more</span>
      )}
    </div>
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

// Roles ▾ — the task-category -> Assistant policy (configs/assistant-routing
// .yaml, preview-only by contract) joined with LIVE availability, so you can
// reevaluate which assistant owns which role and switch with one click.
// Picking is an explicit human action routed through the same assistant
// selector; nothing dispatches silently.
function AssistantRolesPanel({ onPick }: { onPick: (assistantId: string) => void }) {
  const [routing, setRouting] = useState<AssistantRoutingView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open || routing) return;
    fetchAssistantRouting().then(setRouting)
      .catch((e) => setError((e as Error).message));
  }, [open, routing]);
  return (
    <details className="roles-panel" open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary title="Which assistant is preferred for each kind of task — edit configs/assistant-routing.yaml to adjust; cc validate enforces it.">
        Roles ▾
      </summary>
      {error && <div className="cl err">roles unavailable: {error}</div>}
      {!routing && !error && open && <div className="muted small">loading…</div>}
      {routing && (
        <div className="roles-grid">
          {routing.categories.map((cat) => (
            <div className="roles-row" key={cat.category_id}>
              <div className="roles-cat">
                <b>{cat.category_id.replace(/_/g, " ")}</b>
                <span className="muted small"> · {cat.capability_profile}
                  {" · "}{cat.risk_ceiling}</span>
              </div>
              <div className="roles-cands">
                {cat.candidates.map((c) => (
                  <button key={c.assistant_id} className="editbtn roles-cand"
                    disabled={c.availability !== "available"}
                    title={c.unavailable_reason
                      ?? `preference ${c.preference} — switch this chat to ${c.display_name}`}
                    onClick={() => onPick(c.assistant_id)}>
                    <span className={`hopdot ${c.availability === "available" ? "ok" : "bad"}`} />
                    {c.preference}. {c.display_name}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <div className="muted small">
            Adjust in <code>{routing.config_path}</code> — preview-only policy;
            switching stays a human click.
          </div>
        </div>
      )}
    </details>
  );
}

// ---- chat (the console as a channel) --------------------------------------
type ChatThread = {
  id: string;
  title: string;
  updatedAt: string;
  target?: string;
  lastPrompt?: string;
  // Agent-session recovery metadata — local-only, deliberately never sent to
  // saveChatThread/GatewayCore's flight-recorder transcript (see WORKLOG.md
  // "Agent-session chat integration": agent sessions are a structurally
  // separate execution path and must not be conflated with GatewayCore's
  // chat history store). Present only on threads whose target is "agent:*".
  agentSessionId?: string;
  agentHarnessId?: string;
  agentRepoId?: string;
  agentMode?: string;
  agentPermissionProfile?: string;
  agentLastSeenSequence?: number;
  // Per-harness session slots: ONE conversation can hold a live Codex session
  // AND a live Claude session, and switching the assistant picker back and
  // forth resumes each harness's own session instead of abandoning it (the
  // single agentSessionId/agentHarnessId pair above is the legacy single-slot
  // form, still written for the ACTIVE harness for compatibility).
  agentSessions?: Record<string, {
    sessionId: string; repoId?: string; mode?: string;
  }>;
  // Set once the user elects "Track as mission" — the OPTIONAL governance
  // wrapper. Local-only; the mission itself lives in the Ledger (id `T-…`).
  missionId?: string;
};
const CHAT_THREADS_KEY = "agent-kanban-cockpit.chatThreads.v1";
const ACTIVE_THREAD_KEY = "agent-kanban-cockpit.activeThread.v1";

// Which execution lane a message goes to. A discriminated union, not a bare
// string: GatewayCore's /chat/completions tool-call loop and an agent
// session (Claude/Codex/Fake, via the host worker) are structurally
// separate systems — this makes "which one am I talking to" a single,
// exhaustively-checked switch instead of scattered string comparisons.
// Encoded as a plain string for the <select>'s value / localStorage, via
// encodeChatTarget/decodeChatTarget below.
type ChatTarget =
  | { kind: "gateway" }
  | { kind: "agent"; harnessId: string }
  | { kind: "external"; name: string };

function decodeChatTarget(raw: string): ChatTarget {
  if (!raw || raw === "GatewayCore") return { kind: "gateway" };
  if (raw.startsWith("agent:")) return { kind: "agent", harnessId: raw.slice("agent:".length) };
  return { kind: "external", name: raw };
}

function loadActiveThreadPointer(): { conversationId: string; target: string } {
  try {
    const raw = window.localStorage.getItem(ACTIVE_THREAD_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed.conversationId === "string" && typeof parsed.target === "string") {
      return parsed;
    }
  } catch { /* browser storage can be unavailable in private modes */ }
  return { conversationId: "app", target: "GatewayCore" };
}
function saveActiveThreadPointer(conversationId: string, target: string) {
  try {
    window.localStorage.setItem(ACTIVE_THREAD_KEY, JSON.stringify({ conversationId, target }));
  } catch { /* browser storage can be unavailable in private modes */ }
}

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

function ChatBubbleShell({ role, text, runtime, streaming = false, error = false,
  onRoute }: {
  role: "user" | "assistant";
  text: string;
  runtime: RuntimeTarget;
  streaming?: boolean;
  error?: boolean;
  onRoute?: (text: string) => void;
}) {
  const runtimeInfo = runtimeLabel(runtime);
  return (
    <div className={`chat-bubble chat-bubble-${role}${error ? " error chat-bubble-error" : ""}`}>
      <div className="chat-bubble-meta"><Badge value={runtimeInfo.label} /></div>
      <div>{error ? "⚠ " : ""}{text}
        {streaming ? <span className="agent-cursor">▌</span> : null}
      </div>
      {onRoute && text.trim() && (
        <button className="route-todos-link" onClick={() => onRoute(text)}>
          Route as TODOs
        </button>
      )}
    </div>
  );
}

function ChatActivity({ text, collapsedDetail, runtime }: {
  text: string;
  collapsedDetail?: string;
  runtime: RuntimeTarget;
}) {
  const runtimeInfo = runtimeLabel(runtime);
  return (
    <details className="agent-activity">
      <summary><Badge value={runtimeInfo.label} /> {text}</summary>
      {collapsedDetail && (
        <pre className="agent-activity-out">{collapsedDetail}</pre>
      )}
    </details>
  );
}

function ChatLine({ ev, onRoute }: {
  ev: ChatEvent;
  onRoute?: (text: string) => void;
}) {
  const described = describeChatEvent(ev);
  if (described.kind === "activity") {
    return <ChatActivity runtime="GatewayCore" text={described.text}
      collapsedDetail={described.collapsedDetail} />;
  }
  return <ChatBubbleShell runtime="GatewayCore" role={described.role}
    text={described.text} error={described.kind === "error"}
    onRoute={described.kind === "message" && described.role === "assistant"
      ? onRoute : undefined} />;
}

// ---- agent sessions (Claude Agent / Codex Agent / Fake) --------------------
// A structurally separate execution path from GatewayCore chat above — see
// api.ts's streamAgentEvents and WORKLOG.md "Agent-session chat integration".
// Never routed through streamChat/ChatLine; AgentTranscript coalesces the
// typed AgentEvent vocabulary into natural chat blocks (user/agent bubbles,
// collapsible activity, one usage chip) — tool activity is always rendered
// from a real typed event, never inferred from assistant prose.

function pendingApprovalsOf(events: AgentEvent[]) {
  const resolved = new Set(
    events.filter((e) => e.type === "approval_resolved")
      .map((e) => String(e.payload.approval_id)));
  return events.filter((e) =>
    e.type === "approval_required"
      // Board-policy ASK routes to the existing board confirm card/token wall;
      // it deliberately has no generic approval_id and must never render a
      // second approve button in the agent-session strip.
      && typeof e.payload.approval_id === "string"
      && !resolved.has(e.payload.approval_id));
}

// ---- natural transcript: coalesce the raw event stream into chat blocks ----
// The 2026-07-16 transcript rendered every assistant_delta as its own row
// (one word per line), usage as raw JSON, and no user turns at all. The event
// STREAM stays exactly as the worker persisted it; only presentation groups:
//   user_message                    -> right-aligned user bubble
//   assistant_delta*+assistant_message -> ONE agent bubble (message wins)
//   command/tool started..finished  -> one collapsible activity block
//   usage                           -> a single running summary chip (header)
//   session_idle                    -> dropped (the header already shows it)
type AgentBlock =
  | { kind: "user"; text: string; key: string }
  | { kind: "agent"; text: string; streaming: boolean; key: string }
  | { kind: "activity"; label: string; output: string[]; exit: string | null;
      done: boolean; key: string }
  | { kind: "marker"; text: string; tone: "info" | "err"; key: string };

interface AgentUsage { totalTokens: number | null; contextWindow: number | null }

function buildAgentTranscript(events: AgentEvent[]):
    { blocks: AgentBlock[]; usage: AgentUsage } {
  const blocks: AgentBlock[] = [];
  let usage: AgentUsage = { totalTokens: null, contextWindow: null };
  const openActivity = () =>
    [...blocks].reverse().find((b) => b.kind === "activity" && !b.done) as
      Extract<AgentBlock, { kind: "activity" }> | undefined;
  events.forEach((ev, i) => {
    const p = ev.payload ?? {};
    const key = String(ev.sequence ?? `i${i}`);
    const last = blocks[blocks.length - 1];
    switch (ev.type) {
      case "user_message":
        blocks.push({ kind: "user", text: String(p.text ?? ""), key });
        break;
      case "assistant_delta":
        if (last?.kind === "agent" && last.streaming) {
          last.text += String(p.text ?? "");
        } else {
          blocks.push({ kind: "agent", text: String(p.text ?? ""),
                        streaming: true, key });
        }
        break;
      case "assistant_message":
        // the authoritative complete text CLOSES the streaming bubble —
        // never render deltas AND the full message as separate rows
        if (last?.kind === "agent" && last.streaming) {
          last.text = String(p.text ?? "");
          last.streaming = false;
        } else {
          blocks.push({ kind: "agent", text: String(p.text ?? ""),
                        streaming: false, key });
        }
        break;
      case "command_started":
        blocks.push({ kind: "activity", label: `$ ${String(p.command ?? "")}`,
                      output: [], exit: null, done: false, key });
        break;
      case "tool_requested":
      case "tool_started":
        blocks.push({ kind: "activity",
                      label: `tool: ${String(p.name ?? p.action ?? "tool")}`,
                      output: [], exit: null, done: false, key });
        break;
      case "tool_output": {
        const open = openActivity();
        const text = String(p.output ?? p.text ?? "");
        if (open) open.output.push(text);
        else blocks.push({ kind: "activity", label: "output", output: [text],
                           exit: null, done: false, key });
        break;
      }
      case "command_finished": {
        const open = openActivity();
        const code = String(p.exit_code ?? p.code ?? "");
        if (open) { open.exit = code; open.done = true; }
        break;
      }
      case "tool_finished": {
        const open = openActivity();
        if (open) open.done = true;
        break;
      }
      case "file_changed":
        blocks.push({ kind: "marker", tone: "info",
                      text: `✎ ${String(p.path ?? "file changed")}`, key });
        break;
      case "usage": {
        const total = (p as Record<string, any>).total;
        usage = {
          totalTokens: typeof total?.total_tokens === "number"
            ? total.total_tokens : usage.totalTokens,
          contextWindow: typeof (p as Record<string, any>).context_window
            === "number" ? (p as Record<string, any>).context_window
            : usage.contextWindow,
        };
        break;
      }
      case "session_started":
        blocks.push({ kind: "marker", tone: "info", key,
                      text: `session started${p.resumed ? " (resumed)" : ""}`
                        + (p.mode ? ` · ${String(p.mode)}` : "") });
        break;
      case "session_idle": {
        // a short turn can end with deltas but no closing assistant_message
        // (observed live: Codex one-word replies) — idle closes the bubble
        const openAgent = [...blocks].reverse().find(
          (b) => b.kind === "agent" && b.streaming) as
          Extract<AgentBlock, { kind: "agent" }> | undefined;
        if (openAgent) openAgent.streaming = false;
        break;                       // header status already says idle
      }
      case "session_failed":
        blocks.push({ kind: "marker", tone: "err", key,
                      text: `session failed — ${String(p.reason ?? "")}` });
        break;
      case "session_closed":
        blocks.push({ kind: "marker", tone: "info", text: "session closed",
                      key });
        break;
      case "warning":
        blocks.push({ kind: "marker", tone: "err", key,
                      text: `⚠ ${String(p.message ?? p.detail ?? ev.type)}` });
        break;
      case "rate_limit": {
        // A rate_limit_event is pure TELEMETRY: the CLI emits one every turn
        // and it already feeds the header usage badge ("62% used"). It is NOT
        // a chat message. Surface a transcript row ONLY when the status
        // signals the request was actually DENIED/throttled — never for
        // informational fields like overage_status (account config; e.g.
        // "disabled" on a Max subscription is normal, and previously produced
        // the "⚠ rate limit allowed · resets <epoch>" banner every turn).
        const status = String(p.status ?? "").toLowerCase();
        const denied =
          /reject|block|exceed|throttl|denied|limit_reached|paused/.test(status);
        if (denied) {
          blocks.push({ kind: "marker", tone: "err", key,
                        text: `⚠ rate limited (${status}) — the runtime paused this turn` });
        }
        break;
      }
      case "approval_required":
      case "approval_resolved":
        break;                       // rendered by the approval strip below
      default: {
        const described = describeChatEvent({ type: ev.type });
        blocks.push({
          kind: "activity", label: described.text,
          output: described.collapsedDetail ? [described.collapsedDetail] : [],
          exit: null, done: true, key,
        });
      }
    }
  });
  return { blocks, usage };
}

function AgentTranscript({ events, runtime }: {
  events: AgentEvent[];
  runtime: RuntimeTarget;
}) {
  const { blocks } = buildAgentTranscript(events);
  return (
    <>
      {blocks.map((b) => {
        if (b.kind === "user") {
          return <ChatBubbleShell role="user" text={b.text} runtime={runtime}
            key={b.key} />;
        }
        if (b.kind === "agent") {
          return <ChatBubbleShell role="assistant" text={b.text} runtime={runtime}
            streaming={b.streaming} key={b.key} />;
        }
        if (b.kind === "activity") {
          return (
            <details className="agent-activity" key={b.key}>
              <summary>
                <Badge value={runtimeLabel(runtime).label} />{" "}
                {b.label}
                {b.exit !== null && ` · exit ${b.exit}`}
                {!b.done && " · running…"}
              </summary>
              {b.output.length > 0 && (
                <pre className="agent-activity-out">{b.output.join("")}</pre>
              )}
            </details>
          );
        }
        if (b.tone === "err") {
          return <ChatBubbleShell role="assistant" text={b.text} runtime={runtime}
            error key={b.key} />;
        }
        return <div className="agent-marker muted small"
          key={b.key}>{b.text}</div>;
      })}
    </>
  );
}


// A render error anywhere below must SHOW its message, never blank the whole
// chat surface (2026-07-16: an unrenderable model-catalog payload unmounted
// the entire panel with no visible error). React only supports catching
// render errors in a class component.
class PanelErrorBoundary extends Component<
  { label: string; children: ReactNode },
  { error: Error | null }
> {
  constructor(props: { label: string; children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="error">
          {this.props.label} crashed while rendering: {this.state.error.message}
          <button className="editbtn" style={{ marginLeft: 10 }}
            onClick={() => this.setState({ error: null })}>retry</button>
        </div>
      );
    }
    return this.props.children;
  }
}

// The reserved Home-workspace context id (mirrors the backend
// home_workspace.HOME_WORKSPACE_ID). Selecting it starts a READ-ONLY sandbox
// over the user's home dir — no repo registration, credential paths denied.
const HOME_WORKSPACE_ID = "home_workspace";

/** Accessible dropdown for secondary chat controls. Opens on hover (desktop
 *  pointer), on keyboard focus-within (Tab reaches the trigger), AND on
 *  click/tap (touch — no hover there). Per the plan's a11y rule: NOT
 *  hover-only. Closes on outside click or Escape once click-opened. The
 *  hover/focus paths are pure CSS (.popover:hover / :focus-within); `open`
 *  only drives the tap path so touch users aren't stuck. */
function Popover({ label, title, align = "right", children }: {
  label: ReactNode;
  title?: string;
  align?: "left" | "right";
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div className={`popover ${open ? "popover-open" : ""}`} ref={ref}>
      <button type="button" className="popover-trigger clear" title={title}
        aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen((v) => !v)}>
        {label}
      </button>
      <div className={`popover-menu popover-${align}`} role="menu"
        onClick={() => setOpen(false)}>
        {children}
      </div>
    </div>
  );
}

const _RESOURCE_KINDS = ["work_item", "board_card", "capture", "packet", "url",
  "conversation_excerpt"];

function _attachId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  return c?.randomUUID ? c.randomUUID() : `att-${Date.now()}-${Math.round(Math.random() * 1e6)}`;
}

/** Composer attach menu — add a repo file/image by PATH (resolved + secret-checked
 *  on the host at send time) or a typed reference by id. No raw content is inlined;
 *  the agent reads referenced files with its own tools. */
function AttachMenu({ onAdd, contextLabel }: {
  onAdd: (a: AttachmentReq) => void; contextLabel: string;
}) {
  const [path, setPath] = useState("");
  const [resKind, setResKind] = useState("work_item");
  const [resId, setResId] = useState("");
  return (
    <Popover label="+ Attach" align="left"
      title="Attach a repo file or a typed reference">
      <div className="attach-menu">
        <div className="attach-row">
          <span className="muted small">repo file / image — path in {contextLabel}</span>
          <input className="select" placeholder="src/app.py" value={path}
            onChange={(e) => setPath(e.target.value)} />
          <button type="button" className="editbtn" disabled={!path.trim()}
            onClick={() => {
              onAdd({ attachment_id: _attachId(), kind: "file",
                rel_path: path.trim(), display_name: path.trim() });
              setPath("");
            }}>Add file</button>
        </div>
        <div className="attach-row">
          <span className="muted small">typed reference — by id/url</span>
          <select className="select" value={resKind}
            onChange={(e) => setResKind(e.target.value)}>
            {_RESOURCE_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <input className="select" placeholder="W-123 / https://…" value={resId}
            onChange={(e) => setResId(e.target.value)} />
          <button type="button" className="editbtn" disabled={!resId.trim()}
            onClick={() => {
              onAdd({ attachment_id: _attachId(), kind: resKind,
                resource_id: resId.trim(), display_name: resId.trim() });
              setResId("");
            }}>Add reference</button>
        </div>
        <div className="muted small">
          Files resolve against the current context; secret/credential paths are
          refused and blocked attachments are shown, never dropped.
        </div>
      </div>
    </Popover>
  );
}

/** Board-format confirm-card. A STRUCTURED column edit (no browser YAML): the
 *  server computes before/after + validates; a read-only PREVIEW always works,
 *  and Apply is gated behind the §8 proposal-bound token (disabled by default —
 *  needs the signing secret + operator set on the server). */
function BoardFormatCard({ onClose }: { onClose: () => void }) {
  const [boards, setBoards] = useState<BoardFormatTarget[]>([]);
  const [domainId, setDomainId] = useState("");
  const [columnsText, setColumnsText] = useState("");
  const [plan, setPlan] = useState<BoardFormatPlan | null>(null);
  const [operator, setOperator] = useState("");
  const [stage, setStage] = useState<"input" | "preview" | "applied">("input");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchBoardFormatTargets()
      .then((r) => setBoards(r.boards))
      .catch((e) => setError((e as Error).message));
  }, []);

  function pickBoard(id: string) {
    setDomainId(id);
    const b = boards.find((x) => x.domain_id === id);
    setColumnsText((b?.columns ?? []).join("\n"));
    setPlan(null);
    setStage("input");
  }

  const columns = columnsText.split("\n").map((c) => c.trim()).filter(Boolean);

  async function preview() {
    if (!domainId || columns.length === 0) return;
    setBusy(true); setError(null);
    try {
      const p = await planBoardFormat(domainId, columns,
        "board-format change reviewed in chat");
      setPlan(p);
      setStage("preview");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function apply() {
    if (!plan) return;
    if (!operator.trim()) {
      setError("enter your operator identity/token to approve");
      return;
    }
    setBusy(true); setError(null);
    try {
      const { approval_token } = await mintBoardApproval(plan.proposal_id, operator.trim());
      await applyBoardChange(plan.apply_payload, approval_token);
      setStage("applied");
    } catch (e) {
      // apply is gated: no secret / not an operator / flag off all surface here
      setError(`apply unavailable: ${(e as Error).message} — this is preview-only `
        + "unless the server has the signing secret + operator set + apply flag.");
    } finally { setBusy(false); }
  }

  return (
    <div className="workitems-card">
      <div className="workitems-head">
        <b>Propose board update</b>
        <button type="button" className="attach-chip-x" aria-label="close"
          onClick={onClose}>×</button>
      </div>
      {error && <div className="cl err">⚠ {error}</div>}

      {stage !== "applied" && (
        <div className="workitems-body">
          <label className="chat-field">
            <span className="muted small">board</span>
            <select className="select" value={domainId}
              onChange={(e) => pickBoard(e.target.value)}>
              <option value="">(pick a board)</option>
              {boards.map((b) => (
                <option key={b.domain_id} value={b.domain_id}>{b.title}</option>
              ))}
            </select>
          </label>
          {domainId && (
            <label className="chat-field">
              <span className="muted small">columns (one per line — reorder/add/remove)</span>
              <textarea className="chat-composer-input" rows={5} value={columnsText}
                onChange={(e) => { setColumnsText(e.target.value); setPlan(null); }} />
            </label>
          )}
          {stage === "preview" && plan && (
            <div className="bfmt-diff">
              <div className="muted small">
                {plan.preview.validates
                  ? "Valid change — no changes applied yet (preview)."
                  : `⚠ Invalid: ${plan.preview.validation_error}`}
              </div>
              <div className="bfmt-cols">
                <div><b>Before</b><ol>{plan.before_columns.map((c) =>
                  <li key={c}>{c}</li>)}</ol></div>
                <div><b>After</b><ol>{plan.after_columns.map((c) =>
                  <li key={c} className={plan.diff.added.includes(c) ? "bfmt-added" : ""}>
                    {c}{plan.diff.added.includes(c) ? " +" : ""}</li>)}</ol></div>
              </div>
              {plan.diff.removed.length > 0 && (
                <div className="muted small">Removed: {plan.diff.removed.join(", ")}</div>)}
              {plan.preview.warnings.map((w, i) =>
                <div key={i} className="cl warn">⚠ {w}</div>)}
            </div>
          )}
          <div className="workitems-actions">
            {stage === "preview" && plan?.preview.validates && (
              <>
                <input className="select bfmt-operator" placeholder="operator token (to approve)"
                  value={operator} onChange={(e) => setOperator(e.target.value)} />
                <button type="button" className="actbtn capture-primary"
                  disabled={busy} onClick={() => void apply()}>
                  {busy ? "…" : "Apply reviewed change"}
                </button>
              </>
            )}
            <button type="button" className="clear" onClick={onClose}>Cancel</button>
            <button type="button" className="actbtn" disabled={busy || !domainId || columns.length === 0}
              onClick={() => void preview()}>
              {busy ? "…" : "Preview"}
            </button>
          </div>
        </div>
      )}

      {stage === "applied" && (
        <div className="workitems-body">
          <div className="workitems-ok">✓ Board update applied — reversible via its rollback receipt.</div>
          <button type="button" className="actbtn" onClick={onClose}>Return to chat</button>
        </div>
      )}
    </div>
  );
}

function AgentSessionPanel({ conversationId, harnessId, harnesses, repos, thread,
  onThreadChange, initialPrompt, initialRepoId, onHandoff }: {
  conversationId: string;
  harnessId: string;
  harnesses: AgentHarnessOption[] | null;
  repos: { repo_id: string; remote_url: string }[];
  thread: ChatThread | undefined;
  onThreadChange: (patch: Partial<ChatThread>) => void;
  initialPrompt?: string;   // e.g. a card's context, seeded from its runtime picker
  initialRepoId?: string;   // selected by a source-backed research handoff
  // Claude<->Codex protocol: an explicit HUMAN-clicked handoff to the other
  // agent runtime, same conversation (per-harness session slots resume each
  // side). Carries a prefilled context prompt; never fires on its own.
  onHandoff?: (otherHarnessId: string, text: string) => void;
}) {
  // THIS harness's session slot (per-harness map, legacy single-slot fallback)
  const slot = thread?.agentSessions?.[harnessId]
    ?? (thread?.agentHarnessId === harnessId && thread.agentSessionId
      ? { sessionId: thread.agentSessionId, repoId: thread.agentRepoId,
          mode: thread.agentMode }
      : undefined);
  const [sessionId, setSessionId] = useState<string | null>(slot?.sessionId ?? null);
  const [record, setRecord] = useState<AgentSessionRecord | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [input, setInput] = useState(initialPrompt ?? "");
  // re-seed if a different card's context arrives while the panel is mounted
  useEffect(() => { if (initialPrompt) setInput(initialPrompt); }, [initialPrompt]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repoId, setRepoId] = useState(
    // No registered repo chosen -> Home workspace (read-only), per the plan's
    // session defaults, instead of an empty picker that blocks Start.
    thread?.agentRepoId ?? initialRepoId ?? repos[0]?.repo_id ?? HOME_WORKSPACE_ID,
  );
  useEffect(() => {
    if (!sessionId && initialRepoId && repos.some((repo) => repo.repo_id === initialRepoId)) {
      setRepoId(initialRepoId);
    }
  }, [initialRepoId, repos, sessionId]);
  const [mode, setMode] = useState(thread?.agentMode ?? "analysis");
  // runtime-discovered model + effort catalog for this harness (empty until loaded)
  const [models, setModels] = useState<AgentModelOption[]>([]);
  const [model, setModel] = useState<string>("");
  const [effort, setEffort] = useState<string>("");
  // Phase 4: explicit paid-egress acknowledgement. An external-egress harness
  // (OpenRouter) may not send until the user confirms "this context leaves the
  // machine" — never a silent paid send.
  const [egressAck, setEgressAck] = useState(false);
  // Phase 1: typed composer attachments (resolved + safety-checked on the host
  // at send time). staged = what the user added; blocked = refusals surfaced
  // after a resolve attempt (never silently dropped).
  const [attachments, setAttachments] = useState<AttachmentReq[]>([]);
  const [attachBlocked, setAttachBlocked] =
    useState<{ requested: string; reason: string }[]>([]);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  // repos load ASYNC: a panel mounted before they arrived held repoId=""
  // forever while the <select> painted the first option — LOOKING selected
  // without BEING selected, so auto-start never fired and the register
  // warning stuck (the 2026-07-17 "can't start even with a repo" trap).
  // Adopt a real value once options exist; never override a valid choice.
  useEffect(() => {
    // Home workspace is a valid selection even though it's not in `repos` — the
    // adoption below must NOT clobber it (it would otherwise reset to repos[0]).
    if (repoId === HOME_WORKSPACE_ID) return;
    if (repos.length && !repos.some((r) => r.repo_id === repoId)) {
      setRepoId(initialRepoId && repos.some((r) => r.repo_id === initialRepoId)
        ? initialRepoId : repos[0].repo_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repos, initialRepoId]);
  // inline folder registration (mirrors `cc repo-register` via the cockpit)
  const [regPath, setRegPath] = useState("");
  const [regName, setRegName] = useState("");
  const [regBusy, setRegBusy] = useState(false);
  const [regResult, setRegResult] = useState<string | null>(null);
  // settings changed mid-conversation are NOTED in the chat (they bind when
  // the next session starts — a live CLI session pins its model); "new chat"
  // resets by remount
  const [settingsNotes, setSettingsNotes] = useState<string[]>([]);
  const noteSetting = (text: string) =>
    setSettingsNotes((current) => [...current, text]);
  // "Track as mission" — the OPTIONAL governance wrapper. Set once promoted.
  const [missionId, setMissionId] = useState<string | null>(thread?.missionId ?? null);
  const [promoting, setPromoting] = useState(false);
  const sessionIdRef = useRef(sessionId);
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);
  const closeStreamRef = useRef<(() => void) | null>(null);
  const autoStartAttemptedRef = useRef("");
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { endRef.current?.scrollIntoView(); }, [events]);

  // load the runtime's model catalog once, only while setting up a new session
  useEffect(() => {
    if (sessionId) return;
    let cancelled = false;
    fetchHarnessModels(harnessId)
      .then((cat) => {
        if (cancelled) return;
        setModels(cat.models);
        const def = cat.models.find((m) => m.is_default) ?? cat.models[0];
        setModel(def?.id ?? "");
        setCatalogError(null);
        setCatalogLoaded(true);
      })
      .catch((e) => {
        if (cancelled) return;
        setModels([]);
        setCatalogError((e as Error).message);
        setCatalogLoaded(true);
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [harnessId, sessionId]);

  // efforts offered by the currently-selected model (falls back to all)
  const selectedModel = models.find((m) => m.id === model);
  const effortChoices = selectedModel?.supported_efforts ?? [];

  function connect(id: string, afterSequence: number) {
    closeStreamRef.current?.();
    closeStreamRef.current = streamAgentEvents(id, afterSequence,
      (ev) => {
        if (sessionIdRef.current !== id) return;
        setEvents((current) => [...current, ev]);
        if (ev.sequence != null) onThreadChange({ agentLastSeenSequence: ev.sequence });
        if (["session_idle", "session_failed", "session_closed"].includes(ev.type)) {
          void fetchAgentSession(id).then(setRecord).catch(() => {});
        }
      },
      (detail) => { if (sessionIdRef.current === id) setError(detail); });
  }

  // Refresh recovery: a persisted session id (from a previous page load, via
  // the parent's ChatThread metadata) is re-verified against the real
  // worker, replayed in full, then the live stream resumes from wherever it
  // left off — never trusted blindly (see WORKLOG.md "Agent-session chat
  // integration" on why an agent session's state is never assumed).
  useEffect(() => {
    const id = slot?.sessionId;
    if (!id) return;
    let cancelled = false;
    setSessionId(id);
    fetchAgentSession(id)
      .then((rec) => { if (!cancelled) setRecord(rec); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    fetchAgentEvents(id, 0)
      .then((all) => {
        if (cancelled) return;
        setEvents(all);
        const last = all.length ? all[all.length - 1].sequence ?? 0 : 0;
        connect(id, last);
      })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => {
      cancelled = true;
      closeStreamRef.current?.();
      closeStreamRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slot?.sessionId]);

  async function createSession() {
    setBusy(true);
    setError(null);
    try {
      const rec = await createAgentSession({
        harness_id: harnessId, conversation_id: conversationId,
        repo_id: repoId, mode, permission_profile: "read_only",
        model: model || null, effort: effort || null,
      });
      setSessionId(rec.session_id);
      setRecord(rec);
      setEvents([]);
      onThreadChange({
        agentSessionId: rec.session_id, agentHarnessId: harnessId,
        agentRepoId: repoId, agentMode: mode,
        agentPermissionProfile: rec.permission_profile, agentLastSeenSequence: 0,
        // per-harness slot map: merge so OTHER harnesses' sessions survive
        // switching back and forth (the panel owns the merge — the parent
        // patch is a shallow spread)
        agentSessions: {
          ...(thread?.agentSessions ?? {}),
          [harnessId]: { sessionId: rec.session_id, repoId, mode },
        },
      });
      connect(rec.session_id, 0);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    const id = sessionId;
    const text = input.trim();
    if (!id || (!text && attachments.length === 0) || busy) return;
    // No silent paid send: an external-egress harness needs an explicit,
    // per-session acknowledgement before the FIRST message leaves the machine.
    if (harness?.external_egress && !egressAck) {
      setError("Confirm the paid external-egress notice below before sending.");
      return;
    }
    setBusy(true);
    setError(null);
    let prompt = text;
    try {
      // Resolve + safety-check attachments on the host BEFORE sending. Blocked
      // ones (secret path / escape / oversize) are surfaced, never dropped —
      // and we attach TYPED references (path + digest) for the agent to read
      // with its own tools, not concatenated raw content (plan §4).
      if (attachments.length > 0) {
        const res = await resolveAttachments(
          repoId || null, !!harness?.external_egress, attachments);
        if (res.summary.blocked.length > 0) {
          setAttachBlocked(res.summary.blocked.map(
            (b) => ({ requested: b.requested, reason: b.reason })));
          setError(`${res.summary.blocked.length} attachment(s) blocked — `
            + "remove them or fix the path before sending.");
          setBusy(false);
          return;
        }
        const refs = res.resolutions
          .filter((r) => r.attachment)
          .map((r) => {
            const a = r.attachment!;
            return a.path_ref
              ? `- ${a.kind}: ${a.path_ref}${a.content_digest ? ` (${a.content_digest})` : ""}`
              : `- ${a.kind}: ${a.resource_id}`;
          });
        if (refs.length) {
          prompt = `${text}\n\nReferenced context (read these):\n${refs.join("\n")}`;
        }
      }
      setInput("");
      setAttachments([]);
      setAttachBlocked([]);
      await sendAgentMessage(id, prompt);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function addAttachment(a: AttachmentReq) {
    setAttachments((prev) => [...prev, a]);
    setAttachBlocked([]);
  }

  async function decide(approvalId: string, approved: boolean) {
    if (!sessionId) return;
    try { await resolveAgentApproval(sessionId, approvalId, approved); }
    catch (e) { setError((e as Error).message); }
  }

  async function doInterrupt() {
    if (!sessionId) return;
    try { await interruptAgentSession(sessionId); setRecord(await fetchAgentSession(sessionId)); }
    catch (e) { setError((e as Error).message); }
  }
  async function doResume() {
    if (!sessionId) return;
    try { await resumeAgentSession(sessionId); setRecord(await fetchAgentSession(sessionId)); }
    catch (e) { setError((e as Error).message); }
  }
  async function doClose() {
    if (!sessionId) return;
    try {
      await closeAgentSession(sessionId);
      closeStreamRef.current?.();
      closeStreamRef.current = null;
      setRecord(await fetchAgentSession(sessionId));
    } catch (e) { setError((e as Error).message); }
  }
  // Track this read-only session as a Ledger mission — reuses the SAME session
  // (no restart) and grants no writes. Records the mission id on the thread.
  async function doPromote() {
    if (!sessionId || missionId || promoting) return;
    setPromoting(true); setError(null);
    try {
      const res = await promoteAgentSession(sessionId);
      setMissionId(res.mission_id);
      onThreadChange({ missionId: res.mission_id });
    } catch (e) { setError((e as Error).message); }
    finally { setPromoting(false); }
  }

  const harness = harnesses?.find((h) => h.harness_id === harnessId);
  const pending = pendingApprovalsOf(events);
  const status = record?.status;
  const autoStartKey = `${harnessId}:${conversationId}:${repoId}`;

  useEffect(() => {
    if (sessionId || busy || !catalogLoaded || catalogError
        || !harness?.available || !repoId) return;
    if (autoStartAttemptedRef.current === autoStartKey) return;
    autoStartAttemptedRef.current = autoStartKey;
    void createSession();
    // createSession uses the runtime catalog's selected default. The key
    // prevents React StrictMode from creating the same session twice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStartKey, busy, catalogError, catalogLoaded, harness?.available,
      repoId, sessionId]);

  if (!sessionId) {
    return (
      <div className="chat-log">
        <div className="agent-session-setup">
          <div><b>{harness?.label ?? harnessId}</b>{harness ? ` — ${harness.detail}` : ""}</div>
          {harness && !harness.available ? (
            <div className="agent-unavailable">
              <div className="muted">
                Unavailable — {harness.detail || "the host worker can't reach this runtime."}
              </div>
              <div className="muted small">
                To enable it: wire the host agent worker (<code>KANBAN_UI_AGENT_SESSIONS_ENABLED=1</code>,{" "}
                <code>AGENT_WORKER_URL</code>, <code>AGENT_WORKER_TOKEN</code>) and log the runtime in on the
                worker (<code>claude auth login</code> / <code>codex login</code>). See{" "}
                <code>docs/runbooks/agent-sessions-activation.md</code>.
              </div>
            </div>
          ) : (
            <>
              <label className="chat-field">
                <span className="muted small">context</span>
                <select className="select" value={repoId} onChange={(e) => setRepoId(e.target.value)}>
                  {/* Home is ALWAYS selectable — a read-only sandbox, not a
                      registered repo (no unrestricted recursive access). */}
                  <option value={HOME_WORKSPACE_ID}>🏠 Home workspace (read-only)</option>
                  {repos.length > 0 && <optgroup label="registered repos">
                    {repos.map((r) => <option key={r.repo_id} value={r.repo_id}>{r.repo_id}</option>)}
                  </optgroup>}
                </select>
              </label>
              {repoId === HOME_WORKSPACE_ID && (
                <div className="muted small home-disclosure">
                  🏠 Read-only sandbox over your home folder. Credential &amp; secret
                  locations (.ssh, .aws, .azure, .gnupg, .env, private keys, browser
                  profiles) stay unreadable. Add a folder below for a scoped repo session.
                </div>
              )}
              <label className="chat-field">
                <span className="muted small">mode</span>
                <select className="select" value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option value="analysis">analysis (read-only)</option>
                  <option value="workspace" disabled>workspace (leased worktree — not yet available)</option>
                </select>
              </label>
              {models.length > 0 && (
                <label className="chat-field">
                  <span className="muted small">agent model</span>
                  <select className="select" value={model}
                    onChange={(e) => { setModel(e.target.value); setEffort(""); }}>
                    {models.map((m) => (
                      <option key={m.id} value={m.id} disabled={!m.available}>
                        {m.display_name}{m.is_default ? " (default)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {effortChoices.length > 0 && (
                <label className="chat-field">
                  <span className="muted small">reasoning effort</span>
                  <select className="select" value={effort}
                    onChange={(e) => setEffort(e.target.value)}>
                    <option value="">auto ({selectedModel?.default_effort ?? "model default"})</option>
                    {effortChoices.map((ef) => <option key={ef} value={ef}>{ef}</option>)}
                  </select>
                </label>
              )}
              {busy ? (
                <div className="muted">Starting a read-only session…</div>
              ) : (
                <button className="actbtn capture-primary"
                  disabled={!repoId || !catalogLoaded || !!catalogError}
                  title={!repoId ? "Pick or register a folder below first"
                    : "Starts a read-only session with the settings above"}
                  onClick={() => {
                    autoStartAttemptedRef.current = "";
                    void createSession();
                  }}>
                  ▶ {error ? "Retry" : "Start chat"}
                </button>
              )}
              {catalogError && (
                <ChatBubbleShell role="assistant"
                  text={`model catalog failed: ${catalogError}`}
                  runtime={harness ?? `agent:${harnessId}`} error />
              )}
              <details className="dup-more agent-register-details" open={repos.length === 0}>
                <summary>
                  Add a folder as a scoped repo — any path ▾
                </summary>
                <div className="agent-register">
                  {/* Home is NOT registered here anymore — it's a first-class
                      read-only workspace in the context picker above (a fake
                      repo would grant unrestricted recursive access). This flow
                      is only for scoping a REAL project folder as a repo. */}
                  <div className="muted small">
                    Want your whole home folder? Pick <b>🏠 Home workspace</b> in
                    the context selector above — it's read-only and denies secret
                    paths, no registration needed. Use this form to register a
                    specific project folder for deeper, graphed analysis.
                  </div>
                  <div className="agent-register-fields">
                    <label className="chat-field"><span className="muted small">folder path</span>
                      <input className="select" value={regPath}
                        placeholder="C:\\path\\to\\your\\project"
                        onChange={(e) => setRegPath(e.target.value)} />
                    </label>
                    <label className="chat-field"><span className="muted small">name (id)</span>
                      <input className="select" value={regName}
                        placeholder="my_project"
                        onChange={(e) => setRegName(e.target.value)} />
                    </label>
                  </div>
                  <button className="actbtn" disabled={regBusy || !regPath.trim() || !regName.trim()}
                    onClick={async () => {
                      setRegBusy(true); setRegResult(null);
                      try {
                        const res = await registerRepo({
                          repo_id: regName.trim(), local_path: regPath.trim(),
                          remote_url: "", kanban_board: "personal_todos",
                          apply: true,
                        });
                        const r = res as unknown as Record<string, unknown>;
                        setRegResult(r.status === "blocked"
                          ? `blocked: ${(r.blockers as string[])?.join(", ")}`
                          : `✓ registered. One host step remains: add `
                            + `${String(r.local_path_env ?? `${regName.trim().toUpperCase()}_LOCAL_PATH`)}=${regPath.trim()} `
                            + "to .env, then restart the agent worker "
                            + "(scripts/start_agent_worker.ps1 restart) so "
                            + "sessions can resolve the folder.");
                      } catch (e) { setRegResult(`failed: ${(e as Error).message}`); }
                      finally { setRegBusy(false); }
                    }}>
                    {regBusy ? "registering…" : "Register folder"}
                  </button>
                  {regResult && <div className="muted small">{regResult}</div>}
                  <div className="muted small">
                    Registration mirrors <code>cc repo-register</code>: the
                    manifest commits with autonomy disabled; paths live in
                    <code>.env</code> (never committed). <code>llm_station</code>{" "}
                    and <code>betts_basketball</code> resolve out of the box.
                  </div>
                </div>
              </details>
            </>
          )}
          {error && <ChatBubbleShell role="assistant" text={error}
            runtime={harness ?? `agent:${harnessId}`} error />}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="chat-subbar chat-idbar">
        {/* Identity row — ALWAYS visible per the plan: what context this
            session can see, which assistant, and that it is read-only. These
            were previously buried; the header is now Context → Assistant →
            permission → live status, then actions on the right. */}
        <span className="id-chip" title="Workspace this session reads (read-only until a governed promotion)">
          <span className="id-chip-k">Context</span>
          <span className="id-chip-v">{repoId || "—"}</span>
        </span>
        <span className="id-chip" title={harness?.detail ?? ""}>
          <span className="id-chip-k">Assistant</span>
          <span className="id-chip-v">{harness?.label ?? harnessId}</span>
        </span>
        <span className="id-chip id-perm"
          title="Read-only analysis — no writes, merges, or approvals without a governed mission">
          {mode === "analysis" ? "Read-only" : mode}
        </span>
        {harness?.usage_summary && (
          <span className={`usage-badge ${AVAIL_CLASS[harness.usage_summary.availability] ?? "muted"}`}
            title={harness.usage_summary.availability_reason}>
            {harness.usage_summary.availability.replace(/_/g, " ")}
          </span>
        )}
        {(() => {   // ONE running token chip instead of raw usage JSON rows
          const { usage } = buildAgentTranscript(events);
          if (usage.totalTokens === null) return null;
          const pct = usage.contextWindow
            ? Math.round((usage.totalTokens / usage.contextWindow) * 100)
            : null;
          return (
            <span className="muted small" title="session tokens used (from the runtime's own usage events)">
              {(usage.totalTokens / 1000).toFixed(1)}k tokens
              {pct !== null ? ` · ${pct}% of context` : ""}
            </span>
          );
        })()}
        <span className="id-status muted small" title={`agent session ${sessionId}`}>
          {status ?? "…"}
        </span>

        <div className="chat-header-right">
          {/* Stop stays VISIBLE while a turn runs (plan: Send + Stop always
              on-screen); resume replaces it when the turn is interrupted. */}
          {(status === "idle" || status === "active") && (
            <button className="clear stopbtn" onClick={() => void doInterrupt()}
              title="Stop the current turn">■ stop</button>
          )}
          {(status === "interrupted" || status === "failed") && (
            <button className="clear" onClick={() => void doResume()}>resume</button>
          )}
          {/* Handoff — the in-conversation assistant switch, kept as a primary
              compact button (both native sessions stay resumable). */}
          {onHandoff && (() => {
            const other = harnesses?.find(
              (h) => h.harness_id !== harnessId && h.available);
            if (!other) return null;
            return (
              <button className="clear"
                title={`Per the CLAUDE.md protocol: hand this work to ${other.label} (same conversation — both sessions stay resumable). A BOUNDED briefing is built from this session — not the whole transcript.`}
                onClick={async () => {
                  // Bounded, typed hand-off: the worker assembles a briefing
                  // from THIS session's stored events (never an unlimited
                  // transcript) and records handoff_started evidence. Seed the
                  // target with that prompt; its per-harness slot resumes.
                  try {
                    if (sessionId) {
                      const r = await buildAgentHandoff(sessionId, other.harness_id);
                      onHandoff(other.harness_id, r.prompt);
                    } else {
                      onHandoff(other.harness_id,
                        `Hand-off to ${other.label}, per the CLAUDE.md capability split. Continue this work at your capability level.`);
                    }
                  } catch (e) {
                    setError(`hand-off failed: ${(e as Error).message}`);
                  }
                }}>
                ⇄ {other.label.split(" ")[0]}
              </button>
            );
          })()}
          {/* Settings popover: model + effort for the NEXT session in this chat
              (a live session pins its model). Hover / keyboard / tap. */}
          {sessionId && models.length > 0 && (
            <Popover
              label={`Settings: ${models.find((m) => m.id === model)?.display_name ?? "model"}`
                + ` · ${effort || "auto"} ▾`}
              title="Model & reasoning effort for the next session in this chat">
              <div className="agent-settings-body">
                <label className="chat-field"><span className="muted small">next-session model</span>
                  <select className="select" value={model}
                    onChange={(e) => {
                      const next = models.find((m) => m.id === e.target.value);
                      setModel(e.target.value); setEffort("");
                      noteSetting(`model → ${next?.display_name ?? e.target.value}`);
                    }}>
                    {models.map((m) => (
                      <option key={m.id} value={m.id} disabled={!m.available}>
                        {m.display_name}</option>
                    ))}
                  </select>
                </label>
                {effortChoices.length > 0 && (
                  <label className="chat-field"><span className="muted small">next-session effort</span>
                    <select className="select" value={effort}
                      onChange={(e) => {
                        setEffort(e.target.value);
                        noteSetting(`effort → ${e.target.value || "auto"}`);
                      }}>
                      <option value="">auto</option>
                      {effortChoices.map((ef) => <option key={ef} value={ef}>{ef}</option>)}
                    </select>
                  </label>
                )}
                <div className="muted small">
                  A live session pins its model — changes bind when the next
                  session starts in this chat (close, or hand off and return);
                  each change is noted below. “new chat” resets everything.
                </div>
              </div>
            </Popover>
          )}
          {/* More popover: the secondary session actions the plan says to tuck
              under a menu (mission promotion, close/diagnostics). */}
          <Popover label="More ⋯" title="Session actions">
            {missionId ? (
              <div className="popover-note"><MissionProgressStrip missionId={missionId} /></div>
            ) : (
              <button type="button" className="popover-item"
                onClick={() => void doPromote()} disabled={promoting}
                title="Track this conversation as a mission — optional governance/tracking, no writes, keeps the same session">
                {promoting ? "tracking…" : "Track as mission"}
              </button>
            )}
            {status !== "closed" && (
              <button type="button" className="popover-item danger"
                onClick={() => void doClose()}>Close session</button>
            )}
          </Popover>
        </div>
      </div>
      <div className="chat-log">
        {events.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-title">
              {harness?.label ?? harnessId} is ready — read-only analysis of <b>{repoId}</b>
            </div>
            <div className="chat-empty-body muted small">
              Ask anything about this workspace. It can read files, search, explain,
              plan, and draft — every change is previewed first and nothing is
              written, merged, deployed, or approved without you.
            </div>
            <div className="chat-empty-starters">
              {[
                `Give me a tour of ${repoId}: what it does and how it's laid out.`,
                "Find the riskiest or most confusing part of this code and explain why.",
                "Draft a short plan for a change I could make here (no edits yet).",
              ].map((s) => (
                <button key={s} className="chat-starter" type="button"
                  onClick={() => setInput(s)}
                  title="Fills the composer — you still press Enter to send">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        <AgentTranscript events={events} runtime={harness ?? `agent:${harnessId}`} />
        {settingsNotes.map((note, i) => (
          <div className="agent-marker muted small" key={`sn-${i}`}>
            ⚙ settings updated: {note} — binds to the next session in this chat
          </div>
        ))}
        {error && <ChatBubbleShell role="assistant" text={error}
          runtime={harness ?? `agent:${harnessId}`} error />}
        <div ref={endRef} />
      </div>
      {pending.map((ev) => (
        <div className="agent-approval" key={String(ev.payload.approval_id)}>
          <span>Approval requested: {String(ev.payload.action)}</span>
          <button className="actbtn" onClick={() => void decide(String(ev.payload.approval_id), true)}>
            approve
          </button>
          <button className="clear" onClick={() => void decide(String(ev.payload.approval_id), false)}>
            deny
          </button>
        </div>
      ))}
      {status !== "closed" && (
        <div className="chat-composer"
          onDragOver={(e) => { e.preventDefault(); }}
          onDrop={(e) => {
            // browsers can't expose a dropped file's host path; accept dropped
            // TEXT as a repo-relative path hint the user can verify/remove.
            e.preventDefault();
            const t = e.dataTransfer.getData("text")?.trim();
            if (t) addAttachment({ attachment_id: _attachId(), kind: "file",
              rel_path: t, display_name: t });
          }}>
          {(attachments.length > 0 || attachBlocked.length > 0) && (
            <div className="attach-chips">
              {attachments.map((a) => (
                <span className="attach-chip" key={a.attachment_id}
                  title={a.rel_path ?? a.resource_id ?? ""}>
                  <span className="attach-chip-kind">{a.kind}</span>
                  {a.display_name}
                  <button type="button" className="attach-chip-x" aria-label="remove"
                    onClick={() => setAttachments((p) =>
                      p.filter((x) => x.attachment_id !== a.attachment_id))}>×</button>
                </span>
              ))}
              {attachBlocked.map((b, i) => (
                <span className="attach-chip attach-chip-blocked" key={`b-${i}`}
                  title={b.reason}>⚠ {b.requested}: {b.reason}</span>
              ))}
            </div>
          )}
          <textarea className="chat-composer-input" value={input} rows={3}
            placeholder={`Message ${harness?.label ?? "the agent"}…  (Enter to send · Shift+Enter for a newline)`}
            onChange={(e) => {
              setInput(e.target.value);
              // auto-grow: 3 lines min, ~12 lines max, then internal scroll
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 280)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault(); void send();
              }
            }} />
          {harness?.external_egress && (
            <label className="egress-notice">
              <input type="checkbox" checked={egressAck}
                onChange={(e) => setEgressAck(e.target.checked)} />
              <span>
                ⚠ <b>This context will leave the machine.</b> {harness.label} is a
                paid external API — files you reference are sent off-box. Check to
                allow sending; local runtimes (Claude/Codex) keep everything on-box.
              </span>
            </label>
          )}
          <div className="chat-composer-bar">
            <AttachMenu onAdd={addAttachment} contextLabel={repoId || "context"} />
            <span className="muted small">
              read-only analysis · {harness?.label ?? harnessId}
              {harness?.external_egress ? " · paid external egress" : ""}
            </span>
            <button className="actbtn" onClick={() => void send()}
              disabled={busy || status === "active"
                || (!input.trim() && attachments.length === 0)
                || (harness?.external_egress && !egressAck)}
              title={harness?.external_egress && !egressAck
                ? "Confirm the paid external-egress notice first" : undefined}>
              {busy ? "…" : "Send"}
            </button>
          </div>
        </div>
      )}
    </>
  );
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
                const described = describeChatEvent(ev);
                const timestamp = fmtThreadTime(ev.ts ?? "");
                if (described.kind === "activity") {
                  return <ChatActivity key={j} runtime="GatewayCore"
                    text={`${timestamp ? `${timestamp} · ` : ""}${described.text}`}
                    collapsedDetail={described.collapsedDetail} />;
                }
                return <ChatBubbleShell key={j} runtime="GatewayCore"
                  role={described.role} text={described.text}
                  error={described.kind === "error"} />;
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

function ChatView({ roles, runtime, agentHarnesses, agentHarnessesError,
  agentSessionSpecs, draft, onBack, onWorkCreated }: {
  roles: string[];
  runtime: ChatRuntime | null;
  agentHarnesses: AgentHarnessOption[] | null;
  agentHarnessesError: string | null;
  agentSessionSpecs: AgentSessionSpecSummary[];
  draft?: { text: string; nonce: number; conversationId?: string;
            storyTs?: string; target?: string; repoId?: string } | null;
  onBack?: () => void;
  onWorkCreated?: () => void;
}) {
  const [model, setModel] = useState(roles.includes("chat") ? "chat" : roles[0] ?? "");
  const initialActive = useMemo(() => loadActiveThreadPointer(), []);
  const [conversationId, setConversationId] = useState(initialActive.conversationId);
  const [historyOpen, setHistoryOpen] = useState(false);
  // Phase 5 board-format confirm-card (structured column edit → preview → gated apply)
  const [boardFmtOpen, setBoardFmtOpen] = useState(false);
  // an explicit Claude<->Codex handoff in flight: which agent target it is
  // for and the prefilled context prompt (cleared implicitly on new chat)
  const [handoff, setHandoff] = useState<{ target: string; text: string } | null>(null);
  // which lane we're talking to: GatewayCore (in-app, /chat/completions),
  // an agent session (Claude/Codex/Fake, structurally separate — see
  // WORKLOG.md "Agent-session chat integration"), or a configured external
  // specialist (ORCA/OmniAgent/OxyGent) opened in its own tab. targetRaw is
  // the <select>'s string value; chatTarget is the parsed discriminated
  // union everything else below switches on.
  const [targetRaw, setTargetRaw] = useState(initialActive.target);
  const chatTarget = decodeChatTarget(targetRaw);
  // Packet 2 is a read path only: this selection previews a validated spec in
  // the chrome and never changes targetRaw or mounts/starts an agent session.
  const [selectedSpecName, setSelectedSpecName] = useState("");
  const selectedSessionSpec = agentSessionSpecs.find(
    (spec) => spec.name === selectedSpecName) ?? agentSessionSpecs[0];
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
  const [promoting, setPromoting] = useState(false);
  const [promoteErr, setPromoteErr] = useState<string | null>(null);
  const [routeText, setRouteText] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  // guards hydration races: a slow transcript fetch for a thread the user has
  // already left must not fill the current thread's log
  const conversationIdRef = useRef(conversationId);
  useEffect(() => { conversationIdRef.current = conversationId; }, [conversationId]);
  useEffect(() => { endRef.current?.scrollIntoView(); }, [events]);
  // Refresh recovery (page reload): remember which thread + lane were open
  // so a browser refresh lands back on the same agent session (or GatewayCore
  // thread) instead of always resetting to "app"/GatewayCore.
  useEffect(() => {
    saveActiveThreadPointer(conversationId, targetRaw);
  }, [conversationId, targetRaw]);
  const currentThread = threads.find((t) => t.id === conversationId);
  // Agent-session metadata lives on the local ChatThread cache only — never
  // routed through persistThread/saveChatThread (GatewayCore's flight
  // recorder), matching the structural separation everywhere else in this
  // subsystem.
  function updateAgentThread(patch: Partial<ChatThread>) {
    setThreads((current) => {
      const existing = current.find((t) => t.id === conversationIdRef.current);
      const next: ChatThread = {
        id: conversationIdRef.current,
        title: existing?.title ?? "Agent session",
        target: targetRaw,
        ...existing,
        ...patch,
        updatedAt: new Date().toISOString(),
      };
      const merged = upsertChatThread(current, next);
      saveChatThreads(merged);
      return merged;
    });
  }
  // "Track as mission" for a GatewayCore conversation — optional governance,
  // reuses this thread (no restart), grants no writes. Records the mission id on
  // the thread so MissionProgressStrip renders the journey inline.
  async function promoteGatewayChat() {
    if (currentThread?.missionId || promoting) return;
    setPromoting(true); setPromoteErr(null);
    try {
      const res = await promoteChat(conversationId, currentThread?.lastPrompt ?? "");
      updateAgentThread({ missionId: res.mission_id });
    } catch (e) { setPromoteErr((e as Error).message); }
    finally { setPromoting(false); }
  }
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
    setSelectedSpecName((current) => (
      agentSessionSpecs.some((spec) => spec.name === current)
        ? current : agentSessionSpecs[0]?.name ?? ""
    ));
  }, [agentSessionSpecs]);
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
    // a card's runtime picker preselects the assistant lane
    if (draft?.target) setTargetRaw(draft.target);
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
  }, [draft?.conversationId, draft?.nonce, draft?.repoId, draft?.text,
      draft?.storyTs, draft?.target]);
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
      target: targetRaw,
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
    if (thread.target) setTargetRaw(thread.target);
    if (thread.lastPrompt) setInput(thread.lastPrompt);
    setEvents([]);
    setStory(null);
    setStoryError(null);
    setFocusTs(null);
    setChatMode(mode);
    // agent threads recover their own history/live stream from ChatThread's
    // agentSessionId (see AgentSessionPanel) — GatewayCore's story/live
    // hydration below only applies to a "GatewayCore" or external thread.
    if (decodeChatTarget(thread.target ?? "GatewayCore").kind !== "gateway") return;
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

  // Delete ONE thread from the strip. Agent threads have no GatewayCore
  // transcript to delete — their history is the worker's durable session
  // store; deleting the thread CLOSES its sessions (evidence retained in the
  // Ledger) and drops the local chip. Gateway threads go through the full
  // server-side transcript delete above.
  async function deleteThread(thread: ChatThread) {
    const target = decodeChatTarget(thread.target ?? "GatewayCore");
    if (target.kind !== "agent") {
      await deleteConversation(thread.id);
      return;
    }
    if (!window.confirm(
      `Remove agent chat "${thread.title}"?\n\nIts sessions are closed; the `
      + "durable session events stay in the Ledger.")) return;
    const slotIds = Object.values(thread.agentSessions ?? {})
      .map((s) => s.sessionId);
    if (thread.agentSessionId) slotIds.push(thread.agentSessionId);
    for (const sid of [...new Set(slotIds)]) {
      try { await closeAgentSession(sid); } catch { /* already closed/gone */ }
    }
    const local = threads.filter((t) => t.id !== thread.id);
    setThreads(local);
    saveChatThreads(local);
    if (conversationIdRef.current === thread.id) startNewChat();
  }

  // Clear history: every gateway transcript (server-side, best effort — a
  // failure is reported, never silently skipped) + every agent thread's
  // sessions, then the local strip. One explicit confirmation.
  async function clearHistory() {
    if (!window.confirm(
      `Clear ALL chat history (${threads.length} thread${threads.length === 1 ? "" : "s"})?\n\n`
      + "Gateway transcripts are deleted server-side; agent sessions are "
      + "closed (their Ledger events remain). Boards and cards are untouched.")) {
      return;
    }
    const failures: string[] = [];
    for (const thread of threads) {
      const target = decodeChatTarget(thread.target ?? "GatewayCore");
      try {
        if (target.kind === "agent") {
          const ids = Object.values(thread.agentSessions ?? {})
            .map((s) => s.sessionId);
          if (thread.agentSessionId) ids.push(thread.agentSessionId);
          for (const sid of [...new Set(ids)]) {
            try { await closeAgentSession(sid); } catch { /* gone */ }
          }
        } else {
          await deleteChatConversation(thread.id);
        }
      } catch (e) {
        failures.push(`${thread.title}: ${(e as Error).message}`);
      }
    }
    setThreads([]);
    saveChatThreads([]);
    setConversations([]);
    startNewChat();
    loadConversations();
    if (failures.length) {
      window.alert("Some transcripts could not be deleted server-side "
        + `(local chips removed):\n${failures.join("\n")}`);
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
  const activeExternal = chatTarget.kind === "external"
    ? externalChats.find((c) => c.name === chatTarget.name) : undefined;
  const agentRepos = runtime?.repos ?? [];
  return (
    <div className="chat">
      {routeText && (
        <TodoRoutingWizard text={routeText} conversationId={conversationId}
          onClose={() => setRouteText(null)}
          onCommitted={() => onWorkCreated?.()} />
      )}
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
                <span className="muted small">assistant</span>
                <select className="select" value={targetRaw}
                  onChange={(e) => setTargetRaw(e.target.value)}
                  title="Pick the runtime that handles this conversation. Growth OS/GatewayCore is the local action-aware chat lane. Claude Code and Codex are coding-agent runtimes on the host worker — no mission is needed to start a read-only session.">
                  <option value="GatewayCore">Growth OS (GatewayCore local chat)</option>
                  {externalChats.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}{c.active ? "" : " (not configured)"}
                    </option>
                  ))}
                  <optgroup label="Coding agents (Claude Code · Codex)">
                    {agentHarnessesError && (
                      <option value="agent:__unavailable" disabled>
                        Agent sessions unavailable — {agentHarnessesError}
                      </option>
                    )}
                    {agentHarnesses?.map((h) => {
                      const display = optionLabel(
                        `${h.label} — ${h.detail}${h.available ? harnessBadgeText(h) : ""}`);
                      return (
                        <option key={h.harness_id} value={`agent:${h.harness_id}`}
                          disabled={!h.available} title={display.title}>
                          {display.label}
                        </option>
                      );
                    })}
                  </optgroup>
                </select>
              </label>
              <AssistantRolesPanel
                onPick={(assistantId) => setTargetRaw(
                  assistantId === "gatewaycore" ? "GatewayCore"
                    : `agent:${assistantId}`)} />
              {selectedSessionSpec && (
                <div className="agent-spec-picker"
                  title="Display preview only — selecting a spec does not start or change a session.">
                  <label className="chat-field">
                    <span className="muted small">session spec</span>
                    <select className="select" value={selectedSessionSpec.name}
                      onChange={(event) => setSelectedSpecName(event.target.value)}>
                      {agentSessionSpecs.map((spec) => (
                        <option key={spec.name} value={spec.name}
                          title={agentSessionSpecOptionLabel(spec)}>
                          {agentSessionSpecOptionLabel(spec)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <span className="agent-spec-meta" aria-live="polite">
                    <Badge value={selectedSessionSpec.harness} />
                    <Badge value={selectedSessionSpec.capability_profile} />
                  </span>
                </div>
              )}
              {chatTarget.kind === "gateway" && (
                <label className="chat-field">
                  <span className="muted small">chat model</span>
                  <select className="select" value={model}
                    onChange={(e) => setModel(e.target.value)}
                    title="Local roles route free through LiteLLM/Ollama. Frontier models are a paid, opt-in escalation lane. Local Frontier models are a free but experimental, very slow, loopback-only lane. To run Claude Code or Codex, pick them from the Assistant selector — they are coding agents, not GatewayCore chat models.">
                    <optgroup label="Local (free)">
                      {roles.map((r) => {
                        const backing = runtime?.roles?.find((x) => x.role === r)?.candidates?.[0]?.model;
                        const display = optionLabel(backing ? `${r} — ${backing}` : r);
                        return <option key={r} value={r} title={display.title}>
                          {display.label}</option>;
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
                          const availability = f.selectable ? ""
                            : !f.lane_enabled ? " (lane disabled)" : " (no key)";
                          const display = optionLabel(
                            `${f.model_id}${resultsBits.length ? ` — ${resultsBits.join(" · ")}` : ""}${availability}`);
                          return (
                            <option key={f.model_id} value={`frontier:${f.model_id}`}
                              disabled={!f.selectable} title={display.title}>
                              {display.label}
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
                          const availability = f.selectable ? ""
                            : !f.lane_enabled ? " (lane disabled)" : ` (${f.health})`;
                          const display = optionLabel(
                            `${f.model_id}${resultsBits.length ? ` — ${resultsBits.join(" · ")}` : ""}${availability}`);
                          return (
                            <option key={f.model_id} value={`local-frontier:${f.model_id}`}
                              disabled={!f.selectable} title={display.title}>
                              {display.label}
                            </option>
                          );
                        })}
                      </optgroup>
                    )}
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
          {chatTarget.kind === "external" && activeExternal && (
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
          {chatTarget.kind === "gateway" && (
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
            {currentThread?.missionId ? (
              <MissionProgressStrip missionId={currentThread.missionId} />
            ) : (
              <button className="clear" onClick={() => void promoteGatewayChat()} disabled={promoting}
                title="Track this conversation as a mission — optional governance/tracking, no writes, keeps this thread">
                {promoting ? "tracking…" : "track as mission"}
              </button>
            )}
            {promoteErr && <span className="muted small">⚠ {promoteErr}</span>}
          </div>
          )}
          {/* Collapsible history: recent chats, tucked away until opened */}
          {historyOpen && (
            <div className="chat-threads">
              <div className="chat-threads-head">
                <span className="muted small">recent chats</span>
                {threads.length > 0 && (
                  <button className="clear"
                    title="Delete every gateway transcript and close every agent session (boards/cards untouched)"
                    onClick={() => void clearHistory()}>
                    clear history
                  </button>
                )}
              </div>
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
                    <button className="thread-delete"
                      title={decodeChatTarget(thread.target ?? "GatewayCore").kind === "agent"
                        ? "Remove this agent chat (closes its sessions; Ledger events remain)"
                        : "Delete this chat and its recorded transcript"}
                      onClick={() => void deleteThread(thread)}>
                      ✕
                    </button>
                  </div>
                ))}
              </HorizontalScroller>
            </div>
          )}
          {chatTarget.kind === "agent" ? (
            <PanelErrorBoundary label="The agent session panel">
              <AgentSessionPanel
                key={`${conversationId}:${chatTarget.harnessId}`}
                conversationId={conversationId}
                harnessId={chatTarget.harnessId} harnesses={agentHarnesses}
                repos={agentRepos}
                thread={currentThread}
                onThreadChange={updateAgentThread}
                initialPrompt={handoff?.target === targetRaw ? handoff.text
                  : draft?.target === targetRaw ? draft?.text : undefined}
                initialRepoId={draft?.target === targetRaw ? draft?.repoId : undefined}
                onHandoff={(otherId, text) => {
                  // same conversation: per-harness slots resume each side
                  setHandoff({ target: `agent:${otherId}`, text });
                  setTargetRaw(`agent:${otherId}`);
                }} />
            </PanelErrorBoundary>
          ) : chatTarget.kind !== "gateway" ? null : chatMode === "story" ? (
            <div className="chat-log chat-log-story">
              <ThreadTimeline transcript={story} loading={storyLoading}
                error={storyError} onRefresh={() => void loadStory()}
                onLoadAll={(total) => void loadStory(conversationId, total)}
                focusTs={focusTs} onFocused={() => setFocusTs(null)} />
            </div>
          ) : (
            <div className="chat-log">
              {events.length === 0 && <div className="muted">Ask the agent to do something — e.g. "stage the odds_promote card", "what's blocked?", "archive the oldest paper".</div>}
              {events.map((ev, i) => (
                <ChatLine key={i} ev={ev} onRoute={setRouteText} />
              ))}
              <div ref={endRef} />
            </div>
          )}
          {chatTarget.kind === "gateway" && (
            <div className="chat-composer">
              {boardFmtOpen && (
                <BoardFormatCard onClose={() => setBoardFmtOpen(false)} />
              )}
              <textarea className="chat-composer-input" value={input} rows={3}
                placeholder="Ask the agent…  (Enter to send · Shift+Enter for a newline)"
                onChange={(e) => {
                  setInput(e.target.value);
                  const el = e.currentTarget;
                  el.style.height = "auto";
                  el.style.height = `${Math.min(el.scrollHeight, 280)}px`;
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
                }} />
              <div className="chat-composer-bar">
                <button className="editbtn"
                  onClick={() => setRouteText(input.trim())}
                  disabled={busy || !input.trim()}>
                  Route TODOs
                </button>
                <button className="editbtn"
                  onClick={() => setBoardFmtOpen((v) => !v)}
                  title="Propose a board column change — preview first; nothing changes until a human approves">
                  {boardFmtOpen ? "Close board update" : "Propose board update"}
                </button>
                <button className="actbtn" onClick={send}
                  disabled={busy || !input.trim()}>
                  {busy ? "…" : "Send"}
                </button>
              </div>
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

// ---- work map -------------------------------------------------------------
// The WorkRelation vocabulary → human labels for the indented tree. Kept as a
// lookup (not hardcoded per branch) so an unrecognized future relation still
// degrades to the raw value instead of vanishing.
const RELATION_LABELS: Record<string, string> = {
  parent_of: "parent of",
  blocks: "blocks",
  related_to: "related to",
  implements: "implements",
  informs: "informs",
  derived_from: "derived from",
  duplicates: "duplicates",
  supersedes: "supersedes",
  supports: "supports",
};

// Connected Work: the backend-generated navigation receipts for one work item.
// Each ResourceLink.href is rendered VERBATIM as an <a href> — the frontend never
// assembles a work route. Ordered graph → primary board → other boards → chat →
// mission so the canonical landing spots come first.
function ConnectedWork({ workItemId }: { workItemId: string }) {
  const [links, setLinks] = useState<ResourceLink[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setLinks(null);
    setError(null);
    getWorkItemLinks(workItemId)
      .then((ls) => { if (!cancelled) setLinks(ls); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, [workItemId]);

  const rank = (l: ResourceLink): number => {
    if (l.kind === "graph") return 0;
    if (l.kind === "board") return l.relation === "primary" ? 1 : 2;
    if (l.kind === "chat") return 3;
    if (l.kind === "mission") return 4;
    return 5;
  };

  if (error) return <div className="error">connected work: {error}</div>;
  if (!links) return <div className="loading">…</div>;
  const ordered = [...links].sort((a, b) => rank(a) - rank(b));
  return (
    <div className="connected-work">
      <div className="nav-section-label">Connected work</div>
      <ul className="connected-links">
        {ordered.map((l, i) => (
          <li key={`${l.kind}-${l.resource_id}-${i}`}>
            <a href={l.href}>{l.label}</a>
            {l.relation && l.relation !== "self" &&
              <span className="muted small"> · {l.relation}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Work Map: a mobile-friendly indented tree of the work graph (NOT a canvas node
// graph). Whole graph when nothing is selected; the neighbourhood of one item
// otherwise. Each item lists its outgoing edges grouped by relation, resolving
// target ids to titles. A 503 (work graph disabled) or any error is surfaced as
// a banner — never a silent empty list.
function WorkMapView({
  workItemId, depth, onSelect, onClear, onDepthChange,
}: {
  workItemId: string | null;
  depth: number;
  onSelect: (id: string) => void;
  onClear: () => void;
  onDepthChange: (d: number) => void;
}) {
  const [graph, setGraph] = useState<WorkGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const req = workItemId
      ? getWorkGraphNeighbourhood(workItemId, depth)
      : getWorkGraph();
    req.then((g) => { if (!cancelled) { setGraph(g); setError(null); } })
      .catch((e) => { if (!cancelled) { setGraph(null); setError((e as Error).message); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [workItemId, depth]);

  // Selected item first, then the rest — so a neighbourhood reads root-down.
  const items = useMemo(() => {
    const list = graph?.items ?? [];
    if (!workItemId) return list;
    return [...list].sort((a, b) =>
      Number(b.work_item_id === workItemId) - Number(a.work_item_id === workItemId));
  }, [graph, workItemId]);
  const titleById = useMemo(
    () => new Map((graph?.items ?? []).map((i) => [i.work_item_id, i.title])),
    [graph]);
  const outgoing = useMemo(() => {
    const m = new Map<string, WorkEdge[]>();
    for (const e of graph?.edges ?? []) {
      const arr = m.get(e.from_work_item_id);
      if (arr) arr.push(e); else m.set(e.from_work_item_id, [e]);
    }
    return m;
  }, [graph]);

  if (error) {
    return (
      <div className="workmap">
        <div className="surface-errors"><div className="error">work graph: {error}</div></div>
      </div>
    );
  }
  if (loading && !graph) return <div className="loading">…</div>;
  if (!graph || graph.items.length === 0) {
    return <div className="workmap"><div className="empty">No work items yet</div></div>;
  }

  const groupByRelation = (edges: WorkEdge[]): [string, WorkEdge[]][] => {
    const g = new Map<string, WorkEdge[]>();
    for (const e of edges) {
      const arr = g.get(e.relation);
      if (arr) arr.push(e); else g.set(e.relation, [e]);
    }
    return [...g.entries()];
  };

  return (
    <div className="workmap">
      <div className="workmap-head">
        {workItemId ? (
          <>
            <button className="clear" onClick={onClear}>← whole graph</button>
            <label className="muted small">
              depth{" "}
              <select className="select" value={depth}
                onChange={(e) => onDepthChange(Number.parseInt(e.target.value, 10))}>
                {[1, 2, 3].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
          </>
        ) : (
          <span className="muted small">{graph.items.length} work items</span>
        )}
      </div>
      {workItemId && <ConnectedWork workItemId={workItemId} />}
      {items.map((item) => {
        const groups = groupByRelation(outgoing.get(item.work_item_id) ?? []);
        return (
          <div className="wm-item" key={item.work_item_id}>
            <button className="wm-item-head" onClick={() => onSelect(item.work_item_id)}>
              <span className="wm-title">{item.title}</span>
              <span className="wm-meta">
                <span className="chip">{item.kind}</span>
                <span className="chip">{item.canonical_status}</span>
                {item.primary_board_id && <span className="chip">{item.primary_board_id}</span>}
              </span>
            </button>
            {groups.map(([relation, edges]) => (
              <div className="wm-edges" key={relation}>
                <span className="wm-relation">{RELATION_LABELS[relation] ?? relation}</span>
                <ul className="wm-targets">
                  {edges.map((e) => (
                    <li key={e.edge_id}>
                      <button className="wm-target-link"
                        onClick={() => onSelect(e.to_work_item_id)}>
                        {titleById.get(e.to_work_item_id) ?? e.to_work_item_id}
                      </button>
                      {e.blocking && <span className="chip wm-blocking">blocking</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ---- app ------------------------------------------------------------------
export function App() {
  const [view, setView] = useState<View>(() => initialViewFromUrl());
  const [board, setBoard] = useState<BoardData | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [boards, setBoards] = useState<BoardSnapshot | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [lanes, setLanes] = useState<ModelLanes | null>(null);
  const [cfg, setCfg] = useState<UIConfig | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [runtimeDebug, setRuntimeDebug] = useState<RuntimeDebug | null>(null);
  const [chatRuntime, setChatRuntime] = useState<ChatRuntime | null>(null);
  const [agentHarnesses, setAgentHarnesses] = useState<AgentHarnessOption[] | null>(null);
  const [agentHarnessesError, setAgentHarnessesError] = useState<string | null>(null);
  const [agentSessionSpecs, setAgentSessionSpecs] =
    useState<AgentSessionSpecSummary[]>([]);
  const [registeredRepos, setRegisteredRepos] = useState<RegisteredRepository[]>([]);
  const [chatDraft, setChatDraft] =
    useState<{ text: string; nonce: number; conversationId?: string;
               storyTs?: string; target?: string; repoId?: string } | null>(null);
  // where the chat was opened from, so the chat's Back button can return there
  const [chatReturnView, setChatReturnView] = useState<View>("domains");
  const [domainNav, setDomainNav] = useState<DomainNavItem[]>([]);
  const [activeDomain, setActiveDomain] = useState(() => initialDomainFromUrl());
  // Work-graph selection (Work Map): the focused work item + neighbourhood depth,
  // both reflected in the URL so Back/Forward and pasted links restore them.
  const [selectedWork, setSelectedWork] = useState<string | null>(() => initialWorkFromUrl());
  const [graphDepth, setGraphDepth] = useState<number>(() => initialDepthFromUrl());
  const [captureOpen, setCaptureOpen] = useState(false);
  const [captureNonce, setCaptureNonce] = useState(0);
  const [updated, setUpdated] = useState<string>("");
  const [selMission, setSelMission] = useState<string | null>(null);
  const [selCard, setSelCard] =
    useState<{ board: string; card: BoardCard; statuses: string[] } | null>(null);
  const [surfaceLoads, setSurfaceLoads] =
    useState<Record<ResilientSurface, LoadResilienceState>>(createSurfaceLoadStates);
  const chatRef = useRef(false);   // so reloadBoards can pick live vs snapshot

  const markSurfaceSuccess = useCallback((surface: ResilientSurface) => {
    setSurfaceLoads((current) => ({
      ...current,
      [surface]: recordLoadSuccess(),
    }));
  }, []);

  const markSurfaceFailure = useCallback((
    surface: ResilientSurface, error: unknown, quiet = false,
  ) => {
    setSurfaceLoads((current) => ({
      ...current,
      [surface]: recordLoadFailure(current[surface], error, { quiet }),
    }));
  }, []);

  // Console: read boards from the LIVE local store (a write reflects at once); read-only:
  // the worker snapshot. Explicit capability switch, not a silent fallback.
  const reloadBoards = useCallback(async (quiet = false) => {
    try {
      setBoards(await (chatRef.current ? fetchBoardsLive() : fetchBoards()));
      markSurfaceSuccess("boards");
    } catch (e) {
      markSurfaceFailure("boards", e, quiet);
    }
  }, [markSurfaceFailure, markSurfaceSuccess]);

  const reloadDomainNav = useCallback(async () => {
    try {
      const body = await fetchDomains();
      setDomainNav((current) => {
        const items = body.domains.filter((domain) => !domain.archived).map((domain) => {
          const prior = current.find((item) => item.id === domain.domain_id);
          return {
            id: domain.domain_id, title: domain.title,
            count: prior?.count ?? null, origin: prior?.origin,
            error: prior?.error,
          };
        });
        setActiveDomain((selected) => (
          items.length && !items.some((item) => item.id === selected)
            ? items[0].id : selected));
        return items;
      });
    } catch {
      setDomainNav([]);
    }
  }, []);

  const recordDomainResults = useCallback((
    specs: DomainSpec[], packs: Record<string, DomainCards>,
    errors: Record<string, string>,
  ) => {
    setDomainNav((current) => current.map((item) => {
      const spec = specs.find((candidate) => candidate.domain_id === item.id);
      if (!spec) return item;
      const pack = packs[item.id];
      return {
        ...item,
        count: pack ? pack.cards.length : item.count,
        origin: pack?.origin ?? item.origin,
        error: errors[item.id],
      };
    }));
  }, []);

  const refreshGlobal = useCallback(async (quiet = false) => {
    try {
      setBoard(await fetchMissions());
      markSurfaceSuccess("missions");
    } catch (e) {
      markSurfaceFailure("missions", e, quiet);
    }
    try {
      setMetrics(await fetchMetrics());
      markSurfaceSuccess("observability");
    } catch (e) {
      markSurfaceFailure("observability", e, quiet);
    }
    try {
      setActivity(await fetchActivity());
      markSurfaceSuccess("activity");
    } catch (e) {
      markSurfaceFailure("activity", e, quiet);
    }
    await reloadBoards(quiet);
    try {
      setLanes(await fetchModels());
      markSurfaceSuccess("router");
    } catch (e) {
      markSurfaceFailure("router", e, quiet);
    }
    // status drives the topbar dots; if the probe endpoint itself is unreachable,
    // clear the dots (their absence is the signal) rather than show stale health.
    try { setStatus(await fetchStatus()); } catch { setStatus(null); }
    try { setRuntimeDebug(await fetchRuntimeDebug()); } catch { setRuntimeDebug(null); }
    try { setChatRuntime(await fetchChatRuntime()); } catch { setChatRuntime(null); }
    try {
      const catalog = await fetchRegisteredRepositories();
      setRegisteredRepos(catalog.repositories);
      markSurfaceSuccess("repositories");
    } catch (e) {
      markSurfaceFailure("repositories", e, quiet);
    }
  }, [markSurfaceFailure, markSurfaceSuccess, reloadBoards]);

  const refresh = useCallback(async () => {
    await Promise.all([refreshGlobal(), reloadDomainNav()]);
    setUpdated(new Date().toLocaleTimeString());
  }, [refreshGlobal, reloadDomainNav]);

  useEffect(() => {
    fetchConfig().then((c) => { setCfg(c); chatRef.current = !!c.chat_enabled; })
      .catch(() => setCfg(null));   // capability probe (once)
    void reloadDomainNav();
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      await refreshGlobal();
      if (!cancelled) timer = window.setTimeout(() => { void poll(); }, POLL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [refreshGlobal, reloadDomainNav]);

  useEffect(() => {
    let cancelled = false;
    fetchAgentHarnesses()
      .then((list) => {
        if (cancelled) return;
        setAgentHarnesses(list);
        setAgentHarnessesError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        setAgentHarnesses(null);
        setAgentHarnessesError((error as Error).message);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchAgentSessionSpecs()
      .then((specs) => { if (!cancelled) setAgentSessionSpecs(specs); })
      .catch(() => { if (!cancelled) setAgentSessionSpecs([]); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void refreshGlobal(true);
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => document.removeEventListener("visibilitychange", refreshWhenVisible);
  }, [refreshGlobal]);

  useEffect(() => {   // Escape closes whichever drawer is open
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setSelMission(null); setSelCard(null); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  // Reflect the current view/domain/work/depth into the URL. The first run only
  // normalizes the address bar (replaceState — no new history entry); afterwards a
  // genuine change pushes a new entry so Back/Forward restores the prior view +
  // selection. A no-op (state already matches the URL, e.g. right after popstate)
  // pushes nothing.
  const navReady = useRef(false);
  useEffect(() => {
    const search = navSearch(view, activeDomain, selectedWork, graphDepth);
    if (!navReady.current) {
      navReady.current = true;
      window.history.replaceState(null, "", search);
    } else if (search !== window.location.search) {
      window.history.pushState(null, "", search);
    }
  }, [view, activeDomain, selectedWork, graphDepth]);

  // Browser Back/Forward: restore the whole navigation state from the URL. The
  // browser has already swapped location.search, so the sync effect above sees a
  // match and does not push again.
  useEffect(() => {
    const onPop = () => {
      const p = new URLSearchParams(window.location.search);
      const v = p.get("view");
      setView(v && VIEW_IDS.has(v) ? (v as View) : "domains");
      setActiveDomain(p.get("domain") || "job_application");
      setSelectedWork(p.get("work") || null);
      const raw = p.get("depth");
      const n = raw ? Number.parseInt(raw, 10) : NaN;
      setGraphDepth(Number.isFinite(n) && n > 0 ? n : 1);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const chatOn = !!cfg?.chat_enabled;
  const openChatWithPrompt = useCallback(
    (prompt: string, conversationId?: string, storyTs?: string,
      target?: string, repoId?: string) => {
      setChatDraft({ text: prompt, conversationId, storyTs, target, repoId, nonce: Date.now() });
      // remember where we came from so Chat's Back button returns there
      setView((prev) => { if (prev !== "chat") setChatReturnView(prev); return "chat"; });
    }, []);
  const nav = [...NAV, { id: "chat" as View, label: "Chat" }];
  const domainNavCount = domainNav.reduce(
    (total, item) => total + (item.count ?? 0), 0);
  const counts: Partial<Record<View, number>> = {
    router: lanes?.roles.length, activity: activity?.calls.length,
  };
  if (domainNavCount > 0) counts.domains = domainNavCount;
  const boardsNote = surfaceLoads.boards.lastError;
  const lanesNote = surfaceLoads.router.lastError;
  const surfaceErrors = Object.fromEntries(
    RESILIENT_SURFACES
      .filter((surface) => surface !== "boards" && surface !== "router")
      .flatMap((surface) => (
        surfaceLoads[surface].lastError
          ? [[surface, surfaceLoads[surface].lastError as string]]
          : []
      )),
  );
  const bannerErrors = RESILIENT_SURFACES.flatMap((surface) => (
    surfaceLoads[surface].bannerError
      ? [[surface, surfaceLoads[surface].bannerError] as const]
      : []
  ));
  const staleSurfaces = RESILIENT_SURFACES.filter(
    (surface) => surfaceLoads[surface].stale,
  );

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
            <div className="nav-section-label">Kanban Boards</div>
            {domainNav.filter((item) => item.id !== "mission").map((item) => (
              <button key={item.id}
                className={`navitem nav-subitem ${view === "domains" && activeDomain === item.id ? "nav-on" : ""}`}
                title={item.error ?? `${item.origin ?? "domain"} source`}
                onClick={() => { setActiveDomain(item.id); setView("domains"); }}>
                {item.title}
                <span className="navcount">{item.error ? "ERR" : item.count ?? "…"}</span>
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
            {staleSurfaces.map((surface) => (
              <span className="chip muted small" key={surface}
                title={`${surfaceLoads[surface].consecutiveFailures} consecutive failed load(s)`}>
                {surface} stale since {formatStaleTime(surfaceLoads[surface].staleSince!)}
              </span>
            ))}
            <button className="actbtn" onClick={() => setCaptureOpen(true)}
              title="Capture an idea, todo, or note — from anywhere. It's saved, not started.">
              + Capture
            </button>
            {updated && <span className="muted small">updated {updated}</span>}
            <button className="refresh" onClick={refresh} title="refresh now">↻</button>
          </div>
        </div>
        {captureOpen && (
          <CaptureComposer
            context={view === "domains" ? activeDomain : undefined}
            onClose={() => setCaptureOpen(false)}
            onCaptured={() => setCaptureNonce((n) => n + 1)}
            onOpenChat={chatOn ? openChatWithPrompt : undefined} />
        )}
        {bannerErrors.length > 0 && (
          <div className="surface-errors">
            {bannerErrors.map(([name, msg]) => (
              <div className="error" key={name}>{name}: {msg}</div>
            ))}
          </div>
        )}
        {view === "missions" && (board
          ? <MissionsView data={board} onOpen={setSelMission} />
          : <div className="empty">{surfaceErrors.missions ?? "..."}</div>)}
        {view === "boards" && (boards
          ? <BoardsView snap={boards} canAct={chatOn} onMoved={reloadBoards}
              onOpenCard={(b, c, st) => setSelCard({ board: b, card: c, statuses: st })} />
          : <div className="empty">
              {surfaceLoads.boards.consecutiveFailures ? "Boards unavailable; retrying…" : "…"}
            </div>)}
        {view === "domains" && (
          <DomainsView refreshKey={updated} activeDomain={activeDomain}
            onActiveDomainChange={setActiveDomain} onOpenView={setView}
            onOpenChat={openChatWithPrompt}
            chatHarnesses={agentHarnesses}
            registeredRepos={registeredRepos}
            onDomainResult={recordDomainResults} />
        )}
        {view === "life-center" && (
          <PanelErrorBoundary label="Life Center">
            <LifeCenterView />
          </PanelErrorBoundary>
        )}
        {view === "todos" && <AllTodosView />}
        {view === "settings" && <SettingsView status={status} runtime={chatRuntime} />}
        {view === "router" && (lanes
          ? <RouterView lanes={lanes} />
          : <div className="empty">
              {surfaceLoads.router.consecutiveFailures ? "Router unavailable; retrying…" : "…"}
            </div>)}
        {view === "diagnostics" &&
          <DiagnosticsView debug={runtimeDebug} surfaceErrors={surfaceErrors}
            boardsNote={boardsNote} lanesNote={lanesNote} />}
        {view === "observability" && (metrics
          ? <ObservabilityView m={metrics} /> : <div className="loading">…</div>)}
        {view === "usage" && <UsageView />}
        {view === "work-map" && (
          <WorkMapView
            workItemId={selectedWork}
            depth={graphDepth}
            onSelect={(id) => { setSelectedWork(id); setView("work-map"); }}
            onClear={() => setSelectedWork(null)}
            onDepthChange={setGraphDepth} />
        )}
        {view === "inbox" && (
          <InboxView refreshKey={captureNonce}
            onOpenChat={chatOn ? openChatWithPrompt : undefined} />
        )}
        {view === "activity" && (activity
          ? <ActivityView a={activity} /> : <div className="loading">…</div>)}
        {/* chat stays MOUNTED so the conversation persists across view switches */}
        {chatOn && (
          <div style={{ display: view === "chat" ? "block" : "none" }}>
            <ChatView roles={cfg?.model_roles ?? []} runtime={chatRuntime}
              agentHarnesses={agentHarnesses} agentHarnessesError={agentHarnessesError}
              agentSessionSpecs={agentSessionSpecs}
              draft={chatDraft}
              onBack={() => setView(chatReturnView)}
              onWorkCreated={() => setUpdated(new Date().toISOString())} />
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
