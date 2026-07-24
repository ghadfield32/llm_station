"""First-party agent kanban + observability UI backend.

A convenience surface, NOT the policy layer (configs/ui.yaml / WebUIConfig). It
reads two sources that are reachable across the container boundary without coupling
to Growth OS and the first-party board store:

  * the Ledger (`LEDGER_BASE_URL`) — missions are the execution kanban, grouped by
    status into Cline-style columns;
  * the agent-call log (`GROWTHOS_AGENT_LOG`) — surfaced through the SAME
    command_center.kanban.metrics used by `make kanban-digest`, so the UI and the
    CLI digest can never disagree.

Full-console deployments can write through governed action verbs and validated
profile/domain config editors. Approving/killing a mission stays in the signed
Ledger endpoints; board writes still go through the governed action layer.
This keeps `external_write_policy: governed_by_ledger` true by construction.

The built SPA (static assets) is mounted at / when present (single-container mode).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import unicodedata
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

# Guarantee co-located sibling modules (agent_worker_client.py) import cleanly
# regardless of how app.py itself was loaded. `uvicorn app:app` gets this for
# free (sys.path[0] = the script's own directory), but
# `importlib.util.spec_from_file_location(...)` — how tests load this module —
# does NOT add its directory to sys.path automatically.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_worker_client import AgentWorkerClient, AgentWorkerUnavailable
from command_center.agent_sessions import spec_bridge
from command_center.kanban.metrics import (
    compute_metrics, load_calls, log_path, recent_calls)
from command_center.kanban_sync import EventLog, KanbanEvent, project_cards
from command_center.kanban_sync.events import emit_event, is_human_owned_status
from command_center.intake import (
    CaptureClassification,
    CaptureConversionConflict,
    CaptureEvent,
    CaptureRecord,
)
from command_center.write_locking import (
    BoardWriteLocked,
    application_memory_write_lock,
    exclusive_write_lock,
)
from command_center.work_graph import (
    RoutingCorrection,
    WorkEdge,
    WorkEvent,
    WorkItem,
    WorkPlanEdgeIn,
    WorkPlanIn,
    WorkPlanItemIn,
)

# Chat + governed writes turn the UI into a first-class CHANNEL (it embeds the same
# GatewayCore Discord uses). OFF by default so the read-only board deployment holds
# no creds; the full console enables it (KANBAN_UI_CHAT_ENABLED=1) and mounts
# growth-os + .env. L3/L4 approve/kill never reach here — only the action layer's
# governed verbs (which already refuse Approved).
CHAT_ENABLED = os.environ.get("KANBAN_UI_CHAT_ENABLED", "") == "1"
KANBAN_UI_TIMING_LOG = os.environ.get("KANBAN_UI_TIMING_LOG", "") == "1"
DOMAIN_CONFIG_WRITES = os.environ.get("KANBAN_UI_DOMAIN_CONFIG_WRITES", "") == "1"
# Phase 5 board-change APPLY (the wall crossing) is OFF by default. Turning it on
# is a DOUBLE opt-in: this flag AND a non-empty KANBAN_UI_HUMAN_OPERATORS (the
# server-authenticated approver allowlist). Preview is always available (it never
# writes); only apply is gated here. Fails closed.
BOARD_CHANGE_APPLY_ENABLED = os.environ.get("KANBAN_UI_BOARD_CHANGE_APPLY", "") == "1"
# Universal Capture — a benign, non-destructive intake list (no repo/Ledger/config
# side effects), so it defaults ON (opt-out). Captures are in-memory for now; a
# durable Ledger-backed store is the immediate follow-up.
CAPTURE_ENABLED = os.environ.get("KANBAN_UI_CAPTURE_ENABLED", "1") == "1"
# Durable capture: back the Inbox with the Ledger (survives restart) instead of
# the in-memory store. Off by default so a Ledger-less dev cockpit still works.
CAPTURE_LEDGER = os.environ.get("KANBAN_UI_CAPTURE_LEDGER", "") == "1"
# Canonical work graph (WorkItem/placement/edge). Benign in-memory list, no repo/
# Ledger/config side effects → defaults on. Durable Ledger persistence is Phase C-2.
WORKGRAPH_ENABLED = os.environ.get("KANBAN_UI_WORKGRAPH_ENABLED", "1") == "1"
# Durable work graph: back it with the Ledger (survives restart → the work-item
# ids are permanent enough for deep links). Off by default for a Ledger-less dev.
WORKGRAPH_LEDGER = os.environ.get("KANBAN_UI_WORKGRAPH_LEDGER", "") == "1"
# Durable Readiness Packets: back the packet store with the Ledger (survives
# restart; immutable revisions; committed packets frozen). Off by default.
PACKET_LEDGER = os.environ.get("KANBAN_UI_PACKET_LEDGER", "") == "1"
# Agent sessions (Claude Agent / Codex Agent) are a SEPARATE execution path from
# GatewayCore chat — proxied to the host worker (cc agent-worker), never
# constructed here, never sharing GatewayCore dispatch. OFF by default like
# every other write-capable surface. FAKE_AGENT is a second, narrower gate on
# top: even with agent sessions enabled, the FakeHarness dev/test double stays
# hidden from the picker unless explicitly opted into — it must never look
# like a real agent option in a normal deployment.
AGENT_SESSIONS_ENABLED = os.environ.get("KANBAN_UI_AGENT_SESSIONS_ENABLED", "") == "1"
FAKE_AGENT_ENABLED = os.environ.get("KANBAN_UI_FAKE_AGENT_ENABLED", "") == "1"
# Usage & Limits surface (the shared metering layer across chat models AND
# coding agents). Read-only. OFF by default like every other compute surface.
# The view is in-process, over either memory or the shared Ledger. In a real
# Ledger-backed agent deployment, provider refresh is proxied to the host worker
# because only that process owns the SDK and user login. USAGE_FAKE seeds the
# deterministic FakeCollector for a dev/demo page.
USAGE_ENABLED = os.environ.get("KANBAN_UI_USAGE_ENABLED", "") == "1"
USAGE_CODEX = os.environ.get("KANBAN_UI_USAGE_CODEX", "") == "1"
# Claude limits are EVENT-driven (fed from live agent-session rate_limit events,
# not polled), so this gate registers the two Claude usage lanes AND turns on the
# SSE usage tee (_feed_agent_usage).
USAGE_CLAUDE = os.environ.get("KANBAN_UI_USAGE_CLAUDE", "") == "1"
# Back the cockpit's UsageService with the durable Ledger (the SAME store the
# host worker writes to) instead of a per-process in-memory store — so the page
# survives a restart and reads the worker's headless-captured usage. Falls back
# to in-memory + the SSE tee when off (dev/test default).
USAGE_LEDGER = os.environ.get("KANBAN_UI_USAGE_LEDGER", "") == "1"
USAGE_FAKE = os.environ.get("KANBAN_UI_USAGE_FAKE", "") == "1"
AGENT_WORKER_URL = os.environ.get(
    "AGENT_WORKER_URL", "http://host.docker.internal:8791").rstrip("/")
AGENT_WORKER_TOKEN = os.environ.get("AGENT_WORKER_TOKEN", "")
# Governed write verbs the console may call directly (the action layer enforces the
# wall; Approved is structurally refused inside them). No Ledger approve/kill here.
ACTION_VERBS = frozenset({"stage_card", "block_card", "reject_card",
                          "start_todo", "finish_todo", "block_todo", "move_item",
                          "annotate_item", "set_item_field",
                          "remove_item_field_value"})

STARTUP_CWD = Path.cwd().resolve()


def _env_path(name: str, default: str) -> Path:
    raw = os.environ.get(name, default)
    path = Path(raw).expanduser()
    if path.is_absolute() or path.anchor:
        return path.resolve()
    return (STARTUP_CWD / path).resolve()


LEDGER_BASE_URL = os.environ.get("LEDGER_BASE_URL", "http://ledger:8090").rstrip("/")
STATIC_DIR = _env_path("KANBAN_UI_STATIC", "/app/static")
# The first-party board snapshot, produced on the worker (`make kanban-board-snapshot`)
# and mounted read-only here. The UI reads this file without any external board credentials.
BOARD_SNAPSHOT = _env_path("KANBAN_BOARD_SNAPSHOT",
                           "/app/snapshot/board-snapshot.json")
# Read-only config mount — the model lanes + judge stages come from the real
# configs (no hardcoded model names), for the Router view.
CONFIGS_DIR = _env_path("KANBAN_UI_CONFIGS", "/app/configs")
# The kanban event log (source of truth for live board projection). Read-only here.
KANBAN_EVENT_LOG = _env_path("KANBAN_EVENT_LOG", "/app/generated/kanban-events.jsonl")
# Durable append-only evidence log for the executor-ranking leaderboard. Each
# line is one EvidenceSample {executor, dimension_id, value, sample_size,
# source}; producers (assistant-verify, mission outcomes, usage) append, the
# leaderboard reads. Read-only here.
LEADERBOARD_EVIDENCE = _env_path(
    "KANBAN_UI_LEADERBOARD_EVIDENCE",
    str(KANBAN_EVENT_LOG.with_name("leaderboard-evidence.jsonl")))
# The executors shown on the leaderboard even before evidence exists (so the
# matrix renders with honest "insufficient evidence" cells). Mirrors the harness
# registry + the local completion route.
_LEADERBOARD_EXECUTORS = ("claude_code_local", "codex_agent", "openrouter_agent",
                          "gatewaycore")
CHAT_THREADS_FILE = _env_path(
    "KANBAN_CHAT_THREADS",
    str(KANBAN_EVENT_LOG.with_name("chat-threads.json")),
)
FRONTIER_USAGE_LEDGER = _env_path(
    "FRONTIER_ROUTER_USAGE_LEDGER",
    str(KANBAN_EVENT_LOG.with_name("frontier-router-usage.jsonl")),
)
LOCAL_FRONTIER_USAGE_LEDGER = _env_path(
    "LOCAL_FRONTIER_USAGE_LEDGER",
    str(KANBAN_EVENT_LOG.with_name("local-frontier-usage.jsonl")),
)

# Cline-style columns: live work first, terminal last. Any status the Ledger returns
# that isn't listed still shows under its own name (nothing is hidden).
MISSION_COLUMNS = ["awaiting_approval", "open", "approved", "running",
                   "blocked", "done", "killed", "failed"]


app = FastAPI(title="Agent Kanban UI", version="1.0.0")
logger = logging.getLogger(__name__)

if KANBAN_UI_TIMING_LOG:
    class _RouteTiming:
        __slots__ = ("count", "total_ms", "max_ms", "samples")

        def __init__(self) -> None:
            self.count = 0
            self.total_ms = 0.0
            self.max_ms = 0.0
            self.samples: deque[float] = deque(maxlen=500)

    class _TimingRollup:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._routes: dict[str, _RouteTiming] = {}

        def record(self, route: str, duration_ms: float) -> None:
            with self._lock:
                timing = self._routes.setdefault(route, _RouteTiming())
                timing.count += 1
                timing.total_ms += duration_ms
                timing.max_ms = max(timing.max_ms, duration_ms)
                timing.samples.append(duration_ms)

        def snapshot(self) -> dict[str, dict[str, float | int]]:
            with self._lock:
                result = {}
                for route, timing in self._routes.items():
                    samples = sorted(timing.samples)
                    result[route] = {
                        "count": timing.count,
                        "p50_ms": self._percentile(samples, 50),
                        "p95_ms": self._percentile(samples, 95),
                        "max_ms": timing.max_ms,
                    }
                return result

        @staticmethod
        def _percentile(samples: list[float], percentile: int) -> float:
            index = max(0, (len(samples) * percentile + 99) // 100 - 1)
            return samples[index]

    app.state.timing_rollup = _TimingRollup()

    @app.middleware("http")
    async def _request_timing(request: Request, call_next):
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or request.url.path
            app.state.timing_rollup.record(route_path, duration_ms)
            logger.info(json.dumps({
                "duration_ms": round(duration_ms, 3),
                "event": "request_timing",
                "method": request.method,
                "route": route_path,
                "status_code": status_code,
            }, separators=(",", ":"), sort_keys=True))

    @app.get("/api/debug/timings")
    def timing_debug() -> dict[str, dict[str, float | int]]:
        return app.state.timing_rollup.snapshot()

_PRIVATE_JOB_MEMORY_PREFIXES = (
    "/api/job-search/relationships",
    "/api/job-search/question-library",
    "/api/job-search/profile-controls",
)
_PRIVATE_HISTORY_PREFIXES = (
    "/api/todos",
    "/api/captures",
    "/api/intake/inbox",
    "/api/work-items",
    "/api/work-edges",
    "/api/work-graph",
    "/api/work/",
)


def _is_private_job_memory_request(request: Request) -> bool:
    path = request.url.path
    return (
        path.startswith(_PRIVATE_JOB_MEMORY_PREFIXES)
        or (path.startswith("/api/job-search/cards/")
            and path.endswith("/outreach"))
        or (path.startswith("/api/domain/job_application/card/")
            and path.endswith("/note"))
    )


def _is_private_history_request(request: Request) -> bool:
    return request.url.path.startswith(_PRIVATE_HISTORY_PREFIXES)


def _is_no_store_request(request: Request) -> bool:
    return (
        _is_private_job_memory_request(request)
        or _is_private_history_request(request)
    )


@app.middleware("http")
async def _private_job_memory_no_store(request: Request, call_next):
    """Prevent browser/proxy caching for personal answers, notes, and contacts."""
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - private failures must also be non-cacheable
        if not _is_no_store_request(request):
            raise
        logger.exception("Unhandled private-history request failure")
        return JSONResponse(
            status_code=500,
            content={"detail": "private history request failed"},
            headers={"Cache-Control": "no-store"},
        )
    if _is_no_store_request(request):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def _private_validation_error_handler(
    request: Request, exc: RequestValidationError,
):
    if _is_private_job_memory_request(request):
        return JSONResponse(
            status_code=422,
            content={"detail": "invalid private job-search memory request"},
            headers={"Cache-Control": "no-store"},
        )
    response = await request_validation_exception_handler(request, exc)
    if _is_private_history_request(request):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def _private_http_error_handler(request: Request, exc: HTTPException):
    response = await http_exception_handler(request, exc)
    if _is_no_store_request(request):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(BoardWriteLocked)
async def _board_write_locked_handler(
    _request: Request, _exc: BoardWriteLocked,
) -> JSONResponse:
    return JSONResponse(
        status_code=423,
        content={
            "detail": (
                "Another writer is updating this board. No card was changed; "
                "retry after that write finishes."
            )
        },
        headers={"Retry-After": "2"},
    )


@app.exception_handler(CaptureConversionConflict)
async def _capture_conversion_conflict_handler(
    _request: Request, exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc)},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


def _http_probe(url: str, *, timeout: float = 4.0) -> dict:
    try:
        r = httpx.get(url, timeout=timeout)
        return {"ok": True, "status_code": r.status_code, "url": url}
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "url": url,
        }


def _dns_probe(url: str) -> dict:
    host = urlsplit(url).hostname
    if not host:
        return {"ok": False, "host": "", "error": "URL has no hostname"}
    try:
        infos = socket.getaddrinfo(host, None)
        addresses = sorted({item[4][0] for item in infos})
        return {"ok": True, "host": host, "addresses": addresses}
    except socket.gaierror as exc:
        return {"ok": False, "host": host, "error": str(exc)}


def _path_info(path: Path) -> dict:
    parent = path if path.is_dir() else path.parent
    return {"path": str(path), "exists": path.exists(), "is_file": path.is_file(),
            "is_dir": path.is_dir(), "writable": os.access(path, os.W_OK),
            "parent_writable": os.access(parent, os.W_OK)}


def _job_search_data_info() -> dict:
    try:
        from command_center.job_search.config import data_root, load_config

        return _path_info(data_root(load_config()))
    except Exception as exc:
        return {"error_type": type(exc).__name__, "error": str(exc)}


@app.get("/api/status")
def status() -> dict:
    """Real liveness of each hop the console depends on (ok/error each) — for the
    topbar. No fabrication: a hop is 'ok' only if it actually answered."""
    hops: dict[str, str] = {}
    targets: dict[str, str] = {}

    def probe(name: str, url: str) -> None:
        targets[name] = url
        result = _http_probe(url)
        hops[name] = "ok" if result["ok"] else f"error: {result['error_type']}"

    probe("ledger", f"{LEDGER_BASE_URL}/health")
    if CHAT_ENABLED:
        litellm = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
        if litellm:
            probe("litellm", litellm.replace("/v1", "") + "/health/liveliness")

    if AGENT_SESSIONS_ENABLED:
        probe("agent_worker", f"{AGENT_WORKER_URL}/health")
    return {"hops": hops, "targets": targets}


@app.get("/api/debug/runtime")
def runtime_debug() -> dict:
    """Non-secret runtime diagnostics for local setup issues.

    This is intentionally explicit rather than forgiving: it reports the exact
    URLs and mounted paths the service is using so operator mistakes show up as
    data, not as blank boards.
    """
    ledger_health_url = f"{LEDGER_BASE_URL}/health"
    agent_worker_health_url = f"{AGENT_WORKER_URL}/health"
    return {
        "mode": {
            "chat_enabled": CHAT_ENABLED,
            "cwd": str(Path.cwd()),
            "startup_cwd": str(STARTUP_CWD),
        },
        # AGENT_WORKER_TOKEN is deliberately absent from this block (and from
        # every other response this service returns) — see agent_worker_client.py.
        "agent_sessions": {
            "enabled": AGENT_SESSIONS_ENABLED,
            "fake_agent_enabled": FAKE_AGENT_ENABLED,
            "worker_url": AGENT_WORKER_URL,
            "worker_token_configured": bool(AGENT_WORKER_TOKEN),
            "health": (_http_probe(agent_worker_health_url)
                      if AGENT_SESSIONS_ENABLED else None),
        },
        "ledger": {
            "base_url": LEDGER_BASE_URL,
            "health_url": ledger_health_url,
            "dns": _dns_probe(LEDGER_BASE_URL),
            "health": _http_probe(ledger_health_url),
            "host_run_hint": (
                "When running uvicorn on the Windows host, use "
                "LEDGER_BASE_URL=http://127.0.0.1:8091. "
                "http://ledger:8090 is the Docker Compose service URL."
            ),
        },
        "paths": {
            "static_dir": _path_info(STATIC_DIR),
            "board_snapshot": _path_info(BOARD_SNAPSHOT),
            "configs_dir": _path_info(CONFIGS_DIR),
            "kanban_event_log": _path_info(KANBAN_EVENT_LOG),
            "chat_threads": _path_info(CHAT_THREADS_FILE),
            "board_store_dir": _path_info(BOARD_STORE_DIR),
            "fixtures_file": _path_info(FIXTURES_FILE),
            "job_search_data": _job_search_data_info(),
        },
    }


@app.get("/api/missions")
def missions() -> dict:
    """The execution kanban: Ledger missions grouped into columns. Ledger
    unreachable is surfaced as a 502 — never an empty board passed off as 'no work'."""
    url = f"{LEDGER_BASE_URL}/missions"
    try:
        r = httpx.get(url, timeout=15)
        r.raise_for_status()
        rows = r.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"ledger unreachable at {url}: {exc}") from exc
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
    url = f"{LEDGER_BASE_URL}/mission/{mid}"
    try:
        r = httpx.get(url, timeout=15)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ledger error at {url}: {exc}") from exc
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
    """The workspace boards, from the worker-produced snapshot (mounted read-only).
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
    """Read the workspace boards LIVE from the mounted local store — console only,
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


# ── Typed domain surfaces (configs/domain_surfaces.yaml) ────────────────────
# Each domain binds a card grammar to a data source: a command_center_ui board's
# card store (event-log fold = status truth), the Ledger's missions, or the
# committed demo fixtures. Origin always travels in the payload — fixture data
# can never masquerade as live data.
FIXTURES_FILE = _env_path(
    "KANBAN_UI_FIXTURES", str(Path(__file__).parent / "domain_fixtures.json"))
BOARD_STORE_DIR = _env_path("KANBAN_BOARD_STORE", "/app/generated/boards")
WATCHER_STATUS_FILE = _env_path(
    "GROWTHOS_WATCHER_STATUS", "/app/watcher-state/watcher_status.json")
RESEARCH_REFRESH_FILE = _env_path(
    "GROWTHOS_RESEARCH_REFRESH", "/app/watcher-state/research_refresh.json")
GRAND_TODO_SOURCE = _env_path(
    "BETTS_GRAND_TODO_SOURCE",
    "/workspace/betts_basketball/docs/backend/projects/GRAND_TODO_LIST.md",
)
# Container-path default like BETTS_GRAND_TODO_SOURCE above; host runs and
# tests set the env var (the image flattens app.py to /app/app.py, so no
# repo-relative default is derivable from __file__ here).
MASTER_GRAND_TODO_SOURCE = _env_path(
    "MASTER_GRAND_TODO_SOURCE", "/app/docs/todos/GRAND_TODO_LIST.md",
)
# Source-projected grand-todo boards: canonical Markdown per domain. Both are
# merge-only projections of their file; generic todo routing must never place
# cards on them.
GRAND_TODO_DOMAIN_IDS = frozenset({"betts_basketball_grand_todo", "grand_todo"})


def _grand_todo_source(domain_id: str) -> Path:
    # Read the module attribute at call time so tests and operators can
    # repoint a single source without rebuilding any lookup table.
    if domain_id == "betts_basketball_grand_todo":
        return GRAND_TODO_SOURCE
    if domain_id == "grand_todo":
        return MASTER_GRAND_TODO_SOURCE
    raise HTTPException(
        status_code=400,
        detail=f"domain {domain_id!r} has no canonical grand-todo source")


@app.get("/api/upkeep/status")
def upkeep_status() -> dict:
    if not WATCHER_STATUS_FILE.is_file():
        raise HTTPException(
            status_code=503,
            detail="Growth OS watcher has not completed an observable cycle yet",
        )
    value = json.loads(WATCHER_STATUS_FILE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail="watcher status is not an object")
    return value


def _config_module_lock():
    return exclusive_write_lock(
        CONFIGS_DIR / ".locks" / "board-module-config.write.lock")


def _research_refresh_lock():
    return exclusive_write_lock(
        RESEARCH_REFRESH_FILE.parent / ".research-refresh.write.lock")


def _config_intent_path() -> Path:
    return CONFIGS_DIR / ".transactions" / "board-module.json"


def _board_change_rollback_path(ref: str) -> Path:
    """Durable rollback point for an applied board change (persisted `before`
    bytes, keyed by the proposal's rollback_ref). Segment-sanitized so a ref can
    never escape the rollback dir."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", ref)
    return CONFIGS_DIR / ".board-change-rollback" / f"{safe}.json"


def _spent_nonce_path() -> Path:
    """Durable single-use ledger for §8 approval-token nonces — a spent nonce is
    never accepted again, so a token can't be replayed even across a restart."""
    return CONFIGS_DIR / ".board-change-rollback" / "spent-nonces.txt"


def _spent_nonces() -> set[str]:
    p = _spent_nonce_path()
    if not p.is_file():
        return set()
    return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _record_spent_nonce(nonce: str) -> None:
    p = _spent_nonce_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(nonce + "\n")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably replace one config/journal file without exposing partial YAML."""
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_config_directory(path.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _fsync_config_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _unlink_config_intent(path: Path) -> None:
    path.unlink()
    _fsync_config_directory(path.parent)


def _yaml_bytes(data: dict[str, Any]) -> bytes:
    import yaml

    return yaml.safe_dump(data, sort_keys=False).encode("utf-8")


def _read_config_direct(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _read_yaml_file(path)


def _reconcile_config_intent_locked() -> None:
    """Finish or abandon an interrupted two-config board-module transaction.

    The intent is written before either config. A later reader can therefore
    distinguish the exact before/after states. Unknown third-party divergence
    fails closed instead of being overwritten by recovery.
    """
    intent_path = _config_intent_path()
    if not intent_path.is_file():
        return
    try:
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        before_reg = intent["before_registry"]
        before_dom = intent["before_domains"]
        after_reg = intent["after_registry"]
        after_dom = intent["after_domains"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="board-module config transaction journal is unreadable; "
                   "operator inspection is required",
        ) from exc

    reg_path = _kanban_boards_path()
    dom_path = _domain_config_path()
    current_reg = _read_config_direct(reg_path)
    current_dom = _read_config_direct(dom_path)
    reg_state = (
        "before" if current_reg == before_reg
        else "after" if current_reg == after_reg else "other")
    dom_state = (
        "before" if current_dom == before_dom
        else "after" if current_dom == after_dom else "other")
    if "other" in {reg_state, dom_state}:
        raise HTTPException(
            status_code=503,
            detail="board-module config recovery found an unrelated concurrent "
                   "edit; no file was overwritten",
        )
    if reg_state == dom_state == "before":
        _unlink_config_intent(intent_path)
        return
    if reg_state != "after":
        _atomic_write_bytes(reg_path, _yaml_bytes(after_reg))
    if dom_state != "after":
        _atomic_write_bytes(dom_path, _yaml_bytes(after_dom))
    _unlink_config_intent(intent_path)


def _require_stable_config_read() -> None:
    """Fail read-only config access while an explicit write recovery is pending."""
    if _config_intent_path().is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "board-module config transaction recovery is pending; "
                "run a governed config write/recovery operation"
            ),
        )


def _domain_config() -> dict:
    _require_stable_config_read()
    dp = _domain_config_path()
    if not dp.is_file():
        raise HTTPException(
            status_code=503, detail=f"domain_surfaces.yaml not at {dp}")
    data = _read_yaml_file(dp)
    _require_stable_config_read()
    _validate_domain_config(data, status_code=503)
    return data


def _domain_config_path() -> Path:
    return CONFIGS_DIR / "domain_surfaces.yaml"


def _validate_domain_config(data: dict[str, Any], *, status_code: int = 400) -> None:
    from command_center.schemas.contracts import DomainSurfacesConfig

    try:
        DomainSurfacesConfig.model_validate(data)
    except Exception as exc:
        raise HTTPException(
            status_code=status_code,
            detail=f"invalid domain_surfaces.yaml: {exc}",
        ) from exc


def _domain_config_write_blocker() -> str | None:
    path = _domain_config_path()
    if not CHAT_ENABLED:
        return "chat/writes not enabled in this deployment"
    if not DOMAIN_CONFIG_WRITES:
        return "domain config writes disabled; set KANBAN_UI_DOMAIN_CONFIG_WRITES=1"
    if path.exists():
        if not os.access(path, os.W_OK):
            return f"domain config is not writable: {path}"
    elif not os.access(path.parent, os.W_OK):
        return f"domain config parent is not writable: {path.parent}"
    return None


def _require_domain_config_writable() -> None:
    blocker = _domain_config_write_blocker()
    if blocker:
        raise HTTPException(status_code=503, detail=blocker)


def _require_profile_writable() -> None:
    """Profile-controls YAML writes carry the same discipline as the domain
    config editor: chat alone is not enough — the deployment must opt into
    config writes (KANBAN_UI_DOMAIN_CONFIG_WRITES=1)."""
    _require_chat()
    if not DOMAIN_CONFIG_WRITES:
        raise HTTPException(
            status_code=503,
            detail="profile writes disabled; set KANBAN_UI_DOMAIN_CONFIG_WRITES=1")


def _domain_schema_response(data: dict[str, Any] | None = None) -> dict:
    data = data if data is not None else _domain_config()
    path = _domain_config_path()
    blocker = _domain_config_write_blocker()
    return {
        "schema_version": data.get("schema_version"),
        "config_path": str(path),
        "config_writable": os.access(path, os.W_OK),
        "writable": blocker is None,
        "write_gate": "enabled" if blocker is None else blocker,
        "domains": data.get("domains", []),
    }


def _clean_domain_surface(domain: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(domain)
    cleaned["domain_id"] = str(cleaned.get("domain_id", "")).strip()
    cleaned["title"] = str(cleaned.get("title", "")).strip()
    cleaned["card_component"] = str(cleaned.get("card_component", "generic_task")).strip()
    cleaned["source"] = str(cleaned.get("source", "fixtures")).strip()
    if cleaned["source"] != "board_store":
        cleaned.pop("board_id", None)
    elif cleaned.get("board_id") is not None:
        cleaned["board_id"] = str(cleaned.get("board_id", "")).strip()
    cleaned["columns"] = [
        str(column).strip() for column in cleaned.get("columns", []) if str(column).strip()
    ]
    cleaned["allowed_actions"] = [
        str(action).strip() for action in cleaned.get("allowed_actions", [])
        if str(action).strip()
    ]
    cleaned["column_actions"] = {
        str(column).strip(): str(action).strip()
        for column, action in (cleaned.get("column_actions") or {}).items()
        if str(column).strip() and str(action).strip()
    }
    cleaned["summary_fields"] = [
        {k: v for k, v in field.items() if v not in (None, "")}
        for field in cleaned.get("summary_fields", [])
        if isinstance(field, dict)
    ]
    cleaned["drawer_fields"] = [
        {k: v for k, v in field.items() if v not in (None, "")}
        for field in cleaned.get("drawer_fields", [])
        if isinstance(field, dict)
    ]
    cleaned["empty_state"] = dict(cleaned.get("empty_state") or {})
    from command_center.schemas.contracts import DomainIntakeSpec
    cleaned["intake"] = DomainIntakeSpec.model_validate(
        cleaned.get("intake") or {}).model_dump(mode="json")
    return cleaned


def _write_domain_config(data: dict[str, Any]) -> dict:
    _require_domain_config_writable()
    with _config_module_lock():
        _reconcile_config_intent_locked()
        _validate_domain_config(data)
        _write_yaml_file(_domain_config_path(), data)
        return _domain_schema_response(data)


def _domain_spec(domain_id: str) -> dict:
    for d in _domain_config().get("domains", []):
        if d.get("domain_id") == domain_id:
            return d
    raise HTTPException(status_code=404, detail=f"unknown domain {domain_id!r}")


# ── Board-module create (kanban board + domain surface, crash-recoverable) ────
def _kanban_boards_path() -> Path:
    return CONFIGS_DIR / "kanban_boards.yaml"


def _read_board_registry_data() -> dict[str, Any]:
    _require_stable_config_read()
    path = _kanban_boards_path()
    if not path.is_file():
        return {"schema_version": "command-center.kanban-boards.v1", "boards": []}
    data = _read_yaml_file(path)
    _require_stable_config_read()
    _validate_board_registry(data, status_code=503)
    return data


def _validate_board_registry(data: dict[str, Any], *, status_code: int = 400) -> None:
    from command_center.schemas.contracts import KanbanBoardsConfig
    try:
        KanbanBoardsConfig.model_validate(data)
    except Exception as exc:
        raise HTTPException(
            status_code=status_code,
            detail=f"invalid kanban_boards.yaml: {exc}") from exc


# governance defaults for a new internal board — the human wall is FIXED here
_KANBAN_STATUS_LABELS = {
    "backlog": "Backlog", "ready": "Ready", "in_progress": "In Progress",
    "done": "Done", "blocked": "Blocked", "rejected": "Rejected",
    "awaiting_approval": "Awaiting Approval"}
_KANBAN_ALLOWED_VERBS = ["add_mission_card", "stage_card", "start_todo",
                         "finish_todo", "block_card", "reject_card"]
_KANBAN_WALL_VERBS = ["approve_card", "merge", "deploy", "delete_card", "delete_board"]
_KANBAN_COLUMN_ACTIONS = {
    "Backlog": "add_mission_card",
    "Ready": "stage_card",
    "In Progress": "start_todo",
    "Done": "finish_todo",
    "Blocked": "block_card",
    "Rejected": "reject_card",
    "Awaiting Approval": "stage_card",
}


def _slug_board_id(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (title or "").strip().lower()).strip("_")
    return slug


def _audit_config_write(action: str, detail: dict[str, Any]) -> None:
    """Append an audit record for a config-mutating write. Best-effort JSONL next
    to the configs — the create is the source of truth, so a failed audit must not
    fail the create, but every board-module create is recorded here."""
    from datetime import datetime, timezone
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "action": action, **detail}
    try:
        with (CONFIGS_DIR / "config_audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _routable_work_boards() -> list[dict[str, Any]]:
    """Validated generic boards whose lane labels reversibly map WorkItem state."""
    domains = _domain_config().get("domains", [])
    registry = _read_board_registry_data()
    _validate_board_registry(registry, status_code=503)
    board_specs = {
        str(board.get("board_id")): board for board in registry.get("boards", [])
    }
    routable: list[dict[str, Any]] = []
    for domain in domains:
        board_id = str(domain.get("board_id") or "")
        board = board_specs.get(board_id)
        if (
            domain.get("archived") is True
            or
            domain.get("source") != "board_store"
            or domain.get("card_component") != "generic_task"
            or domain.get("domain_id") in GRAND_TODO_DOMAIN_IDS
            or not board
            or board.get("provider") != "command_center_ui"
        ):
            continue
        mapping = dict(board.get("status_mapping") or {})
        labels = list(mapping.values())
        columns = list(domain.get("columns") or [])
        if (
            not mapping
            or len(set(labels)) != len(labels)
            or set(columns) != set(labels)
        ):
            continue
        routable.append({
            "board_id": board_id,
            "domain_id": str(domain.get("domain_id")),
            "title": str(domain.get("title") or board_id),
            "columns": columns,
            "status_mapping": mapping,
        })
    return sorted(routable, key=lambda row: (row["title"].casefold(), row["board_id"]))


def _routable_board_for_spec(spec: dict) -> dict[str, Any] | None:
    return next(
        (
            board for board in _routable_work_boards()
            if board["board_id"] == spec.get("board_id")
            and board["domain_id"] == spec.get("domain_id")
        ),
        None,
    )


def _projected_work_cards(spec: dict) -> list[dict[str, Any]]:
    board = _routable_board_for_spec(spec)
    if board is None or not WORKGRAPH_ENABLED:
        return []
    service = _get_workgraph_service()
    mapping = board["status_mapping"]
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for placement in service._store.placements_on_board(board["board_id"]):
        if placement.domain_id != board["domain_id"]:
            continue
        if placement.work_item_id in seen:
            continue
        seen.add(placement.work_item_id)
        item = service.get_item(placement.work_item_id)
        cards.append({
            "card_id": f"work-{item.work_item_id}",
            "board_id": board["board_id"],
            "work_item_id": item.work_item_id,
            "projection_source": "work_graph",
            "title": item.title,
            "description": item.description,
            "notes": item.description,
            "kind": item.kind,
            "status": mapping.get(item.canonical_status, "Unstaged"),
            "canonical_status": item.canonical_status,
            "priority": item.priority,
            "due": item.due_at,
            "due_at": item.due_at,
            "owner": item.owner,
            "capture_id": item.capture_id,
            "conversation_id": item.conversation_id,
            "mission_id": item.mission_id,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        })
    return cards


_RESEARCH_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}]+", re.IGNORECASE)
_CODE_LINK_HOSTS = ("github.com/", "gitlab.com/", "codeberg.org/")


def _research_source_links(
    card: dict[str, Any], source_cells: dict[str, Any], component: str,
) -> tuple[list[str], list[str]]:
    """Recover links only from stored source values; never from model analysis."""
    values: list[Any] = [
        card.get("url"), card.get("URL"), card.get("abstract"),
        card.get("why"), card.get("description"),
        source_cells,
    ]
    pending = list(values)
    urls: list[str] = []
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            for match in _RESEARCH_URL_RE.findall(value):
                url = match.rstrip(".,;:")
                if url and url not in urls:
                    urls.append(url)
    primary = str(card.get("url") or card.get("URL") or "").strip()
    related = [url for url in urls if url != primary]
    code = [
        url for url in urls
        if any(host in url.lower() for host in _CODE_LINK_HOSTS)
    ]
    if component == "repo" and primary and primary not in code:
        code.insert(0, primary)
    return code[:8], related[:12]


_BOARD_AUDIT_HISTORY_FIELDS = frozenset({
    "appflowy_source_cells",
    "appflowy_revisions",
    "appflowy_last_imported_fields",
    "source_revisions",
    "sync_conflicts",
})


def _empty_research_import(card: dict[str, Any]) -> bool:
    """Identify audit-retained rows that contain no research source identity.

    These are legacy empty database rows, not papers/repos. They remain in the
    immutable board store for recovery/audit, but must not render as blank
    Kanban cards or make complete-analysis progress permanently impossible.
    """
    def present(value: Any) -> bool:
        if isinstance(value, dict):
            return any(present(item) for item in value.values())
        if isinstance(value, list):
            return any(present(item) for item in value)
        if isinstance(value, bool) or value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        return bool(str(value).strip())

    source_cells = card.get("appflowy_source_cells")
    research_source_fields = {
        "name", "title", "url", "arxivid", "repoid", "abstract", "why",
        "description", "authors", "owner", "topics", "suggested", "language",
        "notes", "comment", "journalref", "doi",
    }
    if isinstance(source_cells, dict) and any(
        present(value)
        for key, value in source_cells.items()
        if str(key).replace("_", "").casefold() in research_source_fields
    ):
        return False
    meaningful_fields = (
        "title", "Title", "Name", "url", "URL", "arxiv_id", "repo_id",
        "abstract", "why", "description", "authors", "owner", "doi",
        "code_links", "related_links",
    )
    for field in meaningful_fields:
        value = card.get(field)
        if present(value):
            return False
    return True


def _domain_cards(spec: dict) -> dict:
    source = spec.get("source")
    if source == "fixtures":
        fixtures = {}
        if FIXTURES_FILE.is_file():
            fixtures = json.loads(FIXTURES_FILE.read_text(encoding="utf-8"))
        return {"origin": "fixtures",
                "cards": fixtures.get(spec["domain_id"], [])}
    if source == "board_store":
        from command_center.boards.command_center_provider import (
            CommandCenterBoardProvider)
        provider = CommandCenterBoardProvider(
            board_id=spec["board_id"], event_log=EventLog(KANBAN_EVENT_LOG),
            store_dir=BOARD_STORE_DIR)
        configured_topics = list(
            (spec.get("intake") or {}).get("parameters", {}).get(
                "review_topics", []))
        def public_card(card: dict[str, Any]) -> dict[str, Any]:
            component = str(spec.get("card_component") or "")
            if component == "book":
                return _public_book_card(card)
            public = {
                key: value for key, value in card.items()
                if key not in _BOARD_AUDIT_HISTORY_FIELDS
            }
            if component not in {"paper", "repo"}:
                return public
            canonical = str(card.get("title") or "").strip()
            source_cells = card.get("appflowy_source_cells")
            source_cells = source_cells if isinstance(source_cells, dict) else {}
            recovered = str(
                card.get("Title") or card.get("Name")
                or source_cells.get("Title") or source_cells.get("Name") or ""
            ).strip()
            if canonical:
                public["title"] = canonical
                public["title_integrity"] = "canonical"
            elif recovered:
                # Presentation-only recovery from exact retained provenance.
                # Historical source files remain immutable; a migration rerun
                # may later repair the canonical field under its own audit lock.
                public["title"] = recovered
                public["title_integrity"] = "recovered_from_source"
            else:
                public["title"] = ""
                public["title_integrity"] = "missing"
            if not public.get("useful_for_us") and public.get("suggested"):
                public["useful_for_us"] = public["suggested"]
            code_links, related_links = _research_source_links(
                card, source_cells, component)
            if not public.get("code_links"):
                public["code_links"] = code_links
            if not public.get("related_links"):
                public["related_links"] = related_links
            public.setdefault("analysis_status", "not_analyzed")
            from command_center.research_topics import matching_research_topics
            stored_topics = public.get("review_topics")
            stored_topics = stored_topics if isinstance(stored_topics, list) else []
            topic_text = "\n".join(str(value or "") for value in (
                public.get("title"), public.get("abstract"), public.get("why"),
                public.get("useful_for"), public.get("topics"),
            ))
            derived_topics = matching_research_topics(topic_text, configured_topics)
            public["review_topics"] = [
                topic for topic in configured_topics
                if topic in stored_topics or topic in derived_topics
            ]
            return public

        stored_cards = provider.list_cards()
        quarantined_empty = (
            [card for card in stored_cards if _empty_research_import(card)]
            if str(spec.get("card_component") or "") in {"paper", "repo"}
            else []
        )
        quarantined_ids = {
            str(card.get("card_id")) for card in quarantined_empty
        }
        cards = [
            public_card(card) for card in stored_cards
            if str(card.get("card_id")) not in quarantined_ids
        ]
        by_id = {str(card.get("card_id")): card for card in cards}
        for projected in _projected_work_cards(spec):
            projected_id = str(projected["card_id"])
            existing = by_id.get(projected_id)
            if existing is None:
                cards.append(projected)
                by_id[projected_id] = projected
                continue
            if existing.get("work_item_id") == projected.get("work_item_id"):
                cards[cards.index(existing)] = projected
                by_id[projected_id] = projected
                continue
            conflict = dict(projected)
            conflict["card_id"] = f"{projected_id}-projection-conflict"
            conflict["projection_conflict_with"] = projected_id
            conflict["status"] = "Unstaged"
            cards.append(conflict)
        out = {"origin": "board_store", "board_id": spec["board_id"],
               "cards": cards}
        if quarantined_empty:
            out["data_quality"] = {
                "quarantined_empty_imports": len(quarantined_empty),
                "retained_in_store": True,
                "reason": (
                    "No title, source identifier, URL, summary, or retained "
                    "source cells were available."
                ),
            }
        if spec.get("domain_id") in GRAND_TODO_DOMAIN_IDS:
            source_file = _grand_todo_source(str(spec.get("domain_id")))
            projected_sha = next((
                str(card.get("source_sha256"))
                for card in cards
                if card.get("source_kind") == "source_document"
                and card.get("source_sha256")
            ), "")
            if source_file.is_file():
                source_sha = hashlib.sha256(source_file.read_bytes()).hexdigest()
                sync_state = (
                    "current" if projected_sha == source_sha
                    else "stale" if projected_sha else "not_imported")
            else:
                source_sha = ""
                sync_state = "source_unavailable"
            out["source_sync"] = {
                "state": sync_state,
                "source_available": bool(source_sha),
                "source_sha256": source_sha,
                "projected_sha256": projected_sha,
                "write_on_read": False,
            }
        return out
    if source == "ledger_missions":
        data = missions()   # 502s loudly if the Ledger is down — never fabricated
        cards = [dict(c, status=col["name"], card_id=c.get("id"))
                 for col in data["columns"] for c in col["cards"]]
        return {"origin": "ledger", "cards": cards}
    raise HTTPException(status_code=500, detail=f"unknown domain source {source!r}")


def _board_store_provider(spec: dict):
    if spec.get("source") != "board_store":
        raise HTTPException(
            status_code=400,
            detail=f"domain {spec.get('domain_id')!r} is not a board_store domain")
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider)
    return CommandCenterBoardProvider(
        board_id=spec["board_id"], event_log=EventLog(KANBAN_EVENT_LOG),
        store_dir=BOARD_STORE_DIR)


def _find_domain_card(provider, card_id: str) -> dict:
    for card in provider.list_cards():
        if str(card.get("card_id")) == card_id:
            return card
    raise HTTPException(status_code=404, detail=f"card {card_id!r} not found")


_CARD_FOLD_KEYS = frozenset({
    "card_id", "board_id", "repo_id", "status", "last_event_id", "last_actor",
})


def _card_store_fields(card: dict) -> dict[str, Any]:
    return {k: v for k, v in card.items() if k not in _CARD_FOLD_KEYS}


def _required_job_application_id(card: dict, action: str) -> str:
    app_id = str(card.get("application_id") or "").strip()
    if not app_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"job card {card.get('card_id')!r} cannot {action}: "
                "no application_id is attached yet. Move it through selection/material "
                "preparation first so the application memory exists."
            ),
        )
    return app_id


# The job pipeline is a one-step machine around Geoff's three manual gates:
# 1) select (Suggested Jobs -> Selected by Geoff), 2) review what the agent
# finished (-> Needs Geoff = "agent complete"), 3) complete (Needs Geoff ->
# Completed through the validated submit path). Stage skips are refused so an
# agent's "done" can never masquerade as a submitted application.
_JOB_TRANSITIONS: dict[str, list[str]] = {
    "Suggested Jobs": ["Selected by Geoff", "Rejected / Skip"],
    "Selected by Geoff": ["In Progress", "Suggested Jobs"],
    "In Progress": ["Needs Geoff", "Selected by Geoff"],
    "Needs Geoff": ["Completed", "In Progress"],
    "Completed": ["Interviewing", "Closed / Archived"],
    "Interviewing": ["Closed / Archived", "Completed"],
    "Rejected / Skip": ["Suggested Jobs", "Closed / Archived"],
    "Closed / Archived": [],
}

_GRAND_TODO_TRANSITIONS: dict[str, list[str]] = {
    "Backlog": ["Ready", "Archived"],
    "Ready": ["Backlog", "In Progress", "Archived"],
    "In Progress": ["Ready", "Blocked", "Done", "Archived"],
    "Blocked": ["In Progress", "Archived"],
    "Done": ["In Progress", "Archived"],
    "Archived": ["Backlog"],
}

_BOOK_TRANSITIONS: dict[str, list[str]] = {
    # A field document whose initial event was interrupted can only enter the
    # safe first lane. It is never assigned a status automatically.
    "None": ["To read"],
    "To read": ["Reading", "Archived"],
    "Reading": ["To read", "Done", "Archived"],
    "Done": ["Reading", "Archived"],
    "Archived": ["To read"],
}

_GENERIC_WORK_TRANSITIONS: dict[str, list[str]] = {
    "Backlog": ["Ready", "Rejected"],
    "Ready": ["Backlog", "In Progress"],
    "In Progress": ["Ready", "Blocked", "Done"],
    "Blocked": ["In Progress", "Rejected"],
    "Done": ["In Progress"],
    "Rejected": ["Backlog"],
    "Awaiting Approval": [],
}


def _allowed_transitions(spec: dict, from_status: str | None) -> list[str]:
    """One step forward or backward, never a skip. Jobs use the explicit gate
    map; other board domains use column adjacency."""
    if spec.get("domain_id") == "job_application":
        return list(_JOB_TRANSITIONS.get(str(from_status), []))
    if spec.get("domain_id") in GRAND_TODO_DOMAIN_IDS:
        return list(_GRAND_TODO_TRANSITIONS.get(str(from_status), []))
    if spec.get("domain_id") == "book":
        return list(_BOOK_TRANSITIONS.get(str(from_status), []))
    if (
        spec.get("source") == "board_store"
        and spec.get("card_component") == "generic_task"
    ):
        configured_columns = set(spec.get("columns") or [])
        return [
            status for status in _GENERIC_WORK_TRANSITIONS.get(
                str(from_status), [])
            if status in configured_columns and not is_human_owned_status(status)
        ]
    columns = spec.get("columns") or []
    if from_status not in columns:
        return list(columns[:1])       # unknown/new card: enter the first lane
    i = columns.index(from_status)
    return [c for c in (columns[i - 1] if i else None,
                        columns[i + 1] if i + 1 < len(columns) else None)
            if c]


def _column_action(spec: dict, status: str) -> str:
    if spec.get("columns") and status not in spec["columns"]:
        raise HTTPException(
            status_code=400,
            detail=f"status {status!r} is not a configured column for "
                   f"domain {spec.get('domain_id')!r}")
    if is_human_owned_status(status):
        raise HTTPException(
            status_code=400,
            detail=f"status {status!r} is human-owned and cannot be set here")
    action = (spec.get("column_actions") or {}).get(status)
    if not action:
        raise HTTPException(
            status_code=400,
            detail=f"domain {spec.get('domain_id')!r} has no governed move "
                   f"action for status {status!r}")
    return action


def _domain_write_blockers(spec: dict) -> list[str]:
    if spec.get("source") != "board_store":
        return []
    blockers: list[str] = []
    log_parent = KANBAN_EVENT_LOG.parent
    if KANBAN_EVENT_LOG.exists():
        if not os.access(KANBAN_EVENT_LOG, os.W_OK):
            blockers.append(f"kanban event log is not writable: {KANBAN_EVENT_LOG}")
    elif not os.access(log_parent, os.W_OK):
        blockers.append(
            f"kanban event log parent is not writable: {log_parent}")
    if BOARD_STORE_DIR.exists():
        if not os.access(BOARD_STORE_DIR, os.W_OK):
            blockers.append(f"board store is not writable: {BOARD_STORE_DIR}")
    elif not os.access(BOARD_STORE_DIR.parent, os.W_OK):
        blockers.append(
            f"board store parent is not writable: {BOARD_STORE_DIR.parent}")
    return blockers


def _require_domain_writable(spec: dict) -> None:
    if spec.get("archived") is True:
        raise HTTPException(
            status_code=409,
            detail="archived boards are read-only until a human restores them",
        )
    blockers = _domain_write_blockers(spec)
    if blockers:
        raise HTTPException(
            status_code=503,
            detail="domain writes are not available: " + "; ".join(blockers))


def _event_headline(event) -> str:
    action = (event.action or "").replace("_", " ")
    if event.status_after:
        return f"{action} -> {event.status_after}"
    return action or event.event_type


def _application_summary(card: dict) -> dict[str, Any]:
    application_id = card.get("application_id")
    if not application_id:
        return {"exists": False, "application_id": None}

    _, root = _job_search_config_and_root()
    app_dir = root / "applications_active" / str(application_id)
    record_path = app_dir / "application.yml"
    comms_path = app_dir / "communications.jsonl"
    followups_path = app_dir / "followups.md"
    record: dict[str, Any] = {}
    if record_path.is_file():
        import yaml
        record = yaml.safe_load(record_path.read_text(encoding="utf-8")) or {}
    communications = []
    if comms_path.is_file():
        for line in comms_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                communications.append(json.loads(line))
    generation = record.get("generation") or {}
    return {
        "exists": app_dir.is_dir(),
        "application_id": application_id,
        "path": str(app_dir),
        "record_path": str(record_path),
        "followups_path": str(followups_path),
        "followups_exists": followups_path.is_file(),
        "communications_count": len(communications),
        "latest_communication": communications[-1] if communications else None,
        "recent_communications": communications[-6:],
        "status": record.get("status"),
        "stage": record.get("stage"),
        "last_activity_at": record.get("last_activity_at"),
        "retention_until": record.get("retention_until"),
        "generation_mode": str(generation.get("mode") or "unknown"),
        "revision": record.get("revision", 1),
        "review_state": record.get("review_state", "ready_for_review"),
        "record": record,
    }


def _manual_action_detail(card: dict) -> str:
    """What the manual step needs, stated so answered questions read as HANDLED
    and only real blockers read as work. `manual_reason` now holds only real
    blockers; `auto_answered` (set at classify/reclassify time) is presented
    separately as a positive."""
    auto = str(card.get("auto_answered") or "").strip()
    answered = (f" Auto-answered from your standing answers: {auto} "
                "(see the App Answers tab)." if auto else "")
    klass = str(card.get("automation_class") or "")
    reason = str(card.get("manual_reason") or "").strip()
    if klass == "bot_possible":
        base = ("Bot-ready: no questions block this application. Review the "
                "packet, then submit and move the card to Completed.")
    elif klass == "prepare_only":
        base = (f"Materials are prepared. {reason or 'No clear apply workflow'} "
                "— open the apply URL yourself, then submit.")
    elif reason:
        base = f"Needs you: {reason}. Review the packet, then submit."
    else:
        base = card.get("next_action") or "Review the packet, then submit."
    return base + answered


def _job_progress_steps(card: dict, events: list[dict], application: dict) -> list[dict]:
    status = str(card.get("status") or "")
    selected = status not in {"", "Suggested Jobs"}
    has_materials = bool(card.get("materials_path") or card.get("application_id"))
    terminal_or_active = status in {"Completed", "Interviewing"}
    manual_now = status == "Needs Geoff"
    return [
        {
            "id": "ranked",
            "label": "Ranked suggestion",
            "state": "done" if card.get("fit_score") is not None else "waiting",
            "detail": (
                f"Fit {card.get('fit_score', '-')}; resume "
                f"{card.get('resume_variant') or '-'}; automation "
                f"{card.get('automation_class') or '-'}."
            ),
        },
        {
            "id": "selected",
            "label": "Geoff selected",
            "state": "done" if selected else "current",
            "detail": (
                "Move this card to Selected by Geoff when it is worth pursuing."
                if not selected else f"Current lane: {status}."
            ),
        },
        {
            "id": "materials",
            "label": "Materials prepared",
            "state": "done" if has_materials else "current" if status == "In Progress" else "waiting",
            "detail": (
                f"Application {card.get('application_id')} at {card.get('materials_path')}"
                if has_materials else "Materials are created only after Geoff selection."
            ),
        },
        {
            "id": "packet_review",
            "label": "Packet reviewed by Geoff",
            "state": (
                "done" if terminal_or_active
                else "current" if manual_now and application.get("review_state") != "changes_requested"
                else "current" if application.get("review_state") == "changes_requested"
                else "waiting"
            ),
            "detail": (
                f"generation={application.get('generation_mode', 'unknown')}, "
                f"revision={application.get('revision', 1)}, "
                f"review_state={application.get('review_state', '-')}. "
                "Open Review Packet to read the resume/cover letter, leave notes, "
                "or record a submission you completed on the employer portal."
                if application.get("exists")
                else "Packet review starts once materials exist."
            ),
        },
        {
            "id": "manual_action",
            "label": "Manual/application action",
            "state": "done" if terminal_or_active else "current" if manual_now else "waiting",
            "detail": _manual_action_detail(card),
        },
        {
            "id": "followup_memory",
            "label": "Follow-up memory",
            "state": "done" if application.get("followups_exists") else "waiting",
            "detail": (
                f"{application.get('communications_count', 0)} communication(s); "
                f"retention until {application.get('retention_until') or '-'}."
                if application.get("exists") else "Starts once an application record exists."
            ),
        },
        {
            "id": "event_log",
            "label": "Kanban event log",
            "state": "done" if events else "waiting",
            "detail": f"{len(events)} governed event(s) recorded for this card.",
        },
    ]


def _chat_prompt_for_card(
    spec: dict,
    card: dict,
    steps: list[dict],
    events: list[dict],
    application: dict,
) -> str:
    domain_id = spec.get("domain_id", "domain")
    domain_title = spec.get("title") or domain_id
    title = (
        card.get("title")
        or card.get("company")
        or card.get("task")
        or card.get("action")
        or card.get("repo_id")
        or card.get("dag_id")
        or card.get("card_id")
    )
    role = card.get("role_title") or ""
    lines = [
        f"Use the {domain_title} CARD CONTEXT below as the authoritative context for "
        "this turn — it is real state pulled live from the cockpit, not a guess.",
        "Do not look for this card in mission_intake or todos unless I explicitly ask; "
        "domain cards may not exist on those generic boards.",
        "Help Geoff understand what happened so far, where this card is now, and the "
        "next safe action.",
    ]
    if domain_id == "job_application":
        lines.extend([
            "Guide the application collaboratively, exactly one currently visible "
            "portal page at a time. Ask Geoff to describe or paste only that page's "
            "visible fields and options; do not infer hidden or future pages.",
            "Never request, receive, store, repeat, or enter passwords, MFA codes, "
            "CAPTCHA responses, authentication tokens, government identifiers, or "
            "other secrets. Stop and hand control to Geoff when any appear.",
            "Stop before answering EEO, voluntary self-identification, disability, "
            "veteran-status, work-authorization, sponsorship, background-check, "
            "or legal-certification questions. Geoff must answer those himself.",
            "Never click or direct an executor to click the final submit control. "
            "Do not claim an application was submitted; report only recorded status "
            "evidence and say submission is unverified when evidence is ambiguous.",
            "For an unanswered non-sensitive question, do not invent an answer. Ask "
            "Geoff, then explicitly offer to add his approved question and exact "
            "answer to the appropriate job-type question library later; never save "
            "it automatically.",
        ])
    elif spec.get("card_component") in {"paper", "repo"}:
        lines.extend([
            "Treat titles, authors/owners, abstracts/descriptions, repository URLs, "
            "paper URLs, and source/code links as source-derived facts. Treat "
            "usefulness, pros, cons, key details, and implementation notes as "
            "local-model analysis whose status and provenance must remain visible.",
            "Never turn an analysis suggestion into a factual claim. Verify source "
            "links, dependencies, APIs, benchmarks, licenses, and repository fit "
            "before recommending implementation.",
        ])
    lines.extend([
        "",
        "CARD CONTEXT",
        f"- domain: {domain_id} ({domain_title})",
        f"- card_id: {card.get('card_id')}",
        f"- title: {title} {role}".strip(),
        f"- status: {card.get('status')}",
    ])
    intake = spec.get("intake") or {}
    if intake:
        lines.extend([
            "",
            "BOARD INTAKE (the configurable definition of what this board pulls in)",
            f"- producer: {intake.get('producer')}",
            f"- mode: {intake.get('mode')}",
            f"- summary/instructions: {intake.get('summary')}",
            f"- schedule: {intake.get('schedule') or 'manual'}",
            f"- source_refs: {intake.get('source_refs') or []}",
            f"- parameters: {intake.get('parameters') or {}}",
        ])
    # every field this domain actually defines (summary + drawer), so a repo card
    # shows repo fields and a paper card shows paper fields instead of the
    # job-application-shaped fields printing as "None" on unrelated domains
    seen_fields = {"card_id", "status"}
    for field in [*spec.get("summary_fields", []), *spec.get("drawer_fields", [])]:
        name = field.get("name")
        if not name or name in seen_fields:
            continue
        seen_fields.add(name)
        value = card.get(name)
        if (
            name == "title"
            and spec.get("card_component") == "repo"
            and value in (None, "")
        ):
            value = card.get("repo_id")
        if value in (None, "", [], {}):
            continue
        lines.append(f"- {field.get('label', name)}: {value}")
    if domain_id == "job_application":
        lines.extend([
            "",
            "FULL CARD PROVENANCE (live stored card)",
            json.dumps(card, ensure_ascii=False, sort_keys=True, default=str),
        ])
    elif spec.get("card_component") in {"paper", "repo"}:
        lines.extend([
            "",
            "FULL RESEARCH CARD PROVENANCE",
            json.dumps(card, ensure_ascii=False, sort_keys=True, default=str),
        ])
    if application:
        lines.extend([
            "",
            "APPLICATION MEMORY",
            f"- exists: {application.get('exists')}",
            f"- application_id: {application.get('application_id')}",
            f"- status: {application.get('status')}",
            f"- stage: {application.get('stage')}",
            f"- followups_exists: {application.get('followups_exists')}",
            f"- communications_count: {application.get('communications_count')}",
            f"- retention_until: {application.get('retention_until')}",
            f"- generation_mode: {application.get('generation_mode')}",
            f"- revision: {application.get('revision')}",
            f"- review_state: {application.get('review_state')}",
        ])
        if application.get("record"):
            lines.extend([
                "",
                "FULL APPLICATION PROVENANCE (stored application record)",
                json.dumps(
                    application["record"], ensure_ascii=False,
                    sort_keys=True, default=str),
            ])
        recent = application.get("recent_communications") or []
        if recent:
            lines.append("")
            lines.append("MAIN MOMENTS SO FAR (newest last)")
            for row in recent:
                lines.append(
                    f"- {row.get('ts', '?')}: [{row.get('type', 'note')}] "
                    f"{row.get('summary', '')}")
    if steps:
        lines.append("")
        lines.append("PROGRESS CHECKLIST")
        for step in steps:
            lines.append(
                f"- [{step.get('state')}] {step.get('label')}: "
                f"{step.get('detail') or 'No detail recorded.'}"
            )
    if events:
        lines.append("")
        lines.append("RECENT GOVERNED EVENTS")
        for event in events[-6:]:
            lines.append(
                f"- {event.get('created_at')}: {event.get('headline')} "
                f"({event.get('actor_type')} via {event.get('source_surface')})"
            )
    if spec.get("card_component") in {"paper", "repo"}:
        lines.extend([
            "",
            "Answer with:",
            "1. Source-backed facts and explicit unknowns.",
            "2. How this could help us, plus evidence-aware pros and cons.",
            "3. Key implementation prerequisites, useful code/related links, and risks.",
            "4. The smallest repo-specific experiment and validation KPIs; do not "
            "claim it has been implemented.",
        ])
    else:
        lines.extend([
            "",
            "Answer with:",
            "1. What happened so far, using the card context and events above.",
            "2. What is blocking or current.",
            "3. The next safe action Geoff (or an executor started from a mission) should take.",
        ])
    return "\n".join(lines)


def _domain_progress(spec: dict, card_id: str) -> dict:
    card = next(
        (
            c for c in _domain_cards(spec)["cards"]
            if str(c.get("card_id")) == card_id
        ),
        None,
    )
    if card is None:
        raise HTTPException(status_code=404, detail=f"card {card_id!r} not found")
    if card.get("projection_source") == "work_graph":
        work_events = _get_workgraph_service()._store.events(
            str(card["work_item_id"]))
        events = [
            {
                "event_id": f"work-{event.event_seq or index}",
                "created_at": event.ts,
                "headline": event.kind.replace("_", " "),
                "action": event.kind,
                "status_before": None,
                "status_after": event.payload.get("status"),
                "actor_type": "human" if event.kind == "status" else "system",
                "source_surface": "work_graph",
            }
            for index, event in enumerate(work_events, start=1)
        ]
    else:
        raw_events = [
            e for e in EventLog(KANBAN_EVENT_LOG).read()
            if e.board_id == spec.get("board_id") and e.card_id == card_id
        ]
        events = [
            {
                "event_id": e.event_id,
                "created_at": e.created_at,
                "headline": _event_headline(e),
                "action": e.action,
                "status_before": e.status_before,
                "status_after": e.status_after,
                "actor_type": e.actor_type,
                "source_surface": e.source_surface,
            }
            for e in raw_events
        ]
    application = _application_summary(card) if spec.get("domain_id") == "job_application" else {}
    steps = _job_progress_steps(card, events, application) if spec.get("domain_id") == "job_application" else [
        {
            "id": "events",
            "label": "Kanban events",
            "state": "done" if events else "waiting",
            "detail": f"{len(events)} governed event(s) recorded.",
        }
    ]
    return {
        "domain_id": spec.get("domain_id"),
        "card_id": card_id,
        "status": card.get("status"),
        "steps": steps,
        "events": events,
        "application": application,
        "chat_prompt": _chat_prompt_for_card(spec, card, steps, events, application),
    }


class DomainSurfaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: str
    title: str
    archived: bool | None = None
    card_component: str = "generic_task"
    source: str = "fixtures"
    board_id: str | None = None
    columns: list[str] = Field(default_factory=list)
    column_actions: dict[str, str] = Field(default_factory=dict)
    summary_fields: list[dict[str, Any]] = Field(default_factory=list)
    drawer_fields: list[dict[str, Any]] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    empty_state: dict[str, Any] = Field(default_factory=dict)
    intake: dict[str, Any] = Field(default_factory=dict)


class DomainIntakeUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intake: dict[str, Any]
    expected_revision: str = Field(min_length=64, max_length=64, strict=True)


class ResearchSourceSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    top_n: int = Field(ge=0, le=500, strict=True)
    lookback_days: int = Field(ge=0, le=365, strict=True)
    analysis_batch_size: int = Field(ge=1, le=200, strict=True)
    categories: list[str] | None = None
    min_stars: int | None = Field(default=None, ge=0, strict=True)

    @field_validator("categories")
    @classmethod
    def _categories(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        clean = [str(item).strip() for item in value if str(item).strip()]
        if len(clean) > 100 or len(clean) != len(set(clean)):
            raise ValueError("categories must be unique and contain at most 100 values")
        category_re = re.compile(
            r"^[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)?$")
        if any(len(item) > 50 or not category_re.fullmatch(item) for item in clean):
            raise ValueError("categories must be valid arXiv category ids")
        return clean


class ResearchSettingsUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[str] = Field(min_length=1, max_length=100)
    paper: ResearchSourceSettingsIn
    repo: ResearchSourceSettingsIn
    expected_revisions: dict[Literal["paper", "repo"], str]
    refresh: bool = True

    @field_validator("expected_revisions")
    @classmethod
    def _expected_revisions(
        cls, value: dict[Literal["paper", "repo"], str],
    ) -> dict[Literal["paper", "repo"], str]:
        if set(value) != {"paper", "repo"}:
            raise ValueError("expected_revisions must contain paper and repo")
        if any(not re.fullmatch(r"[0-9a-f]{64}", revision) for revision in value.values()):
            raise ValueError("research intake revisions must be SHA-256 values")
        return value


class ResearchRefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[Literal["paper", "repo"]] = Field(
        default_factory=lambda: ["paper", "repo"], min_length=1, max_length=2)


class BoardModuleIn(BaseModel):
    """Normalized 'create a board module' request — produces BOTH a kanban board
    (the repo/verb/status contract) and its domain surface (card grammar), with
    generic_task cards so every board gets the same chat + pipeline treatment.
    Governance defaults are FIXED (wall verbs always forbidden; human approval /
    merge unchanged). The browser never writes YAML — this is the typed seam."""
    title: str
    description: str = ""
    icon: str = ""
    # life = no repository (Books/Health/…); repository/hybrid drive repo work and
    # must name >=1 repo. Default life: the common new personal board is repo-less.
    execution_scope: str = "life"
    repo_ids: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    chat_enabled: bool = True


@app.get("/api/domains")
def domains() -> dict:
    """The typed-surface registry: card grammar + source binding + empty states,
    straight from the validated config (no hardcoded domain list in the SPA)."""
    return {
        "domains": [
            _clean_domain_surface(domain)
            for domain in _domain_config().get("domains", [])
        ],
    }


def _validated_intake(value: dict[str, Any] | None) -> dict[str, Any]:
    from command_center.schemas.contracts import DomainIntakeSpec
    from pydantic import ValidationError

    try:
        return DomainIntakeSpec.model_validate(value or {}).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"invalid board intake: {exc}",
        ) from exc


def _intake_revision(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _domain_intake_response(domain: dict[str, Any]) -> dict[str, Any]:
    intake = _validated_intake(domain.get("intake"))
    blocker = _domain_config_write_blocker()
    editable = (
        intake["editable"]
        and domain.get("archived") is not True
        and blocker is None
    )
    return {
        "domain_id": domain.get("domain_id"),
        "intake": intake,
        "revision": _intake_revision(intake),
        "writable": editable,
        "write_gate": (
            "enabled" if editable
            else blocker or "this producer is read-only from the board"
        ),
    }


_ARXIV_CATEGORY_OPTIONS = [
    {"value": "cs.AI", "label": "Artificial Intelligence"},
    {"value": "cs.CL", "label": "Computation and Language"},
    {"value": "cs.CV", "label": "Computer Vision and Pattern Recognition"},
    {"value": "cs.LG", "label": "Machine Learning (Computer Science)"},
    {"value": "cs.MA", "label": "Multiagent Systems"},
    {"value": "cs.SE", "label": "Software Engineering"},
    {"value": "stat.AP", "label": "Statistics Applications"},
    {"value": "stat.ME", "label": "Statistics Methodology"},
    {"value": "stat.ML", "label": "Machine Learning (Statistics)"},
]


def _research_domains(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = list(data.get("domains", []))
    paper = next((row for row in rows if row.get("domain_id") == "paper"), None)
    repo = next((row for row in rows if row.get("domain_id") == "repo"), None)
    if paper is None or repo is None:
        raise HTTPException(
            status_code=503, detail="research paper/repo domains are not configured")
    return paper, repo


def _research_refresh_state() -> dict[str, Any]:
    if not RESEARCH_REFRESH_FILE.is_file():
        return {"schema_version": "growthos.research-refresh.v1", "state": "idle"}
    try:
        value = json.loads(RESEARCH_REFRESH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503, detail="research refresh status is unreadable") from exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=503, detail="research refresh status is not an object")
    return value


def _enqueue_research_refresh(sources: list[str]) -> dict[str, Any]:
    unique_sources = [source for source in ("paper", "repo") if source in sources]
    if not unique_sources:
        raise HTTPException(status_code=422, detail="choose paper and/or repo to refresh")
    value = {
        "schema_version": "growthos.research-refresh.v1",
        "request_id": str(uuid.uuid4()),
        "state": "queued",
        "requested_at": datetime.now(UTC).isoformat(),
        "requested_sources": unique_sources,
        "ingested_sources": [],
        "analysis": {},
        "message": "Waiting for the Growth OS watcher",
    }
    try:
        with _research_refresh_lock():
            _atomic_write_bytes(
                RESEARCH_REFRESH_FILE,
                json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"),
            )
    except (OSError, BoardWriteLocked) as exc:
        raise HTTPException(
            status_code=503,
            detail="research settings were saved, but the refresh request could not be queued",
        ) from exc
    return value


def _research_settings_response(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or _domain_config()
    paper, repo = _research_domains(data)
    paper_response = _domain_intake_response(paper)
    repo_response = _domain_intake_response(repo)
    paper_topics = paper_response["intake"]["parameters"]["review_topics"]
    repo_topics = repo_response["intake"]["parameters"]["review_topics"]
    topics = list(dict.fromkeys([*paper_topics, *repo_topics]))
    return {
        "topics": topics,
        "topic_suggestions": topics,
        "category_options": _ARXIV_CATEGORY_OPTIONS,
        "paper": paper_response,
        "repo": repo_response,
        "refresh": _research_refresh_state(),
    }


@app.get("/api/research/settings")
def research_settings() -> dict:
    return _research_settings_response()


@app.get("/api/research/refresh")
def research_refresh_status() -> dict:
    return {"refresh": _research_refresh_state()}


@app.post("/api/research/refresh")
def request_research_refresh(body: ResearchRefreshIn) -> dict:
    _require_domain_config_writable()
    return {"refresh": _enqueue_research_refresh(body.sources)}


@app.put("/api/research/settings")
def update_research_settings(body: ResearchSettingsUpdateIn) -> dict:
    _require_domain_config_writable()
    from command_center.research_topics import normalize_research_topics

    try:
        topics = normalize_research_topics(body.topics)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.paper.categories is None or body.paper.min_stars is not None:
        raise HTTPException(
            status_code=422,
            detail="paper settings require categories and do not accept min_stars",
        )
    if body.repo.categories is not None or body.repo.min_stars is None:
        raise HTTPException(
            status_code=422,
            detail="repo settings require min_stars and do not accept categories",
        )
    with _config_module_lock():
        _reconcile_config_intent_locked()
        data = _read_config_direct(_domain_config_path())
        _validate_domain_config(data, status_code=503)
        paper, repo = _research_domains(data)
        for domain in (paper, repo):
            current = _validated_intake(domain.get("intake"))
            expected = body.expected_revisions.get(domain["domain_id"])
            if not expected or _intake_revision(current) != expected:
                raise HTTPException(
                    status_code=409,
                    detail="research settings changed since they were opened; reload before saving",
                )
        paper_parameters = {
            "enabled": body.paper.enabled,
            "top_n": body.paper.top_n,
            "lookback_days": body.paper.lookback_days,
            "analysis_batch_size": body.paper.analysis_batch_size,
            "categories": body.paper.categories or [],
            "review_topics": topics,
        }
        repo_parameters = {
            "enabled": body.repo.enabled,
            "top_n": body.repo.top_n,
            "lookback_days": body.repo.lookback_days,
            "min_stars": body.repo.min_stars if body.repo.min_stars is not None else 0,
            "analysis_batch_size": body.repo.analysis_batch_size,
            "review_topics": topics,
        }
        next_paper = {
            **paper,
            "intake": _validated_intake({
                **_validated_intake(paper.get("intake")),
                "parameters": paper_parameters,
            }),
        }
        next_repo = {
            **repo,
            "intake": _validated_intake({
                **_validated_intake(repo.get("intake")),
                "parameters": repo_parameters,
            }),
        }
        next_rows = [
            next_paper if row.get("domain_id") == "paper"
            else next_repo if row.get("domain_id") == "repo"
            else row
            for row in data.get("domains", [])
        ]
        next_data = {**data, "domains": next_rows}
        _validate_domain_config(next_data)
        _write_yaml_file(_domain_config_path(), next_data)
        _audit_config_write("research.settings.update", {
            "topics": topics,
            "paper_revision_before": body.expected_revisions["paper"],
            "repo_revision_before": body.expected_revisions["repo"],
        })
    refresh = _enqueue_research_refresh(["paper", "repo"]) if body.refresh else None
    response = _research_settings_response(next_data)
    if refresh is not None:
        response["refresh"] = refresh
    return response


@app.get("/api/domain/{domain_id}/intake")
def domain_intake(domain_id: str) -> dict:
    return _domain_intake_response(_domain_spec(domain_id))


@app.put("/api/domain/{domain_id}/intake")
def update_domain_intake(domain_id: str, body: DomainIntakeUpdateIn) -> dict:
    _require_domain_config_writable()
    if domain_id in {"paper", "repo"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "Papers and Repos share one research-topic contract; update "
                "them together through /api/research/settings"
            ),
        )
    candidate_intake = _validated_intake(body.intake)
    with _config_module_lock():
        _reconcile_config_intent_locked()
        data = _read_config_direct(_domain_config_path())
        _validate_domain_config(data, status_code=503)
        rows = list(data.get("domains", []))
        index = next(
            (i for i, row in enumerate(rows)
             if row.get("domain_id") == domain_id),
            None,
        )
        if index is None:
            raise HTTPException(status_code=404, detail=f"unknown domain {domain_id!r}")
        current = rows[index]
        if current.get("archived") is True:
            raise HTTPException(status_code=409, detail="archived boards are read-only")
        current_intake = _validated_intake(current.get("intake"))
        if not current_intake["editable"]:
            raise HTTPException(
                status_code=409,
                detail="this producer is read-only from the board")
        if _intake_revision(current_intake) != body.expected_revision:
            raise HTTPException(
                status_code=409,
                detail="board intake changed since it was opened; reload before saving")
        # Cadence is operational wiring (the watcher interval/trigger), not a
        # free-form parameter. Keep it registry-owned until a scheduler adapter
        # can apply it truthfully.
        immutable_keys = (
            "producer", "mode", "schedule", "source_refs", "editable")
        changed_immutable = [
            key for key in immutable_keys
            if candidate_intake[key] != current_intake[key]
        ]
        if changed_immutable:
            raise HTTPException(
                status_code=409,
                detail=(
                    "board intake identity/schedule is registry-owned; only "
                    "summary and parameters are editable here "
                    f"(attempted: {', '.join(changed_immutable)})"
                ),
            )
        rows[index] = {**current, "intake": candidate_intake}
        next_data = {**data, "domains": rows}
        _validate_domain_config(next_data)
        _write_yaml_file(_domain_config_path(), next_data)
        _audit_config_write("domain.intake.update", {
            "domain_id": domain_id,
            "producer": candidate_intake["producer"],
            "revision_before": body.expected_revision,
            "revision_after": _intake_revision(candidate_intake),
        })
        return _domain_intake_response(rows[index])


@app.get("/api/domain-schema")
def domain_schema() -> dict:
    """Editable view of configs/domain_surfaces.yaml for the full cockpit console."""
    return _domain_schema_response()


@app.post("/api/domain-schema")
def create_domain_schema(body: DomainSurfaceIn) -> dict:
    with _config_module_lock():
        _reconcile_config_intent_locked()
        data = _domain_config()
        domain = _clean_domain_surface(body.model_dump(mode="json"))
        domain["archived"] = False
        if any(
            row.get("domain_id") == domain["domain_id"]
            for row in data.get("domains", [])
        ):
            raise HTTPException(
                status_code=409,
                detail=f"domain {domain['domain_id']!r} already exists",
            )
        next_data = dict(data)
        next_data["domains"] = [*data.get("domains", []), domain]
        return _write_domain_config(next_data)


@app.put("/api/domain-schema/{domain_id}")
def update_domain_schema(domain_id: str, body: DomainSurfaceIn) -> dict:
    with _config_module_lock():
        _reconcile_config_intent_locked()
        data = _domain_config()
        domain = _clean_domain_surface(body.model_dump(mode="json"))
        domains = list(data.get("domains", []))
        idx = next((i for i, row in enumerate(domains)
                    if row.get("domain_id") == domain_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"unknown domain {domain_id!r}")
        if domains[idx].get("archived") is True:
            raise HTTPException(
                status_code=409,
                detail="archived boards are read-only; restore explicitly before editing",
            )
        domain["archived"] = False
        if domain["domain_id"] != domain_id and any(
            row.get("domain_id") == domain["domain_id"] for row in domains
        ):
            raise HTTPException(
                status_code=409,
                detail=f"domain {domain['domain_id']!r} already exists",
            )
        domains[idx] = domain
        next_data = dict(data)
        next_data["domains"] = domains
        return _write_domain_config(next_data)


@app.delete("/api/domain-schema/{domain_id}")
def delete_domain_schema(domain_id: str) -> dict:
    """Archive a surface in place. Hard deletion is intentionally unavailable."""
    with _config_module_lock():
        _reconcile_config_intent_locked()
        data = _domain_config()
        domains = list(data.get("domains", []))
        idx = next((i for i, row in enumerate(domains)
                    if row.get("domain_id") == domain_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"unknown domain {domain_id!r}")
        domains[idx] = {**domains[idx], "archived": True}
        next_data = dict(data)
        next_data["domains"] = domains
        result = _write_domain_config(next_data)
        _audit_config_write("domain.archive", {"domain_id": domain_id})
        return result


@app.post("/api/domain-schema/{domain_id}/restore")
def restore_domain_schema(domain_id: str) -> dict:
    with _config_module_lock():
        _reconcile_config_intent_locked()
        data = _domain_config()
        domains = list(data.get("domains", []))
        idx = next((i for i, row in enumerate(domains)
                    if row.get("domain_id") == domain_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"unknown domain {domain_id!r}")
        domains[idx] = {**domains[idx], "archived": False}
        result = _write_domain_config({**data, "domains": domains})
        _audit_config_write("domain.restore", {"domain_id": domain_id})
        return result


def _commit_board_module_configs(
    before_registry: dict[str, Any],
    before_domains: dict[str, Any],
    after_registry: dict[str, Any],
    after_domains: dict[str, Any],
) -> None:
    """Journal and publish the two validated config documents.

    A crash between replacements is repaired by the next config read under the
    same lock. Ordinary exceptions reconcile immediately before surfacing.
    """
    intent = {
        "before_registry": before_registry,
        "before_domains": before_domains,
        "after_registry": after_registry,
        "after_domains": after_domains,
    }
    intent_path = _config_intent_path()
    _atomic_write_bytes(
        intent_path,
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )
    try:
        _atomic_write_bytes(_kanban_boards_path(), _yaml_bytes(after_registry))
        _atomic_write_bytes(_domain_config_path(), _yaml_bytes(after_domains))
    except Exception:
        _reconcile_config_intent_locked()
        raise
    _unlink_config_intent(intent_path)


@app.post("/api/board-module", status_code=201)
def create_board_module(body: BoardModuleIn) -> dict:
    _require_domain_config_writable()
    with _config_module_lock():
        _reconcile_config_intent_locked()
        return _create_board_module_locked(body)


class BoardChangePreviewIn(BaseModel):
    """A proposed board/config change to REVIEW (read-only). before/after are the
    whole config docs the diff/validation runs against."""
    model_config = ConfigDict(extra="forbid")
    author_harness: str
    kind: str
    target_board: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class BoardChangeApplyIn(BoardChangePreviewIn):
    """Apply a proposed change. When a signing secret is configured, a
    proposal-bound `approval_token` is REQUIRED (§8) and its operator is the
    approver; otherwise `approved_by` must be in the server operator set."""
    created_at: str
    approved_by: str = ""
    approval_token: str | None = None


class ApprovalTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    operator: str


@app.post("/api/board-changes/approval-token")
def mint_board_change_approval(body: ApprovalTokenIn) -> dict:
    """§8: mint a SHORT-LIVED, SINGLE-USE, proposal-BOUND, signed approval token.
    Human-gated: the operator must be in the SERVER operator allowlist AND a
    signing secret must be configured. The token authorizes applying exactly the
    one reviewed proposal_id, by this operator, until it expires."""
    import secrets
    import time

    from command_center.kanban_sync.board_change import (
        human_operators_from_env, mint_approval_token, token_secret_from_env)
    from command_center.kanban_sync.events import GovernanceViolation
    secret = token_secret_from_env()
    if not secret:
        raise HTTPException(
            status_code=403,
            detail="approval tokens unavailable — set "
                   "KANBAN_UI_BOARD_CHANGE_SIGNING_SECRET on the server.")
    if body.operator not in human_operators_from_env():
        raise HTTPException(
            status_code=403,
            detail="operator is not in the authenticated server operator set.")
    nonce = secrets.token_hex(8)
    try:
        token = mint_approval_token(
            proposal_id=body.proposal_id, operator=body.operator, secret=secret,
            issued_at=int(time.time()), nonce=nonce)
    except GovernanceViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"approval_token": token, "proposal_id": body.proposal_id}


def _board_change_validator(kind: str):
    """The right contract validator for a board-change kind (used by preview and
    apply). Raises HTTPException(400) on an invalid proposed config."""
    if kind in ("update_board_format", "archive_domain"):
        return _validate_domain_config
    if kind == "create_board":
        return _validate_board_registry
    return lambda _after: None


@app.post("/api/board-changes/preview")
def preview_board_change(body: BoardChangePreviewIn) -> dict:
    """Phase 5: REVIEW a proposed board/config change with ZERO side effects —
    before/after diff + validation of the proposed config against the real
    contract. Writes nothing; safe for an agent to call."""
    from datetime import datetime, timezone

    from command_center.kanban_sync.board_change import (
        build_board_change_preview, make_proposal)
    try:
        proposal = make_proposal(
            author_harness=body.author_harness, kind=body.kind,
            target_board=body.target_board, before=body.before, after=body.after,
            rationale=body.rationale,
            created_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:                      # invalid kind / author
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preview = build_board_change_preview(
        proposal, validate=_board_change_validator(body.kind))
    return {"proposal_id": proposal.proposal_id, "preview": preview.model_dump()}


class BoardFormatPlanIn(BaseModel):
    """A STRUCTURED board-format change (no browser-generated YAML): the exact
    columns a board should have. The server computes the `after` config."""
    model_config = ConfigDict(extra="forbid")
    domain_id: str
    columns: list[str]
    author_harness: str = "codex_agent"
    rationale: str = ""


@app.get("/api/board-changes/format-boards")
def list_board_format_targets() -> dict:
    """Read-only: the boards whose columns a board-format card can edit, each
    with its CURRENT columns (seeds the editor). Only non-archived board_store
    domains — the ones with reversible lane→status mapping."""
    boards = []
    for domain in _domain_config().get("domains", []):
        if (domain.get("source") == "board_store" and not domain.get("archived")
                and domain.get("card_component") == "generic_task"):
            boards.append({"domain_id": domain["domain_id"],
                           "title": domain.get("title") or domain["domain_id"],
                           "columns": list(domain.get("columns", []))})
    return {"boards": boards}


@app.post("/api/board-changes/plan-format")
def plan_board_format(body: BoardFormatPlanIn) -> dict:
    """Phase 5: turn a STRUCTURED column change into a reviewable board-change
    preview WITHOUT the browser authoring YAML. Reads the current (validated)
    domain config, computes the `after` server-side (pruning stale
    column_actions), and returns the before/after columns + a diff + the
    zero-side-effect preview + an OPAQUE `apply_payload` the card echoes to
    /api/board-changes/apply. ZERO writes."""
    from datetime import datetime, timezone

    from command_center.kanban_sync.board_change import (
        build_board_change_preview, make_proposal)
    from command_center.kanban_sync.board_format import (
        BoardFormatChange, apply_columns_change, columns_diff, current_columns)
    before = _domain_config()                     # current whole config (validated)
    try:
        before_cols = current_columns(before, body.domain_id)
        after = apply_columns_change(
            before, BoardFormatChange(domain_id=body.domain_id, columns=body.columns))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created_at = datetime.now(timezone.utc).isoformat()
    proposal = make_proposal(
        author_harness=body.author_harness, kind="update_board_format",
        target_board=body.domain_id, before=before, after=after,
        rationale=body.rationale, created_at=created_at)
    preview = build_board_change_preview(proposal, validate=_validate_domain_config)
    return {
        "proposal_id": proposal.proposal_id,
        "target_board": body.domain_id,
        "before_columns": before_cols,
        "after_columns": list(body.columns),
        "diff": columns_diff(before_cols, list(body.columns)),
        "preview": preview.model_dump(),
        # opaque, server-computed — the card passes it verbatim to apply (+ token),
        # so the browser never authors config and proposal_id is reproduced exactly
        "apply_payload": {
            "author_harness": body.author_harness, "kind": "update_board_format",
            "target_board": body.domain_id, "before": before, "after": after,
            "rationale": body.rationale, "created_at": created_at},
    }


@app.post("/api/board-changes/apply")
def apply_board_change_endpoint(body: BoardChangeApplyIn) -> dict:
    """Phase 5: APPLY a board/config change — HUMAN-gated, atomic, reversible.

    Double opt-in / fails closed: refuses unless KANBAN_UI_BOARD_CHANGE_APPLY=1
    AND the approver is in the SERVER-configured KANBAN_UI_HUMAN_OPERATORS set
    (sourced here from the server env, NEVER from the request body — an agent
    cannot name itself into approval). Writes via the audited atomic config
    journal after re-checking the live config still matches the reviewed
    `before` (rejects a stale/raced proposal). Returns the durable receipt."""
    import time
    from datetime import datetime, timezone

    from command_center.kanban_sync.board_change import (
        apply_board_change, human_operators_from_env, make_proposal,
        token_secret_from_env, verify_approval_token)
    from command_center.kanban_sync.events import GovernanceViolation

    if not BOARD_CHANGE_APPLY_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="board-change apply is disabled — set "
                   "KANBAN_UI_BOARD_CHANGE_APPLY=1 and KANBAN_UI_HUMAN_OPERATORS "
                   "to enable (double opt-in).")
    _require_domain_config_writable()
    operators = human_operators_from_env()        # SERVER env only (review note N1)
    try:
        proposal = make_proposal(
            author_harness=body.author_harness, kind=body.kind,
            target_board=body.target_board, before=body.before, after=body.after,
            rationale=body.rationale, created_at=body.created_at)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # §8: when a signing secret is configured, a SHORT-LIVED, SINGLE-USE,
    # proposal-BOUND token is REQUIRED and its operator is the approver (a leaked
    # operator name can no longer self-approve). The nonce is burned only on a
    # successful apply (below). No secret configured → the operator-allowlist
    # path (approved_by must be a server operator) still applies.
    secret = token_secret_from_env()
    approver = body.approved_by
    spent_nonce: str | None = None
    if secret:
        if not body.approval_token:
            raise HTTPException(
                status_code=403,
                detail="a proposal-bound approval token is required (mint one "
                       "at /api/board-changes/approval-token).")
        try:
            tok = verify_approval_token(
                body.approval_token, proposal_id=proposal.proposal_id,
                secret=secret, now=int(time.time()),
                spent_nonces=_spent_nonces())
        except GovernanceViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        approver, spent_nonce = tok.operator, tok.nonce

    validate = _board_change_validator(proposal.kind)

    def _write(pr) -> None:
        validate(pr.after)                        # contract-valid before any write
        if pr.kind == "create_board":
            live_before = _read_board_registry_data()
            if pr.before != live_before:
                raise GovernanceViolation(
                    "board registry changed since preview — re-review before apply")
            _commit_board_module_configs(
                pr.before, _domain_config(), pr.after, _domain_config())
        else:                                     # update_board_format | archive_domain
            live_before = _domain_config()
            if pr.before != live_before:
                raise GovernanceViolation(
                    "domain config changed since preview — re-review before apply")
            reg = _read_board_registry_data()
            _commit_board_module_configs(reg, pr.before, reg, pr.after)

    def _snapshot(pr) -> str:
        # Persist the RESTORABLE before-bytes (not just a label) so rollback is
        # real. Written only after the human gate + integrity check passed
        # (apply_board_change calls this after _assert_human_approver), so a
        # rejected apply leaves no snapshot (review notes N2/#4).
        ref = f"bcp-snap-{pr.proposal_id}"
        snap = {"proposal_id": pr.proposal_id, "kind": pr.kind,
                "target_board": pr.target_board, "author_harness": pr.author_harness,
                "before": pr.before}
        _atomic_write_bytes(_board_change_rollback_path(ref),
                            json.dumps(snap, sort_keys=True).encode("utf-8"))
        _audit_config_write("board_change.snapshot",
                            {"proposal_id": pr.proposal_id, "rollback_ref": ref})
        return ref

    try:
        with _config_module_lock():
            _reconcile_config_intent_locked()
            receipt = apply_board_change(
                proposal, approved_by=approver, human_operators=operators,
                apply_config=_write, snapshot=_snapshot,
                now=lambda: datetime.now(timezone.utc).isoformat())
    except GovernanceViolation as exc:            # gate hit / stale proposal
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if spent_nonce:                               # burn the single-use token
        _record_spent_nonce(spent_nonce)
    _audit_config_write("board_change.applied",
                        {"proposal_id": receipt.proposal_id,
                         "approved_by": receipt.approved_by,
                         "rollback_ref": receipt.rollback_ref})
    return {"receipt": receipt.model_dump()}


class BoardChangeRollbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rollback_ref: str
    approved_by: str


@app.post("/api/board-changes/rollback")
def rollback_board_change_endpoint(body: BoardChangeRollbackIn) -> dict:
    """Reverse an applied board change from its rollback_ref — HUMAN-gated by the
    SAME server-sourced operator allowlist as apply. Restores the persisted
    `before` bytes via the audited atomic journal. Returns a rollback receipt."""
    from datetime import datetime, timezone

    from command_center.kanban_sync.board_change import (
        human_operators_from_env, rollback_board_change, BoardChangeReceipt)
    from command_center.kanban_sync.events import GovernanceViolation

    if not BOARD_CHANGE_APPLY_ENABLED:
        raise HTTPException(status_code=403, detail="board-change apply/rollback is disabled")
    _require_domain_config_writable()
    operators = human_operators_from_env()
    snap_path = _board_change_rollback_path(body.rollback_ref)
    if not snap_path.is_file():
        raise HTTPException(status_code=404, detail=f"no rollback point {body.rollback_ref!r}")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))

    def _restore(_ref: str) -> None:
        before = snap["before"]
        if snap["kind"] == "create_board":
            _validate_board_registry(before)
            _commit_board_module_configs(_read_board_registry_data(), _domain_config(),
                                         before, _domain_config())
        else:
            _validate_domain_config(before)
            reg = _read_board_registry_data()
            _commit_board_module_configs(reg, _domain_config(), reg, before)

    from pydantic import ValidationError
    try:
        # reconstruct the receipt shell the module's gate operates on; a
        # non-human approver fails the receipt validator here → 403 (not 500)
        receipt = BoardChangeReceipt(
            proposal_id=snap["proposal_id"], kind=snap["kind"],
            target_board=snap["target_board"], applied_at="(rollback)",
            approved_by=body.approved_by, rollback_ref=body.rollback_ref,
            author_harness=snap["author_harness"])
        with _config_module_lock():
            _reconcile_config_intent_locked()
            rb = rollback_board_change(
                receipt, restored_by=body.approved_by, human_operators=operators,
                restore=_restore, now=lambda: datetime.now(timezone.utc).isoformat())
    except (GovernanceViolation, ValidationError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    _audit_config_write("board_change.rolled_back",
                        {"proposal_id": rb.proposal_id, "restored_by": rb.approved_by})
    return {"receipt": rb.model_dump()}


def _create_board_module_locked(body: BoardModuleIn) -> dict:
    """Create a whole board MODULE from one typed request: a kanban board (the
    repo/verb/status contract) + its domain surface (generic_task card grammar),
    so every board — including user-created ones — gets the same chat + pipeline
    + usage treatment. Governance defaults are FIXED: wall verbs stay forbidden,
    human approval/merge is unchanged. Atomic (both configs validate before either
    is written), write-gated, and audited. The browser never emits YAML."""
    board_id = _slug_board_id(body.title)
    if not board_id:
        raise HTTPException(status_code=400, detail="title must yield a non-empty board id")

    reg = _read_board_registry_data()
    if any(b.get("board_id") == board_id for b in reg.get("boards", [])):
        raise HTTPException(status_code=409, detail=f"board {board_id!r} already exists")
    dom = _domain_config()
    if any(d.get("domain_id") == board_id for d in dom.get("domains", [])):
        raise HTTPException(status_code=409, detail=f"domain {board_id!r} already exists")

    scope = body.execution_scope if body.execution_scope in ("life", "repository", "hybrid") else "life"
    repo_ids = [r.strip() for r in body.repo_ids if r.strip()]
    if scope == "life":
        repo_ids = []                       # no fake board-id-as-repo workaround
    elif not repo_ids:
        raise HTTPException(
            status_code=400,
            detail=f"a {scope} board must name at least one repo_id "
                   "(use execution_scope 'life' for a repo-less board)")
    board_spec = {
        "board_id": board_id, "provider": "command_center_ui", "workspace_ref": "self",
        "board_ref": board_id, "execution_scope": scope, "repo_ids": repo_ids,
        "status_mapping": dict(_KANBAN_STATUS_LABELS),
        "required_fields": ["MissionID", "RepoID", "Risk", "LastSync", "Section"],
        "allowed_agent_verbs": list(_KANBAN_ALLOWED_VERBS),
        "forbidden_agent_verbs": list(_KANBAN_WALL_VERBS), "blockers": []}
    standard_columns = list(_KANBAN_STATUS_LABELS.values())
    requested_columns = [c.strip() for c in body.columns if c.strip()]
    if requested_columns and (
        len(requested_columns) != len(set(requested_columns))
        or set(requested_columns) != set(standard_columns)
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "new board modules use the complete governed workflow; custom "
                "columns need an explicit canonical-status mapping and cannot "
                "be created by this wizard"
            ),
        )
    columns = requested_columns or standard_columns
    surface = _clean_domain_surface({
        "domain_id": board_id, "title": body.title.strip(),
        "card_component": "generic_task", "source": "board_store", "board_id": board_id,
        "columns": columns,
        "column_actions": {
            column: _KANBAN_COLUMN_ACTIONS[column]
            for column in columns if column in _KANBAN_COLUMN_ACTIONS
        },
        "summary_fields": [{"name": "title", "label": "Title"},
                           {"name": "status", "label": "Status"}],
        "drawer_fields": [{"name": "description", "label": "Description"},
                          {"name": "notes", "label": "Notes"}],
        "allowed_actions": ["stage_card", "start_todo", "finish_todo",
                            "block_card", "reject_card"],
        "intake": {
            "producer": "universal_intake",
            "mode": "event",
            "summary": (
                body.description.strip()
                or f"Reviewed captures and chat TODOs for {body.title.strip()} route here."
            ),
            "schedule": "on reviewed capture conversion",
            "source_refs": ["src/command_center/intake"],
            "parameters": {
                "instructions": (
                    body.description.strip()
                    or f"Tasks and notes that belong on {body.title.strip()}."
                )
            },
            "editable": True,
        },
        "empty_state": {"title": f"No {body.title.strip()} cards yet",
                        "hint": body.description.strip() or "Add a card to get started."}})

    # Validate BOTH before writing EITHER — never a half-created module.
    next_reg = {"schema_version": reg.get("schema_version", "command-center.kanban-boards.v1"),
                "boards": [*reg.get("boards", []), board_spec]}
    next_dom = {**dom, "domains": [*dom.get("domains", []), surface]}
    _validate_board_registry(next_reg)
    _validate_domain_config(next_dom)
    _commit_board_module_configs(reg, dom, next_reg, next_dom)
    _audit_config_write("board_module.create", {
        "board_id": board_id, "title": body.title.strip(), "execution_scope": scope,
        "repo_ids": repo_ids, "icon": body.icon, "chat_enabled": body.chat_enabled})
    return {"board_id": board_id, "domain_id": board_id, "title": body.title.strip(),
            "provider": "command_center_ui", "execution_scope": scope,
            "card_component": "generic_task",
            "columns": columns, "repo_ids": repo_ids, "chat_enabled": body.chat_enabled}


# ── Universal Capture (intake) ────────────────────────────────────────────────
# A rough thought is preserved as an immutable capture BEFORE deciding whether it
# becomes a card/project/nothing — capturing never starts work. Classification /
# routing / packet building are later phases; this is the stable record + Inbox.
_capture_service = None   # type: ignore[var-annotated]


def _get_capture_service():
    global _capture_service
    if _capture_service is None:
        import secrets
        from datetime import datetime, timezone

        from command_center.intake import (
            CaptureService,
            InMemoryCaptureStore,
            LedgerCaptureStore,
        )
        if CAPTURE_LEDGER:
            store = LedgerCaptureStore(httpx.Client(base_url=LEDGER_BASE_URL, timeout=30))
        else:
            store = InMemoryCaptureStore()
        _capture_service = CaptureService(
            store,
            clock=lambda: datetime.now(timezone.utc).isoformat(),
            id_factory=lambda: "cap-" + secrets.token_hex(5))
    return _capture_service


def _require_capture():
    if not CAPTURE_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Universal Capture is disabled (set KANBAN_UI_CAPTURE_ENABLED=1)")
    return _get_capture_service()


class CaptureIn(BaseModel):
    raw_content: str
    source_type: str = "text"
    source_ref: str | None = None
    current_board_id: str | None = None
    current_card_id: str | None = None
    conversation_id: str | None = None
    requested_mode: str = "save_only"


class CaptureBatchIn(BaseModel):
    text: str
    source_type: str = "list"
    current_board_id: str | None = None
    conversation_id: str | None = None
    requested_mode: str = "save_only"


class CapturePrepareActionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal[
        "continue_in_chat",
        "route_to_todos",
        "choose_existing_board",
        "create_new_board",
    ]
    label: str
    description: str


class CapturePrepareOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: str
    conversation_id: str
    processing_status: Literal["ready_to_route"]
    chat_prompt: str
    available_actions: list[CapturePrepareActionOut]


def _capture_fields(body) -> dict:
    fields = {"source_type": body.source_type, "requested_mode": body.requested_mode,
              "current_board_id": body.current_board_id,
              "conversation_id": body.conversation_id}
    if getattr(body, "source_ref", None) is not None:
        fields["source_ref"] = body.source_ref
    if getattr(body, "current_card_id", None) is not None:
        fields["current_card_id"] = body.current_card_id
    return fields


@app.post("/api/captures", status_code=201)
def create_capture(body: CaptureIn) -> dict:
    svc = _require_capture()
    try:
        view = svc.capture(body.raw_content, **_capture_fields(body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return view.model_dump()


@app.post("/api/captures/batch", status_code=201)
def create_capture_batch(body: CaptureBatchIn) -> dict:
    svc = _require_capture()
    views = svc.capture_batch(body.text, **_capture_fields(body))
    return {"count": len(views),
            "batch_id": views[0].record.batch_id if views else None,
            "captures": [v.model_dump() for v in views]}


@app.get("/api/captures")
def list_captures(status: str | None = None) -> list:
    svc = _require_capture()
    return [v.model_dump() for v in svc.list(status=status)]


@app.get("/api/captures/{capture_id}")
def get_capture(capture_id: str) -> dict:
    svc = _require_capture()
    try:
        return svc.get(capture_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/api/captures/{capture_id}/prepare",
    response_model=CapturePrepareOut,
)
def prepare_capture(capture_id: str) -> dict:
    """Open the capture's stable routing chat; never create canonical work."""
    svc = _require_capture()
    try:
        return svc.prepare(capture_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/intake/inbox")
def intake_inbox() -> dict:
    """The Universal Inbox: captures grouped into lanes. A capture is recoverable
    here even after it is routed elsewhere — nothing is ever silently dropped."""
    return _require_capture().inbox()


# ── Canonical work graph — one WorkItem, many board placements, typed edges ────
# A task on three boards is ONE work item with three placements, never three
# unrelated cards. Creating work items/placements/edges is planning, NOT a
# mission — write-capable execution stays behind the mission + lease + wall.
_workgraph_service = None   # type: ignore[var-annotated]


def _get_workgraph_service():
    global _workgraph_service
    if _workgraph_service is None:
        import secrets
        from datetime import datetime, timezone

        from command_center.work_graph import (
            InMemoryWorkGraphStore,
            LedgerWorkGraphStore,
            WorkGraphService,
        )
        if WORKGRAPH_LEDGER:
            store = LedgerWorkGraphStore(
                httpx.Client(base_url=LEDGER_BASE_URL, timeout=30))
        else:
            store = InMemoryWorkGraphStore()
        _workgraph_service = WorkGraphService(
            store,
            clock=lambda: datetime.now(timezone.utc).isoformat(),
            id_factory=lambda prefix: f"{prefix}-" + secrets.token_hex(5))
    return _workgraph_service


def _require_workgraph():
    if not WORKGRAPH_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="the work graph is disabled (set KANBAN_UI_WORKGRAPH_ENABLED=1)")
    return _get_workgraph_service()


def _require_workgraph_write():
    """Production/full-console work must survive a cockpit restart.

    Hermetic read-only/dev tests may still exercise the in-memory graph, but a
    write-capable console refuses canonical work writes unless Ledger backing is
    explicitly enabled.
    """
    service = _require_workgraph()
    if CHAT_ENABLED and not WORKGRAPH_LEDGER:
        raise HTTPException(
            status_code=503,
            detail="durable work routing requires KANBAN_UI_WORKGRAPH_LEDGER=1",
        )
    return service


class WorkItemIn(BaseModel):
    title: str
    description: str = ""
    kind: str = "todo"
    owner: str | None = None
    priority: str | None = None
    due_at: str | None = None
    capture_id: str | None = None
    conversation_id: str | None = None
    mission_id: str | None = None


class WorkStatusIn(BaseModel):
    status: Literal[
        "backlog", "ready", "in_progress", "blocked", "awaiting_approval",
        "done", "rejected", "archived",
    ]


class WorkDescriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    expected_updated_at: str
    expected_description: str


class TodoBoardLinkOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_id: str
    domain_id: str
    is_primary: bool
    placement_id: str | None = None
    source_projection: bool = False
    repo_ids: list[str]
    href: str


class TodoIntegrityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    missing_fields: list[str]


class TodoRowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todo_id: str
    work_item_id: str | None
    source_kind: str
    source_id: str
    raw_preview: str | None
    title: str | None
    description: str | None
    kind: str | None
    status: str | None
    raw_status: str | None
    priority: str | None = None
    impact: str | None = None
    timeline: str | None = None
    assigned: bool
    boards: list[TodoBoardLinkOut]
    repo_ids: list[str]
    created_at: str | None
    updated_at: str | None
    source_href: str
    assignable: bool
    integrity: TodoIntegrityOut


class TodoStoryErrorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    code: str
    message: str


class TodoRequestedIdentityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todo_id: str
    kind: Literal["work", "capture", "card"]
    source_id: str
    state: Literal["emitted", "not_materialized", "folded_into_work_items"]
    is_emitted_master_todo: bool
    missing_linked_work_item_ids: list[str]


class TodoRawCaptureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: CaptureRecord
    processing_status: str
    classification: CaptureClassification | None
    events: list[CaptureEvent]


class TodoRepositoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_id: str
    remote_url: str


class TodoInventoryCompletenessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complete: bool
    source_counts: dict[str, int]
    emitted_total: int
    deduplicated_projections: int
    unassigned_total: int
    error_count: int
    errors: list[TodoStoryErrorOut]
    watermark: str
    checked_at: str


class TodoRoutableBoardOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_id: str
    domain_id: str
    title: str
    columns: list[str]
    status_mapping: dict[str, str]


class TodoBoardCatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_id: str
    domain_id: str
    title: str


class TodoFilterCatalogsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kinds: list[str]
    statuses: list[str]
    priorities: list[str]
    sources: list[str]
    boards: list[TodoBoardCatalogOut]


class TodoInventoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[TodoRowOut]
    registered_repos: list[TodoRepositoryOut]
    completeness: TodoInventoryCompletenessOut
    routable_boards: list[TodoRoutableBoardOut]
    filter_catalogs: TodoFilterCatalogsOut
    filtered_total: int
    inventory_total: int
    has_more: bool
    offset: int
    limit: int


class TodoPlacementOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    placement_id: str
    work_item_id: str
    board_id: str
    domain_id: str
    is_primary: bool
    placement_stage: str | None
    card_component: str
    local_fields: dict[str, Any]
    created_at: str
    removed_at: str | None
    active: bool
    role: Literal["primary", "secondary"]
    repo_ids: list[str]
    board_event_join_state: Literal["not_linked"]
    href: str


class TodoRelationshipOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge: WorkEdge
    active: bool
    direction: Literal["outgoing", "incoming"]
    related_item: WorkItem | None


class TodoRoutingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classifications: list[CaptureClassification]
    corrections: list[RoutingCorrection]


class TodoConversationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    href: str


class TodoMissionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    state: Literal["linked", "linked_but_unavailable"]
    record: dict[str, Any] | None
    completion_state: Literal[
        "recorded", "completion_evidence_not_recorded", "unavailable",
        "malformed_source",
    ]


class TodoCompletionEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    evidence_ref: str
    path: str


class TodoTimelineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str | None
    source: str
    kind: str
    payload: Any
    ref: str | None
    sequence: int | str | None


class TodoAuditRecordOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    captured_at: str | None = None
    sha256: str | None = None
    malformed: bool = False
    raw: Any = None


class TodoAuditOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_revisions: list[TodoAuditRecordOut] | None = None
    sync_conflicts: list[TodoAuditRecordOut] | None = None
    active_sync_conflict: dict[str, Any] | None = None


class TodoSourceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["board_card", "capture", "work_graph"]
    card: dict[str, Any] | None
    audit: TodoAuditOut
    exact_board_pairs: list[dict[str, str]]


class TodoCompletenessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complete: bool
    error_count: int
    errors: list[TodoStoryErrorOut]
    board_event_join_state: Literal["exact", "not_linked"]


class TodoDetailOut(BaseModel):
    """Typed top-level contract for the comprehensive TODO story ledger."""
    model_config = ConfigDict(extra="forbid")

    requested_identity: TodoRequestedIdentityOut
    emitted_todo: TodoRowOut | None
    aggregate_todos: list[TodoRowOut]
    canonical_item: WorkItem | None
    linked_work_items: list[WorkItem]
    raw_captures: list[TodoRawCaptureOut]
    source: TodoSourceOut
    repositories: list[TodoRepositoryOut]
    placements: list[TodoPlacementOut]
    relationships: list[TodoRelationshipOut]
    routing: TodoRoutingOut
    conversations: list[TodoConversationOut]
    work_events: list[WorkEvent]
    board_events: list[KanbanEvent]
    missions: list[TodoMissionOut]
    completion_evidence: list[TodoCompletionEvidenceOut]
    timeline: list[TodoTimelineOut]
    archive_history: list[TodoTimelineOut]
    completeness: TodoCompletenessOut


class WorkPlacementIn(BaseModel):
    board_id: str
    domain_id: str
    is_primary: bool = False
    placement_stage: str | None = None
    card_component: str = "generic_task"


class WorkEdgeIn(BaseModel):
    from_work_item_id: str
    to_work_item_id: str
    relation: str
    reason: str | None = None


class TodoAssignIn(BaseModel):
    board_id: str | None = None
    domain_id: str | None = None
    new_board_title: str | None = None
    canonical_title: str | None = None
    canonical_description: str | None = None
    canonical_kind: Literal[
        "note", "todo", "research", "post", "paper", "project", "bug",
        "feature", "decision", "maintenance",
    ] | None = None
    confirm_canonical_fields: bool = False


class MaintenanceDecisionIn(BaseModel):
    decision: Literal["accept", "reject"]
    reason_note: str | None = None


_todo_assignment_lock = threading.RLock()


@contextmanager
def _todo_assignment_guard():
    """Serialize lookup/create/placement recovery across UI worker processes."""
    lock_path = KANBAN_EVENT_LOG.parent / ".locks" / "todo-assignment.write.lock"
    with _todo_assignment_lock, exclusive_write_lock(lock_path):
        yield


def _validate_routable_board_ref(board) -> None:
    """Enforce the generic TODO catalog at the full-console write boundary."""
    if not CHAT_ENABLED:
        return
    matched = any(
        candidate["board_id"] == board.board_id
        and candidate["domain_id"] == board.domain_id
        and board.card_component == "generic_task"
        for candidate in _routable_work_boards()
    )
    if not matched:
        raise HTTPException(
            status_code=400,
            detail=(
                f"board placement {board.board_id!r}/{board.domain_id!r}/"
                f"{board.card_component!r} is not a validated generic TODO board"
            ),
        )


def _validate_routable_plan(plan: WorkPlanIn) -> None:
    if not CHAT_ENABLED:
        return
    for item in plan.items:
        if item.primary_board is not None:
            _validate_routable_board_ref(item.primary_board)
        for board in item.secondary_boards:
            _validate_routable_board_ref(board)


def _wg_call(fn, *args, **kwargs):
    """Translate a graph-integrity violation (cycle/dup primary) → 409, an unknown
    ref → 404. Keeps the human-legible reason."""
    from command_center.work_graph import WorkGraphError
    try:
        return fn(*args, **kwargs)
    except WorkGraphError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/work-items", status_code=201)
def create_work_item(body: WorkItemIn) -> dict:
    svc = _require_workgraph_write()
    item = _wg_call(svc.create_item, body.title, **body.model_dump(exclude={"title"}))
    return {"item": item.model_dump(), "links": [lk.model_dump()
                                                 for lk in svc.links_for(item.work_item_id)]}


@app.get("/api/work-items")
def list_work_items() -> list:
    return [i.model_dump() for i in _require_workgraph().list_items()]


@app.get("/api/work-items/{work_item_id}")
def get_work_item(work_item_id: str) -> dict:
    svc = _require_workgraph()
    item = _wg_call(svc.get_item, work_item_id)
    return {"item": item.model_dump(),
            "placements": [p.model_dump()
                           for p in svc._store.placements_for(work_item_id)],
            "links": [lk.model_dump() for lk in svc.links_for(work_item_id)]}


@app.put("/api/work-items/{work_item_id}/description")
def update_work_item_description(work_item_id: str, body: WorkDescriptionIn) -> dict:
    """Edit the organized WorkItem text; immutable source text is never touched."""
    svc = _require_workgraph_write()
    item = _wg_call(
        svc.update_description,
        work_item_id,
        body.description,
        expected_updated_at=body.expected_updated_at,
        expected_description=body.expected_description,
    )
    return {"item": item.model_dump()}


@app.get("/api/work-items/{work_item_id}/links")
def get_work_item_links(work_item_id: str) -> list:
    svc = _require_workgraph()
    return [lk.model_dump() for lk in _wg_call(svc.links_for, work_item_id)]


@app.post("/api/work-items/{work_item_id}/status")
def set_work_item_status(work_item_id: str, body: WorkStatusIn) -> dict:
    svc = _require_workgraph_write()
    return _wg_call(svc.set_status, work_item_id, body.status).model_dump()


@app.post("/api/work-items/{work_item_id}/placements", status_code=201)
def add_work_placement(work_item_id: str, body: WorkPlacementIn) -> dict:
    svc = _require_workgraph_write()
    _validate_routable_board_ref(body)
    return _wg_call(svc.add_placement, work_item_id, body.board_id, body.domain_id,
                    is_primary=body.is_primary, placement_stage=body.placement_stage,
                    card_component=body.card_component).model_dump()


@app.delete("/api/work-items/{work_item_id}/placements/{placement_id}")
def remove_work_placement(work_item_id: str, placement_id: str) -> dict:
    svc = _require_workgraph_write()
    placement = _wg_call(svc._store.get_placement, placement_id)
    if placement.work_item_id != work_item_id:
        raise HTTPException(
            status_code=409,
            detail="placement does not belong to the WorkItem in this URL",
        )
    _wg_call(svc.remove_placement, placement_id)
    return {"ok": True}


@app.post("/api/work-edges", status_code=201)
def create_work_edge(body: WorkEdgeIn) -> dict:
    svc = _require_workgraph_write()
    return _wg_call(svc.add_edge, body.from_work_item_id, body.to_work_item_id,
                    body.relation, reason=body.reason).model_dump()


@app.delete("/api/work-edges/{edge_id}")
def remove_work_edge(edge_id: str) -> dict:
    svc = _require_workgraph_write()
    _wg_call(svc.remove_edge, edge_id)
    return {"ok": True}


@app.get("/api/work-graph")
def whole_work_graph() -> dict:
    return _require_workgraph().graph().model_dump()


def _todo_repository_contract() -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Read exact registered repos and the validated board-to-repo mapping."""
    autonomy_path = CONFIGS_DIR / "autonomy.yaml"
    if not autonomy_path.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"registered repository config not found: {autonomy_path}",
        )
    autonomy = _read_yaml_file(autonomy_path)
    manifests = autonomy.get("repo_manifests")
    if not isinstance(manifests, list):
        raise HTTPException(
            status_code=503,
            detail="autonomy.yaml repo_manifests must be a list",
        )
    registered: list[dict[str, Any]] = []
    seen_repo_ids: set[str] = set()
    for index, manifest in enumerate(manifests):
        if not isinstance(manifest, dict):
            raise HTTPException(
                status_code=503,
                detail=f"autonomy.yaml repo_manifests[{index}] must be an object",
            )
        repo_id = manifest.get("repo_id")
        remote_url = manifest.get("remote_url")
        if not isinstance(repo_id, str) or not repo_id.strip():
            raise HTTPException(
                status_code=503,
                detail=f"autonomy.yaml repo_manifests[{index}] has no repo_id",
            )
        if repo_id in seen_repo_ids:
            raise HTTPException(
                status_code=503,
                detail=f"autonomy.yaml contains duplicate repo_id {repo_id!r}",
            )
        if not isinstance(remote_url, str) or not remote_url.strip():
            raise HTTPException(
                status_code=503,
                detail=f"registered repository {repo_id!r} has no remote_url",
            )
        seen_repo_ids.add(repo_id)
        registered.append({
            "repo_id": repo_id,
            "remote_url": remote_url,
        })

    board_repo_ids: dict[str, list[str]] = {}
    for board in _read_board_registry_data().get("boards", []):
        board_id = str(board["board_id"])
        repo_ids = [str(repo_id) for repo_id in board["repo_ids"]]
        unknown = [repo_id for repo_id in repo_ids if repo_id not in seen_repo_ids]
        if unknown:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"kanban board {board_id!r} references unregistered repos: "
                    f"{', '.join(unknown)}"
                ),
            )
        board_repo_ids[board_id] = repo_ids
    return registered, board_repo_ids


def _todo_repo_ids(boards: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(
        repo_id
        for board in boards
        for repo_id in board["repo_ids"]
    ))


def _todo_board_repo_ids(
    board_id: str, board_repo_ids: dict[str, list[str]],
) -> list[str]:
    if board_id not in board_repo_ids:
        raise HTTPException(
            status_code=503,
            detail=f"TODO references board {board_id!r} absent from kanban_boards.yaml",
        )
    return board_repo_ids[board_id]


def _todo_board_links(
    service, item, board_repo_ids: dict[str, list[str]],
) -> list[dict[str, Any]]:
    return [
        {
            "board_id": placement.board_id,
            "domain_id": placement.domain_id,
            "is_primary": placement.is_primary,
            "placement_id": placement.placement_id,
            "repo_ids": _todo_board_repo_ids(
                placement.board_id, board_repo_ids),
            "href": "?" + urlencode({
                "view": "domains", "domain": placement.domain_id,
                "work": item.work_item_id,
            }),
        }
        for placement in service._store.placements_for(item.work_item_id)
    ]


def _work_todo_row(
    service, item, board_repo_ids: dict[str, list[str]] | None = None,
    available_source_cards: set[str] | None = None,
) -> dict[str, Any]:
    if board_repo_ids is None:
        _registered_repos, board_repo_ids = _todo_repository_contract()
    boards = _todo_board_links(service, item, board_repo_ids)
    source_kind = "work_graph"
    source_id = item.work_item_id
    if item.capture_id:
        source_kind, source_id = "capture", item.capture_id
    elif (item.packet_id or "").startswith("todo-source:"):
        source_kind = "board_card"
        source_id = str(item.packet_id).removeprefix("todo-source:")
        source_domain, separator, source_card = source_id.partition(":")
        if (
            separator
            and (
                available_source_cards is None
                or source_id in available_source_cards
            )
            and not any(board["domain_id"] == source_domain for board in boards)
        ):
            source_spec = next((
                domain for domain in _domain_config().get("domains", [])
                if domain.get("domain_id") == source_domain
            ), None)
            if source_spec is None:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        f"source-backed TODO references domain {source_domain!r} "
                        "absent from domain_surfaces.yaml"
                    ),
                )
            source_board_id = str(source_spec["board_id"])
            boards.append({
                "board_id": source_board_id,
                "domain_id": source_domain,
                "is_primary": False,
                "placement_id": None,
                "source_projection": True,
                "repo_ids": _todo_board_repo_ids(
                    source_board_id, board_repo_ids,
                ),
                "href": "?" + urlencode({
                    "view": "domains", "domain": source_domain, "card": source_card,
                }),
            })
    return {
        "todo_id": f"work:{item.work_item_id}",
        "work_item_id": item.work_item_id,
        "source_kind": source_kind,
        "source_id": source_id,
        "raw_preview": None,
        "title": item.title,
        "description": item.description,
        "kind": item.kind,
        "status": item.canonical_status,
        "raw_status": item.canonical_status,
        "assigned": bool(boards),
        "boards": boards,
        "repo_ids": _todo_repo_ids(boards),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "source_href": "?" + urlencode({"view": "work-map", "work": item.work_item_id}),
        "assignable": True,
        "integrity": {"missing_fields": []},
    }


def _capture_todo_row(view) -> dict[str, Any]:
    classification = view.classification
    raw_kind = classification.capture_kind if classification else None
    kind = {
        "research_question": "research", "idea": "note", "reminder": "todo",
        "reference": "note", "board_candidate": "project",
    }.get(raw_kind, raw_kind) if raw_kind is not None else None
    record = view.record
    return {
        "todo_id": f"capture:{record.capture_id}",
        "work_item_id": None,
        "source_kind": "capture",
        "source_id": record.capture_id,
        "raw_preview": record.raw_content[:240],
        "title": None,
        "description": record.raw_content,
        "kind": kind,
        "status": None,
        "raw_status": view.processing_status,
        "assigned": False,
        "boards": [],
        "repo_ids": [],
        "created_at": record.captured_at,
        "updated_at": view.updated_at,
        "source_href": "?" + urlencode({"view": "inbox", "capture": record.capture_id}),
        "assignable": True,
        "integrity": {
            "missing_fields": [
                field for field, value in (
                    ("title", None), ("kind", kind), ("canonical_status", None),
                )
                if value is None
            ],
        },
    }


def _card_todo_row(
    domain: dict, card: dict,
    board_repo_ids: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    if board_repo_ids is None:
        _registered_repos, board_repo_ids = _todo_repository_contract()
    domain_id = str(domain["domain_id"])
    card_id = str(card["card_id"])
    board_id = str(domain["board_id"])
    repo_ids = _todo_board_repo_ids(board_id, board_repo_ids)
    href = "?" + urlencode({"view": "domains", "domain": domain_id,
                             "card": card_id})
    title = card.get("title") if isinstance(card.get("title"), str) else None
    description = (
        card.get("description") if isinstance(card.get("description"), str) else None
    )
    kind = card.get("kind") if isinstance(card.get("kind"), str) else None
    canonical_status = (
        card.get("canonical_status")
        if isinstance(card.get("canonical_status"), str) else None
    )
    raw_status = card.get("status") if isinstance(card.get("status"), str) else None
    priority = next((
        value.strip()
        for field in ("priority", "research_priority", "tier", "severity")
        if isinstance((value := card.get(field)), str) and value.strip()
    ), None)
    impact = (
        card["impact"].strip()
        if isinstance(card.get("impact"), str) and card["impact"].strip()
        else None
    )
    timeline = (
        card["timeline"].strip()
        if isinstance(card.get("timeline"), str) and card["timeline"].strip()
        else None
    )
    return {
        "todo_id": f"card:{domain_id}:{card_id}",
        "work_item_id": None,
        "source_kind": "board_card",
        "source_id": f"{domain_id}:{card_id}",
        "raw_preview": None,
        "title": title,
        "description": description,
        "kind": kind,
        "status": canonical_status,
        "raw_status": raw_status,
        "priority": priority,
        "impact": impact,
        "timeline": timeline,
        "assigned": True,
        "boards": [{
            "board_id": board_id,
            "domain_id": domain_id, "is_primary": True,
            "placement_id": None, "href": href, "repo_ids": repo_ids,
        }],
        "repo_ids": repo_ids,
        "created_at": card.get("created_at"),
        "updated_at": card.get("updated_at"),
        "source_href": href,
        "assignable": True,
        "integrity": {
            "missing_fields": [
                field for field, value in (
                    ("title", title), ("description", description), ("kind", kind),
                    ("canonical_status", canonical_status), ("status", raw_status),
                ) if value is None
            ],
        },
    }


def _all_todo_inventory() -> dict[str, Any]:
    registered_repos, board_repo_ids = _todo_repository_contract()
    service = _require_workgraph()
    items = service.list_items()
    captured_ids = {item.capture_id for item in items if item.capture_id}
    materialized_sources = {
        str(item.packet_id).removeprefix("todo-source:")
        for item in items if (item.packet_id or "").startswith("todo-source:")
    }
    source_counts = {"work_items": len(items), "captures": 0, "board_cards": 0}
    deduplicated = 0
    errors: list[dict[str, str]] = []
    cached_board_sources: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    available_source_cards: set[str] = set()
    domains = [
        domain for domain in _domain_config().get("domains", [])
        if domain.get("source") == "board_store"
        and domain.get("card_component") == "generic_task"
    ]
    for domain in domains:
        try:
            cards = _domain_cards(domain)["cards"]
        except Exception:  # noqa: BLE001 - partial state must be explicit
            domain_id = str(domain.get("domain_id"))
            logger.exception(
                "Master TODO inventory could not read board authority %s", domain_id,
            )
            errors.append({
                "source": domain_id, "code": "source_unavailable",
                "message": "board TODO inventory is unavailable",
            })
            continue
        cached_board_sources.append((domain, cards))
        available_source_cards.update(
            f"{domain['domain_id']}:{card.get('card_id')}" for card in cards
        )
    for missing_source in sorted(materialized_sources - available_source_cards):
        errors.append({
            "source": f"card:{missing_source}",
            "code": "linked_but_unavailable",
            "message": "WorkItem source card is unavailable",
        })
    rows = [
        _work_todo_row(
            service, item, board_repo_ids,
            available_source_cards=available_source_cards,
        )
        for item in items
    ]
    existing_work_ids = {item.work_item_id for item in items}
    try:
        captures = _require_capture().list()
        source_counts["captures"] = len(captures)
        available_capture_ids = {view.record.capture_id for view in captures}
        for missing_capture in sorted(captured_ids - available_capture_ids):
            errors.append({
                "source": f"capture:{missing_capture}",
                "code": "linked_but_unavailable",
                "message": "WorkItem capture source is unavailable",
            })
        for view in captures:
            linked_by_event: set[str] = set()
            invalid_link_history = False
            for event in _get_capture_service()._store.events(view.record.capture_id):
                if event.kind != "link":
                    continue
                work_item_ids = event.payload.get("work_item_ids")
                if not isinstance(work_item_ids, list) or not all(
                    isinstance(work_id, str) for work_id in work_item_ids
                ):
                    invalid_link_history = True
                    errors.append({
                        "source": f"capture:{view.record.capture_id}",
                        "code": "malformed_link_history",
                        "message": "capture link history does not contain exact string WorkItem IDs",
                    })
                    continue
                missing = sorted(set(work_item_ids) - existing_work_ids)
                if missing:
                    invalid_link_history = True
                    errors.append({
                        "source": f"capture:{view.record.capture_id}",
                        "code": "dangling_work_item_link",
                        "message": "capture links to unavailable WorkItems: " + ", ".join(missing),
                    })
                linked_by_event.update(set(work_item_ids) & existing_work_ids)
            if view.record.capture_id in captured_ids or (
                linked_by_event and not invalid_link_history
            ):
                deduplicated += 1
                continue
            task_like = (
                view.record.requested_mode != "save_only"
                or (view.classification is not None and
                    view.classification.capture_kind not in {"note", "reference"})
            )
            if task_like:
                rows.append(_capture_todo_row(view))
    except Exception:  # noqa: BLE001 - partial state must be explicit
        logger.exception("Master TODO inventory could not read capture authority")
        errors.append({
            "source": "captures", "code": "source_unavailable",
            "message": "capture inventory is unavailable",
        })
    for domain, cards in cached_board_sources:
        for card in cards:
            if card.get("projection_source") == "work_graph":
                projected_work_id = card.get("work_item_id")
                if (
                    isinstance(projected_work_id, str)
                    and projected_work_id in existing_work_ids
                ):
                    deduplicated += 1
                    continue
                errors.append({
                    "source": (
                        f"card:{domain.get('domain_id')}:{card.get('card_id')}"
                    ),
                    "code": "dangling_work_graph_projection",
                    "message": "board projection does not reference an available WorkItem",
                })
            if card.get("source_kind") in {"source_document", "idea_bank"}:
                continue
            source_counts["board_cards"] += 1
            source_key = f"{domain['domain_id']}:{card.get('card_id')}"
            if source_key in materialized_sources:
                deduplicated += 1
                continue
            rows.append(_card_todo_row(domain, card, board_repo_ids))
    rows.sort(key=lambda row: (
        str(row.get("status") in {"done", "archived", "rejected"}),
        str(row.get("updated_at") or row.get("created_at") or ""),
        str(row["todo_id"]),
    ), reverse=True)
    watermark = hashlib.sha256(json.dumps(
        rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    domain_titles = {
        str(domain.get("domain_id")): str(domain.get("title") or domain.get("domain_id"))
        for domain in _domain_config().get("domains", [])
    }
    board_catalog = sorted({
        (str(board["board_id"]), str(board["domain_id"]),
         domain_titles.get(str(board["domain_id"]), str(board["board_id"])))
        for row in rows for board in row["boards"]
    })
    return {
        "rows": rows,
        "registered_repos": registered_repos,
        "completeness": {
            "complete": not errors,
            "source_counts": source_counts,
            "emitted_total": len(rows),
            "deduplicated_projections": deduplicated,
            "unassigned_total": sum(not row["assigned"] for row in rows),
            "error_count": len(errors),
            "errors": errors,
            "watermark": watermark,
            "checked_at": datetime.now(UTC).isoformat(),
        },
        "routable_boards": _routable_work_boards(),
        "filter_catalogs": {
            "kinds": sorted({
                row["kind"] for row in rows if isinstance(row.get("kind"), str)
            }),
            "statuses": sorted({
                row["status"] for row in rows if isinstance(row.get("status"), str)
            }),
            "priorities": sorted({
                row["priority"]
                for row in rows
                if isinstance(row.get("priority"), str)
            }),
            "sources": sorted({str(row["source_kind"]) for row in rows}),
            "boards": [
                {"board_id": board_id, "domain_id": domain_id, "title": title}
                for board_id, domain_id, title in board_catalog
            ],
        },
    }


@app.get(
    "/api/todos",
    response_model=TodoInventoryOut,
)
def all_todos(
    q: str = "", kind: str = "", status: str = "", priority: str = "",
    source: str = "", assigned: bool | None = None, board_id: str = "",
    offset: int = 0, limit: int = 10000,
) -> dict:
    if offset < 0 or not 1 <= limit <= 10000:
        raise HTTPException(status_code=400, detail="offset must be >= 0 and limit 1..10000")
    result = _all_todo_inventory()
    rows = result["rows"]
    query = q.strip().casefold()
    filtered = [row for row in rows if (
        (
            not query
            or query in " ".join(
                value for value in (
                    row.get("title"), row.get("description"), row.get("raw_preview"),
                )
                if isinstance(value, str)
            ).casefold()
        )
        and (not kind or row["kind"] == kind)
        and (not status or row["status"] == status)
        and (not priority or row.get("priority") == priority)
        and (not source or row["source_kind"] == source)
        and (assigned is None or row["assigned"] is assigned)
        and (not board_id or any(board["board_id"] == board_id for board in row["boards"]))
    )]
    result["rows"] = filtered[offset:offset + limit]
    result["filtered_total"] = len(filtered)
    result["inventory_total"] = len(rows)
    result["has_more"] = offset + limit < len(filtered)
    result["offset"] = offset
    result["limit"] = limit
    return result


def _todo_detail_error(
    errors: list[dict[str, str]], source: str, code: str, message: str,
) -> None:
    errors.append({"source": source, "code": code, "message": message})


def _todo_source_card(domain_id: str, card_id: str) -> tuple[dict, dict]:
    spec = _domain_spec(domain_id)
    if spec.get("source") != "board_store":
        raise HTTPException(status_code=404, detail="TODO source is not a board-store card")
    return spec, _find_domain_card(_board_store_provider(spec), card_id)


def _todo_audit_fields(
    spec: dict, card: dict, errors: list[dict[str, str]],
) -> dict[str, Any]:
    if spec.get("domain_id") not in GRAND_TODO_DOMAIN_IDS:
        return {}
    audit: dict[str, Any] = {}
    for field in ("source_revisions", "sync_conflicts"):
        value = card.get(field, [])
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            _todo_detail_error(
                errors, "grand_todo", "malformed_audit_history",
                f"stored {field} is not a list of records",
            )
            audit[field] = None
        else:
            checked: list[dict[str, Any]] = []
            for index, row in enumerate(value):
                captured_at = row.get("captured_at")
                sha256 = row.get("sha256")
                if (
                    captured_at is not None and not isinstance(captured_at, str)
                ) or (
                    sha256 is not None and not isinstance(sha256, str)
                ):
                    _todo_detail_error(
                        errors, "grand_todo", "malformed_source",
                        f"stored {field}[{index}] has a non-string audit field",
                    )
                    checked.append({"malformed": True, "raw": row})
                else:
                    checked.append({**row, "malformed": False, "raw": None})
            audit[field] = checked
    active_conflict = card.get("active_sync_conflict")
    if active_conflict is not None and not isinstance(active_conflict, dict):
        _todo_detail_error(
            errors, "grand_todo", "malformed_audit_history",
            "stored active_sync_conflict is not a record or null",
        )
        audit["active_sync_conflict"] = {
            "malformed": True, "raw": active_conflict,
        }
    else:
        audit["active_sync_conflict"] = active_conflict
    return audit


def _todo_completion_refs(value: Any, *, path: str) -> list[dict[str, str]]:
    """Collect only explicitly stored evidence_ref(s), preserving their paths."""
    found: list[dict[str, str]] = []
    if isinstance(value, dict):
        evidence_ref = value.get("evidence_ref")
        if isinstance(evidence_ref, str) and evidence_ref:
            found.append({"evidence_ref": evidence_ref, "path": path + ".evidence_ref"})
        evidence_refs = value.get("evidence_refs")
        if isinstance(evidence_refs, list):
            found.extend(
                {"evidence_ref": ref, "path": path + ".evidence_refs"}
                for ref in evidence_refs if isinstance(ref, str) and ref
            )
        for key, child in value.items():
            if key not in {"evidence_ref", "evidence_refs"}:
                found.extend(_todo_completion_refs(child, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_todo_completion_refs(child, path=f"{path}[{index}]"))
    return found


def _todo_detail(todo_id: str) -> dict[str, Any]:
    service = _require_workgraph()
    registered_repos, board_repo_ids = _todo_repository_contract()
    errors: list[dict[str, str]] = []
    identity_kind = ""
    identity_ref = ""
    source_spec: dict | None = None
    source_card: dict | None = None
    requested_capture_id: str | None = None
    canonical_item = None

    if todo_id.startswith("work:") and todo_id != "work:":
        identity_kind, identity_ref = "work", todo_id.removeprefix("work:")
        canonical_item = _wg_call(service.get_item, identity_ref)
    elif todo_id.startswith("capture:") and todo_id != "capture:":
        identity_kind, identity_ref = "capture", todo_id.removeprefix("capture:")
        requested_capture_id = identity_ref
    elif todo_id.startswith("card:"):
        raw = todo_id.removeprefix("card:")
        domain_id, separator, card_id = raw.partition(":")
        if not separator or not domain_id or not card_id:
            raise HTTPException(status_code=400, detail="invalid board-card TODO id")
        identity_kind, identity_ref = "card", raw
        source_spec, source_card = _todo_source_card(domain_id, card_id)
    else:
        raise HTTPException(status_code=404, detail=f"unknown TODO identity {todo_id!r}")

    capture_views: dict[str, Any] = {}
    capture_events: dict[str, list[Any]] = {}
    capture_source_available = True
    try:
        capture_service = _require_capture()
        for view in capture_service.list():
            capture_id = view.record.capture_id
            capture_views[capture_id] = view
            capture_events[capture_id] = list(capture_service._store.events(capture_id))
    except Exception:  # noqa: BLE001 - optional authority is reported, never fabricated
        capture_source_available = False
        _todo_detail_error(
            errors, "captures", "source_unavailable", "capture history is unavailable",
        )

    if requested_capture_id and not capture_source_available:
        raise HTTPException(status_code=503, detail="capture history is unavailable")
    if requested_capture_id and requested_capture_id not in capture_views:
        raise HTTPException(status_code=404, detail=f"capture {requested_capture_id!r} not found")

    linked_ids: list[str] = []
    if canonical_item is not None:
        linked_ids.append(canonical_item.work_item_id)
    if identity_kind == "card":
        packet_id = f"todo-source:{identity_ref}"
        linked_ids.extend(
            item.work_item_id for item in service.list_items()
            if item.packet_id == packet_id
        )
    if identity_kind == "capture":
        linked_ids.extend(
            item.work_item_id for item in service.list_items()
            if item.capture_id == identity_ref
        )
    target_work_ids = set(linked_ids)
    for capture_id, events in capture_events.items():
        for event in events:
            if event.kind != "link":
                continue
            work_item_ids = event.payload.get("work_item_ids")
            if (
                not isinstance(work_item_ids, list)
                or not all(isinstance(work_id, str) for work_id in work_item_ids)
            ):
                _todo_detail_error(
                    errors, f"capture:{capture_id}", "malformed_link_event",
                    "stored capture link does not contain exact string WorkItem IDs",
                )
                continue
            exact_ids = work_item_ids
            if identity_kind == "capture" and capture_id == identity_ref:
                linked_ids.extend(exact_ids)
                target_work_ids.update(exact_ids)
            elif target_work_ids.intersection(exact_ids):
                requested_capture_id = requested_capture_id or capture_id

    linked_ids = list(dict.fromkeys(linked_ids))
    linked_items: list[Any] = []
    missing_work_ids: list[str] = []
    for work_id in linked_ids:
        try:
            linked_items.append(service.get_item(work_id))
        except KeyError:
            missing_work_ids.append(work_id)
            _todo_detail_error(
                errors, f"work:{work_id}", "dangling_capture_link",
                "capture history links to a WorkItem that is unavailable",
            )
    linked_item_ids = {item.work_item_id for item in linked_items}

    related_capture_ids: set[str] = set()
    for item in linked_items:
        if item.capture_id:
            related_capture_ids.add(item.capture_id)
    if identity_kind == "capture":
        related_capture_ids.add(identity_ref)
    for capture_id, events in capture_events.items():
        if any(
            event.kind == "link"
            and isinstance(event.payload.get("work_item_ids"), list)
            and all(
                isinstance(work_id, str)
                for work_id in event.payload["work_item_ids"]
            )
            and linked_item_ids.intersection(event.payload["work_item_ids"])
            for event in events
        ):
            related_capture_ids.add(capture_id)

    raw_captures: list[dict[str, Any]] = []
    conversation_ids: set[str] = set()
    for capture_id in sorted(related_capture_ids):
        view = capture_views.get(capture_id)
        if view is None:
            _todo_detail_error(
                errors, f"capture:{capture_id}", "linked_but_unavailable",
                "linked capture record is unavailable",
            )
            continue
        record = view.record.model_dump()
        if view.record.conversation_id:
            conversation_ids.add(view.record.conversation_id)
        events = [event.model_dump() for event in capture_events.get(capture_id, [])]
        for event in events:
            event_conversation = event["payload"].get("conversation_id")
            if isinstance(event_conversation, str) and event_conversation:
                conversation_ids.add(event_conversation)
        raw_captures.append({
            "record": record,
            "processing_status": view.processing_status,
            "classification": (
                view.classification.model_dump() if view.classification else None
            ),
            "events": events,
        })

    if canonical_item is not None and canonical_item.capture_id in capture_views:
        requested_capture_id = canonical_item.capture_id
    if source_card is None:
        packet_source = next((
            str(item.packet_id).removeprefix("todo-source:")
            for item in linked_items
            if (item.packet_id or "").startswith("todo-source:")
        ), None)
        if packet_source:
            domain_id, separator, card_id = packet_source.partition(":")
            if separator:
                try:
                    source_spec, source_card = _todo_source_card(domain_id, card_id)
                except HTTPException:
                    _todo_detail_error(
                        errors, "source_card", "linked_but_unavailable",
                        "linked source card is unavailable",
                    )

    source_public: dict[str, Any] | None = None
    audit: dict[str, Any] = {}
    exact_board_pairs: set[tuple[str, str]] = set()
    if source_spec is not None and source_card is not None:
        source_public = {
            key: value for key, value in source_card.items()
            if key not in _BOARD_AUDIT_HISTORY_FIELDS
        }
        audit = _todo_audit_fields(source_spec, source_card, errors)
        exact_board_pairs.add((str(source_spec["board_id"]), str(source_card["card_id"])))
    for capture in raw_captures:
        record = capture["record"]
        if record.get("current_board_id") and record.get("current_card_id"):
            exact_board_pairs.add((record["current_board_id"], record["current_card_id"]))

    placements: list[dict[str, Any]] = []
    repo_ids: set[str] = set()
    for item in linked_items:
        for placement in service._store.placements_for(
            item.work_item_id, active_only=False,
        ):
            placement_repo_ids = _todo_board_repo_ids(placement.board_id, board_repo_ids)
            repo_ids.update(placement_repo_ids)
            placements.append({
                **placement.model_dump(),
                "active": placement.removed_at is None,
                "role": "primary" if placement.is_primary else "secondary",
                "repo_ids": placement_repo_ids,
                "board_event_join_state": "not_linked",
                "href": "?" + urlencode({
                    "view": "domains", "domain": placement.domain_id,
                    "work": placement.work_item_id,
                }),
            })
    if source_spec is not None:
        repo_ids.update(_todo_board_repo_ids(str(source_spec["board_id"]), board_repo_ids))
    repositories = [repo for repo in registered_repos if repo["repo_id"] in repo_ids]

    relationships: list[dict[str, Any]] = []
    for edge in service._store.edges(active_only=False):
        from_linked = edge.from_work_item_id in linked_item_ids
        to_linked = edge.to_work_item_id in linked_item_ids
        if not from_linked and not to_linked:
            continue
        related_id = edge.to_work_item_id if from_linked else edge.from_work_item_id
        try:
            related_item = service.get_item(related_id).model_dump()
        except KeyError:
            related_item = None
            _todo_detail_error(
                errors, f"work:{related_id}", "related_item_unavailable",
                "relationship endpoint WorkItem is unavailable",
            )
        relationships.append({
            "edge": edge.model_dump(),
            "active": edge.removed_at is None,
            "direction": "outgoing" if from_linked else "incoming",
            "related_item": related_item,
        })

    work_events = [
        event.model_dump()
        for item in linked_items
        for event in service._store.events(item.work_item_id)
    ]
    for item in linked_items:
        if item.conversation_id:
            conversation_ids.add(item.conversation_id)

    routing_corrections: list[dict[str, Any]] = []
    try:
        linked_work_refs = {
            ref
            for item in linked_items
            for ref in (item.work_item_id, f"work:{item.work_item_id}")
        }
        for correction in _get_telemetry_service().list():
            if (
                correction.capture_id in related_capture_ids
                or correction.ref in linked_work_refs
            ):
                routing_corrections.append(correction.model_dump())
    except Exception:  # noqa: BLE001 - optional evidence stays explicitly partial
        _todo_detail_error(
            errors, "routing", "source_unavailable", "routing correction history is unavailable",
        )

    board_events: list[dict[str, Any]] = []
    try:
        board_events = [
            event.model_dump(mode="json") for event in EventLog(KANBAN_EVENT_LOG).read()
            if (event.board_id, event.card_id) in exact_board_pairs
        ]
    except Exception:  # noqa: BLE001 - malformed/unavailable log is explicit
        _todo_detail_error(
            errors, "board_events", "source_unavailable", "board event history is unavailable",
        )

    mission_ids = list(dict.fromkeys([
        *[item.mission_id for item in linked_items if item.mission_id],
        *[event["mission_id"] for event in board_events if event.get("mission_id")],
    ]))
    missions_out: list[dict[str, Any]] = []
    completion_evidence: list[dict[str, Any]] = []
    for mission_id in mission_ids:
        try:
            payload = mission(mission_id)
            events = payload.get("events") if isinstance(payload, dict) else None
            malformed_events = (
                not isinstance(events, list)
                or any(
                    not isinstance(event, dict)
                    or not isinstance(event.get("kind"), str)
                    or (
                        event.get("ts") is not None
                        and not isinstance(event.get("ts"), str)
                    )
                    for event in (events if isinstance(events, list) else [])
                )
            )
            valid_events = events if isinstance(events, list) and not malformed_events else []
            verification_events = [
                event for event in valid_events
                if event.get("kind") == "mission.verification"
            ]
            verdicts = [
                event for event in valid_events
                if event.get("kind") == "mission.completion_verdict"
            ]
            malformed_completion = any(
                not isinstance(event.get("payload"), dict)
                for event in [*verification_events, *verdicts]
            )
            for verdict in verdicts:
                verdict_payload = verdict.get("payload")
                if not isinstance(verdict_payload, dict):
                    continue
                status = verdict_payload.get("status")
                evidence_refs = verdict_payload.get("evidence_refs")
                if (
                    status not in {"PASS", "BLOCKED"}
                    or not isinstance(evidence_refs, list)
                    or any(
                        not isinstance(ref, str) or not ref.strip()
                        for ref in (evidence_refs if isinstance(evidence_refs, list) else [])
                    )
                    or (status == "PASS" and not evidence_refs)
                ):
                    malformed_completion = True
            malformed_events = malformed_events or malformed_completion
            if malformed_events:
                _todo_detail_error(
                    errors, f"mission:{mission_id}", "malformed_source",
                    "linked mission events are not a valid event list",
                )
            missions_out.append({
                "mission_id": mission_id,
                "state": "linked",
                "record": payload,
                "completion_state": (
                    "malformed_source" if malformed_events
                    else "recorded" if verdicts
                    else "completion_evidence_not_recorded"
                ),
            })
            for index, verification in enumerate(verification_events):
                completion_evidence.extend(
                    {"mission_id": mission_id, **row}
                    for row in _todo_completion_refs(
                        verification.get("payload"),
                        path=(
                            f"mission:{mission_id}.events."
                            f"mission.verification[{index}]"
                        ),
                    )
                )
            for index, verdict in enumerate(verdicts):
                completion_evidence.extend(
                    {"mission_id": mission_id, **row}
                    for row in _todo_completion_refs(
                        verdict.get("payload"),
                        path=(
                            f"mission:{mission_id}.events."
                            f"mission.completion_verdict[{index}]"
                        ),
                    )
                )
        except Exception:  # noqa: BLE001 - exact dangling link, safe public message
            missions_out.append({
                "mission_id": mission_id,
                "state": "linked_but_unavailable",
                "record": None,
                "completion_state": "unavailable",
            })
            _todo_detail_error(
                errors, f"mission:{mission_id}", "linked_but_unavailable",
                "linked mission history is unavailable",
            )

    timeline: list[dict[str, Any]] = []
    def add_timeline(at, source, kind, payload, ref, sequence=None):
        if at is not None and not isinstance(at, str):
            _todo_detail_error(
                errors, source, "malformed_source",
                "stored event timestamp is not a string or null",
            )
            at = None
        if not isinstance(kind, str):
            _todo_detail_error(
                errors, source, "malformed_source",
                "stored event kind is not a string",
            )
            return
        timeline.append({
            "at": at, "source": source, "kind": kind, "payload": payload,
            "ref": ref, "sequence": sequence,
        })
    for event in work_events:
        add_timeline(event.get("ts"), "work_graph", event.get("kind"),
                     event.get("payload"), event.get("work_item_id"), event.get("event_seq"))
    work_event_refs = {
        (event.get("kind"), event.get("payload", {}).get(id_field))
        for event in work_events
        if isinstance(event.get("payload"), dict)
        for id_field in ("placement_id", "edge_id")
        if event.get("payload", {}).get(id_field) is not None
    }
    for capture in raw_captures:
        capture_id = capture["record"]["capture_id"]
        add_timeline(capture["record"].get("captured_at"), "capture", "captured",
                     {"source_type": capture["record"].get("source_type")}, capture_id, 0)
        for index, event in enumerate(capture["events"], 1):
            add_timeline(event.get("ts"), "capture", event.get("kind"),
                         event.get("payload"), capture_id, index)
    for event in board_events:
        add_timeline(event.get("created_at"), "board", event.get("event_type"),
                     event, event.get("event_id"))
    for placement in placements:
        if (
            placement.get("removed_at")
            and ("placement_removed", placement["placement_id"]) not in work_event_refs
        ):
            add_timeline(placement["removed_at"], "placement", "placement_removed",
                         placement, placement["placement_id"])
    for relationship in relationships:
        edge = relationship["edge"]
        if relationship["direction"] == "incoming":
            add_timeline(edge.get("created_at"), "relationship", "edge_added",
                         edge, edge["edge_id"])
        if edge.get("removed_at") and (
            relationship["direction"] == "incoming"
            or ("edge_removed", edge["edge_id"]) not in work_event_refs
        ):
            add_timeline(edge["removed_at"], "relationship", "edge_removed",
                         edge, edge["edge_id"])
    for correction in routing_corrections:
        add_timeline(correction.get("at"), "routing", "routing_correction",
                     correction, correction.get("correction_id"))
    for mission_row in missions_out:
        record = mission_row.get("record")
        if (
            not isinstance(record, dict)
            or mission_row.get("completion_state") == "malformed_source"
        ):
            continue
        for index, event in enumerate(record.get("events") or []):
            if isinstance(event, dict):
                add_timeline(
                    event.get("ts"), "mission", str(event.get("kind") or "event"),
                    event.get("payload") or {}, mission_row.get("mission_id"), index,
                )
    for index, revision in enumerate(audit.get("source_revisions") or []):
        if revision.get("malformed"):
            continue
        add_timeline(revision.get("captured_at"), "grand_todo", "source_revision",
                     revision, revision.get("sha256"), index)
    timeline.sort(key=lambda row: (
        row["at"] is None, row["at"] or "", row["source"],
        str(row["sequence"] if row["sequence"] is not None else ""), str(row["ref"] or ""),
    ))
    archive_history: list[dict[str, Any]] = []
    archived_status_by_ref: dict[str, bool] = {}
    for row in timeline:
        payload = row.get("payload")
        status_value = None
        status_ref = str(row.get("ref") or "")
        if row["kind"] == "status" and isinstance(payload, dict):
            status_value = payload.get("status")
        elif row["source"] == "board" and isinstance(payload, dict):
            status_value = payload.get("status_after")
            status_ref = f"{payload.get('board_id')}:{payload.get('card_id')}"
        if isinstance(status_value, str):
            ref = status_ref
            was_archived = archived_status_by_ref.get(ref, False)
            is_archived = status_value.casefold() in {"archived", "rejected"}
            if was_archived or is_archived:
                archive_history.append(row)
            archived_status_by_ref[ref] = is_archived
        elif row["kind"] in {
            "archived", "restored", "placement_added", "placement_removed",
            "edge_added", "edge_removed",
        }:
            archive_history.append(row)

    available_story_sources = (
        {f"{source_spec['domain_id']}:{source_card['card_id']}"}
        if source_spec is not None and source_card is not None else set()
    )
    aggregate_todos = [
        _work_todo_row(
            service, item, board_repo_ids,
            available_source_cards=available_story_sources,
        )
        for item in linked_items
    ]
    if identity_kind == "work":
        emitted_todo = aggregate_todos[0]
        identity_state = "emitted"
    elif linked_items:
        emitted_todo = None
        identity_state = "folded_into_work_items"
    elif identity_kind == "capture":
        emitted_todo = _capture_todo_row(capture_views[identity_ref])
        identity_state = "not_materialized"
    else:
        emitted_todo = _card_todo_row(source_spec, source_card, board_repo_ids)
        identity_state = "not_materialized"

    return {
        "requested_identity": {
            "todo_id": todo_id,
            "kind": identity_kind,
            "source_id": identity_ref,
            "state": identity_state,
            "is_emitted_master_todo": emitted_todo is not None,
            "missing_linked_work_item_ids": missing_work_ids,
        },
        "emitted_todo": emitted_todo,
        "aggregate_todos": aggregate_todos,
        "canonical_item": canonical_item.model_dump() if canonical_item else None,
        "linked_work_items": [item.model_dump() for item in linked_items],
        "raw_captures": raw_captures,
        "source": {
            "kind": "board_card" if source_card is not None else (
                "capture" if raw_captures else "work_graph"
            ),
            "card": source_public,
            "audit": audit,
            "exact_board_pairs": [
                {"board_id": board_id, "card_id": card_id}
                for board_id, card_id in sorted(exact_board_pairs)
            ],
        },
        "repositories": repositories,
        "placements": placements,
        "relationships": relationships,
        "routing": {
            "classifications": [capture["classification"] for capture in raw_captures
                                if capture["classification"] is not None],
            "corrections": routing_corrections,
        },
        "conversations": [
            {"conversation_id": conversation_id,
             "href": "?" + urlencode({"view": "chat", "conversation": conversation_id})}
            for conversation_id in sorted(conversation_ids)
        ],
        "work_events": work_events,
        "board_events": board_events,
        "missions": missions_out,
        "completion_evidence": completion_evidence,
        "timeline": timeline,
        "archive_history": archive_history,
        "completeness": {
            "complete": not errors,
            "error_count": len(errors),
            "errors": errors,
            "board_event_join_state": (
                "exact" if exact_board_pairs else "not_linked"
            ),
        },
    }


@app.get("/api/todos/{todo_id:path}", response_model=TodoDetailOut)
def todo_detail(todo_id: str) -> dict[str, Any]:
    """Comprehensive, evidence-preserving story for one requested TODO identity."""
    return _todo_detail(todo_id)


def _resolve_assignment_board(body: TodoAssignIn) -> dict[str, Any]:
    if body.new_board_title and (body.board_id or body.domain_id):
        raise HTTPException(status_code=400, detail="choose an existing board or a new board, not both")
    if body.new_board_title:
        title = body.new_board_title.strip()
        board_id = _slug_board_id(title)
        existing = next((board for board in _routable_work_boards()
                         if board["board_id"] == board_id), None)
        if existing is not None:
            if str(existing.get("title") or "").casefold() == title.casefold():
                return existing
            raise HTTPException(
                status_code=409,
                detail=(f"new board title normalizes to existing board {board_id!r}; "
                        "choose that existing board explicitly or use a distinct name"),
            )
        create_board_module(BoardModuleIn(title=title, execution_scope="life"))
        return next(board for board in _routable_work_boards()
                    if board["board_id"] == board_id)
    if not body.board_id or not body.domain_id:
        raise HTTPException(status_code=400, detail="board_id and domain_id are required")
    board = next((candidate for candidate in _routable_work_boards()
                  if candidate["board_id"] == body.board_id
                  and candidate["domain_id"] == body.domain_id), None)
    if board is None:
        raise HTTPException(status_code=400, detail="target is not a validated active TODO board")
    return board


def _confirmed_assignment_fields(body: TodoAssignIn) -> dict[str, str]:
    """Require the human-confirmed canonical values; source text is never promoted."""
    if not body.confirm_canonical_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                "confirm canonical title, organized description, and kind "
                "before materializing this source"
            ),
        )
    title = (body.canonical_title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="canonical title is required")
    if body.canonical_description is None:
        raise HTTPException(
            status_code=400, detail="canonical organized description is required",
        )
    if body.canonical_kind is None:
        raise HTTPException(status_code=400, detail="canonical kind is required")
    return {
        "title": title,
        "description": body.canonical_description,
        "kind": body.canonical_kind,
    }


def _capture_route_preflight(
    capture_id: str, *, expected_work_item_ids: list[str] | None = None,
    conversation_id: str | None = None,
) -> Any:
    """Fail before Work Graph writes when a capture already owns another route."""
    capture_service = _get_capture_service()
    view = capture_service.get(capture_id)
    links = [
        event.payload
        for event in capture_service._store.events(capture_id)
        if event.kind == "link"
    ]
    if any(
        not isinstance(link, dict)
        or not isinstance(link.get("work_item_ids"), list)
        or not all(isinstance(value, str) for value in link["work_item_ids"])
        for link in links
    ):
        raise CaptureConversionConflict(
            "capture has malformed stored WorkItem link history"
        )
    if expected_work_item_ids is None:
        if view.processing_status == "routed" or links:
            raise CaptureConversionConflict(
                "capture already has routing history; no WorkItem was created"
            )
        return view
    expected = {
        "work_item_ids": list(expected_work_item_ids),
        "conversation_id": conversation_id,
    }
    conflicting = [link for link in links if link != expected]
    if conflicting:
        raise CaptureConversionConflict(
            "capture has a different WorkItem link in conflicting history"
        )
    exact = expected in links
    if view.processing_status == "routed" and not exact:
        raise CaptureConversionConflict(
            "capture is already routed with a different WorkItem link"
        )
    return view


def _unique_source_item(service, *, field: str, value: str, source: str):
    matches = [
        candidate for candidate in service.list_items()
        if getattr(candidate, field) == value
    ]
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"{source} maps to multiple canonical WorkItems; repair provenance first",
        )
    return matches[0] if matches else None


def _assignment_source_preflight(todo_id: str, body: TodoAssignIn) -> None:
    """Resolve source identity completely before a requested board can mutate config."""
    service = _require_workgraph_write()
    if todo_id.startswith("work:"):
        _wg_call(service.get_item, todo_id.removeprefix("work:"))
        return
    if todo_id.startswith("capture:"):
        capture_id = todo_id.removeprefix("capture:")
        existing = _unique_source_item(
            service, field="capture_id", value=capture_id,
            source=f"capture {capture_id}",
        )
        _capture_route_preflight(
            capture_id,
            expected_work_item_ids=(
                [existing.work_item_id] if existing is not None else None
            ),
            conversation_id=(existing.conversation_id if existing is not None else None),
        )
        if existing is None:
            _confirmed_assignment_fields(body)
        elif existing is not None:
            _require_exact_assignment_identity(existing, body)
        return
    if todo_id.startswith("card:"):
        raw = todo_id.removeprefix("card:")
        domain_id, separator, card_id = raw.partition(":")
        if not separator:
            raise HTTPException(status_code=400, detail="invalid board-card TODO id")
        spec = _domain_spec(domain_id)
        card = next((
            candidate for candidate in _domain_cards(spec)["cards"]
            if str(candidate.get("card_id")) == card_id
        ), None)
        if card is None:
            raise HTTPException(status_code=404, detail=f"card {card_id!r} not found")
        if card.get("projection_conflict_with"):
            raise HTTPException(
                status_code=409,
                detail="board projection provenance is conflicted; repair it first",
            )
        if card.get("projection_source") == "work_graph":
            work_item_id = card.get("work_item_id")
            if not isinstance(work_item_id, str) or not work_item_id:
                raise HTTPException(
                    status_code=409,
                    detail="board projection has no exact canonical WorkItem identity",
                )
            _wg_call(service.get_item, work_item_id)
            return
        packet_id = f"todo-source:{domain_id}:{card_id}"
        existing = _unique_source_item(
            service, field="packet_id", value=packet_id,
            source=f"board card {domain_id}:{card_id}",
        )
        already_on_source = (
            not body.new_board_title
            and body.domain_id == domain_id
            and body.board_id == str(spec.get("board_id"))
        )
        if existing is None and not already_on_source:
            _confirmed_assignment_fields(body)
        elif existing is not None:
            _require_exact_assignment_identity(existing, body)
        return
    raise HTTPException(status_code=404, detail=f"unknown TODO identity {todo_id!r}")


def _require_exact_assignment_identity(item, body: TodoAssignIn) -> None:
    fields = _confirmed_assignment_fields(body)
    stored = {
        "title": item.title,
        "description": item.description,
        "kind": item.kind,
    }
    divergent = sorted(key for key, value in fields.items() if stored[key] != value)
    if divergent:
        raise HTTPException(
            status_code=409,
            detail=(
                "canonical assignment retry differs from stored WorkItem fields: "
                + ", ".join(divergent)
            ),
        )


def _materialize_todo(todo_id: str, body: TodoAssignIn):
    service = _require_workgraph_write()
    if todo_id.startswith("work:"):
        return _wg_call(service.get_item, todo_id.removeprefix("work:")), None
    if todo_id.startswith("capture:"):
        capture_id = todo_id.removeprefix("capture:")
        capture = _get_capture_service().get(capture_id)
        item = _unique_source_item(
            service, field="capture_id", value=capture_id,
            source=f"capture {capture_id}",
        )
        if item is None:
            _capture_route_preflight(capture_id)
            fields = _confirmed_assignment_fields(body)
            item = _wg_call(
                service.create_item,
                fields.pop("title"), **fields, capture_id=capture_id,
                capture_batch_id=capture.record.batch_id,
                conversation_id=f"capture:{capture_id}",
            )
        else:
            _require_exact_assignment_identity(item, body)
            _capture_route_preflight(
                capture_id,
                expected_work_item_ids=[item.work_item_id],
                conversation_id=item.conversation_id,
            )
        return item, capture
    if todo_id.startswith("card:"):
        raw = todo_id.removeprefix("card:")
        domain_id, separator, card_id = raw.partition(":")
        if not separator:
            raise HTTPException(status_code=400, detail="invalid board-card TODO id")
        spec = _domain_spec(domain_id)
        card = next((candidate for candidate in _domain_cards(spec)["cards"]
                     if str(candidate.get("card_id")) == card_id), None)
        if card is None:
            raise HTTPException(status_code=404, detail=f"card {card_id!r} not found")
        if card.get("projection_conflict_with"):
            raise HTTPException(
                status_code=409,
                detail="board projection provenance is conflicted; repair it first",
            )
        if card.get("projection_source") == "work_graph":
            work_item_id = card.get("work_item_id")
            if not isinstance(work_item_id, str) or not work_item_id:
                raise HTTPException(
                    status_code=409,
                    detail="board projection has no exact canonical WorkItem identity",
                )
            return _wg_call(service.get_item, work_item_id), None
        packet_id = f"todo-source:{domain_id}:{card_id}"
        item = _unique_source_item(
            service, field="packet_id", value=packet_id,
            source=f"board card {domain_id}:{card_id}",
        )
        if item is None:
            fields = _confirmed_assignment_fields(body)
            item = _wg_call(
                service.create_item,
                fields.pop("title"), **fields, packet_id=packet_id,
            )
        else:
            _require_exact_assignment_identity(item, body)
        return item, None
    raise HTTPException(status_code=404, detail=f"unknown TODO identity {todo_id!r}")


@app.post("/api/todos/{todo_id:path}/assign")
def assign_todo(todo_id: str, body: TodoAssignIn) -> dict:
    with _todo_assignment_guard():
        # Validate the source/link authority before a requested new board can
        # write configuration. A rejected route or unconfirmed identity must
        # leave both the Work Graph and board registry untouched.
        _assignment_source_preflight(todo_id, body)
        board = _resolve_assignment_board(body)
        if todo_id.startswith("card:"):
            raw = todo_id.removeprefix("card:")
            source_domain, separator, source_card = raw.partition(":")
            if separator and source_domain == board["domain_id"]:
                spec = _domain_spec(source_domain)
                card = next((candidate for candidate in _domain_cards(spec)["cards"]
                             if str(candidate.get("card_id")) == source_card), None)
                if card is None:
                    raise HTTPException(status_code=404, detail="source card not found")
                return {"status": "already_assigned", "todo": _card_todo_row(spec, card),
                        "placement": None, "board": board}
        item, capture = _materialize_todo(todo_id, body)
        service = _require_workgraph_write()
        if (item.packet_id or "").startswith("todo-source:"):
            source_id = str(item.packet_id).removeprefix("todo-source:")
            source_domain, separator, _source_card = source_id.partition(":")
            if separator and source_domain == board["domain_id"]:
                return {"status": "already_assigned",
                        "todo": _work_todo_row(service, item),
                        "placement": None, "board": board}
        if capture is not None:
            _capture_route_preflight(
                capture.record.capture_id,
                expected_work_item_ids=[item.work_item_id],
                conversation_id=item.conversation_id,
            )
            _require_capture().mark_converted(
                capture.record.capture_id, [item.work_item_id],
                conversation_id=item.conversation_id,
            )
        placements = service._store.placements_for(item.work_item_id)
        existing = next((placement for placement in placements
                         if placement.board_id == board["board_id"]
                         and placement.domain_id == board["domain_id"]), None)
        placement = existing or _wg_call(
            service.add_placement, item.work_item_id,
            board["board_id"], board["domain_id"],
            is_primary=not placements, card_component="generic_task",
        )
        return {
            "status": "assigned" if existing is None else "already_assigned",
            "todo": _work_todo_row(service, service.get_item(item.work_item_id)),
            "placement": placement.model_dump(),
            "board": board,
        }


def _maintenance_log_path() -> Path:
    return Path(os.environ.get(
        "KANBAN_MAINTENANCE_LOG",
        str(KANBAN_EVENT_LOG.with_name("kanban-maintenance-events.jsonl")),
    ))


def _maintenance_scan() -> dict[str, Any]:
    from command_center.kanban_maintenance import analyze, reconcile_suggestions, review

    service = _require_workgraph()
    boards = [dict(domain) for domain in _domain_config().get("domains", [])]
    direct_card_counts: dict[str, int] = {}
    for board in boards:
        if (board.get("card_component") != "generic_task" or
                board.get("archived") or not board.get("board_id")):
            continue
        try:
            cards = _domain_cards(board)["cards"]
        except Exception as exc:  # noqa: BLE001 - partial cleanup advice is unsafe
            raise HTTPException(
                status_code=503,
                detail=f"maintenance scan requires complete board {board['domain_id']}: {exc}",
            ) from exc
        direct_card_counts[str(board["board_id"])] = sum(
            card.get("projection_source") != "work_graph" for card in cards)
    candidates = analyze(
        boards, service._store.list_placements(),
        direct_card_counts=direct_card_counts,
    )
    receipt = reconcile_suggestions(_maintenance_log_path(), candidates)
    return {**review(_maintenance_log_path()), "scan": receipt,
            "destructive_actions_performed": False}


@app.get("/api/kanban-maintenance")
def kanban_maintenance_review() -> dict:
    from command_center.kanban_maintenance import review

    return {**review(_maintenance_log_path()), "destructive_actions_performed": False}


@app.post("/api/kanban-maintenance/scan")
def scan_kanban_maintenance() -> dict:
    return _maintenance_scan()


@app.post("/api/kanban-maintenance/{suggestion_id}/decision")
def decide_kanban_maintenance(suggestion_id: str, body: MaintenanceDecisionIn) -> dict:
    from command_center.kanban_maintenance import (
        MaintenanceError, begin_decision, fulfill_accept,
    )

    path = _maintenance_log_path()
    try:
        _maintenance_scan()
        with _todo_assignment_guard():
            state = begin_decision(
                path, suggestion_id, body.decision, reason_note=body.reason_note)
            if body.decision == "reject":
                return {"status": "rejected", "suggestion": state,
                        "destructive_actions_performed": False}

            service = _require_workgraph_write()
            packet_id = f"maintenance:{suggestion_id}"
            item = next((candidate for candidate in service.list_items()
                         if candidate.packet_id == packet_id), None)
            if item is None:
                board_ids = ", ".join(state.get("board_ids") or [])
                description = "\n\n".join(filter(None, [
                    str(state.get("reason") or ""),
                    f"Boards: {board_ids}" if board_ids else "",
                    f"Evidence: {json.dumps(state.get('evidence') or {}, sort_keys=True)}",
                    "Human review only. Do not merge, archive, move, or delete automatically.",
                    body.reason_note or "",
                ]))
                item = _wg_call(
                    service.create_item,
                    str(state.get("title") or f"Review maintenance suggestion {suggestion_id}"),
                    description=description, kind="maintenance", packet_id=packet_id,
                )
            general_todos = next((
                board for board in _routable_work_boards()
                if board["title"] == "General Todos"
                or board["domain_id"] == "generic_task"
            ), None)
            if general_todos is None:
                raise HTTPException(
                    status_code=503,
                    detail="accepted maintenance reviews require the active General Todos board",
                )
            placements = service._store.placements_for(item.work_item_id)
            if not any(placement.board_id == general_todos["board_id"] and
                       placement.domain_id == general_todos["domain_id"]
                       for placement in placements):
                _wg_call(
                    service.add_placement, item.work_item_id,
                    general_todos["board_id"], general_todos["domain_id"],
                    is_primary=not placements, card_component="generic_task",
                )
            fulfilled = fulfill_accept(path, suggestion_id, item.work_item_id)
            return {"status": "accepted", "suggestion": fulfilled,
                    "todo": _work_todo_row(service, item),
                    "destructive_actions_performed": False}
    except MaintenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/work-graph/{work_item_id}")
def work_graph_neighbourhood(work_item_id: str, depth: int = 1) -> dict:
    svc = _require_workgraph()
    return _wg_call(svc.graph, work_item_id, depth=depth).model_dump()


@app.get("/api/work/{work_item_id}/resolve")
def resolve_work_permalink(work_item_id: str) -> dict:
    """Resolve a stable work-item permalink to its canonical landing target +
    the full navigation receipt. The backend owns the destination — a client
    reads target.href and follows it verbatim."""
    svc = _require_workgraph()
    return _wg_call(svc.resolve, work_item_id).model_dump()


@app.get("/work/{work_item_id}")
def open_work_permalink(work_item_id: str):
    """The human-facing permalink: GET /work/<id> 302-redirects into the SPA at
    the resolved canonical target, so a pasted /work/<id> link lands on the right
    board (or the Work Map). target.href is a '?...'-query the SPA understands, so
    '/' + href is the in-app deep link. Unknown id → 404 (via _wg_call)."""
    svc = _require_workgraph()
    resolution = _wg_call(svc.resolve, work_item_id)
    return RedirectResponse(url="/" + resolution.target.href, status_code=302)


# ── Chat creation: idea → connected work, with navigable receipts ─────────────
# Chat turns a STRUCTURED plan (items + placements + typed edges) into canonical
# work and returns a TaskBatchReceipt so the transcript stays navigable. preview
# is side-effect-free; commit validates the whole plan in a sandbox first, so an
# invalid plan (cycle, unknown ref) writes NOTHING. This is planning, not a
# mission — it starts no execution and touches no wall verb.
_chat_planner = None   # type: ignore[var-annotated]


def _get_chat_planner():
    global _chat_planner
    if _chat_planner is None:
        import secrets
        from datetime import datetime, timezone

        from command_center.work_graph import (
            ChatWorkPlanner,
            InMemoryWorkGraphStore,
            WorkGraphService,
        )

        def _sandbox() -> WorkGraphService:
            # provisional ids make preview receipts obviously not-yet-real
            return WorkGraphService(
                InMemoryWorkGraphStore(),
                clock=lambda: datetime.now(timezone.utc).isoformat(),
                id_factory=lambda prefix: f"prev-{prefix}-" + secrets.token_hex(4))

        _chat_planner = ChatWorkPlanner(_get_workgraph_service(),
                                        sandbox_factory=_sandbox)
    return _chat_planner


def _plan_call(fn, plan):
    """ChatPlanError (malformed plan) → 400, WorkGraphError (cycle/dup primary) →
    409, KeyError (edge references an unknown work item) → 404."""
    from command_center.work_graph import ChatPlanError, WorkGraphError
    try:
        return fn(plan)
    except ChatPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkGraphError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chat/work-items/preview")
def preview_chat_work(plan: WorkPlanIn) -> dict:
    """Dry-run a plan: return the receipt WITHOUT persisting anything (ids are
    provisional, the graph is unchanged)."""
    _require_workgraph()               # 503 if the graph is disabled
    return _plan_call(_get_chat_planner().preview, plan).model_dump()


@app.post("/api/chat/work-items/commit", status_code=201)
def commit_chat_work(plan: WorkPlanIn) -> dict:
    """Create the connected work and return a TaskBatchReceipt with clickable
    links for every item. Validated as a whole first, so a bad plan writes
    nothing."""
    _require_workgraph_write()
    _validate_routable_plan(plan)
    return _plan_call(_get_chat_planner().commit, plan).model_dump()


# ── Capture → work conversion: an intake idea becomes connected work ──────────
# A captured thought is turned into canonical work via the SAME planner (structured
# plan in, receipts out). The capture supplies provenance (capture_id →
# WorkItem.capture_id, its batch, its conversation); the caller supplies the
# structure until classification/routing (Phase G) infers it. preview persists
# nothing; convert commits the plan AND marks the capture 'routed' with a link
# event — the capture is never destroyed, only linked to the work it produced.
class CaptureConvertIn(BaseModel):
    items: list[WorkPlanItemIn]
    edges: list[WorkPlanEdgeIn] = Field(default_factory=list)
    conversation_id: str | None = None      # optional; else the capture's own


def _plan_from_capture(capture_view, body: CaptureConvertIn) -> WorkPlanIn:
    rec = capture_view.record
    return WorkPlanIn(
        conversation_id=(body.conversation_id or rec.conversation_id
                         or f"capture:{rec.capture_id}"),
        capture_id=rec.capture_id, capture_batch_id=rec.batch_id,
        items=body.items, edges=body.edges)


def _capture_for_conversion(capture_id: str):
    """Require both subsystems and fetch the capture (404 if unknown)."""
    _require_workgraph()
    try:
        return _require_capture().get(capture_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/captures/{capture_id}/work-preview")
def preview_capture_work(capture_id: str, body: CaptureConvertIn) -> dict:
    """Dry-run converting a capture into work: returns the receipt WITHOUT
    persisting anything and WITHOUT touching the capture."""
    view = _capture_for_conversion(capture_id)
    plan = _plan_from_capture(view, body)
    return _plan_call(_get_chat_planner().preview, plan).model_dump()


@app.post("/api/captures/{capture_id}/convert", status_code=201)
def convert_capture_to_work(capture_id: str, body: CaptureConvertIn) -> dict:
    # Assignment and conversion share one cross-process guard, so the
    # preflight/link decision cannot race another cockpit workflow.
    with _todo_assignment_guard():
        return _convert_capture_to_work_locked(capture_id, body)


def _convert_capture_to_work_locked(
    capture_id: str, body: CaptureConvertIn,
) -> dict:
    """Create the work the capture describes, then mark the capture 'routed' and
    link it to the created work items. Atomic on the work side (a bad plan writes
    nothing); the capture is only marked AFTER the work commits."""
    _require_workgraph_write()
    view = _capture_for_conversion(capture_id)
    plan = _plan_from_capture(view, body)
    if len(plan.items) != 1 or plan.edges:
        raise HTTPException(
            status_code=400,
            detail=(
                "capture conversion applies exactly one item with no edges; "
                "use bulk capture so every TODO has independent provenance"
            ),
        )
    _validate_routable_plan(plan)
    svc = _get_workgraph_service()
    existing = [
        item for item in svc.list_items() if item.capture_id == capture_id
    ]
    if len(existing) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"capture {capture_id!r} is linked to multiple work items; repair manually",
        )
    if existing:
        item = existing[0]
        requested = plan.items[0]
        requested_fields = {
            "title": requested.title,
            "description": requested.description,
            "kind": requested.kind,
            "owner": requested.owner,
            "priority": requested.priority,
            "due_at": requested.due_at,
        }
        mismatched = [
            field for field, value in requested_fields.items()
            if getattr(item, field) != value
        ]
        if mismatched:
            raise HTTPException(
                status_code=409,
                detail=(
                    "capture retry differs from its canonical WorkItem fields: "
                    + ", ".join(sorted(mismatched))
                ),
            )
        work_item_ids = [item.work_item_id]
        _capture_route_preflight(
            capture_id,
            expected_work_item_ids=work_item_ids,
            conversation_id=plan.conversation_id,
        )
        # Establish the exact provenance before placement repair. If a later
        # board write fails, the next identical retry finds this same item.
        _get_capture_service().mark_converted(
            capture_id, work_item_ids, conversation_id=plan.conversation_id,
        )
        primary = None
        if requested.primary_board is not None:
            ref = requested.primary_board
            primary = _wg_call(
                svc.add_placement, item.work_item_id, ref.board_id, ref.domain_id,
                is_primary=True, placement_stage=ref.placement_stage,
                card_component=ref.card_component,
            )
        secondaries = [
            _wg_call(
                svc.add_placement, item.work_item_id, ref.board_id, ref.domain_id,
                is_primary=False, placement_stage=ref.placement_stage,
                card_component=ref.card_component,
            )
            for ref in requested.secondary_boards
        ]
        return {
            "conversation_id": plan.conversation_id,
            "capture_id": capture_id,
            "capture_batch_id": plan.capture_batch_id,
            "preview": False,
            "created": [],
            "linked_existing": [{
                    "work_item": {
                        "work_item_id": item.work_item_id,
                        "title": item.title,
                        "kind": item.kind,
                        "canonical_status": item.canonical_status,
                        "primary_board_id": svc.get_item(
                            item.work_item_id).primary_board_id,
                    },
                    "primary_placement": (
                        primary.model_dump() if primary is not None else None),
                    "secondary_placements": [
                        placement.model_dump() for placement in secondaries],
                    "incoming_edges": [],
                    "outgoing_edges": [],
                    "links": [
                        link.model_dump() for link in svc.links_for(item.work_item_id)
                    ],
                    "warnings": [
                        "recovered an existing durable conversion for this capture"
                    ],
                }],
            "needs_confirmation": [],
            "board_suggestions": [],
            "warnings": ["capture link/status repaired without creating duplicate work"],
        }
    _capture_route_preflight(capture_id)
    receipt = _plan_call(_get_chat_planner().commit, plan)
    work_item_ids = [r.work_item.work_item_id for r in receipt.created]
    _get_capture_service().mark_converted(
        capture_id, work_item_ids, conversation_id=plan.conversation_id)
    return receipt.model_dump()


# ── Routing (Phase G): free text → a PROPOSED plan for a human to confirm ─────
# A deterministic first pass: split deliverables, tag evidence-backed board
# suggestions, flag exact-title duplicates and dependency-worded lines. It
# NEVER commits and NEVER silently auto-routes — every unresolved point is a
# needs_confirmation question. The human reviews/edits the proposal, then calls
# /convert or /commit. (Free-text board calibration is a later phase; with no
# injected board rules, every board is a question against the real domain list.)
class RouteTextIn(BaseModel):
    text: str
    conversation_id: str | None = None
    capture_id: str | None = None


def _board_domain_resolver(placements):
    """board_id -> domain_id, learned from REAL existing placements (the
    most-common domain seen for that board). Returns None for an unknown board so
    the calibrator never fabricates a domain."""
    from collections import Counter, defaultdict
    doms: dict[str, Counter] = defaultdict(Counter)
    for p in placements:
        doms[p.board_id][p.domain_id] += 1
    resolved = {
        board["board_id"]: board["domain_id"]
        for board in _routable_work_boards()
    }
    if not CHAT_ENABLED:
        for board_id, counts in doms.items():
            resolved.setdefault(board_id, counts.most_common(1)[0][0])
    return lambda board_id: resolved.get(board_id)


def _existing_work_contexts():
    """Compose everything the duplicate checker may see about existing work —
    bulk reads only (items, placements, captures each listed ONCE), so routing
    stays cheap with hundreds of cards. occurrence_count is filled lazily by
    the duplicate-check endpoints for their top findings, not here."""
    from command_center.work_graph import ExistingWorkContext
    svc = _get_workgraph_service()
    placements = svc._store.list_placements()
    boards_by_item: dict[str, list[str]] = {}
    for p in placements:
        if p.removed_at is None:
            boards_by_item.setdefault(p.work_item_id, []).append(p.board_id)
    raw_by_capture: dict[str, str] = {}
    try:
        for view in _require_capture().list():
            raw_by_capture[view.record.capture_id] = view.record.raw_content
    except HTTPException:
        pass                          # capture store off: titles still checked
    # parent project context: one bulk pass over active parent_of edges
    parent_by_child: dict[str, str] = {}
    for edge in svc._store.edges():
        if edge.relation == "parent_of" and edge.removed_at is None:
            parent_by_child[edge.to_work_item_id] = edge.from_work_item_id
    return [
        ExistingWorkContext(
            work_item_id=i.work_item_id, title=i.title,
            canonical_status=i.canonical_status,
            board_ids=boards_by_item.get(i.work_item_id, []),
            primary_board_id=i.primary_board_id,
            capture_raw=(raw_by_capture.get(i.capture_id)
                         if i.capture_id else None),
            description=i.description,
            last_activity_at=i.updated_at,
            completion_at=(i.updated_at
                           if i.canonical_status == "done" else None),
            kind=i.kind,
            parent_id=parent_by_child.get(i.work_item_id),
        )
        for i in svc.list_items()
    ]


def _build_work_router():
    from command_center.intake import split_bulk_list
    from command_center.work_graph import (
        DuplicateChecker, RoutingCalibrator, WorkRouter)
    svc = _get_workgraph_service()
    existing = [(i.work_item_id, i.title) for i in svc.list_items()]
    placements = svc._store.list_placements()
    # board-question options are a HINT sourced from boards that actually exist in
    # the graph (real, always-available) — not the domain config file, so routing
    # never depends on config plumbing. A fresh graph offers none (human types one).
    known = {board["board_id"] for board in _routable_work_boards()}
    if not CHAT_ENABLED:
        known.update(p.board_id for p in placements)
    # EVIDENCE-backed calibration: derive keyword->board rules from the human
    # correction log (past corrections only). The router then makes evidence-tagged
    # suggestions instead of always asking; every suggestion is still confirmed by
    # the human (proposal, not auto-routing), and overrides feed back as telemetry.
    # min_support stays at its committed default (1): a single REAL human
    # correction may already ground a suggestion the human then confirms.
    # The junk-suggestion incident ("matched 'g','e','if'") was punctuation
    # shrapnel + function words in keyword DERIVATION — fixed at the source
    # by the calibrator's token-quality filter, not by demanding more data.
    rules = RoutingCalibrator(_get_telemetry_service().list()).board_rules(
        _board_domain_resolver(placements))
    return WorkRouter(split=split_bulk_list, board_rules=rules,
                      known_boards=sorted(known), existing_titles=existing,
                      duplicate_checker=DuplicateChecker(
                          _existing_work_contexts()))


@app.post("/api/work-items/route")
def route_work_text(body: RouteTextIn) -> dict:
    """Propose a structured plan from free text — side-effect-free; commits
    nothing. Feed the (human-edited) plan to /api/chat/work-items/commit."""
    _require_workgraph()
    proposal = _build_work_router().route(
        body.text, conversation_id=body.conversation_id,
        capture_id=body.capture_id).model_dump()
    proposal["routable_boards"] = _routable_work_boards()
    return proposal


@app.post("/api/captures/{capture_id}/route")
def route_capture_text(capture_id: str) -> dict:
    """Propose a plan from a capture's raw content, carrying its provenance. The
    capture is untouched (routing is not conversion — /convert commits)."""
    view = _capture_for_conversion(capture_id)     # 503/404 as appropriate
    rec = view.record
    proposal = _build_work_router().route(
        rec.raw_content,
        conversation_id=(rec.conversation_id or f"capture:{rec.capture_id}"),
        capture_id=rec.capture_id).model_dump()
    proposal["routable_boards"] = _routable_work_boards()
    return proposal


# ── duplicate checking + resolution: evidence-tagged, side-effect-free checks;
# every RESOLUTION is an explicit human choice recorded as append-only ground
# truth on the canonical item. Nothing here merges or deletes silently.

class DuplicateCheckIn(BaseModel):
    text: str


class OccurrenceIn(BaseModel):
    note: str | None = None
    quantity: int | None = None
    unit: str | None = None
    source_capture_id: str | None = None


class ResolveDuplicateIn(BaseModel):
    existing_work_item_id: str
    resolution: str
    note: str | None = None
    quantity: int | None = None
    unit: str | None = None
    match_class: str | None = None
    evidence_kinds: list[str] = Field(default_factory=list)
    # expand_existing: which recomputed deltas to apply (empty = none)
    selected_delta_ids: list[str] = Field(default_factory=list)
    # group_under_existing / create_project_group / add_child placement
    board_id: str | None = None
    domain_id: str | None = None
    # create_project_group inputs
    group_title: str | None = None
    member_work_item_ids: list[str] = Field(default_factory=list)
    capture_as_parent: bool = False
    canonical_title: str | None = None
    canonical_description: str | None = None
    canonical_kind: str | None = None
    confirm_canonical_fields: bool = False
    canonical_project_title: str | None = None
    canonical_project_description: str | None = None
    canonical_project_kind: str | None = None
    confirm_canonical_project: bool = False
    canonical_children: dict[str, dict[str, str]] = Field(default_factory=dict)


class CaptureArchiveIn(BaseModel):
    reason: str


def _duplicate_report(text: str) -> dict:
    """Side-effect-free evidence report; top findings enriched with the real
    occurrence badge (bounded: at most MAX_FINDINGS event lookups)."""
    from command_center.work_graph import DuplicateChecker
    _require_workgraph()
    checker = DuplicateChecker(_existing_work_contexts())
    report = checker.check(text)
    svc = _get_workgraph_service()
    enriched = []
    for finding in report.findings:
        data = finding.model_dump()
        data["occurrence_count"] = svc.occurrence_count(
            finding.existing_work_item_id)
        enriched.append(data)
    out = report.model_dump()
    out["findings"] = enriched
    return out


@app.post("/api/captures/{capture_id}/duplicate-check")
def capture_duplicate_check(capture_id: str) -> dict:
    """Check ONE capture against all existing canonical work. GET-equivalent
    semantics: the capture and the graph are untouched."""
    view = _capture_for_conversion(capture_id)
    return _duplicate_report(view.record.raw_content)


@app.post("/api/captures/{capture_id}/matches")
def capture_matches(capture_id: str) -> dict:
    """Match & Organize report: per-candidate findings (same work / progress /
    expansion / subtask / parent / same subject) PLUS report-level project
    grouping and board-fit suggestions. Side-effect-free."""
    return capture_duplicate_check(capture_id)


@app.post("/api/work-items/matches")
def work_text_matches(body: DuplicateCheckIn) -> dict:
    """Match & Organize report for free text, before anything is created."""
    return work_text_duplicate_check(body)


@app.post("/api/work-items/duplicate-check")
def work_text_duplicate_check(body: DuplicateCheckIn) -> dict:
    """Check free text (a proposed todo) before anything is created."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    return _duplicate_report(text)


@app.post("/api/work-items/{work_item_id}/occurrences", status_code=201)
def add_work_occurrence(work_item_id: str, body: OccurrenceIn) -> dict:
    """Append repeated progress ('applied to jobs again') to the ONE canonical
    item — never a second task."""
    svc = _require_workgraph_write()
    event = _wg_call(svc.add_occurrence, work_item_id, note=body.note,
                     quantity=body.quantity, unit=body.unit,
                     source_capture_id=body.source_capture_id)
    return {"event": event.model_dump(),
            "occurrence_count": svc.occurrence_count(work_item_id)}


@app.get("/api/work-items/{work_item_id}/occurrences")
def list_work_occurrences(work_item_id: str) -> dict:
    svc = _require_workgraph()
    events = _wg_call(svc.occurrences, work_item_id)
    return {"occurrences": [e.model_dump() for e in events],
            "occurrence_count": len(events)}


@app.get("/api/work-items/{work_item_id}/duplicate-decisions")
def list_duplicate_decisions(work_item_id: str) -> dict:
    svc = _require_workgraph()
    events = _wg_call(svc.duplicate_decisions, work_item_id)
    return {"decisions": [e.model_dump() for e in events]}


@app.post("/api/captures/{capture_id}/archive")
def archive_capture(capture_id: str, body: CaptureArchiveIn) -> dict:
    """Safe discard: hides the capture from active Inbox lanes; the immutable
    raw record + history stay recoverable. Routed captures are refused."""
    _require_workgraph_write()          # discarding intake is a governed write
    svc = _require_capture()
    try:
        return svc.archive(capture_id, reason=body.reason).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/captures/{capture_id}/resolve-duplicate")
def resolve_capture_duplicate(capture_id: str, body: ResolveDuplicateIn) -> dict:
    with _todo_assignment_guard():
        return _resolve_capture_duplicate_locked(capture_id, body)


def _resolve_capture_duplicate_locked(
    capture_id: str, body: ResolveDuplicateIn,
) -> dict:
    """Resolve a duplicate candidate for a capture the way the HUMAN chose.
    Records the decision (append-only) and performs exactly the chosen action:

      reuse_existing        — link the capture to the existing item; no new work
      add_occurrence        — append a progress event to the existing item + link
      reopen_existing       — set the existing item back to 'ready' + link
      discard_capture       — archive the capture (history preserved)
      expand_existing       — append the SELECTED deltas (recomputed
                              deterministically server-side); subtask-target
                              deltas become child items with parent_of edges
      add_child             — the whole capture becomes ONE child of existing
      group_under_existing  — new item created under existing as its project
      create_project_group  — new project item + parent_of edges to members
      create_separate       — RECORD-ONLY: the create itself flows through /convert
      link_related          — RECORD-ONLY: the edge itself flows through /convert

    so every match decision lands in ONE append-only log."""
    from command_center.work_graph import extract_deltas
    from command_center.work_graph.schemas import WORK_ITEM_KINDS
    wg = _require_workgraph_write()
    intake = _require_capture()
    view = _capture_for_conversion(capture_id)
    if view.processing_status == "archived":
        archive_reasons = [
            event.payload.get("reason")
            for event in intake._store.events(capture_id)
            if event.kind == "archived"
        ]
        if not (
            body.resolution == "discard_capture"
            and len(archive_reasons) == 1
            and archive_reasons[0] == (body.note or "").strip()
        ):
            raise HTTPException(
                status_code=409,
                detail=f"capture {capture_id} is archived with different history",
            )
    raw = view.record.raw_content
    resolution = body.resolution
    allowed = {"reuse_existing", "add_occurrence", "reopen_existing",
               "discard_capture", "create_separate", "link_related",
               "expand_existing", "add_child", "group_under_existing",
               "create_project_group", "archive_existing"}
    if resolution not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"resolution must be one of {sorted(allowed)}")
    # calibration telemetry records the SERVER's classification of this pair,
    # never a client-supplied claim — a stale or forged request cannot poison
    # the append-only decision log
    from command_center.work_graph import DuplicateChecker
    server_report = DuplicateChecker(_existing_work_contexts()).check(raw)
    server_finding = next(
        (f for f in server_report.findings
         if f.existing_work_item_id == body.existing_work_item_id), None)
    server_class = server_finding.match_class if server_finding else None
    server_evidence = ([e.kind for e in server_finding.evidence]
                       if server_finding else None)
    existing = _wg_call(wg.get_item, body.existing_work_item_id)

    def _board_ref_for(work_item_id: str) -> tuple[str, str]:
        """Placement target: explicit body board, else the item's primary,
        else its first active placement. 409 when nothing fits."""
        if body.board_id and body.domain_id:
            if not any(
                board["board_id"] == body.board_id
                and board["domain_id"] == body.domain_id
                for board in _routable_work_boards()
            ):
                raise HTTPException(
                    status_code=400,
                    detail="explicit child placement is not a validated active TODO board",
                )
            return body.board_id, body.domain_id
        placements = [p for p in wg._store.placements_for(work_item_id)
                      if p.removed_at is None]
        chosen = next((p for p in placements if p.is_primary),
                      placements[0] if placements else None)
        if chosen is None:
            raise HTTPException(
                status_code=409,
                detail="no placement to inherit — pass board_id + domain_id")
        return chosen.board_id, chosen.domain_id

    def _canonical_fields(*, project: bool = False) -> dict[str, str]:
        confirmed = (
            body.confirm_canonical_project if project else body.confirm_canonical_fields
        )
        title = body.canonical_project_title if project else body.canonical_title
        description = (
            body.canonical_project_description if project else body.canonical_description
        )
        kind = body.canonical_project_kind if project else body.canonical_kind
        if not confirmed:
            raise HTTPException(
                status_code=400,
                detail=("confirm canonical project fields" if project else
                        "confirm canonical child fields"),
            )
        title = (title or "").strip()
        if not title or description is None or kind is None:
            raise HTTPException(
                status_code=400,
                detail="canonical title, organized description, and kind are required",
            )
        if kind not in WORK_ITEM_KINDS:
            raise HTTPException(
                status_code=400,
                detail=f"canonical kind must be one of {list(WORK_ITEM_KINDS)}",
            )
        return {"title": title, "description": description, "kind": kind}

    def _ensure_parent_edge(parent_id: str, child_id: str) -> None:
        if any(
            edge.from_work_item_id == parent_id
            and edge.to_work_item_id == child_id
            and edge.relation == "parent_of"
            for edge in wg._store.edges()
        ):
            return
        _wg_call(wg.add_edge, parent_id, child_id, "parent_of")

    def _create_under(
        parent_id: str, fields: dict[str, str], work_item_id: str,
    ):
        board_id, domain_id = _board_ref_for(parent_id)
        item = _wg_call(
            wg.create_item, fields["title"], work_item_id=work_item_id,
            description=fields["description"], kind=fields["kind"],
            capture_id=capture_id, conversation_id=f"capture:{capture_id}",
        )
        _wg_call(wg.add_placement, item.work_item_id, board_id, domain_id,
                 is_primary=True, card_component="generic_task")
        _ensure_parent_edge(parent_id, item.work_item_id)
        return item

    # Validate the entire operation before recording intent. No missing child,
    # project, board, member, delta, or kind can fail after the capture is routed.
    selected: list[Any] = []
    child_specs: list[tuple[Any, dict[str, str]]] = []
    child_fields: dict[str, str] | None = None
    project_fields: dict[str, str] | None = None
    members: list[str] = []
    project_board: tuple[str, str] | None = None
    if resolution in {"add_child", "group_under_existing"}:
        child_fields = _canonical_fields()
        _board_ref_for(existing.work_item_id)
    elif resolution == "expand_existing":
        deltas = extract_deltas(raw, existing.title, existing.description)
        selected_ids = set(body.selected_delta_ids)
        selected = [delta for delta in deltas if delta.delta_id in selected_ids]
        resolved_ids = {delta.delta_id for delta in selected}
        if not selected or resolved_ids != selected_ids:
            raise HTTPException(
                status_code=422,
                detail="expand_existing selected_delta_ids must all resolve exactly",
            )
        for delta in selected:
            if delta.proposed_target != "child":
                continue
            fields = body.canonical_children.get(delta.delta_id)
            if not isinstance(fields, dict) or not all(
                isinstance(fields.get(field), str)
                for field in ("title", "description", "kind")
            ) or not fields["title"].strip():
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "each selected child delta requires confirmed canonical "
                        f"title/description/kind: {delta.delta_id}"
                    ),
                )
            if fields["kind"] not in WORK_ITEM_KINDS:
                raise HTTPException(
                    status_code=400,
                    detail=f"canonical child kind must be one of {list(WORK_ITEM_KINDS)}",
                )
            child_specs.append((delta, fields))
        if child_specs:
            _board_ref_for(existing.work_item_id)
    elif resolution == "create_project_group":
        members = list(dict.fromkeys(
            [*body.member_work_item_ids, existing.work_item_id]
        ))
        for member_id in members:
            _wg_call(wg.get_item, member_id)
        project_fields = _canonical_fields(project=True)
        if (
            body.group_title is not None
            and body.group_title.strip() != project_fields["title"]
        ):
            raise HTTPException(
                status_code=409,
                detail="group_title differs from confirmed canonical project title",
            )
        if not body.capture_as_parent:
            child_fields = _canonical_fields()
        project_board = _board_ref_for(members[0])
    elif resolution == "discard_capture" and not (body.note or "").strip():
        raise HTTPException(
            status_code=400, detail="discard_capture requires a reason note",
        )

    routes_capture = resolution in {
        "reuse_existing", "add_occurrence", "reopen_existing",
        "expand_existing", "add_child", "group_under_existing",
        "create_project_group",
    }
    if view.processing_status == "routed" and not routes_capture:
        raise HTTPException(
            status_code=409,
            detail="capture is already routed with another resolution intent",
        )
    planned_ids: list[str] = []
    operation_key: str | None = None
    if routes_capture:
        intent_body = body.model_dump(
            mode="json", exclude={"match_class", "evidence_kinds"},
        )
        intent_digest = hashlib.sha256(json.dumps(
            intent_body, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        operation_key = (
            f"duplicate-resolution:{resolution}:{existing.work_item_id}:"
            f"{intent_digest}"
        )
        links: list[dict[str, Any]] = []
        for event in intake._store.events(capture_id):
            if event.kind != "link":
                continue
            link = event.payload
            if (
                not isinstance(link, dict)
                or not isinstance(link.get("work_item_ids"), list)
                or not all(isinstance(value, str) for value in link["work_item_ids"])
                or not isinstance(link.get("conversation_id"), str)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="capture has malformed stored resolution intent",
                )
            links.append(link)
        exact_links = [
            link for link in links
            if link.get("operation_key") == operation_key
        ]
        if links and (len(links) != 1 or len(exact_links) != 1):
            raise HTTPException(
                status_code=409,
                detail="capture resolution retry differs from stored intent",
            )
        if exact_links:
            planned_ids = list(exact_links[0]["work_item_ids"])
        elif resolution in {"reuse_existing", "add_occurrence", "reopen_existing"}:
            planned_ids = [existing.work_item_id]
        elif resolution in {"add_child", "group_under_existing"}:
            planned_ids = [wg.reserve_work_item_id()]
        elif resolution == "expand_existing":
            planned_ids = [
                existing.work_item_id,
                *[wg.reserve_work_item_id() for _delta, _fields in child_specs],
            ]
        elif resolution == "create_project_group":
            planned_ids = [wg.reserve_work_item_id()]
            if not body.capture_as_parent:
                planned_ids.append(wg.reserve_work_item_id())
        expected_count = {
            "reuse_existing": 1,
            "add_occurrence": 1,
            "reopen_existing": 1,
            "add_child": 1,
            "group_under_existing": 1,
            "expand_existing": 1 + len(child_specs),
            "create_project_group": 1 + int(not body.capture_as_parent),
        }[resolution]
        if len(planned_ids) != expected_count or (
            resolution in {
                "reuse_existing", "add_occurrence", "reopen_existing",
                "expand_existing",
            }
            and planned_ids[0] != existing.work_item_id
        ):
            raise HTTPException(
                status_code=409,
                detail="stored capture resolution intent has invalid WorkItem identities",
            )
        try:
            intake.mark_converted(
                capture_id, planned_ids,
                conversation_id=(
                    view.record.conversation_id or f"capture:{capture_id}"
                ),
                operation_key=operation_key,
            )
        except CaptureConversionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    result: dict = {}
    if resolution == "reuse_existing":
        result["linked_work_item_id"] = existing.work_item_id
    elif resolution == "add_occurrence":
        event = _wg_call(wg.add_occurrence, existing.work_item_id,
                         note=body.note, quantity=body.quantity,
                         unit=body.unit, source_capture_id=capture_id)
        result["occurrence"] = event.model_dump()
        result["occurrence_count"] = wg.occurrence_count(
            existing.work_item_id)
    elif resolution == "reopen_existing":
        item = _wg_call(wg.set_status, existing.work_item_id, "ready")
        result["canonical_status"] = item.canonical_status
    elif resolution == "discard_capture":
        try:
            intake.archive(capture_id,
                           reason=body.note)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        result["capture_status"] = "archived"
    elif resolution == "expand_existing":
        children = [
            _create_under(existing.work_item_id, fields, work_item_id)
            for (_delta, fields), work_item_id in zip(
                child_specs, planned_ids[1:], strict=True,
            )
        ]
        event = _wg_call(
            wg.record_expansion, existing.work_item_id,
            deltas=[d.model_dump() for d in selected],
            source_capture_id=capture_id)
        result["expansion"] = event.model_dump()
        result["created_children"] = [c.work_item_id for c in children]
        result["applied_delta_ids"] = [d.delta_id for d in selected]
    elif resolution == "add_child":
        assert child_fields is not None
        child = _create_under(existing.work_item_id, child_fields, planned_ids[0])
        result["created_work_item_id"] = child.work_item_id
        result["parent_work_item_id"] = existing.work_item_id
    elif resolution == "group_under_existing":
        # existing_work_item_id IS the parent/project to group under
        assert child_fields is not None
        child = _create_under(existing.work_item_id, child_fields, planned_ids[0])
        result["created_work_item_id"] = child.work_item_id
        result["parent_work_item_id"] = existing.work_item_id
    elif resolution == "create_project_group":
        assert project_fields is not None and project_board is not None
        board_id, domain_id = project_board
        project = _wg_call(
            wg.create_item, project_fields["title"],
            work_item_id=planned_ids[0],
            description=project_fields["description"], kind=project_fields["kind"],
            capture_id=(capture_id if body.capture_as_parent else None),
            conversation_id=f"capture:{capture_id}")
        _wg_call(wg.add_placement, project.work_item_id, board_id, domain_id,
                 is_primary=True, card_component="generic_task")
        for member_id in members:
            _ensure_parent_edge(project.work_item_id, member_id)
        created = [project.work_item_id]
        if not body.capture_as_parent:
            assert child_fields is not None
            child = _create_under(
                project.work_item_id, child_fields, planned_ids[1],
            )
            created.append(child.work_item_id)
        result["project_work_item_id"] = project.work_item_id
        result["member_work_item_ids"] = members
        result["created_work_item_ids"] = created
    elif resolution == "archive_existing":
        # archive the EXISTING todo (history preserved; archived items stop
        # projecting onto boards). The capture stays unresolved so the human
        # can still route it normally afterwards.
        item = _wg_call(wg.set_status, existing.work_item_id, "archived")
        result["canonical_status"] = item.canonical_status
    decision = _wg_call(
        wg.record_duplicate_decision, existing.work_item_id,
        resolution=resolution, capture_id=capture_id,
        match_class=server_class,
        evidence_kinds=server_evidence, note=body.note)
    result["decision"] = decision.model_dump()
    result["resolution"] = resolution
    return result


# ── router-correction telemetry: the durable EVIDENCE for later calibration ──
# When a human accepts / changes / declines the board the router proposed, that
# decision is recorded as ground truth. Nothing is derived from it here; it is
# the log a future evidence-backed calibration phase learns from. Durable under
# KANBAN_UI_WORKGRAPH_LEDGER (same ledger.db); recording is planning, not a
# mission — no wall verb.
_telemetry_service = None   # type: ignore[var-annotated]


def _get_telemetry_service():
    global _telemetry_service
    if _telemetry_service is None:
        import secrets
        from datetime import datetime, timezone

        from command_center.work_graph import (
            InMemoryRoutingTelemetryStore,
            LedgerRoutingTelemetryStore,
            RoutingTelemetryService,
        )
        if WORKGRAPH_LEDGER:
            store = LedgerRoutingTelemetryStore(
                httpx.Client(base_url=LEDGER_BASE_URL, timeout=30))
        else:
            store = InMemoryRoutingTelemetryStore()
        _telemetry_service = RoutingTelemetryService(
            store,
            clock=lambda: datetime.now(timezone.utc).isoformat(),
            id_factory=lambda: "rc-" + secrets.token_hex(6))
    return _telemetry_service


class RoutingCorrectionIn(BaseModel):
    title: str
    ref: str | None = None
    suggested_board_id: str | None = None
    chosen_board_id: str | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    capture_id: str | None = None
    source: str = "chat"


@app.post("/api/routing-corrections", status_code=201)
def record_routing_correction(body: RoutingCorrectionIn) -> dict:
    """Record a human's routing decision as durable evidence (accept / change /
    decline a suggested board). Derives no rules — just logs the ground truth."""
    _require_workgraph()
    try:
        return _get_telemetry_service().record(
            body.title, ref=body.ref, suggested_board_id=body.suggested_board_id,
            chosen_board_id=body.chosen_board_id,
            matched_keywords=body.matched_keywords,
            conversation_id=body.conversation_id, capture_id=body.capture_id,
            source=body.source).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/routing-corrections")
def list_routing_corrections(since: str | None = None, board: str | None = None,
                             limit: int | None = None) -> dict:
    """The evidence log (honouring since/board/limit) + a read-only summary. The
    summary is computed over the WHOLE log regardless of the filters (it is the
    global evidence surface: totals, acceptance rate, chosen-board tallies), NOT a
    rule set."""
    _require_workgraph()               # 503 if the work graph is disabled
    svc = _get_telemetry_service()
    return {"corrections": [c.model_dump()
                            for c in svc.list(since=since, board=board, limit=limit)],
            "summary": svc.summary()}


@app.get("/api/routing-rules")
def routing_rules() -> dict:
    """What the router has LEARNED from the correction log: `derived` = every
    keyword->board association with its support + full per-board distribution
    (the evidence), `applied` = the BoardRules currently fed to the router (one
    per board, domain resolved from real placements). Read-only; past
    corrections only; derives no rule without evidence and invents no domain."""
    _require_workgraph()
    from command_center.work_graph import RoutingCalibrator
    svc = _get_workgraph_service()
    placements = svc._store.list_placements()
    calib = RoutingCalibrator(_get_telemetry_service().list())
    derived = calib.derive()                       # derive once, reuse below
    applied = calib.board_rules(_board_domain_resolver(placements), rules=derived)
    return {"derived": [r.model_dump() for r in derived],
            "applied": [r.model_dump() for r in applied]}


@app.post("/api/work-items/plan-summary")
def work_plan_summary(plan: WorkPlanIn) -> dict:
    """The confirmation gate: 'this will create N items / M placements / K edges'
    for a proposed plan. Deterministic and side-effect-free — commits nothing;
    the human reads it before choosing Create / Edit / Keep as note."""
    from command_center.work_graph import summarize_plan
    _require_workgraph()
    return summarize_plan(plan).model_dump()


# ── Readiness Packet (Phase H, slice 1): review a unit of work before creating it
# A packet gathers the Work Graph Plan + runbook + research + acceptance criteria
# + per-role review slots, and a readiness gate that commit must pass. Assembling
# and committing a packet is PLANNING (creates work items, no wall verb); the
# independent Claude/Codex review orchestration that FILLS the review slots is a
# later, separately-reviewed slice — here slots start pending / are set by a human.
_packet_service = None   # type: ignore[var-annotated]


def _get_packet_service():
    global _packet_service
    if _packet_service is None:
        import secrets
        from datetime import datetime, timezone

        from command_center.work_graph import InMemoryPacketStore, PacketService
        if PACKET_LEDGER:
            from command_center.work_graph import LedgerPacketStore
            store = LedgerPacketStore(
                httpx.Client(base_url=LEDGER_BASE_URL, timeout=30))
        else:
            store = InMemoryPacketStore()
        _packet_service = PacketService(
            store,
            clock=lambda: datetime.now(timezone.utc).isoformat(),
            id_factory=lambda: "pkt-" + secrets.token_hex(5))
    return _packet_service


def _work_items_for_packet(packet_id: str) -> list[str]:
    """The commit reconcile hook: work-item ids already created for this packet
    (they carry packet_id). Lets a re-commit after a partial failure REUSE the
    existing graph instead of creating a duplicate."""
    svc = _get_workgraph_service()
    return [it.work_item_id for it in svc.list_items()
            if getattr(it, "packet_id", None) == packet_id]


def _packet_call(fn, *args, **kwargs):
    """PacketNotReady -> 409, PacketError (malformed) -> 400, work-graph cycle ->
    409, unknown ref -> 404."""
    from command_center.work_graph import (
        ChatPlanError, PacketError, PacketNotReady, PacketRevisionConflict,
        WorkGraphError,
    )
    try:
        return fn(*args, **kwargs)
    except (PacketNotReady, PacketRevisionConflict) as exc:  # not-ready / stale -> 409
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (PacketError, ChatPlanError) as exc:   # malformed plan/packet -> 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkGraphError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class PacketAssembleIn(BaseModel):
    plan: WorkPlanIn
    title: str | None = None
    research: str = ""
    runbook: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    review_roles: list[str] = Field(default_factory=list)
    capture_id: str | None = None
    conversation_id: str | None = None


class ReviewOutcomeIn(BaseModel):
    status: str                        # reviewed | approved | changes_requested | error | pending
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    session_id: str | None = None      # the agent-session/judge run, when present
    reviewer_kind: str = "human"       # agent (advisory) | human (may approve)
    expected_revision: int | None = None   # 409 if the packet changed under you


class PacketReviseIn(BaseModel):
    """Edit a packet's plan-content, minting a new immutable revision. Reviews are
    not content, so they survive; but readiness is re-evaluated against the new
    revision (a review bound to the old revision no longer counts)."""
    expected_revision: int | None = None
    title: str | None = None
    research: str | None = None
    runbook: list[str] | None = None
    acceptance_criteria: list[str] | None = None


@app.post("/api/packets", status_code=201)
def assemble_packet(body: PacketAssembleIn) -> dict:
    """Assemble a readiness packet from a plan (side-effect-free beyond storing the
    packet — creates NO work items). Review slots open as pending."""
    _require_workgraph()
    return _packet_call(
        _get_packet_service().assemble, body.plan, title=body.title,
        capture_id=body.capture_id, conversation_id=body.conversation_id,
        research=body.research, runbook=body.runbook,
        acceptance_criteria=body.acceptance_criteria,
        review_roles=body.review_roles).model_dump()


@app.get("/api/packets")
def list_packets(status: str | None = None) -> list:
    _require_workgraph()
    return [p.model_dump() for p in _get_packet_service().list(status=status)]


@app.get("/api/packets/{packet_id}")
def get_packet(packet_id: str) -> dict:
    _require_workgraph()
    return _packet_call(_get_packet_service().get, packet_id).model_dump()


@app.get("/api/packets/{packet_id}/revisions")
def list_packet_revisions_api(packet_id: str) -> list:
    """The immutable revision history: one entry per plan-content edit, each with
    the content_digest a review binds to."""
    _require_workgraph()
    return [r.model_dump()
            for r in _packet_call(_get_packet_service().revisions, packet_id)]


@app.post("/api/packets/{packet_id}/revise")
def revise_packet(packet_id: str, body: PacketReviseIn) -> dict:
    """Edit plan-content → new immutable revision. Refused (409) if committed
    (frozen) or if expected_revision is stale."""
    _require_workgraph()
    return _packet_call(
        _get_packet_service().revise, packet_id,
        expected_revision=body.expected_revision, title=body.title,
        research=body.research, runbook=body.runbook,
        acceptance_criteria=body.acceptance_criteria).model_dump()


@app.get("/api/packets/{packet_id}/readiness")
def packet_readiness(packet_id: str) -> dict:
    """The deterministic readiness gate: the checks + whether the packet may be
    committed (no error-level check failing)."""
    _require_workgraph()
    svc = _get_packet_service()
    packet = _packet_call(svc.get, packet_id)
    return {"ready": svc.is_ready(packet),          # the canonical gate predicate
            "checks": [c.model_dump() for c in svc.readiness(packet_id)]}


@app.post("/api/packets/{packet_id}/reviews/{role}")
def set_packet_review(packet_id: str, role: str, body: ReviewOutcomeIn) -> dict:
    """Set a review slot's outcome. An AGENT review (reviewer_kind='agent') is
    advisory and can never be 'approved' — only a human approval satisfies the
    readiness gate, so an agent can never unlock commit by reviewing its own
    work (plan §6)."""
    _require_workgraph()
    return _packet_call(
        _get_packet_service().set_review, packet_id, role, status=body.status,
        summary=body.summary, findings=body.findings, session_id=body.session_id,
        reviewer_kind=body.reviewer_kind,
        expected_revision=body.expected_revision).model_dump()


@app.post("/api/packets/{packet_id}/request-reviews")
def request_packet_reviews(packet_id: str) -> dict:
    """Phase 6 review ORCHESTRATION: run an ADVISORY agent review into each of
    the packet's reviewer slots + a judge synthesis. Every recorded review is
    reviewer_kind='agent' and never 'approved', so this can NEVER unlock commit —
    a human approval is still required (plan §6). Uses the deterministic
    structural reviewer by default (no quota); the real Claude/Codex reviewer is
    the injectable production seam. Returns the report + the (still-gated) ready
    state."""
    _require_workgraph()
    from command_center.work_graph.packet import PacketError
    from command_center.work_graph.packet_review import orchestrate_reviews
    svc = _get_packet_service()
    packet = _packet_call(svc.get, packet_id)
    roles = [s.role for s in packet.reviews if s.role != "judge"]

    def record(**kw: Any) -> None:
        svc.set_review(packet_id, kw["role"], status=kw["status"],
                       summary=kw["summary"], findings=kw["findings"],
                       reviewer_kind=kw["reviewer_kind"])
    try:
        report = orchestrate_reviews(
            packet=packet, review_roles=roles, record=record)
    except PacketError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "report": {"reviews": report.reviews, "synthesis": report.synthesis,
                   "unlocked_commit": report.unlocked_commit},
        "ready": svc.is_ready(svc.get(packet_id)),
    }


@app.post("/api/packets/{packet_id}/commit", status_code=201)
def commit_packet(packet_id: str, expected_revision: int | None = None) -> dict:
    """Create the work graph the packet describes — refused (409) unless the
    packet is ready (or if expected_revision is stale). Every created item links
    back via WorkItem.packet_id; a re-commit reuses an already-created graph."""
    _require_workgraph()
    return _packet_call(
        _get_packet_service().commit, packet_id, _get_chat_planner(),
        expected_revision=expected_revision,
        work_items_for_packet=_work_items_for_packet).model_dump()


def _read_leaderboard_evidence() -> list:
    """Read the durable append-only evidence log into EvidenceSamples. A
    malformed line is skipped, never fatal — the leaderboard degrades to
    'insufficient evidence', it never fabricates."""
    from command_center.ranking import EvidenceSample
    samples = []
    if not LEADERBOARD_EVIDENCE.is_file():
        return samples
    for line in LEADERBOARD_EVIDENCE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            samples.append(EvidenceSample(
                executor=str(d["executor"]), dimension_id=str(d["dimension_id"]),
                value=float(d["value"]), sample_size=int(d.get("sample_size", 1)),
                source=str(d.get("source", "evidence-log"))))
        except (ValueError, KeyError, TypeError):
            continue
    return samples


@app.get("/api/leaderboard")
def executor_leaderboard() -> dict:
    """Phase 8 executor-ranking leaderboard: each dimension ranked INDEPENDENTLY
    from durable evidence — never collapsed into one 'best executor' score.
    Dimensions with no evidence render as 'insufficient evidence' (never
    guessed). Read-only; evidence is appended by producers (assistant-verify,
    mission outcomes, usage)."""
    from command_center.ranking import build_leaderboard
    board = build_leaderboard(_read_leaderboard_evidence(),
                              executors=list(_LEADERBOARD_EXECUTORS))
    return board.to_dict()


@app.get("/api/domain/{domain_id}/cards")
def domain_cards(domain_id: str) -> dict:
    spec = _domain_spec(domain_id)
    out = _domain_cards(spec)
    out["domain_id"] = domain_id
    # a live loader may report the board's REAL lanes; spec.columns is the
    # fallback so fixture/store domains render their configured lanes
    out.setdefault("columns", spec.get("columns", []))
    out["empty_state"] = spec.get("empty_state", {})
    if spec.get("source") == "board_store":
        # one-step machine: the UI offers only these targets per lane
        out["transitions"] = {
            c: _allowed_transitions(spec, c) for c in out["columns"]}
        if (
            domain_id == "book"
            and any(card.get("status") is None for card in out["cards"])
        ):
            out["transitions"][""] = _allowed_transitions(spec, None)
        if any(card.get("status") == "Unstaged" for card in out["cards"]):
            out["transitions"]["Unstaged"] = list(out["columns"][:1])
    return out


@app.post("/api/domain/{domain_id}/sync")
def sync_grand_todo_source(domain_id: str) -> dict:
    """Explicitly reconcile the canonical tracker; domain GETs stay read-only."""
    if domain_id not in GRAND_TODO_DOMAIN_IDS:
        raise HTTPException(
            status_code=404,
            detail=f"domain {domain_id!r} has no canonical grand-todo sync",
        )
    _require_chat()
    spec = _domain_spec(domain_id)
    _require_domain_writable(spec)
    source_path = _grand_todo_source(domain_id)
    if not source_path.is_file():
        raise HTTPException(
            status_code=503,
            detail="canonical GRAND TODO source is unavailable; no sync was run")
    from command_center.cli.grand_todo_import import (
        PROFILES,
        GrandTodoImportError,
        run_import,
    )
    try:
        result = run_import(
            source_path=source_path,
            store_dir=BOARD_STORE_DIR,
            event_log_path=KANBAN_EVENT_LOG,
            apply=True,
            profile=PROFILES[domain_id],
        )
    except GrandTodoImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "status": "synchronized",
        "domain_id": spec["domain_id"],
        "source_sha256": result["source_sha256"],
        "counts": result["counts"],
    }


@app.get("/api/domain/{domain_id}/card/{card_id}")
def domain_card(domain_id: str, card_id: str) -> dict:
    spec = _domain_spec(domain_id)
    for card in _domain_cards(spec)["cards"]:
        if str(card.get("card_id")) == card_id:
            return {"domain_id": domain_id, "card": card,
                    "drawer_fields": spec.get("drawer_fields", [])}
    raise HTTPException(status_code=404,
                        detail=f"card {card_id!r} not in domain {domain_id!r}")


# ── Life Center: catalog-joined Launch view + read-only action dispatch ────
# GETs need no gate (matches domain_cards/domain_card above — pure reads over
# the catalog + the three existing Life Center boards). The dispatch POST
# requires _require_chat(), same as every other write-shaped route in this
# file, even though every action life_center_actions.py registers is itself
# read-only — see that module's docstring for why nothing beyond that tier
# is ever added here.

class LifeCenterActionDispatchIn(BaseModel):
    action_id: str
    service_id: str | None = None
    idempotency_key: str | None = None
    parameters: dict = {}


def _life_center_view():
    from command_center.mcp.life_center_launch import live_launch_view
    try:
        return live_launch_view()
    except Exception as exc:  # noqa: BLE001 - a clear 503, never a raw stack trace to the SPA
        raise HTTPException(
            status_code=503,
            detail=f"Life Center view unavailable: {exc}") from exc


@app.get("/api/life-center/launch")
def life_center_launch() -> dict:
    from dataclasses import asdict
    return asdict(_life_center_view())


@app.get("/api/life-center/services/{service_id}")
def life_center_service(service_id: str) -> dict:
    from dataclasses import asdict
    view = _life_center_view()
    for svc in view.services:
        if svc.service_id == service_id:
            return asdict(svc)
    raise HTTPException(status_code=404, detail=f"unknown service_id: {service_id!r}")


def _life_center_infra_root() -> Path:
    """The container mount path if present, else the host-relative path when
    running this file outside a container (e.g. local dev). A tuple literal
    of both candidates would evaluate the host fallback unconditionally —
    `Path(__file__).resolve().parents[2]` only has 2 parents when __file__ is
    the container's /app/app.py, raising IndexError before the first (working)
    candidate was ever checked. Lazy per-candidate evaluation, found live."""
    container_path = Path("/app/life-center-infra")
    if container_path.is_dir():
        return container_path.resolve()
    parents = Path(__file__).resolve().parents
    if len(parents) > 2:
        host_path = parents[2] / "life-center-infra"
        if host_path.is_dir():
            return host_path.resolve()
    raise HTTPException(status_code=503, detail="life-center-infra is not mounted in this deployment")


@app.get("/api/life-center/services/{service_id}/runbook")
def life_center_service_runbook(service_id: str) -> dict:
    """Resolve and return ONLY the registered runbook for this service — never
    an arbitrary path. Most runbooks live under life-center-infra/runbooks/;
    a few reference ../docs/... one level up (also mounted, read-only) — both
    are legitimate, so the boundary is "inside this repository", not "inside
    life-center-infra". Anything resolving outside that fails closed."""
    view = _life_center_view()
    svc = next((s for s in view.services if s.service_id == service_id), None)
    if svc is None:
        raise HTTPException(status_code=404, detail=f"unknown service_id: {service_id!r}")
    runbook_link = next((link for link in svc.links if link.kind == "runbook"), None)
    if not runbook_link or not runbook_link.href:
        raise HTTPException(status_code=404, detail=f"{service_id} has no registered runbook")

    lc_root = _life_center_infra_root()
    repo_root = lc_root.parent
    candidate = (lc_root / runbook_link.href).resolve()
    if not candidate.is_relative_to(repo_root):
        raise HTTPException(status_code=400,
                            detail="runbook path resolves outside the repository")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="runbook file not found on this host")

    return {
        "service_id": service_id,
        "runbook_path": runbook_link.href,
        "content": candidate.read_text(encoding="utf-8"),
    }


@app.post("/api/life-center/actions/dispatch")
def life_center_dispatch_action(body: LifeCenterActionDispatchIn) -> dict:
    _require_chat()
    from command_center.mcp.life_center_actions import ActionResult, dispatch

    result: ActionResult = dispatch(
        body.action_id, service_id=body.service_id,
        idempotency_key=body.idempotency_key, parameters=body.parameters,
    )
    return {
        "action_id": result.action_id, "request_id": result.request_id,
        "status": result.status, "result": result.result, "error": result.error,
    }


@app.get("/api/domain/{domain_id}/card/{card_id}/progress")
def domain_card_progress(domain_id: str, card_id: str) -> dict:
    spec = _domain_spec(domain_id)
    return _domain_progress(spec, card_id)


@app.get("/api/domain/{domain_id}/actions")
def domain_actions(domain_id: str) -> dict:
    """Governed verbs this domain's cards may offer. Wall verbs can never appear
    (the config contract rejects them); dispatch goes through /api/action, which
    requires the console deployment (chat enabled)."""
    spec = _domain_spec(domain_id)
    blockers = _domain_write_blockers(spec)
    return {"domain_id": domain_id,
            "allowed_actions": spec.get("allowed_actions", []),
            "dispatch_enabled": CHAT_ENABLED and not blockers,
            "write_ready": not blockers,
            "write_blockers": blockers}


# ---- chat + governed writes (the console as a channel) --------------------
_cores: dict[str, object] = {}


def _role_names() -> set[str]:
    return {r["role"] for r in models()["roles"]}


_FRONTIER_PREFIX = "frontier:"
_LOCAL_FRONTIER_PREFIX = "local-frontier:"


def _get_core(model: str):
    """One GatewayCore per model role (cached) — the same loop Discord uses, so
    the in-app agent can chat AND drive the governed action verbs. A
    "frontier:<id>" model routes to the paid frontier-router lane instead of
    LiteLLM; a "local-frontier:<id>" model routes to the experimental loopback
    lane instead — neither gets tools or board/memory context (see
    channels/frontier_client.py / channels/local_frontier_client.py)."""
    if model not in _cores:
        from command_center.channels.core import GatewayConfig, GatewayCore
        frontier_id = (model[len(_FRONTIER_PREFIX):]
                       if model.startswith(_FRONTIER_PREFIX) else None)
        local_frontier_id = (model[len(_LOCAL_FRONTIER_PREFIX):]
                             if model.startswith(_LOCAL_FRONTIER_PREFIX) else None)
        _cores[model] = GatewayCore(GatewayConfig.build(
            surface="app", model=model, frontier_model_id=frontier_id,
            local_frontier_model_id=local_frontier_id))
    return _cores[model]


def _require_chat() -> None:
    if not CHAT_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="chat/writes not enabled in this deployment "
                   "(set KANBAN_UI_CHAT_ENABLED=1 + mount growth-os/.env)")


_agent_worker_client: AgentWorkerClient | None = None


def _get_agent_worker_client() -> AgentWorkerClient:
    """Lazily constructed so a deployment with agent sessions OFF never needs
    AGENT_WORKER_TOKEN configured at all — matches _get_core's lazy pattern
    for the chat lane."""
    global _agent_worker_client
    if _agent_worker_client is None:
        if not AGENT_WORKER_TOKEN:
            raise HTTPException(
                status_code=503,
                detail="AGENT_WORKER_TOKEN is not configured for this cockpit "
                       "(agent sessions cannot authenticate to the worker)")
        _agent_worker_client = AgentWorkerClient(AGENT_WORKER_URL, AGENT_WORKER_TOKEN)
    return _agent_worker_client


def _require_agent_sessions() -> AgentWorkerClient:
    if not AGENT_SESSIONS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="agent sessions not enabled in this deployment "
                   "(set KANBAN_UI_AGENT_SESSIONS_ENABLED=1)")
    return _get_agent_worker_client()


def _call_worker(fn, *args: object, **kwargs: object):
    """Call an AgentWorkerClient method, translating a transport failure to
    502 and preserving whatever real status/detail the worker itself
    responded with (404/409/400 mean the same thing here as on the worker —
    never collapsed into a generic 500)."""
    try:
        r = fn(*args, **kwargs)
    except AgentWorkerUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise HTTPException(status_code=r.status_code, detail=detail)
    return r.json()


# ── Usage & Limits (in-process; command_center.usage imported directly) ───────
_usage_service = None   # type: ignore[var-annotated]  # UsageService | None
_usage_collectors: list = []   # [(CollectorProtocol, collector_id), ...]


def _usage_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _jsonl_usage_rows(path: Path, *, source_id: str,
                      label: str, after_iso: str | None = None,
                      timestamp_field: str = "ts") -> tuple[list[dict], dict]:
    """Read a usage-only JSONL ledger and return explicit source health.

    The returned rows are normalized later by the pure portfolio builder. A
    missing optional ledger means no calls have been recorded; malformed rows
    degrade the source visibly instead of disappearing without explanation.
    """
    if not path.is_file():
        return [], {"source_id": source_id, "label": label, "state": "empty",
                    "row_count": 0, "detail": "No calls recorded yet"}
    retained_rows: list[dict] = []
    malformed = 0
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(value, dict):
                retained_rows.append(value)
            else:
                malformed += 1
    except OSError as exc:
        return [], {"source_id": source_id, "label": label,
                    "state": "unavailable", "row_count": 0,
                    "detail": f"Usage ledger could not be read: {exc}"}
    after = _usage_timestamp(after_iso)
    invalid_timestamps = sum(
        1 for row in retained_rows
        if _usage_timestamp(row.get(timestamp_field)) is None
    )
    rows = [
        row for row in retained_rows
        if after is None
        or ((_usage_timestamp(row.get(timestamp_field)) or datetime.min.replace(
            tzinfo=UTC)) >= after)
    ]
    observed = [
        parsed for row in retained_rows
        if (parsed := _usage_timestamp(row.get(timestamp_field))) is not None
    ]
    state = "degraded" if malformed or invalid_timestamps else "ok"
    detail = (
        f"Loaded {len(rows)} calls in this period; "
        f"{len(retained_rows)} retained"
    )
    if malformed:
        detail += f"; skipped {malformed} malformed rows"
    if invalid_timestamps:
        detail += f"; excluded {invalid_timestamps} rows without a valid timestamp"
    return rows, {
        "source_id": source_id, "label": label, "state": state,
        "row_count": len(rows), "retained_row_count": len(retained_rows),
        "latest_observed_at": max(observed).isoformat() if observed else None,
        "detail": detail,
    }


def _litellm_usage_rows(after_iso: str | None = None) -> tuple[list[dict], dict]:
    """Read all retained local-model spend rows from LiteLLM's paginated API.

    Only the sanitized aggregation leaves this process. The master key stays in
    the mounted environment file and is used solely for the local control-plane
    request. A bounded page ceiling prevents an unbounded UI request; truncation
    is reported as degraded source health rather than presented as complete.
    """
    from command_center.channels.core import env as gateway_env

    live_env = gateway_env()
    master_key = live_env.get("LITELLM_MASTER_KEY", "")
    base_url = (os.environ.get("LITELLM_BASE_URL")
                or live_env.get("LITELLM_URL")
                or live_env.get("LITELLM_BASE_URL", "")).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    if not base_url:
        return [], {"source_id": "litellm", "label": "Local model gateway",
                    "state": "unavailable", "row_count": 0,
                    "detail": "LiteLLM base URL is not configured"}
    if not master_key:
        return [], {"source_id": "litellm", "label": "Local model gateway",
                    "state": "unavailable", "row_count": 0,
                    "detail": "LiteLLM usage credentials are not configured"}

    rows: list[dict] = []
    page_size = 100
    max_pages = 50
    after = _usage_timestamp(after_iso)
    params = {
        "start_date": (
            after.strftime("%Y-%m-%d %H:%M:%S")
            if after else "2000-01-01 00:00:00"),
        "end_date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "page": 1,
        "page_size": page_size,
        "sort_by": "startTime",
        "sort_order": "asc",
    }
    try:
        with httpx.Client(
            headers={"Authorization": f"Bearer {master_key}"}, timeout=10,
        ) as client:
            total_pages = 1
            while params["page"] <= min(total_pages, max_pages):
                response = client.get(f"{base_url}/spend/logs/v2", params=params)
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, list):
                    raise ValueError("LiteLLM spend response has no data list")
                rows.extend(row for row in data if isinstance(row, dict))
                total_pages = max(1, int(payload.get("total_pages") or 1))
                params["page"] += 1
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return [], {"source_id": "litellm", "label": "Local model gateway",
                    "state": "unavailable", "row_count": 0,
                    "detail": f"LiteLLM usage query failed: {exc}"}

    truncated = total_pages > max_pages
    observed = [
        parsed for row in rows
        if (parsed := _usage_timestamp(row.get("startTime"))) is not None
    ]
    detail = (f"Loaded the first {len(rows)} calls in this period; source has more rows"
              if truncated else f"Loaded {len(rows)} calls in this period")
    return rows, {"source_id": "litellm", "label": "Local model gateway",
                  "state": "degraded" if truncated else "ok",
                  "row_count": len(rows),
                  "retained_row_count": None,
                  "latest_observed_at": max(observed).isoformat() if observed else None,
                  "detail": detail}


def _model_usage_portfolio(window_id: str = "week") -> dict:
    import yaml
    from command_center.usage.portfolio import (
        build_model_usage_portfolio,
        resolve_usage_window,
    )

    models_path = CONFIGS_DIR / "models.yaml"
    if not models_path.is_file():
        raise HTTPException(status_code=503,
                            detail=f"models.yaml not at {models_path}")
    models_config = yaml.safe_load(models_path.read_text(encoding="utf-8")) or {}
    window = resolve_usage_window(window_id)
    after_iso = window["start_at"]
    litellm_rows, litellm_source = _litellm_usage_rows(after_iso)
    frontier_rows, frontier_source = _jsonl_usage_rows(
        FRONTIER_USAGE_LEDGER, source_id="openrouter_ledger",
        label="OpenRouter ledger", after_iso=after_iso)
    local_frontier_rows, local_frontier_source = _jsonl_usage_rows(
        LOCAL_FRONTIER_USAGE_LEDGER, source_id="local_frontier_ledger",
        label="Local frontier ledger", after_iso=after_iso)
    return build_model_usage_portfolio(
        models_config=models_config,
        litellm_rows=litellm_rows,
        litellm_available=litellm_source["state"] in {"ok", "degraded"},
        frontier_rows=frontier_rows,
        local_frontier_rows=local_frontier_rows,
        sources=[litellm_source, frontier_source, local_frontier_source],
        window=window,
    )


def _get_usage_service():
    """Lazy per-process UsageService over an in-memory store (mirrors
    _get_agent_worker_client's lazy singleton). Registers the enabled
    collectors ONCE so /api/model-usage/refresh and /collector-health agree on
    the same set. Nothing is polled at construction — the page shows honest
    UNKNOWN until a refresh runs."""
    global _usage_service
    if _usage_service is None:
        from command_center.usage.service import UsageService
        if USAGE_LEDGER and LEDGER_BASE_URL:
            # read the SAME durable Ledger the worker writes to (restart-proof,
            # one authoritative store) instead of a per-process in-memory store
            import httpx
            from command_center.usage.ledger_store import LedgerUsageStore
            store = LedgerUsageStore(
                httpx.Client(base_url=LEDGER_BASE_URL, timeout=30))
        else:
            from command_center.usage.store import UsageStore
            store = UsageStore()   # type: ignore[assignment]
        _usage_service = UsageService(store)
        _usage_collectors.clear()
        if USAGE_FAKE:
            from command_center.usage.collectors.fake import FakeCollector
            _usage_collectors.append((FakeCollector(), "fake"))
        worker_owned_collectors = USAGE_LEDGER and AGENT_SESSIONS_ENABLED
        if USAGE_CODEX and not worker_owned_collectors:
            from command_center.usage.collectors.codex_app_server import (
                CODEX_COLLECTOR_ID, CodexAppServerCollector)
            _usage_collectors.append((CodexAppServerCollector(), CODEX_COLLECTOR_ID))
        if USAGE_CLAUDE and not worker_owned_collectors:
            # TWO event-fed Claude collectors — one per lane — so a local
            # subscription session's limits never land on the API lane's card.
            # They report honest UNKNOWN until a real rate_limit event is teed
            # in from a live session (see _feed_agent_usage below).
            from command_center.usage.collectors.claude_agent import (
                ClaudeRateLimitCollector)
            _usage_collectors.append(
                (ClaudeRateLimitCollector("claude_code_local"), "claude_code_local_rl"))
            _usage_collectors.append(
                (ClaudeRateLimitCollector("claude_agent"), "claude_agent_rl"))
    return _usage_service


# session_id -> harness_id, so the SSE usage tee can attribute a rate_limit
# event to the right runtime without an extra worker round-trip. Populated on
# create; lazily backfilled from the worker for pre-existing sessions.
_session_harness: dict[str, str] = {}
_CLAUDE_HARNESSES = ("claude_code_local", "claude_agent")


def _harness_of(client, session_id: str) -> str | None:
    harness = _session_harness.get(session_id)
    if harness is None:
        try:
            rec = _call_worker(client.get_session, session_id)
            harness = rec.get("harness")
            if harness:
                _session_harness[session_id] = harness
        except Exception:
            return None
    return harness


def _feed_agent_usage(client, session_id: str, ev: dict) -> None:
    """Tee a live `rate_limit` AgentEvent into the durable usage store so a
    running Claude session lights up its own Usage card + selector badge. Codex
    limits come from its own provider collector, so only Claude lanes are fed
    here. Best-effort — a usage-tee failure must never break the browser SSE.

    RETIRED AS A WRITER under USAGE_LEDGER: when the cockpit reads the shared
    Ledger, the WORKER is the sole authoritative writer (worker_app._run_turn),
    so this browser-dependent tee stands down to avoid a second writer. It stays
    active only as the in-memory dev/test fallback (no worker durability)."""
    if not (USAGE_ENABLED and USAGE_CLAUDE) or USAGE_LEDGER \
            or ev.get("type") != "rate_limit":
        return
    harness = _harness_of(client, session_id)
    if harness not in _CLAUDE_HARNESSES:
        return
    try:
        from command_center.usage.collectors.claude_agent import translate_rate_limit_info
        result = translate_rate_limit_info(
            ev.get("payload", {}) or {}, ev.get("ts") or "", harness)
        _get_usage_service().ingest_collector_result(result)
    except Exception:
        pass


def _require_usage():
    if not USAGE_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Usage & Limits not enabled in this deployment "
                   "(set KANBAN_UI_USAGE_ENABLED=1)")
    return _get_usage_service()


class ChatIn(BaseModel):
    text: str
    conversation_id: str = "app"
    model: str = "chat"


class ChatThreadIn(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=80)
    target: str = Field(default="GatewayCore", max_length=80)
    last_prompt: str | None = Field(default=None, max_length=2000)
    model: str | None = Field(default=None, max_length=80)


def _thread_title(text: str | None) -> str:
    compact = " ".join((text or "").split())
    if not compact:
        return "Cockpit chat"
    return compact[:51] + "..." if len(compact) > 54 else compact


def _read_chat_threads() -> list[dict]:
    if not CHAT_THREADS_FILE.is_file():
        return []
    try:
        data = json.loads(CHAT_THREADS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("threads", data if isinstance(data, list) else [])
    if not isinstance(rows, list):
        return []
    clean: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        conversation_id = str(row.get("conversation_id") or row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not conversation_id or not title:
            continue
        clean.append({
            "conversation_id": conversation_id[:200],
            "id": conversation_id[:200],
            "title": title[:80],
            "updated_at": str(row.get("updated_at") or row.get("updatedAt") or ""),
            "target": str(row.get("target") or "GatewayCore")[:80],
            "last_prompt": str(row.get("last_prompt") or row.get("lastPrompt") or "")[:2000],
            "model": str(row.get("model") or "")[:80],
        })
    return clean[:50]


def _write_chat_threads(threads: list[dict]) -> None:
    CHAT_THREADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHAT_THREADS_FILE.with_suffix(f"{CHAT_THREADS_FILE.suffix}.tmp")
    payload = {"threads": threads[:50]}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(CHAT_THREADS_FILE)


def _upsert_chat_thread(body: ChatThreadIn) -> dict:
    now = datetime.now(UTC).isoformat()
    last_prompt = (body.last_prompt or "").strip()
    title = (body.title or "").strip() or _thread_title(last_prompt)
    conversation_id = body.conversation_id.strip()
    next_thread = {
        "conversation_id": conversation_id,
        "id": conversation_id,
        "title": title[:80],
        "updated_at": now,
        "target": (body.target or "GatewayCore").strip()[:80],
        "last_prompt": last_prompt[:2000],
        "model": (body.model or "").strip()[:80],
    }
    threads = [
        next_thread,
        *[row for row in _read_chat_threads()
          if row.get("conversation_id") != conversation_id],
    ][:50]
    _write_chat_threads(threads)
    return next_thread


class ActionIn(BaseModel):
    action: str
    params: dict = {}


class DomainMoveIn(BaseModel):
    card_id: str
    status: str
    # Optional rejection metadata, recorded when a job card is moved to
    # "Rejected / Skip" so the rejection report can suggest filter changes.
    reason_code: str | None = None
    reason_note: str | None = None


class GrandTodoEditIn(BaseModel):
    raw_markdown: str = Field(min_length=1)
    expected_source_sha256: str = Field(min_length=64, max_length=64)


class DomainNoteIn(BaseModel):
    type: str = "manual_note"
    text: str
    source: str = "cockpit"
    furthers_process: bool = False


class BookFieldsIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    author: str | None = Field(default=None, max_length=200, strict=True)
    description: str | None = Field(default=None, max_length=20_000, strict=True)
    tier: str | None = Field(default=None, max_length=100, strict=True)
    type: str | None = Field(default=None, max_length=100, strict=True)
    genre: str | None = Field(default=None, max_length=120, strict=True)
    module: str | None = Field(default=None, max_length=300, strict=True)
    section: str | None = Field(default=None, max_length=100, strict=True)
    hours: str | None = Field(default=None, max_length=40, strict=True)
    isbn: str | None = Field(default=None, max_length=40, strict=True)
    notes: str | None = Field(default=None, max_length=50_000, strict=True)
    current_chapter: str | None = Field(
        default=None, max_length=300, strict=True)
    current_page: int | None = Field(
        default=None, ge=0, le=1_000_000, strict=True)
    total_pages: int | None = Field(
        default=None, ge=1, le=1_000_000, strict=True)
    progress_percent: int | None = Field(
        default=None, ge=0, le=100, strict=True)

    @field_validator("hours")
    @classmethod
    def _valid_hours(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return value
        if not re.fullmatch(r"\d+(?:\.\d+)?", value):
            raise ValueError("hours must be a non-negative number")
        return value

    @model_validator(mode="after")
    def _page_within_total(self):
        if (
            self.current_page is not None
            and self.total_pages is not None
            and self.current_page > self.total_pages
        ):
            raise ValueError("current_page cannot exceed total_pages")
        return self


class BookCreateIn(BookFieldsIn):
    title: str = Field(min_length=1, max_length=300, strict=True)
    status: str = Field(min_length=1, max_length=80, strict=True)

    @field_validator("title", "status")
    @classmethod
    def _nonblank_required(cls, value: str) -> str:
        if not value:
            raise ValueError("value must not be blank")
        return value


class BookUpdateIn(BookFieldsIn):
    title: str | None = Field(default=None, max_length=300, strict=True)


class BookNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    author: str = Field(min_length=1, max_length=120, strict=True)
    text: str = Field(min_length=1, max_length=10_000, strict=True)
    chapter: str | None = Field(
        default=None, min_length=1, max_length=300, strict=True)
    page: int | None = Field(
        default=None, ge=0, le=1_000_000, strict=True)
    total_pages: int | None = Field(
        default=None, ge=1, le=1_000_000, strict=True)
    progress_percent: int | None = Field(
        default=None, ge=0, le=100, strict=True)

    @field_validator("author", "text")
    @classmethod
    def _nonblank_required(cls, value: str) -> str:
        if not value:
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def _page_within_total(self):
        if (
            self.page is not None
            and self.total_pages is not None
            and self.page > self.total_pages
        ):
            raise ValueError("page cannot exceed total_pages")
        return self


class BookNoteRecord(BookNoteIn):
    note_id: str = Field(pattern=r"^book-note-[a-f0-9]{16}$")
    sequence: int = Field(ge=1, strict=True)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value


_BOOK_POSITION_FIELDS = (
    "current_chapter", "current_page", "total_pages", "progress_percent",
)
_BOOK_EDITABLE_FIELDS = (
    "author", "description", "tier", "type", "genre", "module", "section",
    "hours", "isbn", "notes", *_BOOK_POSITION_FIELDS,
)


class _BookDuplicateError(ValueError):
    pass


class _BookStateError(ValueError):
    pass


def _book_title_projection(card: dict[str, Any]) -> tuple[str, str]:
    """Resolve only canonical or exact retained source title text.

    The projection is deliberately read-only. A non-text stored value is a
    contract error rather than something to stringify, guess, or hide.
    """
    source_cells = card.get("appflowy_source_cells")
    if source_cells is not None and not isinstance(source_cells, dict):
        raise _BookStateError(
            "stored book appflowy_source_cells must be an object")
    source_cells = source_cells or {}
    candidates = (
        ("title", card.get("title"), "canonical"),
        ("Title", card.get("Title"), "recovered_from_source"),
        ("Name", card.get("Name"), "recovered_from_source"),
        (
            "appflowy_source_cells.Title",
            source_cells.get("Title"),
            "recovered_from_source",
        ),
        (
            "appflowy_source_cells.Name",
            source_cells.get("Name"),
            "recovered_from_source",
        ),
    )
    for field, value, integrity in candidates:
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise _BookStateError(f"stored book {field} must be text")
        title = value.strip()
        if title:
            return title, integrity
    return "", "missing"


def _public_book_card(card: dict[str, Any]) -> dict[str, Any]:
    """Return the Book API shape with audit history redacted consistently."""
    public = {
        key: value for key, value in card.items()
        if key not in _BOARD_AUDIT_HISTORY_FIELDS
    }
    title, integrity = _book_title_projection(card)
    public["title"] = title
    public["title_integrity"] = integrity
    return public


def _normalized_book_text(value: Any, *, field: str) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise _BookStateError(f"stored book {field} must be text")
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _ensure_unique_book(
    cards: list[dict[str, Any]],
    *,
    title: str,
    author: str | None,
    exclude_card_id: str | None = None,
) -> None:
    wanted = (
        _normalized_book_text(title, field="title"),
        _normalized_book_text(author, field="author"),
    )
    for card in cards:
        card_id = str(card.get("card_id") or "")
        if card_id == exclude_card_id:
            continue
        display_title, _integrity = _book_title_projection(card)
        existing_title = _normalized_book_text(
            display_title, field=f"{card_id!r} title")
        existing_author = _normalized_book_text(
            card.get("author"), field=f"{card_id!r} author")
        if not existing_title:
            # Historical provenance rows with a genuinely blank source title stay
            # visible and editable, but cannot equal the required nonblank title
            # being checked. Stored field types were validated above; never invent
            # or remove a value to make this pass.
            continue
        existing = (existing_title, existing_author)
        if existing == wanted:
            raise _BookDuplicateError(
                f"a book with this title and author already exists: {card_id}")


def _validated_book_location(fields: dict[str, Any]) -> None:
    """Validate the complete stored reading position after partial updates."""
    chapter = fields.get("current_chapter")
    if chapter is not None and (
        not isinstance(chapter, str) or not chapter.strip()
    ):
        raise _BookStateError(
            "stored book current_chapter must be nonblank text")

    limits = {
        "current_page": (0, 1_000_000),
        "total_pages": (1, 1_000_000),
        "progress_percent": (0, 100),
    }
    values: dict[str, int | None] = {}
    for name, (minimum, maximum) in limits.items():
        value = fields.get(name)
        if value is None:
            values[name] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise _BookStateError(f"stored book {name} must be an integer")
        if not minimum <= value <= maximum:
            raise _BookStateError(
                f"stored book {name} must be between {minimum} and {maximum}")
        values[name] = value
    if (
        values["current_page"] is not None
        and values["total_pages"] is not None
        and values["current_page"] > values["total_pages"]
    ):
        raise _BookStateError(
            "stored book current_page cannot exceed total_pages")


def _book_create_fields(body: BookCreateIn, now: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "title": body.title,
        "created_at": now,
        "updated_at": now,
        "book_notes": [],
    }
    for name in _BOOK_EDITABLE_FIELDS:
        value = getattr(body, name)
        if value not in (None, ""):
            fields[name] = value
    if any(getattr(body, name) is not None for name in _BOOK_POSITION_FIELDS):
        fields["reading_position_updated_at"] = now
    _validated_book_location(fields)
    return fields


def _book_update_values(body: BookUpdateIn) -> tuple[dict[str, Any], set[str]]:
    submitted = set(body.model_fields_set)
    if not submitted:
        raise HTTPException(status_code=400, detail="at least one book field is required")
    if "title" in submitted and body.title in (None, ""):
        raise HTTPException(status_code=422, detail="title must not be blank")
    updates: dict[str, Any] = {}
    clears: set[str] = set()
    for name in ("title", *_BOOK_EDITABLE_FIELDS):
        if name not in submitted:
            continue
        value = getattr(body, name)
        if value in (None, ""):
            clears.add(name)
        else:
            updates[name] = value
    return updates, clears


def _validated_book_notes(fields: dict[str, Any]) -> list[dict[str, Any]]:
    if "book_notes" not in fields:
        return []
    raw = fields["book_notes"]
    if not isinstance(raw, list):
        raise _BookStateError("stored book_notes must be a list")
    seen_ids: set[str] = set()
    for index, item in enumerate(raw, start=1):
        try:
            note = BookNoteRecord.model_validate(item)
        except Exception as exc:
            raise _BookStateError(
                f"stored book_notes entry {index} is invalid: {exc}") from exc
        if note.sequence != index:
            raise _BookStateError(
                "stored book_notes sequences must be contiguous and ordered "
                f"from 1; entry {index} has sequence {note.sequence}")
        if note.note_id in seen_ids:
            raise _BookStateError(
                f"stored book_notes contains duplicate note_id {note.note_id!r}")
        seen_ids.add(note.note_id)
    return raw


def _raise_book_mutation_error(exc: Exception) -> None:
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=f"book card {exc.args[0]!r} not found")
    if isinstance(exc, (_BookDuplicateError, _BookStateError, FileExistsError)):
        raise HTTPException(status_code=409, detail=str(exc))
    raise exc


def _move_book_card(
    provider: Any,
    spec: dict,
    card_id: str,
    target_status: str,
) -> dict[str, Any]:
    """Read, validate, and append one book transition under one board lock."""
    action = _column_action(spec, target_status)

    def mutate(card: dict[str, Any]) -> dict[str, Any]:
        previous = card.get("status")
        if previous == target_status:
            return {
                "status": "unchanged",
                "domain_id": "book",
                "card_id": card_id,
                "card": _public_book_card(card),
                "event": None,
            }
        allowed = _allowed_transitions(spec, previous)
        if target_status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"cards move one step at a time: from {previous!r} the "
                       f"next steps are {allowed or ['(terminal)']}, "
                       f"not {target_status!r}",
            )
        event = emit_event(
            provider.log,
            action=action,
            board_id=provider.board_id,
            card_id=card_id,
            source_surface="internal_ui",
            actor_type="human",
            status_before=previous,
            status_after=target_status,
        )
        committed_card = {
            **card,
            "status": target_status,
            "last_event_id": event.event_id,
            "last_actor": event.actor_type,
        }
        return {
            "status": "moved",
            "domain_id": "book",
            "card_id": card_id,
            "from_status": previous,
            "to_status": target_status,
            "event": event.model_dump(mode="json"),
            "side_effect": None,
            "card": _public_book_card(committed_card),
        }

    try:
        return provider.mutate_card_event(card_id, mutate)
    except Exception as exc:
        _raise_book_mutation_error(exc)
        raise AssertionError("unreachable")


class PostDraftIn(BaseModel):
    """Exact operator-authored LinkedIn draft fields.

    The server derives only review metadata (hook, character count, lint);
    it never asks a model to fill missing copy or publishes externally.
    """
    account: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=3000)
    tags: list[str] = Field(default_factory=list)
    source_ref: str | None = Field(default=None, max_length=500)
    scheduled_for: datetime | None = None


class DraftDefaultIn(BaseModel):
    key: str
    value: str


class JobSearchRuntimeSettingsIn(BaseModel):
    daily_run_time: str | None = None
    max_suggested_jobs_per_day: int | None = None
    max_bot_possible_suggestions_per_day: int | None = None
    max_manual_required_suggestions_per_day: int | None = None
    max_selected_jobs_per_day: int | None = None


class JobSearchCategorySettingsIn(BaseModel):
    role_focus: str | None = None
    keywords: list[str] | None = None
    # required only when CREATING a new category (must name a known variant)
    resume_variant: str | None = None


class JobSearchLocationsSettingsIn(BaseModel):
    # partial update: only provided fields are written; validation happens
    # against the merged JobSearchConfig so a bad mode/region combo returns 400
    mode: str | None = None
    remote_ok: bool | None = None
    remote_types_allowed: list[str] | None = None
    employment_types_allowed: list[str] | None = None
    countries: list[str] | None = None
    regions: list[str] | None = None


class JobSearchLanguagesSettingsIn(BaseModel):
    spoken: list[str] | None = None
    require_spoken_for_apply: bool | None = None


class JobSearchCompanyTargetsSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    faang: list[str]
    sports_teams_keywords: list[str]
    sports_tech_companies: list[str]
    major_other: list[str]


class JobSearchRetentionSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rich_application_cache_days: int = Field(ge=1, le=365)


class StandingAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=1, max_length=5_000)
    question: str | None = Field(default=None, max_length=2_000)
    covers: list[str] | None = Field(default=None, max_length=100)


class JobSearchRelationshipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    role_title: str = Field(default="", max_length=200)
    relationship_kind: str = Field(
        default="known_contact", min_length=1, max_length=80)
    linkedin_url: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=5_000)
    active: bool = True


class JobSearchQuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2_000)


class JobSearchCandidateAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=5_000)


class JobSearchDigestItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    role: str
    fit_score: int | float
    automation_class: str
    apply_url: str
    review_href: str
    column: Literal["Suggested Jobs", "Needs Geoff"]


class JobSearchDigestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[JobSearchDigestItemOut]
    counts: dict[str, int]
    generated_at: datetime


@app.post("/api/domain/book/cards", status_code=201)
def create_book_card(body: BookCreateIn) -> dict:
    """Create one operator-authored book and enter its selected governed lane."""
    _require_chat()
    spec = _domain_spec("book")
    _require_domain_writable(spec)
    action = _column_action(spec, body.status)
    provider = _board_store_provider(spec)

    import secrets

    card_id = "book-manual-" + secrets.token_hex(8)
    now = datetime.now(UTC).isoformat()
    fields = _book_create_fields(body, now)

    def mutate(_current, cards):
        _ensure_unique_book(
            cards, title=body.title, author=body.author)
        return fields

    event: dict[str, Any] = {}

    def emit_initial_status() -> None:
        event["value"] = emit_event(
            provider.log,
            action=action,
            board_id=provider.board_id,
            card_id=card_id,
            source_surface="internal_ui",
            actor_type="human",
            status_after=body.status,
        )

    try:
        provider.mutate_card_fields(
            card_id, mutate, create=True, after_write=emit_initial_status)
    except Exception as exc:
        _raise_book_mutation_error(exc)
    return {
        "status": "created",
        "domain_id": "book",
        "card_id": card_id,
        "card": _public_book_card(_find_domain_card(provider, card_id)),
        "event": event["value"].model_dump(mode="json"),
    }


@app.put("/api/domain/book/card/{card_id}")
def update_book_card(card_id: str, body: BookUpdateIn) -> dict:
    """Update only explicit editable fields; fold state and provenance stay owned."""
    _require_chat()
    spec = _domain_spec("book")
    _require_domain_writable(spec)
    provider = _board_store_provider(spec)
    updates, clears = _book_update_values(body)
    now = datetime.now(UTC).isoformat()
    position_changed = bool(
        set(body.model_fields_set).intersection(_BOOK_POSITION_FIELDS))

    def mutate(current, cards):
        if current is None:
            raise KeyError(card_id)
        next_fields = dict(current)
        for name in clears:
            next_fields.pop(name, None)
        next_fields.update(updates)
        if position_changed:
            next_fields["reading_position_updated_at"] = now
        _validated_book_location(next_fields)
        title, _title_integrity = _book_title_projection(next_fields)
        if not title:
            raise _BookStateError("stored book title is missing or invalid")
        author = next_fields.get("author")
        _ensure_unique_book(
            cards, title=title, author=author, exclude_card_id=card_id)
        _validated_book_notes(next_fields)
        next_fields["updated_at"] = now
        return next_fields

    try:
        provider.mutate_card_fields(card_id, mutate)
    except Exception as exc:
        _raise_book_mutation_error(exc)
    return {
        "status": "updated",
        "domain_id": "book",
        "card_id": card_id,
        "card": _public_book_card(_find_domain_card(provider, card_id)),
    }


@app.post("/api/domain/book/card/{card_id}/notes", status_code=201)
def add_book_note(card_id: str, body: BookNoteIn) -> dict:
    """Append one validated note after the latest durable sequence."""
    _require_chat()
    spec = _domain_spec("book")
    _require_domain_writable(spec)
    provider = _board_store_provider(spec)

    import secrets

    note_id = "book-note-" + secrets.token_hex(8)
    created_at = datetime.now(UTC).isoformat()
    appended: dict[str, Any] = {}

    def mutate(current, _cards):
        if current is None:
            raise KeyError(card_id)
        notes = _validated_book_notes(current)
        note = BookNoteRecord(
            note_id=note_id,
            sequence=len(notes) + 1,
            author=body.author,
            text=body.text,
            chapter=body.chapter,
            page=body.page,
            total_pages=body.total_pages,
            progress_percent=body.progress_percent,
            created_at=created_at,
        ).model_dump(mode="json", exclude_none=True)
        appended.update(note)
        replacement = {
            **current,
            "book_notes": [*notes, note],
            "updated_at": created_at,
        }
        position_values = {
            "current_chapter": body.chapter,
            "current_page": body.page,
            "total_pages": body.total_pages,
            "progress_percent": body.progress_percent,
        }
        if any(value is not None for value in position_values.values()):
            replacement.update({
                name: value for name, value in position_values.items()
                if value is not None
            })
            replacement["reading_position_updated_at"] = created_at
        _validated_book_location(replacement)
        return replacement

    try:
        provider.mutate_card_fields(card_id, mutate)
    except Exception as exc:
        _raise_book_mutation_error(exc)
    return {
        "status": "noted",
        "domain_id": "book",
        "card_id": card_id,
        "note": appended,
        "card": _public_book_card(_find_domain_card(provider, card_id)),
    }


@app.delete("/api/domain/book/card/{card_id}")
def archive_book_card(card_id: str) -> dict:
    """Archive a book without erasing its fields or event history."""
    _require_chat()
    spec = _domain_spec("book")
    _require_domain_writable(spec)
    provider = _board_store_provider(spec)
    result = _move_book_card(provider, spec, card_id, "Archived")
    if result["status"] == "moved":
        result["status"] = "archived"
    return result


def _linkedin_composer_accounts() -> list[dict[str, str]]:
    """Return content accounts from the validated committed contract."""
    path = CONFIGS_DIR / "content.yaml"
    if not path.is_file():
        raise HTTPException(
            status_code=503, detail=f"content.yaml not at {path}")
    from command_center.schemas.contracts import ContentConfig

    try:
        cfg = ContentConfig.model_validate(_read_yaml_file(path))
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"invalid content.yaml: {exc}") from exc
    return [
        {
            "id": account.board,
            "kind": account.author,
            "label": (
                f"Personal profile - {account.board}"
                if account.author == "member"
                else f"Organization page - {account.board}"
            ),
        }
        for account in cfg.accounts
    ]


@app.get("/api/domain/linkedin_post/composer")
def linkedin_post_composer() -> dict:
    """Data-derived accounts and canonical local preview limits."""
    from command_center.content.post_model import (
        DESKTOP_SEE_MORE_CHARS,
        LINKEDIN_MAX_CHARS,
        MOBILE_SEE_MORE_CHARS,
    )

    spec = _domain_spec("linkedin_post")
    blockers = _domain_write_blockers(spec)
    return {
        "accounts": _linkedin_composer_accounts(),
        "max_characters": LINKEDIN_MAX_CHARS,
        "desktop_fold_characters": DESKTOP_SEE_MORE_CHARS,
        "mobile_fold_characters": MOBILE_SEE_MORE_CHARS,
        "write_ready": CHAT_ENABLED and not blockers,
        "write_blockers": (
            blockers if CHAT_ENABLED
            else ["chat/writes not enabled in this deployment"]
        ),
    }


@app.post("/api/domain/linkedin_post/drafts", status_code=201)
def create_linkedin_post_draft(body: PostDraftIn) -> dict:
    """Create one real Draft card; never approve, schedule, or publish it."""
    _require_chat()
    spec = _domain_spec("linkedin_post")
    _require_domain_writable(spec)
    account = body.account.strip()
    accounts = {row["id"] for row in _linkedin_composer_accounts()}
    if account not in accounts:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{account!r} is not a configured content account; "
                f"choose from {sorted(accounts)}"
            ),
        )
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="post body is required")
    if body.scheduled_for is not None and body.scheduled_for.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail="scheduled_for must include an explicit timezone offset")

    import secrets
    from command_center.content.post_model import LinkedInPost

    post = LinkedInPost(author_name=account, body=text)
    warnings = [
        {"level": warning.level, "code": warning.code, "message": warning.message}
        for warning in post.lint()
    ]
    card_id = "post-" + secrets.token_hex(6)
    now = datetime.now(UTC).isoformat()
    fields = {
        "account": account,
        "hook": post.hook(),
        "body": text,
        "tags": [tag.strip() for tag in body.tags if tag.strip()],
        "source_ref": (body.source_ref or "cockpit/manual").strip(),
        "scheduled_for": (
            body.scheduled_for.isoformat()
            if body.scheduled_for is not None else None
        ),
        "approval_state": "Draft",
        "post_urn": None,
        "created_at": now,
        "char_count": post.char_count(),
        "lint": warnings,
    }
    provider = _board_store_provider(spec)
    provider.upsert_card(card_id, fields)
    event = emit_event(
        provider.log,
        action="add_mission_card",
        board_id=provider.board_id,
        card_id=card_id,
        source_surface="internal_ui",
        actor_type="human",
        status_after="Draft",
    )
    return {
        "status": "created",
        "domain_id": "linkedin_post",
        "card_id": card_id,
        "card": _find_domain_card(provider, card_id),
        "event": event.model_dump(mode="json"),
        "warnings": warnings,
    }


def _validation_blockers_detail(validation: dict) -> str:
    failed = [
        f"{c['label']} ({c['detail']})"
        for c in validation.get("checks", [])
        if not c["ok"] and c["level"] == "error"
    ]
    return (
        "packet validation failed — open Review Packet for details: "
        + "; ".join(failed))


# One completion at a time: two concurrent submits must not both finalize
# (duplicate emails/evidence). The second caller sees applied_at set and takes
# the idempotent path.
_job_finalize_lock = threading.Lock()


def _sync_completed_job_card(provider, card: dict) -> dict[str, Any]:
    """Finalize on completion: validate → mark submitted → email record →
    submission evidence. Both the Completed drag and the record-external-submission
    button land here BEFORE the governed event is emitted, so a blocked or
    failed finalize never logs a Completed move it did not make. A record that
    is already applied (e.g. finalized via `cc job-search finalize`) completes
    idempotently: the card syncs without a second submission or email."""
    app_id = _required_job_application_id(card, "move to Completed")
    from command_center.job_search.application_memory import load_application
    from command_center.job_search.finalize import (
        FinalizeBlocked,
        finalize_application,
    )

    _, root = _job_search_config_and_root()
    with _job_finalize_lock:
        _, existing = load_application(app_id, root=root)
        if existing.applied_at:
            record = existing.model_dump(mode="json")
            outcome: dict[str, Any] = {
                "already_submitted": True,
                "validation": None,
                "email": {
                    "status": "skipped",
                    "detail": "already submitted; the record email was handled "
                              "when the application was first finalized",
                },
                "submission_record_path": str(
                    root / "applications_active" / app_id / "submission_record.json"),
            }
        else:
            try:
                result = finalize_application(app_id, root=root)
            except FinalizeBlocked as exc:
                raise HTTPException(
                    status_code=409,
                    detail=_validation_blockers_detail(exc.validation)) from exc
            record = result["record"]
            outcome = {
                "already_submitted": False,
                "validation": result["validation"],
                "email": result["email"],
                "submission_record_path": result["submission_record_path"],
            }
    fields = _card_store_fields(card)
    fields.update({
        "application_status": record["status"],
        "application_stage": record["stage"],
        "applied_at": record["applied_at"],
        "last_seen_at": record["last_activity_at"],
        "retention_until": record["retention_until"],
        "next_action": (record.get("followup") or {}).get("next_action"),
        "completion_source": "cockpit_completed_lane",
        "review_state": record.get("review_state"),
        "revision": record.get("revision"),
        "generation_mode": str((record.get("generation") or {}).get("mode") or "unknown"),
        "email_record_status": outcome["email"].get("status"),
    })
    provider.upsert_card(str(card["card_id"]), fields)
    return {
        "application_id": app_id,
        "application_status": record["status"],
        "application_stage": record["stage"],
        "applied_at": record["applied_at"],
        "next_action": (record.get("followup") or {}).get("next_action"),
        **outcome,
    }


def _job_card_needs_packet(card: dict) -> bool:
    fields = _card_store_fields(card)
    return bool(fields.get("job_key")) and not (
        fields.get("application_id") or fields.get("materials_path"))


def _process_selected_job_cards() -> dict[str, Any]:
    from command_center.job_search.board import process_selected

    cfg, root = _job_search_config_and_root()
    result = process_selected(
        backend="internal",
        apply=True,
        root=root,
        cfg=cfg,
        env={
            "KANBAN_EVENT_LOG": str(KANBAN_EVENT_LOG),
            "KANBAN_BOARD_STORE": str(BOARD_STORE_DIR),
        },
        executor=os.environ.get("JOB_SEARCH_EXECUTOR", "codex"),
    )
    plans = [
        {
            "card_id": plan.get("card_id"),
            "job_key": plan.get("job_key"),
            "company": plan.get("company"),
            "role_title": plan.get("role_title"),
            "automation_class": plan.get("automation_class"),
            "source_column": plan.get("source_column"),
            "target_column": plan.get("target_column"),
            "application_id": plan.get("application_id"),
            "materials_path": plan.get("materials_path"),
            "would_submit": plan.get("would_submit"),
        }
        for plan in result.get("plans", [])
    ]
    return {
        "operation": "process_selected",
        "status": result.get("status"),
        "selected_count": result.get("selected_count", 0),
        "selected_limit": result.get("selected_limit"),
        "deferred_selected_count": result.get("deferred_selected_count", 0),
        "writes_performed": result.get("writes_performed", False),
        "plans": plans,
    }


class _JobPrepQueue:
    """Runs job-card packet preparation OFF the request path so moving a card to
    'Selected by Geoff' returns immediately instead of blocking on an LLM run.

    A single daemon worker drains requests. Rapid moves (or a bulk-select)
    coalesce into at most one pending re-run, so N moves do not spawn N runs;
    process_selected is idempotent (already-prepared cards are skipped), so one
    coalesced run still prepares every pending card. The run holds
    _job_finalize_lock so preparation never overlaps a Completed finalize.

    The worker never dies on a failed run: the error is captured and surfaced
    via /api/job-search/prep-status rather than swallowed or killing the queue.
    """

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._pending = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._runs_completed = 0
        self._requests_total = 0
        self._last_finished_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def _ensure_worker(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._loop, name="job-prep-worker", daemon=True)
            self._thread.start()

    def request(self) -> dict[str, Any]:
        with self._cv:
            self._pending = True
            self._requests_total += 1
            self._ensure_worker()
            self._cv.notify_all()
            snapshot = self._snapshot_locked()
        snapshot["operation"] = "process_selected_queued"
        return snapshot

    def status(self) -> dict[str, Any]:
        with self._cv:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, Any]:
        return {
            "pending": self._pending,
            "running": self._running,
            "runs_completed": self._runs_completed,
            "requests_total": self._requests_total,
            "last_finished_at": self._last_finished_at,
            "last_result": self._last_result,
            "last_error": self._last_error,
        }

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._pending:
                    self._cv.wait()
                self._pending = False
                self._running = True
            result: dict[str, Any] | None = None
            error: str | None = None
            try:
                with _job_finalize_lock:
                    result = _process_selected_job_cards()
            except Exception as exc:  # noqa: BLE001 - worker must not die
                error = repr(exc)
            with self._cv:
                self._running = False
                self._runs_completed += 1
                self._last_result = result
                self._last_error = error
                self._last_finished_at = datetime.now(UTC).isoformat()


_job_prep_queue = _JobPrepQueue()


def _record_job_rejection_from_card(
    card: dict, reason_code: str | None, reason_note: str | None,
) -> dict[str, Any] | None:
    """Record why a job card was rejected so the rejection report can suggest
    filter/scoring changes. A drag with no reason still logs one (as 'other')
    so the count is honest; the UI supplies a reason code when it can."""
    from command_center.job_search.rejections import record_rejection

    fields = _card_store_fields(card)
    job_key = str(fields.get("job_key") or card.get("card_id") or "").strip()
    if not job_key:
        return None
    _, root = _job_search_config_and_root()
    score = fields.get("fit_score")
    try:
        fit_score = int(score) if score not in (None, "") else None
    except (TypeError, ValueError):
        fit_score = None
    try:
        return record_rejection(
            root,
            job_key=job_key,
            reason_code=(reason_code or "other"),
            note=reason_note,
            card_id=str(card.get("card_id") or ""),
            company=fields.get("company") or card.get("company"),
            role_title=fields.get("role_title") or card.get("role_title"),
            location=fields.get("location"),
            remote_type=fields.get("remote_type"),
            fit_score=fit_score,
        )
    except ValueError:
        # unknown reason code from a client — fall back to 'other' rather than
        # 500 the move; the rejection is still captured
        return record_rejection(
            root, job_key=job_key, reason_code="other", note=reason_note,
            card_id=str(card.get("card_id") or ""),
            company=fields.get("company") or card.get("company"),
            role_title=fields.get("role_title") or card.get("role_title"),
            location=fields.get("location"),
            remote_type=fields.get("remote_type"), fit_score=fit_score)


def _note_type_moves_to_interviewing(note_type: str) -> bool:
    lowered = note_type.lower()
    return any(token in lowered for token in (
        "recruiter", "interview", "phone_screen", "onsite", "offer",
        "manager", "hiring",
    ))


@app.post("/api/domain/{domain_id}/move")
def domain_move(domain_id: str, body: DomainMoveIn) -> dict:
    """Move a typed domain card by emitting a governed kanban event.

    This is intentionally limited to `board_store` domains. Fixture and Ledger
    domains are read models here; a drag must never fabricate state or bypass
    the existing event log.
    """
    _require_chat()
    spec = _domain_spec(domain_id)
    _require_domain_writable(spec)
    # Books are a typed library, never a routable generic Work Graph board.
    # Take the exact-card path before the generic projection scan so one move
    # does not materialize every book field document.
    if domain_id == "book":
        provider = _board_store_provider(spec)
        return _move_book_card(provider, spec, body.card_id, body.status)
    routable_board = _routable_board_for_spec(spec)
    projected = next(
        (
            card for card in _domain_cards(spec)["cards"]
            if str(card.get("card_id")) == body.card_id
            and card.get("projection_source") == "work_graph"
        ),
        None,
    )
    if projected is not None:
        if projected.get("projection_conflict_with"):
            raise HTTPException(
                status_code=409,
                detail="this projection conflicts with an unrelated stored card; "
                       "resolve the provenance conflict before moving it",
            )
        if routable_board is None:
            raise HTTPException(
                status_code=409,
                detail="this board no longer has a reversible Work Graph status mapping",
            )
        previous = str(projected.get("status") or "Unstaged")
        if previous == body.status:
            return {
                "status": "unchanged", "domain_id": domain_id, "card": projected}
        _column_action(spec, body.status)
        allowed = _allowed_transitions(spec, previous)
        if body.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"cards move one step at a time: from {previous!r} the "
                       f"next steps are {allowed or ['(terminal)']}, "
                       f"not {body.status!r}",
            )
        reverse = {
            label: canonical
            for canonical, label in routable_board["status_mapping"].items()
        }
        canonical_status = reverse.get(body.status)
        if canonical_status is None:
            raise HTTPException(
                status_code=400,
                detail=f"lane {body.status!r} has no canonical Work Graph status",
            )
        service = _require_workgraph_write()
        service.set_status(str(projected["work_item_id"]), canonical_status)
        moved = next(
            card for card in _domain_cards(spec)["cards"]
            if card.get("work_item_id") == projected["work_item_id"]
            and not card.get("projection_conflict_with")
        )
        return {
            "status": "moved",
            "domain_id": domain_id,
            "card_id": body.card_id,
            "from_status": previous,
            "to_status": body.status,
            "event": {
                "action": "work_graph_status",
                "status_before": previous,
                "status_after": body.status,
                "source_surface": "internal_ui",
                "actor_type": "human",
            },
            "side_effect": None,
            "card": moved,
        }
    provider = _board_store_provider(spec)
    card = _find_domain_card(provider, body.card_id)
    previous = card.get("status")
    if previous == body.status:
        return {"status": "unchanged", "domain_id": domain_id, "card": card}
    # configured-column + wall checks first (400 for a bogus status), THEN
    # the one-step machine (409 for a real-but-skipped stage)
    action = _column_action(spec, body.status)
    allowed = _allowed_transitions(spec, previous)
    if body.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"cards move one step at a time: from {previous!r} the "
                   f"next steps are {allowed or ['(terminal)']}, "
                   f"not {body.status!r}")
    if domain_id in GRAND_TODO_DOMAIN_IDS:
        from command_center.cli.grand_todo_import import (
            PROFILES,
            GrandTodoImportError,
            move_grand_todo_card,
        )
        try:
            result = move_grand_todo_card(
                source_path=_grand_todo_source(domain_id),
                store_dir=BOARD_STORE_DIR,
                event_log_path=KANBAN_EVENT_LOG,
                card_id=body.card_id,
                status=body.status,
                expected_source_sha256=str(card.get("source_sha256") or "") or None,
                profile=PROFILES[domain_id],
            )
        except GrandTodoImportError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"domain_id": domain_id, **result}
    side_effect: dict[str, Any] | None = None
    if domain_id == "job_application" and body.status == "Completed":
        # Finalize BEFORE the governed event so a blocked or failed finalize
        # never logs a Completed move it did not make (409 carries the failed
        # validation checks; already-applied records complete idempotently).
        side_effect = _sync_completed_job_card(provider, card)
    event = emit_event(
        provider.log, action=action, board_id=provider.board_id,
        card_id=body.card_id, source_surface="internal_ui",
        actor_type="human", status_before=previous, status_after=body.status)
    if (
        domain_id == "job_application"
        and body.status in {"Selected by Geoff", "In Progress"}
        and _job_card_needs_packet(card)
    ):
        # Queue packet prep instead of running it inline: the move returns
        # immediately so Geoff can move through cards fast, and the background
        # worker prepares them. /api/job-search/prep-status reports progress.
        side_effect = _job_prep_queue.request()
    elif domain_id == "job_application" and body.status == "Rejected / Skip":
        rejection = _record_job_rejection_from_card(
            card, body.reason_code, body.reason_note)
        if rejection is not None:
            side_effect = {"operation": "rejection_recorded",
                           "reason_code": rejection["reason_code"]}
    elif domain_id == "linkedin_post":
        fields = _card_store_fields(card)
        fields["approval_state"] = body.status
        provider.upsert_card(body.card_id, fields)
    moved = _find_domain_card(provider, body.card_id)
    return {
        "status": "moved",
        "domain_id": domain_id,
        "card_id": body.card_id,
        "from_status": previous,
        "to_status": body.status,
        "event": event.model_dump(mode="json"),
        "side_effect": side_effect,
        "card": moved,
    }


@app.put("/api/domain/{domain_id}/card/{card_id}")
def edit_grand_todo(
    domain_id: str, card_id: str, body: GrandTodoEditIn,
) -> dict:
    """Edit one stable task block; source Markdown remains canonical."""
    if domain_id not in GRAND_TODO_DOMAIN_IDS:
        raise HTTPException(
            status_code=404,
            detail=f"domain {domain_id!r} has no canonical grand-todo editor",
        )
    _require_chat()
    spec = _domain_spec(domain_id)
    _require_domain_writable(spec)
    from command_center.cli.grand_todo_import import (
        PROFILES,
        GrandTodoImportError,
        edit_grand_todo_card,
    )
    try:
        return edit_grand_todo_card(
            source_path=_grand_todo_source(domain_id),
            store_dir=BOARD_STORE_DIR,
            event_log_path=KANBAN_EVENT_LOG,
            card_id=card_id,
            raw_markdown=body.raw_markdown,
            expected_source_sha256=body.expected_source_sha256,
            profile=PROFILES[domain_id],
        )
    except GrandTodoImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/domain/{domain_id}/card/{card_id}/note")
def domain_card_note(domain_id: str, card_id: str, body: DomainNoteIn) -> dict:
    """Append a job-card note into the application memory and refresh follow-ups."""
    _require_chat()
    spec = _domain_spec(domain_id)
    if domain_id != "job_application":
        raise HTTPException(
            status_code=400,
            detail="card notes are currently implemented only for job_application cards")
    _require_domain_writable(spec)
    provider = _board_store_provider(spec)
    card = _find_domain_card(provider, card_id)
    app_id = _required_job_application_id(card, "record an application note")
    note_type = body.type.strip() or "manual_note"
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", note_type):
        raise HTTPException(
            status_code=400,
            detail="note type must be a stable token ([A-Za-z0-9_:-]+)")
    content = body.text.strip()
    if not content:
        raise HTTPException(status_code=400, detail="note text is required")

    from command_center.job_search.application_memory import append_note_text

    _, root = _job_search_config_and_root()
    event = append_note_text(
        app_id, note_type, content, root=root,
        source=body.source.strip() or "cockpit",
        furthers_process=body.furthers_process)
    fields = _card_store_fields(card)
    fields.update({
        "next_action": event.get("action_needed"),
        "last_seen_at": str(event.get("ts") or "")[:10],
        "latest_communication": event.get("summary"),
        "latest_communication_type": note_type,
    })
    provider.upsert_card(card_id, fields)

    kanban_event = None
    if (body.furthers_process
            and _note_type_moves_to_interviewing(note_type)
            and card.get("status") != "Interviewing"):
        kanban_event = emit_event(
            provider.log, action="stage_card", board_id=provider.board_id,
            card_id=card_id, source_surface="internal_ui",
            actor_type="human", status_before=card.get("status"),
            status_after="Interviewing")

    return {
        "status": "noted",
        "domain_id": domain_id,
        "card_id": card_id,
        "application_id": app_id,
        "note": event,
        "event": kanban_event.model_dump(mode="json") if kanban_event else None,
        "card": _find_domain_card(provider, card_id),
        "progress": _domain_progress(spec, card_id),
    }


# ── Packet review: materials → notes/regenerate → record external submission ──
_PACKET_FILES = (
    ("resume", "generated_resume.md"),
    ("resume_ats", "resume_ats.txt"),
    ("cover_letter", "cover_letter.md"),
    ("recruiter_message", "recruiter_message.md"),
    ("application_answers", "application_answers.md"),
    ("answer_bank", "answer_bank.md"),
    ("followups", "followups.md"),
    ("manual_checklist", "manual_checklist.md"),
    ("resume_selection_report", "resume_selection_report.md"),
    ("recruiter_notes", "recruiter_notes.md"),
    ("review_notes", "review_notes.md"),
)


class PacketNotesIn(BaseModel):
    # notes may be empty when regenerate=true: "regenerate with the current
    # writer" without adding a review note
    notes: str = ""
    regenerate: bool = True


class PacketFileIn(BaseModel):
    file: str
    content: str


class PacketSubmitIn(BaseModel):
    confirm: bool = False


def _require_job_domain(domain_id: str) -> dict:
    spec = _domain_spec(domain_id)
    if domain_id != "job_application":
        raise HTTPException(
            status_code=400,
            detail="packet review is implemented only for job_application cards")
    return spec


def _job_packet_response(spec: dict, card: dict) -> dict:
    app_id = _required_job_application_id(card, "open the packet")
    from command_center.job_search.achievement_bank import ensure_bank
    from command_center.job_search.agent_writer import read_trace
    from command_center.job_search.application_memory import (
        load_application,
        read_job_description,
    )
    from command_center.job_search.packet_validation import validate_packet
    from command_center.job_search.record_email import email_config_status

    _, root = _job_search_config_and_root()
    try:
        app_dir, record = load_application(app_id, root=root)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"application {app_id!r} has no application.yml on disk "
                f"({exc}); the card references a packet that was purged or "
                "never created — re-run material preparation")) from exc
    files: dict[str, str | None] = {}
    for key, filename in _PACKET_FILES:
        path = app_dir / filename
        files[key] = path.read_text(encoding="utf-8") if path.is_file() else None
    try:
        files["job_description"] = read_job_description(app_dir) or None
    except (OSError, EOFError):
        # corrupt/truncated gzip — validation reports it as a failed check
        files["job_description"] = None
    bank = ensure_bank(root / "profile" / "achievement_bank.yml")
    submission_path = app_dir / "submission_record.json"
    return {
        "domain_id": spec.get("domain_id"),
        "card_id": str(card.get("card_id")),
        "application_id": app_id,
        "path": str(app_dir),
        "record": record.model_dump(mode="json"),
        "files": files,
        "agent_trace": read_trace(app_dir),
        "story": _job_card_story(spec, card, app_id, app_dir),
        "validation": validate_packet(app_dir, record, bank),
        "email": email_config_status(),
        "submission_record": (
            json.loads(submission_path.read_text(encoding="utf-8"))
            if submission_path.is_file() else None),
    }


def _job_card_story(spec: dict, card: dict, app_id: str, app_dir: Path) -> list[dict]:
    """The card's full story in linear order — every main moment as one compact
    row, with the long content (model output, submission evidence) attached as
    expandable detail: governed board moves, agent generation attempts, notes,
    manual edits, and the final submission record."""
    from command_center.job_search.agent_writer import read_trace

    entries: list[dict] = []
    card_id = str(card.get("card_id"))
    for e in EventLog(KANBAN_EVENT_LOG).read():
        if e.board_id == spec.get("board_id") and e.card_id == card_id:
            entries.append({
                "ts": str(e.created_at or ""),
                "kind": "board",
                "title": _event_headline(e),
                "summary": f"{e.actor_type or 'actor'} via {e.source_surface or 'surface'}",
                "detail": None,
            })
    comms_path = app_dir / "communications.jsonl"
    if comms_path.is_file():
        for line in comms_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            entries.append({
                "ts": str(row.get("ts") or ""),
                "kind": "note",
                "title": str(row.get("type") or "note").replace("_", " "),
                "summary": str(row.get("summary") or ""),
                "detail": None,
            })
    for t in read_trace(app_dir):
        ok = t.get("ok")
        claims = ", ".join(t.get("claim_ids") or [])
        problems = "; ".join(str(p) for p in (t.get("problems") or []))
        duration = t.get("duration_ms")
        summary_bits = [f"model {t.get('model')}"]
        if isinstance(duration, (int, float)):
            summary_bits.append(f"{duration / 1000:.0f}s")
        if claims:
            summary_bits.append(f"claims: {claims}")
        if t.get("error"):
            summary_bits.append(f"error: {t.get('error')}")
        elif problems:
            summary_bits.append(f"problems: {problems}")
        entries.append({
            "ts": str(t.get("ts") or ""),
            "kind": "agent",
            "title": (str(t.get("step", "generate")).replace("_", " ")
                      + f" — attempt {t.get('attempt')}"
                      + ("" if ok else " (failed)")),
            "summary": ", ".join(summary_bits),
            "detail": t.get("response") or t.get("error"),
        })
    answers_path = app_dir / "application_answers.md"
    if answers_path.is_file():
        answers_text = answers_path.read_text(encoding="utf-8",
                                              errors="replace")
        asked = answers_text.count("(asked in this posting)")
        entries.append({
            "ts": datetime.fromtimestamp(
                answers_path.stat().st_mtime, UTC).isoformat(),
            "kind": "answers",
            "title": "application answers prepared",
            "summary": (f"{asked} question(s) detected in this posting have "
                        "standing answers" if asked else
                        "standing answers rendered (none detected in this "
                        "posting)"),
            "detail": answers_text,
        })
    submission_path = app_dir / "submission_record.json"
    if submission_path.is_file():
        evidence = json.loads(submission_path.read_text(encoding="utf-8"))
        email = evidence.get("email") or {}
        entries.append({
            "ts": str(evidence.get("finalized_at") or ""),
            "kind": "submission",
            "title": "application finalized and recorded",
            "summary": f"email record: {email.get('status', 'unknown')}",
            "detail": json.dumps(evidence, indent=2, ensure_ascii=False),
        })
    entries.sort(key=lambda r: r["ts"])
    return entries


@app.get("/api/domain/{domain_id}/card/{card_id}/packet")
def domain_card_packet(domain_id: str, card_id: str) -> dict:
    """The complete application packet: record, every material file, the agent
    trace (full prompts + model outputs), validation, and email-record status."""
    spec = _require_job_domain(domain_id)
    provider = _board_store_provider(spec)
    card = _find_domain_card(provider, card_id)
    return _job_packet_response(spec, card)


@app.post("/api/domain/{domain_id}/card/{card_id}/packet/request-changes")
def domain_card_packet_request_changes(
    domain_id: str, card_id: str, body: PacketNotesIn,
) -> dict:
    """Geoff's 'not ready' action: record the notes, then regenerate the
    materials with the agent writer against ALL accumulated notes. If the
    writer fails, the notes stay recorded and the error is returned verbatim
    (review_state stays changes_requested — nothing is papered over)."""
    _require_chat()
    spec = _require_job_domain(domain_id)
    _require_domain_writable(spec)
    provider = _board_store_provider(spec)
    card = _find_domain_card(provider, card_id)
    app_id = _required_job_application_id(card, "request packet changes")
    notes = body.notes.strip()
    if not notes and not body.regenerate:
        raise HTTPException(
            status_code=400,
            detail="notes text is required (or set regenerate=true for a "
                   "plain regeneration with the current writer)")

    from command_center.job_search.agent_writer import AgentWriterError
    from command_center.job_search.application_memory import (
        load_application,
        regenerate_materials,
        request_changes,
    )

    _, root = _job_search_config_and_root()
    if notes:
        request_changes(app_id, notes, root=root, source="cockpit_packet_review")
    regenerate_error: str | None = None
    if body.regenerate:
        try:
            regenerate_materials(app_id, root=root)
        except (AgentWriterError, ValueError) as exc:
            regenerate_error = str(exc)
    _, record = load_application(app_id, root=root)
    fields = _card_store_fields(card)
    fields.update({
        "review_state": record.review_state,
        "revision": record.revision,
        "generation_mode": str(record.generation.get("mode") or "unknown"),
        "next_action": (
            f"Review regenerated materials (revision {record.revision})."
            if record.review_state == "ready_for_review"
            else "Notes recorded; regeneration pending — run request-changes "
                 "again or check the writer error."),
        "last_seen_at": record.last_activity_at,
    })
    provider.upsert_card(card_id, fields)
    return {
        # no-notes + failed writer recorded nothing and changed nothing —
        # saying "changes_requested" there would be a false status
        "status": ("regenerated" if body.regenerate and not regenerate_error
                   else "changes_requested" if notes
                   else "regenerate_failed"),
        "regenerate_error": regenerate_error,
        "domain_id": domain_id,
        "card_id": card_id,
        "application_id": app_id,
        "packet": _job_packet_response(spec, _find_domain_card(provider, card_id)),
        "progress": _domain_progress(spec, card_id),
    }


_EDITABLE_PACKET_FILES = {
    "resume": "generated_resume.md",
    "cover_letter": "cover_letter.md",
    "recruiter_message": "recruiter_message.md",
    "application_answers": "application_answers.md",
    "answer_bank": "answer_bank.md",
    "recruiter_notes": "recruiter_notes.md",
}


@app.put("/api/domain/{domain_id}/card/{card_id}/packet/file")
def domain_card_packet_file(
    domain_id: str, card_id: str, body: PacketFileIn,
) -> dict:
    """Geoff edits a material directly: the file is replaced, the edit is
    recorded as a manual_edit moment in the story (communications + generation
    provenance), and validation re-runs against the edited content."""
    _require_chat()
    spec = _require_job_domain(domain_id)
    _require_domain_writable(spec)
    provider = _board_store_provider(spec)
    card = _find_domain_card(provider, card_id)
    app_id = _required_job_application_id(card, "edit a packet file")
    filename = _EDITABLE_PACKET_FILES.get(body.file)
    if not filename:
        raise HTTPException(
            status_code=400,
            detail=f"file {body.file!r} is not editable here; choose from "
                   f"{sorted(_EDITABLE_PACKET_FILES)}")
    content = body.content.rstrip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail="content is required — an emptied material would fail "
                   "packet validation; use request-changes to rewrite it")

    from command_center.job_search.application_memory import (
        append_note_text,
        atomic_write_text,
        load_application,
        save_application,
    )

    _, root = _job_search_config_and_root()
    with application_memory_write_lock(root, app_id):
        app_dir, record = load_application(app_id, root=root)
        atomic_write_text(app_dir / filename, content + "\n")
        if body.file == "resume":
            # the plain-text ATS variant is derived from the resume — regenerate
            # on every resume edit so the two files cannot drift
            from command_center.job_search.agent_writer import resume_ats_text
            atomic_write_text(
                app_dir / "resume_ats.txt", resume_ats_text(content))
        generation = dict(record.generation)
        edits = list(generation.get("manual_edits") or [])
        edits.append({"file": body.file,
                      "ts": datetime.now(UTC).isoformat()})
        generation["manual_edits"] = edits
        record.generation = generation
        save_application(app_dir, record)
        append_note_text(
            app_id, "manual_edit",
            f"Geoff edited {body.file} in the packet review modal.",
            root=root, source="cockpit_packet_review")
    return {
        "status": "saved",
        "file": body.file,
        "domain_id": domain_id,
        "card_id": card_id,
        "application_id": app_id,
        "packet": _job_packet_response(spec, _find_domain_card(provider, card_id)),
        "progress": _domain_progress(spec, card_id),
    }


@app.post("/api/domain/{domain_id}/card/{card_id}/packet/submit")
def domain_card_packet_submit(
    domain_id: str, card_id: str, body: PacketSubmitIn,
) -> dict:
    """Record an external submission: the same governed Completed move as the drag, gated on
    packet validation, then finalize (mark submitted + email record + evidence).
    Geoff pressing this button IS the human approval — no bot self-approval
    path exists (WALL verbs still never reach the drawer)."""
    _require_chat()
    spec = _require_job_domain(domain_id)
    _require_domain_writable(spec)
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="submission requires confirm=true — review the packet first")
    provider = _board_store_provider(spec)
    card = _find_domain_card(provider, card_id)
    previous = card.get("status")
    if previous == "Completed":
        raise HTTPException(
            status_code=409, detail="card is already in Completed")
    if "Completed" not in _allowed_transitions(spec, previous):
        # the 3-gate flow: submit happens at "agent complete" (Needs Geoff),
        # never as a stage skip from earlier in the pipeline
        raise HTTPException(
            status_code=409,
            detail=f"submit happens from 'Needs Geoff' (agent complete); this "
                   f"card is in {previous!r} — move it one step at a time")
    _required_job_application_id(card, "submit the application")
    action = _column_action(spec, "Completed")
    # Finalize BEFORE the governed event (same invariant as the drag): a
    # blocked finalize 409s here with the failed checks and no event is logged.
    side_effect = _sync_completed_job_card(provider, card)
    event = emit_event(
        provider.log, action=action, board_id=provider.board_id,
        card_id=card_id, source_surface="internal_ui",
        actor_type="human", status_before=previous, status_after="Completed")
    return {
        "status": "submitted",
        "domain_id": domain_id,
        "card_id": card_id,
        "from_status": previous,
        "to_status": "Completed",
        "event": event.model_dump(mode="json"),
        "side_effect": side_effect,
        "card": _find_domain_card(provider, card_id),
        "progress": _domain_progress(spec, card_id),
    }


def _job_search_config_and_root():
    from command_center.job_search.config import data_root, load_config

    cfg = load_config()
    return cfg, data_root(cfg)


def _read_yaml_file(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml_file(path: Path, data: dict[str, Any]) -> None:
    _atomic_write_bytes(path, _yaml_bytes(data))


def _job_search_profile_settings_path() -> Path:
    _, root = _job_search_config_and_root()
    return root / "profile" / "search_settings.yml"


def _profile_yaml_lock(path: Path):
    return exclusive_write_lock(path.parent / f".{path.name}.write.lock")


def _job_search_profile_settings_lock():
    return _profile_yaml_lock(_job_search_profile_settings_path())


def _read_job_search_profile_settings() -> dict[str, Any]:
    path = _job_search_profile_settings_path()
    if not path.is_file():
        return {}
    return _read_yaml_file(path)


def _validate_job_search_profile_settings(
    override: dict[str, Any],
):
    from command_center.job_search.config import merge_profile_settings
    from command_center.job_search.schemas import JobSearchConfig

    base_path = CONFIGS_DIR / "job_search.yaml"
    if not base_path.is_file():
        raise HTTPException(status_code=503, detail=f"job_search.yaml not at {base_path}")
    base = _read_yaml_file(base_path)
    return JobSearchConfig.model_validate(merge_profile_settings(base, override))


def _write_job_search_profile_settings(override: dict[str, Any]) -> dict:
    cfg = _validate_job_search_profile_settings(override)
    target = _job_search_profile_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(target.parent, os.W_OK):
        raise HTTPException(
            status_code=503,
            detail=f"profile settings directory is not writable: {target.parent}")
    _write_yaml_file(target, override)
    return {
        "status": "updated",
        "source": str(target),
        "job_search": cfg.job_search.model_dump(mode="json"),
        "ranking": cfg.ranking.model_dump(mode="json"),
        "job_categories": [c.model_dump(mode="json") for c in cfg.job_categories],
        "locations": cfg.locations.model_dump(mode="json"),
        "languages": cfg.languages.model_dump(mode="json"),
        "company_targets": cfg.company_targets.model_dump(mode="json"),
        "retention": cfg.retention.model_dump(mode="json"),
    }


def _application_question_policy() -> tuple[dict[str, Any], Path]:
    cfg, root = _job_search_config_and_root()
    policy_path = root / "profile" / "application_question_policy.yml"
    if policy_path.is_file():
        return _read_yaml_file(policy_path), policy_path
    return cfg.application_questions.model_dump(mode="json"), CONFIGS_DIR / "job_search.yaml"


@app.get("/api/job-search/digest", response_model=JobSearchDigestOut)
def job_search_digest(response: Response) -> dict:
    """Read-only review list for Suggested Jobs and prepared Needs-Geoff cards."""
    _private_no_store(response)
    spec = _require_job_domain("job_application")
    from command_center.job_search.digest import build_digest_items

    items = build_digest_items(_domain_cards(spec)["cards"])
    counts = {
        "suggested_jobs": sum(
            item["column"] == "Suggested Jobs" for item in items
        ),
        "needs_geoff": sum(item["column"] == "Needs Geoff" for item in items),
        "total": len(items),
    }
    return {
        "items": items,
        "counts": counts,
        "generated_at": datetime.now(UTC),
    }


@app.get("/api/job-search/profile-controls")
def job_search_profile_controls() -> dict:
    """Profile/job-search controls surfaced for review before applications.

    Personal defaults live under data/job_search/profile. The endpoint reports
    the exact source files so a blank UI can never masquerade as missing policy.
    """
    cfg, root = _job_search_config_and_root()
    # same base + same override file the PUT endpoints write — the menu can
    # never show different values than the ones it just saved. Read-only
    # deployments without configs/job_search.yaml keep the resolved config.
    try:
        cfg = _validate_job_search_profile_settings(
            _read_job_search_profile_settings())
    except HTTPException:
        pass
    policy, policy_source = _application_question_policy()
    profile_dir = root / "profile"
    source_paths = {
        "application_question_policy": str(profile_dir / "application_question_policy.yml"),
        "search_settings": str(profile_dir / "search_settings.yml"),
        "job_targets": str(profile_dir / "job_targets.yml"),
        "resume_variants": str(profile_dir / "resume_variants.yml"),
        "writing_style": str(profile_dir / "writing_style.yml"),
        "claim_policy": str(profile_dir / "claim_policy.yml"),
        "manual_only_rules": str(profile_dir / "manual_only_rules.yml"),
        "fallback_config": str(CONFIGS_DIR / "job_search.yaml"),
    }
    return {
        "writable": CHAT_ENABLED and DOMAIN_CONFIG_WRITES,
        "write_gate": (
            "enabled" if CHAT_ENABLED and DOMAIN_CONFIG_WRITES else
            "read-only deployment; enable both chat and domain config writes "
            "for in-app profile edits"
        ),
        "application_questions": policy,
        "application_questions_source": str(policy_source),
        "source_paths": source_paths,
        "job_search": cfg.job_search.model_dump(mode="json"),
        "ranking": cfg.ranking.model_dump(mode="json"),
        "job_search_config_source": str(CONFIGS_DIR / "job_search.yaml"),
        "job_search_settings_source": str(profile_dir / "search_settings.yml"),
        "job_search_settings_writable": os.access(profile_dir, os.W_OK),
        "resume_variants": cfg.resume_variants,
        "job_categories": [c.model_dump(mode="json") for c in cfg.job_categories],
        "company_targets": cfg.company_targets.model_dump(mode="json"),
        "retention": cfg.retention.model_dump(mode="json"),
        "executor_fallback": cfg.executor_fallback.model_dump(mode="json"),
        "locations": cfg.locations.model_dump(mode="json"),
        "languages": cfg.languages.model_dump(mode="json"),
        "standing_answers": _standing_answers_block(root),
        "dag": _job_search_dag_block(cfg),
    }


def _standing_answers_block(root: Path) -> dict:
    from command_center.job_search.standing_answers import (
        load_standing_answers,
        standing_answers_path,
    )

    answers = load_standing_answers(root)
    return {
        "answers": answers,
        "source": str(standing_answers_path(root)),
        "coverage_note": (
            "a manual phrase listed in an entry's `covers` may be rendered into "
            "each packet's application_answers.md instead of blocking; topics "
            "listed in never_auto_answer always remain human-only"),
    }


def _job_search_dag_block(cfg) -> dict:
    """The daily pipeline as seen from the settings menu: the schedule and
    target numbers it runs with (all adjustable via the runtime PUT), plus
    last-run evidence from the digest file."""
    # the digest lands next to the kanban event log (host ./generated,
    # container /snapshot) — resolve through the same mount
    digest_path = Path(KANBAN_EVENT_LOG).parent / Path(
        cfg.job_search.digest_path).name
    last_digest = None
    if digest_path.is_file():
        last_digest = datetime.fromtimestamp(
            digest_path.stat().st_mtime, UTC).isoformat()
    return {
        "dag_id": "job_search_daily",
        "schedule": (f"daily at {cfg.job_search.daily_run_time} "
                     f"{cfg.job_search.timezone}"),
        "daily_targets": {
            "suggested": cfg.job_search.max_suggested_jobs_per_day,
            "bot_possible": cfg.job_search.max_bot_possible_suggestions_per_day,
            "manual_required": cfg.job_search.max_manual_required_suggestions_per_day,
            "selected": cfg.job_search.max_selected_jobs_per_day,
        },
        "targets_adjustable_via": "/api/job-search/profile-controls/runtime",
        "digest_path": str(digest_path),
        "last_digest_at": last_digest,
        "note": ("discovery tags derive from the job categories above — "
                 "editing category keywords changes what the DAG searches"),
    }


@app.put("/api/job-search/profile-controls/runtime")
def update_job_search_runtime(body: JobSearchRuntimeSettingsIn) -> dict:
    _require_profile_writable()
    with _job_search_profile_settings_lock():
        override = _read_job_search_profile_settings()
        runtime = override.setdefault("job_search", {})
        for key, value in body.model_dump(exclude_none=True).items():
            runtime[key] = value
        return _write_job_search_profile_settings(override)


@app.put("/api/job-search/profile-controls/company-targets")
def update_job_search_company_targets(
    body: JobSearchCompanyTargetsSettingsIn,
) -> dict:
    """Replace the four typed company-target lists; no free-form keys exist."""
    _require_profile_writable()
    with _job_search_profile_settings_lock():
        override = _read_job_search_profile_settings()
        override["company_targets"] = body.model_dump(mode="json")
        return _write_profile_override_or_400(override, "company targets")


@app.put("/api/job-search/profile-controls/retention")
def update_job_search_retention(body: JobSearchRetentionSettingsIn) -> dict:
    """Set the resolved rich-record lifetime; purge behavior is not writable."""
    _require_profile_writable()
    with _job_search_profile_settings_lock():
        override = _read_job_search_profile_settings()
        override.setdefault("retention", {})[
            "rich_application_cache_days"
        ] = body.rich_application_cache_days
        return _write_profile_override_or_400(override, "retention")


def _write_profile_override_or_400(override: dict[str, Any], what: str) -> dict:
    """Persist a profile-settings override, converting a contract violation
    (e.g. mode=regions with no region/country) into a 400 instead of a 500."""
    from pydantic import ValidationError

    try:
        return _write_job_search_profile_settings(override)
    except ValidationError as exc:
        errors = exc.errors()
        msg = errors[0].get("msg") if errors else f"invalid {what} settings"
        raise HTTPException(status_code=400, detail=str(msg)) from exc


@app.put("/api/job-search/profile-controls/locations")
def update_job_search_locations(body: JobSearchLocationsSettingsIn) -> dict:
    """Update the location + work-arrangement filter (the countries/states
    checklist and remote/hybrid/onsite + full-time toggles). Partial update:
    only provided fields change. Validated against the merged config, so an
    empty region list under mode=regions (with no country) returns 400."""
    _require_profile_writable()
    with _job_search_profile_settings_lock():
        override = _read_job_search_profile_settings()
        section = override.setdefault("locations", {})
        for key, value in body.model_dump(exclude_none=True).items():
            section[key] = value
        return _write_profile_override_or_400(override, "locations")


@app.put("/api/job-search/profile-controls/languages")
def update_job_search_languages(body: JobSearchLanguagesSettingsIn) -> dict:
    """Update the spoken-languages filter. A posting requiring a language not
    listed here is hard-excluded from suggestions."""
    _require_profile_writable()
    with _job_search_profile_settings_lock():
        override = _read_job_search_profile_settings()
        section = override.setdefault("languages", {})
        for key, value in body.model_dump(exclude_none=True).items():
            section[key] = value
        return _write_profile_override_or_400(override, "languages")


@app.put("/api/job-search/profile-controls/category/{category_id}")
def update_job_search_category(category_id: str,
                               body: JobSearchCategorySettingsIn) -> dict:
    """Upsert a search category: patch an existing one, or CREATE a new one
    when the id is unknown (new categories need resume_variant + keywords so
    scoring and discovery know what to do with them)."""
    _require_profile_writable()
    with _job_search_profile_settings_lock():
        return _update_job_search_category_locked(category_id, body)


def _update_job_search_category_locked(
    category_id: str, body: JobSearchCategorySettingsIn,
) -> dict:
    category_id = category_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", category_id):
        raise HTTPException(status_code=400, detail="invalid category id")
    override = _read_job_search_profile_settings()
    cfg = _validate_job_search_profile_settings(override)
    existing_ids = {category.id for category in cfg.job_categories}
    creating = category_id not in existing_ids
    if creating:
        if not body.resume_variant or not body.keywords:
            raise HTTPException(
                status_code=400,
                detail=f"category {category_id!r} does not exist yet — to "
                       "create it, provide resume_variant and keywords")
        if body.resume_variant not in cfg.resume_variants:
            raise HTTPException(
                status_code=400,
                detail=f"unknown resume_variant {body.resume_variant!r}; "
                       f"pick from {sorted(cfg.resume_variants)}")
    patches = override.setdefault("job_categories", [])
    patch = next((row for row in patches if row.get("id") == category_id), None)
    if patch is None:
        patch = {"id": category_id}
        patches.append(patch)
    patch.pop("remove", None)   # re-adding a previously removed category
    if body.resume_variant is not None:
        patch["resume_variant"] = body.resume_variant
    if body.role_focus is not None:
        patch["role_focus"] = body.role_focus
    elif creating:
        patch["role_focus"] = "secondary"
    if body.keywords is not None:
        patch["keywords"] = [kw.strip() for kw in body.keywords if kw.strip()]
    return _write_job_search_profile_settings(override)


@app.delete("/api/job-search/profile-controls/category/{category_id}")
def remove_job_search_category(category_id: str) -> dict:
    """Remove a search category (recorded as a remove patch in
    search_settings.yml, so a base-config category stays removed and can be
    re-added later from the same menu)."""
    _require_profile_writable()
    with _job_search_profile_settings_lock():
        return _remove_job_search_category_locked(category_id)


def _remove_job_search_category_locked(category_id: str) -> dict:
    category_id = category_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", category_id):
        raise HTTPException(status_code=400, detail="invalid category id")
    override = _read_job_search_profile_settings()
    cfg = _validate_job_search_profile_settings(override)
    if category_id not in {category.id for category in cfg.job_categories}:
        raise HTTPException(
            status_code=404, detail=f"unknown job category {category_id!r}")
    if len(cfg.job_categories) <= 1:
        raise HTTPException(
            status_code=400,
            detail="refusing to remove the last search category — the daily "
                   "search would have nothing to look for")
    patches = override.setdefault("job_categories", [])
    patches[:] = [row for row in patches if row.get("id") != category_id]
    patches.append({"id": category_id, "remove": True})
    return _write_job_search_profile_settings(override)


@app.put("/api/job-search/profile-controls/standing-answer")
def update_standing_answer(body: StandingAnswerIn) -> dict:
    """Upsert one standing answer. An edit takes effect on the NEXT packet
    preparation/regeneration; classification of new discoveries uses it
    immediately."""
    _require_profile_writable()
    topic = body.topic.strip()
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", topic):
        raise HTTPException(
            status_code=400,
            detail="standing answer topic must be a stable token "
                   "([A-Za-z0-9_:-]+)")
    if not body.answer.strip():
        raise HTTPException(
            status_code=400,
            detail="answer text is required — delete the entry from "
                   "profile/standing_answers.yml to stop covering a question")
    cfg, _ = _job_search_config_and_root()
    policy_text = "\n".join([
        topic,
        body.answer,
        body.question or "",
        *(body.covers or []),
    ])
    if any(len(value) > 500 for value in (body.covers or [])):
        raise HTTPException(
            status_code=400, detail="standing-answer coverage phrases are too long")
    if _sensitive_memory_text(policy_text, cfg):
        raise HTTPException(
            status_code=400,
            detail="protected or credential-like values cannot be stored as "
                   "reusable standing answers",
        )
    from command_center.job_search.standing_answers import (
        load_standing_answers,
        save_standing_answers,
        standing_answers_path,
    )

    _, root = _job_search_config_and_root()
    target = standing_answers_path(root)
    with _profile_yaml_lock(target):
        answers = load_standing_answers(root)
        row = next((a for a in answers if a.get("topic") == topic), None)
        if row is None:
            if not body.question:
                raise HTTPException(
                    status_code=400,
                    detail=f"topic {topic!r} does not exist yet — provide "
                           "`question` text to create it")
            row = {"topic": topic}
            answers.append(row)
        row["answer"] = body.answer.strip()
        if body.question is not None:
            row["question"] = body.question.strip()
        if body.covers is not None:
            row["covers"] = [c.strip() for c in body.covers if c.strip()]
        source = save_standing_answers(root, answers)
    return {
        "status": "updated",
        "topic": topic,
        "source": str(source),
        "standing_answers": _standing_answers_block(root),
    }


def _job_search_memory():
    from command_center.job_search.memory import JobSearchMemory

    _, root = _job_search_config_and_root()
    return JobSearchMemory(root)


def _private_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _canonical_uuid_or_400(value: str, noun: str) -> str:
    from uuid import UUID

    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"{noun} must be a canonical UUID") from exc
    canonical = str(parsed)
    if value.lower() != canonical:
        raise HTTPException(
            status_code=400, detail=f"{noun} must be a canonical UUID")
    return canonical


def _sensitive_memory_text(text: str, cfg) -> bool:
    from command_center.job_search.automation_policy import (
        is_never_auto_question,
    )

    return is_never_auto_question(
        text, cfg.application_questions.never_auto_answer)


def _job_card_application_and_category(card_id: str):
    """Resolve capture provenance from the canonical card and application.

    The caller cannot nominate either the application or category. Existing
    cards use resume-variant ids as their category field; those ids are
    validated against the current resolved category config before storage.
    """
    from command_center.job_search.application_memory import load_application

    spec = _require_job_domain("job_application")
    provider = _board_store_provider(spec)
    card = _find_domain_card(provider, card_id)
    application_id = _required_job_application_id(
        card, "add an application question")
    cfg, root = _job_search_config_and_root()
    try:
        _, record = load_application(application_id, root=root)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail="the card's application memory is unavailable; "
                   "no question was stored",
        ) from exc

    configured = {category.id: category for category in cfg.job_categories}
    candidates = [
        str(card.get("category") or "").strip(),
        str(record.category or "").strip(),
        str(record.resume_variant or "").strip(),
    ]
    category_id = next(
        (candidate for candidate in candidates if candidate in configured), None)
    if category_id is None:
        matching = {
            category.id
            for category in cfg.job_categories
            if category.resume_variant in candidates
        }
        if len(matching) == 1:
            category_id = next(iter(matching))
    if category_id is None:
        raise HTTPException(
            status_code=409,
            detail="the card's job category is not in the current config; "
                   "no question was stored",
        )
    return cfg, card, application_id, category_id


@app.get("/api/job-search/relationships")
def job_search_relationships(
    response: Response, active: bool | None = None,
) -> dict:
    _require_chat()
    _private_no_store(response)
    return {"relationships": _job_search_memory().list_relationships(active)}


@app.put("/api/job-search/relationships/{relationship_id}")
def put_job_search_relationship(
    relationship_id: str, body: JobSearchRelationshipIn, response: Response,
) -> dict:
    _private_no_store(response)
    _require_profile_writable()
    relationship_id = _canonical_uuid_or_400(
        relationship_id, "relationship id")
    try:
        status, relationship = _job_search_memory().put_relationship(
            relationship_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="invalid relationship fields") from exc
    return {"status": status, "relationship": relationship}


@app.get("/api/job-search/question-library")
def job_search_question_library(
    response: Response, category_id: str | None = None,
) -> dict:
    _require_chat()
    _private_no_store(response)
    if category_id is not None:
        category_id = category_id.strip()
        if not category_id:
            raise HTTPException(status_code=400, detail="category id is required")
    return {
        "questions": _job_search_memory().list_questions(category_id),
    }


@app.post("/api/job-search/question-library")
def record_job_search_question(
    body: JobSearchQuestionIn, response: Response,
) -> dict:
    _private_no_store(response)
    _require_profile_writable()
    cfg, _, application_id, category_id = (
        _job_card_application_and_category(body.card_id))
    if _sensitive_memory_text(body.question, cfg):
        raise HTTPException(
            status_code=400,
            detail="sensitive application questions cannot be stored in the "
                   "reusable question library",
        )
    try:
        status, question, occurrence = _job_search_memory().record_question(
            application_id=application_id,
            card_id=body.card_id,
            category_id=category_id,
            question=body.question,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="question text is required") from exc
    return {
        "status": status,
        "question": question,
        "occurrence": occurrence,
    }


@app.put(
    "/api/job-search/question-library/{question_id}/candidate/{category_id}")
def put_job_search_candidate_answer(
    question_id: str,
    category_id: str,
    body: JobSearchCandidateAnswerIn,
    response: Response,
) -> dict:
    _private_no_store(response)
    _require_profile_writable()
    question_id = _canonical_uuid_or_400(question_id, "question id")
    category_id = category_id.strip()
    cfg, _ = _job_search_config_and_root()
    memory = _job_search_memory()
    configured = {category.id for category in cfg.job_categories}
    try:
        observed = memory.question_categories(question_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="question not found") from exc
    if category_id not in configured and category_id not in observed:
        raise HTTPException(
            status_code=400,
            detail="category is neither currently configured nor observed for "
                   "this question",
        )
    if _sensitive_memory_text(body.answer, cfg):
        raise HTTPException(
            status_code=400,
            detail="sensitive candidate answers cannot be stored in the "
                   "reusable question library",
        )
    try:
        status, candidate = memory.put_candidate_answer(
            question_id, category_id, body.answer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="question not found") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="candidate answer is required") from exc
    return {"status": status, "candidate_answer": candidate}


@app.get("/api/job-search/cards/{card_id}/outreach")
def job_search_card_outreach(card_id: str, response: Response) -> dict:
    _require_chat()
    _private_no_store(response)
    spec = _require_job_domain("job_application")
    provider = _board_store_provider(spec)
    card = _find_domain_card(provider, card_id)
    application_id = str(card.get("application_id") or "").strip() or None
    company = str(card.get("company") or "").strip()
    role_title = str(card.get("role_title") or "").strip()
    relationships = _job_search_memory().active_relationships_for_company(
        company)
    # Outreach is least-privilege even inside the private console: notes and
    # provenance/timestamps stay in the relationship editor and never enter
    # this job-card response or any generated draft.
    public_relationships = [
        {
            key: relationship[key]
            for key in (
                "relationship_id", "name", "company", "role_title",
                "relationship_kind", "linkedin_url", "active",
            )
        }
        for relationship in relationships
    ]
    drafts: list[dict[str, str]] = []
    for relationship in relationships:
        name = relationship["name"]
        relationship_id = relationship["relationship_id"]
        drafts.extend([
            {
                "relationship_id": relationship_id,
                "kind": "known_contact_note",
                "subject": "",
                "body": (
                    f"Hi {name} — I'm exploring the {role_title} opportunity "
                    f"at {company}. Since we know each other, would you be open "
                    "to sharing any context on the team or role? No pressure "
                    "either way."
                ),
            },
            {
                "relationship_id": relationship_id,
                "kind": "follow_up",
                "subject": "",
                "body": (
                    f"Hi {name} — just following up on the {role_title} role at "
                    f"{company}. I know schedules get busy, so no worries if "
                    "you don't have context to share."
                ),
            },
        ])
    return {
        "draft_only": True,
        "card_id": card_id,
        "application_id": application_id,
        "company": company,
        "role_title": role_title,
        "known_contacts": public_relationships,
        "drafts": drafts,
        "recommended_role_searches": [
            f"{company} recruiter",
            f"{company} talent acquisition",
            f"{company} hiring manager {role_title}",
        ],
    }


@app.post("/api/job-search/reclassify")
def reclassify_job_applications() -> dict:
    """Re-run automation classification for every prepared (not-yet-applied)
    job card against the CURRENT standing answers and manual rules, refresh
    each application_answers.md, and re-sort the board card between the Bot and
    Manual boards. Idempotent and repeatable — run it after editing answers or
    search rules so existing cards catch up. Applied cards are left untouched."""
    _require_chat()
    from command_center.job_search.application_memory import (
        reclassify_application,
        reclassify_suggestion,
    )

    spec = _require_job_domain("job_application")
    provider = _board_store_provider(spec)
    _, root = _job_search_config_and_root()

    changes: list[dict] = []
    errors: list[dict] = []
    counts = {"bot_possible": 0, "manual_required": 0, "prepare_only": 0,
              "skip": 0, "unclassified": 0}
    for card in provider.list_cards():
        app_id = str(card.get("application_id") or "").strip()
        if app_id:
            try:
                result = reclassify_application(app_id, root=root)
            except FileNotFoundError:
                errors.append({"card_id": card.get("card_id"),
                               "application_id": app_id,
                               "error": "no application on disk"})
                continue
        else:
            # SUGGESTED card (no packet): re-classify from the cached posting
            # so cards published before the standing answers existed catch up.
            job_key = str(card.get("job_key") or "").strip()
            before = str(card.get("automation_class") or "unclassified")
            result = reclassify_suggestion(job_key, before, root=root) if job_key else None
            if result is None:
                counts["unclassified"] += 1
                continue
        after = result["after"]
        counts[after] = counts.get(after, 0) + 1
        # push the fresh class + reason onto the board card so the Bot/Manual
        # split and the card badge reflect the new decision
        fields = _card_store_fields(card)
        fields["automation_class"] = after
        fields["manual_reason"] = result.get("manual_reason")
        if result.get("auto_answered"):
            fields["auto_answered"] = "; ".join(result["auto_answered"])
        provider.upsert_card(str(card["card_id"]), fields)
        if result["changed"]:
            changes.append({
                "card_id": card.get("card_id"),
                "application_id": app_id or None,
                "company": card.get("company"),
                "role_title": card.get("role_title"),
                "before": result["before"], "after": after,
                "auto_answered": result.get("auto_answered", []),
            })
    return {
        "status": "reclassified",
        "cards_scanned": sum(counts.values()) + len(errors),
        "counts": counts,
        "changed": changes,
        "errors": errors,
    }


class BulkSelectIn(BaseModel):
    # which automation class to bulk-select from Suggested Jobs
    automation_class: str = "bot_possible"
    target: str = "Selected by Geoff"


@app.post("/api/job-search/bulk-select")
def bulk_select_suggested(body: BulkSelectIn) -> dict:
    """'Add all': move EVERY Suggested Jobs card of one automation class to the
    next lane in one click, each as its own governed event. Default moves all
    bot-possible suggestions to 'Selected by Geoff' so Geoff can queue the whole
    bot board at once instead of one card at a time."""
    _require_chat()
    spec = _require_job_domain("job_application")
    _require_domain_writable(spec)
    provider = _board_store_provider(spec)
    target = body.target
    # the move must be a legal one-step transition from Suggested Jobs
    if target not in _allowed_transitions(spec, "Suggested Jobs"):
        raise HTTPException(
            status_code=400,
            detail=f"{target!r} is not a legal next lane from Suggested Jobs; "
                   f"choose from {_allowed_transitions(spec, 'Suggested Jobs')}")
    action = _column_action(spec, target)
    moved: list[dict] = []
    for card in provider.list_cards():
        if (card.get("status") != "Suggested Jobs"
                or str(card.get("automation_class")) != body.automation_class):
            continue
        card_id = str(card["card_id"])
        event = emit_event(
            provider.log, action=action, board_id=provider.board_id,
            card_id=card_id, source_surface="internal_ui", actor_type="human",
            status_before="Suggested Jobs", status_after=target)
        fields = _card_store_fields(card)
        provider.upsert_card(card_id, fields, status=target)
        moved.append({"card_id": card_id, "company": card.get("company"),
                      "role_title": card.get("role_title"),
                      "event_id": event.event_id})
    # Queue background packet prep for the whole batch (respects the daily
    # selected limit; the rest stay queued for the next run).
    prep = None
    if moved and target in {"Selected by Geoff", "In Progress"}:
        prep = _job_prep_queue.request()
    return {
        "status": "bulk_selected",
        "automation_class": body.automation_class,
        "target": target,
        "moved_count": len(moved),
        "moved": moved,
        "prep": prep,
    }


@app.get("/api/job-search/prep-status")
def job_search_prep_status() -> dict:
    """Background packet-prep queue status: whether a run is pending/running and
    the last run's result/error. The UI polls this to badge 'preparing...' cards
    and to surface a failed prep instead of leaving a card silently stuck."""
    return {"operation": "prep_status", **_job_prep_queue.status()}


@app.get("/api/job-search/rejections-report")
def job_search_rejections_report() -> dict:
    """Aggregate recorded rejections into concrete filter/scoring suggestions."""
    from command_center.job_search.rejections import rejection_report

    cfg, root = _job_search_config_and_root()
    return rejection_report(root=root, cfg=cfg)


@app.put("/api/job-search/profile-controls/draft-default")
def update_draft_default(body: DraftDefaultIn) -> dict:
    _require_profile_writable()
    key = body.key.strip()
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", key):
        raise HTTPException(
            status_code=400,
            detail="draft default key must be a stable token "
                   "([A-Za-z0-9_:-]+)")
    from command_center.job_search.schemas import ApplicationQuestions
    _, root = _job_search_config_and_root()
    target = root / "profile" / "application_question_policy.yml"
    with _profile_yaml_lock(target):
        policy, source = _application_question_policy()
        policy.setdefault("draft_defaults", {})
        policy["draft_defaults"][key] = body.value
        ApplicationQuestions.model_validate(policy)
        _write_yaml_file(target, policy)
    return {
        "status": "updated",
        "key": key,
        "source_before": str(source),
        "source": str(target),
        "application_questions": policy,
    }


@app.get("/api/board-registry")
def board_registry() -> dict:
    path = _kanban_boards_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"kanban_boards.yaml not at {path}")
    data = _read_board_registry_data()
    boards = []
    for board in data.get("boards", []):
        boards.append({
            "board_id": board.get("board_id"),
            "provider": board.get("provider"),
            "execution_scope": board.get("execution_scope", "repository"),
            "workspace_ref": board.get("workspace_ref"),
            "board_ref": board.get("board_ref"),
            "repo_ids": board.get("repo_ids", []),
            "status_mapping": board.get("status_mapping", {}),
            "required_fields": board.get("required_fields", []),
            "allowed_agent_verbs": board.get("allowed_agent_verbs", []),
            "forbidden_agent_verbs": board.get("forbidden_agent_verbs", []),
            "blockers": board.get("blockers", []),
        })
    return {
        "schema_version": data.get("schema_version"),
        "config_path": str(path),
        "config_writable": os.access(path, os.W_OK),
        "boards": boards,
    }


def _registered_repos(*, strict: bool = False) -> list[dict]:
    """Validated registered repos for board tabs and scoped-chat targets.

    Chat remains fail-soft for backward compatibility. Catalog callers use
    ``strict=True`` so an invalid manifest is visible instead of looking like
    a legitimately empty repository registry.
    """
    try:
        from command_center.schemas.contracts import AutonomyConfig

        path = CONFIGS_DIR / "autonomy.yaml"
        data = _read_yaml_file(path)
        config = AutonomyConfig.model_validate(data)
        return [
            {
                "repo_id": repo.repo_id,
                "remote_url": repo.remote_url,
                "kanban_board_id": repo.kanban_board_id,
                "risk_ceiling": repo.risk_ceiling.value,
                "autonomous_edits_enabled": repo.autonomous_edits_enabled,
                "research_capabilities": list(repo.research_capabilities),
                "scan_reason": (
                    "Check this repository against its declared capabilities: "
                    + "; ".join(repo.research_capabilities)
                    if repo.research_capabilities else
                    "Check this registered work repository for code-health drift, "
                    "standards gaps, and improvement opportunities."
                ),
            }
            for repo in config.repo_manifests
        ]
    except Exception as exc:
        if strict:
            raise HTTPException(
                status_code=503,
                detail=f"registered repository catalog unavailable: {exc}",
            ) from exc
        return []


@app.get("/api/repos")
def registered_repositories() -> dict:
    """Validated read-only catalog used by repository-driven board tabs."""
    return {
        "repositories": _registered_repos(strict=True),
        "source": str(CONFIGS_DIR / "autonomy.yaml"),
    }


def _repo_chat_context(repo_id: str) -> dict:
    """Full context for a repo-scoped chat: the registered manifest, a live
    (read-only) repo-verify pass, and any Ledger missions already running
    against this repo. Verify/missions failures degrade to a partial payload
    with the failure named — a Ledger outage or an unresolved local-path env
    var should never turn into a broken chat entry point."""
    data = _read_yaml_file(CONFIGS_DIR / "autonomy.yaml")
    manifest = next(
        (r for r in (data.get("repo_manifests") or []) if r.get("repo_id") == repo_id),
        None,
    )
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"repo {repo_id!r} is not registered")
    try:
        from command_center.channels.core import env as gateway_env
        from command_center.cli.repo_registry import run_repo_verify
        verify = run_repo_verify(
            repo_id=repo_id, env=gateway_env(),
            config_path=CONFIGS_DIR / "autonomy.yaml", root=CONFIGS_DIR.parent)
    except Exception as exc:
        verify = {"status": "unknown", "blockers": [f"verify_failed: {exc}"]}
    recent_missions: list[dict] = []
    try:
        data_missions = missions()
        recent_missions = [
            {"id": c.get("id"), "action": c.get("action"), "status": col["name"],
             "risk": c.get("risk"), "created_at": c.get("created_at")}
            for col in data_missions["columns"] for c in col["cards"]
            if c.get("repo") == repo_id
        ][-5:]
    except Exception as exc:
        recent_missions = [{"unavailable": str(exc)}]
    return {
        "repo_id": repo_id,
        "manifest": manifest,
        "verify": verify,
        "recent_missions": recent_missions,
    }


def _chat_prompt_for_repo(context: dict) -> str:
    manifest = context["manifest"]
    verify = context.get("verify") or {}
    recent_missions = [m for m in context.get("recent_missions") or [] if "unavailable" not in m]
    lines = [
        "Use the REPO CONTEXT below as the authoritative context for this turn — "
        "it is read live from configs/autonomy.yaml plus a live, read-only "
        "repo-verify pass, not a guess.",
        "",
        "REPO CONTEXT",
        f"- repo_id: {manifest.get('repo_id')}",
        f"- remote_url: {manifest.get('remote_url')}",
        f"- default_branch: {manifest.get('default_branch')}",
        f"- branch_write_policy: {manifest.get('branch_write_policy')}",
        f"- execution_mode: {manifest.get('execution_mode')}",
        f"- risk_ceiling: {manifest.get('risk_ceiling')}",
        f"- kanban_board_id: {manifest.get('kanban_board_id')}",
        f"- ci_commands: {', '.join(manifest.get('ci_commands') or []) or 'none declared'}",
        f"- autonomous_edits_enabled: {manifest.get('autonomous_edits_enabled')}",
        f"- autonomy_gate_status: {verify.get('status', 'unknown')}",
    ]
    blockers = verify.get("blockers") or manifest.get("blockers") or []
    lines.append(f"- open blockers: {', '.join(blockers) if blockers else 'none'}")
    if recent_missions:
        lines.append("")
        lines.append("RECENT MISSIONS AGAINST THIS REPO")
        for m in recent_missions:
            lines.append(
                f"- {m.get('created_at', '?')}: [{m.get('status')}] "
                f"{m.get('action')} (risk={m.get('risk')})"
            )
    lines.extend([
        "",
        "Answer with:",
        "1. What this repo is set up for and what's actually enabled right now.",
        "2. Anything blocking autonomous edits, if that's relevant to what I'm asking.",
        "3. The next safe action.",
    ])
    return "\n".join(lines)


@app.get("/api/chat/repo-context/{repo_id}")
def chat_repo_context(repo_id: str) -> dict:
    """Rich repo-scoped chat-starter context — the deep-context counterpart to
    domain card progress prompts, for the "registered repo" chat entry point."""
    _require_chat()
    context = _repo_chat_context(repo_id)
    context["chat_prompt"] = _chat_prompt_for_repo(context)
    return context


class AgentSessionSpecListItem(BaseModel):
    name: str
    harness: str
    capability_profile: str
    effort: str | None
    mode: str
    instructions_source: Literal["inline", "file"]
    policy_refs: list[str]


class AgentSessionSpecListErrorDetail(BaseModel):
    code: Literal["invalid_agent_session_spec"] = "invalid_agent_session_spec"
    message: str = "This agent-session spec could not be loaded or validated."


class AgentSessionSpecListError(BaseModel):
    name: str
    error: AgentSessionSpecListErrorDetail


AgentSessionSpecListEntry = AgentSessionSpecListItem | AgentSessionSpecListError


@app.get(
    "/api/agent-session-specs",
    response_model=list[AgentSessionSpecListEntry],
)
def agent_session_specs() -> list[AgentSessionSpecListEntry]:
    """List validated, redacted agent-session specs for display-only clients.

    The response deliberately omits instruction content and file paths. AGT-10's
    future allocator emission seam is a validated ``AgentSessionSpec`` YAML in
    ``CONFIGS_DIR / "agent_sessions"``; allocator output will therefore appear
    through this same read contract without a separate mutation API.
    """
    directory = CONFIGS_DIR / "agent_sessions"
    if not directory.is_dir():
        return []

    entries: list[AgentSessionSpecListEntry] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            spec, _instructions = spec_bridge.load_spec(
                path.stem, directory=directory)
        except Exception:
            # Validation errors can contain the rejected YAML input. Keep the
            # public error stable and intentionally discard those details so a
            # malformed file cannot turn this read endpoint into a secret leak.
            entries.append(AgentSessionSpecListError(
                name=path.stem,
                error=AgentSessionSpecListErrorDetail(),
            ))
            continue
        entries.append(AgentSessionSpecListItem(
            name=spec.name,
            harness=spec.harness.value,
            capability_profile=spec.capability_profile.value,
            effort=spec.effort.value if spec.effort is not None else None,
            mode=spec.mode,
            instructions_source="inline" if spec.instructions is not None else "file",
            policy_refs=spec.policy_refs,
        ))
    return entries


@app.get("/api/chat/runtime")
def chat_runtime() -> dict:
    """What the cockpit chat actually uses: ONE harness (GatewayCore), THREE lanes.
    LOCAL (default): every `roles` entry routes through the one LiteLLM gateway
    to Ollama — free, tool-integrated, board/memory-aware. FRONTIER (opt-in,
    paid): `frontier_models` lists the budgeted OpenRouter escalation lane
    (configs/frontier-router-{providers,budgets}.yaml) — plain conversation
    only (no tools, no board/memory context leaves the machine), selectable
    only once an operator sets budgets.default.enabled=true AND the provider
    key. LOCAL FRONTIER (opt-in, experimental, free): `local_frontier_models`
    lists loopback-only disk-streamed engines (colibrì today —
    configs/local-frontier-providers.yaml) — same "no tools, no board/memory"
    discipline as the paid frontier lane, but nothing leaves the machine and
    there is no $ cost, only a (potentially very long) wall-clock one.
    `executors` (Claude Code / Codex CLI) are a FOURTH, distinct thing:
    agentic coding harnesses with their own runtime model catalogs and
    subscription/OAuth login, not GatewayCore chat models. They appear in the
    cockpit's Assistant selector, never in GatewayCore's model picker.
    Chat-gated like every /api/chat* route."""
    _require_chat()
    lanes = models()
    chat_role = next((r for r in lanes["roles"] if r["role"] == "chat"), None)
    from command_center.channels.frontier_client import available_frontier_models
    from command_center.channels.local_frontier_client import available_local_frontier_models
    return {
        "enabled": CHAT_ENABLED,
        "harness": "GatewayCore",
        "transport_surface": "app",
        "model_gateway": "LiteLLM",
        "chat_role": chat_role,
        "roles": lanes["roles"],
        "executors": lanes["executors"],
        "executor_note": (
            "Claude Code and Codex CLI are coding runtimes, not GatewayCore "
            "chat roles. Choose them from the Assistant selector for a direct "
            "read-only agent session; their model/effort picker comes from the "
            "selected runtime's own catalog. Mission tracking is optional and "
            "does not grant writes."
        ),
        "frontier_models": available_frontier_models(),
        "frontier_note": (
            "Paid escalation lane for open-weight frontier models too large "
            "for local VRAM (GLM-5.2 / DeepSeek V4 Pro / Kimi K2.6 — the top "
            "3 open-weight models on Artificial Analysis's July 2026 index). "
            "Off by default; enabling it is a deliberate operator decision: "
            "set OPENROUTER_API_KEY, flip "
            "configs/frontier-router-budgets.yaml default.enabled to true, "
            "then run `make frontier-router-egress-check`. A frontier turn "
            "never carries tools, board state, or memory to the provider."
        ),
        "local_frontier_models": available_local_frontier_models(),
        "local_frontier_note": (
            "Experimental, disabled-by-default LOCAL lane for open-weight models too "
            "large for VRAM but small enough to disk-stream on this machine (colibrì / "
            "GLM-5.2 744B today). Free, but self-reported at 0.05-1.06 tokens/sec — a "
            "reply can take minutes. Never carries tools, board state, or memory (same "
            "discipline as the frontier lane); the engine itself rejects tool schemas. "
            "Off by default; enabling it means building the engine, downloading its "
            "~370GB weights, starting its server, then flipping "
            "configs/local-frontier-providers.yaml enabled: true — see docs/MASTER.md "
            "\"Local frontier lane (colibrì)\"."
        ),
        "stream_endpoint": "/api/chat/stream",
        "action_endpoint": "/api/action",
        "activity_endpoint": "/api/activity",
        "conversations_endpoint": "/api/chat/conversations",
        "repos": _registered_repos(),
        "provider_note": (
            "The LOCAL lane (roles above) is the only tool-integrated, "
            "board-aware chat surface, and it stays cloud-free by design "
            "(forbidden-provider scan). The FRONTIER lane (frontier_models "
            "above) is the sanctioned path to a paid model — a separate, "
            "budgeted, redacted escalation, never a change to the local "
            "lane's roles. The LOCAL FRONTIER lane (local_frontier_models "
            "above) is a third, free-but-experimental option for models too "
            "large for VRAM — loopback-only, never a change to the local "
            "lane's roles."
        ),
        "chat_memory_note": (
            "Thread shortcuts sync across devices; full turn transcripts live "
            "in the flight recorder and are browsable under All chats."
        ),
    }


class RepoRegisterIn(BaseModel):
    repo_id: str
    local_path: str
    remote_url: str
    kanban_board: str
    apply: bool = False


def _require_repo_registry_writable() -> None:
    """Same discipline as the domain-schema editor: chat alone previews a
    registration (writes nothing); committing it to configs/autonomy.yaml
    additionally requires the operator's KANBAN_UI_DOMAIN_CONFIG_WRITES=1 opt-in
    and a writable file."""
    _require_chat()
    if not DOMAIN_CONFIG_WRITES:
        raise HTTPException(
            status_code=503,
            detail="repo registry writes disabled; set KANBAN_UI_DOMAIN_CONFIG_WRITES=1")
    path = CONFIGS_DIR / "autonomy.yaml"
    if not os.access(path, os.W_OK):
        raise HTTPException(status_code=503, detail=f"autonomy config is not writable: {path}")


@app.post("/api/repos/register")
def register_repo(body: RepoRegisterIn) -> dict:
    """Register a new work repo from the cockpit — mirrors `cc repo-register`.
    apply=false (the default) only validates and previews the manifest block,
    writing nothing; apply=true commits it to configs/autonomy.yaml and
    requires the same write-gate as the domain-schema editor. A committed
    manifest always starts with autonomous_edits_enabled=false — `cc
    repo-verify` / `cc repo-enable-autonomy` remain separate, human-run gates,
    never flipped by this endpoint."""
    _require_chat()
    if body.apply:
        _require_repo_registry_writable()
    from command_center.cli.repo_registry import run_repo_register
    try:
        result = run_repo_register(
            repo_id=body.repo_id.strip(),
            local_path=body.local_path.strip(),
            remote_url=body.remote_url.strip(),
            kanban_board=body.kanban_board.strip(),
            apply=body.apply,
            config_path=CONFIGS_DIR / "autonomy.yaml",
            root=CONFIGS_DIR.parent,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"repo registration failed: {exc}") from exc
    return result


def _transcript_storage() -> dict:
    """What the server retains for chat: compact thread metadata always; full
    per-turn transcripts (the GatewayCore flight recorder) when enabled."""
    from command_center.channels.transcript import (
        transcript_dir,
        transcripts_enabled,
        write_failure_count,
    )

    enabled = transcripts_enabled()
    return {
        "storage": ("server_metadata_plus_transcripts" if enabled
                    else "server_metadata_only"),
        "transcripts": {
            "enabled": enabled,
            "dir": str(transcript_dir()),
            "endpoint": "/api/chat/threads/{conversation_id}/transcript",
            # fail-open recording is silent by design; nonzero here means
            # turns were dropped (disk/permissions) and the story has gaps
            "write_failures": write_failure_count(),
        },
    }


@app.get("/api/chat/threads")
def chat_threads() -> dict:
    _require_chat()
    return {
        "threads": _read_chat_threads(),
        "source": str(CHAT_THREADS_FILE),
        "writable": os.access(CHAT_THREADS_FILE.parent, os.W_OK),
        **_transcript_storage(),
    }


@app.post("/api/chat/threads")
def save_chat_thread(body: ChatThreadIn) -> dict:
    _require_chat()
    thread = _upsert_chat_thread(body)
    return {
        "thread": thread,
        "threads": _read_chat_threads(),
        "source": str(CHAT_THREADS_FILE),
        **_transcript_storage(),
    }


@app.delete("/api/chat/threads/{conversation_id}")
def delete_chat_conversation(conversation_id: str) -> dict:
    """Clear ONE conversation's chat history: the thread shortcut and the
    flight-recorder transcript file. Chat hygiene only — the governed kanban
    event log (card/board history) is a different record and is untouched;
    this can never delete a card, board, or mission."""
    _require_chat()
    from command_center.channels.transcript import transcript_path

    threads = [row for row in _read_chat_threads()
               if row.get("conversation_id") != conversation_id]
    _write_chat_threads(threads)
    removed_transcript = False
    try:
        path = transcript_path(conversation_id)
        if path.is_file():
            path.unlink()
            removed_transcript = True
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"could not remove transcript: {exc}") from exc
    return {
        "status": "deleted",
        "conversation_id": conversation_id,
        "transcript_removed": removed_transcript,
        "threads": threads,
    }


@app.get("/api/chat/conversations")
def chat_conversations(limit: int = 200) -> dict:
    """Every conversation the flight recorder has seen, across ALL surfaces
    (app/Discord/CLI/...), merged with the shared thread shortcuts — the
    review index: pick any conversation, read its full story."""
    _require_chat()
    from command_center.channels.transcript import (
        read_transcript,
        transcript_dir,
    )

    by_id: dict[str, dict] = {}
    tdir = transcript_dir()
    for path in (sorted(tdir.glob("*.jsonl")) if tdir.is_dir() else []):
        turns = [t for t in read_transcript(path.stem)
                 if "conversation_id" in t]
        if not turns:
            continue
        last = turns[-1]
        cid = str(last.get("conversation_id"))
        by_id[cid] = {
            "conversation_id": cid,
            "turns": len(turns),
            "last_ts": str(last.get("ts") or ""),
            "surfaces": sorted({str(t.get("surface") or "?") for t in turns}),
            "last_user_text": str(last.get("user_text") or "")[:160],
            "title": None,
        }
    for row in _read_chat_threads():
        cid = row["conversation_id"]
        entry = by_id.setdefault(cid, {
            "conversation_id": cid, "turns": 0, "last_ts": "",
            "surfaces": [],
            "last_user_text": str(row.get("last_prompt") or "")[:160],
            "title": None,
        })
        entry["title"] = row.get("title")
        entry["last_ts"] = max(entry["last_ts"],
                               str(row.get("updated_at") or ""))
    rows = sorted(by_id.values(), key=lambda r: r["last_ts"], reverse=True)
    return {"conversations": rows[:max(1, limit)], "total": len(rows),
            **_transcript_storage()}


def _conversation_card_story(conversation_id: str) -> list[dict]:
    """Card-scoped chats (ids like 'job_application:job_x') carry the card's
    board/agent history into the chat story, so the full story is never empty
    for work the system already did. Fail-soft: any gap -> fewer rows, never
    a broken chat."""
    if ":" not in conversation_id:
        return []
    domain_id, card_id = conversation_id.split(":", 1)
    try:
        spec = _domain_spec(domain_id)
    except Exception:
        return []
    # jobs: the full packet story (board moves + notes + agent attempts +
    # submission evidence) — the same builder the packet modal uses
    try:
        provider = _board_store_provider(spec)
        card = _find_domain_card(provider, card_id)
        app_id = str(card.get("application_id") or "")
        if app_id:
            from command_center.job_search.application_memory import (
                load_application,
            )
            _, root = _job_search_config_and_root()
            app_dir, _record = load_application(app_id, root=root)
            return _job_card_story(spec, card, app_id, app_dir)
    except Exception:
        pass
    # any other domain: the governed board moves recorded for this card
    entries: list[dict] = []
    try:
        for e in EventLog(KANBAN_EVENT_LOG).read():
            if e.board_id == spec.get("board_id") and e.card_id == card_id:
                entries.append({
                    "ts": str(e.created_at or ""),
                    "kind": "board",
                    "title": _event_headline(e),
                    "summary": (f"{e.actor_type or 'actor'} via "
                                f"{e.source_surface or 'surface'}"),
                    "detail": None,
                })
    except Exception:
        return []
    entries.sort(key=lambda r: r["ts"])
    return entries


@app.get("/api/chat/threads/{conversation_id}/transcript")
def chat_thread_transcript(
    conversation_id: str, limit: int = 100, offset: int = 0,
) -> dict:
    """The full story of one conversation, straight from the flight recorder:
    every turn with its injected context blocks, FULL tool args/results, and
    the final answer (the SSE stream truncates; this endpoint never does).
    Pages from the newest end: default the last `limit` turns; `offset` skips
    that many newest turns (page back through a long-running thread)."""
    _require_chat()
    from command_center.channels.transcript import (
        read_transcript,
        transcript_path,
        transcripts_enabled,
    )

    all_turns = read_transcript(conversation_id)
    end = max(0, len(all_turns) - max(0, offset))
    start = max(0, end - max(1, limit))
    turns = all_turns[start:end]
    return {
        "conversation_id": conversation_id,
        "turns": turns,
        "turn_count": len(turns),
        "total_turns": len(all_turns),
        "offset": offset,
        # card-scoped chats also get the card's board/agent history, so the
        # story is populated even before the first chat turn
        "card_story": _conversation_card_story(conversation_id),
        "source": str(transcript_path(conversation_id)),
        "recording_enabled": transcripts_enabled(),
    }


def _validated_model(model: str) -> str:
    if model.startswith(_FRONTIER_PREFIX):
        from command_center.channels.frontier_client import available_frontier_models
        frontier_id = model[len(_FRONTIER_PREFIX):]
        options = {r["model_id"]: r for r in available_frontier_models()}
        row = options.get(frontier_id)
        if row is None:
            raise HTTPException(
                status_code=400,
                detail=f"unknown frontier model {frontier_id!r}; pick from "
                       f"{sorted(options)}")
        if not row["selectable"]:
            reason = ("the frontier-router lane is disabled "
                      "(configs/frontier-router-budgets.yaml default.enabled=false)"
                      if not row["lane_enabled"] else
                      "no provider API key is set for this model")
            raise HTTPException(
                status_code=503,
                detail=f"frontier model {frontier_id!r} is not enabled yet: {reason}")
        return model
    if model.startswith(_LOCAL_FRONTIER_PREFIX):
        from command_center.channels.local_frontier_client import available_local_frontier_models
        local_frontier_id = model[len(_LOCAL_FRONTIER_PREFIX):]
        options = {r["model_id"]: r for r in available_local_frontier_models()}
        row = options.get(local_frontier_id)
        if row is None:
            raise HTTPException(
                status_code=400,
                detail=f"unknown local-frontier model {local_frontier_id!r}; pick from "
                       f"{sorted(options)}")
        if not row["selectable"]:
            reason = ("the local-frontier lane is disabled "
                      "(configs/local-frontier-providers.yaml enabled=false)"
                      if not row["lane_enabled"] else
                      f"server health check returned {row['health']!r} — is it running?")
            raise HTTPException(
                status_code=503,
                detail=f"local-frontier model {local_frontier_id!r} is not ready: {reason}")
        return model
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
    # thread metadata keeps a 2000-char preview; the full prompt still reaches
    # the model and the flight recorder (an untruncated text here would fail
    # ChatThreadIn validation and 500 a turn that already ran)
    _upsert_chat_thread(ChatThreadIn(
        conversation_id=body.conversation_id,
        last_prompt=body.text[:2000],
        model=body.model,
    ))
    return {"reply": reply, "model": body.model}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn) -> StreamingResponse:
    """Same turn, streamed live (SSE): each round / tool call / tool result / final
    answer as it happens — 'watch what the LLM is doing now'."""
    _require_chat()
    core = _get_core(_validated_model(body.model))
    # 2000-char preview only — a longer paste (a job description) must not
    # 500 the stream before it starts; the model gets the full text below
    _upsert_chat_thread(ChatThreadIn(
        conversation_id=body.conversation_id,
        last_prompt=body.text[:2000],
        model=body.model,
    ))

    async def gen():
        async for ev in core.run_turn_events(body.conversation_id, body.text):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── Agent sessions (Claude Agent / Codex Agent) — proxied to the host worker ──
# A SEPARATE execution path from the chat lane above: no GatewayCore object is
# ever constructed here, no agent message is ever forwarded to /api/chat/stream,
# and the worker's own event vocabulary (session_started/tool_requested/
# approval_required/...) is relayed as-is, never translated into a fabricated
# chat turn. See WORKLOG.md "Agent-session chat integration" for the full
# design; this is the cockpit-side half of "Browser -> Cockpit proxy -> Host
# worker -> AgentSessionService -> harness".

class AgentSessionCreateIn(BaseModel):
    harness_id: str = "fake"
    conversation_id: str
    repo_id: str
    mode: str
    provider_profile: str = "default"
    model: str | None = None
    effort: str | None = None
    context_mode: str | None = None
    permission_profile: str = "read_only"


class AgentMessageIn(BaseModel):
    prompt: str


class AgentApprovalIn(BaseModel):
    approved: bool
    reason: str = ""


class AgentPromoteIn(BaseModel):
    """'Track as mission' — the OPTIONAL governance wrapper for an existing chat.
    summary becomes the mission's action line; nothing here grants writes."""
    summary: str = ""


class AgentHandoffIn(BaseModel):
    """Build a BOUNDED hand-off packet from a session for the assistant taking
    over (Claude ⇄ Codex ⇄ OpenRouter). No writes; returns a briefing prompt."""
    to_harness: str
    goal: str | None = None
    open_questions: list[str] = Field(default_factory=list)


class ChatPromoteIn(BaseModel):
    """'Track as mission' for a GatewayCore conversation (no agent session).
    Same inert tracking contract; nothing here grants writes."""
    conversation_id: str
    summary: str = ""
    repo: str = ""


# ── Usage & Limits routes (read-only; in-process UsageService) ────────────────
# NOTE: the literal /api/model-usage/* paths are declared BEFORE the
# /api/model-usage/{runtime_id} catch-all so FastAPI's in-order matching does
# not treat "collector-health"/"top-drivers"/"refresh" as a runtime_id.
def _resolved_usage_window(value: str) -> dict:
    from command_center.usage.portfolio import resolve_usage_window

    try:
        return resolve_usage_window(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/model-usage")
def model_usage(window: str = "week") -> list:
    """One status row per runtime (availability + every live bucket + rolled
    usage + honest staleness)."""
    from command_center.usage import cockpit_views as cv
    selected = _resolved_usage_window(window)
    return cv.usage_overview(_require_usage(), selected["start_at"])


@app.get("/api/model-usage/collector-health")
def model_usage_collector_health() -> list:
    """Durable checkpoint per registered collector — polling cleanly / failing
    (with the real error) / never ran."""
    service = _require_usage()
    if USAGE_LEDGER and AGENT_SESSIONS_ENABLED:
        return _call_worker(_require_agent_sessions().usage_collector_health)
    from command_center.usage import cockpit_views as cv
    return cv.collector_health(service, [cid for _, cid in _usage_collectors])


@app.get("/api/model-usage/top-drivers")
def model_usage_top_drivers(runtime_id: str, dimension: str = "mission",
                            metric: str = "total_tokens", limit: int = 10,
                            window: str = "week") -> dict:
    """"What used the most?" for a runtime, from recorded driver facts."""
    service = _require_usage()
    from command_center.usage import cockpit_views as cv
    selected = _resolved_usage_window(window)
    try:
        return cv.top_drivers(service, runtime_id=runtime_id, dimension=dimension,
                              metric=metric, limit=limit,
                              after_iso=selected["start_at"])
    except ValueError as exc:            # unknown dimension/metric
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/model-usage/recent-activity")
def model_usage_recent_activity(runtime_id: str, limit: int = 8,
                                window: str = "week") -> dict:
    """Recent sanitized coding-agent usage and evidence-derived KPIs."""
    from command_center.usage import cockpit_views as cv
    selected = _resolved_usage_window(window)
    result = cv.recent_activity(
        _require_usage(), runtime_id=runtime_id, limit=limit,
        after_iso=selected["start_at"])
    result["window"] = selected
    return result


@app.get("/api/model-usage/portfolio")
def model_usage_portfolio(window: str = "week") -> dict:
    """Sanitized model-level usage across local and OpenRouter chat lanes."""
    _require_usage()
    _resolved_usage_window(window)
    return _model_usage_portfolio(window)


@app.post("/api/model-usage/refresh")
async def model_usage_refresh() -> dict:
    """Run every registered collector once (durable tracked path). With no
    collectors registered this is a no-op that honestly reports 0 — it never
    fabricates data."""
    service = _require_usage()
    if USAGE_LEDGER and AGENT_SESSIONS_ENABLED:
        return await asyncio.to_thread(
            _call_worker, _require_agent_sessions().refresh_usage)
    from command_center.usage import cockpit_views as cv
    return await cv.refresh(service, _usage_collectors)


@app.get("/api/model-usage/{runtime_id}")
def model_usage_runtime(runtime_id: str, window: str = "week") -> dict:
    """Full status for one runtime (UNKNOWN + no buckets if never observed —
    never an error, never fabricated)."""
    selected = _resolved_usage_window(window)
    return _require_usage().runtime_status(
        runtime_id, selected["start_at"]).to_dict()


@app.get("/api/model-limits")
def model_limits() -> list:
    """Every live limit bucket across all runtimes, each tagged with its
    runtime's availability + staleness. Provider quota and internal budget stay
    distinct rows (scope), never merged."""
    from command_center.usage import cockpit_views as cv
    return cv.limits_overview(_require_usage())


@app.get("/api/model-alerts")
def model_alerts(runtime_id: str | None = None) -> list:
    """Deduplicated usage/limit/availability alerts."""
    from command_center.usage import cockpit_views as cv
    return cv.alerts_view(_require_usage(), runtime_id)


@app.get("/api/agent-harnesses")
def agent_harnesses() -> list:
    client = _require_agent_sessions()
    harnesses = _call_worker(client.list_harnesses)
    if not FAKE_AGENT_ENABLED:
        harnesses = [h for h in harnesses if h.get("harness_id") != "fake"]
    # enrich each harness with its live Usage & Limits status (availability +
    # buckets + rolled usage) when the usage layer is enabled, so the picker can
    # badge a runtime honestly (near-limit / exhausted / stale) — never a
    # fabricated number. runtime_id == harness_id for agent lanes.
    if USAGE_ENABLED:
        from command_center.usage import cockpit_views as cv
        statuses = {s["runtime_id"]: s for s in cv.usage_overview(_get_usage_service())}
        for h in harnesses:
            st = statuses.get(h.get("harness_id"))
            if st is not None:
                h["usage_summary"] = st
        for h in harnesses:
            h["models_endpoint"] = f"/api/agent-harnesses/{h.get('harness_id')}/models"
    return harnesses


@app.get("/api/agent-harnesses/{harness_id}/models")
def agent_harness_models(harness_id: str) -> dict:
    """Runtime-discovered model+effort catalog for the picker (proxied to the
    worker, which asks the live harness)."""
    client = _require_agent_sessions()
    return _call_worker(client.list_models, harness_id)


@app.get("/api/assistants")
def assistants_catalog() -> dict:
    """Read-only Assistant Catalog: ONE normalized list joining GatewayCore
    (completion) + the agent harnesses (Claude Code / Codex) + the Auto
    dispatcher, so the UI stops conflating a workspace, a runtime, and a model.
    Growth OS/boards/repos are CONTEXT, not assistants (see context_note). Never
    503s on a disabled/down lane — it lists it unavailable with a grounded reason
    (so the catalog survives an unreachable worker)."""
    from command_center.assistants import (
        build_assistant_catalog,
        declared_harness_descriptors,
    )
    runtime: dict = {"enabled": CHAT_ENABLED}
    try:
        runtime["roles"] = models().get("roles", [])
    except Exception as exc:          # noqa: BLE001 — degrade gateway, don't 503
        runtime["roles"] = []
        runtime["error"] = str(getattr(exc, "detail", exc))
    probes = None
    worker_error: str | None = None
    if AGENT_SESSIONS_ENABLED:
        try:
            client = _require_agent_sessions()
            probes = _call_worker(client.list_harnesses)
            if not FAKE_AGENT_ENABLED:
                probes = [p for p in probes if p.get("harness_id") != "fake"]
        except HTTPException as exc:      # worker unreachable / disabled path
            worker_error = str(exc.detail)
        except Exception as exc:          # noqa: BLE001 — surface as grounded reason
            worker_error = str(exc)
    return build_assistant_catalog(
        runtime=runtime,
        descriptors=declared_harness_descriptors(),
        probes=probes,
        agent_sessions_enabled=AGENT_SESSIONS_ENABLED,
        worker_error=worker_error).model_dump()


@app.get("/api/assistant-routing")
def assistant_routing() -> dict:
    """The task-category -> Assistant ROLES view: the validated
    configs/assistant-routing.yaml policy joined with the live Assistant
    Catalog's availability. Read-only and preview-only by contract (v1
    admits no dispatch mode) — the human clicks the assistant picker;
    nothing routes silently. Design: docs/architecture/
    task-assistant-routing.md."""
    import yaml as _yaml

    from command_center.schemas import CONFIG_CONTRACTS
    path = CONFIGS_DIR / "assistant-routing.yaml"
    if not path.is_file():
        raise HTTPException(
            status_code=503,
            detail="configs/assistant-routing.yaml is missing — the roles "
            "policy ships with the repo; restore it (never inferred)")
    try:
        contract = CONFIG_CONTRACTS["configs/assistant-routing.yaml"]
        policy = contract(**(_yaml.safe_load(
            path.read_text(encoding="utf-8")) or {}))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"assistant-routing.yaml failed validation: {exc}") from exc
    catalog = assistants_catalog()
    by_id = {a.get("assistant_id"): a for a in catalog.get("assistants", [])}
    categories = []
    for name, category in policy.categories.items():
        candidates = []
        for cand in sorted(category.candidates, key=lambda c: c.preference):
            live = by_id.get(cand.assistant_id)
            candidates.append({
                "assistant_id": cand.assistant_id,
                "preference": cand.preference,
                "display_name": (live or {}).get(
                    "display_name", cand.assistant_id),
                "availability": (live or {}).get("availability", "unknown"),
                "unavailable_reason": (live or {}).get("unavailable_reason"),
                "in_catalog": live is not None,
            })
        categories.append({
            "category_id": name,
            "capability_profile": category.capability_profile,
            "risk_ceiling": str(category.risk_ceiling.value
                                if hasattr(category.risk_ceiling, "value")
                                else category.risk_ceiling),
            "candidates": candidates,
        })
    return {"enabled": policy.enabled, "default_mode": policy.default_mode,
            "config_path": "configs/assistant-routing.yaml",
            "categories": categories}


@app.get("/api/agent-sessions")
def list_agent_sessions(conversation_id: str | None = None,
                        repo_id: str | None = None) -> list:
    """Recovers durable sessions by conversation_id/repo_id — lets the cockpit
    (or another device) find an in-progress agent session without relying
    exclusively on local browser storage."""
    client = _require_agent_sessions()
    return _call_worker(client.list_sessions, conversation_id=conversation_id,
                        repo_id=repo_id)


@app.post("/api/agent-sessions")
def create_agent_session(body: AgentSessionCreateIn) -> dict:
    client = _require_agent_sessions()
    if body.harness_id == "fake" and not FAKE_AGENT_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Fake Agent is disabled in this deployment (set "
                   "KANBAN_UI_FAKE_AGENT_ENABLED=1 for development use)")
    rec = _call_worker(client.create_session, body.model_dump())
    if isinstance(rec, dict) and rec.get("session_id"):
        _session_harness[rec["session_id"]] = body.harness_id   # for the usage tee
    return rec


@app.get("/api/agent-sessions/{session_id}")
def get_agent_session(session_id: str) -> dict:
    client = _require_agent_sessions()
    return _call_worker(client.get_session, session_id)


@app.post("/api/agent-sessions/{session_id}/messages", status_code=202)
def send_agent_message(session_id: str, body: AgentMessageIn) -> dict:
    """202 Accepted — the worker runs the turn as a background task and this
    call returns immediately (see worker_app.py's async execution-model
    correction). The browser gets the resulting events over the SSE stream
    below, not from this response body."""
    client = _require_agent_sessions()
    return _call_worker(client.send_message, session_id, body.prompt)


@app.get("/api/agent-sessions/{session_id}/events")
def get_agent_events(session_id: str, after_sequence: int = 0) -> list:
    client = _require_agent_sessions()
    return _call_worker(client.get_events, session_id, after_sequence)


@app.post("/api/agent-sessions/{session_id}/approvals/{approval_id}")
def resolve_agent_approval(session_id: str, approval_id: str,
                          body: AgentApprovalIn) -> dict:
    client = _require_agent_sessions()
    return _call_worker(client.resolve_approval, session_id, approval_id,
                        approved=body.approved, reason=body.reason)


@app.post("/api/agent-sessions/{session_id}/interrupt")
def interrupt_agent_session(session_id: str) -> dict:
    client = _require_agent_sessions()
    return _call_worker(client.interrupt, session_id)


@app.post("/api/agent-sessions/{session_id}/resume")
def resume_agent_session(session_id: str) -> dict:
    client = _require_agent_sessions()
    return _call_worker(client.resume, session_id)


@app.delete("/api/agent-sessions/{session_id}")
def close_agent_session(session_id: str) -> dict:
    client = _require_agent_sessions()
    return _call_worker(client.close_session, session_id)


class AttachmentReqIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: str
    kind: str
    rel_path: str | None = None
    resource_id: str | None = None
    display_name: str


class AttachmentsResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo_id: str | None = None
    external_egress: bool = False
    items: list[AttachmentReqIn] = Field(default_factory=list)


@app.post("/api/attachments/resolve")
def resolve_attachments(body: AttachmentsResolveIn) -> dict:
    """Resolve + safety-check the composer's typed attachments. Proxies to the
    worker (HOST filesystem, where the real context roots live): path kinds are
    clamped to the selected context root and refused on secret/escape/oversize;
    blocked ones are returned in the summary, never silently dropped."""
    client = _require_agent_sessions()
    return _call_worker(
        client.resolve_attachments, repo_id=body.repo_id,
        external_egress=body.external_egress,
        items=[it.model_dump() for it in body.items])


@app.post("/api/agent-sessions/{session_id}/handoff")
def build_agent_handoff(session_id: str, body: AgentHandoffIn) -> dict:
    """Build a BOUNDED hand-off packet (Claude ⇄ Codex ⇄ OpenRouter). Proxies to
    the worker, which assembles the packet from the source session's stored
    events and records handoff_started evidence. Returns {packet, prompt}; the
    browser seeds the target assistant with `prompt` and switches to its slot."""
    client = _require_agent_sessions()
    return _call_worker(client.build_handoff, session_id,
                        to_harness=body.to_harness, goal=body.goal,
                        open_questions=body.open_questions)


@app.post("/api/agent-sessions/{session_id}/promote")
def promote_agent_session(session_id: str, body: AgentPromoteIn) -> dict:
    """'Track as mission' — the OPTIONAL governance/tracking wrapper.

    A mission is NEVER a prerequisite for chat. This records an EXISTING read-only
    agent session as a Ledger mission so the same conversation becomes monitorable
    on the missions board. It deliberately:
      - reuses the durable session (read via the worker) — it does NOT call
        start_session/create_session, so the conversation is not restarted or
        duplicated;
      - opens an L0 (read-only), requires_approval=False mission with NO branch —
        so there is nothing to execute and no write capability is granted
        (`cc branch-mission` never polls open missions; it generates its own id);
      - links the session to the mission via the append-only event log (kind
        `note`), needing no schema change.
    Writes remain gated behind lease + worktree + approval, unchanged by this."""
    client = _require_agent_sessions()
    rec = _call_worker(client.get_session, session_id)   # durable repo/conversation
    repo_id = (rec.get("repo_id") or "").strip()
    conversation_id = rec.get("conversation_id") or ""
    action = (body.summary or "").strip() or f"Tracked cockpit agent session {session_id}"
    try:
        mr = httpx.post(f"{LEDGER_BASE_URL}/mission", json={
            "action": action, "repo": repo_id or "unknown", "branch": "",
            "risk": "L0", "requires_approval": False}, timeout=15)
        mr.raise_for_status()
        mission = mr.json()
        mid = mission["id"]
        er = httpx.post(f"{LEDGER_BASE_URL}/mission/{mid}/event", json={
            "kind": "note", "payload": {
                "event": "agent_session_link", "session_id": session_id,
                "conversation_id": conversation_id, "harness": rec.get("harness"),
                "repo_id": repo_id, "mode": "analysis", "promoted_from": "cockpit_chat"}},
            timeout=15)
        er.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"ledger error at {LEDGER_BASE_URL}: {exc}") from exc
    return {"mission_id": mid, "status": mission.get("status", "open"),
            "session_id": session_id, "conversation_id": conversation_id}


@app.post("/api/chat/promote")
def promote_chat(body: ChatPromoteIn) -> dict:
    """'Track as mission' for a GatewayCore conversation (no agent session).

    Same INERT tracking-mission contract as the agent-session promote: L0
    (read-only), requires_approval=False, NO branch — so nothing executes and no
    write capability is granted. It links the conversation via the append-only
    event log. A mission is never required to chat; this is opt-in tracking so a
    plain conversation can be monitored on the missions board without losing
    context. Writes remain gated behind lease + worktree + approval, unchanged."""
    conversation_id = (body.conversation_id or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")
    action = (body.summary or "").strip() or f"Tracked cockpit chat {conversation_id}"
    repo = (body.repo or "").strip() or "unknown"
    try:
        mr = httpx.post(f"{LEDGER_BASE_URL}/mission", json={
            "action": action, "repo": repo, "branch": "",
            "risk": "L0", "requires_approval": False}, timeout=15)
        mr.raise_for_status()
        mission = mr.json()
        mid = mission["id"]
        er = httpx.post(f"{LEDGER_BASE_URL}/mission/{mid}/event", json={
            "kind": "note", "payload": {
                "event": "chat_conversation_link", "conversation_id": conversation_id,
                "promoted_from": "cockpit_gateway_chat"}}, timeout=15)
        er.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"ledger error at {LEDGER_BASE_URL}: {exc}") from exc
    return {"mission_id": mid, "status": mission.get("status", "open"),
            "conversation_id": conversation_id}


_AGENT_EVENT_POLL_SECONDS = 0.5
_AGENT_EVENT_HEARTBEAT_SECONDS = 15.0


async def _agent_event_frames(client, session_id: str, checkpoint: int, is_disconnected):
    """The actual SSE generator, factored out from the route so tests can drive
    it with a controllable `is_disconnected` callable (an async 0-arg callable
    returning bool, matching Starlette's Request.is_disconnected) instead of
    depending on TestClient's real disconnect detection — empirically found
    unreliable for a genuinely long-lived streaming generator (the same class
    of TestClient portal/lifecycle limitation the worker's own concurrency
    test hit; see WORKLOG.md "Agent-session chat integration").

    Uses `sequence` as the SSE event id, same convention as /api/events/kanban,
    so the browser's native EventSource reconnect (Last-Event-ID) resumes
    exactly where it left off with no duplicates and no gaps. A worker
    transport failure or error response is sent as a DISTINCT
    `transport_error` SSE event — it is never persisted as an AgentEvent and
    never fabricated into assistant text; the browser decides how to react."""
    last_heartbeat = time.monotonic()
    while True:
        if await is_disconnected():
            return
        try:
            r = await asyncio.to_thread(client.get_events, session_id, checkpoint)
        except AgentWorkerUnavailable as exc:
            yield (f"event: transport_error\n"
                  f"data: {json.dumps({'detail': str(exc)})}\n\n")
            await asyncio.sleep(_AGENT_EVENT_POLL_SECONDS)
            continue
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            yield (f"event: transport_error\n"
                  f"data: {json.dumps({'detail': detail, 'status_code': r.status_code})}\n\n")
            await asyncio.sleep(_AGENT_EVENT_POLL_SECONDS)
            continue
        events = r.json()
        for ev in events:
            checkpoint = ev["sequence"]
            # The uncached-session fallback may call the synchronous worker
            # client; keep that network round-trip off the SSE event loop.
            await asyncio.to_thread(_feed_agent_usage, client, session_id, ev)
            yield f"id: {ev['sequence']}\nevent: agent_event\ndata: {json.dumps(ev)}\n\n"
        now = time.monotonic()
        if not events and now - last_heartbeat >= _AGENT_EVENT_HEARTBEAT_SECONDS:
            yield ": heartbeat\n\n"
            last_heartbeat = now
        await asyncio.sleep(_AGENT_EVENT_POLL_SECONDS)


def _resolve_sse_checkpoint(last_event_id_header: str | None, after_sequence: int) -> int:
    """Last-Event-ID (the browser's native EventSource reconnect header) wins
    over the ?after_sequence query param — same convention as
    /api/events/kanban. Never negative, whichever source it came from."""
    checkpoint = (int(last_event_id_header)
                 if (last_event_id_header and last_event_id_header.lstrip("-").isdigit())
                 else after_sequence)
    return max(0, checkpoint)


@app.get("/api/agent-sessions/{session_id}/events/stream")
def stream_agent_events(session_id: str, request: Request,
                        after_sequence: int = 0) -> StreamingResponse:
    """Browser-facing SSE — see _agent_event_frames for the actual generator."""
    client = _require_agent_sessions()
    checkpoint = _resolve_sse_checkpoint(
        request.headers.get("last-event-id"), after_sequence)
    return StreamingResponse(
        _agent_event_frames(client, session_id, checkpoint, request.is_disconnected),
        media_type="text/event-stream")


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
