"""First-party agent kanban + observability UI backend.

A convenience surface, NOT the policy layer (configs/ui.yaml / WebUIConfig). It
reads two sources that are reachable across the container boundary without coupling
to growthos/AppFlowy:

  * the Ledger (`LEDGER_BASE_URL`) — missions are the execution kanban, grouped by
    status into Cline-style columns;
  * the agent-call log (`GROWTHOS_AGENT_LOG`) — surfaced through the SAME
    command_center.kanban.metrics used by `make kanban-digest`, so the UI and the
    CLI digest can never disagree.

Full-console deployments can write through governed action verbs and validated
profile/domain config editors. Approving/killing a mission stays in the signed
Ledger endpoints; AppFlowy/provider writes still go through the action layer.
This keeps `external_write_policy: governed_by_ledger` true by construction.

The built SPA (static assets) is mounted at / when present (single-container mode).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Guarantee co-located sibling modules (agent_worker_client.py) import cleanly
# regardless of how app.py itself was loaded. `uvicorn app:app` gets this for
# free (sys.path[0] = the script's own directory), but
# `importlib.util.spec_from_file_location(...)` — how tests load this module —
# does NOT add its directory to sys.path automatically.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent_worker_client import AgentWorkerClient, AgentWorkerUnavailable
from command_center.kanban.metrics import (
    compute_metrics, load_calls, log_path, recent_calls)
from command_center.kanban_sync import EventLog, project_cards
from command_center.kanban_sync.events import emit_event, is_human_owned_status

# Chat + governed writes turn the UI into a first-class CHANNEL (it embeds the same
# GatewayCore Discord uses). OFF by default so the read-only board deployment holds
# no creds; the full console enables it (KANBAN_UI_CHAT_ENABLED=1) and mounts
# growth-os + .env. L3/L4 approve/kill never reach here — only the action layer's
# governed verbs (which already refuse Approved).
CHAT_ENABLED = os.environ.get("KANBAN_UI_CHAT_ENABLED", "") == "1"
DOMAIN_CONFIG_WRITES = os.environ.get("KANBAN_UI_DOMAIN_CONFIG_WRITES", "") == "1"
# Universal Capture — a benign, non-destructive intake list (no repo/Ledger/config
# side effects), so it defaults ON (opt-out). Captures are in-memory for now; a
# durable Ledger-backed store is the immediate follow-up.
CAPTURE_ENABLED = os.environ.get("KANBAN_UI_CAPTURE_ENABLED", "1") == "1"
# Durable capture: back the Inbox with the Ledger (survives restart) instead of
# the in-memory store. Off by default so a Ledger-less dev cockpit still works.
CAPTURE_LEDGER = os.environ.get("KANBAN_UI_CAPTURE_LEDGER", "") == "1"
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
# The store is in-process (command_center.usage is imported directly here, not
# proxied), so with the flag on but nothing polled yet the page honestly shows
# "no data / unknown" rather than fabricating quota. USAGE_CODEX registers the
# real Codex rate-limit collector for the refresh endpoint (it degrades to
# UNAVAILABLE if the SDK/login isn't present); USAGE_FAKE seeds the deterministic
# FakeCollector for a dev/demo page — never both on in a real deployment.
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
# The AppFlowy board snapshot, produced on the worker (`make kanban-board-snapshot`)
# and mounted read-only here. The UI never holds AppFlowy creds — it reads this file.
BOARD_SNAPSHOT = _env_path("KANBAN_BOARD_SNAPSHOT",
                           "/app/snapshot/board-snapshot.json")
# Read-only config mount — the model lanes + judge stages come from the real
# configs (no hardcoded model names), for the Router view.
CONFIGS_DIR = _env_path("KANBAN_UI_CONFIGS", "/app/configs")
# The kanban event log (source of truth for live board projection). Read-only here.
KANBAN_EVENT_LOG = _env_path("KANBAN_EVENT_LOG", "/app/generated/kanban-events.jsonl")
CHAT_THREADS_FILE = _env_path(
    "KANBAN_CHAT_THREADS",
    str(KANBAN_EVENT_LOG.with_name("chat-threads.json")),
)

# Cline-style columns: live work first, terminal last. Any status the Ledger returns
# that isn't listed still shows under its own name (nothing is hidden).
MISSION_COLUMNS = ["awaiting_approval", "open", "approved", "running",
                   "blocked", "done", "killed", "failed"]


app = FastAPI(title="Agent Kanban UI", version="1.0.0")


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
        appflowy = os.environ.get("APPFLOWY_BASE_URL", "").rstrip("/")
        if appflowy:
            probe("appflowy", appflowy)
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


# ── Typed domain surfaces (configs/domain_surfaces.yaml) ────────────────────
# Each domain binds a card grammar to a data source: a command_center_ui board's
# card store (event-log fold = status truth), the Ledger's missions, or the
# committed demo fixtures. Origin always travels in the payload — fixture data
# can never masquerade as live data.
FIXTURES_FILE = _env_path(
    "KANBAN_UI_FIXTURES", str(Path(__file__).parent / "domain_fixtures.json"))
BOARD_STORE_DIR = _env_path("KANBAN_BOARD_STORE", "/app/generated/boards")


def _domain_config() -> dict:
    dp = _domain_config_path()
    if not dp.is_file():
        raise HTTPException(status_code=503, detail=f"domain_surfaces.yaml not at {dp}")
    data = _read_yaml_file(dp)
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
    return cleaned


def _write_domain_config(data: dict[str, Any]) -> dict:
    _require_domain_config_writable()
    _validate_domain_config(data)
    _write_yaml_file(_domain_config_path(), data)
    return _domain_schema_response(data)


def _domain_spec(domain_id: str) -> dict:
    for d in _domain_config().get("domains", []):
        if d.get("domain_id") == domain_id:
            return d
    raise HTTPException(status_code=404, detail=f"unknown domain {domain_id!r}")


# ── Board-module create (kanban board + domain surface, atomic) ───────────────
def _kanban_boards_path() -> Path:
    return CONFIGS_DIR / "kanban_boards.yaml"


def _read_board_registry_data() -> dict[str, Any]:
    path = _kanban_boards_path()
    if not path.is_file():
        return {"schema_version": "command-center.kanban-boards.v1", "boards": []}
    return _read_yaml_file(path)


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


# snapshot board field -> the domain card grammar the typed components render
_APPFLOWY_FIELD_MAPS: dict[str, dict[str, str]] = {
    "paper": {"Title": "title", "Authors": "authors", "Abstract": "abstract",
              "URL": "url", "Published": "year", "Topics": "useful_for",
              "Score": "score", "ArxivID": "arxiv_id"},
    "repo": {"Name": "repo_id", "Owner": "owner", "URL": "url",
             "Stars": "stars", "Language": "language", "Why": "why",
             "Topics": "topics", "Score": "score", "Updated": "updated"},
    "dag": {"DagID": "dag_id", "Status": "state", "Schedule": "schedule",
            "NextRun": "next_run", "LastSeen": "last_run", "Owners": "owner",
            "Path": "related_repo", "Description": "description",
            "Notes": "failure_summary"},
    "book": {"Title": "title", "Author": "author", "Type": "type",
             "Tier": "tier", "Hours": "hours", "Section": "section",
             "Module": "module", "Notes": "notes"},
}


def _appflowy_board_cards(spec: dict) -> dict:
    """Real items from the AppFlowy board snapshot (worker-produced, mounted
    under ./generated) — a read-only projection with an honest origin and the
    snapshot timestamp. A missing snapshot/board reads as an explicit empty
    with the fix named, never a fabricated count."""
    board_name = spec.get("board")
    if not BOARD_SNAPSHOT.is_file():
        return {"origin": "board_snapshot", "cards": [],
                "note": f"board snapshot not found at {BOARD_SNAPSHOT} — "
                        f"run `make kanban-board-snapshot` on the worker"}
    snap = json.loads(BOARD_SNAPSHOT.read_text(encoding="utf-8"))
    board = next((b for b in snap.get("boards", [])
                  if b.get("board") == board_name), None)
    if board is None:
        return {"origin": "board_snapshot", "cards": [],
                "generated_at": snap.get("generated_at"),
                "note": f"board {board_name!r} is not in the snapshot — add it "
                        f"to board_state.UI_BOARDS and regenerate"}
    fmap = _APPFLOWY_FIELD_MAPS.get(spec["domain_id"], {})
    cards: list[dict] = []
    for col in board.get("columns", []):
        status = col.get("name")
        for raw in col.get("cards", []):
            fields = raw.get("fields") or {}
            card = {fmap.get(k, k.lower()): v for k, v in fields.items()}
            card.setdefault("title", raw.get("title"))
            card["status"] = status or card.get("status")
            card["card_id"] = str(
                card.get("dag_id") or card.get("arxiv_id")
                or card.get("url") or card.get("repo_id")
                or card.get("title") or "")[:200]
            cards.append(card)
    return {"origin": "board_snapshot",
            "generated_at": snap.get("generated_at"),
            "columns": board.get("statuses") or spec.get("columns", []),
            "cards": cards}


def _domain_cards(spec: dict) -> dict:
    source = spec.get("source")
    if source == "fixtures":
        fixtures = {}
        if FIXTURES_FILE.is_file():
            fixtures = json.loads(FIXTURES_FILE.read_text(encoding="utf-8"))
        return {"origin": "fixtures",
                "cards": fixtures.get(spec["domain_id"], [])}
    if source == "appflowy_board":
        return _appflowy_board_cards(spec)
    if source == "board_store":
        from command_center.boards.command_center_provider import (
            CommandCenterBoardProvider)
        provider = CommandCenterBoardProvider(
            board_id=spec["board_id"], event_log=EventLog(KANBAN_EVENT_LOG),
            store_dir=BOARD_STORE_DIR)
        return {"origin": "board_store", "board_id": spec["board_id"],
                "cards": provider.list_cards()}
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


def _allowed_transitions(spec: dict, from_status: str | None) -> list[str]:
    """One step forward or backward, never a skip. Jobs use the explicit gate
    map; other board domains use column adjacency."""
    if spec.get("domain_id") == "job_application":
        return list(_JOB_TRANSITIONS.get(str(from_status), []))
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
                "or approve & submit."
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
        lines.append(
            "Do not claim an application was submitted unless the application status "
            "is applied or the board lane is Completed."
        )
    lines.extend([
        "",
        "CARD CONTEXT",
        f"- domain: {domain_id} ({domain_title})",
        f"- card_id: {card.get('card_id')}",
        f"- title: {title} {role}".strip(),
        f"- status: {card.get('status')}",
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
        if value in (None, "", [], {}):
            continue
        lines.append(f"- {field.get('label', name)}: {value}")
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
    lines.extend([
        "",
        "Answer with:",
        "1. What happened so far, using the card context and events above.",
        "2. What is blocking or current.",
        "3. The next safe action Geoff (or an executor started from a mission) should take.",
    ])
    return "\n".join(lines)


def _domain_progress(spec: dict, card_id: str) -> dict:
    provider = _board_store_provider(spec) if spec.get("source") == "board_store" else None
    card = _find_domain_card(provider, card_id) if provider else next(
        (c for c in _domain_cards(spec)["cards"] if str(c.get("card_id")) == card_id),
        None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"card {card_id!r} not found")
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
    domain_id: str
    title: str
    card_component: str = "generic_task"
    source: str = "fixtures"
    board_id: str | None = None
    columns: list[str] = Field(default_factory=list)
    column_actions: dict[str, str] = Field(default_factory=dict)
    summary_fields: list[dict[str, Any]] = Field(default_factory=list)
    drawer_fields: list[dict[str, Any]] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    empty_state: dict[str, Any] = Field(default_factory=dict)


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
    return {"domains": _domain_config().get("domains", [])}


@app.get("/api/domain-schema")
def domain_schema() -> dict:
    """Editable view of configs/domain_surfaces.yaml for the full cockpit console."""
    return _domain_schema_response()


@app.post("/api/domain-schema")
def create_domain_schema(body: DomainSurfaceIn) -> dict:
    data = _domain_config()
    domain = _clean_domain_surface(body.model_dump(mode="json"))
    if any(row.get("domain_id") == domain["domain_id"] for row in data.get("domains", [])):
        raise HTTPException(
            status_code=409,
            detail=f"domain {domain['domain_id']!r} already exists",
        )
    next_data = dict(data)
    next_data["domains"] = [*data.get("domains", []), domain]
    return _write_domain_config(next_data)


@app.put("/api/domain-schema/{domain_id}")
def update_domain_schema(domain_id: str, body: DomainSurfaceIn) -> dict:
    data = _domain_config()
    domain = _clean_domain_surface(body.model_dump(mode="json"))
    domains = list(data.get("domains", []))
    idx = next((i for i, row in enumerate(domains)
                if row.get("domain_id") == domain_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"unknown domain {domain_id!r}")
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
    data = _domain_config()
    domains = list(data.get("domains", []))
    next_domains = [row for row in domains if row.get("domain_id") != domain_id]
    if len(next_domains) == len(domains):
        raise HTTPException(status_code=404, detail=f"unknown domain {domain_id!r}")
    next_data = dict(data)
    next_data["domains"] = next_domains
    return _write_domain_config(next_data)


@app.post("/api/board-module", status_code=201)
def create_board_module(body: BoardModuleIn) -> dict:
    """Create a whole board MODULE from one typed request: a kanban board (the
    repo/verb/status contract) + its domain surface (generic_task card grammar),
    so every board — including user-created ones — gets the same chat + pipeline
    + usage treatment. Governance defaults are FIXED: wall verbs stay forbidden,
    human approval/merge is unchanged. Atomic (both configs validate before either
    is written), write-gated, and audited. The browser never emits YAML."""
    _require_domain_config_writable()   # CHAT_ENABLED + DOMAIN_CONFIG_WRITES + writable
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
    columns = ([c.strip() for c in body.columns if c.strip()]
               or list(_KANBAN_STATUS_LABELS.values()))
    surface = _clean_domain_surface({
        "domain_id": board_id, "title": body.title.strip(),
        "card_component": "generic_task", "source": "board_store", "board_id": board_id,
        "columns": columns, "column_actions": {},
        "summary_fields": [{"name": "title", "label": "Title"},
                           {"name": "status", "label": "Status"}],
        "drawer_fields": [{"name": "description", "label": "Description"},
                          {"name": "notes", "label": "Notes"}],
        "allowed_actions": ["stage_card", "start_todo", "finish_todo",
                            "block_card", "reject_card"],
        "empty_state": {"title": f"No {body.title.strip()} cards yet",
                        "hint": body.description.strip() or "Add a card to get started."}})

    # Validate BOTH before writing EITHER — never a half-created module.
    next_reg = {"schema_version": reg.get("schema_version", "command-center.kanban-boards.v1"),
                "boards": [*reg.get("boards", []), board_spec]}
    next_dom = {**dom, "domains": [*dom.get("domains", []), surface]}
    _validate_board_registry(next_reg)
    _validate_domain_config(next_dom)
    _write_yaml_file(_kanban_boards_path(), next_reg)
    _write_domain_config(next_dom)      # re-validates + writes domain_surfaces.yaml
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


@app.get("/api/intake/inbox")
def intake_inbox() -> dict:
    """The Universal Inbox: captures grouped into lanes. A capture is recoverable
    here even after it is routed elsewhere — nothing is ever silently dropped."""
    return _require_capture().inbox()


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
    return out


@app.get("/api/domain/{domain_id}/card/{card_id}")
def domain_card(domain_id: str, card_id: str) -> dict:
    spec = _domain_spec(domain_id)
    for card in _domain_cards(spec)["cards"]:
        if str(card.get("card_id")) == card_id:
            return {"domain_id": domain_id, "card": card,
                    "drawer_fields": spec.get("drawer_fields", [])}
    raise HTTPException(status_code=404,
                        detail=f"card {card_id!r} not in domain {domain_id!r}")


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
        if USAGE_CODEX:
            from command_center.usage.collectors.codex_app_server import (
                CODEX_COLLECTOR_ID, CodexAppServerCollector)
            _usage_collectors.append((CodexAppServerCollector(), CODEX_COLLECTOR_ID))
        if USAGE_CLAUDE:
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
    here. Best-effort — a usage-tee failure must never break the browser SSE."""
    if not (USAGE_ENABLED and USAGE_CLAUDE) or ev.get("type") != "rate_limit":
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


class DomainNoteIn(BaseModel):
    type: str = "manual_note"
    text: str
    source: str = "cockpit"


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


class StandingAnswerIn(BaseModel):
    topic: str
    answer: str
    question: str | None = None
    covers: list[str] | None = None


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
    submission evidence. Both the Completed drag and the Approve & Submit
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
        side_effect = _process_selected_job_cards()
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
        app_id, note_type, content, root=root, source=body.source.strip() or "cockpit")
    fields = _card_store_fields(card)
    fields.update({
        "next_action": event.get("action_needed"),
        "last_seen_at": str(event.get("ts") or "")[:10],
        "latest_communication": event.get("summary"),
        "latest_communication_type": note_type,
    })
    provider.upsert_card(card_id, fields)

    kanban_event = None
    if _note_type_moves_to_interviewing(note_type) and card.get("status") != "Interviewing":
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


# ── Packet review loop: view materials → notes/regenerate → approve & submit ──
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
        load_application,
        save_application,
    )

    _, root = _job_search_config_and_root()
    app_dir, record = load_application(app_id, root=root)
    (app_dir / filename).write_text(content + "\n", encoding="utf-8")
    if body.file == "resume":
        # the plain-text ATS variant is derived from the resume — regenerate
        # on every resume edit so the two files cannot drift
        from command_center.job_search.agent_writer import resume_ats_text
        (app_dir / "resume_ats.txt").write_text(
            resume_ats_text(content), encoding="utf-8")
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
    """Approve & Submit: the same governed Completed move as the drag, gated on
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
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _job_search_profile_settings_path() -> Path:
    _, root = _job_search_config_and_root()
    return root / "profile" / "search_settings.yml"


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
    }


def _application_question_policy() -> tuple[dict[str, Any], Path]:
    cfg, root = _job_search_config_and_root()
    policy_path = root / "profile" / "application_question_policy.yml"
    if policy_path.is_file():
        return _read_yaml_file(policy_path), policy_path
    return cfg.application_questions.model_dump(mode="json"), CONFIGS_DIR / "job_search.yaml"


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
        "writable": CHAT_ENABLED,
        "write_gate": (
            "enabled" if CHAT_ENABLED else
            "read-only deployment; set KANBAN_UI_CHAT_ENABLED=1 for in-app edits"
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
        "executor_fallback": cfg.executor_fallback.model_dump(mode="json"),
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
            "a manual phrase listed in an entry's `covers` no longer blocks "
            "automation — the answer is rendered into each packet's "
            "application_answers.md instead"),
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
    override = _read_job_search_profile_settings()
    runtime = override.setdefault("job_search", {})
    for key, value in body.model_dump(exclude_none=True).items():
        runtime[key] = value
    return _write_job_search_profile_settings(override)


@app.put("/api/job-search/profile-controls/category/{category_id}")
def update_job_search_category(category_id: str,
                               body: JobSearchCategorySettingsIn) -> dict:
    """Upsert a search category: patch an existing one, or CREATE a new one
    when the id is unknown (new categories need resume_variant + keywords so
    scoring and discovery know what to do with them)."""
    _require_profile_writable()
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
    from command_center.job_search.standing_answers import (
        load_standing_answers,
        save_standing_answers,
    )

    _, root = _job_search_config_and_root()
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
    return {
        "status": "bulk_selected",
        "automation_class": body.automation_class,
        "target": target,
        "moved_count": len(moved),
        "moved": moved,
    }


@app.put("/api/job-search/profile-controls/draft-default")
def update_draft_default(body: DraftDefaultIn) -> dict:
    _require_profile_writable()
    key = body.key.strip()
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", key):
        raise HTTPException(
            status_code=400,
            detail="draft default key must be a stable token "
                   "([A-Za-z0-9_:-]+)")
    policy, source = _application_question_policy()
    policy.setdefault("draft_defaults", {})
    policy["draft_defaults"][key] = body.value
    from command_center.job_search.schemas import ApplicationQuestions
    ApplicationQuestions.model_validate(policy)
    _, root = _job_search_config_and_root()
    target = root / "profile" / "application_question_policy.yml"
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
    path = CONFIGS_DIR / "kanban_boards.yaml"
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"kanban_boards.yaml not at {path}")
    data = _read_yaml_file(path)
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


def _registered_repos() -> list[dict]:
    """Registered repos (configs/autonomy.yaml repo_manifests) — the scoped-
    chat targets. Read-only; any failure means an empty list, never a broken
    chat view."""
    try:
        data = _read_yaml_file(CONFIGS_DIR / "autonomy.yaml")
        return [
            {"repo_id": str(r.get("repo_id")),
             "remote_url": str(r.get("remote_url") or "")}
            for r in (data.get("repo_manifests") or []) if r.get("repo_id")
        ]
    except Exception:
        return []


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
    agentic coding harnesses that drive leased worktrees via their own
    subscription/OAuth login, not conversational chat models — they never
    appear in this picker. Chat-gated like every /api/chat* route."""
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
            "Claude Code and Codex CLI are agentic coding EXECUTORS, not chat "
            "roles — they drive leased repo worktrees under their own "
            "subscription/OAuth login (never a LiteLLM API key) and are "
            "launched from missions, not this chat picker."
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
@app.get("/api/model-usage")
def model_usage() -> list:
    """One status row per runtime (availability + every live bucket + rolled
    usage + honest staleness)."""
    from command_center.usage import cockpit_views as cv
    return cv.usage_overview(_require_usage())


@app.get("/api/model-usage/collector-health")
def model_usage_collector_health() -> list:
    """Durable checkpoint per registered collector — polling cleanly / failing
    (with the real error) / never ran."""
    service = _require_usage()
    from command_center.usage import cockpit_views as cv
    return cv.collector_health(service, [cid for _, cid in _usage_collectors])


@app.get("/api/model-usage/top-drivers")
def model_usage_top_drivers(runtime_id: str, dimension: str = "mission",
                            metric: str = "total_tokens", limit: int = 10) -> dict:
    """"What used the most?" for a runtime, from recorded driver facts."""
    service = _require_usage()
    from command_center.usage import cockpit_views as cv
    try:
        return cv.top_drivers(service, runtime_id=runtime_id, dimension=dimension,
                              metric=metric, limit=limit)
    except ValueError as exc:            # unknown dimension/metric
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/model-usage/refresh")
async def model_usage_refresh() -> dict:
    """Run every registered collector once (durable tracked path). With no
    collectors registered this is a no-op that honestly reports 0 — it never
    fabricates data."""
    service = _require_usage()
    from command_center.usage import cockpit_views as cv
    return await cv.refresh(service, _usage_collectors)


@app.get("/api/model-usage/{runtime_id}")
def model_usage_runtime(runtime_id: str) -> dict:
    """Full status for one runtime (UNKNOWN + no buckets if never observed —
    never an error, never fabricated)."""
    from command_center.usage import cockpit_views as cv
    return cv.runtime_detail(_require_usage(), runtime_id)


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
            _feed_agent_usage(client, session_id, ev)   # tee live limits into usage
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
