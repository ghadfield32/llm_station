# Local Fleet + R2 Workflow — Two-Machine Execution-Lane Standard

**Status**: PRODUCTION STANDARD (enforced) | **Last updated**: 2026-06-11
**Owner lane**: Data Engineering / Ops
**Enforced by**: `scripts/upload_data.sh`, `_base_three_mode_dag.py`,
`theoddsapi_client.py`, `api/src/airflow_project/utils/machine_role.py`

> **Read this first.** This is the authoritative standard for how the **two
> physical machines** in this project share **one** Cloudflare R2 production
> bucket and **one** set of Railway services without clobbering each other's
> data. It is referenced by [PIPELINE_STANDARDS_TEMPLATE.md §16](../PIPELINE_STANDARDS_TEMPLATE.md#16-multi-machine-role-contract-desktop-scheduler--laptop-dev),
> [DATA_ENGINEERING_PIPELINE.md §0.9/§0.9e](DATA_ENGINEERING_PIPELINE.md), and
> [MULTI_SESSION_R2.md](MULTI_SESSION_R2.md). Those cover *philosophy*; this doc
> is the *enforced contract* (env-var gates, mirror model, promotion flow).

---

## The one-sentence rule

> **Desktop = production orchestrator and the ONLY production R2 writer.
> Laptop = dev/training/frontend lane, READ-ONLY from production R2, writes only
> to local `.r2_staging`. Production R2 = canonical promoted truth. Local mirrors
> = disposable, hydrated read-only from the R2 manifest — never peer-to-peer.**

---

## Module tree — files this standard governs

```
betts_basketball/
├── api/src/airflow_project/utils/machine_role.py   # Python guard helpers (fail-closed)
│       get_machine_role / get_artifact_lane / is_flag_enabled
│       assert_can_run_prod_dags / assert_can_write_prod_r2
│       assert_can_make_paid_provider_calls / MachineRoleError
├── scripts/upload_data.sh                          # R2 writer — bash write-guard (before lock)
├── api/src/airflow_project/dags/_base_three_mode_dag.py
│       _wrap_with_prod_dag_guard()                 # gates scheduled daily/rebuild runs
├── api/src/pipelines/odds/ingestion/theoddsapi_client.py
│       _request()                                  # gates every billed Odds API call
├── scripts/ops/sync_from_r2_manifest.py            # READ-ONLY hydrate -> .r2_mirror/prod
├── scripts/ops/compare_local_to_r2_manifest.py     # READ-ONLY drift report vs manifest
├── docker-compose.nba-airflow.yml                  # scheduler/worker container env (BETTS_*)
├── .env.example (root)                             # documented BETTS_* values per machine
├── ops/production_writer.md                        # live writer-ownership record
└── .r2_mirror/ , .r2_staging/                      # gitignored; disposable local artifacts
```

**What each piece does**

| Piece | Role |
|-------|------|
| `machine_role.py` | Single source of truth for the fail-closed Python gates. Pure stdlib so it imports at DAG parse time and from scripts. |
| `upload_data.sh` guard | The R2 write boundary. Aborts a real upload unless `BETTS_CAN_WRITE_PROD_R2=1`. `--dry-run` is exempt. Runs **before** `acquire_r2_lock`. |
| `_wrap_with_prod_dag_guard` | Wraps scheduled `daily`/`rebuild` DAG callables so the run fails loud on a machine without `BETTS_CAN_RUN_PROD_DAGS=1`. Runtime, not parse-time. |
| `theoddsapi_client._request()` | The single chokepoint for billed Odds API calls; gated on `BETTS_CAN_MAKE_PAID_PROVIDER_CALLS=1`, composed with the credit-budget cap. |
| `sync_from_r2_manifest.py` | Hydrates `.r2_mirror/prod` from the R2 manifest. Strictly read-only (`get_object`/`list_objects_v2`). |
| `compare_local_to_r2_manifest.py` | Reports drift between a local mirror and the R2 manifest by sha256. Read-only. |
| `ops/production_writer.md` | Records who the current production writer is, the emergency-writer switch, and the rollback manifest. |

---

## 1. The problem: three drifting "truths"

The repo runs across two machines doing **different jobs**:

- **Desktop (RTX 4090)** — always-on Airflow scheduler, unpaused production DAGs,
  GPU training. Its local data changes because pipelines continuously produce.
- **Laptop (RTX 5080)** — code authoring, fast training experiments, frontend dev.
  Its local data changes because you are developing.

That yields three stores that legitimately differ:

1. **Production R2** — what Railway/the site serves (canonical).
2. **Desktop-local** — moving because scheduled DAGs produce artifacts.
3. **Laptop-local** — moving because of active development.

The fix is **not** to force both machines to be perfectly live-synced while they
do different jobs. The fix is to make them **different execution lanes** with
explicit promotion rules, and to make "are we looking at the same production
truth?" answerable via the **R2 manifest**, not by comparing working trees.

---

## 2. Role definition

| Area | Desktop (4090) | Laptop (5080) |
|---|---|---|
| Airflow scheduler (always-on) | ✅ only scheduler | ❌ |
| Unpaused production DAGs | ✅ | ❌ |
| Production R2 upload | ✅ **only writer by default** | ❌ |
| Paid provider pulls (Odds API) | ✅ operator-gated | ❌ |
| GPU heavy retrains | ✅ primary | overflow only if assigned |
| Read production R2 | ✅ | ✅ |
| Build candidate features/models | ✅ | ✅ |
| Local one-off validation | ✅ | ✅ |
| Frontend / API development | ✅ | ✅ |
| Write dev/staging artifacts (`.r2_staging`) | ✅ | ✅ |
| Promote production champion | ✅ | ❌ by default |
| Production Railway smoke | ✅ | ✅ read-only |

These are **responsibilities**, not raw capabilities. Either machine *can* run a
command; only one is *responsible* on a given day. Cross the line only with an
explicit reason and the emergency-writer switch (§9).

---

## 3. The env-var role contract (enforced, fail-closed)

Each machine declares its lane in its **repo-root `.env`** (gitignored). The
flags are **fail-closed**: a capability is denied unless its flag is exactly
`"1"`. Unset → denied → loud error. There is **no default-allow**.

| Env var | Desktop | Laptop | Gate |
|---|---|---|---|
| `BETTS_MACHINE_ROLE` | `production_orchestrator` | `dev_laptop` | informational label |
| `BETTS_CAN_RUN_PROD_DAGS` | `1` | `0` | scheduled `daily`/`rebuild` DAG runs |
| `BETTS_CAN_WRITE_PROD_R2` | `1` | `0` | real `upload_data.sh` writes |
| `BETTS_CAN_MAKE_PAID_PROVIDER_CALLS` | `1` | `0` | billed Odds API calls |
| `BETTS_DEFAULT_ARTIFACT_LANE` | `prod` | `dev` | default output namespace |

**Where they are read — set the flags in BOTH env files**

Setting the `.env` flags is necessary but only takes effect if they reach the two
*different* readers. The flags must be set in **both** files, with the same values:

| File | Read by | Why |
|------|---------|-----|
| repo-root `.env` | `scripts/upload_data.sh` (auto-loads root `.env`) + your interactive shell | the R2 write-guard reads `BETTS_CAN_WRITE_PROD_R2` here |
| `api/src/airflow_project/.env` | the Airflow scheduler/worker **containers** | this file is the compose `--env-file` **and** the `env_file:` injected into every container (see `scripts/run_phase3_auto.sh`). The DAG guard + paid-Odds guard run *inside* the container and only see vars present here. |

- `api/src/airflow_project/utils/machine_role.py` is the Python enforcement point
  for the DAG and Odds gates; it reads whatever the process env contains.
- `docker-compose.nba-airflow.yml` also interpolates `${BETTS_*:-0}` into the
  container `environment:` block, so an **unconfigured** machine defaults to the
  safe (denied) posture even if the file is missing a value.

> The committed `.env.example` (both root and airflow) ships the **safe (laptop)
> posture** as the default. Flip the flags on the desktop only. See §10 for the
> mandatory rollout order **and the container recreate + verify step**.

---

## 4. The mirror / staging directory model

```
repo/
  data/ , cache/                 # local working outputs; MAY differ per machine (gitignored)
  .r2_mirror/prod/               # READ-ONLY hydrated production snapshot (gitignored)
  .r2_staging/<machine>/<run_id>/# dev/candidate artifacts; NEVER served, NEVER prod (gitignored)
```

Rules:

- **Local copies sync from R2, not from each other.** Do not try to make
  `desktop/data` and `laptop/data` continuously identical. Hydrate both machines'
  `.r2_mirror/prod` from the same R2 manifest instead.
- **`.r2_mirror/prod` is read-only truth.** It is a disposable snapshot of what R2
  says is live. Never edit it; re-hydrate it.
- **`.r2_staging/<machine>/<run_id>/` is the dev lane's scratch space.** Laptop
  candidate outputs land here, get code/report-reviewed, and are reproduced on the
  desktop before promotion. They are never uploaded to the production manifest.

### Read-only tools

```bash
# Refresh the manifest snapshot (cheapest; works over public BUCKET_URL):
python scripts/ops/sync_from_r2_manifest.py --manifest-only

# Hydrate named domains + verify checksums where the manifest records them
# (listing objects needs R2 credentials):
python scripts/ops/sync_from_r2_manifest.py --domains boards models gold_products --verify-checksums

# Report drift between the local mirror and the R2 manifest:
python scripts/ops/compare_local_to_r2_manifest.py --local .r2_mirror/prod --json
```

Both tools are **strictly read-only** w.r.t. R2 (`get_object` / `list_objects_v2`
only) and fail loud if R2 is unreachable — they never leave a half-empty mirror
that looks complete, and they never touch `upload.lock`.

**Honesty note:** the manifest records per-object `sha256` for core artifacts
(`basketball.duckdb`) and grouped families (`draft_pick_power/*.parquet`); those
are checksum-verified. Domain sections such as `sportsbook`/`odds` are tracked as
**metadata only** (version, dates) and are reported as such — never falsely
"verified".

---

## 5. Production promotion flow (desktop)

Run this on the **desktop** (the production writer). Every step before the upload
is read-only or local; only `upload_data.sh` (without `--dry-run`) writes R2.

```bash
# 0. Git state — know exactly what you're promoting.
git status && git branch --show-current && git log -1 --oneline

# 1. Validate locally on the producing machine.
python scripts/<pipeline>/validation/validate_pipeline.py    # must reach PASS threshold
#   + dbt build for the affected tags where relevant
#   + npm --prefix web run build   (only if frontend/API touched)

# 2. Dry-run the EXACT domains (read-only; any machine may preview).
bash scripts/upload_data.sh --dry-run --skip-core --odds
bash scripts/upload_data.sh --dry-run --skip-core --sportsbook

# 3. Upload — ONLY from the production writer, one writer at a time.
bash scripts/upload_data.sh --skip-core --odds
bash scripts/upload_data.sh --skip-core --sportsbook

# 4. Post-upload verification.
curl -I "$BUCKET_URL/basketball.duckdb"                       # expect HTTP 200
curl https://bettsbasketball-production.up.railway.app/api/v1/ops/freshness                  # new manifest version, no SLA misses
# smoke the affected domain endpoints
```

**R2 lock discipline (unchanged, non-negotiable):** `upload_data.sh` holds the
single-writer `upload.lock` (TTL 10 min). If you see a lock error, **wait** — never
delete the lock. Full protocol: [DATA_ENGINEERING_PIPELINE.md §0.9](DATA_ENGINEERING_PIPELINE.md#09-r2--railway-multi-session-safety)
and PIPELINE_STANDARDS_TEMPLATE §11.2a.

---

## 6. Per-pipeline run-location

Default lanes per pipeline. "Desktop" means the production orchestrator;
"Laptop" means the dev lane. Production R2 upload is **always** desktop-only.

### ODDS
| Action | Where |
|---|---|
| Daily/rebuild/validate (production) | Desktop only |
| Source expansion / paid pulls | Desktop only, operator-gated (`BETTS_CAN_MAKE_PAID_PROVIDER_CALLS=1` + credit cap) |
| Contract edits / frontend display | Laptop OK |
| Local validation | Laptop OK |
| Production R2 upload | Desktop only |

### Player Game Predictions (PGP)
| Action | Where |
|---|---|
| Daily inference (production) | Desktop |
| Initial candidate training | Laptop OK (writes `.r2_staging`) |
| Champion retrain / promotion | Desktop after a laptop candidate proves out |
| Prediction-cache upload | Desktop only |

Do **not** let a laptop-generated prediction-cache manifest upload to production
while desktop DAGs are also producing daily predictions.

### Sportsbook
| Action | Where |
|---|---|
| Daily products (after ODDS + PGP validated) | Desktop |
| Frontend filters | Laptop OK |
| B12/B13/B14/B16 rebuild | Desktop for prod; laptop for candidate/local testing |
| R2 upload | Desktop only |

Sportsbook consumes PGP prediction-cache + ODDS gold, so it runs **after** those
two are stable.

### Computer Vision
| Action | Where |
|---|---|
| Production / review lane | Desktop (needs the GPU + large video assets) |
| Heavy experiments | Laptop only if explicitly assigned; outputs stay dev/staging |
| R2 promotion (`--cv --skip-core`) | Desktop only, after stage validation |

---

## 7. The ownership matrix

| Action | Desktop | Laptop |
|---|---|---|
| Run unpaused production Airflow DAGs | ✅ | ❌ |
| Run local one-off validation | ✅ | ✅ |
| Run paid Odds provider calls | ✅ operator-gated | ❌ |
| Build candidate features/models | ✅ | ✅ |
| Promote production champion | ✅ | ❌ by default |
| Upload production R2 | ✅ only writer | ❌ |
| Read production R2 | ✅ | ✅ |
| Write dev/staging artifacts | ✅ | ✅ |
| Frontend / API development | ✅ | ✅ |
| Production Railway smoke | ✅ | ✅ read-only |

---

## 8. Conflict resolution — the R2 manifest is the tiebreaker

When the two machines show different inventories, resolve by the **R2 manifest**,
never by trusting a working tree:

```
If the R2 manifest has it:                 production truth is R2.
If desktop has it but R2 does not:         production CANDIDATE until validated + uploaded.
If laptop has it but R2 does not:          development candidate — NEVER production.
If both have different versions:           whichever matches the R2 manifest is truth.
If neither matches the R2 manifest:        STOP and reconcile before uploading.
```

Diagnostics (read-only) — run on both machines:

```bash
git rev-parse HEAD && git log --oneline -5                   # same code SHA?
curl -s "$BUCKET_URL/manifest.json" | jq '.artifact_version, .producer.git_sha, .built_at'
python scripts/ops/compare_local_to_r2_manifest.py --local .r2_mirror/prod
```

If the manifest's `git_sha` matches neither machine's `HEAD`, **someone uploaded
from a stale tree.** Diagnose, do not auto-fix; never "fix" by deleting the lock
or force-pushing.

---

## 9. Emergency writer switch + rollback

The default writer is the desktop. If the desktop is offline and a production
upload is genuinely required, the laptop may become a **temporary** writer:

1. Confirm the desktop scheduler is down and **no `upload.lock` is held**
   (wait out the TTL; never delete it).
2. Record the switch in [`ops/production_writer.md`](../../../ops/production_writer.md):
   who, why, which domains, the rollback manifest version.
3. On the laptop, **edit the root `.env`**: set `BETTS_CAN_WRITE_PROD_R2=1`, run the
   §5 promotion flow, then **revert the line to `0`** immediately after.

   > **Why edit the file (not an inline prefix):** `upload_data.sh` auto-sources the
   > root `.env` *after* the process env is set, and that bash autoload is
   > **file-wins** — an inline `BETTS_CAN_WRITE_PROD_R2=1 bash scripts/upload_data.sh …`
   > gets clobbered back to the `.env` value of `0` and the guard (correctly) denies.
   > The inline prefix is also bash-only syntax; it is a parse error in PowerShell.
   > From PowerShell, run the upload via the wrapper after the `.env` edit:
   > `powershell -ExecutionPolicy Bypass -File scripts/upload_data.ps1 --skip-core --odds`
4. When the desktop returns, re-hydrate both mirrors from the new manifest and
   confirm the desktop is back to being the sole writer.

**Rollback**: every manifest records `previous_version`. To roll back, re-promote
the artifacts named by the previous manifest version from the desktop. Do not
hand-edit R2 objects.

---

## 10. Rollout (mandatory order — read before merging the guards)

The guards are **fail-closed**. The moment they land, the desktop's scheduled
DAGs + R2 uploads + paid pulls will **abort** until the desktop's `.env` grants
the capabilities. Therefore:

1. **Desktop — set BOTH env files** (`.env` AND `api/src/airflow_project/.env`,
   same values; see §3 for why both):
   ```
   BETTS_MACHINE_ROLE=production_orchestrator
   BETTS_CAN_RUN_PROD_DAGS=1
   BETTS_CAN_WRITE_PROD_R2=1
   BETTS_CAN_MAKE_PAID_PROVIDER_CALLS=1
   BETTS_DEFAULT_ARTIFACT_LANE=prod
   ```
2. **Desktop — recreate the Airflow containers** so the new env is baked in, then
   **verify the container actually sees the vars** (this is the step that proves
   the guards will work; the YAML `env_file:` only injects after compose
   substitution, so the `--env-file` is required):
   ```bash
   docker compose --env-file api/src/airflow_project/.env \
     -f docker-compose.nba-airflow.yml -f docker-compose.nba-airflow.local.yml up -d
   docker exec betts_basketball-airflow-scheduler-1 printenv | grep BETTS_
   # expect: production_orchestrator / 1 / 1 / 1 / prod
   ```
3. **Laptop — set BOTH env files**: `BETTS_MACHINE_ROLE=dev_laptop`, all caps `=0`,
   `BETTS_DEFAULT_ARTIFACT_LANE=dev`. (Laptop normally does not run the prod
   scheduler; if it does, `printenv | grep BETTS_` should show all `0`.)
4. **Verify each station** with `python scripts/ops/fleet_preflight.py --station
   {desktop|laptop}` — it asserts role/cap consistency and flags a dev lane that
   wrongly holds prod caps.
5. **Then** merge the guard code using the
   [§16.5 pause→push→pull→manual-trigger→unpause ladder](../PIPELINE_STANDARDS_TEMPLATE.md#165-pausing-the-scheduler-when-you-edit-pipeline-code)
   so no scheduled run fires mid-merge.

**Negative tests (the real proof — run on the laptop, in bash):**

```bash
# real upload must be DENIED (laptop .env has the flag at 0):
bash scripts/upload_data.sh --skip-core --odds        # -> [FAIL] aborts pre-lock
# dry-run preview must still WORK:
bash scripts/upload_data.sh --dry-run --skip-core --odds
```

> Shell note: `VAR=1 command` prefixes are bash-only (PowerShell parse error), and
> for this script they are moot anyway — the `.env` autoload is **file-wins**, so
> the effective flag value is always whatever the root `.env` says. Toggle the
> flag by editing `.env`, never by inline prefix. PowerShell users run uploads via
> `powershell -ExecutionPolicy Bypass -File scripts/upload_data.ps1 <flags>`.

Credentials live only in the gitignored per-machine `.env`; the committed
`.env.example` documents the values. R2 **write** credentials should live on the
desktop; the laptop ideally holds **read-only** R2 credentials.

---

## 11. Upload preflight checklist (before any real R2 write)

- [ ] `BETTS_CAN_WRITE_PROD_R2=1` on this machine (else: run on the desktop)
- [ ] `git status` inspected; you are on the intended SHA
- [ ] No `upload.lock` held (and no active `upload_data.sh` process)
- [ ] `--dry-run` already run for the same domain set
- [ ] Validation report for the changed pipeline is fresh + PASS
- [ ] Exact domain flags only (`--skip-core` unless you intend a core duckdb rebuild)
- [ ] `ops/production_writer.md` reflects the current writer

---

## 12. Negative rules (never do these)

- Never set `BETTS_CAN_WRITE_PROD_R2=1` on the laptop to "just push this once" —
  run it on the desktop, or use the §9 emergency switch with the record.
- Never delete `upload.lock` to unblock an upload. Wait.
- Never make `.r2_mirror/prod` a serving source or edit it by hand.
- Never upload `.r2_staging/*` to the production manifest.
- Never hide a missing artifact behind a fallback row (NaN/503 tell the truth;
  fake values lie — see DATA_ENGINEERING §0.4).
- Never `git push --force` to `main` to "fix" a sync issue.

---

## 13. Daily operating loops

Two truths, two transports:

```
GitHub                = code / config / docs truth
Production R2 manifest = data / artifact truth
```

Never put generated parquet/model/data in git; never treat a local `data/` folder
as production truth. Both stations START from the same production baseline; only
the desktop PUBLISHES back.

### Start of session — BOTH machines

```bash
git status && git branch --show-current
git fetch origin && git pull --ff-only
python scripts/ops/fleet_preflight.py --station {desktop|laptop}      # READY?
python scripts/ops/sync_from_r2_manifest.py --manifest-only          # refresh manifest snapshot
python scripts/ops/compare_local_to_r2_manifest.py --local .r2_mirror/prod   # drift?
```

### Publish — DESKTOP only

```bash
# validate the changed pipeline -> dbt -> (frontend build if touched)
bash scripts/upload_data.sh --dry-run --skip-core <domain flags>     # preview
bash scripts/upload_data.sh --skip-core <domain flags>               # write (one writer)
curl -I "$BUCKET_URL/basketball.duckdb"                              # 200
curl https://bettsbasketball-production.up.railway.app/api/v1/ops/freshness                          # new manifest version
# update ops/production_writer.md if the writer/rollback changed
```

### After a publish — BOTH machines re-baseline

```bash
git pull --ff-only
python scripts/ops/sync_from_r2_manifest.py --domains <changed domains> --verify-checksums
python scripts/ops/compare_local_to_r2_manifest.py --local .r2_mirror/prod
```

## 14. Working locally from the production mirror (don't clobber candidates)

```
.r2_mirror/prod                  = read-only production reference (synced from manifest)
data/ , cache/ , reports/        = local working data (may differ per machine)
.r2_staging/<machine>/<run_id>/  = your candidate outputs (never promoted directly)
```

Do **not** blanket-overwrite local `data/` from R2 — that can wipe in-progress
candidate work. Hydrate only the **specific domain** you need, through the guarded
copy tool (dry-run by default, refuses to clobber uncommitted changes, backs up
what it overwrites):

```bash
# preview, then apply:
python scripts/ops/hydrate_local_from_r2_mirror.py --from-prefix odds/gold/ --into data/odds/gold
python scripts/ops/hydrate_local_from_r2_mirror.py --from-prefix odds/gold/ --into data/odds/gold --apply
```

Write experiments/candidates to `data/` or `.r2_staging/<machine>/<run_id>/`, never
to production R2. Promotion happens on the desktop after your code is merged.

## 15. Branch + GitHub standard (code truth)

```
main               production-safe, validated code (deploy branch)
session/<topic>    active laptop/desktop development
hotfix/<topic>     urgent production repair
```

Push with **exact staging** — never `git add -A` (the 2026-06-11 incident mixed
generated `*/artifacts/*.json` + `reports/*` into real work):

```bash
git status && git diff --stat
git add <exact-code/doc/test files>          # explicit paths only
git diff --cached --stat                      # confirm blast radius
git commit -m "<clear message>" && git push origin session/<topic>
```

Do not commit: `data/`, `cache/`, generated `reports/*`, `*.parquet`, `*.duckdb`,
model artifacts, `.r2_mirror/`, `.r2_staging/`, `.upload_staging/`. Run
`python scripts/ops/fleet_closeout.py` — it splits your changes into
stage-these / never-stage-these.

**Laptop → desktop handoff**: laptop pushes code; desktop `git pull --ff-only`,
reruns the affected pipeline + validation, dry-runs, then promotes R2.

## 16. Sync checkpoints + per-pipeline pull/push order

You cannot keep both stations continuously identical while the desktop runs DAGs
and the laptop experiments — but you can make them **perfect at checkpoints**:

| Moment | Required sync |
|--------|---------------|
| Before starting work | git pull + `sync_from_r2_manifest --manifest-only` + compare |
| Before running a pipeline locally | hydrate the upstream domains that pipeline needs |
| Before validating | compare mirror to R2 manifest |
| Before production upload (desktop) | git clean/review + local validation + dry-run |
| After production upload | both stations sync the changed domains + compare |
| Before merging code | focused tests + exact-file staging |

Per-pipeline upstream domains to hydrate before working, and publish flags
(desktop only):

| Pipeline | Hydrate before work | Desktop publish |
|----------|---------------------|-----------------|
| ODDS | `--domains odds` | `--skip-core --odds` |
| PGP | `--domains predictions odds` | `--skip-core --prediction-cache --game-adjustments` |
| Sportsbook | `--domains sportsbook predictions odds` | `--skip-core --sportsbook` |

ODDS + Sportsbook publish as **separate** `--skip-core` artifact-only passes after
validation; Sportsbook runs **after** ODDS + PGP are stable.

## 17. Fleet helper tools (scripts/ops/)

| Tool | Purpose | Mutates? |
|------|---------|----------|
| `fleet_preflight.py` | "am I configured + safe to work?" (role/caps, git, mirror, lock, writer file) | read-only |
| `sync_from_r2_manifest.py` | hydrate `.r2_mirror/prod` from the R2 manifest | read-only vs R2 |
| `compare_local_to_r2_manifest.py` | drift report (sha256 vs manifest; metadata-only domains labeled) | read-only |
| `hydrate_local_from_r2_mirror.py` | guarded copy mirror → active local path (dry-run default, backups) | local only, guarded |
| `fleet_closeout.py` | end-of-session: what to stage vs never-stage, mirror drift, promotion-required | read-only |
| `normalize_project_doc_headers.py` | idempotent banner on project docs | docs only |

## 18. Why this exists — the 2026-06-11 R2 split-brain

This standard is not hypothetical. On **2026-06-11 12:02–12:50Z**, a second
producer machine uploaded R2 from a **partial local tree**: all 5 ODDS gold
products were overwritten (`game_lines` → 85 KB), exchange/DFS manifest entries
nulled, the sportsbook manifest dropped 157 → 38 snapshots, and the
`basketball_multileague` key was lost. `upload_data.sh` was hardened in response
(manifest UNION + domain preservation + boto3-first lock reads + an ODDS
coverage-monotonicity gate). **This machine-writer boundary is the upstream fix**:
with one designated writer, two machines cannot race the manifest.

**Emergency restore (this is the §9 emergency-writer path in practice).** When the
machine that holds the canonical data must restore R2 after the *other* machine
regressed it: confirm the other machine has pulled the fixes and paused its
upload tasks, wait out `upload.lock` (never delete), then **edit the restoring
machine's root `.env`** to `BETTS_CAN_WRITE_PROD_R2=1` (an inline env prefix does
NOT work — the script's `.env` autoload is file-wins and clobbers it; see §9), run
the dry-run-verified `--skip-core --odds` / `--sportsbook` /
`--basketball-multileague` passes, then revert the `.env` line to `0` and record
the switch in `ops/production_writer.md`. The coverage gate will (intentionally) make
the regressed machine's next upload fail until it re-hydrates.
