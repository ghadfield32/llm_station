"""High-level workspace actions shared by the MCP server (Claude) and the
local-LLM assistant (Ollama). Every write goes through the verified
pre_hash upsert, so all actions are idempotent and safe to retry.

Row keys: a row's stable key is the pre_hash it was created with —
papers: ArxivID cell; repos/signals: URL cell; todos/lessons/books/notes:
a slug derived from the title (recomputed here, callers just pass titles).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .config import load_settings
from .appflowy import AppFlowyClient

KEY_FIELD = {"papers": "ArxivID", "repos": "URL", "signals": "URL", "dags": "DagID"}
STATUSES = {
    "papers": ["Inbox", "Reading", "Read", "Archived"],
    "repos": ["Inbox", "Trying", "Using", "Archived"],
    "signals": ["Inbox", "Saved", "Archived"],
    "library": ["To read", "Reading", "Done"],
    "lessons": ["Capture", "Review", "Internalized"],
    "todos": ["Backlog", "Todo", "In Progress", "Blocked", "Done"],
    "dags": ["Active", "Paused", "Manual", "Broken", "Retired"],
    "mission_intake": ["Backlog", "Ready", "Approved", "In Progress",
                       "Blocked", "Done", "Rejected"],
}
TODO_AREAS = ["Betts Basketball", "DAGs", "Growth OS", "Learning", "Life"]
PRIORITIES = ["P0", "P1", "P2", "P3"]

_client: AppFlowyClient | None = None


def client() -> AppFlowyClient:
    global _client
    if _client is None:
        st = load_settings()
        _client = AppFlowyClient(st.appflowy_base_url, st.appflowy_workspace_id,
                                 dry_run=False)
        _client.login(st.appflowy_email, st.appflowy_password)
    return _client


def _slug(prefix: str, title: str) -> str:
    return f"{prefix}-{title.lower()[:80]}"


def _rows(db: str) -> list[dict]:
    af = client()
    out = []
    for d in af.row_details(db, af.list_row_ids(db)):
        c = d["cells"]
        if c.get("Name"):                 # skip blank starter rows
            out.append(c)
    return out


def _date_str(v) -> str:
    return v.get("pretty_start_date", "") if isinstance(v, dict) else (v or "")


# ----------------------------------------------------------------- triage --

INBOX_DBS = ("papers", "repos", "signals")


def list_inbox(database: str = "papers", limit: int = 20) -> list[dict] | str:
    """Untriaged (Status=Inbox) items. database must be one of papers,
    repos, signals - the only databases with an Inbox; for todos use
    list_todos, for mission cards use list_cards."""
    if database not in INBOX_DBS:
        return (f"invalid database {database!r}; inboxes exist on "
                f"{INBOX_DBS}. todos -> list_todos, cards -> list_cards")
    rows = []
    for c in _rows(database):
        if c.get("Status") != "Inbox":
            continue
        rows.append({"title": c.get("Name", ""),
                     "key": c.get(KEY_FIELD.get(database, "URL"), ""),
                     "score": c.get("Score", ""), "url": c.get("URL", "")})
    rows.sort(key=lambda r: float(r["score"] or 0), reverse=True)
    return rows[:limit]


def search(database: str, query: str, limit: int = 10) -> list[dict]:
    q = query.lower()
    hits = []
    for c in _rows(database):
        blob = " ".join(str(v) for v in c.values() if isinstance(v, str)).lower()
        if q in blob:
            hits.append({"title": c.get("Name", ""), "status": c.get("Status", ""),
                         "key": c.get(KEY_FIELD.get(database, "URL"), "")
                         or c.get("Name", "")})
    return hits[:limit]


def set_status(database: str, key: str, status: str) -> str:
    if database == "mission_intake" and status == "Approved":
        return ("refused: approving mission cards is human-only - drag the "
                "card to Approved on the board. Agents may draft (Backlog), "
                "stage (Ready), block, or reject, never approve.")
    allowed = STATUSES.get(database)
    if allowed and status not in allowed:
        return f"invalid status {status!r} for {database}; allowed: {allowed}"
    if database in ("library", "lessons", "todos", "notes"):
        prefix = {"library": "book", "lessons": "lesson", "todos": "todo",
                  "notes": "note"}[database]
        if not key.startswith(f"{prefix}-"):
            key = _slug(prefix, key)
    n = client().upsert(database, [{"pre_hash": key, "cells": {"Status": status}}])
    return f"updated {len(n)} row(s) in {database}"


# ------------------------------------------------------------------ todos --

def add_todo(task: str, area: str = "Life", priority: str = "P2",
             due: str = "", notes: str = "", status: str = "Todo") -> str:
    """due: ISO date (YYYY-MM-DD) or empty."""
    if area not in TODO_AREAS:
        return f"invalid area {area!r}; allowed: {TODO_AREAS}"
    if priority not in PRIORITIES:
        return f"invalid priority {priority!r}; allowed: {PRIORITIES}"
    cells = {"Task": task, "Status": status, "Area": area, "Priority": priority,
             "Notes": notes, "Created": date.today().isoformat()}
    if due:
        cells["Due"] = due
    n = client().upsert("todos", [{"pre_hash": _slug("todo", task), "cells": cells}])
    return f"added {len(n)} todo(s): {task}"


def list_todos(status: str = "", area: str = "") -> list[dict] | str:
    """Todos sorted by priority then due date. status: empty = all non-Done
    (the default you want for "open" todos), or exactly one of Backlog, Todo,
    In Progress, Blocked, Done. area: empty = all, or one of the five areas."""
    if status and status not in STATUSES["todos"]:
        return (f"invalid status {status!r}; allowed: {STATUSES['todos']} "
                "(leave empty for all open todos)")
    if area and area not in TODO_AREAS:
        return f"invalid area {area!r}; allowed: {TODO_AREAS} (empty = all)"
    out = []
    for c in _rows("todos"):
        if status and c.get("Status") != status:
            continue
        if not status and c.get("Status") == "Done":
            continue
        if area and c.get("Area") != area:
            continue
        out.append({"task": c.get("Name", ""), "status": c.get("Status", ""),
                    "area": c.get("Area", ""), "priority": c.get("Priority", ""),
                    "due": _date_str(c.get("Due")), "notes": c.get("Notes", "")[:120]})
    out.sort(key=lambda t: (t["priority"] or "P9", t["due"] or "9999"))
    return out


def update_todo(task: str, status: str = "", due: str = "", priority: str = "",
                area: str = "", notes: str = "") -> str:
    """Update any subset of fields on a todo, addressed by its task title."""
    cells: dict = {}
    if status:
        if status not in STATUSES["todos"]:
            return f"invalid status {status!r}; allowed: {STATUSES['todos']}"
        cells["Status"] = status
    if due:
        cells["Due"] = due
    if priority:
        cells["Priority"] = priority
    if area:
        cells["Area"] = area
    if notes:
        cells["Notes"] = notes
    if not cells:
        return "nothing to update"
    n = client().upsert("todos", [{"pre_hash": _slug("todo", task), "cells": cells}])
    return f"updated {len(n)} todo(s): {task}"


# ------------------------------------------------------------------- dags --

def list_dags(status: str = "") -> list[dict] | str:
    """DAG board rows. status: empty = all, or one of Active, Paused, Manual,
    Broken, Retired."""
    if status and status not in STATUSES["dags"]:
        return f"invalid status {status!r}; allowed: {STATUSES['dags']} (empty = all)"
    out = []
    for c in _rows("dags"):
        if status and c.get("Status") != status:
            continue
        out.append({"name": c.get("Name", ""), "dag_id": c.get("DagID", ""),
                    "schedule": c.get("Schedule", ""), "status": c.get("Status", ""),
                    # full failure summaries end with the UI log URL - keep it
                    "notes": c.get("Notes", "")[:400]})
    return out


def update_dag(dag_id: str, status: str = "", notes: str = "") -> str:
    cells: dict = {}
    if status:
        if status not in STATUSES["dags"]:
            return f"invalid status {status!r}; allowed: {STATUSES['dags']}"
        cells["Status"] = status
    if notes:
        cells["Notes"] = notes
    if not cells:
        return "nothing to update"
    n = client().upsert("dags", [{"pre_hash": dag_id, "cells": cells}])
    return f"updated {len(n)} dag(s): {dag_id}"


def project_status(project: str = "betts_basketball") -> dict | str:
    """Full situational awareness for one registered project in a single
    call: DAG board counts + broken-DAG error summaries, pending package
    updates, open mission cards in its section, and open todos in its area.
    This is the context pack an agent loads before working on the repo."""
    from .config import load_projects
    projects = {p.name: p for p in load_projects().projects}
    if project not in projects:
        return f"unknown project {project!r}; registered: {list(projects)}"
    dag_counts: dict[str, int] = {}
    broken = []
    for c in _rows("dags"):
        s = c.get("Status", "?")
        dag_counts[s] = dag_counts.get(s, 0) + 1
        if s == "Broken":
            broken.append({"dag_id": c.get("DagID"),
                           "error": (c.get("Notes") or "")[:200]})
    pkgs = [{"package": c.get("Name"), "current": c.get("Current"),
             "latest": c.get("Latest"), "severity": c.get("Severity")}
            for c in _rows("packages")
            if c.get("Repo") == project and c.get("Status") == "Inbox"]
    pkgs.sort(key=lambda p: ("major", "minor", "patch").index(p["severity"])
              if p["severity"] in ("major", "minor", "patch") else 3)
    section_label = "Betts Basketball" if project == "betts_basketball" \
        else project.replace("_", " ").title()
    cards = [c for c in list_cards()
             if c["section"] == section_label and c["status"] not in
             ("Done", "Rejected")]
    todos = list_todos(area=section_label) \
        if section_label in TODO_AREAS else []
    return {"project": project, "dags": dag_counts, "broken_dags": broken,
            "package_updates_pending": pkgs[:10],
            "open_mission_cards": cards, "open_todos": todos}


def network_health() -> dict:
    """Liveness of every hop in the agent request network: AppFlowy API,
    Ollama, LiteLLM, the Ledger, and Airflow. Each entry is ok/error with
    the reason - silence is never reported as success."""
    import httpx
    st = load_settings()
    checks: dict[str, str] = {}

    def probe(name: str, fn) -> None:
        try:
            fn()
            checks[name] = "ok"
        except Exception as exc:
            checks[name] = f"ERROR: {str(exc)[:120]}"

    probe("appflowy", lambda: client().list_row_ids("todos"))
    probe("ollama", lambda: httpx.get(
        f"{(st.ollama_base_url or 'http://localhost:11434').rstrip('/')}/api/tags",
        timeout=10).raise_for_status())
    probe("litellm", lambda: httpx.get(
        "http://localhost:4000/health/liveliness", timeout=10).raise_for_status())
    probe("ledger", lambda: httpx.get(
        f"{st.ledger_base_url.rstrip('/')}/health", timeout=10).raise_for_status())

    def airflow_probe():
        from . import airflow_sync as a
        registry = a.load_registry()
        if not registry:
            raise RuntimeError("no airflow projects registered")
        with a._api(registry[0][2]) as api:
            api.get("/dags", params={"limit": 1}).raise_for_status()
    probe("airflow", airflow_probe)
    return checks


def dag_health(dag_id: str = "") -> dict | list[dict] | str:
    """LIVE Airflow check (not the board): latest run state straight from the
    Airflow API. dag_id empty = health counts for every DAG plus the list of
    currently-failing ones with error summaries; dag_id set = that DAG's
    latest run state, and on failure the extracted root-cause summary."""
    from . import airflow_sync as a   # lazy: airflow_sync imports actions
    try:
        registry = a.load_registry()
    except SystemExit as exc:
        return str(exc)
    if not registry:
        return "no projects with an airflow block in config/projects.yaml"
    proj, afcfg, auth = registry[0]
    try:
        with a._api(auth) as api:
            if dag_id:
                run = a.latest_run(api, dag_id)
                if run is None:
                    return f"{dag_id}: no runs recorded"
                out = {"dag_id": dag_id, "state": run["state"],
                       "ended": run.get("end_date", "")}
                if run["state"] == "failed":
                    out["error"] = a.failed_summary(api, afcfg.ui_url, dag_id, run)
                return out
            counts: dict[str, int] = {}
            failing = []
            for dag in a.fetch_dags(api):
                run = a.latest_run(api, dag["dag_id"])
                state = "paused" if dag["is_paused"] else \
                    (run or {}).get("state", "no-runs")
                counts[state] = counts.get(state, 0) + 1
                if state == "failed":
                    failing.append({
                        "dag_id": dag["dag_id"],
                        "error": a.failed_summary(api, afcfg.ui_url,
                                                  dag["dag_id"], run)})
            return {"project": proj.name, "counts": counts, "failing": failing}
    except Exception as exc:   # surfaced to the asking agent, never swallowed
        return (f"airflow API error: {exc} - if this is 401/403, the basic-auth "
                "backend isn't enabled yet (webserver restart pending)")


def mission_status(mission_id: str) -> dict | str:
    """Check a Ledger mission opened from the kanban: current status, risk,
    and the most recent executor events (executors post progress summaries
    as events, so this is the 'how is it going' answer from any channel)."""
    import httpx
    st = load_settings()
    base = st.ledger_base_url.rstrip("/")
    try:
        r = httpx.get(f"{base}/mission/{mission_id}", timeout=15)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        return f"ledger unreachable or unknown mission: {exc}"
    body = r.json()
    m = body.get("mission", body)
    events = body.get("events", [])[-5:]
    return {"id": m.get("id"), "status": m.get("status"),
            "risk": m.get("risk"),
            "requires_approval": bool(m.get("requires_approval")),
            "action": (m.get("action") or "").splitlines()[0][:120],
            "recent_events": [
                {"kind": e.get("kind"), "at": e.get("created_at", "")[:19],
                 "summary": str(e.get("payload", ""))[:160]} for e in events]}


# ---------------------------------------------------------- mission cards --

MISSION_SECTIONS = ["DAGs", "Learning", "Betts Basketball", "Command Center"]
MISSION_DEFAULT_RISK = {
    "DAGs": "L2",
    "Learning": "L1",
    "Betts Basketball": "L2",
    "Command Center": "L1",
}


def add_mission_card(title: str, section: str, action: str = "",
                     acceptance: str = "", risk: str = "", repo: str = "",
                     target: str = "", priority: str = "P2", due: str = "",
                     notes: str = "") -> str:
    """Draft a work card on the mission_intake board (Status=Backlog). The
    card becomes real work ONLY after the human drags it to Approved — then
    the kanban bridge opens a gated Ledger mission and stamps MissionID back.
    Risk: L0-L4 (empty = the section's default). Priority: P0-P3. Due:
    ISO date (YYYY-MM-DD) or empty. L3/L4 need Ledger approval on top of
    board approval."""
    if section not in MISSION_SECTIONS:
        return f"invalid section {section!r}; allowed: {MISSION_SECTIONS}"
    if priority not in PRIORITIES:
        return f"invalid priority {priority!r}; allowed: {PRIORITIES}"
    if risk and risk not in ("L0", "L1", "L2", "L3", "L4"):
        return f"invalid risk {risk!r}; use L0-L4"
    key = _slug("card", title)
    cells = {"Title": title, "Section": section, "Status": "Backlog",
             "Priority": priority, "Risk": risk or MISSION_DEFAULT_RISK[section],
             "Action": action or title, "Acceptance": acceptance, "Notes": notes,
             "CardKey": key, "Created": date.today().isoformat()}
    if due:
        cells["Due"] = due
    if repo:
        cells["Repo"] = repo
    if target:
        cells["Target"] = target
    n = client().upsert("mission_intake", [{"pre_hash": key, "cells": cells}])
    return (f"drafted {len(n)} card(s) in Backlog (key {key}); drag to "
            f"Approved on the board to dispatch")


def list_cards(status: str = "") -> list[dict] | str:
    """Cards on the mission_intake board. status: empty = all, or exactly
    one of Backlog, Ready, Approved, In Progress, Blocked, Done, Rejected."""
    if status and status not in STATUSES["mission_intake"]:
        return (f"invalid status {status!r}; allowed: "
                f"{STATUSES['mission_intake']} (empty = all)")
    out = []
    for c in _rows("mission_intake"):
        if status and c.get("Status") != status:
            continue
        out.append({"title": c.get("Name", ""), "section": c.get("Section", ""),
                    "status": c.get("Status", ""), "risk": c.get("Risk", ""),
                    "priority": c.get("Priority", ""), "due": _date_str(c.get("Due")),
                    "repo": c.get("Repo", ""), "target": c.get("Target", ""),
                    "mission_id": c.get("MissionID", ""),
                    "key": c.get("CardKey", ""), "notes": c.get("Notes", "")[:120]})
    return out


# ---------------------------------------------------------------- capture --

def add_lesson(lesson: str, detail: str = "", domain: str = "Life",
               source: str = "") -> str:
    today = date.today()
    n = client().upsert("lessons", [{
        "pre_hash": _slug("lesson", lesson),
        "cells": {"Lesson": lesson, "Detail": detail, "Domain": domain,
                  "Source": source, "Status": "Capture", "Confidence": 3,
                  "NextReview": (today + timedelta(days=1)).isoformat(),
                  "Interval": 1, "Created": today.isoformat()}}])
    return f"added {len(n)} lesson(s)"


def add_book(title: str, author: str = "", tier: str = "Optional",
             status: str = "To read", module: str = "", hours: float = 0) -> str:
    cells = {"Title": title, "Author": author, "Tier": tier, "Status": status,
             "Module": module}
    if hours:
        cells["Hours"] = hours
    n = client().upsert("library", [{"pre_hash": _slug("book", title), "cells": cells}])
    return f"added {len(n)} book(s)"


def add_note(title: str, tags: str = "") -> str:
    n = client().upsert("notes", [{
        "pre_hash": _slug("note", title),
        "cells": {"Title": title, "Tags": tags,
                  "Updated": date.today().isoformat()}}])
    return f"added {len(n)} note(s)"


def book_note(title: str, note: str) -> str:
    """Append a dated reading note to a book's Notes in the library. title
    must match the book's title (case-insensitive); on a miss you get the
    closest matches back so you can retry with the exact one."""
    rows = _rows("library")
    match = next((c for c in rows
                  if c.get("Name", "").lower() == title.lower()), None)
    if match is None:
        near = [c["Name"] for c in rows
                if title.lower() in c.get("Name", "").lower()][:5]
        return (f"no book titled {title!r}; close matches: {near}" if near
                else f"no book titled {title!r} in the library")
    stamped = f"[{date.today().isoformat()}] {note}"
    existing = match.get("Notes", "") or ""
    merged = f"{existing}\n{stamped}".strip()
    n = client().upsert("library", [{"pre_hash": _slug("book", match["Name"]),
                                     "cells": {"Notes": merged}}])
    return f"noted on {match['Name']!r} ({len(n)} row updated)"


def review_lesson(lesson_key: str, quality: int) -> str:
    rows = [c for c in _rows("lessons")
            if _slug("lesson", c.get("Name", "")) == lesson_key
            or c.get("Name") == lesson_key]
    if not rows:
        return f"no lesson found for {lesson_key!r}"
    c = rows[0]
    interval = int(float(c.get("Interval") or 1))
    interval = max(1, round(interval * 2.5)) if quality >= 4 else \
        max(1, round(interval * 1.5)) if quality == 3 else 1
    nxt = (date.today() + timedelta(days=interval)).isoformat()
    status = "Internalized" if quality >= 4 and interval >= 14 else "Review"
    n = client().upsert("lessons", [{
        "pre_hash": _slug("lesson", c["Name"]),
        "cells": {"Interval": interval, "NextReview": nxt, "Status": status,
                  "Confidence": quality}}])
    return f"updated {len(n)} lesson(s); next review {nxt} (interval {interval}d)"


def latest_brief() -> str:
    briefs = sorted(Path("_export").glob("brief_*.md"))
    return briefs[-1].read_text(encoding="utf-8") if briefs else "no briefs yet"
