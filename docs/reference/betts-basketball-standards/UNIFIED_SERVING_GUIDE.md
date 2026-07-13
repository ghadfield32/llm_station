# Unified ML Serving Guide

> **Version**: 2.5 | **Date**: 2026-05-06
> **Doc refresh (2026-05-06 LLM News)**: production `/api/v1/news/*`
> is verified through story date `2026-05-05` after the LLM News current-run
> recovery. Serving remains promoted-artifact only: Airflow validates gold and
> dbt news marts first, R2 promotion uses the centralized uploader with
> `--news-date=YYYY-MM-DD` for date-scoped daily partitions, and Railway reads
> the promoted news artifacts/marts rather than running batch generation in the
> request path. Missing artifacts remain an explicit 503/404/null-boundary
> contract, not a synthetic news row.
> **Doc refresh (2026-05-05 YouTube Highlights)**: production `/api/v1/highlights/*`
> is verified through NBA local game date `2026-05-04` after the local-date
> schedule fix. Serving remains artifact-first from R2-hydrated gold product
> parquets; dbt is validation/analytics only. Top-player clips are served from
> `player_game_highlights`, and current gold carries the exact YouTube
> `PUBLISHED_AFTER`/`PUBLISHED_BEFORE` request window for validation parity.
> **Doc refresh (2026-05-04 YouTube Highlights)**: `/api/v1/highlights/*`
> now serves validated YouTube highlight gold product parquets hydrated from R2,
> not `basketball_v2.duckdb`. Missing required game/player artifacts are 503;
> missing entity/date rows are 404 or explicit empty collections by endpoint
> contract. Railway bootstrap and manifest hot-sync own artifact refresh.
> **Doc refresh (2026-05-04 Sportsbook sources)**: `/api/v1/sportsbook/sources` is the canonical source catalog for Sportsbook filters. It scans B9/B12/B13/B14/B16 artifacts for source/provider/book provenance; `/sportsbook/markets` remains internal board grain and must not be used to infer external book availability.
> **Doc refresh (2026-04-29 ODDS)**: ODDS/Sportsbook serving must remain artifact-only while provider pulls stay in Airflow/planning code; game-level Sportsbook endpoints carry the selected date, and season/package-budget reports live under `reports/odds/planning/` before any new ODDS scope is promoted.
> **Doc refresh (2026-04-29 KPI)**: Added cross-domain overview/KPI serving rules to §6d after the Home tab KPI incident: overview endpoints must read domain-owned serving sources or a currently contracted rollup, surface per-domain errors, and never fabricate KPI values.
> **Doc refresh (2026-04-29 DAG)**: `/api/v1/ingest/dag-observability` now exposes
> `total_duration_seconds` in every daily/weekly/monthly summary so the admin
> DAG dashboard can render CPU/GPU time-used graphics and add-process cost
> projections from telemetry rather than fixed budgets or fake values. Keep this
> contract always-current: any ingest observability, fleet, or GPU job response
> change must update the admin DAG dashboard, `PIPELINE_STANDARDS_TEMPLATE.md`,
> and `docs/frontend/FRONTEND.md` in the same change set.
> **Doc refresh (2026-04-30)**: `/ingest/dag-observability` interval summaries
> must avoid PostgreSQL reserved words for internal SQL identifiers. The public
> response still exposes `window`, but SQL uses `summary_window` internally.
> **Doc refresh (2026-04-30)**: admin DAG capacity cards may use global ledger
> summaries when Airflow fleet metadata is unavailable, but must label the
> provenance and leave schedule-derived fields unavailable. CPU capacity uses
> configured Airflow local task parallelism from
> `/ingest/dag-observability.capacity_config.cpu_resource_slots`, with
> `/ingest/fleet.parallelism` as a secondary source; otherwise negative CPU
> headroom is one-lane serial pressure until configured Airflow worker
> parallelism proves external capacity is required.
> **Doc refresh (2026-04-30)**: the admin DAG scan table must surface the
> high-signal merged telemetry directly: source/worker/artifact, Airflow
> owner/schedule/paused/next run, state/stage, selected-window run health,
> latest/avg/p95/total runtime, event date range, rows/bytes, null/NaN health,
> GPU required/used/provider/runtime/cost, latest run, and last error. Lower
> frequency diagnostics stay in the expanded detail panel.
> **Doc refresh (2026-04-28)**: Added ODDS and Sportsbook serving rows to the endpoint inventory and an explicit ODDS/Sportsbook handoff note in §6d. These endpoints read promoted gold/product artifacts only; B12/B13/B14/B16 consume validated ODDS gold and must not fabricate CLV, arbitrage, book-quality, or frontend rows when artifacts are absent.
> **Consolidates and supersedes**: `notebooks/unified_serving_documentation.ipynb`
> **Doc refresh (2026-04-26)**: Added a data-pipeline serving handoff checklist to §6d: served APIs read promoted gold/product artifacts only, Railway never runs batch pipelines, artifact absence is a 503/404 contract instead of a fake default, and every new serving surface must declare its manifest/freshness source before cutover.
> **Doc refresh (2026-04-18)**: Added §6d serving promotion gate so new pipeline/DAG artifacts must prove local full-run, staged Railway bootstrap, typed endpoint contracts, and frontend safety before production cutover.
> **Changes (v2.3)**: §6d now explicitly ties data-engineering promotion to serving readiness: source artifact/table, R2 manifest key, freshness endpoint, response model, missing-data behavior, and rollback artifact must be documented before a DAG-backed endpoint is considered live.
> **Doc refresh (2026-04-02)**: Lineup router entry corrected to the current `lineup_serving.duckdb` footprint (12 tables, ~75 MB), V4.4 scenario-key joins, scoped tempo thresholds, and restored 5-man opponent serving.
> **Changes (v2.2)**: §6d expanded with a hard "ready to unpause" view of serving rollouts: staged cutovers now assume a single root-cause taxonomy, runtime-derived GPU/backend proof for retrain-backed artifacts, and explicit frontend/non-regression checks before the schedule is treated as live.
> **Changes (v2.1)**: New §6d "Serving Promotion Gate" consolidates the local -> staging -> production acceptance sequence for new pipeline-backed serving surfaces, including artifact contract validation, frontend/non-regression checks, R2 freshness validation, and runtime-derived GPU/backend logging for retrain-backed models.
> **Changes (v2.0)**: FastAPI 0.128 -> 0.134 upgrade — Pydantic Rust JSON serialization (~2x speedup on typed endpoints); ORJSONResponse/UJSONResponse migrated to JSONResponse; strict Content-Type safety net; blocking I/O bug fixed (predictions/draft/nba handlers converted from `async def` to `def`); threading.Lock added for nba_endpoints.py module-level TTL caches; Pydantic `response_model=` added to analytics/draft/referee endpoints; NDJSON streaming endpoints added (`/daily-slate/stream`, `/market-scanner/stream`, `/prospect-board/stream`); §2b Handler Type Standards, §2c Response Model Standards, §2d DuckDB Query Standards, §6b Decision Guide, §6c New Endpoint Checklist, §15 Upgrade History added.
> **Changes (v1.7)**: XFG pipeline rebuilt (Sessions 381-386) — 12 champion seasons retrained with 53-feature set + TRAIN_WINDOW_SEASONS=3 (ablation-derived); Bayesian zone model retrained (Binomial posteriors, 45.0% shrinkage, 91.4% CI coverage); shot-level challenger evaluated and rejected (GBDT remains champion); `_attach_bayesian_cis` defensive fallback removed (raises `FileNotFoundError` instead); zone profile path now raises `FileNotFoundError` if missing. XFG model artifact count updated to 35 files.
> **Changes (v1.6)**: XFG live endpoint added (`GET /xfg/live-performance/{game_id}`, Session 369); `annotated-types>=0.6.0` added to `pyproject.toml` (NBA MCP crash fix); XFG credible intervals row corrected to Yes
> **Changes (v1.9)**: Router count corrected 13->20. Removed ghost forecasting router (deregistered v30.6). Added missing routers: referee (#11), analytics (#16), sentiment (#17), ops/schedule (#18). Renumbered table.
> **Changes (v1.8)**: Added Team-Controlled Promotions (rows 16-17) and Overseas Targets (rows 18-19) endpoints — `pickup_endpoints.py` `tc_router` + `overseas_router`, `/api/v1/team-controlled/*` + `/api/v1/overseas/*`. Model artifacts for team-controlled: `cache/models/team_controlled_v1/` (per-bucket HistGBDT). Overseas reuses prospect pipeline artifacts (no separate model).
> **Changes (v1.5)**: Added G-League Pickup Forecasting endpoint (row 12) to endpoint reference table — `pickup_endpoints.py`, `/api/v1/pickup/*`
> **Changes (v1.4)**: Added "Architecture Layers" section clarifying REST APIs vs MCP distinction; new "LLM Agent Tooling (MCP)" section documenting agent integration layer

Single source of truth for how ML models are served in production on Railway.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
1b. [Architecture Layers: REST APIs vs MCP](#1b-architecture-layers-rest-apis-vs-mcp)
2. [Middleware Stack (Standardized)](#2-middleware-stack-standardized)
2b. [Handler Type Standards](#2b-handler-type-standards)
2c. [Response Model Standards](#2c-response-model-standards)
2d. [DuckDB Query Standards](#2d-duckdb-query-standards)
3. [API Endpoint Reference](#3-api-endpoint-reference)
4. [Model Registry & Discovery](#4-model-registry--discovery)
5. [Model Artifacts & Storage](#5-model-artifacts--storage)
6. [Prediction Flow](#6-prediction-flow)
6b. [Response Pattern Decision Guide](#6b-response-pattern-decision-guide)
6c. [New Endpoint Development Checklist](#6c-new-endpoint-development-checklist)
6d. [Serving Promotion Gate](#6d-serving-promotion-gate)
7. [Champion-Challenger System](#7-champion-challenger-system)
8. [MLflow Integration](#8-mlflow-integration)
9. [Health & Monitoring](#9-health--monitoring)
10. [Prediction Audit Trail](#10-prediction-audit-trail)
11. [CI/CD Pipeline](#11-cicd-pipeline)
12. [API Security](#12-api-security)
13. [LLM Agent Tooling (MCP)](#13-llm-agent-tooling-mcp)
14. [Rollback Runbook & SLO Thresholds](#14-rollback-runbook--slo-thresholds)
15. [FastAPI Upgrade History](#15-fastapi-upgrade-history)

---

## Upgrade Progress (FastAPI 0.128 -> 0.134)

| Step | Status | Notes |
|------|--------|-------|
| 1.1 Version bump pyproject.toml | ✅ Done | `>=0.134.0,<0.136.0` |
| 1.2 `strict_content_type=False` safety net | ✅ Done | TODO in main.py to remove after client audit |
| 1.3 ORJSONResponse migration | ✅ Done | No usage found — already clean |
| 1.4 Baseline tests pass | ✅ Done | |
| 2.1 Fix blocking I/O — predictions | ✅ Done | All 7 handlers converted `async def` -> `def` |
| 2.2 Fix blocking I/O — draft | ✅ Done | All 9 handlers converted; `await health_check()` -> `health_check()` |
| 2.3 Fix blocking I/O + cache locks — nba | ✅ Done | 10 handlers converted; `threading.Lock` added for 2 TTL caches |
| 3.1 Pydantic models — analytics | ✅ Done | `MartResponse` on all 18 `wrap_rows()` endpoints |
| 3.2 Pydantic models — draft | ✅ Done | `DraftRankingsResponse`, `DraftTeamPicksResponse`, `DraftHealthResponse` |
| 3.3 Pydantic models — referee | ✅ Done | `RefereeRowsResponse` on 7 raw dict endpoints |
| 4.1 Streaming — daily-slate | ✅ Done | `GET /predictions/daily-slate/stream -> Iterable[PlayerPrediction]` |
| 4.2 Streaming — market-scanner | ✅ Done | `GET /analytics/market-scanner/stream -> Iterable[MarketScannerRow]` |
| 4.3 Streaming — prospect-board | ✅ Done | `GET /analytics/prospect-board/stream -> Iterable[ProspectBoardRow]` |
| 5. UNIFIED_SERVING_GUIDE v2.0 | ✅ Done | This document |

---

## Compliance Sweep Progress (2026-03-09)

Full endpoint audit against v2.0 standards (§2b handler types, §2c response models, §2d error codes, §6c checklist).

| Step | Status | Notes |
|------|--------|-------|
| A1 `datasets_endpoints.py` — 200+error -> HTTPException | ✅ Done | `async def` -> `def`; 3 error paths -> 503/404; bare except -> 500 |
| A2 `bayesian_endpoints.py` — async def -> def | ✅ Done | All 5 handlers; removed `asyncio` import; `failed_targets` added to BatchPredictionResponse |
| A3 `gbdt_endpoints.py` — async def -> def; /health fix; /train response_model | ✅ Done | All 6 handlers; `HealthResponse(status="error")` -> HTTPException(503); `TrainStartedResponse` added |
| A4 `llm_proxy_endpoints.py` — LLMProxyHealthResponse model | ✅ Done | `LLMProxyHealthResponse` + `LLMProviderStatus`; /health now typed; /chat stays async (genuine `await`) |
| A5 `sim_endpoints.py` — remove empty DataFrame fallback | ✅ Done | `pd.DataFrame()` -> `HTTPException(503)`; all 3 handlers `async def` -> `def` |
| B1 `lineup_endpoints.py` — full compliance sweep | ✅ Done | **Session 2 (2026-03-09):** All 11 non-SSE handlers `async def` -> `def`; 9 endpoints missing/broken `response_model=` fixed; `_get_duckdb_conn()` race condition fixed (added lock); singleton `conn.close()` bug removed; `_get_column_value` now returns `Optional[float]`; 3 new inline Pydantic models (`LeagueLineupsResponse`, `NBATeamsResponse`, `GradeThresholdsResponse`); `get_duckdb_connection()` NameError bug fixed |
| B2 `nba_data_endpoints.py` — Lock + response_models + async fix | ✅ Done | `_players_cache_lock` added; 6 handlers `async def` -> `def`; Pydantic models for all 7 endpoints |
| B3 `xfg_endpoints.py` — response_models + async fix | ✅ Done | `ModelComparisonResponse`, `ModelAuditResponse`, `ShotDetailResponse` added; 3 handlers `async def` -> `def` |
| B4 `prospect_endpoints.py` — async def -> def | ✅ Done | All 5 handlers converted; all had `response_model=` already |
| B5 `sentiment_endpoints.py` | ✅ Pass | No violations found; all `def` (sync); proper HTTPException(404)s |
| C1 `XFG_FORECASTING.md` — UNIFIED_SERVING_GUIDE cross-ref | ✅ Done | Added §6b-§6c callout in REST Endpoint Serving section |
| C2 `GLEAGUE_PICKUP_SPEC.md` — UNIFIED_SERVING_GUIDE cross-ref | ✅ Done | Added §6b-§6c callout in Stage 9 Board Build and Serving section |

### Remaining Known Gaps
- `nba_data_endpoints.py`: 1 endpoint (`/players`) stays `async def` — has genuine `await httpx` call (correct behavior, not a violation)
- `lineup_endpoints.py` `stream_live_recommendations`: stays `async def` — SSE endpoint, correct by design

---

## 1. Architecture Overview

### Deployment Topology

```
 React Frontend (Railway: Nixpacks)           FastAPI Backend (Railway: Nixpacks)
+-------------------------------------+     +----------------------------------------------+
|  Vite build -> static assets        | --> |  api/start.sh                                |
|  Dockerfile.railway (Node 18)       |     |    1. MLflow store setup (/data/mlruns)       |
|  Production URL:                    |     |    2. DB seed (seed_user.py or inline)        |
|    react-frontend-production-       |     |    3. Model warm-start (ensure_models.py)     |
|    2805.up.railway.app              |     |    4. uvicorn app.main:app --port $PORT       |
+-------------------------------------+     +----------------------------------------------+
                                                |           |           |
                                          Bayesian      GBDT        XFG
                                          Backend      Backend     Backend
                                          (PyMC)     (sklearn)   (sklearn)
```

### Railway Configuration

**Backend** (`api/railway.json`):
- Builder: Nixpacks (reads `api/pyproject.toml`)
- Health check: `GET /api/v1/health` every 10s
- Restart: on failure
- Start command: `api/start.sh`

**Frontend** (`Dockerfile.railway`):
- Node 18 Alpine, Vite build
- Nginx serving static assets

### Key Files

| File | Purpose |
|------|---------|
| `api/start.sh` | Railway launcher (182 LOC): MLflow init, DB seed, model warm-start, uvicorn |
| `api/railway.json` | Railway service config (health check, restart policy) |
| `api/pyproject.toml` | All Python dependencies (Nixpacks reads this) |
| `api/app/main.py` | FastAPI app factory (20 routers, middleware stack) |
| `api/config.yaml` | Centralized config (dev/staging/prod environments) |

---

## 1b. Architecture Layers: REST APIs vs MCP

Your serving infrastructure has **two distinct communication channels** that serve different purposes:

### Channel 1: REST APIs (Product & ML Serving)
**What**: HTTP/JSON endpoints for dashboards, predictions, analytics, and product functionality.

**Endpoints** (`/api/v1/*`):
- `/serving/predict` -- Model inference (Bayesian, GBDT, XFG)
- `/analytics/*` -- Dashboard & analytics queries (DuckDB via analytics_db service, 23 endpoints)
- `/prospects/*` -- Prospect forecasting (big board, backtest, player cards)
- `/referees/*` -- Referee tendencies, bias audit, game predictions
- `/health` -- System health checks

**Clients**:
- React frontend (dashboards, UI components)
- External integrations (third-party APIs, data pipelines)
- Batch scripts (validation, reporting)

**Security**: Auth via JWT (issued by backend), CORS configured per environment, request signing via X-Request-ID.

**Monitoring**: Prometheus metrics at `/metrics`, prediction audit trail in `logs/predictions.jsonl`.

---

### Channel 2: MCP (LLM Agent Tooling)
**What**: Model Context Protocol — a standardized protocol for LLM agents/assistants to discover and call "tools", fetch "resources", and retrieve context. MCP is **NOT** an ML serving layer; it's an agent integration layer.

**Where it runs**: `:8001/sse` service (separate from main FastAPI backend).

**What it exposes**:
- **Tools**: agent-callable functions like `catalog/fetch/build_dataset` (prospect pipeline operations)
- **Resources**: data/context the agent can request (player stats, prospect rankings, etc.)
- **Prompts**: pre-canned agent instructions for specific workflows (scouting advice, trade analysis)

**Clients**:
- LLM assistants (Claude in mcpClient.js, other AI agents)
- Agent chat flows (internal tooling for analysts)
- NOT: regular product UI (use REST instead)

**Security**: Auth + Origin validation (to prevent CSRF), tool allowlist (not all functions exposed to agents).

---

### The Key Distinction

| Aspect | REST API | MCP |
|--------|----------|-----|
| **Purpose** | Product & ML serving | Agent/tool integration |
| **Clients** | Frontend, dashboards, scripts | LLM assistants, agents |
| **Transport** | HTTP/JSON | JSON-RPC 2.0 over SSE (or HTTP) |
| **Failures** | User sees error in UI | Agent retries or reports to user |
| **Monitoring** | Prometheus + prediction logs | Tool call metrics (cbb_tool_calls_total, etc.) |
| **Frontend access** | ✅ Direct (JWT auth) | ❌ No direct access (too powerful) |

**Rule of thumb**: If a frontend dashboard or user-facing feature needs data, use REST. If an LLM assistant needs to run a tool or fetch context, use MCP.

---

## 2. Middleware Stack (Standardized)

All middleware is **pure ASGI** (not `BaseHTTPMiddleware`) to avoid the Starlette EndOfStream bug. The middleware chain wraps the entire FastAPI application at the ASGI level, meaning ALL 20 routers automatically pass through the same chain.

### Middleware Execution Order (outermost -> innermost)

```
Incoming HTTP Request
  |
  v
[1. RequestIDMiddleware]    -- Generates UUID, stores in contextvars,
  |                            adds X-Request-ID response header.
  |                            If caller sends X-Request-ID, reuses it.
  |                            File: api/app/middleware/request_id.py
  v
[2. PrometheusMiddleware]   -- Records per-request latency, status code,
  |                            and prediction-specific counters.
  |                            Serves /metrics endpoint for Prometheus scraping.
  |                            File: api/app/middleware/metrics.py
  v
[3. PredictionLogger]       -- For prediction endpoints ONLY: logs structured
  |                            JSONL records (request_id, latency, model_type).
  |                            File: api/app/middleware/prediction_logger.py
  v
[4. ConcurrencyLimiter]    -- Semaphore limiting max 4 concurrent heavy
  |                            requests (cancer/predict, iris/train, etc.).
  |                            File: api/app/middleware/concurrency.py
  v
[5. CORSMiddleware]         -- Standard FastAPI CORS (allow all origins in dev).
  |                            Configured inline in main.py.
  v
[6. X-Process-Time]         -- Inline @app.middleware("http") that adds
  |                            X-Process-Time header to every response.
  v
[7. FastAPILimiter]         -- Rate limiting via Redis (initialized in lifespan).
  |                            Per-endpoint rate limits via dependency injection.
  v
[Your Route Handler]        -- /api/v1/bayesian/predict, /api/v1/gbdt/predict, etc.
  |
  v
Response (with X-Request-ID, X-Process-Time headers)
```

### Why ASGI-Level Middleware

Because middleware wraps the entire ASGI application:
- **No per-pipeline configuration needed** -- Bayesian, GBDT, XFG, Forecasting, Prospects all get the same Request ID + logging automatically.
- **PredictionLogger only activates on matching URL prefixes** -- configurable set in `prediction_logger.py`.
- **Existing `ConcurrencyLimiter` already follows this pattern** -- checks `scope["path"]` against `heavy_endpoints` set.

### Structured JSON Logging

All log output is JSON-formatted via `api/app/middleware/log_filter.py`:

```json
{
  "timestamp": "2026-02-24T15:30:45.123456+00:00",
  "level": "INFO",
  "logger": "app.services.ml.model_service",
  "message": "GBDT champion loaded for PTS_PLAYER_GAME",
  "request_id": "a1b2c3d4e5f6..."
}
```

The `request_id` field is automatically injected via a `logging.Filter` that reads from `contextvars.ContextVar` set by `RequestIDMiddleware`.

Config: `api/logging.yaml`

---

## 2b. Handler Type Standards

### Rule: `def` (sync) for I/O-bound; `async def` for genuine async work only

FastAPI/Starlette automatically runs `def` (sync) handlers in a thread pool executor.
Sync handlers **never block the event loop** — they are the correct choice for:

- `pd.read_parquet()`, `pd.read_csv()` — file I/O
- DuckDB queries (`.execute()`, `.fetchdf()`, `.fetchall()`, `.fetchmany()`)
- Joblib model loading and `.predict()` calls (CPU-bound)
- Any call that does not use `await`

`async def` handlers should be reserved **only** for:

- `await httpx.AsyncClient.get(...)` — async HTTP
- `await redis.get(...)` — async Redis reads
- `await anyio.open_file(...)` — true async file I/O
- Orchestrating concurrent async operations with `asyncio.gather()`

### Anti-patterns (NEVER DO)

```python
# WRONG — blocks the event loop:
async def get_predictions(date: str) -> ...:
    df = pd.read_parquet(cache_path)  # synchronous I/O inside async handler

# CORRECT — runs in thread pool automatically:
def get_predictions(date: str) -> ...:
    df = pd.read_parquet(cache_path)
```

### Thread pool sizing

Default Starlette thread pool: `min(32, os.cpu_count() + 4)` workers.
The existing `ConcurrencyLimiter` (max 4 concurrent heavy requests) limits demand
on the thread pool for the heaviest endpoints.

### Module-level TTL caches — threading.Lock required

Sync handlers run in the thread pool concurrently. Module-level `dict` mutations
without a lock create race conditions:

```python
import threading
_cache_lock = threading.Lock()

def _get_cached(cache: dict, key: str, ttl: int, compute_fn):
    with _cache_lock:
        entry = cache.get(key)
        if entry and (time.time() - entry["ts"]) < ttl:
            return entry["data"]
        result = compute_fn()  # compute_fn must NOT hold the lock
        cache[key] = {"data": result, "ts": time.time()}
        return result
```

Lock scope: read + write as an atomic unit. Error states are **not cached** —
if `compute_fn` raises, the exception propagates naturally.

---

## 2c. Response Model Standards

### Rule: ALL endpoints must declare a Pydantic `response_model`

FastAPI 0.130 activated Pydantic Rust JSON serialization. Endpoints with a declared
Pydantic `response_model` receive ~2x JSON serialization speedup automatically. Raw
`dict` returns bypass this entirely.

### Required patterns

**Typed endpoint (preferred):**

```python
class TradeIdeaRow(BaseModel):
    player_a_id: str = Field(..., description="Seller player ID")
    player_b_id: str = Field(..., description="Buyer player ID")
    match_score: float = Field(..., description="CBA match quality 0-1")
    salary_diff: Optional[float] = Field(None, description="None if CBA-illegal")

@router.get("/trade-ideas", response_model=list[TradeIdeaRow])
def get_trade_ideas(...) -> list[TradeIdeaRow]:
    ...
```

**Generic mart endpoint (column schema varies by endpoint):**

```python
class MartResponse(BaseModel):
    rows: list[dict[str, Any]] = Field(..., description="Mart rows")
    count: int = Field(..., description="Row count")

@router.get("/market-scanner", response_model=MartResponse)
def get_market_scanner(...) -> MartResponse:
    ...
```

### Rules for Pydantic model fields

- `Optional[float]` for any nullable numeric — NaN becomes `null` in JSON (NEVER `.fillna(0)`)
- `Field(description=...)` on every field
- `model_config = {"json_schema_extra": {...}}` with realistic (not fake/random) example values
- Only expose publicly-derivable data — no model weights, calibration params, internal paths
- No backwards-compat shims: remove unused fields cleanly

---

## 2d. DuckDB Query Standards

### Prefer DuckDB over `pd.read_parquet()` for filtered reads

DuckDB pushes predicates into columnar scans — always use DuckDB for filtered reads,
never load full parquets into pandas and filter in Python:

```python
# CORRECT — predicate pushdown, scans only matching rows:
import duckdb
con = duckdb.connect()
rows = con.execute(
    "SELECT * FROM read_parquet(?) WHERE SEASON_ID = ? AND SIGNAL = ?",
    [str(path), season_id, signal]
).fetchall()

# WRONG — loads full 254K rows into memory then filters:
df = pd.read_parquet(path)
df = df[df["SEASON_ID"] == season_id]
```

### Large result sets: cursor with `fetchmany()`

For endpoints returning >500 rows, use cursor-based batched reads:

```python
cursor = con.execute("SELECT * FROM read_parquet(?) WHERE ...", [path])
cols = [d[0] for d in cursor.description]
while batch := cursor.fetchmany(500):
    for row in batch:
        yield MyModel(**dict(zip(cols, row)))
```

### Parameterized queries — no f-string interpolation

SQL injection risk: NEVER interpolate user input directly.
Use `con.execute(query, [param1, param2])` — DuckDB's native parameter binding.

```python
# WRONG — SQL injection risk:
sql = f"SELECT * FROM read_parquet('{path}') WHERE TEAM = '{team}'"

# CORRECT — parameterized:
sql = "SELECT * FROM read_parquet(?) WHERE TEAM = ?"
rows = con.execute(sql, [str(path), team]).fetchall()
```

### NaN in DuckDB results

DuckDB/pandas can surface missing numerics as `None`, `float('nan')`, `pd.NA`,
or `NaT`, depending on the fetch path.

- Typed Pydantic fields such as `Optional[float]` should carry missing numerics
  as JSON `null`.
- Raw `dict` / `list[dict]` payloads from `fetchdf().to_dict(orient="records")`
  are NOT automatically JSON-safe. Normalize them with
  `serialize_dataframe_records()` (or equivalent) before returning.
- Preserve missingness as `null` on the wire. Never `.fillna(0)` just to make
  serialization pass.

### Completed-game local-first rule

For completed games, endpoints must prefer local artifacts before any upstream API:

1. in-memory cache
2. Redis live cache
3. persisted DuckDB JSON/cache tables
4. DuckDB/parquet reconstruction from local gold or `nba.duckdb`
5. upstream API only on a true local miss

This rule is especially important for the NBA Games surface:

- `/games/{id}/leaders` must reuse the shared raw boxscore loader instead of calling `nba_api` independently.
- `/games/{id}/xfg_summary` and completed-game shot payloads must read `shot_xfg_predictions.parquet` first when `XFG_PROB` is already materialized.
- optional enrichments such as xFG/edge may fail independently, but they must not blank the parent response.

### Serving reads PROMOTED R2 artifacts only

Serving reads only **promoted** production artifacts — the R2-published
`basketball.duckdb` / `nba.duckdb` / domain parquets bootstrapped on container
boot, or their local equivalents on the producing machine. Serving must **never**
read from `.r2_staging/` (dev/candidate scratch) or from a dev laptop's working
tree. Those are not production truth; only the desktop production writer's
R2-promoted manifest is. If the local promoted DuckDB is missing **and** R2 is
unreachable, raise `503` — never serve `200 OK` with empty/default data (see
DATA_ENGINEERING §0.4 and
[LOCAL_FLEET_R2_WORKFLOW.md](../engineering/LOCAL_FLEET_R2_WORKFLOW.md)).

---

## 3. API Endpoint Reference

### Routers Registered in `api/app/main.py`

| # | Router | Prefix | Endpoints | Source |
|---|--------|--------|-----------|--------|
| 1 | NBA Prediction | `/api/v1/nba/*` | Player/team predictions | `api/app/routers/nba_endpoints.py` |
| 2 | NBA Data Explorer | `/api/v1/nba-data/*` | Shot charts, data explorer | `api/app/routers/nba_data_endpoints.py` |
| 3 | XFG% ML Pipeline | `/api/v1/xfg/*` | Expected FG% predictions; includes `GET /xfg/live-performance/{game_id}` (Session 369) — `LiveXFGPredictor` + `ShotChartDetail`; `live_predictor` global set by `db.py` lifespan | `api/app/routers/xfg_endpoints.py` |
| 4 | Player Leaderboard | `/api/v1/nba-data/leaderboard/*` | Tier rankings | `api/app/routers/leaderboard_endpoints.py` |
| 5 | Bayesian Prediction | `/api/v1/bayesian/*` | Bayesian model predictions | `api/app/routers/bayesian_endpoints.py` |
| 6 | Draft Picks | `/api/v1/draft-picks/*` | Draft power rankings | `api/app/routers/draft_endpoints.py` |
| 7 | Datasets Explorer | `/api/v1/datasets/*` | Dataset browsing | `api/app/routers/datasets_endpoints.py` |
| 8 | Lineup Analysis | `/api/v1/lineups/*` | 21 endpoints. Historical (4h TTL): `/leaderboard` (unified 1-5 man, opponent filter, pct/min filter, period/clutch/tempo joins), `/team/{id}`, `/team/{id}/roster`, `/team/{id}/form`, `/team/{id}/candidates`, `/player/{id}/vs/{oppId}`, `/group/matchup` (N-vs-M from stints), `/lineup/{id}/opponents`, `/grade-thresholds`, `/kpis`, `/teams`. Live (60s TTL): `/game/{id}/recommendations/{teamId}`, `/game/{id}/possession-form/{teamId}`, `/optimal`. Streaming: `/game/{id}/stream-recommendations/{teamId}` (SSE, `async def` — sole exception). Ops: `/ready`, `/diagnostics`. All others `def` (sync). All `response_model=` except 2 ops endpoints. Source: `lineup_serving.duckdb` (R2 bootstrap, 12 tables including `lineup_clock_profiles`, `lineup_period_stats`, and `lineup_clutch_stats`, ~75 MB). Scenario filters join on `(lineup_id, season, team_id, opponent_team_id, group_quantity)` and tempo thresholds are computed from the active leaderboard scope. Current daily publish contract restores 5-man opponent rows; deeper all-group opponent rebuilds remain offline/backfill work. `LINEUP_ALLOW_LIVE_API=0` on Railway. | `api/app/routers/lineup_endpoints.py` |
| 9 | LLM Proxy | `/api/v1/llm/*` | Claude, OpenAI, DeepSeek, Gemini | `api/app/routers/llm_proxy_endpoints.py` |
| 10 | Prospect Forecasting | `/api/v1/prospects/*` | `/health`, `/big-board`, `/big-board/{rank}`, `/backtest`, `/backtest/{year}` — v21 3-stage pipeline (v17a HistGBDT + RSF v21 + LTR v21), 10 leagues, pre-built JSON/parquet boards | `api/app/routers/prospect_endpoints.py` |
| 11 | Referee Analytics | `/api/v1/referees/*` | Referee tendencies, bias audit, game crew, live foul hazard (Phase 28b: conformal intervals via `RefereeHazardService`) | `api/app/routers/referee_endpoints.py` |
| 12 | G-League Pickup Forecasting | `/api/v1/pickup/*` | G-League player callup probability + quality tiers | `api/app/routers/pickup_endpoints.py` |
| 13 | GBDT Unified | `/api/v1/gbdt/*` | GBDT player eval predictions | `serving/api/gbdt_router.py` |
| 14 | Unified Serving | `/api/v1/serving/*` | All-model-type routing | `serving/api/router.py` |
| 15 | Player Game Predictions | `/api/v1/predictions/*` | daily-slate, game/{id}, game/{id}/results, player/{id}, health | `api/app/routers/predictions_endpoints.py` |
| 16 | Analytics (DuckDB) | `/api/v1/analytics/*` | 23 endpoints: player-value, market-scanner, trade-ideas, team, age-curves, CBA, pipeline-stage, backtest | `api/app/routers/analytics_endpoints.py` |
| 17 | Sentiment Analysis | `/api/v1/sentiment/*` | Multimodal sentiment, audio emotion, transcript map | `api/app/routers/sentiment_endpoints.py` |
| 18 | Ops / Schedule | `/api/v1/schedule/*` | Schedule, top performers, game cards | `api/app/routers/ops_endpoints.py` |
| 19 | Team-Controlled | `/api/v1/team-controlled/*` | Promotion boards + health (per-bucket HistGBDT) | `api/app/routers/pickup_endpoints.py` (`tc_router`) |
| 20 | Overseas Targets | `/api/v1/overseas/*` | International watchlist with LTR_SCORE, P_MADE_NBA, league strength | `api/app/routers/pickup_endpoints.py` (`overseas_router`) |
| 21 | Game Simulation | `/api/v1/sim/*` | Wave-based game simulation, live context, what-if | `api/app/routers/sim_endpoints.py` |
| 22 | News Intelligence | `/api/v1/news/*` | Morning report, forecast, evidence, reactions, journalist leaderboard, pipeline report, and `/news/kpis` freshness/range KPIs. Sync `def` handlers, DuckDB marts + JSON reactions store. KPI contract includes data-derived story date range, season range, latest-day story/forecast counts, approval rate, rejected count, and top story type so frontend freshness is visible without fabricated values. Anti-leakage enforced (no raw CI bounds, no CONFIDENCE_PERCENTILE in responses). | `api/app/routers/news_endpoints.py` |
| 23 | MCP Proxy | `/api/v1/mcp/*` | `/health`, `/tools`, `/call-tool` — proxies NBA MCP tool calls through backend (in-process, no SSE). 40 tools with real `input_schema` from FastMCP type annotations. Sync `def` handlers. | `api/app/routers/mcp_proxy_endpoints.py` |
| 24 | Player + Team Profiles | `/api/v1/profiles/*` | `GET /profiles/player/{id}` — bio + stat cards + valuation + projections (Session 523). `GET /profiles/player/{id}/season-history?until_season=<season>` — per-season breakdown (Session 577): DuckDB JOIN across `player_value_season.parquet` + `player_season_features.parquet` + `player_daily_scorecard.parquet`; response: `PlayerSeasonHistoryResponse` (player_id, seasons[]). `GET /profiles/team/{abbrev}` — team overview. Sync `def` handlers. `PlayerSeasonRow` + `PlayerSeasonHistoryResponse` Pydantic models. | `api/app/routers/profile_endpoints.py` |
| 25 | Fantasy Optimization | `/api/v1/fantasy/*` | `POST /leagues/import` — sync S0-S3 import pipeline, returns `LeagueImportResponse`. `GET /leagues/{id}/overview`, `draft-board`, `pickup-board`, `matchup-plan`, `season-plan` — DuckDB mart reads. `POST /leagues/{id}/recompute` — background thread S4-S12. `GET /jobs/{id}` — poll job status. 8 endpoints total. Sync `def` handlers, `response_model=` on all, 15 Pydantic models in `api/app/models/fantasy.py`. | `api/app/routers/fantasy_endpoints.py` |
| 26 | Injury & Availability | `/api/v1/injury/*` | `GET /injury/player/{id}` — full injury profile (status, health multipliers, season agg, bucket confidence). `GET /injury/player/{id}/history` — multi-season career history from `injury_season_agg.parquet`. Thread-local DuckDB, parameterized queries. Sync `def` handlers. `PlayerInjuryProfile` + `PlayerInjuryHistory` Pydantic models. 503 if parquet missing; 404 if player not found. Added Session 634. | `api/app/routers/injury_endpoints.py` |
| 27 | YouTube Highlights | `/api/v1/highlights/*` | `GET /highlights/games/{game_id}` returns game, team, and top-player clips for one game. `GET /highlights/games?date=YYYY-MM-DD` returns covered games for a date. `GET /highlights/players/{player_id}?date=YYYY-MM-DD` and `GET /highlights/teams/{team_id}?date=YYYY-MM-DD` return entity clips. `POST /highlights/cache/clear` clears the in-process cache after artifact refresh. Source: R2-hydrated `data/youtube_highlights/gold/products/{game_highlights,player_game_highlights,team_highlights}/season=*/date=*/data.parquet`; dbt mart is validation/analytics only. Current gold carries `PUBLISHED_AFTER`/`PUBLISHED_BEFORE` so serving artifacts preserve the same temporal contract V0 validated. Missing required game/player artifacts -> 503, missing game -> 404, missing optional entity/date rows -> empty collection. | `api/app/routers/youtube_highlights_endpoints.py` |
| 28 | Ingest Status | `/api/v1/ingest/*` | `GET /ingest/freshness` — dual-timestamp per source (fetch_staleness, validation_staleness) + latest quality snapshot (row_count, min/max event date, null_counts, distinct/duplicate key counts, stale_partition_flag) from `ingest.artifact_quality`. `GET /ingest/circuits` — per-source circuit breaker state. `GET /ingest/summary` — aggregate rollup (green/degraded/red) for dashboard one-glance view; includes `blocking_stale` list of sources that would fail `upload_data.sh --validate`. `GET /ingest/summary/fetch` (PR 13) — fetch-only sibling that ignores `validation_red` (for Phase 1 when manifest-promotion isn't wired; see DATA_ENGINEERING_PIPELINE §26.12). `GET /ingest/inventory` (PR 8) — one row per registered source with full ops metadata: cadence/pool/owner/blocking + `fetcher_registered` (flags YAML-without-fetcher gaps) + `airflow_dag_id`+`airflow_ui_url` deep-link + `run_stats` (last, previous, avg, p95 duration from `ingest_jobs`) + latest quality + circuit state + GPU spec + GPU actuals. `GET /ingest/gpu-jobs` (PR 8) — flat GPU-job inventory joining `gpu_job_specs.yaml` with `ingest.gpu_job_runs` actuals (last run, avg runtime, avg cost). `GET /ingest/dag-observability` — admin-gated DAG-level operations ledger for the `/admin` DAGs tab: latest state/stage, rows/bytes, min/max event dates, null summary, data-derived NaN spike, GPU use/cost, last error stage, recent-run drilldown, daily/weekly/monthly KPI summaries including `total_duration_seconds`, no-store response. **`async def`** — asyncpg to Railway Postgres `ingest.*` schema (operational control-plane, never joined to dbt marts per DATA_ENGINEERING_PIPELINE §26.2). All endpoints declare `response_model=`. 503 on DB unreachable (not empty list). Originally PR 3; extended with `/inventory` + `/gpu-jobs` in PR 8 and `/dag-observability` on 2026-04-28. | `api/app/routers/ingest_status.py` |
| 29 | ODDS | `/api/v1/odds/*` | Health, artifact inventory, source contracts, coverage, bookmaker, and provider-profile endpoints. Reads promoted ODDS gold/features/reports from R2/local artifacts only; Railway never runs bronze/silver/gold ODDS stages. Missing artifacts return explicit unavailable states instead of fake rows. | `api/app/routers/odds_endpoints.py` |
| 30 | Sportsbook | `/api/v1/sportsbook/*` | Source catalog, market snapshots, settlement, odds comparison, CLV, arbitrage, Strategy Lab, opportunity ledger, season tracker, and book quality. `/sportsbook/sources` scans B9/B12/B13/B14/B16 for source/provider/book/product provenance; `/sportsbook/markets` remains the internal Betts board. B12/B13/B14/B16 read validated ODDS gold products through the Sportsbook adapter; Strategy Lab frontend receives typed JSON-safe rows and explicit empty/missing states. | `api/app/routers/sportsbook_endpoints.py` |
| 31 | Computer Vision | `/api/v1/cv/*` | ~20 typed routes: `/health`, `/games/{game_id}/tracks` · `/shots` · `/player-id-resolution`, `/players/{nba_player_id}/kinematics`, `/review[/{run_id}[/frames[/{idx}]]]` + `/review/{run_id}/artifacts/{id}` (stage-review surface), `/models[/{id}]`, `/uploads` (operator lane), `/jobs` + `/jobs/run-config` (async job control). Sync `def` handlers, all `response_model=`, NaN→JSON null, read-only from CV gold/duckdb; 404 missing entity / 503 missing artifact. Z-bearing marts (pose_3d/biomechanics) serve only with explicit `Z_STATUS` (`weak` exposed, never silently treated as solved); broadcast clips are rights-blocked from R2 so Railway serves operator-clip gold only. See `docs/backend/projects/CV_PIPELINE.md` §9. | `api/app/routers/cv_endpoints.py` |

> **Note**: Forecasting router (`/api/v1/forecasting/*`) was **removed in v30.6** — legacy forecasting modules archived, no active consumers.

### Unified Serving Endpoints (`/api/v1/serving/*`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/models` | GET | List all models (filter by type/target/champions_only) |
| `/models/{type}/{target}/champion` | GET | Get champion for specific type + target + granularity |
| `/predict` | POST | Route prediction to appropriate backend (Bayesian/GBDT/XFG) |
| `/health` | GET | Health check across all services |
| `/model-types` | GET | List supported model types (bayesian, xfg, gbdt) |
| `/refresh-manifest` | POST | Rescan artifacts directory and rebuild manifest |

### GBDT Endpoints (`/api/v1/gbdt/*`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/models` | GET | List GBDT models (filter by target/granularity) |
| `/models/{target}/{granularity}/champion` | GET | Get GBDT champion model |
| `/predict` | POST | Generate GBDT predictions |
| `/targets` | GET | List valid targets (14 total) |
| `/granularities` | GET | List valid granularities (4 total) |
| `/feature-importance/{target}/{granularity}` | GET | Top-N feature importance |
| `/health` | GET | GBDT service health |

### Player Value Endpoints (`/api/v1/player-value/*`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/model-info` | GET | AAV model metadata (Bayesian or GBDT) |
| `/compare-models` | GET | Side-by-side Bayesian vs GBDT metrics |
| `/scorecard` | GET | S10 surplus scorecard (BUY/SELL/HOLD signals) |
| `/trade-signals` | GET | S11 rolling divergence signals |
| `/trade-recommendations` | GET | S13 CBA-compliant trade pairs |
| `/projections` | GET | SCHOENE forward projections |
| `/dashboard` | GET | S14 consensus multi-signal view |

### Health & Readiness Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/health` | GET | Basic health (always 200 if running) |
| `/api/v1/ready` | GET | Readiness check (models loaded?) |
| `/api/v1/ready/frontend` | GET | Lightweight readiness for React SPA |
| `/api/v1/ready/full` | GET | Extended readiness with env drift audit |
| `/api/v1/ready/serving` | GET | **Deep serving readiness**: manifest parseable, GBDT + Bayesian champions present |
| `/api/v1/serving/health` | GET | ML serving layer health (all backends) |
| `/api/v1/gbdt/health` | GET | GBDT-specific health |
| `/metrics` | GET | Prometheus metrics scrape endpoint |

---

## 4. Model Registry & Discovery

### Two-Tier System

```
 Training Time                              Serving Time
+--------------------------+              +---------------------------+
| MLflow Experiment Logs   |              | UnifiedModelRegistry      |
| - metrics, params, tags  |              | - Scans serving/artifacts/|
| - model signatures       |              | - Builds model_manifest   |
| - artifact lineage       |              | - Caches loaded models    |
| DB: mlflow.db            |              | File: model_manifest.json |
+--------------------------+              +---------------------------+
       (tracking)                              (discovery + loading)
```

### UnifiedModelRegistry (`serving/registry/unified_registry.py`, 535 LOC)

**Purpose**: Discover and load ALL model types from `serving/artifacts/`.

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `list_models(model_type, target, granularity, champions_only)` | Filter models by criteria |
| `get_champion(model_type, target, granularity)` | Get production champion model |
| `load_model(model_id)` | Load from cache or disk |
| `register_model(metadata, artifact)` | Save new model + update manifest |
| `promote_to_champion(model_id, metrics)` | Demote old, promote new |
| `refresh_manifest()` | Rescan artifacts (POST `/refresh-manifest`) |
| `get_model_counts()` | Returns count by type |

**ModelMetadata Fields**:

```python
@dataclass
class ModelMetadata:
    model_id: str           # Unique identifier
    model_type: str         # "bayesian" | "xfg" | "gbdt"
    target: str             # "PTS", "AST", "AAV_PCT_CAP", etc.
    granularity: str        # "player_game", "player_season", etc.
    version: str            # Timestamp or version number
    is_champion: bool       # True if production model
    artifact_path: str      # Absolute path to model file
    metrics: dict           # Training metrics (R2, MAE, etc.)
    created_at: str         # ISO timestamp
    mlflow_run_id: str      # Optional link to MLflow run
    model_family: str       # "negbin", "beta", "xgboost", etc.
```

**Model Discovery Rules**:

| Model Type | Filename Pattern | Metadata Source |
|------------|-----------------|-----------------|
| Bayesian | `{family}_{target}_{granularity}_{timestamp}[_champion].pkl` | Parsed from filename |
| XFG | `xfg_model_{season}.joblib` (service-discoverable format; `xfg_champion_{season}.joblib` also written as dual-save) | Parsed from filename |
| GBDT | `{target}_{granularity}/champion/model.joblib` | `metadata.json` in same dir |

**Manifest** (`serving/registry/model_manifest.json`):
- Auto-generated on registry init or `refresh_manifest()`
- ~92 models across Bayesian (80), XFG (12 champion seasons), GBDT (growing)

---

## 5. Model Artifacts & Storage

### Directory Layout

```
serving/artifacts/
  bayesian/
    player_game/                    # 80 PKL files (~636MB)
      negbin_PTS_playergame_20250219_..._champion.pkl
      negbin_AST_playergame_20250219_..._champion.pkl
      ...
    player_season_aav/              # AAV_PCT_CAP Bayesian model
      training/PLAYER_SEASON_AAV/
        champion/                   # Production champion
    traces/                         # 13 NetCDF files (~7.7GB)
      negbin_PTS_playergame_20250219_..._trace.nc
      ...
  xfg/                              # 35 joblib files (~438MB): 12 xfg_model_*.joblib (service-discoverable), 12 xfg_champion_*.joblib (dual-save), 11 xfg_champion_full_*.joblib, 1 test
    xfg_model_2024-25.joblib
    ...
  gbdt/                             # Per target-granularity dirs
    PTS_PLAYER_GAME/
      champion/
        model.joblib                # Trained model (joblib wrapper)
        model.xgb.json              # XGBoost native format (when XGBoost champion)
        metadata.json               # Version, metrics, timestamps, lineage
        features.json               # Feature list used
        conformal_quantiles.json    # Conformal prediction intervals
        training_stats.json         # Training statistics
        model_contract.json         # Typed input schema (col -> dtype); included in checksums
    AAV_PCT_CAP_PLAYER_SEASON/
      champion/
        ...
```

**Team-controlled model artifacts** (separate from GBDT/Bayesian/XFG serving):
```
cache/models/team_controlled_v1/
  nba_active/
    model.pkl                         # HistGBDT per bucket
    imputer.pkl                       # SimpleImputer (for NaN features)
    metadata.json                     # trainability results, selected features, metrics
  nba_returnee/
    model.pkl
    imputer.pkl
    metadata.json
  draft_rights/
    model.pkl
    imputer.pkl
    metadata.json
```
No model directory for overseas targets (reuses prospect pipeline artifacts: `cache/models/registry.json`, `cache/models/ltr_ranker_v21.json`).

**Prospect model artifacts** (used by prospect + overseas endpoints):
```
cache/models/
  registry.json                           # Version registry (v10-v21, deployed=v21)
  survival_rsf_v21.pkl                    # RSF (keys: "model", "features"), C-index=0.840
  ltr_ranker_v21.json                     # XGBoost rank:ndcg, P@10=98.6%
  prospect_v17a/                          # Stage 1: 6 GBDT (3 position groups x 2 tiers)
```

**XGBoost native format**: when a GBDT champion uses XGBoost, `model.xgb.json` is saved alongside `model.joblib`. `GBDTPredictor.load_champion()` prefers the native file on load -- native XGBoost JSON is forward-compatible across XGBoost versions, unlike pickle. The joblib wrapper is kept as a fallback for non-XGBoost models (LightGBM, CatBoost) and for older champion artifacts.

### GBDT metadata.json Fields

```json
{
  "target": "PTS",
  "granularity": "PLAYER_GAME",
  "version": "s12345678_m9abcdef0",
  "schema_hash": "12345678abcdef0...",
  "metrics": {"rmse": 3.45, "mae": 2.67, "r2": 0.612},
  "feature_cols": ["PTS_ROLL10_MEAN", "..."],
  "n_features": 18,
  "feature_order_hash": "a3f9b2c1d4e5f6a7",
  "model_type": "xgboost",
  "timestamp": "2026-02-24T14:32:18",
  "git_sha": "d02bdc2",
  "python_version": "3.12.4",
  "platform": "Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.35",
  "library_versions": {"sklearn": "1.5.2", "xgboost": "2.1.4", "numpy": "2.2.0", "pandas": "2.1.5"},
  "artifact_checksums": {
    "model.joblib": "e3b0c44298fc1c149...",
    "features.json": "a87ff679a2f3e71d9...",
    "training_stats.json": "8277e0910d750195...",
    "conformal_quantiles.json": "d3b07384d113edec...",
    "model_contract.json": "f4d4c9d82af4ba3e..."
  }
}
```

**Lineage fields** (`git_sha`, `python_version`, `platform`, `library_versions`): saved at promotion time; enable full reproducibility -- you can reconstruct exactly which code, Python version, OS, and dependency versions produced any champion model.

**`n_features` and `feature_order_hash`**: `n_features` is a quick sanity check (do we have the right number of features?). `feature_order_hash` is SHA256 of `sorted(feature_cols)` -- detects if the feature set changed between training and loading without comparing all 30+ feature names.

**`artifact_checksums`**: SHA256 hex digests for every data file in the champion directory. Written last (after all data files exist). Verified at load time by `GBDTPredictor.load_champion()` -- raises `RuntimeError` if any file is tampered or corrupt. The metadata.json file itself is NOT in the checksums (it would be self-referential).

**Schema hash validation on load**: when `GBDTPredictor.load_champion()` runs, it reads `schema_hash` from `metadata.json`, recomputes a hash of the current granularity YAML schema, and logs a warning if they differ. This catches the case where the feature schema was updated after a champion was promoted:

```
WARNING: Schema mismatch for PTS: champion trained with schema abc123,
current schema is def456. Consider retraining.
```

Mismatches are non-blocking (warnings, not errors) because serving must continue. The warning is a prompt to retrain with the updated schema.

### Dual-Save Pattern (GBDT)

When a new GBDT champion is promoted, artifacts are saved to **three** locations:
1. `api/src/ml/modeling/gddt/training/{GRAN}/{TARGET}/champion/` (current champion)
2. `api/src/ml/modeling/gddt/training/{GRAN}/{TARGET}/champion_{version}/` (version history for rollback)
3. `serving/artifacts/gbdt/{TARGET}_{GRANULARITY}/champion/` (serving)

This ensures the serving layer always has the latest champion, training history is preserved, and rollback is always available.

### Total Artifact Size: ~13.5 GB

| Type | Count | Size |
|------|-------|------|
| Bayesian PKL | 80 | ~636 MB |
| Bayesian NetCDF (traces) | 13 | ~7.7 GB |
| XFG joblib | 35 | ~438 MB |
| GBDT (varies) | growing | ~100 MB per target |

---

## 6. Prediction Flow

### Request Lifecycle

```
HTTP POST /api/v1/gbdt/predict
  |
  v
RequestIDMiddleware       --> UUID assigned, stored in contextvars
  |
  v
PrometheusMiddleware      --> Start timer
  |
  v
PredictionLogger          --> Recognized as prediction endpoint
  |
  v
gbdt_router.predict()    --> Validates request
  |
  v
GBDTService.predict()    --> Gets champion from registry
  |                           Loads model (cached or from disk)
  |                           model.predict(observations)
  v
Response                  --> X-Request-ID header added
                              Prometheus latency recorded
                              Prediction logged to predictions.jsonl
```

### GBDT Prediction Request

```bash
curl -X POST http://localhost:8000/api/v1/gbdt/predict \
  -H "Content-Type: application/json" \
  -d '{
    "target": "PER",
    "granularity": "PLAYER_SEASON",
    "observations": {
      "PTS_LAG1": [25.5, 22.3],
      "AST_LAG1": [6.2, 4.1]
    }
  }'
```

**Response**:
```json
{
  "predictions": [25.3, 22.1],
  "target": "PER",
  "granularity": "PLAYER_SEASON",
  "model_info": {
    "model_id": "gbdt_PER_PLAYER_SEASON_champion",
    "version": "20260220",
    "metrics": {"r2": 0.794, "mae": 0.027}
  },
  "n_samples": 2
}
```

### Unified Prediction Request (Routes by model_type)

```bash
curl -X POST http://localhost:8000/api/v1/serving/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model_type": "gbdt",
    "target": "PER",
    "granularity": "PLAYER_SEASON",
    "observations": {"PTS_LAG1": [25.5]}
  }'
```

### Prediction Features by Pipeline

| Feature | Bayesian | GBDT | XFG |
|---------|----------|------|-----|
| Point predictions | Yes | Yes | Yes |
| Credible intervals | Yes (posterior) | No | Yes (Binomial posterior CIs: 91.4% coverage, 45.0% shrinkage; per-player attempt-weighted aggregation in leaderboard) |
| Conformal intervals | No | Yes [50,80,90,95,99]% | No |
| Drift detection | Planned | Yes (z-score > 2.0) | No |
| Uncertainty | Full posterior | Conformal | No |

---

## 6b. Response Pattern Decision Guide

### When to use each pattern

| Pattern | When | FastAPI mechanism | Content-Type |
|---------|------|------------------|-------------|
| Standard JSON | <50 rows; single records; frontend `response.json()` consumers | `response_model=PydanticModel` | `application/json` |
| **NDJSON Streaming** | >500 rows; bulk data; progressive frontend rendering; script/API consumers | `-> Iterable[Model]` or `-> AsyncIterable[Model]` | `application/x-ndjson` |
| **SSE** | Real-time push; live game events; heartbeats; client-initiated `EventSource` | `StreamingResponse(media_type="text/event-stream")` | `text/event-stream` |

### Streaming NDJSON — code templates

**Sync generator (DuckDB reads — most common):**

```python
from collections.abc import Iterable
import duckdb

_STREAM_BATCH_SIZE = 500  # from config — not hardcoded in handler

@router.get("/market-scanner/stream")
def stream_market_scanner(season: Optional[str] = Query(None)) -> Iterable[MarketScannerRow]:
    con = get_analytics_db()  # raises 503 if DB unavailable
    cursor = con.execute(
        "SELECT * FROM main_marts.mart_market_scanner WHERE SEASON = ? ORDER BY PROD_SURPLUS_ZSCORE DESC",
        [season]
    )
    cols = [d[0] for d in cursor.description]
    while batch := cursor.fetchmany(_STREAM_BATCH_SIZE):
        for row in batch:
            yield MarketScannerRow(**dict(zip(cols, row)))
```

**Sync generator with 404 on empty (for required data):**

```python
@router.get("/prospect-board/stream")
def stream_prospect_board(year: int = Query(...)) -> Iterable[ProspectBoardRow]:
    con = get_analytics_db()
    cursor = con.execute("SELECT * FROM mart_prospect_big_board WHERE BOARD_YEAR = ?", [year])
    cols = [d[0] for d in cursor.description]
    first_batch = cursor.fetchmany(_STREAM_BATCH_SIZE)
    if not first_batch:
        raise HTTPException(status_code=404, detail=f"No data for year={year}")
    for row in first_batch:
        yield ProspectBoardRow(**dict(zip(cols, row)))
    while batch := cursor.fetchmany(_STREAM_BATCH_SIZE):
        for row in batch:
            yield ProspectBoardRow(**dict(zip(cols, row)))
```

**Sync generator from parquet (predictions cache):**

```python
@router.get("/daily-slate/stream")
def stream_daily_slate(date: Optional[str] = Query(None)) -> Iterable[PlayerPrediction]:
    prediction_date = date or _today_et()
    df = _load_cache(prediction_date)  # raises 404 if missing/stale — no empty generator
    has_opponent = "OPPONENT_ID" in df.columns
    for row in df.itertuples(index=False):
        opp = str(row.OPPONENT_ID) if has_opponent and pd.notna(row.OPPONENT_ID) else None
        yield PlayerPrediction(
            player_id=str(row.PLAYER_ID),
            ...
            std=float(row.STD) if pd.notna(row.STD) else None,  # NaN -> null via Optional[float]
        )
```

### Client consumption (fetch + ReadableStream)

```javascript
const response = await fetch('/api/v1/analytics/market-scanner/stream?season=2024-25');
const reader = response.body.getReader();
const decoder = new TextDecoder();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  decoder.decode(value).split('\n').filter(Boolean).forEach(line => {
    const row = JSON.parse(line);  // render immediately — no wait for full response
  });
}
```

### SSE canonical example (existing lineup endpoint)

See `api/app/routers/lineup_endpoints.py` — this is the reference implementation for live push.
**Do NOT use SSE for bulk data downloads.** SSE = live push only.

### Streaming + ConcurrencyLimiter

The existing semaphore (max 4 concurrent heavy requests) is acquired when the generator
starts yielding its first item and released when the generator is exhausted or the client
disconnects. No change needed for streaming endpoints.

### Streaming + PredictionLogger

For streaming prediction endpoints, `PredictionLogger` middleware logs once per request
(at connection start). Prometheus `prediction_count` increments per yielded item.

---

## 6c. New Endpoint Development Checklist

Before merging any new endpoint, verify ALL of the following:

**Handler type:**
- [ ] I/O-bound handler is `def` (sync), NOT `async def`
- [ ] If `async def`, all awaited calls are genuinely async (httpx, Redis async, anyio)
- [ ] No `pd.read_parquet()` or `duckdb.execute()` called from `async def` without executor
- [ ] Lifespan/background bootstrap does not run blocking MLflow/model-loading work on the main event loop before the socket opens; heavy warmup uses an executor/thread and serving starts first

**Response model:**
- [ ] `response_model=PydanticModel` declared (or `-> PydanticModel` annotation)
- [ ] No raw `dict` returns (bypasses Pydantic Rust speedup)
- [ ] Nullable numeric fields typed `Optional[float]` (NaN -> null; NO `.fillna(0)`)
- [ ] Any DataFrame / DuckDB `list[dict]` payload is normalized to JSON-safe primitives before return (`NaN`/`pd.NA`/`NaT` -> `null`)
- [ ] All fields have `Field(description=...)` annotation
- [ ] `model_config = {"json_schema_extra": {...}}` with realistic (non-fake) example values

**Data safety:**
- [ ] Response contains only publicly-derivable data (NBA Stats, BBRef, Spotrac)
- [ ] No model weights, calibration params, feature importances, or internal paths exposed
- [ ] SQL queries parameterized — no f-string interpolation of user input
- [ ] Completed-game endpoints use a local-first source order before any upstream API call
- [ ] Backing marts use the canonical internal temporal key (`SEASON_ID`, `GAME_DATE`, etc.); legacy aliases are applied only at the final response edge if needed
- [ ] The serving mart is built from a fully prepared gold contract; required upstream enrichments are present and were not skipped by a partial prep wrapper
- [ ] For temporal models, the served payload or backing mart exposes prediction provenance (`holdout_eval` vs forward/current-season serving) and the training cutoff season if current/future periods are included
- [ ] Champion selection validates the loaded artifact contract, not only stored metrics; an invalid legacy artifact is not retained as the serving champion
- [ ] Production diagnostics compare aligned units (rate-to-rate, count-to-count); no reconstructed count thresholds from stripped artifacts
- [ ] A forward-serving temporal model either preserves its schema-declared temporal effect or fails validation explicitly; it does not silently serve as non-temporal

**Error codes (no defensive fallbacks):**
- [ ] Missing data -> `404` (not empty 200)
- [ ] Model/artifact not loaded -> `503` (not silent empty response)
- [ ] Policy-gated feature -> `403` (not empty response)
- [ ] No `except: pass` or `except Exception: return {}`
- [ ] Optional sub-payload failure does not erase a valid parent payload

**Streaming decision:**
- [ ] >500 rows -> streaming endpoint added (`Iterable[T]` variant)
- [ ] Real-time push -> SSE (not streaming NDJSON)
- [ ] Streaming endpoint raises `404` before yielding first item if data is missing (not empty generator)

**Auth:**
- [ ] Public endpoint added to `public_endpoint_baseline.txt` (CI fails if new public endpoints appear without being baselined)
- [ ] Internal/protected endpoint has JWT dependency declared

**Prometheus/logging:**
- [ ] Heavy endpoint added to `heavy_endpoints` set in `concurrency.py` if compute-intensive
- [ ] Prediction endpoint URL prefix added to `PredictionLogger` matching set if applicable
- [ ] Local dev transport contract is aligned end-to-end: frontend origin allowed in `ALLOWED_ORIGINS`, and the configured frontend API base matches the actual backend port
- [ ] Artifact publish logs record the actual retrain backend/runtime when backend-dependent behavior matters (for example `jax` `cuda` vs `cpu`), rather than inferring it from container name or visible hardware alone

## 6d. Serving Promotion Gate

When a new DAG, artifact family, or model retrain starts feeding a served API
surface, the serving rollout must pass these gates in order:

**Gate 1 -- Prove the artifact contract locally**
- The upstream pipeline has completed one clean full local DAG run.
- The produced artifact passes its validation gate and matches the serving
  schema expected by the router, mart, or model loader.
- If the artifact depends on GPU retraining, publish the actual runtime/backend
  evidence (`jax.default_backend()`, device list, library versions, or
  equivalent) with the build logs.
- If the artifact depends on local GPU or Ollama work, the producing DAG tasks
  must use the single-slot `gpu_exclusive` Airflow pool and, for direct
  dispatcher/subprocess paths, the shared GPU process lock. Serving promotion is
  not considered ready if the GPU producer can overlap another GPU DAG.
- The Airflow pool the producing DAG uses must be declared in
  [`_workload_bands/pool_registry.py`](../../../api/src/airflow_project/dags/_workload_bands/pool_registry.py)
  or derivable from `sources.yaml` via `_workload_bands/source_limits.py`. Pool
  changes follow [`DATA_ENGINEERING_PIPELINE.md` §0.19](../engineering/DATA_ENGINEERING_PIPELINE.md#019-phase-2-workload-band-capacity-enforcement-2026-05-04)
  WB8/WB10. Serving promotion does not validate band correctness — that is the
  upstream responsibility of WB14's audit — but a DAG whose pool name is
  unknown to the registry must not be promoted.

**Gate 2 -- Prove the backend locally**
- `GET /api/v1/health` is green against the new artifact set.
- Affected endpoints return the expected typed shapes and correct `404`/`503`
  behavior when data/artifacts are absent.
- Existing endpoints that share `basketball.duckdb` or the same model registry
  still succeed; no silent regression is acceptable.

**Data-pipeline serving handoff**

Every DAG-backed serving surface must document the handoff before it is exposed
or unpaused:

| Item | Required contract |
|------|-------------------|
| Source | The endpoint reads only promoted gold/product artifacts, `basketball.duckdb`, `nba.duckdb`, or a declared serving DuckDB. Railway does not run bronze/silver/gold stages. |
| Remote DuckDB / Quack | Quack or any other remote DuckDB protocol is internal/admin infrastructure only unless separately approved. Public product traffic still goes through FastAPI routers with `response_model=`, freshness checks, auth policy, and documented 404/503 behavior. |
| Manifest | The R2 manifest key/domain version, artifact checksum, producer DAG, producer git SHA, and validation report path are known. |
| Freshness | The readiness or freshness endpoint reports the same max event date / partition coverage that the validation gate approved. |
| Shape | The router declares `response_model=` and the table/model loader validates required columns before returning data. |
| Missing data | Missing artifact/model -> `503`; missing entity/game/date -> `404` or an explicit empty collection when that is the documented product contract. No fake rows, fake probabilities, or silent fallback artifacts. |
| Serialization | NaN/Inf never cross REST/SSE JSON; internal missingness is converted to JSON `null` at the response boundary. |
| Reload | Artifact hot reload happens through the manifest poller or an approved admin reload after R2 promotion, not by shell-patching Railway containers. |
| Rollback | Previous Railway deployment, previous R2 manifest, and previous champion/model artifact are identified before cutover. |

**Cross-domain overview/KPI surfaces (2026-04-29)**

- Dashboard rollups such as `/api/v1/overview/platform` must not depend on one
  cross-domain mart unless that mart is part of the current serving contract and
  all upstream owners are green. If one optional rollup is disabled, query each
  domain-owned serving source directly and surface failures per domain.
- A missing optional KPI should remain `null` with a specific diagnostic key
  (for example `payload.errors["xfg_kpis"]`), while unrelated cards keep their
  real values. Do not fabricate zeros or reuse stale values to fill cards.
- If a KPI needs data not bootstrapped to Railway, add a domain-owned small mart,
  manifest field, or validated JSON metadata artifact; do not make the frontend
  infer training-row counts from unrelated board sizes.

**ODDS -> Sportsbook serving handoff (2026-04-28)**

- `/api/v1/odds/*` serves promoted ODDS artifacts and source-contract
  metadata. It does not trigger provider fetches.
- `/api/v1/sportsbook/*` serves Sportsbook gold products. B12 odds
  comparison, B13 CLV, B14 arbitrage/deviation, and B16 book quality consume
  ODDS gold through `odds_gold_adapter.py`.
- Missing ODDS/Sportsbook artifacts are 404/503 or documented empty states.
  Do not create default CLV, arbitrage, book-quality, or frontend evidence
  rows to make a panel look populated.
- Strategy Lab Cross-Book panels are presentation over B13/B14/B16 artifacts.
  Bettor-level book/casino attribution requires canonical book keys in replay
  products before it can be served.
- Game-level Sportsbook serving must carry the selected snapshot date through
  frontend hooks and `/sportsbook/game/{game_id}?date=YYYY-MM-DD`; Live/Games
  panels and the Sportsbook tab should read the same date contract instead of
  silently falling back to today's snapshot.
- Sportsbook source discovery must come from `/sportsbook/sources`, not from
  `/sportsbook/markets`. The board endpoint is B9 internal grain; external
  providers/books live in B12/B13/B14/B16 products. External source filters
  should route to comparison/CLV/arbitrage/book-quality surfaces and must not
  synthesize external rows into GAME/TEAM/PLAYER board tabs.
- ODDS package budgets and provider season gates are offline/operator reports
  (`reports/odds/planning/monthly_package_budget*.json`) and DAG contracts;
  serving endpoints must not inspect provider keys, call The Odds API, or infer
  missing markets from budget estimates.
- R2 promotion uses `bash scripts/upload_data.sh --skip-core --odds` and
  `bash scripts/upload_data.sh --skip-core --sportsbook` as separate
  single-writer passes after dry-run and validation. Never remove the active
  upload lock.

**Gate 3 -- Prove the frontend contract locally**
- If the surface is user-facing, the frontend build passes and the affected
  flows render against the local backend without contract drift.
- New artifact-backed states must not masquerade as success; if data is not
  ready, the UI should receive a real empty/error contract, not fake defaults.

**Gate 4 -- Prove the rollout in Railway staging**
- Deploy the working tree with `railway up` and validate real R2/Redis/Railway
  behavior before production.
- Confirm artifact bootstrap and freshness (`/api/v1/ops/freshness` or the
  relevant readiness endpoint), plus endpoint smoke checks and CORS.
- A staging build that only works after a manual shell patch is not promotable.

**Gate 5 -- Cut over to production carefully**
- Promote during the approved deployment windows unless this is a hotfix.
- Push code first, then promote data/artifacts via the single-writer R2 path.
- Re-check health, freshness, and the affected endpoint family immediately after
  cutover before considering the rollout complete.

**Gate 6 -- Keep rollback immediate**
- The previous Railway deployment, previous R2 manifest, and previous champion
  artifact version must be known before cutover.
- If a gate fails, revert or pause the schedule; do not leave the frontend or
  backend serving a partially proven artifact.

**Serving-ready-to-unpause interpretation**
- If the new artifact is fed by a scheduled DAG, the serving surface is not
  considered live until the upstream DAG clears its ready-to-unpause checklist.
- Incidents and alerts should use the shared root-cause taxonomy
  (`scheduler`, `queue`, `claim`, `fetch`, `validation`, `artifact_write`,
  `promotion`, `gpu_dispatch`, `training`, `serving_refresh`) so backend and
  data-engineering operators are talking about the same failure stage.
- For retrain-backed artifacts, the serving plane trusts only runtime-derived
  backend proof recorded during the build, not assumptions about local GPU,
  pod GPU, or container naming.

---

## 7. Champion-Challenger System

### Bayesian Champion-Challenger

- **Ranking metric**: ELPD (Expected Log Pointwise Predictive Density)
- **3-tier system**: Champion > Challenger > Baseline
- **Automatic switching**: If challenger ELPD > champion ELPD (with severity levels)
- **Convergence gates**: R-hat < 1.04, ESS > 200, divergences < 1%, BFMI > 0.30
- **Implementation**: `api/src/ml/modeling/bayesian/champion_challenger_system.py` (659 LOC)

### GBDT Champion-Challenger

- **Ranking metric**: Configurable per target (R2, MAE, RMSE) via `gbdt_master_schema.yaml`
- **Promotion**: New model must beat existing champion on the promotion metric
- **Version history**: Previous champions preserved with timestamps
- **Rollback**: Load any previous version by path
- **Dual-save**: Training dir + serving dir updated atomically
- **Artifact integrity**: SHA256 checksums computed for all data files and embedded in `metadata.json`; verified by `GBDTPredictor.load_champion()` -- `RuntimeError` raised on mismatch
- **Extended lineage**: `python_version`, `platform`, `n_features`, `feature_order_hash` saved alongside `git_sha` and `library_versions`
- **Implementation**: `api/src/ml/modeling/gddt/diagnostics/champion_challenger.py`

### Promotion Flow

```
Training Pipeline
  |
  v
Train new model --> Evaluate on test set
  |
  v
Compare vs champion --> metric_new > metric_champion?
  |                          |
  No: keep champion          Yes: promote
                               |
                               v
                             Save to training/{target}/champion/
                             Save to serving/artifacts/gbdt/{target}/champion/
                             Update metadata.json (version, metrics, timestamp)
                             Log to MLflow (mlflow.log_metrics, mlflow.log_artifact)
```

---

## 8. MLflow Integration

### Training-Time Logging

MLflow is used for **experiment tracking and lineage** -- NOT for model loading at serving time.

#### Bayesian Pipeline (`bayesian_trainer_core.py:5167-5220`)

```python
mlflow.log_metrics({
    "max_rhat": float(convergence_result.get("max_rhat", 1.0)),
    "min_ess_bulk": ...,
    "min_ess_tail": ...,
    "train_r2": ...,
    "test_r2": ...,
})
mlflow.log_metric("ppc_coverage_95", ...)
mlflow.log_params({"target": target, "granularity": granularity, ...})
```

#### GBDT Pipeline (`gddt/trainer.py:1509-1700`)

```python
mlflow.sklearn.log_model(
    self.model.model,
    artifact_path="model",
    signature=signature,
    input_example=input_example,
)
mlflow.log_metrics(safe_metrics)
mlflow.log_artifact(str(importance_path), "feature_importance")
mlflow.log_artifact(str(conformal_path), "conformal")
mlflow.log_artifact(str(training_stats_path), "training_stats")
```

### MLflow Database

- **Location**: `sqlite:///workspace/serving/registry/mlflow.db`
- **Start UI**: `mlflow ui --backend-store-uri sqlite:///workspace/serving/registry/mlflow.db`
- **Production store**: `file:/data/mlruns` (Railway `/data` volume)

### Why Not MLflow for Model Loading?

The filesystem champion system already handles:
- Version tracking (timestamped directories)
- Rollback (previous champion preserved)
- Dual-save (training/ + serving/ directories)
- Fast loading (direct joblib/pickle, no MLflow overhead)

MLflow complements for tracking; filesystem handles fast serving.

---

## 9. Health & Monitoring

### API Health Endpoints

| Endpoint | What It Checks |
|----------|---------------|
| `GET /api/v1/health` | Server running (always 200) |
| `GET /api/v1/ready` | Models loaded |
| `GET /api/v1/ready/frontend` | Lightweight check for React SPA |
| `GET /api/v1/ready/full` | Full readiness + env drift audit |
| `GET /api/v1/ready/serving` | **Deep serving probe**: manifest parseable, GBDT/Bayesian champion files present; always 200, inspect `ready` field |
| `GET /api/v1/serving/health` | All ML services (Bayesian/GBDT/XFG + registry) |
| `GET /api/v1/gbdt/health` | GBDT manifest + cache status |

**`/api/v1/ready/serving` response structure**:
```json
{
  "ready": true,
  "checks": {
    "registry_manifest": {"ok": true, "detail": "parseable, 91 model entries"},
    "gbdt_champions": {
      "ok": true,
      "detail": "3 champion(s) found",
      "champions": [
        {"target": "PTS", "version": "s12345678_m9abc", "timestamp": "2026-02-24T14:32:18", "n_features": 18},
        {"target": "AST", "version": "s12345678_m7def", "timestamp": "2026-02-24T14:35:07", "n_features": 20}
      ]
    },
    "bayesian_champions": {"ok": true, "detail": "80 champion artifact(s) found"}
  }
}
```

`ready` is `true` when GBDT champions are present (Bayesian is informational only). Used by Railway health checks and `start.sh` warm-start logic.

### Pipeline Health (`scripts/health/`)

10 health modules with **113 manifest checks**, run via:

```bash
python scripts/health/report.py              # All checks
python scripts/health/report.py --pipeline prospects  # Prospects only
python scripts/health/report.py --pipeline nba_value  # NBA value only
```

Exit code: 0 = all pass, 1 = failures detected.

**Pre-rebuild gate**: `scripts/health/pre_rebuild_gate.py` blocks mart rebuilds if source data fails validation.

### Drift Detection (Multi-Layer)

| Layer | Tool | Threshold | Action |
|-------|------|-----------|--------|
| Pipeline | `validate_pipeline.py --compare` | `DRIFT_ALERT_THRESHOLDS` | FAIL alert |
| GBDT prediction | `GBDTPredictor.predict(check_drift=True)` | z-score > 2.0 | Flag in response |
| Forecasting PSI | `production_monitoring.py` | PSI > 0.10 warn, > 0.25 critical | Auto-retrain trigger |
| Prospect calibration | `calibration_check.py` | C-index < 0.70, IBS increase > 20% | Alert |

**Full SLO thresholds and rollback runbook**: see [Section 14](#14-rollback-runbook--slo-thresholds).

### Prometheus Metrics

**FastAPI** (`api/app/middleware/metrics.py`):
- `fastapi_request_total{method, endpoint, status}` -- Counter
- `fastapi_request_duration_seconds{method, endpoint}` -- Histogram
- `fastapi_prediction_total{endpoint, status}` -- Counter
- `fastapi_active_requests` -- Gauge
- Scrape: `GET /metrics`

**Prospects MCP** (`cbb_data/servers/metrics.py`):
- `cbb_tool_calls_total`, `cbb_cache_hits_total`, `cbb_tool_latency_ms`, etc.
- See [Section 13 — LLM Agent Tooling (MCP)](#13-llm-agent-tooling-mcp) for full MCP architecture and security details

**Infrastructure** (`api/de/infra/observability.yml`):
- Docker Compose with Prometheus + Grafana

### Known Dependency Issues

| Package | Issue | Fix | Session |
|---------|-------|-----|---------|
| `annotated-types>=0.6.0` | Mandatory pydantic v2 transitive dep NOT in `pyproject.toml`. NBA MCP crashes at import: `fastmcp -> pydantic/fields.py:16 -> import annotated_types`. | Added to `pyproject.toml` after `pydantic-settings` line; run `uv pip install "annotated-types>=0.6.0"` for immediate fix without full sync. | 369 |
| `fastmcp>=2.2.0,<3.0.0` | fastmcp 3.x requires OAuth deps (authlib, aiofile, key_value) not in the venv. Pinned to `<3.0.0` to stay on 2.14.x. | Pin already in `pyproject.toml`; if `uv pip install fastmcp --reinstall` upgrades to 3.x, run `uv pip install "fastmcp>=2.2.0,<3.0.0"` to downgrade. | 369 |

---

## 10. Prediction Audit Trail

### Prediction Log (`logs/predictions.jsonl`)

Every prediction request is logged as a single JSON line. The log uses **rotating file handlers** (50 MB max per file, 5 backups = 300 MB total) to prevent unbounded growth:

```json
{
  "request_id": "a1b2c3d4e5f6...",
  "timestamp": 1740422445.123,
  "endpoint": "/api/v1/gbdt/predict",
  "method": "POST",
  "status_code": 200,
  "latency_ms": 125.45,
  "model_type": "gbdt",
  "model_version": "20260220",
  "target": "PER"
}
```

Log rotation files: `predictions.jsonl`, `predictions.jsonl.1`, ..., `predictions.jsonl.5`

### Querying the Audit Trail

```bash
# Find all predictions for a specific request (search rotated files too)
grep "a1b2c3d4" logs/predictions.jsonl*

# Find all GBDT predictions in the last hour
python -c "
import json, time
with open('logs/predictions.jsonl') as f:
    for line in f:
        r = json.loads(line)
        if r['model_type'] == 'gbdt' and r['timestamp'] > time.time() - 3600:
            print(r)
"

# Compute average latency by endpoint
python -c "
import json
from collections import defaultdict
latencies = defaultdict(list)
with open('logs/predictions.jsonl') as f:
    for line in f:
        r = json.loads(line)
        latencies[r['endpoint']].append(r['latency_ms'])
for ep, vals in latencies.items():
    print(f'{ep}: avg={sum(vals)/len(vals):.1f}ms, n={len(vals)}')
"
```

### Correlating with Application Logs

Because both the prediction logger and the application logger include `request_id`:

1. User reports bad prediction -> get their `X-Request-ID` from browser DevTools
2. Search `predictions.jsonl` for that request_id -> find model_version, latency, target
3. Search `logs/backend.log` for same request_id -> full request lifecycle

---

## 11. CI/CD Pipeline

CI runs on every push to `main` and on every pull request via `.github/workflows/ci.yml`.

### Jobs

| Job | Trigger | Deps Installed | Tests Run |
|-----|---------|---------------|-----------|
| `test-unit` | push + PR | pytest, numpy, pandas, scikit-learn, pyarrow, pyyaml | CBA tests, golden formula tests (16 invariants), trade timeline tests, trade optimizer fixture tests |
| `test-bayesian` | push + PR | + pymc, arviz | `api/src/ml/modeling/bayesian/tests/` (non-GPU) |
| `test-gbdt` | push + PR | + xgboost, lightgbm, catboost | `api/src/ml/modeling/gddt/tests/` (non-GPU) |
| `test-integration` | push to main only | editable install or minimal deps | `scripts/validate_pipeline.py`, `scripts/health/report.py` |

### Pip Caching

All jobs use `actions/cache@v4` keyed on `hashFiles('api/pyproject.toml')`. Cache is invalidated automatically when deps change; the restore key (`pip-{job}-`) falls back to the last warm cache to still get a partial hit.

### GPU Tests Excluded

Tests decorated with `@pytest.mark.gpu` are excluded via `-m "not gpu"` in the bayesian and gbdt jobs. GPU tests require the RTX 5080 and must be run locally.

### Round-Trip Save/Load Test (Test 35)

`test_gbdt_pipeline.py::test_model_save_load_roundtrip_xgboost_native` verifies that:
1. Training an XGBoost model produces both `model.joblib` and `model.xgb.json`
2. `GDDTModel.load()` restores the model and produces bit-identical predictions
3. `GBDTPredictor.load_champion()` end-to-end also restores identical predictions

This test guards against model artifact corruption and ensures the XGBoost native/joblib fallback path is exercised.

### Concurrency Control

Jobs within the same `github.ref` are deduplicated:

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

A new push to the same branch cancels the in-flight run.

---

## 12. API Security

### Actual Security Posture (Audited 2026-02-24)

A full code audit of `api/app/main.py`, `api/app/security.py`, and all 20 routers produced these counts:

| Category | Count | Notes |
|----------|-------|-------|
| Total endpoints | 82+ | All routers combined |
| **Intentionally public** (no auth) | 65+ | Public NBA data + ML predictions |
| **Protected** (JWT required) | 17 | Training, MLOps, admin endpoints |

**This split is intentional.** The API serves public NBA statistics and ML predictions derived from public data (NBA Stats API, Basketball-Reference, Spotrac public contracts). There is no user-specific PII in prediction responses.

### Auth Mechanism

- **Type**: JWT (HS256) via OAuth2PasswordBearer
- **Token endpoint**: `POST /api/v1/token`
- **Dependency**: `get_current_user(token: str = Depends(oauth2_scheme)) -> str`
- **TTL**: `ACCESS_TOKEN_EXPIRE_MINUTES` env var (default: 30 min)
- **No RBAC**: all authenticated users have equal access to protected endpoints

### Clerk and user-product API (Clerk JWT, parallel to legacy JWT)

The **user / preferences / email / admin** surface uses **Clerk-issued session JWTs** verified with **`CLERK_SECRET_KEY`** (JWKS fetch), not the HS256 `SECRET_KEY` token above. Routers: `auth_endpoints`, `preference_endpoints`, `email_endpoints`, `admin_user_endpoints`. Full data flow, Postgres tables, workers, and **Railway frontend Vite env** (publishable key baked at **image build time**) are documented in [USER_STRATEGY_MARKETING_SECURITY.md](../projects/USER_STRATEGY_MARKETING_SECURITY.md). The backend does **not** use `VITE_CLERK_PUBLISHABLE_KEY`; it uses `CLERK_SECRET_KEY`, `CLERK_WEBHOOK_SECRET`, and (if used) `VITE_CLERK_PUBLISHABLE_KEY` only in the **browser bundle**.

### Protected Endpoints (17 — must return 401 without token)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/hello` | Token validation |
| `GET /api/v1/debug/ready` | Rate limits + training config |
| `GET /api/v1/debug/effective-config` | Full runtime config (3 fields redacted) |
| `POST /api/v1/debug/ratelimit/reset` | Flush rate-limit counters |
| `POST /api/v1/cancer/bayes/train` | Bayesian training |
| `GET /api/v1/cancer/bayes/config` | Bayes config |
| `GET /api/v1/cancer/bayes/runs/{run_id}` | Training metrics |
| `POST /api/v1/mlops/evaluate/{model_name}` | Model evaluation |
| `POST /api/v1/mlops/promote/{model_name}/staging` | Promote to staging |
| `POST /api/v1/mlops/promote/{model_name}/production` | Promote to production |
| `POST /api/v1/mlops/reload-model` | Hot reload |
| `GET /api/v1/mlops/status` | MLOps status |
| `GET /api/v1/mlops/models/{model_name}/metrics` | Model metrics |
| `GET /api/v1/mlops/models/{model_name}/compare` | Compare versions |
| `GET /api/v1/mlops/models/{model_name}/quality-gate` | Quality gate check |
| `POST /api/v1/iris/train` | Iris training |
| `POST /api/v1/cancer/train` | Cancer training |

### Security Fixes Applied (2026-02-24)

The audit identified four gaps, all fixed in `api/app/main.py`:

| Fix | Problem | Resolution |
|-----|---------|------------|
| **CORS** | `allow_origins=["*"]` hardcoded, ignoring `ALLOWED_ORIGINS` config; `allow_credentials=True` with wildcard violates CORS spec | Changed to `allow_origins=origins` (computed from `settings.ALLOWED_ORIGINS`); `allow_credentials` only true when explicit origins set |
| **`/debug/ready`** | Returned all rate limits + MLflow URIs + training flags without auth | Added `Depends(get_current_user)` |
| **`/debug/ratelimit/reset`** | No auth — anyone could flush their own rate-limit counters to bypass throttling | Added `Depends(get_current_user)` |
| **`/debug/psutil`** | Response included `sys.path` (server path disclosure) | Removed `sys.path` from response body |
| **`/debug/effective-config`** | Only `SECRET_KEY` and `DATABASE_URL` were redacted; `REDIS_URL` (connection string) was exposed | Added `REDIS_URL` to redacted set |

### Autoswagger — What It Is and How It Works

**Autoswagger** ([intruder-io/autoswagger](https://github.com/intruder-io/autoswagger)) is an open-source tool by Intruder that:
1. Discovers your OpenAPI spec (FastAPI auto-exposes `/openapi.json`)
2. Probes every defined endpoint without authentication
3. Reports endpoints returning 200 (broken authorization), PII in responses, and secrets in responses

**Installation**: not on PyPI — installed via git clone:

```bash
git clone https://github.com/intruder-io/autoswagger /opt/autoswagger
pip install -r /opt/autoswagger/requirements.txt
```

**Correct CLI**:

```bash
# Broken auth check (GET + POST/PUT/DELETE with -risk) + JSON output
python3 /opt/autoswagger/autoswagger.py http://api.example.com -risk -json -stats

# PII / secrets detection in responses
python3 /opt/autoswagger/autoswagger.py http://api.example.com -risk -product -json

# Throttled scan (avoid triggering rate limits)
python3 /opt/autoswagger/autoswagger.py http://api.example.com -risk -json -rate 10
```

**Flags**:

| Flag | Effect |
|------|--------|
| `-risk` | Include POST/PUT/PATCH/DELETE (not just GET) |
| `-product` | Output endpoints with PII or large responses only |
| `-json` | JSON output instead of Rich table |
| `-stats` | Print scan statistics (total requests, average RPS) |
| `-rate N` | Throttle to N requests/second (default: 30) |
| `-all` | Include 200 and 404 endpoints in output |
| `-b` | Brute-force parameter values |

**What it catches**:
- Endpoints returning 200 to unauthenticated requests
- PII in responses: phone numbers, emails, addresses, names
- Secrets in responses: API keys, tokens, environment variables (regex-based)

**What it does NOT catch**:
- Broken Object Level Authorization (BOLA/IDOR)
- Role-based access control (RBAC) gaps
- SQL injection, XSS, or other input validation issues
- Auth tokens passed in cookies (only checks Bearer header)

### Baseline Strategy

Because 85% of our endpoints are intentionally public, Autoswagger will find them all and report them as unauthenticated. We handle this with a **committed baseline**:

```
scripts/security/public_endpoint_baseline.txt   # committed, reviewed
scripts/security/generate_baseline.py           # generates from live API
scripts/security/check_new_public_endpoints.py  # CI comparison
```

**How it works**:
1. `generate_baseline.py` probes the live API and writes `METHOD /path -> status` for every public endpoint
2. This baseline is committed (documenting intentional public exposure)
3. In CI, `check_new_public_endpoints.py` compares the new Autoswagger scan against the baseline
4. **CI fails only if NEW public endpoints appear** beyond the committed baseline

Regenerate the baseline when intentionally adding a public endpoint:

```bash
python3 scripts/security/generate_baseline.py --url http://127.0.0.1:8000
git add scripts/security/public_endpoint_baseline.txt
git commit -m "Update public endpoint baseline: added GET /api/v1/new-route"
```

### CI Workflow

Both Autoswagger and Schemathesis run in `.github/workflows/security-scan.yml`:

| Job | Tool | Runs On | What It Checks |
|-----|------|---------|---------------|
| `autoswagger-scan` | Autoswagger (git clone) | push + PR + nightly | Broken auth, PII, secrets; compares against baseline |
| `schemathesis-contract` | Schemathesis (PyPI) | push + PR | OpenAPI contract conformance (no 5xx, correct content-type) |

**Schemathesis** (`pip install schemathesis`) runs property-based tests against every endpoint defined in `/openapi.json`, generating random valid inputs and checking that no endpoint returns a 5xx error or violates its declared content type. This complements Autoswagger's auth focus.

### Data Leakage Assessment

ML prediction responses in this API are derived from **publicly available data**:

| Response type | Data source | PII concern |
|---------------|------------|-------------|
| Game predictions (PTS, AST, etc.) | NBA Stats API (public) | None — aggregate stats |
| Contract predictions (AAV_PCT_CAP) | Spotrac public contracts | None — published data |
| Trade signals (BUY/SELL/HOLD) | Derived analysis | None — model output |
| Player leaderboard | NBA stats (public) | None |

**Genuine leakage risks** (not from prediction responses, but from infrastructure endpoints):
- `REDIS_URL` in effective-config → now redacted
- `sys.path` in debug/psutil → removed
- Rate limit config in debug/ready → now auth-gated
- MLflow tracking URIs in debug/ready → now auth-gated

### Auth Pattern for New Endpoints

Any new endpoint that should be protected:

```python
from app.security import get_current_user
from fastapi import Depends

@router.post("/your-endpoint")
async def your_endpoint(
    ...,
    current_user: str = Depends(get_current_user),
):
    ...
```

Any new endpoint that is intentionally public (no auth): add it to `scripts/security/public_endpoint_baseline.txt` and regenerate the baseline before merging.

---

## 13. LLM Agent Tooling (MCP)

### Overview

**MCP (Model Context Protocol)** is a standardized protocol for LLM assistants and agents to discover and call tools, fetch resources, and retrieve context. In your architecture, MCP runs as a **separate service** (`:8001/sse`) and is **distinct from your REST API**.

**Key principle**: MCP is for **agent tool integration**, not for ML serving. If you need predictions or dashboard data, use the REST API. If an LLM agent needs to run a tool or fetch context, use MCP.

### What MCP Exposes

#### Tools (Agent-Callable Functions)
Prospect pipeline operations that an LLM assistant can invoke:
- `catalog/fetch` -- fetch raw game/player data from bronze or silver
- `build_dataset` -- construct a feature table for training or analysis
- `validate_schema` -- check data schema conformance
- And others per `cbb_data/servers/` MCP server definitions

#### Resources (Fetchable Context)
Data the agent can request:
- Player statistics tables
- Prospect rankings and big boards
- League strength factors
- Historical predictions

#### Prompts (Pre-Canned Instructions)
- Scouting advice templates
- Trade analysis workflows
- Other domain-specific agent instructions

### How MCP Runs

**Two access paths exist:**

**Path 1: Backend Proxy (Frontend)** — Router #23 (`/api/v1/mcp/*`)
The frontend `mcpClient.js` calls MCP tools through the FastAPI backend proxy. The backend imports `nba_api_mcp` in-process and calls tool functions directly — no HTTP or SSE to the MCP server.

```
Frontend (mcpClient.js)
  |
  | GET  /api/v1/mcp/tools      (tool discovery with real schemas)
  | POST /api/v1/mcp/call-tool  (tool execution)
  v
FastAPI Backend (mcp_proxy_endpoints.py)
  |
  | In-process call to nba_api_mcp tool functions
  v
NBA data (from nba_api)
```

**Path 2: Direct SSE (External Clients)** — `:8005/sse` (FastMCP server)
Claude Desktop, external MCP clients, and other LLM tools connect directly via JSON-RPC 2.0 over SSE. This path is NOT used by the frontend.

```
Claude Desktop / External MCP Client
  |
  | JSON-RPC 2.0 (SSE)
  v
:8005/sse (FastMCP server)
```

### Security Posture

**Authentication**:
- JWT token required (same as REST API)
- Origin validation to prevent CSRF
- Tool allowlist (not all backend functions exposed to agents)

**Authorization**:
- All tools require authenticated session
- No guest access to MCP

**Monitoring**:
- Tool call metrics: `cbb_tool_calls_total`, `cbb_tool_latency_ms` (Prometheus)
- Tool failures logged and alerted
- See [Section 9](#9-health--monitoring) for full metrics details

### When to Use MCP vs REST

| Need | Use This |
|------|----------|
| Frontend dashboard needs player stats | REST API (`/api/v1/analytics/*`) |
| Agent needs to fetch a dataset | MCP (`catalog/fetch` tool) |
| Batch script needs bulk predictions | REST API (`/api/v1/serving/predict`) |
| Agent needs to validate data quality | MCP (`validate_schema` tool) |
| User needs to export a report | REST API endpoint |
| Agent needs to explore available datasets | MCP (Resources discovery) |

### Implementation Details

**MCP Servers in your codebase**:
- `api/src/airflow_project/eda/nba_prospects/cbb_data/servers/` -- prospect pipeline tools
- Server registration: `api/app/routers/agents.py` or similar agent-facing router

**Metrics & Observability**:
Covered in [Section 9 - Health & Monitoring](#9-health--monitoring), subsection "Prometheus Metrics". Prospect MCP metrics include tool call counts, cache hit rates, and latency distributions.

---

## 14. Rollback Runbook & SLO Thresholds

### SLO Thresholds (GBDT Serving)

| Metric | SLO | Critical Threshold | Action |
|--------|-----|-------------------|--------|
| Prediction endpoint p99 latency | < 500 ms | > 1 000 ms | Alert + investigate slow queries |
| Prediction endpoint p50 latency | < 100 ms | > 300 ms | Alert |
| Prediction error rate (5xx) | < 0.5% | > 2% | PagerDuty |
| Artifact integrity check failures on load | 0 | Any | Stop serving, rollback immediately |
| Schema hash mismatch on load | Warning only | — | Retrain champion |
| Feature drift flags (`z > 2.0`) per prediction | < 10% of features | > 30% of features | Investigate data pipeline |
| Model contract dtype mismatch warnings | < 5% of requests | > 20% of requests | Review serving data pipeline |

### Champion Rollback Procedure

**When to rollback:**
- Integrity check failure (`RuntimeError: Artifact integrity check failed`) on load
- Test R² drops > 10% vs previous champion
- Prediction latency p99 increases > 3x after a promotion
- Sudden spike in feature drift flags across multiple targets
- CI golden formula tests start failing in serving

**Rollback steps (GBDT):**

```python
# 1. List available versions
from api.src.ml.modeling.gddt.diagnostics.champion_challenger import GBDTChampionChallenger
from api.src.ml.modeling.gddt.config.pipeline_config import GDDTConfig
from api.src.ml.modeling.gddt.config.schema import load_schema_for_target

config = GDDTConfig(target="PTS", granularity="PLAYER_GAME")
schema = load_schema_for_target("PTS")
cc = GBDTChampionChallenger(schema, config)

versions = cc.list_versions()
for v in versions:
    print(f"{'[current]' if v.is_current else '         '} {v.version} | {v.timestamp} | rmse={v.metrics.get('rmse', '?'):.4f}")

# 2. Rollback to a specific version
success = cc.rollback(version="s12345678_m9abc")
print("Rollback OK" if success else "Rollback FAILED — check logs")

# 3. Verify the rollback
from api.src.ml.modeling.gddt.serving.predictor import GBDTPredictor
predictor = GBDTPredictor.load_champion("PTS")  # Integrity check runs on load
print(f"Active version: {predictor.metadata['version']}")
```

**Verify via API after rollback:**
```bash
# Confirm serving probe shows the rolled-back version
curl -s http://localhost:8000/api/v1/ready/serving | python -m json.tool

# Smoke-test a prediction
curl -X POST http://localhost:8000/api/v1/gbdt/predict \
  -H "Content-Type: application/json" \
  -d '{"target": "PTS", "data": {"PLAYER_ID": [2544], "MIN": [35.0]}}' \
  | python -m json.tool
```

### Bayesian Rollback

Bayesian artifacts use the `BayesianChampionChallenger` (ELPD-based). Rollback is manual:

```bash
# 1. Find version directories
ls serving/artifacts/bayesian/player_game/training/PLAYER_GAME/

# 2. Copy a historical version over the champion directory
# (Bayesian uses timestamped directories, not champion_{version})
PREV_VERSION="negbin_pts_player_game_20260201T153210"
cp -r serving/artifacts/bayesian/player_game/training/PLAYER_GAME/${PREV_VERSION} \
      serving/artifacts/bayesian/player_game/training/PLAYER_GAME/${PREV_VERSION}_champion

# 3. Restart the API to reload the champion
kill -HUP $(pgrep -f uvicorn)
```

### Artifact Integrity Checks

Every champion load runs SHA256 verification against checksums stored in `metadata.json`.

**On failure:**
```
RuntimeError: Artifact integrity check failed for PTS champion at .../champion:
  - model.joblib: expected a1b2c3d4e5f60000... got 99887766554433...
```

**Resolution:**
1. Identify when the file was modified: `stat serving/artifacts/gbdt/PTS_PLAYER_GAME/champion/model.joblib`
2. Check git history and deployment logs for unauthorized changes
3. Rollback to the nearest clean version (see rollback steps above)
4. If no clean version: retrain from scratch

**Artifacts covered by checksums** (saved in `metadata.json` → `artifact_checksums`):
- `model.joblib` — the serialized ML model
- `features.json` — ordered feature list
- `training_stats.json` — per-feature mean/std/median (if conformal enabled)
- `conformal_quantiles.json` — prediction interval widths (if conformal enabled)
- `model_contract.json` — typed input schema per column (if `feature_dtypes` provided at training time)

### Model Contract (`model_contract.json`)

Saved at training time when `feature_dtypes=X_train.dtypes.astype(str).to_dict()` is passed to `compare_and_promote()`.

```json
{
  "inputs": [
    {"name": "MIN", "dtype": "float64"},
    {"name": "FEAT_A", "dtype": "float64"},
    {"name": "IS_HOME", "dtype": "int64"}
  ],
  "output": {"name": "PTS"},
  "n_features": 18,
  "created_at": "2026-02-24T14:32:18"
}
```

**At serving time**: `GBDTPredictor.predict()` compares live column dtypes against the contract. Integer types (`int8/16/32/64`) are treated as compatible with `float32/64` (safe promotion). Any other mismatch emits a **WARNING** — inference continues but the warning signals a data pipeline change.

---

## Appendix: Quick Reference

### Start Backend Locally

```bash
cd /workspace
export PYTHONPATH=/workspace
uvicorn api.app.main:app --reload --host 0.0.0.0 --port 8000
```

### Refresh Model Manifest

```bash
curl -X POST http://localhost:8000/api/v1/serving/refresh-manifest
```

### Check Serving Health

```bash
curl http://localhost:8000/api/v1/serving/health | python -m json.tool
```

### Deep Serving Readiness (Champion Artifacts)

```bash
# Check registry manifest + GBDT/Bayesian champion presence
curl http://localhost:8000/api/v1/ready/serving | python -m json.tool

# Quick check: is serving ready?
curl -s http://localhost:8000/api/v1/ready/serving | python -c "import json,sys; d=json.load(sys.stdin); print('READY' if d['ready'] else 'NOT READY', d['checks']['gbdt_champions']['detail'])"
```

### Run Pipeline Validation

```bash
python scripts/validate_pipeline.py          # 27/27 gold checks
python scripts/health/report.py              # 113 manifest checks
```

### Valid GBDT Targets (14)

PER, VORP, WS, BPM, PTS, AST, TRB, STL, BLK, TS_PCT, EFG_PCT, AAV_PCT_CAP, ORTG, DRTG

### Valid Granularities (4)

PLAYER_GAME, PLAYER_SEASON, TEAM_GAME, PLAYER_TEAM_SEASON

---

## 15. FastAPI Upgrade History

### 0.128.0 -> 0.134.0 (Applied: 2026-03-09)

| Version | Change | Action Taken |
|---------|--------|-------------|
| 0.129 | Python 3.9 dropped | No action — already on 3.11+ |
| 0.130 | Pydantic Rust JSON serialization (~2x speedup for `response_model` endpoints) | Added Pydantic `response_model=` to analytics, draft, referee endpoints (§3.1-3.3); free speedup activates automatically on typed endpoints |
| 0.131 | `ORJSONResponse`/`UJSONResponse` deprecated | Scanned all routers — no usage found; `JSONResponse` already in use everywhere |
| 0.132 | Strict `Content-Type` enforcement ON by default for JSON POST/PUT/PATCH | Added `strict_content_type=False` safety net to `FastAPI()` constructor with explicit TODO to remove after client audit |
| 0.133 | Starlette 1.0+ support | No action — additive |
| 0.134 | `AsyncIterable[T]`/`Iterable[T]` for native streaming NDJSON | Added `/stream` variants: `daily-slate/stream`, `market-scanner/stream`, `prospect-board/stream` (§6b) |

**Bugs fixed during this upgrade cycle (found by endpoint audit):**

| Bug | File | Fix |
|-----|------|-----|
| Blocking `pd.read_parquet()` inside `async def` handlers | `predictions_endpoints.py` | Converted all 7 handlers to `def` (sync) |
| Blocking DuckDB/parquet inside `async def` handlers | `draft_endpoints.py` | Converted all 9 handlers to `def`; `await health_check()` -> `health_check()` |
| Blocking DuckDB inside `async def` handlers | `nba_endpoints.py` | Converted 10 handlers to `def`; kept 4 genuine `async def` (`asyncio.gather`, `_fetch_shots_with_xfg`) |
| Module-level TTL cache race condition (no lock) | `nba_endpoints.py` | Added `threading.Lock` wrapping all `_leaders_cache` and `_schedule_date_cache` reads/writes |

**Dependency change (single package):**

```toml
# api/pyproject.toml
fastapi>=0.134.0,<0.136.0   # was: >=0.128.0,<0.130.0
# All other 30+ packages confirmed compatible — no other changes required.
```
