"""First-party agent kanban + observability UI — read-only backend.

A convenience surface, NOT the policy layer (configs/ui.yaml / WebUIConfig). It
reads two sources that are reachable across the container boundary without coupling
to growthos/AppFlowy:

  * the Ledger (`LEDGER_BASE_URL`) — missions are the execution kanban, grouped by
    status into Cline-style columns;
  * the agent-call log (`GROWTHOS_AGENT_LOG`) — surfaced through the SAME
    command_center.kanban.metrics used by `make kanban-digest`, so the UI and the
    CLI digest can never disagree.

It performs NO writes. Approving/killing a mission stays in the signed Ledger
endpoints (the HMAC secret is never given to this service); the UI links out to
them. AppFlowy remains the human staging surface. This keeps `external_write_policy:
governed_by_ledger` true by construction — there is simply no write path here.

The built SPA (static assets) is mounted at / when present (single-container mode).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from command_center.kanban.metrics import (
    compute_metrics, load_calls, log_path, recent_calls)
from command_center.kanban_sync import EventLog, project_cards

# Chat + governed writes turn the UI into a first-class CHANNEL (it embeds the same
# GatewayCore Discord uses). OFF by default so the read-only board deployment holds
# no creds; the full console enables it (KANBAN_UI_CHAT_ENABLED=1) and mounts
# growth-os + .env. L3/L4 approve/kill never reach here — only the action layer's
# governed verbs (which already refuse Approved).
CHAT_ENABLED = os.environ.get("KANBAN_UI_CHAT_ENABLED", "") == "1"
# Governed write verbs the console may call directly (the action layer enforces the
# wall; Approved is structurally refused inside them). No Ledger approve/kill here.
ACTION_VERBS = frozenset({"stage_card", "block_card", "reject_card",
                          "start_todo", "finish_todo", "block_todo", "move_item",
                          "annotate_item", "set_item_field",
                          "remove_item_field_value"})

LEDGER_BASE_URL = os.environ.get("LEDGER_BASE_URL", "http://ledger:8090").rstrip("/")
STATIC_DIR = Path(os.environ.get("KANBAN_UI_STATIC", "/app/static"))
# The AppFlowy board snapshot, produced on the worker (`make kanban-board-snapshot`)
# and mounted read-only here. The UI never holds AppFlowy creds — it reads this file.
BOARD_SNAPSHOT = Path(os.environ.get("KANBAN_BOARD_SNAPSHOT",
                                     "/app/snapshot/board-snapshot.json"))
# Read-only config mount — the model lanes + judge stages come from the real
# configs (no hardcoded model names), for the Router view.
CONFIGS_DIR = Path(os.environ.get("KANBAN_UI_CONFIGS", "/app/configs"))
# The kanban event log (source of truth for live board projection). Read-only here.
KANBAN_EVENT_LOG = Path(os.environ.get("KANBAN_EVENT_LOG", "/app/generated/kanban-events.jsonl"))

# Cline-style columns: live work first, terminal last. Any status the Ledger returns
# that isn't listed still shows under its own name (nothing is hidden).
MISSION_COLUMNS = ["awaiting_approval", "open", "approved", "running",
                   "blocked", "done", "killed", "failed"]

app = FastAPI(title="Agent Kanban UI", version="1.0.0")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    """Real liveness of each hop the console depends on (ok/error each) — for the
    topbar. No fabrication: a hop is 'ok' only if it actually answered."""
    hops: dict[str, str] = {}

    def probe(name: str, url: str) -> None:
        try:
            httpx.get(url, timeout=4)        # any HTTP response = reachable
            hops[name] = "ok"
        except httpx.HTTPError as exc:
            hops[name] = f"error: {type(exc).__name__}"

    probe("ledger", f"{LEDGER_BASE_URL}/health")
    if CHAT_ENABLED:
        litellm = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
        if litellm:
            probe("litellm", litellm.replace("/v1", "") + "/health/liveliness")
        appflowy = os.environ.get("APPFLOWY_BASE_URL", "").rstrip("/")
        if appflowy:
            probe("appflowy", appflowy)
    return {"hops": hops}


@app.get("/api/missions")
def missions() -> dict:
    """The execution kanban: Ledger missions grouped into columns. Ledger
    unreachable is surfaced as a 502 — never an empty board passed off as 'no work'."""
    try:
        r = httpx.get(f"{LEDGER_BASE_URL}/missions", timeout=15)
        r.raise_for_status()
        rows = r.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ledger unreachable: {exc}") from exc
    columns: dict[str, list] = {c: [] for c in MISSION_COLUMNS}
    for m in rows:
        columns.setdefault(m.get("status", "unknown"), []).append({
            "id": m.get("id"), "action": (m.get("action") or "").splitlines()[0][:120],
            "repo": m.get("repo", ""), "risk": m.get("risk", ""),
            "status": m.get("status", ""), "created_at": m.get("created_at", "")})
    ordered = [c for c in MISSION_COLUMNS if columns.get(c)]
    ordered += [c for c in columns if c not in MISSION_COLUMNS and columns[c]]
    return {"columns": [{"name": c, "cards": columns[c]} for c in ordered],
            "total": len(rows)}


@app.get("/api/mission/{mid}")
def mission(mid: str) -> dict:
    try:
        r = httpx.get(f"{LEDGER_BASE_URL}/mission/{mid}", timeout=15)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ledger error: {exc}") from exc
    return r.json()


@app.get("/api/metrics")
def metrics() -> dict:
    """Agent-surface observability — the same figures as `make kanban-digest`."""
    m = compute_metrics(load_calls())
    return {
        "log_file": str(log_path()),
        "total_calls": m.total_calls,
        "by_surface": m.by_surface,
        "error_rate": m.error_rate,
        "redundant_rate": m.redundant_rate,
        "board_mutations": m.board_mutations,
        "intent_verb_calls": m.intent_verb_calls,
        "generic_mutator_calls": m.generic_mutator_calls,
        "intent_verb_share": m.intent_verb_share,
        "per_tool": m.per_tool,
    }


@app.get("/api/boards")
def boards() -> dict:
    """The AppFlowy boards, from the worker-produced snapshot (mounted read-only).
    Missing snapshot is a loud 503 with the path — never an empty board set passed
    off as 'no boards'. Per-board read errors travel inside the snapshot."""
    if not BOARD_SNAPSHOT.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"board snapshot not found at {BOARD_SNAPSHOT}; "
                   "run `make kanban-board-snapshot` on the worker")
    return json.loads(BOARD_SNAPSHOT.read_text(encoding="utf-8"))


@app.get("/api/boards/live")
def boards_live() -> dict:
    """Read the AppFlowy boards LIVE — console only (the container has creds here),
    so a write reflects immediately instead of waiting for the next worker snapshot.
    503 when chat/creds aren't enabled. Per-board fail-loud travels in the payload."""
    from datetime import datetime, timezone

    from command_center.channels.board_state import all_boards_json
    _require_chat()
    _get_core("chat")   # ensure growthos is bootstrapped (sys.path + chdir)
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "live": True, "boards": all_boards_json()}


@app.get("/api/activity")
def activity(limit: int = 25) -> dict:
    """Recent agent actions across every surface — the Cline 'what is the agent
    doing' feed, straight from the agent-call log."""
    rows = recent_calls(limit)
    return {"calls": [{"ts": c.get("ts"), "surface": c.get("surface"),
                       "tool": c.get("tool"), "ok": c.get("ok", True),
                       "ms": c.get("ms"), "detail": c.get("detail", "")}
                      for c in reversed(rows)]}


@app.get("/api/models")
def models() -> dict:
    """The router/model lanes: roles → ranked local candidates + executors + judge
    stages, read from the mounted configs (no hardcoded model names — data-derived
    from models.yaml/judges.yaml). Missing config is a loud 503."""
    import yaml
    mp = CONFIGS_DIR / "models.yaml"
    if not mp.is_file():
        raise HTTPException(status_code=503, detail=f"models.yaml not at {mp}")
    m = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
    roles = [{"role": role, "candidates": [
                {"alias": c.get("alias"), "model": c.get("model"),
                 "priority": c.get("priority"),
                 "canary_weight": c.get("canary_weight", 0)} for c in cands]}
             for role, cands in (m.get("roles") or {}).items()]
    executors = [{"name": e.get("name"), "family": e.get("family"),
                  "priority": e.get("priority")}
                 for e in (m.get("executors") or [])]
    stages = []
    jp = CONFIGS_DIR / "judges.yaml"
    if jp.is_file():
        j = yaml.safe_load(jp.read_text(encoding="utf-8")) or {}
        stages = [{"stage": s.get("stage"),
                   "judges": [jj.get("name") for jj in (s.get("judges") or [])]}
                  for s in (j.get("stages") or [])]
    return {"roles": roles, "executors": executors, "judge_stages": stages}


@app.get("/api/config")
def config() -> dict:
    """What the SPA can do here: whether chat/writes are enabled, the model roles
    to pick from (data-derived), and where the signed Ledger actions live."""
    roles = []
    if CHAT_ENABLED:
        try:
            roles = [r["role"] for r in models()["roles"]]
        except HTTPException:
            roles = []
    return {"ledger_ui": os.environ.get("LEDGER_UI_URL", ""),
            "chat_enabled": CHAT_ENABLED, "model_roles": roles}


# ---- chat + governed writes (the console as a channel) --------------------
_cores: dict[str, object] = {}


def _role_names() -> set[str]:
    return {r["role"] for r in models()["roles"]}


def _get_core(model: str):
    """One GatewayCore per model role (cached) — the same loop Discord uses, so
    the in-app agent can chat AND drive the governed action verbs."""
    if model not in _cores:
        from command_center.channels.core import GatewayConfig, GatewayCore
        _cores[model] = GatewayCore(GatewayConfig.build(surface="app", model=model))
    return _cores[model]


def _require_chat() -> None:
    if not CHAT_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="chat/writes not enabled in this deployment "
                   "(set KANBAN_UI_CHAT_ENABLED=1 + mount growth-os/.env)")


class ChatIn(BaseModel):
    text: str
    conversation_id: str = "app"
    model: str = "chat"


class ActionIn(BaseModel):
    action: str
    params: dict = {}


def _validated_model(model: str) -> str:
    roles = _role_names()
    if model not in roles:
        raise HTTPException(status_code=400,
                            detail=f"unknown model role {model!r}; pick from {sorted(roles)}")
    return model


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict:
    """Talk to the agent in-app (it can move/assign via the governed verbs). Pick
    the model role per turn (validated against models.yaml — no free-form model)."""
    _require_chat()
    core = _get_core(_validated_model(body.model))
    reply = await core.run_turn(body.conversation_id, body.text)
    return {"reply": reply, "model": body.model}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn) -> StreamingResponse:
    """Same turn, streamed live (SSE): each round / tool call / tool result / final
    answer as it happens — 'watch what the LLM is doing now'."""
    _require_chat()
    core = _get_core(_validated_model(body.model))

    async def gen():
        async for ev in core.run_turn_events(body.conversation_id, body.text):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/action")
def action(body: ActionIn) -> dict:
    """Assign/move a task directly through a GOVERNED action verb (the action layer
    refuses Approved; L3/L4 stay signed and out of here). Unknown verb → 400."""
    _require_chat()
    if body.action not in ACTION_VERBS:
        raise HTTPException(status_code=400,
                            detail=f"verb {body.action!r} not allowed here; "
                                   f"governed verbs: {sorted(ACTION_VERBS)}")
    # route through the SAME logged dispatch the chat uses, so every console write
    # is recorded in the agent-call log under surface "app" (observable in Activity).
    core = _get_core("chat")
    return {"result": core.dispatch[body.action](**body.params)}


# ── Live board projection from the kanban event log (Level 1: immediate UI) ──
@app.get("/api/events/kanban/snapshot")
def kanban_snapshot() -> dict:
    """Folded current card state from the event log — the UI's initial board load."""
    cards = project_cards(EventLog(KANBAN_EVENT_LOG).read())
    return {"n_cards": len(cards), "cards": cards}


@app.get("/api/events/kanban")
def kanban_events(request: Request, since: int = 0) -> StreamingResponse:
    """SSE: emit kanban events with index >= cursor, then close.

    Each frame carries `id: <resume-offset>`, so the browser records it as
    Last-Event-ID and the auto-reconnect resumes exactly where it left off (no
    replay, no manual refresh). On reconnect the browser sends `Last-Event-ID`;
    we honour it over `?since`. A governed action on any surface (Discord/UI/SMS/
    DAG) shows up live. The UI never holds board authority — it only renders events.
    """
    header = request.headers.get("last-event-id")
    offset = int(header) if (header and header.lstrip("-").isdigit()) else since
    offset = max(0, offset)

    def gen():
        new, nxt = EventLog(KANBAN_EVENT_LOG).read_after(offset=offset)
        for i, ev in enumerate(new):
            yield f"id: {offset + i + 1}\ndata: {json.dumps(ev, default=str)}\n\n"
        # final cursor frame (also for non-EventSource pollers)
        yield f"event: cursor\nid: {nxt}\ndata: {json.dumps({'next': nxt})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# Serve the built SPA last so /api/* wins. Absent build dir (dev) → a clear note.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="spa")
else:
    @app.get("/")
    def _no_spa() -> JSONResponse:
        return JSONResponse(
            {"detail": f"SPA not built at {STATIC_DIR}; the API is live under /api/*"},
            status_code=200)
