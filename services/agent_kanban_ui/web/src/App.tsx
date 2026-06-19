import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AppFlowyBoard, BoardCard, BoardData, BoardSnapshot, ChatEvent,
  MissionDetail, MissionEvent, Metrics, ModelLanes, Status, UIConfig, fetchActivity,
  fetchBoards, fetchBoardsLive, fetchConfig, fetchMetrics, fetchMission,
  fetchMissions, fetchModels, fetchStatus, postAction, streamChat,
} from "./api";

type View = "missions" | "boards" | "router" | "observability" | "activity" | "chat";
const NAV: { id: View; label: string }[] = [
  { id: "missions", label: "Missions" },
  { id: "boards", label: "Boards" },
  { id: "router", label: "Router" },
  { id: "observability", label: "Observability" },
  { id: "activity", label: "Activity" },
];
const RISK_CLASS: Record<string, string> = {
  L0: "risk-l0", L1: "risk-l1", L2: "risk-l2", L3: "risk-l3", L4: "risk-l4",
};
const POLL_MS = 5000;

const pct = (x: number | null) => (x === null ? "—" : `${(x * 100).toFixed(0)}%`);
const matches = (q: string, ...parts: (string | undefined)[]) =>
  !q || parts.filter(Boolean).join(" ").toLowerCase().includes(q.toLowerCase());

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
      <div className="board">
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
      </div>
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

  async function drop(status: string) {
    const title = dragged;
    setOverCol(null); setDragged(null);
    if (!title || !board) return;
    setToast(null);
    try {
      const r = await postAction("move_item",
        { database: board.board, title, status });
      setToast(r.result);          // governed result (e.g. Approved → refusal)
      onMoved();
    } catch (e) { setToast("⚠ " + (e as Error).message); }
  }

  return (
    <>
      <div className="tabs">
        {snap.boards.map((b) => (
          <button key={b.board} className={`tab ${b.board === active ? "tab-on" : ""}`}
            onClick={() => setActive(b.board)}>{b.board}{b.error ? " ⚠" : ""}</button>
        ))}
        <span className="snap-time">
          {snap.generated_at.slice(0, 19)}{snap.live ? " · live" : " · snapshot"}
        </span>
      </div>
      <FilterBar q={q} setQ={setQ} risk="" setRisk={() => {}} risks={false} />
      {canAct && <div className="muted small">drag a card between columns, or open one to use the Move dropdown</div>}
      {toast && <div className="actmsg">{toast}</div>}
      {!board ? <div className="empty">No boards.</div>
        : board.error ? <div className="error">⚠ {board.board}: {board.error}</div>
        : (
          <div className="board">
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
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
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
function ChatLine({ ev }: { ev: ChatEvent }) {
  switch (ev.type) {
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

function ChatView({ roles }: { roles: string[] }) {
  const [model, setModel] = useState(roles.includes("chat") ? "chat" : roles[0] ?? "");
  const [input, setInput] = useState("");
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { endRef.current?.scrollIntoView(); }, [events]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setEvents((e) => [...e, { type: "you", content: text }]);
    setBusy(true);
    try {
      await streamChat({ text, model, conversation_id: "app" },
        (ev) => setEvents((e) => [...e, ev]));
    } catch (e) {
      setEvents((ev) => [...ev, { type: "error", message: (e as Error).message }]);
    } finally { setBusy(false); }
  }

  return (
    <div className="chat">
      <div className="chat-bar">
        <span className="muted small">model</span>
        <select className="select" value={model} onChange={(e) => setModel(e.target.value)}>
          {roles.map((r) => <option key={r}>{r}</option>)}
        </select>
        <span className="muted small">the agent moves/assigns via governed verbs — Approved stays human-only</span>
        {events.length > 0 && (
          <button className="clear" onClick={() => setEvents([])}>clear</button>
        )}
      </div>
      <div className="chat-log">
        {events.length === 0 && <div className="muted">Ask the agent to do something — e.g. "stage the odds_promote card", "what's blocked?", "archive the oldest paper".</div>}
        {events.map((ev, i) => <ChatLine key={i} ev={ev} />)}
        <div ref={endRef} />
      </div>
      <div className="chat-input">
        <input value={input} placeholder="ask the agent…" autoFocus
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
        <button onClick={send} disabled={busy}>{busy ? "…" : "send"}</button>
      </div>
    </div>
  );
}

// ---- app ------------------------------------------------------------------
export function App() {
  const [view, setView] = useState<View>("missions");
  const [board, setBoard] = useState<BoardData | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [boards, setBoards] = useState<BoardSnapshot | null>(null);
  const [boardsNote, setBoardsNote] = useState<string | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [lanes, setLanes] = useState<ModelLanes | null>(null);
  const [lanesNote, setLanesNote] = useState<string | null>(null);
  const [cfg, setCfg] = useState<UIConfig | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [updated, setUpdated] = useState<string>("");
  const [selMission, setSelMission] = useState<string | null>(null);
  const [selCard, setSelCard] =
    useState<{ board: string; card: BoardCard; statuses: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const chatRef = useRef(false);   // so reloadBoards can pick live vs snapshot

  // Console: read boards LIVE from AppFlowy (a write reflects at once); read-only:
  // the worker snapshot. Explicit capability switch, not a silent fallback.
  const reloadBoards = useCallback(async () => {
    try {
      setBoards(await (chatRef.current ? fetchBoardsLive() : fetchBoards()));
      setBoardsNote(null);
    } catch (e) { setBoards(null); setBoardsNote((e as Error).message); }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [b, m, act] = await Promise.all([fetchMissions(), fetchMetrics(), fetchActivity()]);
      setBoard(b); setMetrics(m); setActivity(act); setError(null);
    } catch (e) { setError((e as Error).message); }
    await reloadBoards();
    try { setLanes(await fetchModels()); setLanesNote(null); }
    catch (e) { setLanes(null); setLanesNote((e as Error).message); }
    // status drives the topbar dots; if the probe endpoint itself is unreachable,
    // clear the dots (their absence is the signal) rather than show stale health.
    try { setStatus(await fetchStatus()); } catch { setStatus(null); }
    setUpdated(new Date().toLocaleTimeString());
  }, [reloadBoards]);

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
  const nav = chatOn ? [...NAV, { id: "chat" as View, label: "Chat" }] : NAV;
  const counts: Partial<Record<View, number>> = {
    missions: board?.total, boards: boards?.boards.length,
    router: lanes?.roles.length, activity: activity?.calls.length,
  };

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
        <div className="badge">{chatOn ? "console · chat + governed writes" : "read-only · Ledger + log + snapshot"}</div>
      </aside>
      <main className="main">
        <div className="topbar">
          <div className="hops">
            {Object.entries(status?.hops ?? {}).map(([name, state]) => (
              <span className="hop" key={name} title={state}>
                <span className={`hopdot ${state === "ok" ? "ok" : "bad"}`} />{name}
              </span>
            ))}
          </div>
          <div className="topright">
            {updated && <span className="muted small">updated {updated}</span>}
            <button className="refresh" onClick={refresh} title="refresh now">↻</button>
          </div>
        </div>
        {error && <div className="error">⚠ {error}</div>}
        {view === "missions" && (board
          ? <MissionsView data={board} onOpen={setSelMission} />
          : <div className="loading">…</div>)}
        {view === "boards" && (boards
          ? <BoardsView snap={boards} canAct={chatOn} onMoved={reloadBoards}
              onOpenCard={(b, c, st) => setSelCard({ board: b, card: c, statuses: st })} />
          : <div className="empty">{boardsNote ?? "…"}</div>)}
        {view === "router" && (lanes
          ? <RouterView lanes={lanes} />
          : <div className="empty">{lanesNote ?? "…"}</div>)}
        {view === "observability" && (metrics
          ? <ObservabilityView m={metrics} /> : <div className="loading">…</div>)}
        {view === "activity" && (activity
          ? <ActivityView a={activity} /> : <div className="loading">…</div>)}
        {/* chat stays MOUNTED so the conversation persists across view switches */}
        {chatOn && (
          <div style={{ display: view === "chat" ? "block" : "none" }}>
            <ChatView roles={cfg?.model_roles ?? []} />
          </div>
        )}
        {view === "chat" && !chatOn &&
          <div className="empty">chat is not enabled in this deployment</div>}
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
