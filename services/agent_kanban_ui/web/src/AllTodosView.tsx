import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  assignTodo,
  decideKanbanMaintenance,
  fetchKanbanMaintenance,
  fetchTodoDetail,
  fetchTodos,
  scanKanbanMaintenance,
  KanbanMaintenanceReview,
  TodoInventory,
  TodoDetail,
  TodoRow,
  TodoStoryItem,
  updateWorkItemDescription,
} from "./api";
import {
  isDescriptionConflictStatus,
  TodoStoryMutationGate,
  TodoStoryRequestGate,
} from "./todoStoryRequest";

const POLL_MS = 30_000;

type Filters = {
  q: string;
  kind: string;
  status: string;
  source: string;
  assigned: string;
  board_id: string;
};

const EMPTY_FILTERS: Filters = {
  q: "", kind: "", status: "", source: "", assigned: "", board_id: "",
};

type TodoSection = {
  id: string;
  title: string;
  detail: string;
  remoteUrl?: string;
  rows: TodoRow[];
  kind: "repository" | "shared" | "general";
};

function buildTodoSections(
  rows: TodoRow[], repos: TodoInventory["registered_repos"],
): TodoSection[] {
  const repoSections = new Map(repos.map((repo) => [repo.repo_id, {
    id: `repo:${repo.repo_id}`,
    title: repo.repo_id,
    detail: "TODOs mapped through boards registered to this repository.",
    remoteUrl: repo.remote_url,
    rows: [] as TodoRow[],
    kind: "repository" as const,
  }]));
  const shared: TodoRow[] = [];
  const general: TodoRow[] = [];

  for (const row of rows) {
    if (row.repo_ids.length > 1) {
      shared.push(row);
    } else if (row.repo_ids.length === 1) {
      const section = repoSections.get(row.repo_ids[0]);
      if (!section) {
        throw new Error(
          `TODO ${row.todo_id} references unregistered repo ${row.repo_ids[0]}`,
        );
      }
      section.rows.push(row);
    } else {
      general.push(row);
    }
  }

  const sections: TodoSection[] = [...repoSections.values()];
  if (shared.length > 0) sections.push({
    id: "shared", title: "Shared repositories",
    detail: "TODOs mapped to more than one registered repository.",
    rows: shared, kind: "shared",
  });
  sections.push({
    id: "general", title: "General & unassigned",
    detail: "Personal, life, and unassigned TODOs with no repository mapping.",
    rows: general, kind: "general",
  });
  return sections;
}

export function AllTodosView() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [data, setData] = useState<TodoInventory | null>(null);
  const [maintenance, setMaintenance] = useState<KanbanMaintenanceReview | null>(null);
  const [selected, setSelected] = useState<TodoRow | null>(null);
  const [target, setTarget] = useState("");
  const [newBoard, setNewBoard] = useState("");
  const [canonicalTitle, setCanonicalTitle] = useState("");
  const [canonicalDescription, setCanonicalDescription] = useState("");
  const [canonicalKind, setCanonicalKind] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [story, setStory] = useState<TodoDetail | null>(null);
  const [storyLoading, setStoryLoading] = useState(false);
  const [storyError, setStoryError] = useState<string | null>(null);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [descriptionBase, setDescriptionBase] = useState<TodoStoryItem | null>(null);
  const [descriptionStale, setDescriptionStale] = useState(false);
  const [descriptionSaving, setDescriptionSaving] = useState(false);
  const [storyTodoId, setStoryTodoId] = useState<string | null>(null);
  const storyRequests = useRef(new TodoStoryRequestGate());
  const storyMutations = useRef(new TodoStoryMutationGate());
  const inventoryRequests = useRef(new TodoStoryRequestGate());
  const assignmentMutations = useRef(new TodoStoryMutationGate());
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const load = useCallback(async () => {
    const request = inventoryRequests.current.begin();
    try {
      const activeFilters = filtersRef.current;
      const assigned = activeFilters.assigned === ""
        ? undefined : activeFilters.assigned === "true";
      const loaded = await fetchTodos(
        { ...activeFilters, assigned, limit: 10000 }, request.signal,
      );
      if (!inventoryRequests.current.isCurrent(request)) return;
      setData(loaded);
      setError(null);
    } catch (e) {
      if (!inventoryRequests.current.isCurrent(request)) return;
      setData(null);
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      await load();
      if (!cancelled) timer = window.setTimeout(() => { void poll(); }, POLL_MS);
    };
    const debounce = window.setTimeout(() => { void poll(); }, 200);
    return () => {
      cancelled = true;
      inventoryRequests.current.close();
      window.clearTimeout(debounce);
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [filters, load]);

  useEffect(() => {
    fetchKanbanMaintenance().then(setMaintenance).catch(() => setMaintenance(null));
  }, []);

  const rows = data?.rows ?? [];
  const sections = useMemo(
    () => buildTodoSections(rows, data?.registered_repos ?? []),
    [rows, data?.registered_repos],
  );
  const options = useMemo(() => ({
    kinds: data?.filter_catalogs.kinds ?? [],
    statuses: data?.filter_catalogs.statuses ?? [],
    sources: data?.filter_catalogs.sources ?? [],
  }), [data]);

  function updateFilter(name: keyof Filters, value: string) {
    setFilters((current) => ({ ...current, [name]: value }));
  }

  async function loadStory(todoId: string, preserveCurrent = false) {
    const request = storyRequests.current.begin();
    setStoryTodoId(todoId);
    if (!preserveCurrent) setStory(null);
    setStoryError(null);
    setStoryLoading(true);
    try {
      const loaded = await fetchTodoDetail(todoId, request.signal);
      if (!storyRequests.current.isCurrent(request)) return;
      const editable = loaded.canonical_item
        ?? (loaded.linked_work_items.length === 1 ? loaded.linked_work_items[0] : null);
      setStory(loaded);
      setDescriptionBase(editable);
      setDescriptionDraft(editable?.description ?? "");
      setDescriptionStale(false);
    } catch (e) {
      if ((e as Error).name !== "AbortError"
          && storyRequests.current.isCurrent(request)) {
        setStoryError((e as Error).message);
      }
    } finally {
      if (storyRequests.current.isCurrent(request)) setStoryLoading(false);
    }
  }

  function openStory(row: TodoRow) {
    storyMutations.current.invalidate();
    setDescriptionSaving(false);
    void loadStory(row.todo_id);
  }

  function closeStory() {
    storyRequests.current.close();
    storyMutations.current.invalidate();
    setDescriptionSaving(false);
    setStoryTodoId(null);
    setStory(null);
    setStoryError(null);
    setStoryLoading(false);
    setDescriptionBase(null);
    setDescriptionDraft("");
    setDescriptionStale(false);
  }

  async function saveDescription() {
    if (!descriptionBase || descriptionSaving || !storyTodoId) return;
    const mutation = storyMutations.current.begin(storyTodoId);
    setDescriptionSaving(true); setStoryError(null);
    try {
      const result = await updateWorkItemDescription(descriptionBase.work_item_id, {
        description: descriptionDraft,
        expected_updated_at: descriptionBase.updated_at,
        expected_description: descriptionBase.description,
      }, mutation.signal);
      if (!storyMutations.current.isCurrent(mutation, storyTodoId)) return;
      setDescriptionBase(result.item);
      await loadStory(mutation.todoId, true);
      if (!storyMutations.current.isCurrent(mutation, mutation.todoId)) return;
      setNotice("Organized description saved; immutable source text was unchanged.");
      await load();
    } catch (e) {
      if (!storyMutations.current.isCurrent(mutation, storyTodoId)) return;
      if (e instanceof ApiError && isDescriptionConflictStatus(e.status)) {
        setDescriptionStale(true);
        setStoryError(
          "This TODO changed after the story loaded. Reload the story before editing again.",
        );
      } else {
        setStoryError((e as Error).message);
      }
    } finally {
      if (storyMutations.current.isCurrent(mutation, storyTodoId)) {
        setDescriptionSaving(false);
      }
    }
  }

  async function assign() {
    if (!selected || busy) return;
    const mutation = assignmentMutations.current.begin(selected.todo_id);
    const board = data?.routable_boards.find(
      (candidate) => `${candidate.domain_id}|${candidate.board_id}` === target);
    if (!board && !newBoard.trim()) {
      setError("Choose an existing board or enter a new board name.");
      return;
    }
    const needsCanonical = !selected.work_item_id;
    if (needsCanonical && (!canonicalTitle.trim() || !canonicalKind)) {
      setError(
        "Confirm a canonical title and kind before materializing this source.",
      );
      return;
    }
    setBusy(true); setError(null); setNotice(null);
    try {
      const destination = board ? {
        board_id: board.board_id, domain_id: board.domain_id,
      } : { new_board_title: newBoard.trim() };
      const result = await assignTodo(selected.todo_id, {
        ...destination,
        ...(needsCanonical ? {
          canonical_title: canonicalTitle.trim(),
          canonical_description: canonicalDescription,
          canonical_kind: canonicalKind,
          confirm_canonical_fields: true,
        } : {}),
      }, mutation.signal);
      if (!assignmentMutations.current.isCurrent(mutation, mutation.todoId)) return;
      setNotice(result.status === "already_assigned"
        ? "This TODO was already linked there; no duplicate was created."
        : `Assigned to ${result.board.title}.`);
      setSelected(null); setTarget(""); setNewBoard("");
      setCanonicalTitle(""); setCanonicalDescription(""); setCanonicalKind("");
      await load();
    } catch (e) {
      if (assignmentMutations.current.isCurrent(mutation, mutation.todoId)
          && (e as Error).name !== "AbortError") {
        setError((e as Error).message);
      }
    } finally {
      if (assignmentMutations.current.isCurrent(mutation, mutation.todoId)) {
        setBusy(false);
      }
    }
  }

  async function scanMaintenance() {
    setBusy(true); setError(null);
    try { setMaintenance(await scanKanbanMaintenance()); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function decide(suggestionId: string, decision: "accept" | "reject") {
    setBusy(true); setError(null);
    try {
      await decideKanbanMaintenance(suggestionId, decision);
      setMaintenance(await fetchKanbanMaintenance());
      if (decision === "accept") await load();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="domain-wrap">
      <div className="domain-head">
        <div>
          <h2>Master TODO List</h2>
          <div className="muted small">
            One complete list across registered repositories, canonical work, intake captures, imported cards, and direct board TODOs.
          </div>
        </div>
        <div className="settings-head-actions">
          <span className="status-pill">{data?.filtered_total ?? "…"} shown</span>
          <span className="status-pill">{data?.completeness.emitted_total ?? "…"} total</span>
          <button className="editbtn" onClick={() => void load()}>refresh</button>
        </div>
      </div>

      {data && !data.completeness.complete && (
        <div className="error">
          PARTIAL INVENTORY — {data.completeness.error_count} source(s) could not be read. Nothing was silently treated as empty.
          {data.completeness.errors.map((row) => (
            <div key={row.source}>
              <code>{row.source}/{row.code}</code>: {row.message}
            </div>
          ))}
        </div>
      )}
      {data?.has_more && (
        <div className="error">INVENTORY TRUNCATED — {data.filtered_total} rows match but this page loaded {data.rows.length}. Narrow the filters before relying on this view.</div>
      )}
      {data?.completeness.complete && (
        <div className="settings-card">
          <b>Completeness verified</b>
          <div className="muted small">
            {data.completeness.source_counts.work_items} canonical work items · {data.completeness.source_counts.captures} captures checked · {data.completeness.source_counts.board_cards} direct/imported board TODOs · {data.completeness.deduplicated_projections} duplicate projections folded · {data.completeness.unassigned_total} unassigned
          </div>
          <div className="muted small">watermark <code>{data.completeness.watermark.slice(0, 16)}</code> · checked {new Date(data.completeness.checked_at).toLocaleString()}</div>
        </div>
      )}
      {error && <div className="error">ERR {error}</div>}
      {notice && <div className="actmsg">{notice}</div>}

      <div className="settings-card settings-card-wide">
        <div className="schema-form-grid">
          <label className="schema-form-wide">Search
            <input value={filters.q} placeholder="title or description"
              onChange={(e) => updateFilter("q", e.target.value)} />
          </label>
          <label>Type<select className="select" value={filters.kind}
            onChange={(e) => updateFilter("kind", e.target.value)}>
            <option value="">all types</option>
            {options.kinds.map((value) => <option key={value}>{value}</option>)}
          </select></label>
          <label>Status<select className="select" value={filters.status}
            onChange={(e) => updateFilter("status", e.target.value)}>
            <option value="">all statuses</option>
            {options.statuses.map((value) => <option key={value}>{value}</option>)}
          </select></label>
          <label>Source<select className="select" value={filters.source}
            onChange={(e) => updateFilter("source", e.target.value)}>
            <option value="">all sources</option>
            {options.sources.map((value) => <option key={value}>{value}</option>)}
          </select></label>
          <label>Assignment<select className="select" value={filters.assigned}
            onChange={(e) => updateFilter("assigned", e.target.value)}>
            <option value="">assigned + unassigned</option>
            <option value="false">unassigned only</option>
            <option value="true">assigned only</option>
          </select></label>
          <label>Kanban<select className="select" value={filters.board_id}
            onChange={(e) => updateFilter("board_id", e.target.value)}>
            <option value="">all kanbans</option>
            {(data?.filter_catalogs.boards ?? []).map((board) => (
              <option key={`${board.domain_id}|${board.board_id}`} value={board.board_id}>{board.title}</option>
            ))}
          </select></label>
        </div>
        <button className="editbtn" onClick={() => setFilters(EMPTY_FILTERS)}>clear filters</button>
      </div>

      <div className="todo-sections">
        {sections.map((section) => (
          <section className={`todo-section todo-section-${section.kind}`} key={section.id}>
            <div className="todo-section-head">
              <div>
                <h3>{section.title}</h3>
                <div className="muted small">{section.detail}</div>
                {section.remoteUrl && (
                  <a className="muted small todo-repo-link" href={section.remoteUrl}
                    target="_blank" rel="noreferrer">{section.remoteUrl}</a>
                )}
              </div>
              <span className="status-pill">{section.rows.length} TODOs</span>
            </div>
            <div className="settings-list">
              {section.rows.map((row) => (
                <div className="settings-row settings-row-tall" key={row.todo_id}>
                  <span>
                    <button className="todo-story-link" onClick={() => void openStory(row)}>
                      <b>{row.title ?? "Title not recorded"}</b>
                      {!row.title && row.raw_preview && (
                        <span className="muted small">raw preview: {row.raw_preview}</span>
                      )}
                    </button>
                    <span className="chip-list">
                      <span className="status-pill">{row.kind ?? "type not recorded"}</span>
                      <span className="status-pill">{row.status ?? "status not recorded"}</span>
                      <span className="status-pill">{row.source_kind}</span>
                      {row.repo_ids.map((repoId) => (
                        <span className="status-pill" key={repoId}>repo: {repoId}</span>
                      ))}
                    </span>
                    <span className="muted small">
                      source status: {row.raw_status ?? "not recorded"} · <a href={row.source_href}>open source</a>
                    </span>
                    <span className="muted small">
                      {row.boards.length ? row.boards.map((board, index) => (
                        <span key={`${board.domain_id}-${board.placement_id ?? "source"}`}>
                          {index > 0 ? " · " : "Kanban: "}<a href={board.href}>{board.board_id}</a>
                          {board.is_primary ? " (primary)" : ""}
                        </span>
                      )) : "Kanban: Unassigned"}
                    </span>
                  </span>
                  <button className="actbtn" disabled={!row.assignable}
                    onClick={() => {
                      assignmentMutations.current.invalidate();
                      setBusy(false);
                      setSelected(row); setTarget(""); setNewBoard("");
                      setCanonicalTitle(row.title ?? "");
                      setCanonicalDescription(
                        row.source_kind === "capture" ? "" : (row.description ?? ""),
                      );
                      setCanonicalKind(row.kind ?? "");
                    }}>
                    Assign / add kanban
                  </button>
                </div>
              ))}
              {section.rows.length === 0 && (
                <div className="empty">No TODOs in this section match the current filters.</div>
              )}
            </div>
          </section>
        ))}
        {data && sections.length === 0 && (
          <div className="empty">No registered repositories or TODOs were returned.</div>
        )}
      </div>

      {selected && (
        <div className="schema-editor">
          <div className="settings-card-head">
            <h3>Assign “{selected.title ?? selected.raw_preview ?? "untitled TODO"}”</h3>
            <button className="editbtn" onClick={() => {
              assignmentMutations.current.invalidate();
              setBusy(false);
              setSelected(null);
            }}>close</button>
          </div>
          <div className="schema-form-grid">
            {!selected.work_item_id && <>
              <label>Canonical title<input value={canonicalTitle} disabled={busy}
                placeholder="required; confirm the permanent WorkItem title"
                onChange={(event) => setCanonicalTitle(event.target.value)} /></label>
              <label>Canonical kind<select className="select" value={canonicalKind}
                disabled={busy}
                onChange={(event) => setCanonicalKind(event.target.value)}>
                <option value="">choose one</option>
                {[
                  "note", "todo", "research", "post", "paper", "project",
                  "bug", "feature", "decision", "maintenance",
                ].map((kind) => <option key={kind}>{kind}</option>)}
              </select></label>
              <label className="schema-form-wide">Organized description
                <textarea rows={5} value={canonicalDescription} disabled={busy}
                  onChange={(event) => setCanonicalDescription(event.target.value)} />
              </label>
            </>}
            <label>Existing kanban<select className="select" value={target}
              disabled={!!newBoard.trim() || busy}
              onChange={(e) => setTarget(e.target.value)}>
              <option value="">choose one</option>
              {(data?.routable_boards ?? []).filter((board) =>
                !selected.boards.some((current) =>
                  current.board_id === board.board_id && current.domain_id === board.domain_id)
              ).map((board) => (
                <option key={`${board.domain_id}|${board.board_id}`}
                  value={`${board.domain_id}|${board.board_id}`}>{board.title}</option>
              ))}
            </select></label>
            <label>Or create a new kanban<input value={newBoard} disabled={!!target || busy}
              placeholder="broad topic, e.g. Home Projects"
              onChange={(e) => setNewBoard(e.target.value)} /></label>
          </div>
          <div className="muted small">
            The original source remains intact. For a source without a WorkItem,
            the values above are the explicit canonical identity you are confirming;
            they are never inferred by the backend. Assignment adds a durable projection,
            and an exact retry creates nothing twice.
          </div>
          <button className="actbtn" disabled={
            busy || (!target && !newBoard.trim())
            || (!selected.work_item_id && (!canonicalTitle.trim() || !canonicalKind))
          }
            onClick={() => void assign()}>{busy ? "assigning…" : "Assign"}</button>
        </div>
      )}

      {(storyTodoId || storyLoading || story || storyError) && (
        <div className="drawer-bg todo-story-bg" onClick={closeStory}>
          <aside className="drawer todo-story-drawer" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-head">
              <div>
                <h2>TODO story</h2>
                {story && <div className="muted small">
                  <code>{story.requested_identity.todo_id}</code> · {story.requested_identity.state}
                </div>}
              </div>
              <button className="x" onClick={closeStory}>close</button>
            </div>
            {storyLoading && <div className="loading">Loading exact stored history…</div>}
            {storyError && <div className="error">{storyError}</div>}
            {storyTodoId && (storyError || descriptionStale) && (
              <button className="actbtn" disabled={storyLoading || descriptionSaving}
                onClick={() => void loadStory(storyTodoId, true)}>
                Reload current story
              </button>
            )}
            {story && !story.completeness.complete && (
              <div className="error">
                PARTIAL STORY — unavailable data was not replaced with guesses.
                {story.completeness.errors.map((row, index) => (
                  <div key={`${row.source}-${row.code}-${index}`}>
                    <code>{row.source}/{row.code}</code>: {row.message}
                  </div>
                ))}
              </div>
            )}
            {story && <>
              <section className="todo-story-section">
                <h3>Canonical identity & organized description</h3>
                {descriptionBase ? <>
                  <div className="muted small">
                    WorkItem <code>{descriptionBase.work_item_id}</code> · {descriptionBase.canonical_status}
                  </div>
                  <textarea rows={6} value={descriptionDraft}
                    disabled={descriptionSaving || descriptionStale}
                    onChange={(event) => setDescriptionDraft(event.target.value)} />
                  <button className="actbtn" disabled={
                    descriptionSaving || descriptionStale
                    || descriptionDraft === descriptionBase.description
                  }
                    onClick={() => void saveDescription()}>
                    {descriptionSaving ? "saving…" : "Save organized description"}
                  </button>
                </> : <div className="muted">
                  No singular canonical WorkItem is available to edit. The raw source remains read-only.
                </div>}
                {story.linked_work_items.length > 1 && <div className="error-inline">
                  This source links to {story.linked_work_items.length} WorkItems; none was selected implicitly.
                </div>}
              </section>

              <section className="todo-story-section">
                <h3>Repositories & placements</h3>
                <div className="chip-list">
                  {story.repositories.map((repo) => <a className="status-pill" key={repo.repo_id}
                    href={repo.remote_url} target="_blank" rel="noreferrer">{repo.repo_id}</a>)}
                  {!story.repositories.length && <span className="muted">General / no repository</span>}
                </div>
                {story.placements.map((placement) => <div className="event" key={placement.placement_id}>
                  <a href={placement.href}>{placement.board_id}</a> · {placement.role} · {placement.active ? "active" : "removed"}
                  <div className="muted small">board history: {String(placement.board_event_join_state)}</div>
                </div>)}
                {!story.placements.length && <div className="muted">No WorkPlacement recorded.</div>}
              </section>

              <details className="todo-story-section" open>
                <summary>Immutable raw capture ({story.raw_captures.length})</summary>
                {story.raw_captures.map((capture) => <div key={capture.record.capture_id}>
                  <div className="muted small"><code>{capture.record.capture_id}</code> · {capture.processing_status}</div>
                  <pre className="todo-raw-source">{capture.record.raw_content}</pre>
                </div>)}
                {!story.raw_captures.length && <div className="muted">No capture is exactly linked.</div>}
              </details>

              <details className="todo-story-section">
                <summary>Source card & Betts revisions</summary>
                {story.source.card
                  ? <pre>{JSON.stringify(story.source.card, null, 2)}</pre>
                  : <div className="muted">No exact source card is linked.</div>}
                {Object.keys(story.source.audit).length > 0 &&
                  <pre>{JSON.stringify(story.source.audit, null, 2)}</pre>}
              </details>

              <details className="todo-story-section" open>
                <summary>Status, progress & routing ({story.timeline.length} events)</summary>
                {story.timeline.map((event, index) => <div className="event" key={`${event.source}-${event.ref}-${index}`}>
                  <b>{event.kind}</b> <span className="chip">{event.source}</span>
                  <div className="muted small">{event.at ?? "stored timestamp unavailable"}</div>
                  <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                </div>)}
              </details>

              <details className="todo-story-section">
                <summary>Relationships, dependencies & child tasks ({story.relationships.length})</summary>
                {story.relationships.map((relationship, index) => <div className="event" key={index}>
                  {relationship.direction} · {String(relationship.edge.relation)} · {relationship.active ? "active" : "removed"}
                  <div>{relationship.related_item?.title ?? "related WorkItem unavailable"}</div>
                </div>)}
              </details>

              <details className="todo-story-section">
                <summary>Routing evidence ({story.routing.corrections.length} corrections)</summary>
                <pre>{JSON.stringify(story.routing, null, 2)}</pre>
              </details>

              <details className="todo-story-section">
                <summary>Conversations ({story.conversations.length})</summary>
                {story.conversations.map((conversation) => <div key={conversation.conversation_id}>
                  <a href={conversation.href}>{conversation.conversation_id}</a>
                </div>)}
              </details>

              <details className="todo-story-section" open>
                <summary>Completion evidence ({story.completion_evidence.length})</summary>
                {story.missions.map((mission, index) => <div className="event" key={index}>
                  <code>{String(mission.mission_id)}</code> · {String(mission.completion_state)}
                </div>)}
                {story.completion_evidence.map((evidence, index) => <div key={index}>
                  <code>{evidence.evidence_ref}</code>
                </div>)}
                {!story.missions.length && <div className="muted">No mission is explicitly linked.</div>}
              </details>

              <details className="todo-story-section">
                <summary>Reversible archive history ({story.archive_history.length})</summary>
                <pre>{JSON.stringify(story.archive_history, null, 2)}</pre>
              </details>
            </>}
          </aside>
        </div>
      )}

      <section className="settings-card settings-card-wide">
        <div className="settings-card-head">
          <div>
            <h3>Kanban maintenance review</h3>
            <div className="muted small">Suggestions only. Accept creates a maintenance TODO for human review; reject records your decision. Neither action merges, moves, archives, or deletes a board.</div>
          </div>
          <button className="editbtn" disabled={busy} onClick={() => void scanMaintenance()}>
            review now
          </button>
        </div>
        {(maintenance?.open ?? []).map((row) => (
          <div className="settings-row settings-row-tall" key={row.suggestion_id}>
            <span><b>{row.title}</b><span className="muted small">{row.reason}</span>
              <span className="muted small">boards: {row.board_ids.join(", ")}</span></span>
            <span className="preset-actions">
              <button className="actbtn" disabled={busy}
                onClick={() => void decide(row.suggestion_id, "accept")}>accept as TODO</button>
              <button className="editbtn" disabled={busy}
                onClick={() => void decide(row.suggestion_id, "reject")}>reject</button>
            </span>
          </div>
        ))}
        {(maintenance?.pending ?? []).map((row) => (
          <div className="settings-row settings-row-tall" key={row.suggestion_id}>
            <span><b>{row.title}</b><span className="muted small">Acceptance is pending recovery; retry will reuse the same maintenance TODO.</span></span>
            <button className="actbtn" disabled={busy}
              onClick={() => void decide(row.suggestion_id, "accept")}>retry acceptance</button>
          </div>
        ))}
        {maintenance && maintenance.open.length === 0 && (
          <div className="muted small">No open maintenance suggestions.</div>
        )}
      </section>
    </div>
  );
}
