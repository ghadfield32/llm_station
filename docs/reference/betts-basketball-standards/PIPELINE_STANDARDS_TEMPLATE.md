# Pipeline Standards Template

**Version**: 2.2 | **Last Updated**: 2026-06-11 (Session 2026-06-11: §16 hardened into an enforced two-machine execution-lane contract — §16.9 env-var role gates, §16.10 .r2_mirror/.r2_staging model, §16.11 per-pipeline run-location, §16.12 upload preflight + writer ownership; canonical doc LOCAL_FLEET_R2_WORKFLOW.md) | (2026-04-29: §11.9 DAG operations capacity dashboard standard)


A step-by-step guide for building new data and ML pipelines in this project.
Every pipeline in the codebase follows these conventions. Use this document
as a checklist when creating a new pipeline from scratch.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Step 1 -- Create the Directory Structure](#2-step-1----create-the-directory-structure)
3. [Step 2 -- Define the Pipeline Config](#3-step-2----define-the-pipeline-config)
4. [Step 3 -- Build the Medallion Data Layers](#4-step-3----build-the-medallion-data-layers)
5. [Step 4 -- Add ML Pipelines (if needed)](#5-step-4----add-ml-pipelines-if-needed)
6. [Step 5 -- Write the Orchestrator](#6-step-5----write-the-orchestrator)
7. [Step 6 -- Add the Airflow DAG](#7-step-6----add-the-airflow-dag)
8. [Step 7 -- Write the Validation Suite](#8-step-7----write-the-validation-suite)
   - [8.1 Validation Script Structure](#81-validation-script-structure)
   - [8.2 Validation Principles](#82-validation-principles)
   - [8.3 Audit Script (for ML pipelines)](#83-audit-script-for-ml-pipelines)
   - [8.4 Daily Pipeline Report](#84-daily-pipeline-report-session-366-pattern)
   - [8.5 Incremental Mode Pattern](#85-incremental-mode-pattern-for-daily-pipelines)
   - [8.6 Shared-Volume Write Hygiene (Atomic Writes)](#86-shared-volume-write-hygiene-atomic-writes)
9. [Step 8 -- Wire API Endpoints](#9-step-8----wire-api-endpoints)
10. [Step 9 -- Add dbt Models](#10-step-9----add-dbt-models)
11. [Step 10 -- Wire R2 Artifact Promotion](#11-step-10----wire-r2-artifact-promotion)
   - [11.1a Data Layer Decision Tree (R2 vs Local DuckDB vs Railway)](#111a-data-layer-decision-tree-r2-vs-local-duckdb-vs-railway-postgres)
   - [11.2a R2 Advisory Lock — Single-Writer Safety](#112a-r2-advisory-lock--single-writer-safety)
   - [11.2b R2 Data Safety — DAG/Session Conflicts and Validation](#112b-r2-data-safety--dagsession-conflicts-and-validation)
   - [11.8 Local Full-DAG -> Staging -> Production Gate](#118-local-full-dag---staging---production-gate)
   - [11.8.1 DAG Ready To Unpause](#1181-dag-ready-to-unpause-checklist)
   - [11.8.2 Root-Cause Taxonomy](#1182-root-cause-taxonomy-required)
   - [11.8.3 GPU Training Contract](#1183-gpu-training-contract-required)
   - [11.8.4 Artifact Versioning & Rollback Contract](#1184-artifact-versioning--rollback-contract-required)
   - [11.9 DAG Operations Capacity Dashboard Standard](#119-dag-operations-capacity-dashboard-standard)
12. [Step 11 -- Document and Ship](#12-step-11----document-and-ship)
   - [12.4 Documentation Hygiene for Multi-Session Continuity](#124-documentation-hygiene-for-multi-session-continuity)
13. [Reference: Existing Pipelines](#13-reference-existing-pipelines)
14. [Anti-Patterns](#14-anti-patterns)
15. [Multi-Session Development Standards](#15-multi-session-development-standards)
   - [15.6 Merge Conflict Recipes (by File Type)](#156-merge-conflict-recipes-by-file-type)
16. [Multi-Machine Role Contract (Desktop Scheduler + Laptop Dev)](#16-multi-machine-role-contract-desktop-scheduler--laptop-dev)
   - [16.9 Enforced Env-Var Role Contract](#169-enforced-env-var-role-contract)
   - [16.10 Local Mirror / Staging Model (.r2_mirror, .r2_staging)](#1610-local-mirror--staging-model-r2_mirror-r2_staging)
   - [16.11 Per-Pipeline Run-Location](#1611-per-pipeline-run-location)
   - [16.12 Upload Preflight + Writer Ownership](#1612-upload-preflight--writer-ownership)

---

## 1. Overview

Every pipeline in this project follows a standard architecture:

```
Source Data --> Bronze --> Silver --> Gold --> ML (optional) --> dbt --> Validate --> R2 --> API
```

**Key principles:**

- **Medallion architecture** -- raw data (bronze), standardized data (silver),
  analytics-ready data (gold). Each layer is immutable once written.
- **Schema-driven ML** -- YAML schemas define targets, features, forbidden
  features, and column types. New ML domains are added via config, not code.
- **Gold is the source of truth** -- all downstream analysis, ML training,
  and API serving reads from gold. Never read from silver or bronze.
- **Pipelines are independent** -- pipelines never share raw data, IDs, or
  intermediate tables. Cross-pipeline joins happen only in the dbt analytical
  layer.
- **R2 is the transport layer** -- validated artifacts are promoted to
  Cloudflare R2 (S3-compatible) via `scripts/upload_data.sh`. Railway replicas
  download on boot and hot-reload on manifest change. Pipelines never run on
  Railway.
- **GPU routing and backend verification are separate** -- run GPU-capable
  retrains through the datascience container, but log the actual backend
  (`jax.default_backend()`, device list, or library-equivalent). Container name
  or visible hardware alone is not proof the model trained on CUDA.
- **Temporal evaluation and forward serving are separate** -- if a model uses
  holdout seasons for validation, keep that path explicit. Current-season or
  future serving must score a dedicated forward inference frame and surface the
  training cutoff / provenance in downstream products.
- **Champion promotion validates the artifact contract** -- promotion is not
  metric-only. If the saved artifact fails structural validation for serving,
  it is not a valid champion even if historical evaluation metrics look good.
- **Diagnostics must compare aligned units** -- rate thresholds are checked
  against rates, count thresholds against counts. Do not reconstruct a count
  gate from a stripped artifact when the training contract recorded a rate.
- **Forward-temporal artifacts must keep the temporal contract explicit** --
  if current or future periods are served, a schema-declared temporal group
  cannot be silently complete-pooled away. The pipeline must either retain the
  temporal effect for the serving artifact or fail the build and document why.
- **Prep/orchestrator wrappers must publish a complete contract** -- if a
  wrapper stage declares gold ready, it must include every contract-producing
  enrichment that downstream stages require. Omitting RAPM, ensemble, or other
  required enrichments is a build failure, not a soft warning.
- **Internal temporal keys stay canonical** -- choose one temporal key
  (`SEASON_ID`, `GAME_DATE`, etc.) for internal joins, validation, and dbt
  models. Alias to legacy names only at the final output edge when required.

### Reference Documentation

| Doc | Purpose |
|-----|---------|
| [DATA_ENGINEERING_PIPELINE.md](engineering/DATA_ENGINEERING_PIPELINE.md) | Medallion architecture, bronze/silver/gold contracts, dbt layer, R2 artifact promotion (Section 19) |
| [USER_STRATEGY_MARKETING_SECURITY.md](projects/USER_STRATEGY_MARKETING_SECURITY.md) | User/product Postgres pipeline + Railway frontend Vite build-args (Clerk); not R2-backed |
| [UNIFIED_SERVING_GUIDE.md](modeling/UNIFIED_SERVING_GUIDE.md) | API middleware stack, router registration, model serving |
| [CLUSTERING_PIPELINE.md](modeling/CLUSTERING_PIPELINE.md) | Schema-driven clustering (KMeans/GMM, 16 roles, YAML config) |
| [GBDT_PIPELINE_GUIDE.md](modeling/GBDT_PIPELINE_GUIDE.md) | GBDT pipeline (XGBoost/LightGBM/CatBoost, 20 targets, Optuna) |
| [BAYESIAN_PIPELINE_GUIDE.md](modeling/BAYESIAN_PIPELINE_GUIDE.md) | Bayesian pipeline (PyMC/NumPyro, hierarchical models, 8-phase diagnostics) |

---

## 2. Step 1 -- Create the Directory Structure

Every pipeline needs three locations: importable code, CLI scripts, and data.

### 2.1 Pipeline Code Module

Create a package under `api/src/pipelines/`:

```
api/src/pipelines/{pipeline_name}/
    __init__.py          # Public API exports
    config.py            # Frozen dataclass settings (paths, constants)
    etl.py               # Bronze -> Silver -> Gold transforms (if applicable)
    pipeline.py          # Pipeline orchestration class (if applicable)
```

The `__init__.py` exports the public API:

```python
"""
{Pipeline Name} Pipeline

One-line description of what this pipeline does (source -> output).
"""

from .config import settings
from .etl import SomeETLClass
from .pipeline import SomePipeline, SomePipelineError

__all__ = [
    'settings',
    'SomeETLClass',
    'SomePipeline',
    'SomePipelineError',
]
```

**When the pipeline is large** and the core logic lives elsewhere (feature
engineering in `api/src/ml/`, models in `api/src/ml/modeling/`), use a thin
adapter -- a docstring-only `__init__.py` that points to the real locations:

```python
"""
{Pipeline Name} Pipeline -- Thin adapter.

Core logic lives in:
  - scripts/{pipeline_name}/stages/     (stage scripts)
  - api/src/ml/features/                (feature engineering)
  - api/src/ml/modeling/bayesian/        (Bayesian models)
  - api/src/ml/modeling/gddt/            (GBDT models)

YAML schemas:
  - api/src/ml/modeling/bayesian/config/schemas/column_schema.yaml
  - api/src/ml/modeling/gddt/config/schemas/gbdt_master_schema.yaml
"""
```

### 2.2 CLI Scripts

Create directories under `scripts/` organized by function:

```
scripts/{pipeline_name}/
    run_pipeline.py              # Main orchestrator (entry point)
    stages/                      # Numbered stage scripts (S1, S2, ...)
    data/                        # Data building scripts (build_*, merge_*)
    calibration/                 # Calibration scripts (fit_*, calibrate_*)
    validation/                  # Validation scripts (validate_*, audit_*)
    backtests/                   # Temporal backtests
    training/                    # Model training scripts
    analysis/                    # Exploratory scripts (explain_*, debug_*)
```

Every script must set up `sys.path` before imports:

```python
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[N]  # N = depth from repo root
sys.path.insert(0, str(PROJECT_ROOT / "api" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "api"))
sys.path.insert(0, str(PROJECT_ROOT))
```

Use all three package roots when the repo mixes import styles:
- `PROJECT_ROOT` for `from api.src...`
- `PROJECT_ROOT / "api"` for legacy `from src...`
- `PROJECT_ROOT / "api" / "src"` for direct `from ml...` / `from airflow_project...`

Do not assume the caller's shell `PYTHONPATH` will supply missing roots.

For Windows Unicode compatibility, add at the top of any script that writes
to stdout:

```python
sys.stdout.reconfigure(encoding='utf-8')
```

### 2.3 Data Directories

Create medallion directories:

```
data/{pipeline_name}/
    bronze/          # Raw source data (JSON, CSV, gz)
    silver/          # Standardized parquet (Hive-partitioned)
    gold/            # Analytics-ready parquet
        features/    # Feature engineering outputs
        products/    # Final analytical products (marts)
        artifacts/   # Calibration files, model params
```

Or under `api/src/airflow_project/data/` if tightly coupled to Airflow:

```
api/src/airflow_project/data/
    bronze/{pipeline_name}/
    silver/{pipeline_name}/
    gold/{pipeline_name}/
```

### 2.4 Model Artifacts

Trained model files go under `models/`:

```
models/{pipeline_name}/
    {model_type}_champion_{season}.joblib   # Champion models
    {model_type}_model_{season}.joblib      # All trained models
```

Or under `cache/models/` for pipeline-specific artifacts:

```
cache/models/
    registry.json              # Version registry
    {model_name}_v{N}.pkl      # Versioned model files
```

---

## 3. Step 2 -- Define the Pipeline Config

Use a frozen dataclass with `@property` methods for all paths:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelineSettings:
    """Resolved project paths for the {pipeline_name} pipeline."""

    project_root: Path = Path(__file__).resolve().parents[4]
    # Adjust parents[N] so project_root == repo root

    # ---- Bronze ----
    @property
    def bronze_root(self) -> Path:
        return self.project_root / "data" / "{pipeline_name}" / "bronze"

    # ---- Silver ----
    @property
    def silver_root(self) -> Path:
        return self.project_root / "data" / "{pipeline_name}" / "silver"

    # ---- Gold ----
    @property
    def gold_root(self) -> Path:
        return self.project_root / "data" / "{pipeline_name}" / "gold"

    @property
    def gold_features(self) -> Path:
        return self.gold_root / "features"

    @property
    def gold_products(self) -> Path:
        return self.gold_root / "products"

    # ---- Models ----
    @property
    def model_dir(self) -> Path:
        return self.project_root / "models" / "{pipeline_name}"

    # ---- Validation ----
    @property
    def validation_root(self) -> Path:
        return self.gold_root / "validation"

    # ---- DuckDB ----
    @property
    def duckdb_path(self) -> Path:
        return self.project_root / "api" / "de" / "basketball" / "basketball.duckdb"

    # ---- R2 Upload ----
    @property
    def upload_script(self) -> Path:
        return self.project_root / "scripts" / "upload_data.sh"

    @property
    def r2_upload_flags(self) -> list[str]:
        """Flags passed to upload_data.sh for this pipeline's artifacts."""
        # Override per-pipeline. Examples:
        #   ["--gold-products"]           # uploads basketball.duckdb + manifest
        #   ["--boards", "--skip-core"]   # uploads big boards only (skip duckdb)
        #   ["--referees", "--skip-core"] # uploads referee parquets only
        return ["--skip-core"]  # Default: pipeline-specific artifacts only


# Module-level singleton
settings = PipelineSettings()
```

**Rules:**

- `frozen=True` -- paths are immutable once instantiated
- All paths are `@property` methods computed from `project_root`
- Export a module-level `settings` singleton
- No hardcoded absolute paths -- everything is relative to `project_root`

---

## 4. Step 3 -- Build the Medallion Data Layers

### 4.1 Bronze Layer

Bronze is raw source data, stored exactly as received. Never modified after
initial ingestion.

**File format contract** (for API-sourced data):

```json
{
  "data": [...],
  "metadata": {
    "source": "api_name",
    "fetched_at": "2026-03-02T12:00:00Z",
    "endpoint": "/some/endpoint",
    "params": {"season": "2024-25"}
  }
}
```

This `{"data": [...], "metadata": {...}}` wrapper is a **hard contract**.
Downstream silver parsers check `"data" in game_data` -- raw lists break
parsing.

**For parquet bronze** (e.g., scraped tabular data):

```
data/{pipeline_name}/bronze/
    {source}_{date}.parquet
```

Include provenance columns: `SOURCE`, `FETCHED_AT`, `RAW_URL` (if applicable).

### 4.2 Silver Layer

Silver standardizes raw data into a consistent schema. Stored as
Hive-partitioned parquet.

```
data/{pipeline_name}/silver/
    {entity_type}/
        partition_key={value}/
            data.parquet
```

**Standard columns** every silver table should have:

| Column | Type | Description |
|--------|------|-------------|
| Primary key(s) | str | `GAME_ID`, `PLAYER_ID`, `TEAM_ID`, etc. |
| `SOURCE_PLAYER_ID` | str | Format: `{prefix}:{id}` (e.g., `ncaa_mbb:12345`) |
| `SEASON` or `SEASON_CODE` | str | `"2023-2024"` format (string, not int) |
| Temporal key | str/date | `GAME_DATE`, `SEASON_ID`, etc. |

**Silver builder pattern:**

```python
def build_silver(bronze_path: Path, silver_path: Path) -> pd.DataFrame:
    """Convert bronze to silver for one partition."""
    raw = load_bronze(bronze_path)  # handles wrapper extraction

    df = pd.DataFrame(raw["data"])

    # 1. Standardize column names (UPPERCASE)
    df.columns = [c.upper().replace(" ", "_") for c in df.columns]

    # 2. Type coercion (numeric columns)
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        # NO .fillna(0) -- NaN propagates as missing-data signal

    # 3. Add provenance
    df["SOURCE"] = "api_name"
    df["INGESTED_AT"] = pd.Timestamp.now(tz="UTC")

    # 4. Write Hive-partitioned parquet
    df.to_parquet(silver_path / "data.parquet", index=False)
    return df
```

### 4.3 Gold Layer

Gold is the analytics-ready layer. All downstream consumers (ML pipelines,
API endpoints, dashboards) read from gold.

**Gold promotion rules:**

1. Apply column corrections (swapped columns, renamed fields)
2. Apply deduplication (one row per entity per time grain)
3. Validate schema (expected columns, types, non-null keys)
4. Write to gold path

**Gold validation gate** (run before declaring gold ready):

```python
def validate_gold(gold_path: Path) -> bool:
    """8-check validation gate for gold data."""
    df = pd.read_parquet(gold_path)
    checks = [
        ("has_rows", len(df) > 0),
        ("no_dup_keys", df.duplicated(subset=KEY_COLS).sum() == 0),
        ("required_cols", all(c in df.columns for c in REQUIRED_COLS)),
        ("no_null_keys", df[KEY_COLS].notna().all().all()),
        ("numeric_types", all(df[c].dtype.kind in "fi" for c in NUMERIC_COLS)),
        ("season_format", df["SEASON_CODE"].str.match(r"\d{4}-\d{4}").all()),
        ("positive_minutes", (df["MIN"].dropna() >= 0).all()),
        ("no_future_dates", (df["GAME_DATE"] <= pd.Timestamp.now()).all()),
    ]
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    return all(passed for _, passed in checks)
```

**Data-derived decisions only**: All thresholds in gold promotion must come
from the data itself (percentiles, historical means, statistical tests).
Never hardcode bounds like "FG% must be between 0.3 and 0.7" -- instead
derive from `df["FG_PCT"].quantile([0.01, 0.99])` or use domain-specific
statistical tests.

**No fake values or fallbacks**: If a computation cannot produce a result
(missing upstream data, insufficient sample size), the output is NaN. Never
substitute a plausible default. NaN propagates as intentional signal -- it
is the correct representation of "we don't know."

**No silent error swallowing**: Gold promotion scripts must not use
`except: pass` or `except Exception: return default`. If a bronze file is
corrupt or a silver transform fails, the error surfaces immediately. Fix
the root cause, do not paper over it.

> **Offline / degraded-service clarification (added 2026-04-27)**: the rules
> above are about **data fallbacks**, not **service availability fallbacks**.
> They are different things and must be handled differently.
>
> - **Data fallback (forbidden):** computing a missing FG% as 0.5 because
>   "0.5 is the league average" is a fake value — it falsifies signal. NaN
>   instead. Same for: hardcoded defaults for missing minutes, plausible
>   guesses for missing birthdate, "let's just use median" without a
>   data-derived justification. These are forbidden everywhere.
> - **Service-availability fallback (allowed, with discipline):** the
>   pipeline reads from R2; R2 is briefly unreachable; what should the
>   pipeline do? It depends on the role:
>   - **Pipeline / DAG**: fail fast with a descriptive error (`R2GetError`
>     with the bucket key and timestamp). Do not retry silently in a loop;
>     the scheduler's retry policy handles that. Do not fall back to a
>     local stale copy and pretend the run succeeded.
>   - **Serving endpoint**: serve from the locally-bootstrapped DuckDB if it
>     exists (this is the normal serving path). If the local DuckDB is
>     missing AND R2 is unreachable, raise `503 Service Unavailable` with a
>     clear message — do **not** return `200 OK` with empty/default data.
>   - **Optional integration** (e.g., `AWS_ENDPOINT_URL` not set in a dev
>     environment): a graceful skip is acceptable IFF (a) the skip is logged
>     with a clear `[SKIP] reason: AWS_ENDPOINT_URL not set` message,
>     (b) downstream consumers can detect the skip via the manifest
>     (e.g., `manifest.r2_upload_skipped = true`), and (c) the spec doc
>     documents that the skip is the expected dev-environment behavior.
>
> **The test:** if the user could be misled into thinking everything worked
> when it didn't, the fallback is wrong. If the user (or operator, or
> downstream pipeline) is told clearly "this didn't run, here's why," the
> fallback is acceptable. NaN tells the truth about data; 503 tells the
> truth about service. Both are good. Substituting league average for missing
> data, or returning empty `[]` for an unreachable backend, lies.

### 4.4 Medallion Flow Summary

```
Bronze                 Silver                 Gold
(raw, immutable)  -->  (standardized)    -->  (analytics-ready)
                       - UPPERCASE cols        - Corrections applied
                       - Type coercion         - Deduplicated
                       - Hive partitioned      - Schema validated
                       - NaN for missing       - Gate checks passed
```

---

## 5. Step 4 -- Add ML Pipelines (if needed)

This project has three reusable ML pipeline frameworks. **Check whether the
existing pipeline can handle your domain via YAML config before writing new
Python code.** See the decision checklist in CLAUDE.md under "ML Pipeline
Reuse".

### 5.1 Decision: Which ML Pipeline?

| Pipeline | Best For | Entry Point |
|----------|----------|-------------|
| **Clustering** | Grouping entities (players, coaches, teams) into archetypes | [CLUSTERING_PIPELINE.md](modeling/CLUSTERING_PIPELINE.md) |
| **GBDT** | Tabular prediction (classification, regression) | [GBDT_PIPELINE_GUIDE.md](modeling/GBDT_PIPELINE_GUIDE.md) |
| **Bayesian** | Uncertainty quantification, hierarchical effects, count data | [BAYESIAN_PIPELINE_GUIDE.md](modeling/BAYESIAN_PIPELINE_GUIDE.md) |

### 5.2 Adding a Clustering Domain

1. Copy the template schema:

```bash
cp api/src/ml/features/clustering_pipeline/schemas/clustering_template.yaml \
   api/src/ml/features/clustering_pipeline/schemas/clustering_{domain}.yaml
```

2. Define feature groups in the new YAML:

```yaml
domain: {domain_name}
version: "1.0.0"

filters:
  min_games: 15
  min_minutes: 350

features:
  core:           # Always included in PCA
    - PTS
    - AST
    - TRB
  shooting:       # Optional category
    - "FG%"
    - "3P%"
  advanced:       # Optional
    - "USG%"
  impact_only:    # Excluded from PCA, used for IMPACT_TIER only
    - BPM
```

3. Create a domain adapter extending `BaseClusteringAdapter` in
   `api/src/ml/features/clustering_core/adapters/`.

4. Run: `GenericClusteringPipeline.from_schema("path/to/schema.yaml")`

### 5.3 Adding a GBDT Target

1. Add a target definition to the appropriate master schema YAML:

```yaml
# In gbdt_master_schema.yaml (or gbdt_prospect_master_schema.yaml)
target_definitions:

  NEW_TARGET:
    display_name: "Human-Readable Name"
    task: "regression"              # or "classification"
    recommended_models: ["xgboost", "lightgbm", "catboost"]
    search_space_budget: "medium"   # low=25, medium=50, high=100 Optuna trials
    default_max_features: 25
    promotion:
      metric: "rmse"               # or "auc", "mae", "f1"
      direction: "lower_is_better" # or "higher_is_better"
    forbidden_features:             # LEAKAGE PREVENTION
      - EXACT_COMPONENT_1          # Direct components of target
      - EXACT_COMPONENT_2
      - DERIVED_FEATURE            # Features computed from target
      - OTHER_TARGET               # Other prediction targets
```

2. Add a granularity schema if this is a new data grain:

```yaml
# gbdt_{granularity}.yaml
id:
  - ENTITY_ID
  - GAME_ID

temporal_columns:
  - SEASON_ID

numerical:
  - PTS
  - AST
  - TRB

ordinal: []

nominal:
  - POSITION
  - TEAM_ABBREVIATION

target:
  - NEW_TARGET

imputation:
  default: "median"
  overrides:
    POSITION: "mode"
```

3. Register the granularity in `api/src/ml/modeling/gddt/config/gbdt_config.py`.

4. Run:

```python
from api.src.ml.modeling.gddt import GDDTConfig, GDDTTrainer

config = GDDTConfig(target="NEW_TARGET", granularity="NEW_GRANULARITY")
trainer = GDDTTrainer(config)
results = trainer.run_full_pipeline()
```

### 5.4 Adding a Bayesian Target

1. Add to the column schema YAML for the granularity:

```yaml
# column_schema_{granularity}.yaml
target_definitions:
  NEW_TARGET:
    forbidden_features:
      - COMPONENT_1
      - COMPONENT_2
```

2. The pipeline auto-routes to the correct likelihood family (NegBin, Poisson,
   ZINB, Normal, Beta) via overdispersion tests. No code changes needed.

3. Add hierarchical effects if applicable:

```yaml
hierarchical_effects:
  ENTITY_ID:
    preference: random           # data-driven sigma
    allow_override: true
  GROUP_ID:
    preference: random_tight     # tight prior (low ICC)
    hyperprior_sigma: 0.05
```

4. Register in `api/src/ml/column_schema.py` and `api/src/ml/config.py`.

### 5.5 Forbidden Features (Leakage Prevention)

Every ML target must have a `forbidden_features` list in its YAML schema.
This is the primary leakage prevention mechanism.

**What to forbid:**

| Category | Examples | Why |
|----------|----------|-----|
| Direct components | FG, FT, FGA for PTS target | PTS = 2*FG + 3P + FT |
| Derived features | FG_PCT, TS_PCT for shooting targets | Computed from target components |
| Other targets | NBA_STARTER_3YR for MADE_NBA | Mutual leakage between labels |
| Future-only features | NBA_FIRST_YEAR, NBA_GAMES_PRIOR | Only known after outcome |
| Censored indicators | IS_CENSORED, DRAFT_YEAR | Encode outcome information |
| Career projections | AGE_CURVE_MULT, PEAK_AGE | NBA-role-based, not pre-draft |

**Use the schema generator to find candidates:**

```python
from api.src.ml.modeling.gddt.config.schema import SchemaGenerator
candidates = SchemaGenerator.suggest_forbidden_features(df, "NEW_TARGET")
```

**Sync rule:** If both GBDT and Bayesian schemas define the same target, their
`forbidden_features` lists must be identical. The authoritative source is
whichever schema was defined first.

### 5.6 Data Leakage Prevention & Temporal Safety

Beyond `forbidden_features`, every forecasting pipeline must enforce these
rules to prevent data leakage. A pipeline that passes all validation gates
but leaks future information into training produces overconfident, unreliable
predictions.

#### 5.6.1 Temporal Safety

All features must use strict temporal cutoffs. Same-game or same-day data
is never available at prediction time.

```python
# CORRECT -- strict past-only cutoff:
features = df[df["GAME_DATE"] < cutoff_date]

# WRONG -- includes the target game:
features = df[df["GAME_DATE"] <= cutoff_date]

# WRONG -- rolling window includes current row:
df["ROLLING_PTS"] = df.groupby("PLAYER_ID")["PTS"].transform(
    lambda x: x.rolling(10).mean()  # includes current game!
)

# CORRECT -- shift(1) excludes current game:
df["ROLLING_PTS"] = df.groupby("PLAYER_ID")["PTS"].transform(
    lambda x: x.shift(1).rolling(10).mean()
)
```

**Rule**: Every cumulative or rolling feature must use `.shift(1)` or
equivalent to exclude the current observation.

#### 5.6.2 Stage Ordering (Linear Dependency Enforcement)

Stages are numbered and form a strict linear chain. Each stage can ONLY
read outputs from prior stages. No forward references, no circular
dependencies.

```
S0 (data) -> V0 (gate) -> S1 (priors) -> S2 (train) -> S3 (test) -> SIM -> dbt
     |            |             |              |             |
     v            v             v              v             v
  Reads:       Reads:        Reads:         Reads:        Reads:
  bronze       S0 output     V0-gated       V0-gated      S2 models
  upstream     only          S0 output      S0 output     S1 priors
  gold                       only           only          S0 data
```

**Validation gates block downstream**: If V0 fails, S1/S2/S3/SIM do not
run. This is enforced by the orchestrator's `depends_on` + `blocking: True`
mechanism (see Section 6.1).

#### 5.6.3 Train/Test Contamination

Time-series data requires temporal cross-validation. Random splits are
forbidden because they leak future information into training.

| Pattern | Rule |
|---------|------|
| **Expanding window** | Train on years < Y, test on year Y. Repeat. |
| **Walk-forward** | Train on [Y-3, Y-1], test on Y. Slide window. |
| **Never random split** | `train_test_split(shuffle=True)` is forbidden for temporal data. |
| **Nested CV for hyperparams** | Inner loop trains on years < Y, outer loop evaluates on Y. |

```python
# CORRECT -- temporal expanding window:
for test_year in [2021, 2022, 2023]:
    train = df[df["SEASON_YEAR"] < test_year]
    test = df[df["SEASON_YEAR"] == test_year]
    model.fit(train[features], train[target])
    preds = model.predict(test[features])

# WRONG -- random split leaks future:
from sklearn.model_selection import train_test_split
train, test = train_test_split(df, test_size=0.2, shuffle=True)  # FORBIDDEN
```

#### 5.6.4 Cross-Pipeline Leakage

Never merge player data across pipelines on `PLAYER_NAME` -- name
collisions create cartesian products. Use the canonical ID chain:

```
SOURCE_PLAYER_ID -> CANONICAL_PLAYER_ID -> NBA_PLAYER_ID
```

Cross-pipeline joins happen ONLY in the dbt analytical layer (Section 10.6).

#### 5.6.5 Leakage Prevention Gate Checklist

Run this checklist before any ML pipeline ships:

| Check | What to Verify | How |
|-------|----------------|-----|
| Forbidden features | Target components excluded from feature set | `SchemaGenerator.suggest_forbidden_features(df, target)` |
| Temporal cutoff | All features use `< cutoff`, not `<=` | Grep for `<=.*cutoff` in feature code |
| Rolling window shift | Cumulative features use `.shift(1)` | Grep for `.rolling(` without preceding `.shift(1)` |
| Future-only columns | `NBA_FIRST_YEAR`, `DRAFT_YEAR`, outcome labels excluded | Inspect `forbidden_features` YAML |
| No random splits | All CV uses temporal splits | Grep for `shuffle=True` in training code |
| No cross-pipeline name merge | No `merge(..., on="PLAYER_NAME")` across pipelines | Grep for `PLAYER_NAME.*merge` |

---

### 5.7 Artifact Contracts (PR 71 Stage C)

**Problem solved.** The scheduler doesn't know about cross-DAG artifact
dependencies — they're implicit in code. A daily DAG that consumes a
file produced by a training DAG has no way to express "do not run me
unless that file exists and is fresh." The result: opaque
`FileNotFoundError` or `CatalogException` mid-stage, no clear
attribution, and operators guessing which upstream DAG is the culprit.

**Solution.** Every DAG declares two YAML files under
`api/src/airflow_project/dags/artifact_contracts/`:

```
artifact_contracts/
    <dag_id>.producer.yaml   # what this DAG writes
    <dag_id>.consumer.yaml   # what this DAG reads
```

**Producer contract:**

```yaml
dag_id: simulation_daily
mode: daily
produces:
  - artifact_ref: api/src/airflow_project/data/gold/simulation/team_strength_ratings.parquet
    contract: "Per-team strength ratings (OFF/DEF/NET)."
    produced_by_stage: run_daily_sim
    freshness_sla_hours: 26
```

**Consumer contract:**

```yaml
dag_id: playoff_strategy_daily
requires:
  - artifact_ref: api/src/airflow_project/data/gold/simulation/team_strength_ratings.parquet
    producer_dag: simulation_daily
    stage_needed_at: ps0_team_profile
```

**Runtime check (pre-flight in consumer DAGs):**

```python
from _artifact_graph import check_required_artifacts, build_graph

def _preflight(**context):
    ctx = {"season": _current_season(), "year": str(_current_year())}
    missing = check_required_artifacts(
        "playoff_strategy_daily",
        repo_root=REPO_ROOT,
        ctx=ctx,
    )
    if missing:
        raise AirflowException(
            "Upstream artifacts missing:\n"
            + "\n".join(f"  - {m.artifact_ref} (from {m.producer_dag})"
                        for m in missing)
        )
```

**Parse-time validator** (`scripts/fleet/verify_artifact_graph.py`):

- Exits 0 if every consumer's `producer_dag` has a matching producer contract
- Exits 1 on orphan / cycle / schema violation
- Emits topological order for trigger-wave strategies (leaf producers first)
- Emits `blast_radius(dag_id) -> [downstream_consumers]` for email D3 section

**Rollout rules:**

1. **Every new DAG** ships with both `.producer.yaml` and `.consumer.yaml`
   from day one. Missing files = DAG parse fails in strict CI mode.
2. **Self-produced dependencies** (e.g. `xfg_pipeline` rebuild mode
   producing what daily mode consumes) are allowed — declare
   `producer_dag == consumer_dag`. The topological sort skips them.
3. **No defensive fallbacks.** If a required artifact is absent, the
   consumer DAG must raise with the exact `producer_dag` that owes it.
   No "try again tomorrow" retry logic.
4. **The graph is analytical-layer blind.** It only tracks filesystem /
   R2 / DuckDB table artifacts. No cross-references into dbt marts
   (those are implicit in `ref()` calls and dbt already validates).

**Verification before unpausing a DAG:**

```bash
python scripts/fleet/verify_artifact_graph.py
# [OK] N producer contracts, M consumer contracts
# [OK] K DAGs in dependency graph
# Topological order (producer-first):
#   <dag_id> -> [downstream consumers]
```

---

## 6. Step 5 -- Write the Orchestrator

The orchestrator is the main entry point that runs all pipeline stages in
order.

### 6.1 Stage Registry Pattern

Define stages as a list of dicts with script paths and dependencies:

```python
STAGES = [
    {
        "id": "S1",
        "name": "Build Silver",
        "script": "scripts/{pipeline_name}/stages/build_silver.py",
        "depends_on": [],
    },
    {
        "id": "S2",
        "name": "Promote to Gold",
        "script": "scripts/{pipeline_name}/stages/promote_gold.py",
        "depends_on": ["S1"],
    },
    {
        "id": "S3",
        "name": "Feature Engineering",
        "script": "scripts/{pipeline_name}/stages/build_features.py",
        "depends_on": ["S2"],
    },
    {
        "id": "V",
        "name": "Validate",
        "script": "scripts/{pipeline_name}/validation/validate_pipeline.py",
        "depends_on": ["S3"],
        "blocking": True,  # Fail-fast: stops pipeline on failure
    },
    {
        "id": "U",
        "name": "Upload to R2",
        "depends_on": ["V"],
        "type": "r2_upload",  # Special handling -- calls upload_data.sh
    },
]
```

### 6.2 Runner Pattern

```python
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[N]


def run_stage(stage: dict) -> bool:
    """Run a single pipeline stage. Returns True on success."""
    script = PROJECT_ROOT / stage["script"]
    print(f"\n{'='*60}")
    print(f"Stage {stage['id']}: {stage['name']}")
    print(f"{'='*60}")

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONPATH": ":".join([
            str(PROJECT_ROOT),
            str(PROJECT_ROOT / "api"),
            str(PROJECT_ROOT / "api" / "src"),
        ])},
        timeout=stage.get("timeout", 3600),
    )

    if result.returncode != 0:
        print(f"  [FAIL] Stage {stage['id']} failed (exit {result.returncode})")
        if stage.get("blocking", False):
            sys.exit(1)
        return False
    print(f"  [PASS] Stage {stage['id']} complete")
    return True


def run_pipeline(mode: str = "daily"):
    """Run all stages in dependency order."""
    completed = set()
    for stage in STAGES:
        deps = stage.get("depends_on", [])
        if not all(d in completed for d in deps):
            print(f"  [SKIP] {stage['id']}: dependency not met")
            continue
        if run_stage(stage):
            completed.add(stage["id"])
```

### 6.3 Modes

Every orchestrator should support at least these modes:

| Mode | Behavior |
|------|----------|
| `daily` | Standard incremental refresh |
| `rebuild` | Full historical rebuild from scratch |
| `validate` | Read-only validation (no data writes) |
| `stage` | Run specific stages by ID |

---

## 7. Step 6 -- Add the Airflow DAG

### 7.1 DAG File

Create `api/src/airflow_project/dags/{pipeline_name}_dag.py`:

```python
"""
Airflow DAG: {Pipeline Name} medallion pipeline.

Modes:
    daily    - standard refresh
    rebuild  - full historical rebuild
    stage    - run specific stages
"""

from __future__ import annotations

import logging
from pathlib import Path

from _base_three_mode_dag import build_three_mode_dag, parse_stages_param
from _dag_utils import run_script

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNNER = PROJECT_ROOT / "scripts" / "{pipeline_name}" / "run_pipeline.py"


def _run_pipeline(*, mode: str, **kwargs):
    """Build args and delegate to the runner script."""
    args = ["--mode", mode]
    for key, value in kwargs.items():
        if value is not None:
            args.extend([f"--{key.replace('_', '-')}", str(value)])
    return run_script(str(RUNNER), args=args, timeout=7200)


def run_daily(**context):
    params = context.get("params", {})
    _run_pipeline(mode="daily", **{k: v for k, v in params.items() if v})


def run_rebuild(**context):
    params = context.get("params", {})
    _run_pipeline(mode="rebuild", **{k: v for k, v in params.items() if v})


dag = build_three_mode_dag(
    dag_id="{pipeline_name}_pipeline",
    daily_callable=run_daily,
    rebuild_callable=run_rebuild,
    schedule="0 6 * * *",  # adjust as needed
    tags=["{pipeline_name}", "medallion"],
)
```

### 7.2 R2 Upload Task in DAGs

Every pipeline DAG that produces serving artifacts must include an
`upload_to_r2` task as its final step. Use the three-mode DAG factory's
built-in `upload_fn` parameter:

```python
def _upload_{pipeline_name}_to_r2(**context):
    """Upload pipeline artifacts to R2 after validation passes."""
    from _dag_utils import run_script
    flags = "--{pipeline_flag} --skip-core"
    run_script(
        str(PROJECT_ROOT / "scripts" / "upload_data.sh"),
        args=flags.split(),
        timeout=300,
    )

dag = build_three_mode_dag(
    dag_id="{pipeline_name}_pipeline",
    daily_callable=run_daily,
    rebuild_callable=run_rebuild,
    schedule="0 6 * * *",
    tags=["{pipeline_name}", "medallion"],
    upload_fn=_upload_{pipeline_name}_to_r2,  # Wired as final task
)
```

**`--skip-core` flag**: Per-pipeline DAGs use `--skip-core` to avoid
re-uploading `basketball.duckdb` (~51 MB). Only the `nba_value_pipeline` DAG
uploads the core DuckDB file (it uses `--gold-products` without `--skip-core`).

**Graceful skip**: When `AWS_ENDPOINT_URL` is not set (local dev), upload tasks
log a skip message and succeed. No R2 credentials required for local
development.

**Upload flags by pipeline type**:

| Pipeline Type | Upload Flags | What Gets Uploaded |
|--------------|-------------|-------------------|
| NBA Value | `--gold-products` | basketball.duckdb + manifest + 13 gold product parquets |
| Prospects | `--boards --skip-core` (daily); + `--models` (rebuild) | 8 big boards + RSF/LTR models |
| XFG | `--xfg --skip-core` (daily); + `--xfg-models` (rebuild) | XFG cache + 7 gold parquets + zone models |
| Referee | `--referees --skip-core` | 13 Hive-partitioned referee gold parquets |
| Predictions | `--predictions --skip-core` | GBDT + Bayesian champion artifacts |
| Simulation | `--sim-data --skip-core` (daily); + `--sim` (rebuild) | Silver dims + gold features + champion models |
| Lineup | `--lineup` | lineup_v3.duckdb |
| Sentiment | `--sentiment --skip-core` | Sentiment feature parquets |
| Draft Picks | `--draft-gold --skip-core` | Draft pick power parquets |

See [DATA_ENGINEERING_PIPELINE.md Section 19](engineering/DATA_ENGINEERING_PIPELINE.md#19-cloudflare-r2--artifact-promotion) for the complete R2 reference.

### 7.3 Conventions

- DAGs are thin wrappers -- all logic lives in the runner script
- Use `_dag_utils.run_script()` for subprocess execution
- Use `build_three_mode_dag()` for standard 3-mode DAGs
- The DAG file should be parseable without any data or pipeline state
- Every DAG producing serving artifacts must wire `upload_fn` for R2 promotion

### 7.4 Rich v2 Email Contract (required for every DAG)

Every DAG emits success/failure emails through the v2 renderer. The email
contains a module tree, a root-cause box (failure only), a run-summary table
(including GPU cost), and a fleet-health strip. Three wiring steps, no
exceptions:

**Step 1 — Declare stages at module top** (parse-time, no I/O):

```python
from _stage_registry import register_stages, task_stage_callbacks

register_stages("my_pipeline_daily", [
    ("stage_id_1", "Human label 1", "bronze"),
    ("stage_id_2", "Human label 2", "silver"),
    # ... medallion_layer is optional; omit or None for stages that don't map.
])
```

**Step 2 — Wire DAG-level rich callbacks**:

```python
from _email_alerts import dag_rich_success_alert, dag_rich_failure_alert

dag = DAG(
    "my_pipeline_daily",
    on_success_callback=dag_rich_success_alert,
    on_failure_callback=dag_rich_failure_alert,
    ...
)
```

**Step 3 — Wire per-task stage-mark callbacks** so each stage row in the
module tree reports `✅ / ❌` plus wall-clock duration:

```python
succ, fail = task_stage_callbacks("stage_id_1")
BashOperator(
    task_id="stage_id_1",
    on_success_callback=succ,
    on_failure_callback=fail,
    ...
)
```

**Step 4 (producers) — Push `artifact_summaries` XCom** so the run-summary
table populates with rows/bytes/min/max dates:

```python
ti.xcom_push(key="artifact_summaries", value={
    "path": "/path/to/output.parquet",
    "rows": 10006,
    "bytes_written": 284_231_987,
    "min_dates": {"GAME_DATE": "2025-10-21"},
    "max_dates": {"GAME_DATE": "2026-04-20"},
    "null_ratios": {"COL_A": 0.0, "COL_B": 0.02},
})
```

**Step 5 (GPU tasks only) — Push `gpu_run_summary` XCom** so the GPU row
renders. No fake numbers — CPU-only tasks omit this entirely and the table
shows "—".

```python
ti.xcom_push(key="gpu_run_summary", value={
    "provider": "local_cuda",  # or "runpod_h100", etc.
    "duration_s": 423.7,
    "cost_usd": 0.18,
})
```

**Anti-patterns (all §14 violations)**:

- Routing a non-ingest DAG through `ingest_dag_success_alert` — produces
  "INGEST FAIL" subject and inapplicable jobs-acked/deadletter fields.
- Omitting `register_stages(...)` — the email renders "no stage registry
  declared" banner instead of a module tree.
- Fabricating GPU fields for CPU-only tasks — leave them null; the renderer
  shows "—".

Reference implementations: `nba_value_pipeline_dag.py`,
`sentiment_pipeline_dag.py`.

---

## 8. Step 7 -- Write the Validation Suite

### 8.1 Validation Script Structure

Create `scripts/{pipeline_name}/validation/validate_pipeline.py`:

```python
"""
Pipeline Validation -- read-only health check for all stages.

Usage:
    PYTHONPATH=/workspace python scripts/{pipeline_name}/validation/validate_pipeline.py
    PYTHONPATH=/workspace python scripts/{pipeline_name}/validation/validate_pipeline.py --save-snapshot
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')
import functools
print = functools.partial(print, flush=True)

import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[N]
sys.path.insert(0, str(PROJECT_ROOT / "api" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "api"))
sys.path.insert(0, str(PROJECT_ROOT))

# ---- Stage Registry ----
DATA_ROOT = PROJECT_ROOT / "data" / "{pipeline_name}"

STAGES = [
    ("S1", "Silver Data",      DATA_ROOT / "silver" / "main.parquet",     "check_silver"),
    ("S2", "Gold Data",        DATA_ROOT / "gold" / "main.parquet",       "check_gold"),
    ("S3", "Features",         DATA_ROOT / "gold" / "features.parquet",   "check_features"),
]

stats = {"pass": 0, "fail": 0, "warn": 0, "missing": 0}


def log(level: str, msg: str) -> None:
    prefix = {"PASS": "  [PASS]", "FAIL": "  [FAIL]", "WARN": "  [WARN]"}
    print(f"{prefix.get(level, '  [????]')} {msg}")
    stats[level.lower()] += 1


def check_parquet(path: Path, label: str, check_fn: str) -> None:
    """Load a parquet and run the named check function."""
    if not path.exists():
        log("FAIL", f"{label}: file not found at {path}")
        stats["missing"] += 1
        return
    df = pd.read_parquet(path)
    log("PASS", f"{label}: {df.shape[0]:,} rows x {df.shape[1]} cols")
    # Call domain-specific check function
    globals()[check_fn](df, label)


def main():
    print(f"\n{'='*60}")
    print(f"Pipeline Validation: {pipeline_name}")
    print(f"{'='*60}\n")

    for stage_id, label, path, check_fn in STAGES:
        check_parquet(path, f"{stage_id} {label}", check_fn)

    total = stats["pass"] + stats["fail"]
    print(f"\nResult: {stats['pass']}/{total} PASS")
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

### 8.2 Validation Principles

1. **Read-only** -- validation never modifies data
2. **Data-descriptive** -- report what the data IS, not whether it meets
   arbitrary thresholds (the operator interprets results)
3. **Registry-based** -- stage list drives the check loop
4. **Exit code** -- return 0 on all-pass, 1 on any failure (for CI/DAG gating)
5. **Snapshot support** -- `--save-snapshot` saves stats for future comparison

### 8.3 Audit Script (for ML pipelines)

If the pipeline includes ML training, add a full audit script:

```python
# scripts/{pipeline_name}/audit/full_pipeline_audit.py
AUDIT_CHECKS = [
    ("data_freshness",     check_data_freshness),
    ("schema_compliance",  check_schema_compliance),
    ("leakage_prevention", check_forbidden_features),
    ("temporal_integrity", check_no_future_leakage),
    ("model_convergence",  check_model_diagnostics),
    ("backtest_metrics",   check_backtest_results),
]
```

### 8.4 Daily Pipeline Report (Session 366 Pattern)

Every pipeline needs a standardized daily report that runs after validation and is replaced atomically each day. This enables consistent monitoring across all pipelines and surfaces data quality issues early.

#### 8.4.1 Report Location

Reports are stored in `reports/{pipeline_name}/` with two files per day:

```
reports/{pipeline_name}/
    pipeline_report.json              ← latest (atomic overwrite each run)
    pipeline_report_20260303.json     ← 7-day archive (auto-cleaned)
    pipeline_report_20260302.json
    pipeline_report_20260301.json
    ...
```

This standardizes report paths across all pipelines (XFG, NBA Value, etc.) and makes it easy to consume reports downstream (e.g., dashboards, alerting systems).

#### 8.4.2 Report Contents

The report is machine-readable JSON with these sections:

```python
{
  "generated_at": "2026-03-03T12:13:28Z",
  "run_date": "2026-03-03",
  "pipeline_mode": "daily",              # daily | rebuild | backfill

  "freshness": {
    "age_hours": {
      "stage_1": 0.5,
      "stage_2": 1.2,
      ...
    },
    "stale_threshold_hours": 36.0,       # 1.5x schedule interval
    "stale_flags": {
      "stage_1": false,
      "stage_2": false,
    },
    "any_stale": false
  },

  "row_counts": {
    "stage_1": {
      "current": 12345,
      "prev": 12340,                     # from drift_log.json
      "delta": 5
    },
    ...
  },

  "nan_rates": {
    "stage_1": {
      "CRITICAL_COLUMN": {
        "rate": 0.05,
        "max_allowed": 0.15,             # regression detection threshold
        "status": "OK"
      },
      ...
    }
  },

  "signal_distribution": {
    "stage_1": {
      "SIGNAL_VALUE_A": 1234,
      "SIGNAL_VALUE_B": 567,
      "NULL": 89
    }
  },

  "data_gaps": {
    "missing_seasons": [],
    "team_count": 30,
    "team_count_ok": true,
    "players_with_no_signal": 0
  },

  "validation": {
    "status": "WARN",                    # FAIL | WARN | PASS
    "checks_passed": 33,
    "checks_warned": 16,
    "checks_failed": 0,
    "checks_total": 49
  },

  "drift_flags": [],                     # list of regression strings, or empty
  "overall_status": "WARN"               # FAIL | WARN | OK
}
```

#### 8.4.3 Implementation Pattern

Create `scripts/{pipeline_name}/validation/generate_daily_report.py`:

```python
"""
Generate daily pipeline health report.

Writes:
    reports/{pipeline_name}/pipeline_report.json          (latest, atomic)
    reports/{pipeline_name}/pipeline_report_{YYYYMMDD}.json  (7-day archive)

Usage:
    python scripts/{pipeline_name}/validation/generate_daily_report.py
    python scripts/{pipeline_name}/validation/generate_daily_report.py --mode rebuild
    python scripts/{pipeline_name}/validation/generate_daily_report.py --print
"""

import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, date, timedelta

PROJECT_ROOT = Path(__file__).resolve().parents[N]
REPORTS_DIR = PROJECT_ROOT / "reports" / "{pipeline_name}"
VALIDATE_SCRIPT = PROJECT_ROOT / "scripts" / "{pipeline_name}" / "validation" / "validate_pipeline.py"

ARCHIVE_RETAIN_DAYS = 7
STALE_THRESHOLD_HOURS = 1.5 * 24  # 36 hours

def _atomic_write_json(data: dict, path: Path) -> None:
    """Write JSON atomically: temp file in same dir -> rename. Never partial-writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
    try:
        import os
        os.close(tmp_fd)
        Path(tmp_path).write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        Path(tmp_path).rename(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

def _cleanup_old_archives(reports_dir: Path, run_date: date) -> list[str]:
    """Delete archive files older than ARCHIVE_RETAIN_DAYS."""
    cutoff = run_date - timedelta(days=ARCHIVE_RETAIN_DAYS)
    deleted = []
    for f in reports_dir.glob("pipeline_report_????????.json"):
        date_str = f.stem[-8:]  # "20260101"
        try:
            file_date = date.fromisoformat(f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}")
        except ValueError:
            continue
        if file_date < cutoff:
            f.unlink()
            deleted.append(f.name)
    return deleted

def build_report(mode: str) -> dict:
    """Assemble the full pipeline report."""
    # [Implementation: run validation, compute stats, detect drift]
    ...

def main():
    parser = argparse.ArgumentParser(description="Generate pipeline health report")
    parser.add_argument("--mode", default="daily", choices=["daily", "rebuild", "backfill"])
    parser.add_argument("--print", dest="print_report", action="store_true")
    args = parser.parse_args()

    report = build_report(mode=args.mode)
    run_date = date.fromisoformat(report["run_date"])
    date_str = run_date.strftime("%Y%m%d")

    latest_path = REPORTS_DIR / "pipeline_report.json"
    archive_path = REPORTS_DIR / f"pipeline_report_{date_str}.json"

    _atomic_write_json(report, latest_path)
    _atomic_write_json(report, archive_path)
    _cleanup_old_archives(REPORTS_DIR, run_date)

    if args.print_report:
        print(json.dumps(report, indent=2))

    # Non-zero exit if FAIL so Airflow/CI can alert
    if report["overall_status"] == "FAIL":
        sys.exit(1)
```

**Key principles:**
- **Atomic writes**: Never write partial JSON — use tempfile + rename
- **7-day archive**: Auto-clean files older than 7 days (don't grow unbounded)
- **Data-derived thresholds**: NaN rates calibrated to detect REGRESSIONS from known baseline, not arbitrary limits
- **Drift flags only on real changes**: Report NaN rates always, but only flag if exceeding calibrated threshold
- **Non-zero exit on FAIL**: Allows Airflow DAG gating and CI alerting

#### 8.4.4 Daily DAG Integration

Call the report generator from the DAG after validation:

```python
def validate_pipeline(**context):
    """Final validation: validate_pipeline.py + generate_daily_report.py + dbt refresh."""
    # Step 1: run validate_pipeline.py
    run_script(str(SCRIPTS_DIR / "{pipeline_name}" / "validation" / "validate_pipeline.py"), timeout=300)

    # Step 2: generate daily report
    run_script(str(SCRIPTS_DIR / "{pipeline_name}" / "validation" / "generate_daily_report.py"), timeout=120)

    # Step 3: refresh dbt (if applicable)
    if dbt_project_exists:
        _run_dbt_refresh()
```

This ensures every DAG run produces an observable, time-series JSON artifact that can be queried for trend analysis, alerting, and dashboarding.

---

## 8.5 Incremental Mode Pattern (for Daily Pipelines)

Daily pipeline runs should be fast, but freshness is not a global clock. Each
stage declares its own freshness SLA, event-date watermark, input artifact hash,
and output manifest contract. Skip a stage only when the current outputs exist,
their schema/checksum still matches the declared contract, and the data-derived
watermark covers the run's required period.

### 8.5.1 Stage-Level Incremental Check

Add a helper function to the orchestrator:

```python
def _is_stage_fresh(stage_name: str, as_of_date: date) -> bool:
    """Return True only when outputs satisfy the stage's declared freshness contract."""
    stage_def = next(s for s in STAGES if s["name"] == stage_name)

    freshness_sla_hours = stage_def["freshness_sla_hours"]
    required_through = stage_def["required_through"](as_of_date)

    for output_path in stage_def["outputs"]:
        if not output_path.exists():
            return False

        manifest = read_stage_manifest(output_path)
        if manifest["schema_hash"] != stage_def["schema_hash"]:
            return False
        if manifest["input_hash"] != compute_input_hash(stage_def["inputs"]):
            return False
        if manifest["max_event_date"] < required_through:
            return False

        age_h = (time.time() - manifest["written_at_epoch"]) / 3600
        if age_h >= freshness_sla_hours:
            return False

    return True
```

### 8.5.2 Incremental Flag Pattern

Add `--incremental` flags to expensive stages:

```python
def run_pipeline(mode: str = "daily"):
    """Run stages in order. Daily mode: skip-if-fresh."""
    for stage in STAGES:
        if mode == "daily" and _is_stage_fresh(stage["name"], as_of_date=RUN_DATE):
            print(f"  [SKIP] {stage['name']}: freshness contract satisfied")
            continue
        run_stage(stage)
```

For data-building stages with incremental capability:

```python
# In stage-specific scripts:
parser.add_argument("--incremental", action="store_true",
                    help="Append only new data (GAME_DATE > existing max)")
args = parser.parse_args()

if args.incremental and OUTPUT_PATH.exists():
    existing = pd.read_parquet(OUTPUT_PATH)
    cutoff = existing["GAME_DATE"].max()
    new_data = raw_data[raw_data["GAME_DATE"] > cutoff].copy()
    if len(new_data) == 0:
        print("  [OK] No new data since last run")
        sys.exit(0)
    combined = pd.concat([existing, new_data], ignore_index=True)
    combined = combined.drop_duplicates(subset=KEY_COLS, keep="last")
    combined.to_parquet(OUTPUT_PATH, index=False)
else:
    raw_data.to_parquet(OUTPUT_PATH, index=False)  # full rebuild
```

### 8.5.3 DAG Mode Handling

In the Airflow DAG, select the mode:

```python
def run_daily(**context):
    """Daily: incremental refresh (skip-if-fresh, append new rows)."""
    _run_stage_1(incremental=False)  # S1 always rebuilds (depends on fresh ingestion)
    _run_stage_2(incremental=True)   # S2 skips if fresh, appends new game rows
    _run_stage_3(incremental=True)   # S3 skips if fresh, recomputes season aggregates

def run_rebuild(**context):
    """Rebuild: full refresh from scratch."""
    _run_stage_1(incremental=False)
    _run_stage_2(incremental=False)
    _run_stage_3(incremental=False)
```

This keeps daily runs fast while allowing full rebuilds when the declared
freshness, schema, input-hash, or event-date contract is not satisfied.

### 8.5.4 Parallelism, Cache, and Artifact Layers

Use parallelism to shorten wall time, not to blur ownership boundaries.

| Lever | Standard |
|-------|----------|
| Stage fan-out | Split large "do everything" stages into narrow DAG tasks with clear inputs, outputs, and validation gates. A stage may fan out by league, date partition, target, or dbt tag only when every branch writes disjoint artifacts. |
| dbt selectors | `dbt build --select state:modified+ --threads N` is valid for local/staging development and targeted validation. Core R2 promotion still relies on `scripts/upload_data.sh`, which runs the full dbt build before publishing `basketball.duckdb`. |
| Airflow pools | Use pools to cap shared resources (`dbt`, extractors, DuckDB writers, GPU dispatch). Do not raise `parallelism`, `concurrency`, or `max_active_runs` to hide non-idempotent writers. |
| Cache reuse | Persist heavy bronze/silver/gold checkpoints with manifests containing row counts, schema hash, input hash, min/max event date, partition count, and producer version. Reuse the cache only if the manifest validates. |
| Checksum gates | Bronze -> silver -> gold -> product promotion must compare row counts/checksums/schema at the same grain. Rate gates compare rates to rates; count gates compare counts to counts. |
| R2 writes | All artifact promotion still goes through `scripts/upload_data.sh`. Parallel stage execution ends before the single-writer R2 promotion step starts. |

### 8.5.5 dbt Selector vs Core Upload Safety Gate

dbt selectors (`--select state:modified+`, `--select tag:foo+`, etc.) are
**fast** but **unsafe** for core uploads. They build only what you asked for;
everything else in `basketball.duckdb` retains its previous build state. If
you then upload that DuckDB to R2, you ship a database where some marts are
fresh and others are silently stale relative to their declared inputs.

The rule is simple but easy to violate under time pressure:

| Scenario | dbt selector OK? | Why |
|----------|------------------|-----|
| Local development, validating one mart | YES (`--select my_mart+`) | You're not uploading; speed matters |
| CI / staging validation, single domain | YES (`--select tag:my_pipeline+`) | Validates your domain in isolation |
| Per-pipeline R2 upload with `--skip-core` | YES, IF the upload only touches parquets (not DuckDB) | The DuckDB on R2 is untouched, so internal staleness is irrelevant |
| **Core R2 upload (`upload_data.sh` without `--skip-core`)** | **NO — full `dbt build` mandatory** | The DuckDB you publish is consumed by 9 domains; a partial build leaves N-1 of them stale |
| Hotfix to a single mart that you also want in R2 today | NO — full build, then upload | If you only built one mart, the others are at yesterday's state and you do not know whether yesterday's state is consistent with today's upstream parquets |

**Pre-upload checklist whenever DuckDB hits R2:**

```bash
# 1. Verify your last dbt invocation was a FULL build (no --select)
grep -E "dbt (build|run)" logs/dbt_last_run.log | tail -3
# If you see --select, --models, --tag in the last invocation, STOP.
# Re-run as: cd api/de/basketball && dbt build --profiles-dir .

# 2. Verify all 9 domains' marts are present and recent
python -c "
import duckdb, json
con = duckdb.connect('api/de/basketball/basketball.duckdb', read_only=True)
domains = ['nba_value', 'prospects', 'simulation', 'sentiment', 'news',
           'xfg', 'referees', 'draft_pick_power', 'franchise_scorecard']
for d in domains:
    rows = con.sql(f\"SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'mart_{d}_%'\").fetchone()[0]
    print(f'{d}: {rows} marts')
    if rows == 0:
        raise SystemExit(f'FAIL: {d} has no marts — full dbt build was skipped')
"

# 3. Now upload
bash scripts/upload_data.sh
```

**Anti-pattern catalog (do not do these):**

- `dbt build --select state:modified+` followed by `upload_data.sh` (no
  `--skip-core`). Builds only what changed, ships a DuckDB where the other
  domains' marts may be stale or built from a different upstream version.
- `dbt run --select my_mart` (no tests) followed by `upload_data.sh
  --skip-core --my-domain`. Skipped tests means you uploaded an unvalidated
  mart. Always `dbt build` (which runs tests), never `dbt run` alone, before
  any upload.
- Calling `dbt build --select tag:foo` from a DAG and then having the same
  DAG call `upload_data.sh` (no `--skip-core`). The DAG's selector built
  one tag's worth of marts; the upload script then re-runs full dbt before
  publishing — but you've burned compute for nothing AND you've confused
  the next operator who reads the DAG and assumes the selector was the
  effective build.

> **Summary**: if `basketball.duckdb` is going to R2, the build that
> produced it must be a full `dbt build` with no selectors. `upload_data.sh`
> enforces this by running its own full build, but the explicit pre-flight
> check protects against operators who run dbt manually then call
> `upload_data.sh` thinking it will "just use what I built."

### 8.5.6 Incremental Run Audit Checklist

Incremental runs are faster than full rebuilds, but "faster" is also the
shape of a bug — a stage that silently skips work because of a stale
manifest, a missed input partition, or a wrong watermark looks identical to
a stage that legitimately had nothing new to do. Every incremental run
must clear this audit before its outputs are trusted downstream.

**The five questions every incremental run must answer:**

| Question | How to answer | Failure mode if skipped |
|----------|---------------|-------------------------|
| 1. Did total row count grow monotonically? | Compare `len(output)` to the previous run's row count from the manifest. New rows >= 0 always. | An incremental that *shrinks* the output dropped historical data. |
| 2. Did the schema hash stay the same? | `sha256(sorted(df.dtypes.astype(str).items()))` vs `manifest['schema_hash']`. | A schema drift means downstream readers will silently misinterpret columns. |
| 3. Did the temporal coverage extend forward? | `df['{event_date_col}'].max()` should be >= previous run's max. Strictly greater for live pipelines. | An incremental that does not advance the watermark didn't actually consume new upstream data. |
| 4. Did the input hash change since the last run? | `sha256(sorted(input_paths + their_mtimes))` vs `manifest['input_hash']`. | If unchanged, the run was a no-op and should have skipped at the freshness gate, not produced a "new" output. |
| 5. Are there gaps in the temporal coverage? | `df.groupby('{date_col}').size()` — verify no missing dates between min and max for daily-grained pipelines. | A skip-by-mistake leaves holes that joins downstream silently treat as "no game that day." |

**Reference implementation** (run after any incremental stage):

```python
def audit_incremental_output(
    new_path: Path,
    prev_manifest: dict,
    event_date_col: str,
    expect_strict_growth: bool = True,
) -> dict:
    """Return audit report; raise if any blocking check fails."""
    df = pd.read_parquet(new_path)

    # Q1: monotonic row count
    new_rows = len(df)
    prev_rows = prev_manifest.get("row_count", 0)
    if new_rows < prev_rows:
        raise ValueError(
            f"Incremental shrank: {prev_rows} -> {new_rows} rows. "
            f"Stage dropped historical data."
        )

    # Q2: schema hash unchanged
    new_schema_hash = _hash_schema(df)
    if new_schema_hash != prev_manifest["schema_hash"]:
        raise ValueError(
            f"Schema changed during incremental run: "
            f"{prev_manifest['schema_hash']} -> {new_schema_hash}. "
            f"Incremental cannot mutate schema; do a full rebuild instead."
        )

    # Q3: temporal coverage extended
    new_max = df[event_date_col].max()
    prev_max = pd.Timestamp(prev_manifest["max_event_date"])
    if expect_strict_growth and new_max <= prev_max:
        raise ValueError(
            f"Watermark did not advance: prev={prev_max}, new={new_max}. "
            f"Incremental was a no-op but produced output."
        )

    # Q4: input hash differs (sanity check that we actually consumed new data)
    new_input_hash = compute_input_hash(STAGE_INPUTS)
    if new_input_hash == prev_manifest["input_hash"]:
        raise ValueError(
            f"Input hash unchanged but stage ran: input_hash={new_input_hash}. "
            f"Freshness gate should have skipped this run."
        )

    # Q5: no gaps in date range (daily-grained pipelines)
    if expect_strict_growth:
        unique_dates = pd.date_range(df[event_date_col].min(), new_max, freq="D")
        missing = sorted(set(unique_dates) - set(df[event_date_col].unique()))
        if missing:
            raise ValueError(
                f"Temporal gaps in incremental output: {missing[:5]}... "
                f"({len(missing)} total). Backfill or rebuild required."
            )

    return {
        "rows_added": new_rows - prev_rows,
        "watermark_advanced": (new_max - prev_max).days,
        "schema_stable": True,
        "input_changed": True,
    }
```

**Operational rules:**

- Every incremental stage **must** persist a manifest with at minimum:
  `row_count`, `schema_hash`, `max_event_date`, `min_event_date`,
  `input_hash`, `producer_version`, `written_at_epoch`.
- Run `audit_incremental_output` immediately after the stage produces its
  parquet, **before** any downstream stage consumes it. Audit failure halts
  the pipeline.
- A stage that legitimately had zero new rows should `sys.exit(0)` at the
  freshness gate (see §8.5.1) and **not** produce a "new" output. If a
  stage produces output, that output must reflect new work.
- For pipelines where strict growth is not expected (e.g., backfill mode,
  re-statement of historical aggregates), pass `expect_strict_growth=False`
  and document why in the spec doc.

---

## 8.6 Daily vs Event-Driven Refresh

Every pipeline must declare which operations run on which cadence:

| Cadence | Trigger | Appropriate for |
|---------|---------|----------------|
| **Daily** | Airflow schedule | Medallion stages 1-4, validate, health report, API smoke check |
| **Weekly / event-driven** | Parent artifact staleness check | Secondary bridge / model refresh |
| **Monthly (1st)** | Auto-detected by three-mode DAG factory | Full rebuild + control limit bootstrap |
| **Manual** | Engineer via Airflow UI | Rate-limited upstream fetches, schema migrations, backfill |

**Rules**:
- Never automate rate-limited upstream fetches. Never run a full rebuild on the daily schedule.
- Each pipeline declares its cadence in its DAG docstring and in the deployment doc DAG table.
- Staleness-gated jobs that skip are **not failures** — return `{"skipped": True}`.

---

## 8.7 Fail-Fast Gate Chain Contract

Each pipeline defines its blocking chain:

```
Bronze FAIL  ->  Silver / Gold / dbt / publish BLOCKED
Silver FAIL  ->  Gold / dbt / publish BLOCKED
Gold FAIL    ->  dbt / publish BLOCKED
```

On any failure:
- **Always write** validation artifacts — never block artifact writing on upstream failure.
- **Snapshot LKG** before Stage 3+ Gold writes (see Section 8.8 below).
- **Surface the failing gate** in the Airflow exception: stage number, gate name, measured value.
- **Log warning, not failure** for API smoke checks — pipeline success is independent of serving state.

In `validate_fn()`:

```python
def validate_my_pipeline(**_context):
    try:
        run_script(str(RUNNER), args=["--mode", "validate"], timeout=600)
    except RuntimeError:
        if _VALIDATION_PATH.exists():
            payload = json.loads(_VALIDATION_PATH.read_text(encoding="utf-8"))
            for stage in payload.get("stages", []):
                if stage.get("status") == "failed":
                    failed_gates = {
                        k: v for k, v in stage.get("gates", {}).items() if not v
                    }
                    raise AirflowException(
                        f"Stage {stage['stage']} [{stage['name']}] FAILED. "
                        f"Failed gates: {failed_gates}. "
                        f"Metrics: {stage.get('metrics', {})}."
                    )
            raise AirflowException(
                f"overall_status={payload.get('overall_status')} -- "
                f"check {_VALIDATION_PATH}"
            )
        raise
    return {"validation": "passed"}
```

---

## 8.8 Last-Known-Good (LKG) Snapshot Before Gold Writes

Before any Stage 3+ Gold output is written, snapshot the current Gold files so a failed run
can be diagnosed (or manually rolled back) without loss of the last healthy state:

```python
def _snapshot_last_known_good(self) -> dict:
    """Copy current Gold outputs to _last_known_good/ before Stage 3 overwrites them."""
    import shutil
    from datetime import datetime, UTC

    gold_files = [
        "output_a.parquet",
        "output_b.parquet",
    ]
    lkg_dir = self.cfg.project_root / "cache" / "_last_known_good" / "my_pipeline"
    lkg_dir.mkdir(parents=True, exist_ok=True)
    snapshotted: list[str] = []
    for name in gold_files:
        src = self.cfg.gold_root / name
        if src.exists():
            shutil.copy2(src, lkg_dir / name)
            snapshotted.append(name)
    ts = datetime.now(UTC).isoformat()
    (lkg_dir / "snapshot_ts.txt").write_text(ts, encoding="utf-8")
    return {"snapshot_ts": ts, "files": snapshotted, "available": bool(snapshotted)}
```

**Constraints**: No `try/except` — disk-full errors surface as real failures. `shutil` is stdlib. Log the
snapshot result and include it in the validation artifact under `"last_known_good"`.

---

## 8.9 Secondary (Bridge / Model Refresh) DAG Pattern

For pipelines that produce outputs depending on another pipeline's Gold:

1. **Separate DAG**: `dag_id="{pipeline}_bridge_dag"`, separate schedule (weekly typical).
2. **Staleness gate** in `run_daily()`: compare `BRIDGE_OUTPUT.stat().st_mtime` vs parent artifact mtimes.
3. If bridge is current -> log and return `{"skipped": True}` (NOT a failure).
4. If stale -> run bridge script -> validate -> publish only on PASS.
5. `validate_fn()` reads bridge validation JSON and checks all gates explicitly.

```python
_BRIDGE_OUTPUT = GOLD_DIR / "bridge_output.parquet"
_PARENT_ARTIFACTS = [
    GOLD_DIR / "upstream_a.parquet",
    CACHE_DIR / "upstream_b.parquet",
]

def _bridge_is_current() -> bool:
    if not _BRIDGE_OUTPUT.exists():
        return False
    bridge_mtime = _BRIDGE_OUTPUT.stat().st_mtime
    for parent in _PARENT_ARTIFACTS:
        if not parent.exists():
            logger.warning("Parent artifact missing -- treating bridge as stale: %s", parent)
            return False
        if parent.stat().st_mtime > bridge_mtime:
            return False
    return True

def run_daily(**context) -> dict:
    if _bridge_is_current():
        logger.info("Bridge current -- skipping.")
        return {"mode": "daily", "skipped": True}
    _run_bridge(context.get("params", {}).get("snapshot_date"))
    return {"mode": "daily", "skipped": False}
```

**Anti-pattern**: Running the bridge unconditionally on every daily run.

---

## 8.10 API Refresh After Pipeline Completion

After a successful pipeline run, confirm the API sees the new data:

1. **POST `/admin/reload`** (or pipeline-specific equivalent) — signals artifact refresh; clears any
   module-level cached state if present.
2. **GET `/health`** smoke check — confirms DuckDB/parquet reads return fresh timestamps.
3. Both calls are **non-blocking** (log warning on failure, do not fail the pipeline task).
4. Add to `run_daily()` and `run_rebuild()` after `_run_health_report()`.

```python
def _run_api_reload() -> None:
    import urllib.request
    req = urllib.request.Request(
        f"{_BACKEND_URL}/my-pipeline/admin/reload",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=b"{}",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        logger.info("API reload confirmed: %s", body)
    except Exception as exc:
        logger.warning("API reload failed (non-blocking): %s", exc)


def _run_api_smoke_check() -> None:
    import urllib.request
    try:
        with urllib.request.urlopen(
            f"{_BACKEND_URL}/my-pipeline/health", timeout=30
        ) as resp:
            body = json.loads(resp.read())
        status = body.get("status", "unknown")
        if status in ("healthy", "ok"):
            logger.info("API smoke check passed (status=%s)", status)
        else:
            logger.warning("API smoke check returned status=%s: %s", status, body)
    except Exception as exc:
        logger.warning("API smoke check failed (non-blocking): %s", exc)
```

For endpoints that load data at module import time (startup), either:
- Move the read inside the route handler (per-request, preferred for small files < 1 MB).
- Or expose a reload endpoint that re-reads the file into the module-level variable.

DuckDB mart queries and parquet reads are inherently per-request — no reload needed.

---

## 8.6 Shared-Volume Write Hygiene (Atomic Writes)

Every artifact written to a **bind-mounted shared volume** (the `data/` and `cache/`
trees, dbt `target/`, gold products) is read AND written by more than one container.
The `datascience` container runs as `root` (uid 0); `airflow-scheduler`/`worker` run as
`astro` (uid 50000). A direct in-place write —
`df.to_parquet(path)` / `json.dump(open(path,'w'))` — opens the existing file
`O_WRONLY|O_TRUNC`, which **requires write permission on the existing file**. When the
last writer was the *other* user (e.g. a root-owned 644 leftover), the next scheduled DAG
run dies with `[Errno 13] Permission denied` — even when the
[DATA_ENGINEERING_PIPELINE.md §0.9](engineering/DATA_ENGINEERING_PIPELINE.md) ownership/
setgid/umask contract is in force, because that contract governs *new* files, not a stale
one already on disk.

**The standard:** producers MUST publish shared artifacts **atomically** — write to a
sibling temp file, then `os.replace()` it into the directory. `os.replace` needs write
permission only on the **directory** (group-writable per §0.9), not on the existing
target, so the prior file's owner is irrelevant. Set the temp file group-writable before
the replace so the published file lands `astro:astro 664` regardless of producer.

- **Parquet:** reuse `api/src/ml/io/atomic_io.py::write_parquet_atomic(df, path, **kwargs)`
  (re-exported by `scripts/xfg/_atomic_io.py`). Never call `df.to_parquet(path)` directly
  on a shared-volume target.
- **JSON / text:** tempfile + `os.replace` (already mandated for daily reports in §8.4).
- This is the atomic-publish pattern, **not** a `chmod 777` shortcut (which §0.9 forbids).
  It is complementary to — not a replacement for — the §0.9 ownership contract: keep both.
- Precedent: `player_game_predictions_pipeline` (2026-05-30) failed its daily gold refresh
  because a root-owned `silver/nba/dims/game_dim.parquet` blocked the astro scheduler;
  routing the dim builders through `write_parquet_atomic` fixed it durably.

When auditing a producer for this standard: `grep -rn "\.to_parquet(" <pipeline scripts>` —
any write to a `data/`/`cache/`/gold path that is not `write_parquet_atomic` is a candidate
cross-container hazard.

---

## 9. Step 8 -- Wire API Endpoints

Full serving standards are defined in
[UNIFIED_SERVING_GUIDE.md](modeling/UNIFIED_SERVING_GUIDE.md). This section
summarizes the mandatory patterns every pipeline endpoint must follow.

### 9.1 Create the Router

Create `api/app/routers/{pipeline_name}_endpoints.py`:

```python
"""
{Pipeline Name} API endpoints.

Serves pre-computed pipeline outputs from DuckDB marts or gold parquets.
All handlers are sync (def) -- FastAPI runs them in a thread pool.
"""

from typing import Optional
from collections.abc import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.app.services.analytics_db import (
    get_analytics_db,
    serialize_dataframe_records,
)

router = APIRouter(
    prefix="/api/v1/{pipeline_name}",
    tags=["{pipeline_name}"],
)


# ---- Response Models (Pydantic, always required) ----

class EntityRow(BaseModel):
    entity_id: str = Field(..., description="Primary identifier")
    metric_a: float = Field(..., description="Description of metric A")
    metric_b: Optional[float] = Field(None, description="Nullable -- NaN maps to null")

    model_config = {"json_schema_extra": {"examples": [{"entity_id": "12345", "metric_a": 0.85, "metric_b": None}]}}


class MartResponse(BaseModel):
    rows: list[dict] = Field(..., description="Mart rows as dicts")
    count: int = Field(..., description="Row count")


# ---- Endpoints ----

@router.get("/status")
def pipeline_status():
    """Return pipeline health and data freshness."""
    ...


@router.get("/data/{entity_id}", response_model=EntityRow)
def get_entity(entity_id: str) -> EntityRow:
    """Return data for a specific entity."""
    con = get_analytics_db()
    rows = con.execute(
        "SELECT * FROM main_marts.mart_{pipeline_name} WHERE ENTITY_ID = ?",
        [entity_id],
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
    cols = [d[0] for d in con.execute("DESCRIBE main_marts.mart_{pipeline_name}").fetchall()]
    return EntityRow(**dict(zip(cols, rows[0])))


@router.get("/data", response_model=MartResponse)
def list_entities(season: Optional[str] = Query(None)) -> MartResponse:
    """Return all entities, optionally filtered by season."""
    con = get_analytics_db()
    sql = "SELECT * FROM main_marts.mart_{pipeline_name}"
    params = []
    if season:
        sql += " WHERE SEASON_ID = ?"
        params.append(season)
    rows = con.execute(sql, params).fetchall()
    cols = [d[0] for d in con.description]
    return MartResponse(
        rows=serialize_dataframe_records([dict(zip(cols, r)) for r in rows]),
        count=len(rows),
    )
```

### 9.2 Register in Main App

In `api/app/main.py`, add the router:

```python
from api.app.routers import {pipeline_name}_endpoints

app.include_router({pipeline_name}_endpoints.router)
```

### 9.3 Middleware Stack

All endpoints automatically get the middleware stack defined in
[UNIFIED_SERVING_GUIDE.md](modeling/UNIFIED_SERVING_GUIDE.md):

1. `RequestIDMiddleware` -- UUID per request
2. `PrometheusMiddleware` -- latency and status metrics
3. `PredictionLogger` -- JSONL logging for prediction endpoints
4. `ConcurrencyLimiter` -- max 4 concurrent heavy requests
5. `CORSMiddleware` -- environment-specific CORS
6. `X-Process-Time` -- response time header
7. `FastAPILimiter` -- Redis-backed rate limiting

No per-pipeline middleware config needed. The stack applies to all routers
automatically via pure ASGI composition.

### 9.4 Handler Type Rules

**Rule: `def` (sync) for I/O-bound work. `async def` ONLY for genuine async.**

FastAPI runs `def` handlers in a thread pool executor -- they never block the
event loop. This is the correct pattern for DuckDB queries, parquet reads,
and model inference.

```python
# CORRECT -- sync handler, runs in thread pool:
@router.get("/data")
def get_data():
    df = pd.read_parquet(path)       # blocking I/O -- safe in thread pool
    return ...

# CORRECT -- async handler for genuine async I/O:
@router.get("/external")
async def get_external():
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://...")  # genuinely async
    return ...

# WRONG -- blocks the event loop:
@router.get("/data")
async def get_data():
    df = pd.read_parquet(path)       # blocking call in async context!
    con = duckdb.connect()           # also blocking!
    return ...
```

### 9.5 Response Model Rules

**Rule: ALL endpoints must declare Pydantic `response_model`.**

FastAPI 0.130+ activates Pydantic Rust JSON serialization for typed endpoints
-- ~2x speedup. Raw `dict` returns bypass this entirely.

| Rule | Example |
|------|---------|
| Always declare `response_model=` | `@router.get("/data", response_model=EntityRow)` |
| `Optional[float]` for nullable numerics | NaN -> `null` in JSON. NEVER `.fillna(0)` |
| Raw `list[dict]` payloads must be normalized | Use `serialize_dataframe_records(...)` before return so `NaN`/`pd.NA`/`NaT` become `null` |
| `Field(description=...)` on every field | Required for OpenAPI docs |
| `model_config` with examples | Helps frontend devs and LLM agents |
| No raw `dict` returns | Bypasses Rust speedup and type safety |
| No model weights or internal paths | Only publicly-derivable data in responses |

### 9.6 DuckDB Query Standards

**Rule: Parameterized queries only. Never f-string interpolation.**

DuckDB pushes predicates into columnar scans. Always use for filtered reads
-- never load full parquets into pandas for filtering.

```python
# CORRECT -- parameterized, predicate pushdown:
rows = con.execute(
    "SELECT * FROM read_parquet(?) WHERE SEASON_ID = ? AND SIGNAL = ?",
    [str(path), season_id, signal],
).fetchall()

# WRONG -- SQL injection risk:
sql = f"SELECT * FROM read_parquet('{path}') WHERE TEAM = '{team}'"
```

**Large result sets -- cursor with `fetchmany()`:**

```python
_STREAM_BATCH_SIZE = 500

cursor = con.execute("SELECT ... WHERE ...", [path])
cols = [d[0] for d in cursor.description]
while batch := cursor.fetchmany(_STREAM_BATCH_SIZE):
    for row in batch:
        yield MyModel(**dict(zip(cols, row)))
```

### 9.7 Error Code Standards

No defensive fallbacks. Missing data is an error, not an empty response.

| Condition | HTTP Code | Pattern |
|-----------|-----------|---------|
| Entity not found | `404` | `raise HTTPException(404, detail=...)` |
| Model/artifact not loaded | `503` | `raise HTTPException(503, detail=...)` |
| Invalid input | `422` | FastAPI auto-validates via Pydantic |
| Policy-gated feature | `403` | `raise HTTPException(403, detail=...)` |

**Anti-patterns (NEVER):**

```python
# WRONG -- returns empty 200, hides data issues:
@router.get("/data")
def get_data():
    rows = con.execute(...).fetchall()
    return {"rows": rows}  # empty list if no data -- silent failure

# WRONG -- swallows errors:
@router.get("/data")
def get_data():
    try:
        ...
    except Exception:
        return {}  # plausible-looking wrong response

# CORRECT -- missing data is 404:
@router.get("/data/{entity_id}")
def get_data(entity_id: str):
    rows = con.execute("SELECT * FROM mart WHERE ID = ?", [entity_id]).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for {entity_id}")
    return ...
```

### 9.8 Streaming NDJSON (for Large Result Sets)

For endpoints returning >500 rows, add a streaming variant using
`Iterable[Model]`. FastAPI 0.134+ natively streams these as NDJSON.

```python
@router.get("/data/stream")
def stream_data(season: Optional[str] = Query(None)) -> Iterable[EntityRow]:
    """Stream all rows as NDJSON (Content-Type: application/x-ndjson)."""
    con = get_analytics_db()
    cursor = con.execute(
        "SELECT * FROM main_marts.mart_{pipeline_name} WHERE SEASON_ID = ?",
        [season],
    )
    cols = [d[0] for d in cursor.description]
    first_batch = cursor.fetchmany(500)
    if not first_batch:
        raise HTTPException(status_code=404, detail=f"No data for season={season}")
    for row in first_batch:
        yield EntityRow(**dict(zip(cols, row)))
    while batch := cursor.fetchmany(500):
        for row in batch:
            yield EntityRow(**dict(zip(cols, row)))
```

**When to use each response pattern:**

| Pattern | When | Content-Type |
|---------|------|--------------|
| Standard JSON | <500 rows, single records | `application/json` |
| Streaming NDJSON | >500 rows, progressive rendering | `application/x-ndjson` |
| SSE | Real-time push (live game events) | `text/event-stream` |

### 9.9 Thread-Safe Module-Level Caching

Sync handlers run concurrently in the thread pool. Any module-level cache
(dict, list, TTL cache) must be protected with `threading.Lock`.

```python
import threading
import time

_cache: dict[str, tuple[float, list]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL_S = 300  # 5 minutes


def _get_cached(key: str) -> list | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry[0]) < _CACHE_TTL_S:
            return entry[1]
    return None


def _set_cached(key: str, data: list) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), data)
```

**Rules:**
- Lock scope covers both read and write as an atomic unit
- Error states are NOT cached -- exceptions propagate naturally
- Thread pool sizing: Starlette default `min(32, cpu_count + 4)` workers
- ConcurrencyLimiter (max 4 heavy) prevents pool exhaustion

### 9.10 Serving ML Model Predictions

If the pipeline includes trained models, use the unified serving pattern:

```python
from api.src.ml.modeling.gddt.serving.predictor import GBDTPredictor

predictor = GBDTPredictor.load_champion("TARGET_NAME")
result = predictor.predict(input_data, check_drift=True)
# result.predictions, result.intervals, result.drift_flags
```

**Champion-challenger pattern**: New models must beat the existing champion
on the promotion metric before being promoted. Version history is preserved
for rollback. Dual-save to training dir + serving dir ensures consistency.
See [UNIFIED_SERVING_GUIDE.md Section 7](modeling/UNIFIED_SERVING_GUIDE.md).

**Drift detection**: `check_drift=True` flags features with z-score > 2.0
relative to training distribution. Pipeline-level PSI monitoring triggers
retrain at PSI > 0.25. See [UNIFIED_SERVING_GUIDE.md Section 9](modeling/UNIFIED_SERVING_GUIDE.md).

**Artifact integrity**: Every champion load verifies SHA256 checksums from
`metadata.json`. On mismatch: `RuntimeError` -- the model is NOT served.
See [UNIFIED_SERVING_GUIDE.md Section 5](modeling/UNIFIED_SERVING_GUIDE.md).

### 9.11 New Endpoint Development Checklist

Before merging any new endpoint, verify ALL items:

**Handler type:**
- [ ] I/O-bound handler is `def` (sync), NOT `async def`
- [ ] If `async def`, all awaited calls are genuinely async (httpx, Redis)
- [ ] No `pd.read_parquet()` or `duckdb.execute()` inside `async def`

**Response model:**
- [ ] `response_model=PydanticModel` declared on every endpoint
- [ ] No raw `dict` returns (bypasses Pydantic Rust speedup)
- [ ] Nullable numerics typed `Optional[float]` (NaN -> null, NOT `.fillna(0)`)
- [ ] All fields have `Field(description=...)` annotation
- [ ] `model_config` with realistic example values

**Data safety:**
- [ ] Response contains only publicly-derivable data
- [ ] No model weights, calibration params, internal paths exposed
- [ ] SQL queries parameterized -- no f-string interpolation

**Error codes (no defensive fallbacks):**
- [ ] Missing data -> `404` (not empty 200)
- [ ] Model/artifact not loaded -> `503` (not silent empty response)
- [ ] No `except: pass` or `except Exception: return {}`

**Streaming decision:**
- [ ] >500 rows -> streaming variant added (`Iterable[T]`)
- [ ] Streaming endpoint raises `404` before first yield if data missing

**Auth & monitoring:**
- [ ] Heavy endpoint added to `heavy_endpoints` set in `concurrency.py`
- [ ] Prediction endpoint URL added to `PredictionLogger` matching set

---

## 10. Step 9 -- Add dbt Models

### 10.1 Three-Layer dbt Architecture

```
api/src/airflow_project/dbt_project/
    models/
        staging/           # 1:1 passthrough from parquet to views
            stg_{pipeline_name}_{entity}.sql
        intermediate/      # Business logic joins
            int_{pipeline_name}_{joined_entity}.sql
        marts/             # Materialized tables (frontend-ready)
            mart_{pipeline_name}_{product}.sql
```

### 10.2 Staging Model (View)

```sql
-- models/staging/stg_{pipeline_name}_{entity}.sql
{{ config(materialized='view') }}

SELECT *
FROM read_parquet('{{ var("gold_path") }}/data/{pipeline_name}/{entity}.parquet')
```

### 10.3 Intermediate Model (View)

```sql
-- models/intermediate/int_{pipeline_name}_{product}.sql
{{ config(materialized='view') }}

SELECT
    a.ENTITY_ID,
    a.METRIC_1,
    b.METRIC_2,
    a.METRIC_1 / NULLIF(b.METRIC_2, 0) AS DERIVED_RATIO
FROM {{ ref('stg_{pipeline_name}_entity_a') }} a
LEFT JOIN {{ ref('stg_{pipeline_name}_entity_b') }} b
    ON a.ENTITY_ID = b.ENTITY_ID
    AND a.SEASON_ID = b.SEASON_ID
```

### 10.4 Mart Model (Materialized Table)

```sql
-- models/marts/mart_{pipeline_name}_{product}.sql
{{ config(materialized='table') }}

SELECT *
FROM {{ ref('int_{pipeline_name}_{product}') }}
WHERE SEASON_ID >= '2020-21'
```

### 10.5 dbt Tests

```yaml
# models/staging/schema.yml
models:
  - name: stg_{pipeline_name}_{entity}
    columns:
      - name: ENTITY_ID
        tests:
          - not_null
          - unique
      - name: SEASON_ID
        tests:
          - not_null
```

### 10.6 Cross-Pipeline Joins

Cross-pipeline joins happen **only** in the mart layer:

```sql
-- models/marts/mart_combined_analysis.sql
{{ config(materialized='table') }}

SELECT
    p.PLAYER_NAME,
    p.PROSPECT_SCORE,
    v.FAIR_MARKET_VALUE
FROM {{ ref('mart_prospects_big_board') }} p
LEFT JOIN {{ ref('mart_nba_value_season') }} v
    ON p.NBA_PLAYER_ID = v.PLAYER_ID
    AND p.SEASON_ID = v.SEASON_ID
```

**Rule:** Never join across pipelines using PLAYER_NAME -- use
`SOURCE_PLAYER_ID` -> `CANONICAL_PLAYER_ID` lookup tables.

#### 10.6.1 Cross-Pipeline Join Safety Gate (Required for every cross-pipeline mart)

Cross-pipeline marts are the only place pipelines touch each other's data.
That makes them the highest-leverage place to introduce silent bugs: a stale
upstream, a missed join key, or a temporal mismatch produces a mart that
*looks* sensible but encodes a bias that propagates everywhere downstream.
Every cross-pipeline mart must pass this gate before it ships.

**Gate 1 — Join only on canonical IDs.**

| Allowed join key | Why | Forbidden join key | Why |
|------------------|-----|--------------------|-----|
| `CANONICAL_PLAYER_ID` | Single registry-managed ID across all pipelines | `PLAYER_NAME` | Name collisions create cartesian products (e.g., 565 NCAA name collisions documented in MEMORY.md) |
| `NBA_PLAYER_ID` (for NBA-only joins) | Authoritative NBA Stats API ID | `SOURCE_PLAYER_ID` (cross-prefix) | Prefix mismatches (`ncaa_mbb:123` vs `nba:1629029`) silently drop rows |
| `TEAM_ID` (NBA Stats API) | 30-team set, stable | `TEAM_ABBR` / `TEAM_NAME` | BRK vs BKN, "LA Clippers" vs "Los Angeles Clippers" |
| `GAME_ID` (string, prefixed by season for non-NBA) | Unique per game per pipeline | Untyped `GAME_ID` | int vs str collisions across leagues |
| `SEASON_ID` (canonical `"YYYY-YY"` string) | Single source of truth | `SEASON` (int) | Start-year vs end-year convention differs by league (NCAA, G-League use end year) |

**Gate 2 — Temporal alignment is explicit.**

Every cross-pipeline join must declare its temporal alignment policy in a
SQL comment AND in the mart's `schema.yml` description. The four legal
policies:

```sql
-- TEMPORAL_POLICY: same_event
-- Both sides must reference the same GAME_ID / SEASON_ID. Use for "what
-- happened in this game" joins.
ON a.GAME_ID = b.GAME_ID

-- TEMPORAL_POLICY: as_of
-- Right side is "the most recent value as of left side's date." Use for
-- joining a slowly-changing dim (contracts, archetypes) to a fact (games).
ON b.PLAYER_ID = a.PLAYER_ID
   AND b.EFFECTIVE_DATE = (
       SELECT MAX(EFFECTIVE_DATE) FROM b2
       WHERE b2.PLAYER_ID = a.PLAYER_ID
         AND b2.EFFECTIVE_DATE <= a.GAME_DATE
   )

-- TEMPORAL_POLICY: snapshot
-- Right side is point-in-time at a known cutoff (e.g., season start).
-- Document the cutoff source.
ON b.SEASON_ID = a.SEASON_ID AND b.SNAPSHOT_DATE = '{season_start}'

-- TEMPORAL_POLICY: prior_season
-- Right side is the previous season's aggregate (used for priors / projections).
ON b.PLAYER_ID = a.PLAYER_ID
   AND b.SEASON_ID = (a.SEASON_ID - 1 expressed as YYYY-YY)
```

A join with no declared policy is a bug — reviewer must reject the PR.

**Gate 3 — Required upstream freshness is documented per mart.**

Cross-pipeline marts implicitly assume their upstream marts are fresh. When
upstream goes stale, the cross-pipeline mart silently joins yesterday's
left side to last week's right side. Every cross-pipeline mart's
`schema.yml` must declare:

```yaml
models:
  - name: mart_combined_prospect_value
    description: |
      Cross-pipeline mart joining prospects (left) to NBA value (right).
      TEMPORAL_POLICY: as_of (NBA value as of prospect SCORE_DATE)

      REQUIRED_UPSTREAM_FRESHNESS:
        - mart_prospects_big_board: <= 24 hours
        - mart_nba_value_season:    <= 24 hours
        - dim_canonical_player_ids: <= 7 days
      STALE_BEHAVIOR: build_anyway_with_warning
        # alternatives: skip_build_raise_alert, skip_build_silent
    tests:
      - dbt_utils.expression_is_true:
          expression: "GAME_DATE >= '2003-01-01'"
      - cross_pipeline_freshness_gate:
          upstreams: [mart_prospects_big_board, mart_nba_value_season]
          max_age_hours: 24
```

**Gate 4 — Anti-leakage at the join boundary.**

Cross-pipeline joins are a common source of leakage when one side has data
that hasn't happened yet from the other side's perspective. Examples:

- Joining prospects (forward-looking) to NBA value (backward-looking)
  must use `as_of` semantics — the right side cannot reference NBA games
  that occurred *after* the prospect was scored.
- Joining player_game (event-grained) to season_aggregates (window-grained)
  must use `prior_season` or as-of cutoffs — the season aggregate cannot
  include the game being predicted.
- Joining trade_history (point-in-time) to player_value (continuously-updated)
  must use the trade's `executed_at` as the right side's cutoff, not the
  current value.

**Gate 5 — Row-count audit on every build.**

Every cross-pipeline mart must add a row-count assertion:

```sql
-- After the join, verify left side wasn't fan-out-corrupted
{{ config(
    post_hook="
        SELECT CASE WHEN
            (SELECT count(*) FROM {{ this }}) >
            (SELECT count(*) FROM {{ ref('mart_prospects_big_board') }})
        THEN error('Cross-pipeline join inflated rows; check join keys')
        END
    "
) }}
```

Or as a dbt test:

```yaml
- assert_no_row_inflation:
    base_model: mart_prospects_big_board
    joined_model: mart_combined_prospect_value
    tolerance_pct: 0   # left join should not change row count
```

> **Summary**: cross-pipeline joins are the highest-leverage place to
> introduce silent bias. Every one must declare its join key (canonical IDs
> only), its temporal policy (one of four named patterns), its upstream
> freshness requirement, and a row-count assertion. PRs that add a
> cross-pipeline mart without all four are not mergeable.

---

## 11. Step 10 -- Wire R2 Artifact Promotion

Every pipeline that produces artifacts consumed by Railway must wire R2 uploads
as the final promotion step. This is the transport layer between local pipeline
execution and production serving.

### 11.1 Architecture Overview

```
LOCAL DESKTOP                    CLOUDFLARE R2                     RAILWAY
+-----------------+              +------------------+              +------------------+
| Pipeline stages |   PUT via    | basketball.duckdb|   curl on    | FastAPI replicas  |
| dbt build       | -----------> | manifest.json    | -----------> | (downloads on     |
| Validation gate |  upload_     | pipeline-specific|   boot +     |  boot + polls     |
|                 |  data.sh     | artifacts        |   60s poll   |  manifest every   |
+-----------------+              +------------------+              |  60s for updates) |
                                                                   +------------------+
```

**Why R2?** Cloudflare R2 is S3-compatible with zero egress fees. stats.nba.com
blocks cloud IPs, so pipelines must run locally. R2 bridges local compute to
Railway serving.

### 11.1a Data Layer Decision Tree (R2 vs Local DuckDB vs Railway Postgres)

The biggest cause of "where does this query live?" confusion in a multi-machine
setup is treating R2, local DuckDB, and Railway Postgres as interchangeable.
They are not. Use this matrix when you decide where a read or write belongs.

| Use case | Lives in | Read pattern | Write pattern | Why |
|----------|----------|--------------|---------------|-----|
| Pipeline reads upstream **gold parquets** during a DAG run | R2 (canonical) | `duckdb.read_parquet('s3://bucket/path')` from the local DAG runner | Pipeline never writes to upstream's R2 path | Pipelines must be **regen-from-R2 idempotent**. Never rely on local-only state from a previous run. |
| Pipeline **intermediate** Bronze->Silver->Gold artifacts | Local parquet on the runner that produced them | `pd.read_parquet('data/silver/...')` | Local-only until Gold validation passes | Bronze is immutable per-machine; only validated Gold gets uploaded. |
| Serving endpoints (FastAPI on Railway) | Local `basketball.duckdb` materialized from R2 on container boot | `con = duckdb.connect('basketball.duckdb', read_only=True)` | NEVER write from a serving endpoint | Sub-10ms queries; no cold-start latency to R2; manifest hot-reload swaps the file atomically. |
| Multi-session DuckDB inspection / Quack lab | Copied or disposable DuckDB artifact owned by one server process | DuckDB clients use `quack_query(...)` or `ATTACH 'quack:host'` after auth | Read-only by default; disposable-write tests only | Remote DuckDB access can help several sessions inspect one artifact, but it must not bypass R2 locks, dbt validation, or FastAPI serving contracts. |
| **Live operational state** (auth, sessions, geo-social events, user wearables, oauth tokens) | Railway Postgres | `psycopg/SQLAlchemy` | Within a transaction, with idempotency keys at the boundary | Real OLTP. R2 is single-version artifact storage, not OLTP. |
| Ad-hoc analysis from your laptop | DuckDB pointing directly at R2 (`s3://...parquet`) | One-off `duckdb` query in a notebook | Do not write | No download dance for one-off questions. Cheap and fast. |
| Cross-machine "I want the latest gold on this machine" | Pull from R2 to local | `bash scripts/upload_data.sh --download` (or equivalent rclone/aws sync) | N/A | Treat R2 as the **single source of truth**. Both machines pull from it; only one machine pushes to it per artifact family. |
| Champion ML model artifacts (<= ~5 MB) | R2 (or git for tiny artifacts) | `joblib.load(local_path)` after R2 bootstrap | `upload_data.sh --models` after dual-save validation | Small enough that the bootstrap cost is negligible. |
| Bronze/silver intermediate parquets, training data, model traces | Local only | N/A from R2 | N/A to R2 | Too large; reproducible from upstream + code. R2 storage is for serving artifacts, not training data lakes. |

Direct DuckDB access rule: one process may own a DuckDB file in read-write
mode, and multiple processes may read a copied/promoted artifact in read-only
mode. Multiple direct read-write processes on the same DuckDB file are not a
pipeline pattern. Quack is the only approved way to evaluate multi-client
DuckDB access today, and it starts as a read-only lab with one declared server
owner.

**The two anti-patterns to avoid:**

1. **Don't make Railway Postgres a giant data lake "because Pro gives you a TB."**
   R2 is cheaper, S3-native, and already your contract for serving artifacts.
   Railway TB is for Postgres growth headroom (auth, geo-social, user state),
   not for parking 200 GB of game logs.
2. **Don't query R2 directly from a hot serving endpoint.** Serving reads from
   the locally-bootstrapped DuckDB so a request never blocks on R2 latency or
   on R2 availability. Hot-reload via manifest is the right pattern; ad-hoc
   `read_parquet('s3://...')` from inside a request handler is not.
3. **Don't treat Quack as a production write bypass.** Quack centralizes remote
   access through a DuckDB server process, but it does not replace
   `upload_data.sh`, `upload.lock`, full dbt builds before core uploads, or
   validation. Shared Quack use starts read-only against copied/disposable
   artifacts until the protocol, authz, logging, and concurrency behavior are
   proven for the exact DuckDB/Quack version.
4. **Don't let a remote SQL surface become a serving API.** Quack may help
   internal inspection, but public product traffic still goes through FastAPI
   response models, freshness checks, documented missing-data behavior, and
   promoted artifacts.

**The mental model**: R2 is the **shared production artifact store** that
every machine reads from. Local DuckDB is the **per-machine serving cache**
that bootstraps from R2 and hot-reloads on manifest changes. Railway Postgres
is the **shared OLTP plane** for live state that does not belong in a
single-version artifact. A query or write that doesn't fit one of those three
buckets is probably a design smell — stop and reconsider before adding a
fourth storage location.

### 11.2 upload_data.sh Integration

The upload script (`scripts/upload_data.sh`) is the single entry point for all
R2 promotions. It handles:

1. Computes sha256 of `basketball.duckdb`
2. Writes `manifest.json` with sha256, git SHA, validation gate, row counts,
   and previous_version rollback pointer
3. PUTs artifacts to R2 based on flags
4. PUTs `manifests/{version}.json` for immutable rollback history

```bash
# Common usage patterns
bash scripts/upload_data.sh                    # Core only (duckdb + manifest)
bash scripts/upload_data.sh --dry-run          # Print plan without uploading
bash scripts/upload_data.sh --validate         # Run validation gate first
bash scripts/upload_data.sh --skip-core --referees   # Artifact-only (skip duckdb)
bash scripts/upload_data.sh --gold-products --boards --models  # Full seasonal refresh
```

**Required env vars**: `BUCKET_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION=auto`

> **CRITICAL: `upload_data.sh` runs a full `dbt build` automatically before uploading.**
> All 9 pipeline domains (nba_value, prospects, simulation, sentiment, news, xfg,
> referees, draft_pick_power, franchise_scorecard) share ONE `basketball.duckdb`.
> A partial `dbt build --select tag:X` followed by upload would overwrite R2 with
> a DB missing other domains' tables. The script's built-in full build prevents this.
> **Never upload `basketball.duckdb` to R2 without a full `dbt build` first.**
>
> If the DuckDB file is locked (another process has it open), `dbt build` will fail.
> Kill the locking process first (`tasklist | grep python`, then kill the PID), or
> wait for it to release. **Do not skip the dbt build step.**

### 11.2a R2 Advisory Lock — Single-Writer Safety

`upload_data.sh` acquires an **advisory R2 lock** (`upload.lock`) before writing
anything. A second concurrent invocation reads the lock and **aborts with a clear
error** — it does not silently overwrite. This prevents manifest↔duckdb corruption
that would trigger Railway's OOM re-download loop.

**Rules that are never optional:**

- **NEVER delete `upload.lock` to unblock an upload.** Deleting the lock while
  another session is actively writing corrupts the manifest and causes Railway to
  re-download the full DB on every 60-second poll (OOM loop). The lock exists to
  protect you.
- **Only one session owns the production upload.** If two sessions both want to
  upload, serialize them — finish one completely before starting the next.

**When you see a lock error, follow these steps:**

1. Check whether another session or Airflow task is actively uploading:

   ```bash
   # Git Bash / Linux
   ps aux | grep upload_data
   # Windows
   tasklist | findstr upload_data
   ```

2. **If an active session is found:** wait for it to finish, then run your upload
   command once the lock clears.

3. **If no active session is found (orphaned lock from a crash):** the lock
   auto-expires after **10 minutes**. Wait out the TTL, then retry:

   ```bash
   # After the lock expires, run the upload for your pipeline:
   bash scripts/upload_data.sh --skip-core --<your-pipeline-flag>

   # Common flags:
   bash scripts/upload_data.sh --skip-core --sportsbook
   bash scripts/upload_data.sh --skip-core --lineup
   bash scripts/upload_data.sh --skip-core --referees
   bash scripts/upload_data.sh --skip-core --boards
   bash scripts/upload_data.sh --gold-products --boards --models   # full seasonal
   bash scripts/upload_data.sh                                      # core only
   ```

4. **If the lock persists beyond 15 minutes with no active process:** verify no
   process holds it, then wait one more full TTL window before taking any action.
   When in doubt, wait — a 10-minute delay costs nothing; a corrupted R2 artifact
   costs a full Railway cold-start cycle.

> **NEVER force-delete `upload.lock`.** Always wait: either for the active session
> to finish, or for the 10-minute TTL to expire naturally.

### 11.2b R2 Data Safety — DAG/Session Conflicts and Validation

R2 is a shared, single-version artifact store. **Airflow DAGs upload on schedule
and manual sessions upload ad-hoc — both write to the same bucket.** An upload
from either source overwrites what the other just wrote. Treat every upload as
a production write: know what you are overwriting before you do it.

**Core risk**: if a DAG just ran `--gold-products` and you then run
`upload_data.sh` without `--skip-core`, the script rebuilds `basketball.duckdb`
from your local data — which may be stale for the domains the DAG just refreshed
— and overwrites the fresh R2 copy with older data.

#### Before every upload — pre-flight checklist

1. **Check whether any Airflow DAG is currently running or recently finished:**

   ```bash
   airflow dags list-runs --dag-id nba_value_pipeline --state running
   airflow dags list-runs --dag-id sportsbook_pipeline --state running
   # or check Airflow UI: http://localhost:8090
   ```

2. **Know which flags each DAG uses** so you don't clobber its fresh output:

   | DAG | Upload flags | What it writes to R2 |
   | --- | ----------- | -------------------- |
   | `nba_value_pipeline` | `--gold-products` | `basketball.duckdb` + manifest + NBA value gold parquets |
   | `sportsbook_pipeline` | `--skip-core --sportsbook` | Sportsbook market/settlement parquets only |
   | `lineup_pipeline` | `--lineup` | `lineup_serving.duckdb` + sidecar |
   | `referee_pipeline` | `--skip-core --referees` | Referee gold parquets only |
   | `prospect_pipeline` | `--skip-core --boards --models` | Big boards + model artifacts |

3. **Use `--skip-core` whenever you only changed one pipeline's data.** Omitting
   it triggers a full dbt rebuild that overwrites `basketball.duckdb` across all
   9 domains with your local state.

4. **Use `--dry-run` first to confirm exactly what will be uploaded:**

   ```bash
   bash scripts/upload_data.sh --dry-run --skip-core --<your-flag>
   ```

5. **Run the pipeline's validation gate before uploading.** Never upload a
   partial PASS — the gate must reach its documented threshold:

   ```bash
   python scripts/{pipeline_name}/validation/validate_pipeline.py
   # Gate must PASS fully before proceeding to upload
   bash scripts/upload_data.sh --skip-core --{pipeline_flag}
   ```

#### After every upload — post-upload verification

Always confirm Railway received the new data before declaring the upload done:

```bash
# 1. Confirm the artifact landed in R2
curl -I "$BUCKET_URL/basketball.duckdb"
# Expected: HTTP 200

# 2. Check Railway freshness — confirm manifest version changed
curl https://<api-url>/api/v1/ops/freshness
# Look for: new manifest version, no SLA violations on affected domains

# 3. Force immediate reload if you need to verify right now
curl -X PUT https://<api-url>/api/v1/ops/refresh-analytics-db \
  -H "Authorization: Bearer $OPS_ADMIN_TOKEN"

# 4. Smoke the affected endpoint(s)
curl https://<api-url>/api/v1/<affected-domain>/...
```

If the freshness endpoint shows a stale domain or wrong manifest version, stop
and investigate — do not re-upload without diagnosing why the first propagation
failed. A second upload on top of a broken first upload does not self-heal.

#### Row-count + manifest delta gate (mandatory)

The HTTP 200 + freshness checks above prove that *something* landed. They do
not prove that the **right** thing landed. A successful PUT of an empty
parquet, or an upload from a stale local tree, will pass both. To catch those:

```bash
# 1. Capture local row count BEFORE upload
LOCAL_ROWS=$(python -c "import duckdb; \
    print(duckdb.sql(\"SELECT count(*) FROM read_parquet('data/gold/{table}.parquet')\").fetchone()[0])")
echo "Local rows: $LOCAL_ROWS"

# 2. Capture pre-upload manifest version (so you can confirm it changes)
PREV_VERSION=$(curl -s "$BUCKET_URL/manifest.json" | jq -r '.version')
echo "Previous manifest version: $PREV_VERSION"

# 3. Run the upload
bash scripts/upload_data.sh --skip-core --{flag}

# 4. Confirm manifest version actually changed
NEW_VERSION=$(curl -s "$BUCKET_URL/manifest.json" | jq -r '.version')
if [ "$NEW_VERSION" = "$PREV_VERSION" ]; then
    echo "FAIL: manifest version unchanged. Upload silently skipped or failed."
    exit 1
fi
echo "Manifest: $PREV_VERSION -> $NEW_VERSION"

# 5. Confirm Railway sees the same row count we just uploaded
RAILWAY_ROWS=$(curl -s https://<api-url>/api/v1/{domain}/rowcount | jq -r '.rows')
if [ "$RAILWAY_ROWS" -lt "$LOCAL_ROWS" ]; then
    echo "FAIL: Railway has $RAILWAY_ROWS rows; local has $LOCAL_ROWS. Hot-reload may have failed."
    exit 1
fi
```

**Mandatory checks for every upload, in order:**

1. **Pre-upload row count** captured from the local parquet/duckdb being
   uploaded. This is your ground truth for what *should* be in R2 after.
2. **Pre-upload manifest version** captured from the live R2 manifest. This
   is your "before" snapshot for the version delta.
3. **Upload runs and exits 0.** Non-zero exit means stop — do not declare
   success on a non-zero exit even if the artifact appears in R2.
4. **Post-upload manifest version differs from pre-upload.** Same version
   means the upload was a no-op (your local data hashed to the same SHA as
   what was already there). That is informational, not failure — but you
   should know it happened, not assume "success."
5. **Post-upload Railway row count >= local row count.** Strictly less means
   either Railway hasn't hot-reloaded yet (wait 60s and retry) or the
   manifest points at a corrupted artifact (rollback via
   `previous_version`).
6. **Schema hash unchanged unless the change was intentional.** Compute
   `sha256(sorted(column_names + column_types))` locally and compare to the
   value in the new manifest. A schema change you did not intend means a
   pipeline bug is silently shipping new columns to production.

If any of (4)-(6) fails, **roll back via the manifest's `previous_version`
pointer** — do not re-upload over the broken state. Re-uploading on top
of a corrupted manifest doubles the blast radius.

> **Summary**: treat R2 like a shared production database. Check DAG state before
> writing. Use `--skip-core` unless you own all domains locally. Validate before
> upload, verify after. Never assume an upload succeeded without checking the
> freshness endpoint **and** the row count delta.

### 11.3 Railway Bootstrap & Hot-Reload

When a Railway replica starts (`api/start.sh`):

1. **Bootstrap**: checks if `basketball.duckdb` exists on disk. If missing,
   downloads from R2 with sha256 verification against `manifest.json`.
2. **Start serving**: uvicorn starts, serves from local copy.
3. **Background poller**: `api/app/db.py` checks R2 manifest every 60 seconds.
   On version change, downloads new artifact, verifies sha256, swaps atomically.
   All replicas hot-reload independently -- no restart needed.

### 11.4 What Stays Local vs What Goes to R2

| Category | Goes to R2? | Notes |
|----------|-------------|-------|
| `basketball.duckdb` (~51 MB) | YES | Daily, after dbt build + validation |
| `manifest.json` (<1 KB) | YES | Every upload (sha256 + metadata) |
| Pipeline-specific gold parquets | YES | Per pipeline flags (see DAG section) |
| Champion models (<=5 MB each) | YES (or git) | XFG joblib in git; RSF/LTR via `--models` |
| Bronze/silver/gold training data | NO | Too large, training-only |
| `cache/features/` (ML feature store) | NO | Training-only, regenerated by pipeline |
| Airflow DAGs | NO | Run locally, never deployed |
| Model training traces | NO | Large, reproducible |

**Total persistent R2 storage**: ~200-300 MB at ~$0.03/month.

### 11.5 Verification After Upload

```bash
# Check R2 artifact exists
curl -I "$BUCKET_URL/basketball.duckdb"
# Expected: HTTP 200

# Check Railway freshness
curl https://<api-url>/api/v1/ops/freshness
# Returns: manifest metadata + SLA staleness checks

# Force immediate reload on Railway
curl -X PUT https://<api-url>/api/v1/ops/refresh-analytics-db \
  -H "Authorization: Bearer $OPS_ADMIN_TOKEN"
```

### 11.6 Manual Override Workflow

When running outside Airflow (debugging, one-off fixes):

```bash
# 1. Run pipeline stages
python scripts/{pipeline_name}/run_pipeline.py

# 2. Build dbt
cd api/de/basketball && dbt build --profiles-dir .

# 3. Validate
python scripts/{pipeline_name}/validation/validate_pipeline.py

# 4. Upload to R2
bash scripts/upload_data.sh --{pipeline_flag}

# 5. Verify Railway sees new data
curl https://<api-url>/api/v1/ops/freshness
```

### 11.7 Checklist for New Pipelines

- [ ] Determine which artifacts this pipeline produces for serving
- [ ] Add an upload flag to `scripts/upload_data.sh` (e.g., `--{pipeline_flag}`)
- [ ] Wire `upload_fn` in the Airflow DAG (see Section 7.2)
- [ ] Add R2 bootstrap logic in `api/start.sh` if the pipeline has standalone
      artifacts (not part of `basketball.duckdb`)
- [ ] Test with `--dry-run` first, then verify with `/api/v1/ops/freshness`
- [ ] Document the upload flags in the pipeline spec doc

### 11.8 Local Full-DAG -> Staging -> Production Gate

Every new pipeline, scheduler addition, GPU retrain segment, or serving artifact
change must clear this ladder in order. Do not enable the DAG schedule or
publish production artifacts until every prior gate passes.

**Gate 0 -- Plan the rollout before code**
- Start the pipeline spec with `Module Tree`, `Stage Registry`, and `Execution Tracker`.
- For every stage, document inputs, outputs, validation gate, rerun command,
  scheduler task name, serving touchpoints, and rollback point.
- If the pipeline includes Bayesian, GBDT, or clustering work, read the
  relevant modeling guide before implementation and treat its contract checks as
  mandatory acceptance criteria.

**Gate 1 -- Keep environments reproducible**
- If a new package is needed, install it with `uv pip install <package>` first
  so you can verify import/runtime behavior immediately.
- Then add the package with the correct pin or range to `pyproject.toml`.
- Run `uv sync` and confirm the environment still resolves cleanly.
- Never rely on a package that exists only in one developer's venv.

**Gate 2 -- Prove the pipeline in isolation**
- Run targeted unit tests for the new modules and any changed shared utilities.
- Run the stage validation scripts and schema checks locally.
- Execute each stage in order on local artifacts before attempting the full DAG.
- Do not ship defensive coding, hardcoded thresholds, fake defaults, or silent
  fallbacks; thresholds and decisions must be data-derived.

**Gate 3 -- Run the full DAG locally**
- Run the complete DAG locally from the same scheduler/runtime that will own it.
- GPU tasks must route through the datascience container or dispatcher, not the
  Airflow scheduler container directly.
- Log the actual training backend (`jax.default_backend()`, device list, or
  library-equivalent) for every backend-sensitive retrain.
- Keep the DAG paused by default until one clean local end-to-end run passes.
- Run `scripts/audit_dag_schedules.sh` and verify no schedule collisions and
  `max_active_runs=1` before enabling the schedule.

**Gate 4 -- Prove serving and frontend safety locally**
- Boot the backend locally against the new artifacts and smoke the affected
  endpoints.
- Verify typed responses, expected `404`/`503` behavior, and `/api/v1/health`
  plus `/api/v1/ops/freshness` when the artifact affects serving.
- If the change is user-facing, run the frontend build and smoke the affected
  request paths before staging.
- Existing endpoints must continue to work with the new artifact set; do not
  assume the new pipeline is isolated from the rest of `basketball.duckdb`.

**Gate 5 -- Validate in staging**
- Use `railway up --service backend` and `railway up --service frontend` as
  needed to test the working tree in real Railway/R2/Redis conditions.
- Validate health, artifact bootstrap, CORS, freshness, and the affected
  endpoint family against the staging deployment.
- A staging deployment that only works because of an ad hoc manual patch is not
  ready for production.

**Gate 6 -- Promote to production carefully**
- Deploy only in the approved low-traffic windows unless this is a hotfix.
- Push code first, then run the single-writer `upload_data.sh` promotion if the
  serving artifact changed.
- Use the R2 advisory lock as intended; one upload session at a time.
- Unpause the new schedule only after production health and freshness checks
  pass with the new artifact.

**Gate 7 -- Keep rollback ready**
- Identify the previous good manifest version, previous good deployment, and any
  previous champion artifact before cutover.
- If any gate fails, pause the DAG or revert; do not "watch it in prod" and
  hope the frontend or scheduler survives it.

#### 11.8.1 DAG Ready To Unpause Checklist

A DAG may exist in code, appear in Airflow, and remain paused. It may not be
unpaused until every item below is true:

- [ ] Fetcher/entrypoint is registered and reachable from the intended runtime
- [ ] Required env vars, secrets, and credentials are present and documented
- [ ] Worker pool / queue / concurrency settings are assigned intentionally
- [ ] Timeout, retries, and `max_active_runs=1` are set explicitly
- [ ] Manual trigger passes end-to-end once
- [ ] 2-3 clean follow-up runs complete without operator intervention
- [ ] Validation artifacts and quality metrics land in the documented locations
- [ ] Success/failure emails or alerts render the correct root-cause fields
- [ ] `/inventory`, freshness, or equivalent ops surfaces show the DAG/source
- [ ] The previous good rollback target is recorded before the first live schedule

If any box is not checked, the DAG stays paused.

#### 11.8.2 Root-Cause Taxonomy (Required)

Every failed run must resolve to one primary failure stage. Use exactly one of
these values in docs, alerts, inventory, and ops summaries:

- `scheduler`
- `queue`
- `claim`
- `fetch`
- `validation`
- `artifact_write`
- `promotion`
- `gpu_dispatch`
- `training`
- `serving_refresh`

Per run, capture these fields so operators can answer "where did it fail, why,
and what changed?" without opening raw logs:

- `stage_failed_at`
- `error_class`
- `error_summary`
- `log_tail`
- `worker_pool`
- `artifact_ref`
- `rows_written`
- `bytes_written`
- `null_summary`
- `min_event_date`
- `max_event_date`
- `gpu_used`
- `gpu_provider`
- `gpu_runtime_seconds`
- `gpu_cost_usd`

The pipeline spec's stage registry should map each stage to its expected
root-cause bucket so future sessions do not invent their own failure labels.

**Filesystem-permission failures are an environment cause, not a code/data
defect.** A scheduled DAG that fails with `error_class=PermissionError` /
`[Errno 13]` writing under a shared bind-mount (e.g. dbt's
`api/de/basketball/target/`, `data/`, `cache/`) almost always means a prior
**root** `docker exec` poisoned the path with `root:root 0644` files that the
`astro` (uid 50000) scheduler cannot overwrite. Map it to `artifact_write`
(or `serving_refresh` for a dbt mart refresh), set `error_summary` to the exact
offending path, and fix it by `chown -R 50000:50000 <path>` **plus** enforcing
the prevention rule: run all manual container dbt/pipeline writes as
`docker exec -u astro`. Do **not** add a runtime chown/try-except fallback to
the affected stage — that masks the operator-discipline root cause and violates
no-defensive-coding. See the cross-container file-ownership contract in
DATA_ENGINEERING_PIPELINE.md (§0.9) and XFG_FORECASTING Part 16.

#### 11.8.3 GPU Training Contract (Required)

Every GPU-capable DAG or job must declare its contract before it is scheduled:

- `requires_gpu`
- `gpu_provider_default` (`local` or `runpod`)
- `gpu_type`
- `expected_runtime_minutes`
- `expected_cost_usd`
- `actual_runtime_minutes`
- `actual_cost_usd`
- `backend_proof`
- `artifact_ref`
- `trained_on_data_cutoff`
- `retrain_reason`

Supported runtime modes:

- **Mode A -- CPU-safe default**: the scheduler and the training entrypoint must
  still function on CPU so the orchestration plane never depends on GPU health.
- **Mode B -- GPU-enabled training**: JAX, XGBoost, or other GPU backends may be
  used when available, but the run must log runtime-derived proof rather than
  assuming CUDA because of container name or hardware presence.

Retrain policy:

- Retrains are triggered by a documented data-cutoff contract, not just by the
  clock moving.
- `trained_on_data_cutoff` and `retrain_reason` must be persisted with the run.
- If the expected GPU runtime/cost envelope is materially exceeded, the run is
  degraded and requires root-cause review before becoming the new standard path.

Scheduling policy:

- Every Airflow task that can materially use the local GPU must be assigned to
  the single-slot `gpu_exclusive` pool (`pool_slots=1`). This includes LLM/Ollama
  generation, CV GPU stages, and training dispatch tasks.
- GPU work that can also be invoked outside Airflow must acquire the shared
  process lock in `api.src.ingestion.gpu.exclusive_lock` for the duration of the
  GPU body. The lock file may be inspected for owner/run metadata, but never
  deleted as a way to "fix" scheduling.

#### 11.8.4 Artifact Versioning & Rollback Contract (Required)

Every ML pipeline that produces a serving artifact (champion model, calibration
parameters, derived thresholds, lookup tables) must save **two copies** on
every successful retrain: an active copy that serving reads, and a versioned
historical copy that rollback reads. Without the historical copy, a bad
retrain has no recovery path other than re-training the entire pipeline.

**Dual-save layout (mandatory for all serving artifacts):**

```text
serving/artifacts/{pipeline_name}/
    champion/                                  # ACTIVE — served by FastAPI
        model.joblib                           # The current best model
        manifest.json                          # version, trained_on_data_cutoff,
                                               # backend_proof, retrain_reason,
                                               # previous_version pointer
        feature_schema.json                    # Column names + dtypes the model expects
        calibration.json                       # Threshold/calibration params
    champion_{version}/                        # HISTORICAL — never overwritten
        model.joblib                           # Identical to what was champion at v
        manifest.json
        feature_schema.json
        calibration.json
    champion_{version-1}/                      # Older versions kept for rollback
        ...
```

**Required manifest fields (every saved artifact):**

| Field | Type | Purpose |
|-------|------|---------|
| `version` | string (ISO timestamp or semver) | Unique per save; never reused |
| `previous_version` | string or null | Pointer for rollback; null only for the first version |
| `trained_on_data_cutoff` | ISO date | Latest event_date in training data; downstream uses this to detect stale-vs-data |
| `backend_proof` | string | `jax.default_backend()` output, `xgb.get_config()['use_rmm']`, or equivalent runtime evidence — NOT container name |
| `retrain_reason` | enum | `data_cutoff_advanced`, `feature_added`, `bug_fix`, `scheduled_periodic` |
| `git_sha` | string | Commit SHA of the training code |
| `metric_summary` | dict | The eval metric(s) used for promotion: `{"primary": "auc", "value": 0.834, "ci_low": 0.821, "ci_high": 0.847}` |
| `champion_challenger_decision` | string | `promoted`, `held`, `regressed_keep_old` |
| `feature_schema_hash` | string | sha256 of sorted feature names + dtypes |
| `written_at` | ISO timestamp | When the artifact was saved |

**Promotion contract (champion-challenger gate):**

A new artifact may be promoted to `champion/` only if:

1. The challenger's primary metric is **>=** the current champion's primary
   metric on a held-out temporal slice (no win-by-noise — use bootstrapped CI).
2. The challenger passes the same artifact-structural validation the champion
   passes (correct keys, correct feature schema, no missing calibration).
3. The challenger's `feature_schema_hash` either matches the champion's OR
   the change is documented in the spec doc (new features added, old
   features deprecated). Silent schema drift is a promotion-block.
4. The previous champion is **copied** to `champion_{old_version}/` BEFORE
   the new artifact is written to `champion/`. The order matters — if the
   write to `champion/` fails after `champion_{old_version}/` is removed,
   serving is left with no model.

**Rollback procedure (when a promoted champion regresses in production):**

```bash
# 1. Identify the previous good version from the active manifest
PREV=$(cat serving/artifacts/{pipeline}/champion/manifest.json | jq -r '.previous_version')
echo "Rolling back to $PREV"

# 2. Atomic swap: copy the historical version's contents into champion/
rm -rf serving/artifacts/{pipeline}/champion.bad
mv serving/artifacts/{pipeline}/champion serving/artifacts/{pipeline}/champion.bad
cp -r serving/artifacts/{pipeline}/champion_${PREV} serving/artifacts/{pipeline}/champion

# 3. Re-upload to R2 so Railway picks up the rollback on next manifest poll
bash scripts/upload_data.sh --models   # or pipeline-specific flag

# 4. Verify the rollback landed
curl https://<api-url>/api/v1/ops/freshness | jq '.{pipeline}.model_version'
# Should now show $PREV
```

**Pipeline-specific responsibilities:**

- **GBDT pipelines**: dual-save during `train_*.py` finalization step.
  See `GBDT_PIPELINE_GUIDE.md` for the `champion_{version}/` convention
  already implemented in `gddt/serving/`.
- **Bayesian pipelines**: traces are large; save only the inference-ready
  artifacts (means, posteriors, calibration) under `champion/`, not the
  full MCMC trace. Trace files stay local under `serving/artifacts/bayesian/training/`.
- **Clustering pipelines**: dual-save the centroid file + role prototypes
  + scaler. The clustering pipeline produces deterministic features
  consumed by downstream models, so rollback also requires re-running any
  downstream model that consumed the bad clustering.

**Anti-patterns (never do these):**

- Overwrite `champion/` without first copying the previous version. If the
  new write partially fails, serving is left with no model.
- Promote on a single-fold metric. Use temporal CV with bootstrapped CIs.
- Save artifacts with a manifest field set to `null` because "we don't have
  it yet." Empty fields signal incomplete metadata to operators reading the
  manifest later. Either fill the field or document its absence.
- Reuse a version string. Versions are immutable identifiers; reuse breaks
  rollback because `previous_version` no longer points at unique state.
- Delete `champion_{version}/` directories to save disk space without first
  archiving them off-machine. Disk is cheaper than re-training; old champions
  are also evidence for "did we cause this regression in v3 or has it always
  been there?" investigations.

### 11.9 DAG Operations Capacity Dashboard Standard

Every pipeline that is scheduled, promoted, or expected to consume meaningful
CPU/GPU runtime must be visible in the admin DAG operations dashboard before it
is treated as production-ready. The dashboard is an operational telemetry plane:
it summarizes run health, runtime, capacity, and cost projection for operators.
It is not a modeling feature source and must not feed training data, dbt marts,
or forecast labels.

**Required module tree:**

```text
api/src/ingestion/dashboards/
    dag_observability.py       # reads ingest.dag_run_history and emits run/window summaries
    ingest_fleet.py            # reads Airflow metadata and enriches DAG schedule/owner/paused state
api/app/routers/
    ingest_status.py           # admin-gated, typed response_models, no-store responses
web/src/services/
    adminService.js            # fetchDagObservability, fetchIngestFleet, fetchGpuJobs
web/src/components/admin/
    DagOpsDashboard.jsx        # merged DAG table, drilldowns, capacity graphics, projections
docs/backend/engineering/
    DATA_ENGINEERING_PIPELINE.md
docs/frontend/
    FRONTEND.md
```

**Required stages:**

| Stage | Owner Module | Required Output | Gate |
|-------|--------------|-----------------|------|
| O0 Contract inventory | spec/doc pass | List every DAG field available from `dag_run_history`, Airflow metadata, and GPU job telemetry | Missing fields are explicitly nullable; do not invent values |
| O1 Ledger totals | `dag_observability.py` | Daily/weekly/monthly summaries including `total_duration_seconds`, `gpu_runtime_seconds`, cost, success/failure counts | SQL derives totals from the ledger with `SUM(...)`; no frontend recomputation from partial rows |
| O2 Airflow merge | `ingest_fleet.py` + router | Owner, schedule expression, next run, paused state, tags, worker pool, source, latest Airflow run/error | A missing Airflow DB returns a typed degraded response, not fake rows |
| O3 Capacity graphics | `DagOpsDashboard.jsx` | Daily CPU, weekly CPU, and weekly GPU used/remaining graphics | Daily CPU includes daily/subdaily DAGs; weekly CPU includes daily/subdaily/weekly DAGs; GPU includes observed GPU runtime |
| O4 Projection controls | `DagOpsDashboard.jsx` | Operator-entered CPU/GPU minutes per run, runs per week, and hourly rate inputs | Costs are shown only from observed telemetry/specs or operator-entered rates |
| O5 Admin table/drilldown | `DagOpsDashboard.jsx` | One row per DAG with source/worker/artifact, Airflow schedule/cadence/owner/paused/next run, state/stage, selected-window runs/success/fail/skips, latest/avg/p95/total runtime, event date range/window max, rows/size, NaNs, GPU required/used/provider/runtime/cost, last run, last error | Scan table must expose high-signal contract fields; expanded detail keeps lower-frequency diagnostics and recent-run details |
| O6 Serving/docs | router + docs | API response models aligned with `UNIFIED_SERVING_GUIDE.md`; tracker updated in `FRONTEND.md` and pipeline spec | No undocumented endpoint fields |
| O7 Validation | local checks | Python compile/type/build checks for touched layers | No new package unless added with `uv pip install`, recorded in `pyproject.toml`, and verified with `uv sync` |

**Always-current maintenance gate:**

Any change to DAG observability, Airflow fleet, or GPU job telemetry is not
complete until the admin DAG dashboard is updated in the same change set. This
gate applies when a field is added, renamed, removed, changes null semantics, or
changes units.

Required closeout for every such change:

1. Update the typed API response model and `UNIFIED_SERVING_GUIDE.md`.
2. Surface the field in `DagOpsDashboard.jsx`: high-signal fields belong in the
   scan table; lower-frequency diagnostic fields belong in the expanded detail
   panel.
3. Update `docs/frontend/FRONTEND.md` Done/Doing/Next so the active frontend
   order stays visible to the next session.
4. Update this section if the dashboard contract or capacity formula changes.
5. Run backend compile plus frontend type/build checks. If the backing DB is not
   reachable, keep the field nullable and visible as unavailable rather than
   inventing fallback data.
6. Probe new or changed SQL against PostgreSQL syntax directly, and avoid
   reserved words such as `window` for internal CTE/grouping column names even
   when the public response field uses that name.

**Capacity formulas:**

- `used_total_seconds = SUM(duration_seconds)` from the run ledger for the
  selected window.
- `used_gpu_seconds = SUM(gpu_runtime_seconds)` from the run ledger or GPU job
  telemetry for the selected window.
- `used_cpu_seconds = max(used_total_seconds - used_gpu_seconds, 0)`.
- `window_capacity_seconds = window_days * 24 * 60 * 60 * resource_slots`.
- `remaining_seconds = window_capacity_seconds - used_seconds`.
- CPU `resource_slots` must come from configured Airflow local task parallelism
  when available. `/ingest/dag-observability.capacity_config.cpu_resource_slots`
  is the primary source because it remains available even when Airflow metadata
  DB access for `/ingest/fleet` is down; `/ingest/fleet.parallelism` is a
  secondary source. If both are unavailable, the dashboard must label the view
  as a one-lane baseline.
- Daily CPU graphics use the daily window and daily/subdaily schedules only.
- Weekly CPU graphics use the weekly window and daily/subdaily/weekly schedules.
- Weekly GPU graphics use the weekly window and observed GPU runtime.
- If Airflow schedule metadata is unavailable, CPU capacity graphics may use the
  global ledger summary for the same window, but the card must label that
  provenance and keep schedule/cadence fields unavailable. Do not infer cadence
  from DAG names or run counts.
- Local-lane pressure is data-derived: when `remaining_seconds` goes negative
  after current or projected work, the dashboard shows the overflow against one
  local serial lane. This is pressure evidence, not proof that Modal/RunPod is
  required; first verify configured local worker lanes/parallelism, then split
  only the work the confirmed local lanes cannot cover. Do not add arbitrary
  safety thresholds.

Do not hardcode schedule thresholds beyond cadence classification derived from
Airflow schedule expressions. Unknown schedules remain `unknown`; they are not
forced into daily or weekly capacity.

**Workload bands and pools:**

Every production DAG must declare the narrowest practical Airflow pool for its
dominant bottleneck. Pool choice is an operations contract, not a performance
guess: it must be justified by observed task duration, Docker/process CPU,
GPU telemetry, source/API rate limits, DuckDB/R2 writer ownership, or the
pipeline's documented source contract.

| Band | Pool | Default Slots | Use When | Required Evidence |
|------|------|---------------|----------|-------------------|
| CPU-heavy local | `cpu_heavy` | 1 | Long monolithic local CPU tasks such as large simulations, prospect daily/rebuild, or large pandas/model rebuild stages | Airflow duration plus host/container CPU evidence or stage runtime history |
| GPU-exclusive | `gpu_exclusive` | 1 | CUDA/JAX/PyTorch/CV/Ollama/LLM work that can consume the local GPU | GPU backend/runtime proof and `nvidia-smi`/job telemetry where available |
| Source/API serial | source-specific pool, e.g. `stats_nba_serial` | 1 | APIs with known per-IP/session rate limits or WAF cooldown risk | Source contract, recent failure evidence, or provider limit |
| Shared writer | writer-specific pool, e.g. `lineup_duckdb_serial` | 1 | DuckDB/parquet paths with single-writer semantics | Artifact path ownership and corruption/lock risk |
| R2 publish | `r2_publish` | 1 | Any validated artifact upload to R2 | R2 advisory lock plus pre/post validation; never remove locks manually |

Pool slots are the first limiter; DAG `max_active_runs=1` is still required for
same-DAG overlap control where duplicate runs would touch the same artifacts.
If an existing task instance was created before a pool change, do not assume it
is protected by the new pool. Let it finish or make a deliberate operator
decision before clearing/retrying competing work.

**Projection and cost rules:**

- GPU hourly cost can be derived from observed `cost_usd / runtime_hours` or
  from `gpu_job_specs.hourly_rate_usd` when the spec is present.
- CPU hourly cost must come from operator input unless the ledger has real CPU
  cost telemetry. Do not ship a default CPU price.
- Projected added runtime is `minutes_per_run * runs_per_week`.
- Projected added cost is shown only when an hourly rate is known.
- Null, missing, or unavailable source values render as unavailable (`--`) in
  the frontend rather than as zero.

**Safety rules:**

- The dashboard is read-only. It must not trigger DAGs, R2 uploads, or model
  promotion directly.
- R2 is still a shared production database for artifacts. When a dashboard
  projection leads to a new process or retrain, run the normal validation gate,
  wait for the R2 advisory lock, never remove the lock manually, upload through
  `scripts/upload_data.sh`, and validate row counts/manifests before and after.
- Multi-session work follows Section 15: claim the touched files, stage only
  owned files, push code before data, and keep docs updated so parallel sessions
  know what changed.
- Modeling capacity displays may mention Bayesian, clustering, or GBDT jobs
  only as telemetry. The model setup still follows the corresponding guide in
  `docs/backend/modeling/` and the serving artifact rules in
  `UNIFIED_SERVING_GUIDE.md`.
- No defensive hardcoded thresholds, fake fallback rows, fake runtime values, or
  silent error swallowing. Decisions must be data-derived and traceable to the
  source row, schedule expression, or operator projection input.

**Phase 2 enforcement (cross-link):** the executable layer for §11.9 — the
declarative pool registry, the per-stage telemetry sink, the source-aware pool
bridge driven by `sources.yaml`, the p95 / queue-wait reader, and the audit
script that enforces the modeling-leakage gate — lives in
[`DATA_ENGINEERING_PIPELINE.md` §0.19](engineering/DATA_ENGINEERING_PIPELINE.md#019-phase-2-workload-band-capacity-enforcement-2026-05-04).
Stages WB8–WB14 there are how this section's standard becomes enforced rather
than aspirational. Any change to band rules, capacity formulas, or workload
semantics must be reflected in both sections.

---

## 12. Step 11 -- Document and Ship

### 12.1 Pipeline Spec Document

Create `docs/backend/projects/{PIPELINE_NAME}_SPEC.md` with these sections:

1. **Overview** -- what the pipeline does, data sources, key outputs
2. **Execution Tracker** -- ordered checklist of `planned -> implemented -> local pass -> staging pass -> production pass`
3. **Module Tree** -- file listing with one-line descriptions (see template below)
4. **Stage Registry** -- table of all stages with outputs and dependencies (see template below)
5. **Data Architecture** -- bronze/silver/gold schema with row/column counts
6. **Build Order** -- numbered stages with dependencies, build command examples
7. **Promotion Plan** -- local full-DAG gate, staging checks, production cutover, rollback notes
8. **YAML Schemas** -- which ML schemas the pipeline uses
9. **How to Run** -- copy-paste commands for daily, rebuild, validate modes
10. **Validation** -- expected pass counts, known issues
11. **API Endpoints** -- routes and response shapes
12. **dbt Models** -- staging/intermediate/mart model names
13. **R2 Artifacts** -- upload flags, what gets promoted, verification steps
14. **Known Limitations** -- active issues, resolved items, remaining roadmap

The first screenful of the spec should make the implementation order obvious:
execution tracker first, then module tree, then stage registry. A future
session should be able to answer "what is done, what is next, and what breaks
if I enable the DAG today?" without reading the full narrative.

#### 12.1.1 Module Tree Template

The module tree goes at the TOP of the spec doc, immediately
after the overview. Every file gets a one-line comment with its stage ID.

```text
## Module Tree

{pipeline_package}/                          # Core importable package
    __init__.py
    governance/                              # Phase -1: Upstream audits
        audit_serving_readiness.py           # S-1.1: Upstream artifact + schema audit
        audit_temporal_contracts.py          # S-1.2: As-of cutoff manifest
    data/                                    # Phase 0: Data preparation
        build_training_table.py              # S0.1: Raw -> one-row-per-event training table
        derive_distributional_params.py      # S0.2: Data-derived thresholds -> JSON artifact
        recent_form_updater.py               # S0.3: Rolling recency update
        pregame_loader.py                    # S0.4: Context assembler (TRAINING/SERVING modes)
    priors/                                  # Phase 1: Pregame/pre-prediction inputs
        build_starter_projections.py         # S1.1: P(start) projections
        build_minutes_targets.py             # S1.2: Expanding-window minutes
    training/                                # Phase 2: Component model training
        trainer_utils.py                     # Shared: encode, train, save (dual-save)
        train_primary_model.py               # S2.1: Primary GBDT champion
        train_secondary_model.py             # S2.2: Secondary model
    engine/                                  # Phase 3: Inference/simulation
        core_loop.py                         # S3.1: Main inference engine
        monte_carlo.py                       # S3.2: MC orchestrator + aggregation
    validation/                              # Validation suite
        validate_data.py                     # V0: Schema + row count + null rate gates
        historical_replay.py                 # V1: Holdout replay with real data
        serving_gap.py                       # V2: SERVING vs TRAINING mode comparison
    schemas/                                 # YAML contracts
        input_schema.yaml                    # Column types + allowed missingness
        context_schema.yaml                  # Context fields + modes
    artifacts/                               # Written by training + calibration
        params.json                          # Data-derived thresholds (S0.2)

scripts/{pipeline_name}/                     # CLI entry points
    run_pipeline.py                          # Orchestrator (daily/rebuild/validate/stage modes)
    run_daily_batch.py                       # Daily inference batch
    stages/
        run_s0_build_data.py                 # Phase 0 runner
        run_s1_build_priors.py               # Phase 1 runner
        run_s2_train_models.py               # Phase 2 runner
        run_s3_engine_test.py                # Phase 3 smoke test
    validation/
        validate_pipeline.py                 # N/N gate check (registry-based)
        generate_daily_report.py             # Daily JSON report (atomic write, 7-day archive)
    calibration/
        calibrate_blend_alpha.py             # Parameter tuning scripts

api/de/basketball/models/
    staging/{pipeline_name}/                 # 1:1 parquet -> view
        stg_{entity_a}.sql
        stg_{entity_b}.sql
    intermediate/{pipeline_name}/            # Business logic joins
        int_{joined_entity}.sql
    marts/{pipeline_name}/                   # Materialized tables
        mart_{product_a}.sql
        mart_{product_b}.sql

models/{pipeline_name}/                      # Trained model artifacts
serving/artifacts/{pipeline_name}/           # Serving-layer dual-save copies
reports/{pipeline_name}/                     # Daily pipeline reports
```

#### 12.1.2 Stage Registry Table Template

Include this table immediately after the Module Tree. It provides a
complete, scannable reference for the pipeline's execution order.

```markdown
## Stage Registry

| Phase | Stage | Name | Output | Dependencies | Gate? |
|-------|-------|------|--------|--------------|-------|
| Governance | S-1 | Upstream Audit | readiness_report.json | None | Blocking |
| Data | S0.1 | Build Training Table | training_table.parquet | S-1 | -- |
| Data | S0.2 | Derive Parameters | params.json | S0.1 | -- |
| Data | S0.3 | Update Recent Form | recent_form.parquet | S0.1 | -- |
| **Gate** | **V0** | **Validate Data** | **Report** | **S0.1, S0.2, S0.3** | **Blocking** |
| Prior | S1.1 | Starter Projections | starters.parquet | V0 | -- |
| Prior | S1.2 | Minutes Targets | minutes.parquet | V0 | -- |
| Train | S2.1 | Train Primary Model | champion.joblib | V0 | -- |
| Train | S2.2 | Train Secondary Model | secondary.joblib | V0 | -- |
| Test | S3 | Engine Smoke Test | -- | S2.1, S2.2 | -- |
| Batch | SIM | Run Daily Batch | results/{date}/ | S1.1, S1.2, S3 | -- |
| dbt | DBT | Refresh Marts | basketball.duckdb | SIM | -- |
| **Gate** | **V1** | **Historical Replay** | **Report** | **S3** | **Informational** |
| Upload | R2 | Upload to R2 | -- | DBT, V0 PASS | -- |
| Report | RPT | Daily Health Report | report.json | All | -- |
```

**Key conventions:**
- Governance (S-1) stages run first and audit upstream data freshness
- Validation gates (V0, V1, ...) are **bold** and marked as Blocking or Informational
- Blocking gates halt the pipeline on failure. Informational gates log but don't block.
- Phase 0 (Data) stages are independent of each other but all depend on S-1
- Phase 1 (Priors) and Phase 2 (Training) both depend on V0 passing
- Phase 3+ depends on trained models from Phase 2
- dbt and R2 upload are always the final stages

### 12.2 Update Navigation

Add the pipeline to `CLAUDE.md`:

- Add to the "Codebase Navigation" table
- Add run commands to "How to Run Things"
- Add validation expectations
- If ML schemas are used, add to the relevant pipeline guide section

### 12.3 Session Log

Add an entry to `DEVELOPMENT_LOG.md`:

```markdown
## Session NNN: {Pipeline Name} Pipeline (YYYY-MM-DD)

### What Was Built
- {Description of pipeline}

### Key Files
- `api/src/pipelines/{pipeline_name}/` -- pipeline code module
- `scripts/{pipeline_name}/` -- CLI scripts
- `data/{pipeline_name}/` -- medallion data layers
- `docs/backend/projects/{PIPELINE_NAME}_SPEC.md` -- spec doc

### Validation
- {N}/{N} PASS
```

### 12.4 Documentation Hygiene for Multi-Session Continuity

A pipeline that is built but not documented for the **next** session is a
half-finished pipeline. The next session — whether you tomorrow, the other
machine's Claude Code session, or a human reviewer — needs to be able to
answer "what is this for, what is broken, what should I not touch?" without
reading the full PR diff.

Every session that ships meaningful work must update these four surfaces.
This is not optional polish — it is what keeps multi-session work from
re-discovering the same bugs.

**Surface 1 — `tasks/lessons.md` (anti-pattern capture)**

Append a new entry whenever:

- The user corrected your approach mid-session.
- You found a non-obvious bug whose root cause is worth remembering.
- A tool/library behaved differently than its docs implied.
- You discovered a constraint that future sessions could easily violate.

Format:

```markdown
## YYYY-MM-DD — {one-line title}

**Symptom:** {what looked wrong}

**Root cause:** {why it was actually wrong}

**Fix:** {what resolved it}

**Rule for next time:** {the actionable preventive rule}

**Files touched:** {paths so future sessions can see the diff}
```

**Surface 2 — `MEMORY.md` (project-state index)**

Add a one-line entry pointing to a topic file when:

- A new pipeline reaches production.
- A long-standing bug pattern is fixed permanently.
- A pipeline's column conventions or status changes (data limitations,
  KNOWN_NULL_STATS, deprecated paths).
- A new operational pitfall is discovered (e.g., uv sync wiping
  sitecustomize.py, an Alembic enum pattern, a Railway import path
  convention).

Keep the index entry under ~200 chars. Move detail into the topic file.
Lines past 200 in `MEMORY.md` are truncated when loaded into context — keep
the index dense.

**Surface 3 — `CLAUDE.md` (codebase navigation)**

Update when:

- A new pipeline is added — add to "Codebase Navigation" table and
  "How to Run Things."
- A new entry-point script is added or renamed.
- A new validation expectation is set (e.g., "validate_gold.py expects
  10/10 PASS"). Stale validation expectations cost the next session 30
  minutes of "is this PASS rate normal?"
- A schema convention or naming rule changes.

`CLAUDE.md` is **the** orientation doc for new sessions on either machine.
A stale `CLAUDE.md` causes the next session to follow yesterday's contract.

**Surface 4 — Pipeline spec doc (`docs/backend/projects/{NAME}_SPEC.md`)**

Update the **Execution Tracker** at the top of the spec to reflect what is
done, what is in progress, and what is next:

```markdown
## Execution Tracker

| Phase | Status | Owner | Last update |
|-------|--------|-------|-------------|
| Bronze ingestion | DONE | desktop scheduler | 2026-04-26 |
| Silver standardization | DONE | desktop scheduler | 2026-04-26 |
| Gold promotion | DONE | desktop scheduler | 2026-04-26 |
| dbt staging models | DONE | both | 2026-04-26 |
| dbt mart models | IN PROGRESS | laptop dev | 2026-04-27 |
| API endpoints | TODO | laptop dev | -- |
| R2 upload wiring | TODO | both | -- |
| DAG unpause | BLOCKED on R2 wiring | -- | -- |
```

A future session reading the spec should be able to answer "what should I
work on next?" from the Execution Tracker alone — without reading prose.

**The non-negotiable closing checklist:**

Before declaring a session complete, verify:

- [ ] `tasks/lessons.md` updated if any correction or non-obvious bug.
- [ ] `MEMORY.md` updated if any new pipeline state, pitfall, or convention.
- [ ] `CLAUDE.md` updated if navigation, run commands, or validation
      expectations changed.
- [ ] Pipeline spec doc's Execution Tracker reflects current state.
- [ ] `DEVELOPMENT_LOG.md` has a session entry (append-only, at session end
      after merging to main per §15).

If any of these is skipped, the next session pays for it. Documentation
hygiene is a multi-session contract, not a personal taste preference.

---

## 13. Reference: Existing Pipelines

| Pipeline | Code Module | Scripts | Data | Spec Doc |
|----------|-------------|---------|------|----------|
| Draft Pick Power | `api/src/pipelines/draft_picks/` | `scripts/nba_prospects/draft_pick_power/` | `data/draft_picks/` | [DRAFT_PICK_POWER_DATA_PIPELINE.md](projects/DRAFT_PICK_POWER_DATA_PIPELINE.md) |
| NBA Draft Prospects | `api/src/pipelines/nba_prospects/draft_prospects/` | `scripts/nba_prospects/nba_draft_prospects/` | `data/nba_prospects/draft_prospects/` | [NBA_PROSPECTS_PIPELINE_FINAL_SPEC.md](projects/NBA_PROSPECTS_PIPELINE_FINAL_SPEC.md) |
| Player Career History (P3c) | (lives within nba_prospects) | `scripts/nba_prospects/nba_draft_prospects/stages/build_player_career_*.py` | `cache/canonical/player_career_history/`, `cache/canonical/player_career_aggregates.parquet` | [NBA_PROSPECTS_PIPELINE_FINAL_SPEC.md](projects/NBA_PROSPECTS_PIPELINE_FINAL_SPEC.md) §P3c |
| G-League Returnees | `api/src/pipelines/nba_prospects/gleague_returnees/` | `scripts/nba_prospects/nba_gleague_nba_returnee_prospects/` | `data/nba_prospects/gleague_returnees/` | [NBA_PROSPECTS_PIPELINE_FINAL_SPEC.md](projects/NBA_PROSPECTS_PIPELINE_FINAL_SPEC.md) (G-League section) |
| NBA Player Value | `api/src/pipelines/nba_value/` | `scripts/nba_value/` | `api/src/airflow_project/data/` | [DATA_PIPELINE_PLAYER_VALUE_FORECASTING.MD](projects/DATA_PIPELINE_PLAYER_VALUE_FORECASTING.MD) |
| XFG | `api/src/pipelines/xfg/` | `scripts/xfg/` | `api/src/airflow_project/data/` | [XFG_FORECASTING.md](projects/XFG_FORECASTING.md) |
| Referee | `api/src/pipelines/referees/` | `scripts/referees/` | `api/src/airflow_project/data/gold/referees/` | [REFEREE_PIPELINE.md](projects/REFEREE_PIPELINE.md) |
| Game Simulation | `api/src/pipelines/simulation/` | `scripts/simulation/` | `api/src/airflow_project/data/gold/simulation/` | [GAME_SIMULATION.md](projects/GAME_SIMULATION.md) |
| Lineup Optimizer | `api/src/pipelines/lineup/` | `scripts/lineup_optimizer/` | `cache/lineups/` | [LINEUP_OPTIMIZER_PIPELINE_SPEC.md](projects/LINEUP_OPTIMIZER_PIPELINE_SPEC.md) |
| Sentiment Analysis | `api/src/pipelines/sentiment/` | `scripts/sentiment_analysis/` | `data/gold/SENTIMENT_ANALYSIS/` | [SENTIMENT_ANALYSIS.md](projects/SENTIMENT_ANALYSIS.md) |
| News Intelligence | `api/src/pipelines/news/` | `scripts/news/` | `data/news/` | [NEWS_INTELLIGENCE.md](projects/NEWS_INTELLIGENCE.md) |

### Pipeline Characteristics

| Pipeline | Stages | Gold Marts | ML Pipelines Used | Validation | R2 Upload Flags |
|----------|--------|------------|-------------------|------------|----------------|
| Draft Pick Power | 4 | 3 | None (ETL only) | 30 | `--draft-gold --skip-core` |
| NBA Draft Prospects | 7 | 5+ | GBDT, Clustering, Survival | 15 | `--boards --skip-core` (daily); + `--models` (rebuild) |
| Player Career History (P3c) | 4 | 2 | None (ETL only) | 8 | `--career-history --skip-core` |
| G-League Returnees | 4 | 3 | GBDT, Survival | 12 | `--prospect-cards --skip-core` |
| NBA Player Value | 15 | 16 | GBDT, Bayesian, Clustering | 28 | `--gold-products` (includes core duckdb) |
| XFG | 3 | 2 | GBDT, Bayesian (zone) | 21 | `--xfg --skip-core` (daily); + `--xfg-models` (rebuild) |
| Referee | 6 | 4 | GBDT | 13 | `--referees --skip-core` |
| Game Simulation | 25+ | 4 | GBDT (5 component models), XFG | 16 | `--sim-data --skip-core` (daily); + `--sim` (rebuild) |
| Lineup Optimizer | 9 | 13 | CatBoost LTR | 43 | `--lineup` |
| Sentiment Analysis | 10 | 3 | Clustering, Embedding | 12 | `--sentiment --skip-core` |
| News Intelligence | 10+ | 2 | Embedding, HDBSCAN, RRF | -- | Not yet wired |

### Template Changelog

| Version | Date | Key Additions |
|---------|------|----------------|
| v2.1 | 2026-04-29 (Session 2026-04-29) | **Section 11.9 added:** DAG operations capacity dashboard standard covering admin DAG table completeness, daily/weekly CPU graphics, weekly GPU graphics, telemetry-derived runtime/cost projection, read-only serving rules, R2 lock safety, and required frontend/backend/docs validation. |
| v2.0 | 2026-04-27 (Session 2026-04-27) | **Multi-machine MLOps refresh.** **§11.1a (new):** R2 vs Local DuckDB vs Railway Postgres data-layer decision tree — defines where reads and writes belong across the desktop scheduler + laptop dev split. **§11.2b (extended):** row-count + manifest delta gate is now mandatory; PUT-200 alone is not proof an upload succeeded. **§8.5.5 (new):** dbt selector vs core upload safety gate — selectors are OK for local validation, never for `basketball.duckdb` R2 publish. **§8.5.6 (new):** incremental run audit checklist — five questions every incremental output must answer (monotonic rows, schema hash, watermark, input hash, no temporal gaps) with reference implementation. **§10.6.1 (new):** cross-pipeline join safety gate — canonical IDs only, named temporal policy, declared upstream freshness, row-count assertion. **§11.8.4 (new):** artifact versioning + rollback contract — dual-save layout, manifest schema, promotion gate, rollback procedure. **§12.4 (new):** documentation hygiene mandate — `tasks/lessons.md`, `MEMORY.md`, `CLAUDE.md`, spec doc Execution Tracker non-negotiable closing checklist. **§15.6 (new):** merge-conflict recipes by file class (append-only logs, lock-file docs, code, generated configs, frozen artifacts). **§16 (new):** Multi-Machine Role Contract — desktop scheduler vs laptop dev role definition, code flow, data flow, manual trigger ownership, scheduler-pause workflow, conflict detection, future CV. **§4.3 (footnote):** offline / degraded-service fallback clarification — distinguishes forbidden data fallbacks from acceptable service-availability behavior. **CLUSTERING_PIPELINE.md:** added Production State addendum (2026-04-27) with current consumers, recent significant changes, validation status, known pitfalls. |
| v1.9 | 2026-04-26 (Session 2026-04-26) | **Section 8.5 tightened:** incremental/cache reuse must be driven by stage-declared freshness SLA, event-date watermark, schema hash, and input hash rather than a hardcoded clock. **Section 8.5.4 added:** parallelism/cache standards for narrow DAG fan-out, dbt selectors, Airflow pools, manifest-backed checkpoints, and the rule that full dbt build before R2 core promotion remains mandatory. **Section 14 expanded:** performance anti-patterns now call out mega-stages, global freshness windows, unchecked caches, partial dbt uploads, and parallel shared writers. |
| v1.8 | 2026-04-22 (Session 2026-04-22) | **Section 14 expanded:** added Package Management anti-patterns table covering uv workflow, version range guidance, numpy serialization boundary, and multi-pyproject.toml discipline. Cross-references §0.12 of DATA_ENGINEERING_PIPELINE.md for the full 4-step guide. |
| v1.7 | 2026-04-18 (Session 2026-04-18) | **Section 11.8 expanded:** added a hard `DAG Ready to Unpause` checklist, a fixed root-cause taxonomy (`scheduler`, `queue`, `claim`, `fetch`, `validation`, `artifact_write`, `promotion`, `gpu_dispatch`, `training`, `serving_refresh`), and a required GPU training contract (`provider`, `backend_proof`, cost/runtime envelope, `trained_on_data_cutoff`, `retrain_reason`). This turns the rollout ladder into a reusable operating procedure instead of a narrative guideline. |
| v1.6 | 2026-04-18 (Session 2026-04-18) | **Section 11.8 (new):** required promotion ladder for new DAGs, GPU retrains, and serving artifacts: plan first, dependency discipline, unit/stage validation, full local DAG run, local serving smoke, staging via `railway up`, production cutover, rollback readiness. **Section 12.1 updated:** pipeline specs now require an `Execution Tracker` and explicit promotion plan so future sessions know what is done and what is left. **Section 15.5 (new):** safe push workflow for multi-session Railway/R2 work; no `git add -A` from a dirty tree, push code before data, one upload owner. |
| v1.4 | 2026-03-20 (Session 524) | **Section 9 rewritten:** Full UNIFIED_SERVING_GUIDE compliance -- sync handler rules, Pydantic response_model, DuckDB parameterized queries, error code standards (404/503), streaming NDJSON for >500 rows, thread-safe caching, champion-challenger + drift detection + artifact integrity, new endpoint checklist. **Section 5.6 (new):** Data leakage prevention & temporal safety -- strict `< cutoff` rule, stage ordering enforcement, temporal CV mandate, cross-pipeline leakage prevention, 6-point gate checklist. **Section 4.3 expanded:** Data-derived decisions callout (no hardcoded thresholds, no fake values/fallbacks, no silent error swallowing). **Section 12.1 expanded:** Module tree template (40+ files with stage IDs) and stage registry table template (16 columns). **Section 13 expanded:** Added 5 missing pipelines (Referee, Game Simulation, Lineup Optimizer, Sentiment Analysis, News Intelligence) to reference tables. |
| v1.3 | 2026-03-19 (Session 523) | **Section 11 (new), Section 7.2 (new):** R2 artifact promotion as standard pipeline step -- architecture overview, upload_data.sh integration, Railway bootstrap & hot-reload, local vs R2 classification, verification workflow, manual override, new pipeline checklist. DAG upload_fn wiring pattern with --skip-core convention and per-pipeline flag table. R2 anti-patterns added to Section 14. |
| v1.1 | 2026-03-03 (Session 366) | **Sections 8.4 & 8.5:** Daily pipeline report pattern (atomic writes, 7-day archive, JSON structure) and incremental mode implementation for fast daily runs (skip-if-fresh, append-only stages). See [Section 8.4](#84-daily-pipeline-report-session-366-pattern) and [Section 8.5](#85-incremental-mode-pattern-for-daily-pipelines). |
| v1.2 | 2026-03-06 (Session 471) | **Sections 8.6-8.10:** Daily vs event-driven cadence matrix, fail-fast gate chain contract (blocking chain + rich Airflow exception), LKG snapshot before Gold writes, secondary bridge DAG pattern (staleness-gated weekly), API refresh chain after pipeline completion (POST /admin/reload + GET /health smoke check). |
| v1.0 | 2026-03-02 (Session 364) | Initial template with full medallion architecture, ML pipeline decision tree, and 10-step implementation checklist |

---

## 14. Anti-Patterns

These are standing rules. Violating them will cause data corruption or silent
model degradation.

### Data Quality

| Anti-Pattern | Why It's Bad | Do This Instead |
|-------------|-------------|-----------------|
| `.fillna(0)` | Hides missing data, biases ML models | Let NaN propagate -- it is signal |
| `.fillna(1.0)` on multipliers | Silently neutralizes adjustment factors | Use explicit `np.nan` -- downstream multiplies NaN correctly |
| `df.to_dict(orient="records")` returned directly from an endpoint | Raw `NaN` / `pd.NA` / `NaT` can break FastAPI JSON rendering | Normalize with `serialize_dataframe_records(...)` or typed Pydantic models |
| `pd.DataFrame.prod(skipna=True)` | Treats NaN as 1.0 in product chains | Use explicit `a * b * c` multiplication |
| `except: pass` | Silences real errors | Narrow the exception type, log warnings |
| `except Exception: return default` | Returns plausible-looking wrong values | Let the error propagate, fix the root cause |
| Merge on `PLAYER_NAME` across pipelines | Creates cartesian products (name collisions) | Use `SOURCE_PLAYER_ID` -> `CANONICAL_PLAYER_ID` |

### ML

| Anti-Pattern | Why It's Bad | Do This Instead |
|-------------|-------------|-----------------|
| No `forbidden_features` | Model learns from target components (leakage) | Define forbidden list per target in YAML |
| Including continuous outcome variable as feature | AUC=1.0 trivially — model predicts the label from itself (e.g., `SHOT_VALUE=0/2/3` when target is `SHOT_MADE_FLAG`). Single-feature SHAP dominance is the signal. | Audit ALL columns for derivability from the target; add them to `forbidden_features` |
| Audit stage `run()` returns `None` on success | `sys.exit(0 if result else 1)` evaluates `bool(None) == False` → always exits 1 (failure). Orchestrators silently abort every stage. | `run()` must return `True` on success, `False` on failure. Never return `None`. |
| Reading from silver for ML | Silver has pre-correction data | Always read from gold |
| `fillna(0)` before ML training | Median imputation is better; NaN has meaning | Use `native_nan` for XGBoost, median for sklearn |
| Same `random_state` across folds | Temporal CV must respect time ordering | Use expanding/walk-forward splits |
| Modifying bronze data | Breaks reproducibility | Bronze is immutable -- fix in silver/gold promotion |

### Performance and Caching

| Anti-Pattern | Why It's Bad | Do This Instead |
|-------------|-------------|-----------------|
| One mega-stage that ingests, transforms, trains, validates, and uploads | Serializes the whole pipeline and hides the failing boundary | Split into numbered stages with disjoint outputs, validation gates, and Airflow tasks |
| Global `<24h` freshness checks | Offseason, replay, settlement, and live-game data have different expected watermarks | Use stage-declared freshness SLA plus max event date / partition coverage from the output manifest |
| Reusing a parquet cache without schema/input hash validation | Silent upstream drift can look like a speedup while serving stale or incompatible data | Store row counts, schema hash, input hash, producer version, and min/max event date with every reusable checkpoint |
| `dbt build --select state:modified+` followed by core R2 upload | A partial DuckDB can overwrite live tables for domains outside the selector | Use selectors for local/staging validation only; let `scripts/upload_data.sh` run the full dbt build before publishing `basketball.duckdb` |
| Parallel tasks writing the same DuckDB file or R2 manifest | Race conditions corrupt locks, manifests, or table contents | Fan out only disjoint writers; serialize shared DuckDB and R2 promotion through pools/locks |
| Raising Airflow concurrency to compensate for non-idempotent code | Makes intermittent data loss harder to reproduce | Make stages idempotent first, then raise concurrency with documented pools and resource limits |
| Capacity dashboards with fixed CPU/GPU price defaults or guessed schedules | Operators see plausible but false headroom/costs | Derive runtime/cost from telemetry or operator inputs; leave unknown cadence/rates unavailable |

### Package Management

| Anti-Pattern | Why It's Bad | Do This Instead |
|-------------|-------------|-----------------|
| `pip install <pkg>` without updating `pyproject.toml` | Package disappears on next `uv sync` | `uv pip install <pkg>` → add range to `pyproject.toml` → `uv sync` |
| Bare `>=X.Y` with no upper bound for ML libraries | PyMC, NumPyro, CatBoost all have breaking minor versions | Use `>=X.Y,<X+1.0` for most; pin exactly (`==X.Y.Z`) only when load-bearing |
| Adding to root `pyproject.toml` only when API also uses it | Serving import fails on Railway boot | Update both root and `api/pyproject.toml` for Railway-serving packages |
| Mismatched numpy major version between training and serving | `numpy._core` paths in pickled arrays change between 1.x and 2.x — deserialization fails silently | Lock numpy to the same major version (`<2.0`) in both root and `api/pyproject.toml` |
| Importing a package not declared in `pyproject.toml` | Works locally until the next `uv sync` in a clean env | Always commit `pyproject.toml` change alongside the code that imports the package |

**Full workflow**: see [DATA_ENGINEERING_PIPELINE.md §0.12](engineering/DATA_ENGINEERING_PIPELINE.md#012-package-management-standard) for the complete 4-step process and version range guidance table.

### Architecture

| Anti-Pattern | Why It's Bad | Do This Instead |
|-------------|-------------|-----------------|
| Cross-pipeline data sharing | Tight coupling, breaking changes propagate | Join only in dbt analytical layer |
| Hardcoded absolute paths | Breaks on different machines | Use `Path(__file__).resolve().parents[N]` |
| Logic in DAG files | Hard to test, debug, and reuse | DAGs are thin wrappers -- logic in scripts |
| Writing new ML code for existing domains | Duplicate logic, divergent behavior | Add YAML schema config, not Python code |
| Threshold-gated validation | Arbitrary thresholds break on data growth | Data-descriptive validation -- report, don't gate |
| Deploying pipelines to Railway | stats.nba.com blocks cloud IPs; GPU not available | All pipelines run locally, promote artifacts via R2 |
| Assuming a datascience-container retrain used CUDA | Environment drift can silently fall back to CPU | Log actual backend/device list in the run and fix the env before calling it GPU-backed |
| Uploading to R2 without validation gate | Corrupted data reaches production serving | Always pass validation gate before `upload_data.sh` |
| Re-uploading basketball.duckdb from every DAG | Wastes bandwidth (~51 MB per upload) | Use `--skip-core` on per-pipeline DAGs; only nba_value uploads core |
| Using Railway Volumes for serving artifacts | Blocks replica scaling | Use Railway Buckets (S3-compatible); each replica downloads locally |
| Skipping manifest.json on upload | Railway can't detect version changes; no hot-reload | `upload_data.sh` always writes manifest with sha256 + rollback pointer |
| Pushing every commit to `main` | Each push triggers Railway build (~3-5 min), wastes credits | Work on `session/{topic}` branch, merge to main once per batch |
| Multiple sessions editing same file | Merge conflicts, lost changes | Claim file ownership per session (see Section 15) |
| Running `upload_data.sh` concurrently | DuckDB lock errors, wasted bandwidth | Sequential uploads -- wait for previous to finish |
| Removing an R2 advisory lock because an upload looks stuck | Can allow two writers into the shared production artifact store | Wait for the lock to finish or diagnose the owning process; never delete the lock manually |
| Feeding admin DAG/runtime telemetry into model training | Operational metadata leaks future process state into forecasts | Keep DAG observability read-only and out of modeling feature frames |
| Updating `DEVELOPMENT_LOG.md` mid-session | Guaranteed merge conflict with parallel sessions | Append only at session end, after merging to main |
| Force-pushing to `main` | Rewrites shared history, loses other sessions' commits | Always `git merge`, resolve conflicts normally |
| `git add -A` or `git add .` | Stages cache files, secrets, unrelated changes | Stage specific files: `git add {file1} {file2}` |

---

## 15. Multi-Session Development Standards

When multiple Claude Code sessions (or developers) work on this codebase simultaneously,
follow these rules to avoid wasted Railway builds, merge conflicts, and DuckDB corruption.

> **Full reference**: `docs/frontend/RAILWAY_DEPLOYMENT_GUIDE.md` Section 21

### 15.1 Branch Strategy

Each session works on its own branch. `main` is the deploy branch.

```bash
git checkout main && git pull origin main
git checkout -b session/{topic}
# ... work and commit freely ...
git checkout main && git pull origin main
git merge session/{topic}
git push origin main    # ONE Railway build for the entire session
git branch -d session/{topic}
```

### 15.2 File Ownership

Sessions claim non-overlapping domains to avoid conflicts:

| Domain | Frontend | Backend | Scripts |
|--------|----------|---------|---------|
| XFG | `XFG*` components | `xfg_endpoints.py` | `scripts/xfg/` |
| Simulation | `simulation/` components | `sim_endpoints.py` | `scripts/simulation/` |
| Prospects | `NBADraft*` components | `prospect_endpoints.py` | `scripts/nba_prospects/` |
| Lineups | `Lineup*` components | `lineup_endpoints.py` | `scripts/lineup_optimizer/` |
| Sentiment | `Sentiment*` components | `sentiment_endpoints.py` | `scripts/sentiment/` |
| Referees | `Referee*` components | `referee_endpoints.py` | `scripts/referees/` |
| Player Value | `PlayerValue*` components | `nba_data_endpoints.py` | `scripts/nba_value/` |

**High-conflict files** (one session at a time): `DEVELOPMENT_LOG.md`, `CLAUDE.md`,
`web/src/services/api.js`, deployment docs.

### 15.3 DuckDB Upload Coordination

All 9 pipeline domains share ONE `basketball.duckdb`. `upload_data.sh` runs a full
`dbt build` before every upload, so no data is lost regardless of which pipeline ran
last.

**Rules:**

1. **Never run two `upload_data.sh` instances simultaneously.** DuckDB file lock
   prevents corruption (second session aborts), but concurrent uploads waste bandwidth.
2. **Upload order does not matter.** Every upload includes all 9 domains.
3. **Push code first, then upload data.** Railway redeploys on push; the new container
   bootstraps from R2. Uploading before pushing means old container code may not know
   about new schemas.

### 15.4 Quick Checklist

```
[ ] Branch from main: git checkout -b session/{topic}
[ ] Claim your file domain (no overlaps with other sessions)
[ ] Commit to branch, not main
[ ] Merge to main only when batch is complete
[ ] Push once (= one Railway build)
[ ] Upload data sequentially (wait for prior upload to finish)
[ ] Append DEVELOPMENT_LOG.md at session end only
```

### 15.5 Safe Push Workflow

Use this when multiple sessions are active and the change touches Railway- or
R2-backed behavior:

```bash
git checkout main
git pull --rebase origin main
git checkout session/{topic}
git rebase main
git status --short
git diff --stat origin/main
git add path/to/file_a path/to/file_b   # stage specific files only
git commit -m "Describe the batch clearly"
git checkout main
git merge session/{topic}
git push origin main
```

Rules:
- Stage specific files; do not use `git add -A` from a dirty tree.
- Push code before data so Railway boots code that understands the new
  artifact/schema.
- Let exactly one session own the production `upload_data.sh` call.

### 15.6 Merge Conflict Recipes (by File Type)

Two sessions editing the same file is the only Git failure mode that
matters in this repo. Resolve by **file class**, not by reflex `git push -f`.
Force-push to a shared branch destroys the other session's work and is never
the answer.

**Step 0 (every conflict, every time):**

```bash
git fetch origin
git pull --rebase origin main          # pull remote first; do not push first
git status                              # see what conflicts
```

| File class | Examples | Conflict pattern | How to resolve |
|------------|----------|------------------|----------------|
| **Append-only logs** | `DEVELOPMENT_LOG.md`, `tasks/lessons.md`, `tasks/todo.md` | Both sessions appended a new section at the bottom | Keep BOTH sections in chronological order. Never `--ours` or `--theirs` blindly — both sessions' notes are signal. Re-order by timestamp if needed. |
| **Single-section-per-topic indexes** | `MEMORY.md`, `CLAUDE.md` (Codebase Navigation table, Pipeline list) | Both sessions added a new row to a list/table | Keep BOTH rows. Re-sort the list (alphabetical for files, chronological for changelog) so future conflicts collide on the sort, not the content. |
| **Lock-file-style docs** | Spec docs with an `Execution Tracker` checklist (`NBA_PROSPECTS_PIPELINE_FINAL_SPEC.md`, etc.) | One session checked off `[ ] -> [x]`, the other rewrote a stage description | Manually merge: keep the checkbox state from whichever session actually completed the work, keep the prose from whichever session improved the description. Verify with the session author if both edits look load-bearing. |
| **Code (Python, SQL, JSX)** | Pipeline scripts, dbt models, React components | Two sessions edited overlapping lines | Inspect both sides. Re-run unit tests on the merged result before committing. **Do not** accept a side without reading the other side's intent — the diff is what the conflict marker shows; the intent is what the commit message + spec doc explains. |
| **Generated/declarative configs** | `pyproject.toml`, `dbt_project.yml`, `airflow_settings.yaml` | Both sessions added a dependency or DAG entry | Keep both entries. Re-run `uv sync` (or `dbt parse`) on the merged file before committing. If versions conflict, take the **stricter** range (lower upper bound, higher lower bound) and document why. |
| **Frozen artifacts** | `manifest.json`, `serving/artifacts/champion/*.joblib`, `cache/models/registry.json` | Both sessions trained / regenerated | DO NOT manually merge. The model artifact whose `trained_on_data_cutoff` is later wins. Re-train if both are stale. Update `previous_version` in the new manifest to point to the loser so rollback works. |

**Recipe for "I rebased and got 14 conflicts":**

```bash
# 1. Abort if confused; nothing has been pushed yet
git rebase --abort

# 2. Look at what each side changed
git log --oneline origin/main..HEAD          # your unpushed commits
git log --oneline HEAD..origin/main          # commits from the other session

# 3. If the other session's commits are mostly disjoint from yours,
#    rebase one commit at a time so each conflict is small:
git rebase -i origin/main                     # then 'p' (pick) each commit in turn

# 4. If the conflict surface is genuinely overlapping (same function,
#    same dbt model), STOP. Open a second shell, talk to the other
#    session author, and decide who owns the change. Then squash one
#    side into the other rather than mechanically merging.
```

**Recipe for "I just pulled and `MEMORY.md` exploded":**

```bash
git checkout --theirs MEMORY.md              # take the remote version first
# Read both versions side-by-side:
git show :3:MEMORY.md > /tmp/theirs.md
git show :2:MEMORY.md > /tmp/ours.md
diff /tmp/ours.md /tmp/theirs.md
# Hand-merge in your editor; keep BOTH sets of new entries, re-sort.
git add MEMORY.md
git rebase --continue
```

**Negative rules (never do these in a conflict):**

- Never `git checkout --ours <file>` on `DEVELOPMENT_LOG.md`, `MEMORY.md`,
  `CLAUDE.md`, or any append-only doc — you will silently delete the other
  session's notes.
- Never `git push --force` (or `--force-with-lease`) to `main` to "fix"
  a conflict. The conflict means the other session has work you have not
  read yet. Read it, integrate it, then push.
- Never resolve a conflict in a model artifact (`*.joblib`, `*.parquet`,
  `manifest.json`) by accepting one side. Re-run the producing pipeline.
- Never `git rebase --skip` past a conflict you don't understand. Skipping
  drops your commit silently.
- Never resolve a conflict by deleting the conflict markers and one side's
  content without reading what that content was for.

**Pre-commit defense in depth:**

- `git status --short` before every commit. If you see files you did not
  intend to stage, unstage them: `git restore --staged <file>`.
- `git diff --cached` before every commit. The 30 seconds you spend
  reading the staged diff catches 90% of "wait, why is that staged?" bugs.
- For DAG / serving / R2-touching files, `git diff --stat origin/main`
  before pushing — confirm the blast radius matches your intent.

---

## 16. Multi-Machine Role Contract (Desktop Scheduler + Laptop Dev)

This repo runs across two physical machines that contribute to the same
Cloudflare R2 production bucket and the same Railway services. The two
machines have **different jobs** and **different write boundaries**. Treating
them as interchangeable is the fastest way to clobber data, double-run a DAG,
or upload a stale `basketball.duckdb` over a fresh one.

> **Canonical doc**: the full enforced contract — env-var gates, mirror model,
> promotion flow, per-pipeline run-location, ownership matrix, emergency-writer
> switch — lives in
> [engineering/LOCAL_FLEET_R2_WORKFLOW.md](engineering/LOCAL_FLEET_R2_WORKFLOW.md).
> §16.1–16.8 below are the narrative; §16.9–16.12 are the enforced summary.
>
> **The hard rule (enforced, fail-closed):** the **desktop** is the production
> orchestrator and the **only** production R2 writer; the **laptop** is the
> dev/training/frontend lane, **read-only** from production R2, writing only to
> local `.r2_staging`. A capability is **denied unless its `BETTS_CAN_*` flag is
> `1`** — unset means denied. See §16.9.

### 16.1 Role Definition

| Machine | Role | Owns | Never does |
|---------|------|------|-----------|
| **Desktop** (always-on, RTX 4090) | **Production runner**: Airflow scheduler + workers, scheduled DAGs, GPU training, future computer-vision ingestion | Scheduled R2 uploads (DAG-driven), GPU retrains, long-running fetches, CV pipelines | Interactive code editing on `main`, ad-hoc destructive R2 commands, frontend development |
| **Laptop** (mobile, dev box) | **Author**: code edits, pipeline design, validation, ad-hoc backfills, frontend dev | `git push` to `main`, `uv pip install`/`pyproject.toml` edits, manual one-off DAG triggers (paused) | Running scheduled DAGs, owning GPU training, long-running CV jobs |

The roles are **not** "who can do X." They are "who is **responsible** for X."
Either machine *can* run any command; only one is *responsible* for it on a
given day. Cross the line only with explicit reason.

### 16.2 The Code Flow (Laptop -> GitHub -> Desktop)

```
LAPTOP                    GITHUB main                DESKTOP
+-------------+           +-------------+            +-------------------+
| edit code   |  push     | source of   |  pull on   | airflow-scheduler |
| run tests   | -------->|  truth      | --------->|  picks up new DAG  |
| validate    |           | for code    | poll/cron  | code on next tick  |
+-------------+           +-------------+            +-------------------+
```

**Rules:**

1. **Laptop pushes; desktop pulls.** Laptop is the writer for `main`;
   desktop is a reader. Desktop only pushes for two cases: (a) DAG run output
   files that are tracked in git (rare — most outputs are gitignored), and
   (b) emergency hotfixes when laptop is unavailable.
2. **Desktop pulls before every scheduled DAG run.** The Airflow DAG `git_sync`
   task (or equivalent cron) runs `git pull --ff-only origin main` before the
   day's first scheduled DAG. This guarantees the desktop runs the latest
   pipeline code, not yesterday's.
3. **Branch-per-session, even on the same machine.** If the desktop needs to
   push a hotfix, it does so on `session/desktop-hotfix-YYYY-MM-DD`, opens a
   PR (or fast-forward merges), and never edits `main` directly.

### 16.3 The Data Flow (Desktop -> R2 -> Both)

```
DESKTOP                 CLOUDFLARE R2              LAPTOP
+--------------+        +-----------------+        +--------------+
| scheduled    |  push  | basketball.     |  pull  | duckdb       |
| DAG produces | -----> |  duckdb +       | -----> | analysis,    |
| gold parquets|  via   |  manifest +     | ad-hoc | testing, dev |
|              | upload | per-pipeline    |        |              |
| RAILWAY also |  data  | parquets        |        |              |
| reads from R2|  .sh   |                 |        |              |
+--------------+        +-----------------+        +--------------+
```

**Rules:**

1. **Desktop is the default R2 writer.** Scheduled DAGs on the desktop call
   `upload_data.sh` automatically. The laptop only writes to R2 for **manual
   backfills** (rare) or when the desktop is offline (emergency).
2. **The R2 lock makes both machines safe-by-construction.** If the laptop
   tries to upload while a desktop DAG is mid-write, the laptop sees the lock
   and aborts. Wait for the desktop DAG to finish; never delete the lock.
   See §11.2a for the full lock protocol.
3. **Both machines pull from R2 freely.** Read access is unrestricted — laptop
   pulls the latest `basketball.duckdb` for analysis, desktop pulls when a
   DAG needs upstream gold from a different pipeline. Reads do not need
   coordination.
4. **No machine ever queries Railway Postgres for analytical data.** Railway
   Postgres is for live OLTP state (auth, geo-social events). Analytical
   reads go to R2 + DuckDB.

### 16.4 Manual DAG Triggers — Who and When

| Action | Who runs it | Why |
|--------|-------------|-----|
| Scheduled daily/weekly DAG run | Desktop Airflow scheduler | This is what the desktop is for |
| Manual one-off DAG trigger after a code change | Laptop, with the DAG **paused** on desktop's scheduler first | Avoid the scheduler firing the same DAG mid-test |
| Backfill (re-run N days/seasons of history) | Either machine, but with the DAG **paused** during the backfill | Backfills can take hours; do not let the scheduler interleave |
| GPU retrain triggered by data cutoff | Desktop (the GPU lives there) | Laptop has no GPU |
| Hotfix re-run after a failed DAG | Whichever machine fixed the bug | But push the fix to `main` first; do not run from a dirty tree |
| Frontend smoke test against new artifacts | Laptop | Frontend dev lives on the laptop |

**Never do this:** trigger the same DAG manually from the laptop while the
desktop scheduler is also about to fire it. Pause the DAG on desktop first,
run the manual trigger, verify, unpause.

### 16.5 Pausing the Scheduler When You Edit Pipeline Code

When the laptop is editing pipeline code that the desktop scheduler is going
to import on its next tick, **pause the affected DAG on the desktop's Airflow
UI before pushing breaking changes.** Otherwise the next scheduled run picks
up partially-merged code and fails (or worse, succeeds against a half-broken
schema).

```text
1. Laptop:   git checkout -b session/refactor-xfg-stage-3
2. Laptop:   edit code, run unit tests locally
3. Desktop:  pause `xfg_pipeline` DAG via Airflow UI
4. Laptop:   git push, then merge session branch into main
5. Desktop:  git pull --ff-only origin main
6. Laptop or Desktop: airflow dags trigger xfg_pipeline (manual run)
7. Verify the manual run passes end-to-end
8. Desktop:  unpause `xfg_pipeline` DAG
```

This is the "edit-pipeline-code" version of the §11.8 promotion ladder. The
ladder is for new pipelines; this is for changing existing ones.

### 16.6 Conflict Detection and Recovery

If you suspect the two machines are out of sync (desktop DAG is failing on
code the laptop pushed an hour ago, or laptop pulled an R2 manifest that
doesn't match what the desktop just uploaded), use these read-only checks
before taking action:

```bash
# On both machines: are they on the same git SHA?
git rev-parse HEAD
git log --oneline -5

# On both machines: what does R2 think is live?
curl -s "$BUCKET_URL/manifest.json" | jq '.version, .git_sha, .written_at'

# On the desktop only: what did Airflow do in the last 24h?
docker exec betts_basketball-airflow-scheduler-1 \
    airflow dags list-runs --start-date $(date -d '1 day ago' -u +%FT%TZ) | head -30

# On the desktop only: is anything currently uploading?
ps aux | grep upload_data
```

If the manifest's `git_sha` doesn't match either machine's `HEAD`, **someone
ran an upload from a stale tree.** Diagnose (do not auto-fix):

- If the laptop is ahead of `main` and uploaded from an unmerged branch ->
  merge the branch first, then re-upload from `main`.
- If the desktop pulled an old SHA before its scheduled run -> push a no-op
  commit, force the desktop to re-pull, then re-upload from the desktop.

**Never** "fix" a sync issue by deleting the R2 lock or by force-pushing.
Both make the problem worse.

### 16.7 Computer Vision (Future)

When CV pipelines come online they live on the desktop only — they need the
GPU and they pull large video assets that the laptop should not be syncing.
CV outputs (frame-level events, court-coordinate annotations) follow the
same medallion + R2 contract: bronze (raw frames or detections, immutable,
desktop-local) -> silver (standardized event schema) -> gold (per-game
parquets) -> R2 promotion via `upload_data.sh --cv` (or a dedicated CV flag).
Laptop does **not** run CV inference — it pulls the gold parquets from R2 for
analysis only.

### 16.8 Quick Cheatsheet

| If you are about to ... | First check ... | Then ... |
|-------------------------|-----------------|---------|
| Push code | `git status --short`, `git pull --rebase`, `git diff --cached` | `git push origin main` (laptop) or open PR (desktop hotfix) |
| Run a DAG manually | Is the scheduler about to fire it? Pause it first. Is another session running it? | `airflow dags trigger {dag_id}` |
| Upload to R2 | Is `upload.lock` present? Is a DAG currently in `upload_fn`? | `bash scripts/upload_data.sh --dry-run --skip-core --{flag}` first |
| Edit a pipeline's code | Will the next scheduled run break? | Pause the DAG on the desktop, push, pull on desktop, manual trigger, unpause |
| Add a Python package | Will it work in `uv sync` on both machines? | `uv pip install <pkg>` -> add range to `pyproject.toml` -> `uv sync` -> commit `pyproject.toml` -> pull + `uv sync` on the other machine |
| Train a GPU model | Are you on the desktop? | Yes -> proceed via datascience container. No -> ssh to desktop or schedule via Airflow GPU dispatch |

### 16.9 Enforced Env-Var Role Contract

§16.1–16.8 describe responsibilities; this is how they are **enforced**. Each
machine declares its lane in its repo-root `.env`. The flags are **fail-closed**:
a capability is denied unless its flag is exactly `"1"`.

| Env var | Desktop | Laptop | Gate |
|---|---|---|---|
| `BETTS_MACHINE_ROLE` | `production_orchestrator` | `dev_laptop` | informational label |
| `BETTS_CAN_RUN_PROD_DAGS` | `1` | `0` | scheduled `daily`/`rebuild` DAG runs |
| `BETTS_CAN_WRITE_PROD_R2` | `1` | `0` | real `upload_data.sh` writes |
| `BETTS_CAN_MAKE_PAID_PROVIDER_CALLS` | `1` | `0` | billed Odds API calls |
| `BETTS_DEFAULT_ARTIFACT_LANE` | `prod` | `dev` | default output namespace |

Enforcement points:

- `scripts/upload_data.sh` — bash write-guard (reads `BETTS_CAN_WRITE_PROD_R2`
  after the root `.env` autoload), runs **before** `acquire_r2_lock`. `--dry-run`
  is exempt so any machine can preview.
- `api/src/airflow_project/utils/machine_role.py` — Python guards
  (`assert_can_run_prod_dags`, `assert_can_write_prod_r2`,
  `assert_can_make_paid_provider_calls`), fail-closed with actionable messages.
- `_base_three_mode_dag.py::_wrap_with_prod_dag_guard` — gates scheduled
  `daily`/`rebuild` callables at runtime (not parse time; never breaks DAG
  parsing fleet-wide). `validate`/`stage`/`backfill` stay ungated.
- `theoddsapi_client._request()` — gates every billed Odds API call (composed
  with the credit-budget cap).
- `docker-compose.nba-airflow.yml` — bakes `${BETTS_*:-0}` into the container env;
  an unconfigured machine defaults to the **safe (denied)** posture.

**Set the flags in BOTH env files.** `scripts/upload_data.sh` reads the **root
`.env`**; the Airflow scheduler/worker **containers** read
`api/src/airflow_project/.env` (it is the compose `--env-file` *and* the injected
`env_file:`). The DAG + paid-Odds guards run inside the container, so the vars must
be present in `api/src/airflow_project/.env` too. After changing them, **recreate
the containers and verify** `docker exec betts_basketball-airflow-scheduler-1
printenv | grep BETTS_`.

**Rollout is fail-closed (mandatory order):** configure BOTH `.env` files on the
desktop (caps=1) and laptop (caps=0) **before** merging the guards; recreate +
verify the container env; run `python scripts/ops/fleet_preflight.py --station
{desktop|laptop}`; then merge via the §16.5 pause→push→pull→trigger→unpause ladder.
See LOCAL_FLEET_R2_WORKFLOW §3/§10.

### 16.10 Local Mirror / Staging Model (.r2_mirror, .r2_staging)

Local working trees on the two machines **legitimately differ** — do not force
them to be identical. Sync from R2, never peer-to-peer.

```
repo/
  data/ , cache/                  # local working outputs; MAY differ per machine
  .r2_mirror/prod/                # READ-ONLY hydrated production snapshot (gitignored)
  .r2_staging/<machine>/<run_id>/ # dev/candidate artifacts; NEVER served/promoted (gitignored)
```

Read-only tooling (never writes R2, never touches `upload.lock`):

```bash
python scripts/ops/sync_from_r2_manifest.py --manifest-only
python scripts/ops/sync_from_r2_manifest.py --domains boards models --verify-checksums
python scripts/ops/compare_local_to_r2_manifest.py --local .r2_mirror/prod --json
```

The R2 **manifest is the conflict tiebreaker**: if R2 has it, it is production
truth; desktop-only = production candidate; laptop-only = dev candidate, never
production; if neither matches the manifest, stop and reconcile.

### 16.11 Per-Pipeline Run-Location

Production R2 upload is **always** desktop-only. Candidate training/dev may run on
the laptop (writes `.r2_staging`); champion promotion happens on the desktop.

| Pipeline | Laptop may | Desktop owns |
|---|---|---|
| **ODDS** | contract edits, frontend, local validation | daily/rebuild, paid pulls, R2 upload |
| **PGP** | candidate training | daily inference, champion promotion, prediction-cache upload |
| **Sportsbook** | frontend filters, candidate B12–B16 | daily products (after ODDS+PGP), R2 upload |
| **CV** | assigned experiments only | production/review, R2 promotion |

Full matrices: LOCAL_FLEET_R2_WORKFLOW §6.

### 16.12 Upload Preflight + Writer Ownership

Before any real R2 write:

- [ ] `BETTS_CAN_WRITE_PROD_R2=1` on this machine (else run on the desktop)
- [ ] `git status` inspected; intended SHA
- [ ] No `upload.lock` held; no active `upload_data.sh`
- [ ] `--dry-run` already run for the same domain set
- [ ] Validation report fresh + PASS for the changed pipeline
- [ ] Exact domain flags only (`--skip-core` unless a core duckdb rebuild is intended)

The live writer record (current writer, emergency-switch log, rollback manifest)
is [`ops/production_writer.md`](../../ops/production_writer.md). Update it on any
writer change.
