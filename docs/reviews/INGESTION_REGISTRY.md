# Ingestion Registry

> **Archived — orphaned borrowed reference.** Unlike its sibling docs now in
> `docs/reference/betts-basketball-standards/`, this file is not cited by
> `configs/standards.yaml`'s reference bundle and no code in this repo
> implements `SourceSpec`/fetchers/`postgres_mirror`. Kept for history only.

**Status:** Phase 1 Stage 10 — PRODUCTION

The ingestion registry is the declarative source of truth for every external
data source the platform pulls. Adding a new endpoint is a YAML change plus
a fetcher callable — never a new DAG pattern.

Primary files:

- `api/src/ingestion/registry/sources.yaml` — the data
- `api/src/ingestion/registry/models.py` — the `SourceSpec` Pydantic contract
- `api/src/ingestion/registry/loader.py` — strict YAML → `SourceSpec` loader
- `api/src/ingestion/registry/postgres_mirror.py` — mirrors YAML into `ingest.ingestion_registry`
- `scripts/ingestion/classify_fetchers.py` — audits fetcher modules against the registry

## Why a registry at all

Before: adding a new endpoint touched DAG code, fetcher code, rate-limit
config, retry wiring, and freshness dashboards — in four places. Easy to
forget one. No structured inventory of what we pull, from where, or at what
cadence.

After: add one YAML entry with 19 required fields. The registry:

- Loads on DAG parse, mirrored into `ingest.ingestion_registry`
- Drives the per-source rate limiter and circuit-breaker thresholds
- Is the single source of truth the worker dispatcher consults
- Feeds the freshness dashboard and `upload_data.sh --validate` promotion gate

## SourceSpec schema (19 fields, all required)

All fields are required. Pydantic rejects YAML entries missing any field —
no defaults exist. This forces operators to decide idempotency, degradation
policy, and promotion-blocking behavior explicitly per source.

| Field | Type | Purpose |
|---|---|---|
| `source_name` | slug | Canonical source ID (`stats_nba`, `bbref`, …) |
| `endpoint_name` | slug | Endpoint within the source (`scoreboard_v2`, …) |
| `source_type` | enum | `blocked` / `cloud_safe` / `scrape` / `gpu_downstream` |
| `cadence_class` | enum | `live` / `nearline` / `daily` / `seasonal` — SLA tier |
| `priority` | int | Lease tie-breaker (higher wins) |
| `max_concurrency` | int ≥1 | Per-source semaphore bound |
| `min_interval_seconds` | float ≥0 | Token-bucket refill rate |
| `retry_policy` | object | `max_attempts` + `backoff_seconds` + `retryable_status_codes` |
| `timeout_seconds` | int ≥1 | HTTP timeout |
| `collector_pool` | enum | `residential` / `cloud_safe` / `gpu` |
| `partition_key` | Jinja template | R2 path suffix, e.g. `date={{date}}/game_id={{game_id}}` |
| `validation_contract` | path | Validation-gate script or schema |
| `artifact_target` | string | R2 prefix under the public allowlist |
| **`idempotency_scope`** | enum | `per_partition` / `per_run` / `global` |
| **`dedupe_key_template`** | Jinja template | Fields composing the dedupe key |
| **`replace_mode`** | enum | `append_only` / `snapshot_overwrite` / `partition_replace` / `forbidden` |
| **`serving_degradation_policy`** | enum | `serve_last_good` / `hide` / `fallback_direct` / `mark_unknown` |
| **`owner`** | email-ish | Alert routing |
| **`blocking_for_promotion`** | bool | Stale artifact blocks `upload_data.sh --validate` |

The six **bolded** fields are the Phase 1 hardening additions beyond the
original audit. See *Replay Policy* below for `replace_mode` enforcement.

## Add a new source — checklist

1. Add a `SourceSpec` entry to [`sources.yaml`](../../../api/src/ingestion/registry/sources.yaml).
2. Pick `collector_pool`:
   - `residential` if the source blocks cloud IPs (`stats.nba.com`, BBRef-via-Cloudflare, Spotrac)
   - `cloud_safe` for anything else
   - `gpu` is reserved for retrains and uses `gpu_job_specs.yaml`, not SourceSpecs
3. Decide `replace_mode`:
   - New immutable rows → `append_only`
   - Full daily snapshot → `snapshot_overwrite`
   - Per-partition daily → `partition_replace`
   - Time-sensitive economic data (odds, props, pre-game injury) → **`forbidden`**
4. Decide `serving_degradation_policy`. What does the API do when stale?
5. Write the fetcher:
   ```python
   from api.src.ingestion.fetchers import register_fetcher
   from api.src.ingestion.queue.job import FetchJob

   @register_fetcher("your_source", "your_endpoint")
   def fetch_your_endpoint(job: FetchJob) -> dict:
       # Return bronze payload: {"data": [...], "metadata": {...}}
       ...
   ```
6. Run the classification gate:
   ```bash
   python scripts/ingestion/classify_fetchers.py --strict
   ```
7. Pool assignment: if the source is `residential`, ensure the `source_name`
   appears in [`collectors/residential/pool.yaml`](../../../api/src/ingestion/collectors/residential/pool.yaml)
   (or the matching pool config for other pools).

## Replay Policy

Every source declares a `replace_mode`. This determines whether re-running a
job is safe:

| `replace_mode` | Auto retry? | Operator replay? | Example |
|---|---|---|---|
| `append_only` | Yes | Yes — idempotent | Play-by-play events |
| `snapshot_overwrite` | Yes | Yes — last-writer-wins | Current-day schedule |
| `partition_replace` | Yes | Yes — scope-limited | Daily box scores |
| `forbidden` | **No — deadletter** | **Requires signed CLI replay** | Odds / props snapshots |

### Enforcement

- The worker's 4-step hardened ack consults `replace_mode` before writing.
  For `forbidden` sources, existence of the target R2 key triggers
  `IdempotencyViolation` → deadletter.
- `retry_policy.max_attempts` is capped at 1 for `forbidden` sources by the
  producer, regardless of what YAML says.
- Operator-authorized replays require the CLI:
  ```bash
  python scripts/ingestion/replay.py \
      --source sportsbook --endpoint prop_lines \
      --partition-key "date=2026-04-16/book=draftkings" \
      --param date=2026-04-16 --param book=draftkings \
      --authorized-by ops@internal \
      --reason "rebuilding after incident 2026-04-16-INC-12"
  ```
  The CLI writes an audit entry to `bronze/audit/{source}/` and populates
  the three `replay_*` columns together (enforced by a check constraint).

## Operational vs analytical boundary

```
┌────────────────────────────────────────────┐
│       Railway Postgres — ingest schema     │    operational
│   ingestion_registry / ingest_jobs /       │    (control plane)
│   ingest_workers / ingest_heartbeats /     │    never exposed to dbt
│   ingest_circuits                          │    never joined to basketball marts
└────────────────────────────────────────────┘
                    │
                    │  (workers run, bronze wrapper validated,
                    │   artifact_target written to R2)
                    ▼
┌────────────────────────────────────────────┐
│       Cloudflare R2 — public allowlist     │    analytical
│   basketball.duckdb, boards/, models/,     │    (artifact plane)
│   predictions/, gold_products/, …          │    promoted via upload_data.sh
└────────────────────────────────────────────┘
```

The `ingest.*` schema is **operational**. PR review rejects any dbt model,
mart join, or `_PUBLIC_ALLOWLIST` write that mentions these tables.

## Circuit breaker state machine

Per-source state persisted in `ingest.ingest_circuits`:

```
      ┌──────── failure < threshold ───────┐
      │                                     │
      ▼                                     │
 ┌────────┐   failure ≥ threshold    ┌──────────┐
 │ closed │─────────────────────────▶│   open   │
 └────────┘                          └──────────┘
      ▲                                     │
      │                                     │  cooldown elapsed
      │  success                            ▼
      │                              ┌──────────────┐
      └──────────────────────────────│  half_open   │
                                     │ (1 probe)    │
                                     └──────────────┘
                                             │
                                             │ probe fails
                                             ▼
                                     back to open
```

Thresholds are **derived**, not hardcoded:

- `failure_threshold = max(2, retry_policy.max_attempts * 2)`
- `open_cooldown_seconds = sum(retry_policy.backoff_seconds) * 2`
- `half_open_probe_count = 1`

If you want a wider breaker window, increase the source's `retry_policy` —
don't patch the breaker.

## Dual-timestamp freshness

Two independent staleness values per (source, endpoint):

- `fetch_staleness = now - last_fetch_success_ts` — from `ingest_jobs`
- `validation_staleness = now - last_validated_artifact_ts` — from manifest

A source can be `fetch_green, validation_red` (fetch works but silver/gold
is broken). That's a **distinct alert class** with its own runbook.

Exposed via:

- `GET /api/v1/ingest/freshness` — JSON (router: [`ingest_status.py`](../../../api/app/routers/ingest_status.py))
- `python scripts/ingestion/freshness_report.py` — table; exits non-zero if any
  `blocking_for_promotion=true` source is stale

Cadence SLA table (lives in [`freshness_sla.py`](../../../api/src/ingestion/dashboards/freshness_sla.py)):

| cadence_class | SLA |
|---|---|
| live | 60 s |
| nearline | 15 min |
| daily | 26 h |
| seasonal | 8 d |

## Running locally

```bash
# Smoke: verify registry loads + classification gate
python scripts/ingestion/classify_fetchers.py --strict

# Full S1-S9 test suite (hermetic; integration tests skip without DB)
uv run --extra dev pytest api/src/ingestion/tests/ tests/live/ -q

# Run a worker (Postgres must have the Phase 1 migrations applied)
python -m api.src.ingestion.collectors.worker_entry --pool cloud_safe --max-jobs 10

# Freshness report
python scripts/ingestion/freshness_report.py --blocking-only
```

## Running workers in production (Windows host + Docker Compose)

The original operator plan assumed Linux + systemd + `/etc/betts_basketball/worker.env`.
This project's primary residential host is **Windows 11 Pro**, so the actual
deployment pattern is Docker Compose with profile gating. The architecture is
unchanged; only the last-mile packaging differs.

### One-time setup

1. Fill in [`.devcontainer/.env`](../../../.devcontainer/.env) with:
   - `INGEST_DATABASE_URL=postgresql://postgres:…@hopper.proxy.rlwy.net:…/railway`
   - `AWS_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com`
   - `AWS_ACCESS_KEY_ID=…`
   - `AWS_SECRET_ACCESS_KEY=…`
   - `AWS_DEFAULT_REGION=auto`

2. Apply migrations (one-time, already done for this repo):

   ```bash
   cd api
   INGEST_DATABASE_URL=postgresql+asyncpg://… python -m alembic \
       -c alembic_ingest.ini upgrade head
   ```

### Starting the workers

```bash
# Airflow only (no workers) — same as before
docker compose -f docker-compose.nba-airflow.yml up -d

# Airflow + ingest workers (cloud_safe + residential)
docker compose -f docker-compose.nba-airflow.yml --profile ingest-workers up -d

# Check worker health
docker compose -f docker-compose.nba-airflow.yml ps ingest-worker-cloud-safe
docker compose -f docker-compose.nba-airflow.yml logs -f ingest-worker-residential
```

Missing credentials = the worker **refuses to boot** with a clear
`RuntimeError` listing the empty env vars (see
[`worker_entry._assert_required_env`](../../../api/src/ingestion/collectors/worker_entry.py)).
This is intentional — §14 no-defensive-coding. If you see
`"ingest worker refusing to start"` in `docker compose logs`, fill in the
missing var in `.env` and `docker compose up -d` again.

### Why `profiles: ["ingest-workers"]`?

Matches the DAG paused-by-default pattern from PR 4. Default
`docker compose up` does not start workers — activation is an explicit
`--profile ingest-workers` click. Operator must choose to run the data
plane, exactly like they must choose to unpause each DAG.

### Residential IP egress on Windows

Docker Desktop on Windows routes outbound traffic through the host's
residential IP by default (via the WSL2 NAT). No `network_mode: host`
required — it's a Linux-only feature and Docker Desktop silently
ignores it on Windows anyway.

If `stats.nba.com` starts 403-ing Docker NAT traffic in the future
(symptom: cloud_safe still works but residential fetchers fail with
403 despite packet-capture showing residential IP), the fix is:

1. Install Cloudflare Tunnel via the Windows MSI:
   <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>
2. `cloudflared tunnel login`, `cloudflared tunnel create nba-residential`
3. Point the residential worker at the tunnel via an env var override
   (config already exists at `collectors/residential/cloudflared.yml`).

Not needed for Phase 1 — only trigger on actual evidence of fingerprinting.

## Reference files

| Concern | File |
|---|---|
| SourceSpec schema | [`api/src/ingestion/registry/models.py`](../../../api/src/ingestion/registry/models.py) |
| Registry data | [`api/src/ingestion/registry/sources.yaml`](../../../api/src/ingestion/registry/sources.yaml) |
| Queue primitives | [`api/src/ingestion/queue/{producer,consumer,deadletter}.py`](../../../api/src/ingestion/queue/) |
| Worker (hardened ack) | [`api/src/ingestion/collectors/worker_base.py`](../../../api/src/ingestion/collectors/worker_base.py) |
| Circuit breaker | [`api/src/ingestion/policies/circuit_breaker.py`](../../../api/src/ingestion/policies/circuit_breaker.py) |
| Live writer | [`api/src/live/writer.py`](../../../api/src/live/writer.py) |
| GPU dispatcher | [`api/src/ingestion/collectors/gpu/dispatcher.py`](../../../api/src/ingestion/collectors/gpu/dispatcher.py) |
| Freshness router | [`api/app/routers/ingest_status.py`](../../../api/app/routers/ingest_status.py) |
| Replay CLI | [`scripts/ingestion/replay.py`](../../../scripts/ingestion/replay.py) |
| Alembic migrations | [`api/alembic/versions/20260416_0012_ingest_registry_schema.py`](../../../api/alembic/versions/20260416_0012_ingest_registry_schema.py), [`20260416_0013_ingest_queue_tables.py`](../../../api/alembic/versions/20260416_0013_ingest_queue_tables.py) |
