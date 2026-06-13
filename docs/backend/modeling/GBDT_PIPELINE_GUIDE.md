# GBDT Pipeline Guide

**Self-contained, schema-driven Gradient Boosted Decision Tree pipeline for NBA analytics.**

Version 1.5 | February 2026

> **Lane note (two-machine fleet):** candidate GBDT training/Optuna sweeps may run
> on the dev laptop (outputs → `.r2_staging`), but **champion promotion and R2
> upload happen from the desktop production writer only**. See
> [../engineering/LOCAL_FLEET_R2_WORKFLOW.md](../engineering/LOCAL_FLEET_R2_WORKFLOW.md).

---

## Module Tree

```
api/src/ml/modeling/gddt/
├── __init__.py                              Exports: GDDTConfig, GDDTModel, GDDTTrainer
├── config.py                                Backward-compat shim → config/pipeline_config.py
├── model.py                                 Unified XGBoost/LightGBM/CatBoost wrapper
├── trainer.py                               Core orchestrator: legacy 6-step + new 11-stage pipeline
├── main_non_cli.py                          Entry point — edit variables, then run
│
├── config/                                  SELF-CONTAINED configuration (no Bayesian imports)
│   ├── __init__.py                          Re-exports all config symbols
│   ├── pipeline_config.py                   GDDTConfig dataclass (42 fields)
│   ├── schema.py                            GBDTSchemaConfig, ColumnCategory enum, YAML loading
│   ├── gbdt_config.py                       Paths, temporal columns, filter registry, data loading
│   └── schemas/
│       ├── gbdt_master_schema.yaml          20 targets + forbidden_features + task config
│       └── gbdt_player_game.yaml            Column types for PLAYER_GAME granularity
│
├── eda/
│   ├── __init__.py
│   └── eda.py                               GBDTEDAAnalyzer → EDADecisions
│
├── preprocessing/
│   ├── __init__.py
│   ├── preprocessor.py                      Schema-driven preprocessing + drift monitoring
│   ├── feature_selector.py                  Single-strategy feature selection (legacy)
│   └── ensemble_feature_selector.py         Multi-method ensemble selection via RRF
│
├── calibration/
│   ├── __init__.py
│   └── model_zoo.py                         Optuna tuning + multi-model comparison + stacking
│
├── diagnostics/
│   ├── __init__.py
│   ├── diagnostics.py                       SHAP, cross-validation, residuals, conformal intervals
│   └── champion_challenger.py               Promotion logic + dual-save versioning
│
├── serving/
│   ├── __init__.py
│   ├── predictor.py                         Champion loading, inference, drift detection
│   └── api.py                               GBDTAPI class for REST endpoints
│
├── utils/
│   ├── __init__.py
│   ├── dataset_registry.py                  DatasetSpec + DatasetRegistry (dataset abstraction)
│   ├── schema_generator.py                  Auto-generate YAML schema from DataFrame
│   ├── reporter.py                          Markdown pipeline report
│   ├── pipeline_checkpoint.py               Stage-level checkpointing
│   └── scheduler.py                         Cron-compatible retraining triggers
│
└── tests/
    ├── __init__.py
    └── test_gbdt_pipeline.py                25 tests covering full pipeline
```

**API Router:** `api/app/routers/gbdt_endpoints.py` — 6 FastAPI endpoints

---

## Module Purposes

### Core Engine

| Module | Purpose |
|--------|---------|
| **model.py** | Unified wrapper around XGBoost, LightGBM, and CatBoost. Provides a single interface for `train()`, `predict()`, `get_feature_importance()`, `save()`, and `load()` regardless of which library is underneath. Supports both regression and classification. |
| **trainer.py** | The main orchestrator. Has two entry points: `run_pipeline()` (legacy 6-step, backward compatible) and `run_full_pipeline()` (new 11-stage, schema-driven, self-contained). The full pipeline handles dataset resolution, schema validation, data loading, filtering, EDA, preprocessing, Optuna tuning, model zoo comparison, training, diagnostics, champion/challenger promotion, and artifact saving. |
| **main_non_cli.py** | Entry point for running the pipeline. Configuration is done by editing Python variables at the top of the file (not a CLI). Supports single-target and ALL_TARGETS modes. |

### Configuration Layer

| Module | Purpose |
|--------|---------|
| **config/pipeline_config.py** | `GDDTConfig` dataclass with 42 fields controlling every aspect of the pipeline. All new fields default to `False`/`None` for backward compatibility with the legacy pipeline. |
| **config/schema.py** | GBDT's own schema module, independent of the Bayesian pipeline. Defines `ColumnCategory` enum (ID, NUMERIC, ORDINAL, NOMINAL, TARGET), `GBDTSchemaConfig` with type accessors (`.numerical()`, `.ordinal()`, `.nominal()`, `.targets()`), forbidden feature lists for leakage prevention, imputation strategies, and DataFrame validation. Also provides `validate_schema()` pre-flight check that catches structural issues (cross-category duplicates, missing forbidden features, imputation column mismatches) before the pipeline runs. |
| **config/gbdt_config.py** | GBDT-specific paths (artifacts, serving, gold data), temporal column configuration per granularity, filter registry (`GBDT_FILTER_REGISTRY`), and data loading functions. Completely independent of the shared `config.py`. |
| **config/schemas/*.yaml** | Schema YAML files. `gbdt_master_schema.yaml` defines 20 targets with forbidden features and GBDT task config (regression/classification, recommended models, Optuna budget). `gbdt_player_game.yaml` defines column types for the PLAYER_GAME granularity. |

### Pipeline Stages

| Module | Purpose |
|--------|---------|
| **eda/eda.py** | `GBDTEDAAnalyzer` — optional exploratory analysis that feeds downstream decisions. Analyzes target distribution (continuous/count/binary), identifies high-missing features, low-variance features, and multicollinear pairs. Produces per-feature `FeatureProfile` objects (n_unique, missing_fraction, target_correlation, suggested_imputation, suggested_scaling). Returns `EDADecisions` with `features_to_drop`, `suggested_models`, `suitability_score`, `suitability_interpretation`, and `data_profile`. The suitability score uses a transparent penalty table (see [Suitability Score](#suitability-score) below). |
| **preprocessing/preprocessor.py** | `GBDTPreprocessor` — schema-driven preprocessing. Handles temporal splitting, leakage prevention (enforces forbidden features), imputation (zero-fill, median, forward-fill per schema), outlier clipping, categorical encoding (native pd.Categorical with enable_categorical=True for XGBoost, native for LightGBM/CatBoost), and training statistics capture for drift monitoring. The redundancy filter (greedy correlation-based at r>0.80) prevents multicollinear feature pairs. |
| **preprocessing/feature_selector.py** | `GBDTFeatureSelector` — single-strategy feature selection (legacy). Strategies: `importance` (train quick model, rank by gain), `correlation` (rank by |correlation with target|), `variance` (drop near-zero variance). Limits output to `max_features`. Used by legacy `run_pipeline()` and as fallback for `importance`/`correlation`/`variance` strategies in `run_full_pipeline()`. |
| **preprocessing/ensemble_feature_selector.py** | `EnsembleFeatureSelector` — multi-method ensemble feature selection via weighted reciprocal rank fusion (RRF). Runs 3 Tier 1 methods (tree importance, correlation, mutual information) always, plus 2 opt-in Tier 2 methods (permutation importance, RFE). Each method independently ranks features; ranks are combined via `score(f) = SUM weight_m / (k + rank_m(f))` where k=60. Returns `EnsembleFeatureReport` with selected features, per-method ranks, and ensemble scores. No silent fallbacks — every enabled method must succeed. |
| **calibration/model_zoo.py** | `ModelZoo` — Optuna hyperparameter tuning with budget-tiered search spaces (low=25, medium=50, high=100 trials). Supports single-objective (default) and **multi-objective** tuning (presets: `rmse+mae`, `rmse+r2`, `rmse+coverage`) using Pareto-optimal trial selection. Multi-model comparison across XGBoost, LightGBM, and CatBoost. Optional stacking ensemble. Budget is driven by the schema's `search_space_budget` per target. |
| **diagnostics/diagnostics.py** | `GBDTDiagnosticsRunner` — post-training analysis. Runs time-series cross-validation (TimeSeriesSplit), residual analysis (mean/std/skew), SHAP feature importance (TreeExplainer), and split-conformal prediction intervals at coverage levels [50%, 80%, 90%, 95%, 99%]. |
| **diagnostics/champion_challenger.py** | `GBDTChampionChallenger` — model promotion system with **version history and rollback**. Compares candidate model against existing champion on the schema-defined metric (default: RMSE, lower_is_better). Promotes if improvement exceeds `min_improvement` (default 1%). Each promotion saves to `champion_{version}/` for history retention and copies to `champion/` as the active version. `list_versions()` shows all historical champions; `rollback(version)` restores a previous version. Dual-saves to training and serving directories. |

### Serving

| Module | Purpose |
|--------|---------|
| **serving/predictor.py** | `GBDTPredictor` — production inference class. `load_champion()` class method loads a champion model from `GBDT_SERVING_DIR` (`serving/artifacts/gbdt/{target}_{granularity}/champion/`). `predict()` aligns input features with the model's expected features (drops extras, imputes missing with training median, raises `ValueError` on zero overlap), runs inference, checks for feature drift (flags features where mean/std deviates >2σ from training), and optionally computes per-prediction SHAP contributions. Returns `GBDTPredictionResult` with predictions, conformal intervals, drift flags, and feature contributions. |
| **serving/api.py** | `GBDTAPI` — high-level API class that wraps `GBDTPredictor` for use by the FastAPI router. Methods: `predict()`, `list_models()`, `get_model_info()`, `health_check()`, `reload()`. `list_models()` reads target/granularity from `metadata.json` for accuracy. |
| **gbdt_endpoints.py** (router) | FastAPI router at `/api/v1/gbdt/` with 6 endpoints: `POST /predict`, `POST /batch-predict`, `GET /models`, `GET /models/{target}`, `GET /health`, `POST /train` (background training trigger). |
| **diagnostics/champion_challenger.py** | `GBDTChampionChallenger` — handles dual-save promotion to both training (`serving/training/gbdt/{granularity}/{target}/champion/`) and production serving (`serving/artifacts/gbdt/{target}_{granularity}/champion/`) directories. Maintains version history in `champion_{version}/` directories. Supports `list_versions()` and `rollback(version)`. See [Serving Architecture](#serving-architecture) for details. |

**Unified Serving Layer** (outside `gddt/`):

| Module | Purpose |
|--------|---------|
| `serving/registry/unified_registry.py` | `UnifiedModelRegistry` — discovers GBDT champions by scanning `serving/artifacts/gbdt/`. Reads `metadata.json` first, falls back to directory name parsing. |
| `serving/services/gbdt_service.py` | `GBDTService` — inference wrapper using the unified registry. Called by `UnifiedModelService` for multi-model orchestration. |
| `serving/services/unified_service.py` | `UnifiedModelService` — routes predictions to Bayesian, XFG, or GBDT backends based on `model_type`. |
| `serving/api/gbdt_router.py` | FastAPI router for the unified serving layer's GBDT endpoints. |

### Utilities

| Module | Purpose |
|--------|---------|
| **utils/dataset_registry.py** | `DatasetRegistry` — dataset abstraction layer. Each dataset is a `DatasetSpec` with a name, schema path, data loader function, temporal column, entity columns, and optional `filters` dict. When `filters` is set, the trainer resolves filter definitions from DatasetSpec FIRST, falling back to the global `GBDT_FILTER_REGISTRY`. Pre-registers NBA datasets (player_game, player_season, team_game). Enables the pipeline to work with any tabular dataset, not just NBA data. |
| **utils/schema_generator.py** | `SchemaGenerator` — auto-generates a starter YAML schema from a DataFrame. Inspects dtypes and cardinality to infer column categories. Also provides `suggest_forbidden_features(df, target)` which detects leakage candidates via 3 strategies: name match ("PTS" in "PTS_PER_36"), high correlation (|r| > 0.90), and statistical family substring (PTS → FG/FGM/FGA). Outputs a draft YAML that you then refine with forbidden features, imputation strategies, and GBDT-specific config. |
| **utils/reporter.py** | `GBDTPipelineReporter` — generates a Markdown summary of the pipeline run: EDA findings, preprocessing decisions, model comparison table, champion rationale, diagnostic highlights, and promotion decision. Saved alongside artifacts. |
| **utils/pipeline_checkpoint.py** | `PipelineCheckpoint` — saves and loads pipeline state at each stage via pickle. If a run is interrupted, you can resume from the last completed stage instead of starting over. |
| **utils/scheduler.py** | `RetrainingScheduler` — cron-compatible scheduling for periodic retraining. Checks if retraining is due based on configurable intervals and triggers the pipeline. |

---

## Architecture: Two Pipeline Modes

### Legacy Pipeline: `run_pipeline()` (6 Steps)

Backward-compatible with existing code. Calls the legacy methods in sequence:

```
load_data → engineer_features [DEPRECATED] → apply_filters → split_data
→ preprocess [optional] → select_features [optional] → tune [optional] → train → evaluate
```

### Full Pipeline: `run_full_pipeline()` (11 Stages)

Self-contained, schema-driven pipeline. Does NOT call `engineer_features()` — assumes gold data.

```
[0] Dataset Resolution    → resolve schema path + temporal column from granularity
[1] Schema Load           → load YAML, merge master targets, validate schema
[2] Data Load + Filter    → load gold parquet, prune to schema, apply GBDT filters
[3] EDA (optional)        → analyze target + features, produce EDADecisions
[4] Preprocessing         → temporal split, leakage prevention, imputation, redundancy filter
[5] Calibration (optional)→ Optuna hyperparameter tuning with budget-tiered search spaces
[6] Model Zoo (optional)  → compare XGBoost/LightGBM/CatBoost, pick champion
[7] Train                 → train champion model (possibly with tuned params)
[8] Diagnostics           → SHAP, cross-validation, residuals, conformal intervals
[9] Champion/Challenger   → compare vs existing champion, promote if improved
[10] Summary + Artifacts  → save model, metadata, report; MLflow logging; gc.collect()
```

---

## Quick Start

### Running on NBA Data

Edit `main_non_cli.py` and run:

```python
# In main_non_cli.py, set:
TARGET = "PTS"                    # or "ALL_TARGETS" for all 20
GRANULARITY = "PLAYER_GAME"
MODEL_TYPE = "xgboost"
RUN_SHAP = True
RUN_CONFORMAL = True
CHAMPION_CHALLENGER = True
```

```bash
export PYTHONPATH=/workspace
python -m api.src.ml.modeling.gddt.main_non_cli
```

### Programmatic Usage

```python
from api.src.ml.modeling.gddt import GDDTConfig, GDDTTrainer

config = GDDTConfig(
    target="PTS",
    granularity="PLAYER_GAME",
    model_type="xgboost",
    run_shap=True,
    run_conformal=True,
    champion_challenger=True,
)

trainer = GDDTTrainer(config)
results = trainer.run_full_pipeline()

print(f"Test R²: {results['metrics']['r2']:.4f}")
print(f"Test RMSE: {results['metrics']['rmse']:.4f}")
```

### Inference with a Champion Model

```python
from api.src.ml.modeling.gddt.serving.predictor import GBDTPredictor

predictor = GBDTPredictor.load_champion("PTS")
result = predictor.predict(new_game_data, check_drift=True)

print(result.predictions)          # Point predictions
print(result.drift_flags)          # Features with distribution shift
print(result.intervals)            # Conformal prediction intervals
```

---

## Schema System

The pipeline is driven by two types of YAML schemas:

### Master Schema (`gbdt_master_schema.yaml`)

Defines **what targets exist** and **what features are forbidden** for each target (leakage prevention). Also specifies GBDT-specific configuration per target:

```yaml
target_definitions:
  PTS:
    display_name: "Points"
    task: "regression"
    recommended_models: ["xgboost", "lightgbm"]
    search_space_budget: "medium"        # 50 Optuna trials
    default_max_features: 25
    promotion:
      metric: "rmse"
      direction: "lower_is_better"
    forbidden_features:
      - PTS
      - FG
      - FGM
      - FGA
      - FT
      - FTM
      - FTA
      - FG_PCT
      - TS_PCT
      - GAME_SCORE
      # ... comprehensive list preventing data leakage
```

### Granularity Schema (`gbdt_player_game.yaml`)

Defines **what columns exist** and **what type each column is**:

```yaml
id:
  - PLAYER_ID
  - GAME_ID
  - TEAM_ID

target:
  - PTS
  - AST
  - TRB
  # ... 20 targets

ordinal:
  - SEASON_ID
  - SEASON

nominal:
  - PLAYER
  - TEAM
  - POSITION
  - MATCHUP

numerical:
  - MIN
  - AGE
  - USG_PCT
  # ... 184+ features

zero_fill_columns:
  - INJURY_GAMES_MISSED
  - DNP_COUNT

median_impute_columns:
  - USG_PCT
  - PER_ESTIMATE

_gbdt_pipeline_defaults:
  preprocessing:
    outlier_clip_quantiles: [0.01, 0.99]
    redundancy_threshold: 0.80
```

### How Schemas Are Used

At runtime, `load_gbdt_schema()` merges the master and granularity schemas:

- **Master** provides: `target_definitions` (forbidden features, task type, budget, promotion config), `filter_defaults`
- **Granularity** provides: column type lists (id/numerical/ordinal/nominal/target), imputation strategies, pipeline defaults, feature groups

The merged `GBDTSchemaConfig` object is used throughout:

| Pipeline Stage | Schema Usage |
|----------------|-------------|
| Stage 1 | Validate target exists in schema |
| Stage 2 | `prune_dataframe_to_schema()` — drop unexpected columns; `coerce_dataframe_to_schema_dtypes()` — force correct types |
| Stage 3 (EDA) | `schema.numerical()` — which features to analyze for collinearity |
| Stage 4 | `schema.get_forbidden_features(target)` — leakage prevention; `schema.get_imputation_strategy_for_column()` — how to fill missing values |
| Stage 5 | `schema.get_target_config(target)["search_space_budget"]` — Optuna trial count |
| Stage 8 | `schema.get_target_config(target)` — expected R² range for diagnostics |
| Stage 9 | `schema.get_promotion_config(target)` — metric and direction for champion comparison |

---

## Filter Registry

The GBDT pipeline has its own filter registry (`GBDT_FILTER_REGISTRY` in `gbdt_config.py`), independent of the Bayesian pipeline:

| Filter | Type | What It Does | Applied To |
|--------|------|-------------|-----------|
| `nba_teams_only` | pattern_match | Keep rows where TEAM_ID matches `^1610612\d{3}$` | PLAYER_GAME, TEAM_GAME |
| `minimum_game_minutes` | threshold | Keep rows where MIN >= 5.0 | PLAYER_GAME |
| `minimum_shot_attempts` | threshold | Keep rows where FGA >= 1 | PLAYER_GAME (TS_PCT, EFG_PCT only) |
| `temporal_window` | temporal | Keep most recent N seasons | All granularities |

Filters are applied in Stage 2 based on the target and granularity. The `GBDT_TARGET_DEFAULT_FILTERS` dict maps targets to their applicable filters. Most targets use `["nba_teams_only", "minimum_game_minutes"]`; efficiency targets (TS_PCT, EFG_PCT) additionally require `minimum_shot_attempts`.

### Dataset-Specific Filters

Non-NBA datasets can bring their own filter definitions via the `DatasetSpec.filters` field. When set, the trainer resolves filter names from `DatasetSpec.filters` FIRST, then falls back to the global `GBDT_FILTER_REGISTRY` for any names not found. This means a baseball dataset could define `minimum_at_bats` without modifying the global registry:

```python
spec = DatasetSpec(
    name="mlb_player_season",
    filters={
        "minimum_at_bats": {
            "enabled": True,
            "filter_type": "threshold",
            "value_column": "AB",
            "threshold_value": 50,
            "operator": ">=",
            "granularities": ["PLAYER_SEASON"],
        },
    },
    # ... other DatasetSpec fields
)
```

Dataset-specific filters can also override global filters by using the same name. For example, a dataset could override `minimum_game_minutes` to use a threshold of 10 instead of the default 5.

---

## Suitability Score

The EDA suitability score quantifies how well-suited a dataset is for GBDT modeling. It starts at 1.0 and subtracts penalties from a transparent penalty table:

| Condition | Penalty | Rationale |
|-----------|---------|-----------|
| Sample size < 200 | -0.30 | GBDT needs substantial data for tree splits |
| Fewer than 5 numerical features | -0.20 | Too few features for meaningful splits |
| Max feature \|corr with target\| > 0.95 | -0.15 | Near-perfect linear relationship — simpler model suffices |
| Target zero-fraction > 30% | -0.10 | Zero-inflated distribution needs special handling |
| Rows:features ratio < 10:1 | -0.10 | Overfitting risk without enough samples per feature |
| Target \|skew\| > 3.0 | -0.05 | Extreme skew may need log transform |

**Interpretation thresholds:**

| Score | Interpretation | Action |
|-------|---------------|--------|
| >= 0.70 | "good" | Proceed with GBDT |
| 0.40 - 0.69 | "caution" | Review EDA notes; may need preprocessing adjustments |
| < 0.40 | "poor" | Consider alternative model families |

The penalty table is defined in `SUITABILITY_PENALTIES` and thresholds in `SUITABILITY_THRESHOLDS` in `eda.py`, making the score fully transparent and tunable.

---

## Feature Profiling

When EDA runs, it produces a `FeatureProfile` for every numerical feature. This per-feature profile drives schema refinement decisions:

```python
@dataclass
class FeatureProfile:
    name: str
    n_unique: int                          # Cardinality
    missing_fraction: float                # 0.0 to 1.0
    mean: Optional[float]
    std: Optional[float]
    skewness: Optional[float]
    min_val: Optional[float]
    max_val: Optional[float]
    target_correlation: Optional[float]    # Pearson r with target
    suggested_imputation: str              # "zero", "median", or "none"
    suggested_scaling: str                 # "none", "standard", or "robust"
```

Access profiles via `EDADecisions.data_profile`:

```python
decisions = analyzer.analyze(df, target="PTS")
for name, profile in decisions.data_profile.items():
    if profile.missing_fraction > 0.30:
        print(f"{name}: {profile.missing_fraction:.0%} missing → {profile.suggested_imputation}")
    if profile.target_correlation and abs(profile.target_correlation) > 0.80:
        print(f"{name}: high corr with target ({profile.target_correlation:.3f})")
```

---

## Schema Validation

The `validate_schema()` function runs pre-flight checks on a `GBDTSchemaConfig` before the pipeline starts. This catches structural YAML issues early:

| Check | Severity | Example |
|-------|----------|---------|
| Column in multiple categories | Error | "MIN" listed in both `numerical` and `ordinal` |
| Duplicate column within category | Error | "FEAT_A" listed twice in `numerical` |
| Forbidden feature references non-existent column | Warning | `forbidden_features: ["NONEXISTENT_COL"]` |
| Target without forbidden_features | Warning | PTS target with no leakage list |
| Imputation column not in numerical | Warning | `median_impute: ["POSITION"]` (nominal, not numerical) |
| Columns in YAML not in DataFrame | Warning | Schema declares "AGE" but DataFrame lacks it |

```python
from api.src.ml.modeling.gddt.config.schema import validate_schema, load_gbdt_schema

schema = load_gbdt_schema(schema_path, master_path)
result = validate_schema(schema, df=my_dataframe)

if not result["ok"]:
    for error in result["errors"]:
        print(f"ERROR: {error}")
for warning in result["warnings"]:
    print(f"WARNING: {warning}")
```

---

## Forbidden Feature Suggestion

When bringing a new dataset, the `SchemaGenerator.suggest_forbidden_features()` method helps identify data leakage candidates. This is the highest-value safety net in the pipeline — data leakage is silent and catastrophic.

Three detection strategies:

1. **Name match**: Columns whose name contains the target name (e.g., `PTS_PER_36` when predicting `PTS`)
2. **High correlation**: Columns with |correlation| > threshold to the target (default 0.90)
3. **Statistical family**: Known stat families where one metric derives from another (e.g., PTS derives from FG + 3P + FT)

```python
from api.src.ml.modeling.gddt.utils.schema_generator import SchemaGenerator

gen = SchemaGenerator()
suggestions = gen.suggest_forbidden_features(df, target="PTS", correlation_threshold=0.90)

for category, items in suggestions.items():
    for item in items:
        print(f"  [{category}] {item['column']}: {item['reason']}")
```

Output example:
```
  [name_match] PTS_PER_36: Column name contains 'PTS'
  [name_match] PTS_DIFF5: Column name contains 'PTS'
  [high_correlation] SCORING_OUTPUT: |corr| = 0.987 > 0.90
  [substring_family] FGA: Statistical family match via 'FG'
  [substring_family] FT_PCT: Statistical family match via 'FT'
```

Review these suggestions and add confirmed leakage candidates to `forbidden_features` in the master schema YAML.

---

## Leakage Prevention

Every target has a `forbidden_features` list in the master schema. These are features that would create data leakage if used as inputs when predicting that target. For example, when predicting PTS:

- **Direct derivatives**: PTS itself, PPG, PTS_PER_36, PTS_RANK
- **Component stats**: FG, FGM, FT, FTM, 3P, FG3M (these sum to PTS)
- **Attempt stats**: FGA, FTA, FG3A (highly correlated proxies)
- **Percentages**: FG_PCT, FT_PCT, TS_PCT, EFG_PCT (derived from makes/attempts)
- **Composite metrics**: GAME_SCORE, PER_ESTIMATE (contain PTS in formula)
- **Derived features**: PTS_DIFF1, PTS_DIFF5, PTS_PCT_CHANGE, PTS_PER_MIN
- **Fantasy points**: NBA_FANTASY_PTS, WNBA_FANTASY_PTS (contain PTS)

The preprocessor enforces these exclusions automatically in Stage 4 by calling `schema.get_forbidden_features(target)`.

---

## Bringing a New Dataset

This is the step-by-step workflow for using the GBDT pipeline with a dataset other than the default NBA player-game data.

### Step 1: Prepare Gold Data

Your data must be a clean, feature-engineered DataFrame in parquet format. Feature engineering happens upstream (Bronze to Silver to Gold) — the GBDT pipeline strictly consumes gold data.

Requirements:
- One row per observation (e.g., one row per player-game, per player-season)
- A temporal column for train/test splitting (e.g., `SEASON_ID`, `DATE`)
- Entity identifier columns (e.g., `PLAYER_ID`, `GAME_ID`)
- One or more target columns
- Numerical, ordinal, and/or nominal feature columns

### Step 2: Generate a Starter Schema

Use `SchemaGenerator` to auto-infer column types from your DataFrame:

```python
from api.src.ml.modeling.gddt.utils.schema_generator import SchemaGenerator
import pandas as pd

df = pd.read_parquet("path/to/your/gold_data.parquet")

generator = SchemaGenerator()
schema_yaml = generator.generate_from_dataframe(
    df,
    targets=["PTS", "AST"],
    entity_columns=["PLAYER_ID", "GAME_ID"],
    temporal_column="SEASON_ID",
)

generator.save(
    schema_yaml,
    "api/src/ml/modeling/gddt/config/schemas/gbdt_my_dataset.yaml",
)
```

The generator inspects dtypes and cardinality:
- `float64`/`int64` columns with many unique values → `numeric`
- String columns with fewer than 20 unique values → `nominal`
- Columns you specify → `id`, `target`, or `ordinal`

### Step 2.5: Detect Forbidden Features (Leakage Prevention)

Before refining the schema, run the forbidden feature suggester on each target. This is the highest-value step — data leakage is silent and catastrophic:

```python
for target in ["PTS", "AST"]:
    suggestions = generator.suggest_forbidden_features(df, target=target)
    print(f"\n=== {target} ===")
    for category, items in suggestions.items():
        for item in items:
            print(f"  [{category}] {item['column']}: {item['reason']}")
```

Review each suggestion and add confirmed leakage candidates to the master schema YAML under `target_definitions.YOUR_TARGET.forbidden_features`.

### Step 3: Refine the Schema

The auto-generated schema is a starting point. Open the YAML and refine:

1. **Move misclassified columns** — the generator may put ordinal columns in nominal, or vice versa. Fix these based on domain knowledge.

2. **Add forbidden_features** — use the suggestions from Step 2.5 as a starting point. For each target, list every feature that would leak information. Add these to `gbdt_master_schema.yaml` under `target_definitions.YOUR_TARGET.forbidden_features`.

3. **Set imputation strategies** — add `zero_fill_columns`, `median_impute_columns`, or `forward_fill_columns` sections based on the meaning of each feature.

4. **Configure GBDT-specific settings** — add `_gbdt_pipeline_defaults` and `_gbdt_feature_groups` sections.

5. **Set target config** — in the master schema, define task type (`regression` or `classification`), recommended models, search space budget, and promotion criteria for each target.

### Step 3.5: Validate the Schema

Run the schema validator to catch structural issues before the pipeline starts:

```python
from api.src.ml.modeling.gddt.config.schema import load_gbdt_schema, validate_schema

schema = load_gbdt_schema(schema_path, master_path)
result = validate_schema(schema, df=df)

if not result["ok"]:
    for error in result["errors"]:
        print(f"ERROR: {error}")
for warning in result["warnings"]:
    print(f"WARNING: {warning}")
```

Fix any errors before proceeding. Warnings are advisory but should be reviewed.

### Step 4: Register the Dataset

Add your dataset to the `DatasetRegistry`:

```python
from api.src.ml.modeling.gddt.utils.dataset_registry import DatasetSpec, DatasetRegistry

registry = DatasetRegistry(auto_register=False)

spec = DatasetSpec(
    name="my_dataset",
    schema_path=Path("api/src/ml/modeling/gddt/config/schemas/gbdt_my_dataset.yaml"),
    data_loader=lambda: pd.read_parquet("path/to/your/gold_data.parquet"),
    temporal_column="SEASON_ID",
    entity_columns=["PLAYER_ID", "GAME_ID"],
    granularity="PLAYER_GAME",
    description="My custom basketball dataset",
    # Optional: dataset-specific filters (checked before global registry)
    filters={
        "my_custom_filter": {
            "enabled": True,
            "filter_type": "threshold",
            "value_column": "SOME_COL",
            "threshold_value": 10,
            "operator": ">=",
            "granularities": ["PLAYER_GAME"],
        },
    },
)


registry.register(spec)
```

Or add it permanently to `_register_defaults()` in `dataset_registry.py`.

### Step 5: Run EDA First

Before training, run EDA to understand your data:

```python
from api.src.ml.modeling.gddt import GDDTConfig, GDDTTrainer

config = GDDTConfig(
    target="PTS",
    granularity="PLAYER_GAME",
    data_path=Path("path/to/your/gold_data.parquet"),
    schema_path=Path("api/src/ml/modeling/gddt/config/schemas/gbdt_my_dataset.yaml"),
    run_eda=True,
    # Disable everything else for now
    tune_hyperparameters=False,
    model_zoo_mode=False,
    champion_challenger=False,
)

trainer = GDDTTrainer(config)
results = trainer.run_full_pipeline()

# Check EDA findings
eda = results.get("eda_decisions")
print(f"Suitability score: {eda.suitability_score}")
print(f"Features to drop: {eda.features_to_drop}")
print(f"High correlation pairs: {eda.high_correlation_pairs}")
print(f"Suggested models: {eda.suggested_models}")
```

### Step 6: Update Schema Based on EDA

If EDA reveals issues:
- Multicollinear features that the redundancy filter should handle? Verify `redundancy_threshold` is set appropriately in the schema defaults.
- High-missing features? Add them to the appropriate imputation section or the `ignore` list.
- Wrong column types? Fix the YAML.

### Step 7: Run the Full Pipeline

```python
config = GDDTConfig(
    target="PTS",
    granularity="PLAYER_GAME",
    data_path=Path("path/to/your/gold_data.parquet"),
    schema_path=Path("api/src/ml/modeling/gddt/config/schemas/gbdt_my_dataset.yaml"),
    model_type="xgboost",
    run_eda=True,
    run_shap=True,
    run_conformal=True,
    champion_challenger=True,
    cross_validation=True,
    max_features=25,
    redundancy_threshold=0.80,
)

trainer = GDDTTrainer(config)
results = trainer.run_full_pipeline()
```

### Step 8: Train All Targets

Once PTS works, train all targets by editing `main_non_cli.py`:

```python
TARGET = "ALL_TARGETS"
DATA_PATH = "path/to/your/gold_data.parquet"
# Set schema_path in run_single_target() or via GDDTConfig
```

```bash
PYTHONPATH=/workspace python -m api.src.ml.modeling.gddt.main_non_cli
```

### Step 9: Serve Predictions

After champion models are promoted, serve predictions via the API:

```python
from api.src.ml.modeling.gddt.serving.predictor import GBDTPredictor

predictor = GBDTPredictor.load_champion("PTS")
result = predictor.predict(new_data_df, check_drift=True)
```

Or via the REST API:

```bash
curl -X POST http://localhost:8000/api/v1/gbdt/predict \
  -H "Content-Type: application/json" \
  -d '{"target": "PTS", "data": {"MIN": 32.5, "AGE": 27, "USG_PCT": 0.28}}'
```

---

## GDDTConfig Reference

All configuration is done through `GDDTConfig`. Legacy fields are marked with (L), new full-pipeline fields with (F).

### Target & Structure

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `target` | str | `"PER"` | Target stat: PTS, AST, TRB, etc. |
| `granularity` | str | `"PLAYER_SEASON"` | PLAYER_GAME, PLAYER_SEASON, TEAM_GAME |
| `model_type` | str | `"xgboost"` | xgboost, lightgbm, catboost |
| `task` | str | `"regression"` | regression or classification |
| `dataset` | str | `None` | (F) Dataset name for DatasetRegistry lookup |
| `data_path` | Path | `None` | (F) Explicit path to gold parquet (overrides default) |
| `schema_path` | Path | `None` | (F) Explicit schema YAML path (overrides default) |

### Hyperparameters

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `n_estimators` | int | `100` | (L) Number of boosting rounds |
| `max_depth` | int | `6` | (L) Maximum tree depth |
| `learning_rate` | float | `0.1` | (L) Step size shrinkage |
| `subsample` | float | `0.8` | (L) Row sampling ratio |
| `colsample_bytree` | float | `0.8` | (L) Column sampling ratio |

### Feature Selection

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_features` | int | `None` | Max features after selection (schema default: 25) |
| `min_importance` | float | `0.0` | (L) Minimum feature importance threshold |
| `feature_selection_strategy` | str | `"importance"` | `importance`, `correlation`, `variance`, `mutual_info`, or `ensemble` |
| `redundancy_threshold` | float | `0.80` | Correlation threshold for greedy redundancy filter |
| `ensemble_run_permutation` | bool | `False` | (F) Include permutation importance in ensemble (Tier 2, ~30s) |
| `ensemble_run_rfe` | bool | `False` | (F) Include RFE in ensemble (Tier 2, ~2min) |
| `ensemble_rfe_step` | int | `5` | (F) RFE step size (features eliminated per round) |
| `ensemble_permutation_repeats` | int | `5` | (F) Number of permutation repeats |
| `ensemble_weights` | Dict/None | `None` | (F) Custom weight overrides for RRF method weights |

### Pipeline Control

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `run_eda` | bool | `False` | (F) Run EDA analysis in Stage 3 |
| `model_zoo_mode` | bool | `False` | (F) Compare multiple model types in Stage 6 |
| `tune_hyperparameters` | bool | `False` | Run Optuna tuning |
| `multi_objective` | str/None | `None` | Multi-objective preset: `"rmse+mae"`, `"rmse+r2"`, `"rmse+coverage"`, or `None` for single-objective |
| `n_tuning_trials` | int | `50` | Number of Optuna trials (overrides schema budget) |
| `run_shap` | bool | `False` | (F) Compute SHAP feature importance |
| `run_conformal` | bool | `False` | (F) Compute conformal prediction intervals |
| `champion_challenger` | bool | `False` | (F) Compare vs existing champion |
| `cross_validation` | bool | `False` | (F) Run time-series cross-validation |
| `save_artifacts` | bool | `True` | Save model + metadata to disk |
| `log_to_mlflow` | bool | `False` | (F) Log run to MLflow |

### Temporal Split

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `test_seasons` | int | `1` | Number of most-recent seasons for the test set |

---

## Data Flow

```
Gold Parquet (254,512 rows x 645 cols)
    │
    ├─ Schema prune: keep only declared columns
    ├─ Dtype coercion: numeric→float, categorical→object
    │
    ├─ Filter: nba_teams_only → removes non-NBA teams
    ├─ Filter: minimum_game_minutes (MIN >= 5) → removes garbage time
    │
    │  ~235,000 rows remaining
    │
    ├─ Temporal split: train = seasons [:-1], test = most recent season
    │  train: ~47,910 rows, test: ~23,995 rows
    │
    ├─ Leakage prevention: remove forbidden features for this target
    ├─ Imputation: zero-fill, median, or forward-fill per schema
    ├─ Redundancy filter: greedy drop correlated pairs (|r| > 0.80)
    ├─ Feature selection: top 25 (ensemble RRF or single-strategy)
    │
    │  X_train: 47,910 x 25, X_test: 23,995 x 25
    │
    ├─ Train XGBoost/LightGBM/CatBoost
    ├─ Evaluate: RMSE, MAE, R²
    ├─ Diagnostics: SHAP, CV, residuals, conformal
    │
    └─ Champion/Challenger: promote if improved
        ├─ Training:  serving/training/gbdt/{granularity}/{target}/champion/
        └─ Serving:   serving/artifacts/gbdt/{target}_{granularity}/champion/
                      → discoverable by UnifiedModelRegistry
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/gbdt/predict` | Single-row prediction |
| POST | `/api/v1/gbdt/batch-predict` | Batch prediction |
| GET | `/api/v1/gbdt/models` | List all champion models |
| GET | `/api/v1/gbdt/models/{target}` | Model info + metrics for a target |
| GET | `/api/v1/gbdt/health` | Health check |
| POST | `/api/v1/gbdt/train` | Trigger background training (admin) |

### Predict Request

```json
{
  "target": "PTS",
  "data": {"MIN": 32.5, "AGE": 27, "USG_PCT": 0.28, "FGA_ROLL10_MEAN": 15.2},
  "check_drift": true
}
```

### Predict Response

```json
{
  "target": "PTS",
  "predictions": [18.7],
  "model_version": "20260212_143022_a3f2b1c8",
  "n_predictions": 1,
  "drift_warnings": null
}
```

### Train Request

```json
{
  "target": "PTS",
  "granularity": "PLAYER_GAME",
  "model_type": "xgboost",
  "tune_hyperparameters": false,
  "champion_challenger": true
}
```

---

## Serving Architecture

The GBDT pipeline integrates with the project's unified serving layer and also provides a direct access API. This section documents how trained models flow from training to production inference.

### Artifact Directories

Two directories are used for GBDT artifacts:

| Directory | Purpose | Path |
|-----------|---------|------|
| **Training artifacts** | Full training record (model, metadata, features, diagnostics) | `/workspace/serving/training/gbdt/{granularity}/{target}/champion/` |
| **Serving artifacts** | Production-ready model for inference (scanned by unified registry) | `/workspace/serving/artifacts/gbdt/{target}_{granularity}/champion/` |

The training directory uses a hierarchical layout (`{granularity}/{target}/champion/`) because it groups by dataset type. The serving directory uses a flat `{target}_{granularity}/champion/` naming convention because the `UnifiedModelRegistry._scan_artifacts()` method scans one level of subdirectories under each model type.

Both directories are configured in `gbdt_config.py`:

```python
GBDT_ARTIFACTS_DIR = Path("/workspace/serving/training/gbdt")     # Training
GBDT_SERVING_DIR   = Path("/workspace/serving/artifacts/gbdt")    # Serving
```

### Dual-Save Mechanism

When `GBDTChampionChallenger.compare_and_promote()` promotes a candidate model, it **dual-saves** to both directories simultaneously and saves a **versioned copy** for rollback. This ensures:

1. **Training directory** retains the full history and is the source of truth for model provenance
2. **Serving directory** is immediately discoverable by the unified serving layer
3. **Version history** is preserved for rollback capability

```
champion_challenger.compare_and_promote()
  ├─ Save to: serving/training/gbdt/PLAYER_GAME/PTS/champion/
  │   ├── model.joblib          # Serialized GDDTModel
  │   ├── metadata.json         # Target, granularity, version, metrics, timestamp
  │   ├── features.json         # Ordered feature column list
  │   └── training_stats.json   # Per-feature mean/std (when provided)
  │
  ├─ Save to: serving/training/gbdt/PLAYER_GAME/PTS/champion_{version}/
  │   └── (same files)          # Versioned copy for rollback
  │
  └─ Save to: serving/artifacts/gbdt/PTS_PLAYER_GAME/champion/
      └── (same files)          # Serving copy (discoverable by UnifiedModelRegistry)
```

### Champion Rollback

Each promotion creates a versioned backup directory (`champion_{version}/`). To rollback:

```python
from api.src.ml.modeling.gddt.diagnostics.champion_challenger import GBDTChampionChallenger

cc = GBDTChampionChallenger(schema=schema, config=config)

# List all historical versions
versions = cc.list_versions()
for v in versions:
    status = " (CURRENT)" if v.is_current else ""
    print(f"  {v.version}: RMSE={v.metrics.get('rmse', '?')}{status}")

# Rollback to a specific version
cc.rollback(version="s1a2b3c4_m5e6f7g8")
```

Rollback copies all artifacts from the versioned directory back to `champion/` in both training and serving directories. Version history directories are never deleted — they accumulate as an audit trail.

### Artifact Files

Each champion directory contains these files:

| File | Contents | Used By |
|------|----------|---------|
| `model.joblib` | Serialized `GDDTModel` (XGBoost/LightGBM/CatBoost wrapper) | `GBDTPredictor.load_champion()`, `GBDTService.predict()` |
| `metadata.json` | `{target, granularity, version, schema_hash, metrics, model_type, feature_cols, timestamp}` | `UnifiedModelRegistry._extract_gbdt_metadata()`, `GBDTAPI.list_models()` |
| `features.json` | Ordered list of feature column names used during training | `GBDTPredictor` (validates input features match training features) |
| `training_stats.json` | Per-feature mean/std from training data (when available) | `GBDTPredictor` drift detection |
| `feature_selection_report.json` | Ensemble feature selection details: methods run, per-method ranks, RRF scores, weights (when `strategy=ensemble`) | Auditability, MLflow artifact |
| `conformal_quantiles.json` | Residual quantiles for conformal intervals (when available) | `GBDTPredictor` prediction intervals |

### Two Access Paths

GBDT predictions can be served through two independent paths:

#### Path 1: Unified Serving Layer (recommended for multi-model orchestration)

```
Client → UnifiedModelService.predict(model_type="gbdt", ...)
  → GBDTService.predict()
    → UnifiedModelRegistry.get_champion("gbdt", target, granularity)
      → Scans serving/artifacts/gbdt/{target}_{granularity}/champion/
      → Reads metadata.json for target, granularity, version, metrics
    → Loads model.joblib, runs inference
  → UnifiedPredictionResult
```

Files involved:
- `serving/services/unified_service.py` — Routes to GBDT backend
- `serving/services/gbdt_service.py` — GBDT inference via registry
- `serving/registry/unified_registry.py` — Model discovery and metadata
- `serving/api/gbdt_router.py` — FastAPI endpoints

#### Path 2: Direct GBDT API (standalone, no registry dependency)

```
Client → GBDTAPI.predict(target="PTS", data=df)
  → GBDTPredictor.load_champion("PTS")
    → Reads from GBDT_SERVING_DIR / target_dir / champion/
    → Loads model.joblib + metadata.json + features.json
    → Optionally loads training_stats.json + conformal_quantiles.json
  → Validates features → Impute missing → Predict → Drift check → Conformal intervals
  → GBDTPredictionResult
```

Files involved:
- `gddt/serving/api.py` — `GBDTAPI` class
- `gddt/serving/predictor.py` — `GBDTPredictor` class
- `api/app/routers/gbdt_endpoints.py` — FastAPI endpoints (uses GBDTAPI)

#### When to Use Which Path

| Path | Best For |
|------|----------|
| **Unified** | Multi-model orchestration (Bayesian + GBDT + XFG), model catalog, health monitoring |
| **Direct** | Standalone GBDT inference, lower latency (no registry overhead), batch prediction |

### Unified Registry Integration

The `UnifiedModelRegistry` discovers GBDT models by scanning `serving/artifacts/gbdt/`. For each subdirectory containing a `champion/model.joblib`:

1. **Reads `metadata.json`** (preferred) — extracts target, granularity, version, model_type, metrics
2. **Falls back to directory name parsing** — splits `{target}_{granularity}` on the last underscore
3. **Creates `ModelMetadata`** with `model_type="gbdt"` and `is_champion=True`

This metadata-first approach is more reliable than directory name parsing because compound target names like `TS_PCT` would be ambiguous when split on underscores. The `metadata.json` written by `champion_challenger.py` always has the correct target and granularity.

### Predictor Feature Alignment

When `GBDTPredictor.predict()` receives input data, it handles three feature mismatch scenarios:

| Scenario | Behavior | Log Level |
|----------|----------|-----------|
| Input has extra features not in `features.json` | Silently dropped | DEBUG |
| Input is missing features from `features.json` | Imputed with training median from `training_stats.json` (falls back to 0) | WARNING |
| Input has zero overlap with `features.json` | Raises `ValueError` with expected feature list | ERROR |

This design allows the predictor to gracefully handle schema evolution (where new features may be added to the gold data after a model was trained) while still catching catastrophic mismatches (e.g., passing shot data to a player-game model).

### Concurrent Training Safety

The `POST /gbdt/train` endpoint tracks in-flight training tasks per target. If training is already in progress for a target, subsequent requests return `409 Conflict`:

```json
{"detail": "Training already in progress for target 'PTS'"}
```

The lock is released in a `finally` block, so it clears even if training fails. This prevents two simultaneous runs from colliding on the same champion directory.

### Structured Logging

All GBDT modules use Python's standard `logging` with the `gddt.*` namespace. The pipeline logs per-stage timing:

```
[7/10] Training xgboost model
[8/10] Evaluation + diagnostics
...
GBDT FULL PIPELINE COMPLETE
  R²=0.5572 | RMSE=4.12 | MAE=3.88
  Features: 25 | Time: 45.2s
  Stage timings: data_load_filter=8.3s, preprocessing=3.1s, training=22.4s, diagnostics=9.8s
```

Stage timings are also saved in the results dict (`results["stage_timings"]`) and logged to MLflow when enabled.

### MLflow Integration

MLflow is **supplemental** — model discovery and serving use the manifest-based `UnifiedModelRegistry`, not MLflow's model registry. MLflow (v3.8.1) provides:

- Experiment tracking (hyperparameters, metrics per trial)
- Run comparison across Optuna trials (single and multi-objective)
- Artifact logging (plots, reports, conformal quantiles, training stats)
- Per-stage metrics (EDA suitability, CV scores, conformal coverage, stage timings)
- **Model signatures** — inferred from training data + predictions via `mlflow.models.infer_signature()`
- **Input examples** — first 3 training rows saved alongside model for serving payload generation
- **Dataset logging** — training data summary logged via `mlflow.log_input()` for lineage tracking
- **Multi-objective metrics** — Pareto front size and selected trial values logged as `mo_selected_*`

MLflow experiments follow the naming convention `gbdt/{granularity}/{target}` (e.g., `gbdt/PLAYER_GAME/PTS`). Per-stage metrics are logged with prefixes: `eda_*`, `cv_*`, `conformal_*`, `champion_*`, `mo_selected_*`, `time_*_s`.

The model is logged with `mlflow.sklearn.log_model()` including:
- `signature` — Column-based schema for inputs (feature types) and outputs (prediction type)
- `input_example` — 3-row sample for automatic `serving_input_example.json` generation
- `registered_model_name` — `gbdt_{target}_{granularity}` for MLflow Model Registry

MLflow is enabled by setting `log_to_mlflow=True` in `GDDTConfig`. When disabled (the default), the pipeline functions identically — MLflow is never required for serving.

### Multi-Objective Optimization

For targets where multiple quality metrics matter (e.g., minimizing RMSE while also minimizing MAE), the pipeline supports Pareto-optimal hyperparameter tuning via Optuna's multi-objective optimization.

**Available presets** (set via `GDDTConfig.multi_objective`):

| Preset | Metrics | Directions | Use Case |
|--------|---------|------------|----------|
| `rmse+mae` | RMSE, MAE | minimize, minimize | Balanced error minimization |
| `rmse+r2` | RMSE, R² | minimize, maximize | Error + explanatory power |
| `rmse+coverage` | RMSE, Coverage@95% | minimize, maximize | Error + calibration |

**Usage:**

```python
config = GDDTConfig(
    target="PTS",
    tune_hyperparameters=True,
    multi_objective="rmse+mae",  # Enable multi-objective
)
```

The optimizer returns a **Pareto front** — the set of trials where no trial is strictly better than another on all metrics simultaneously. From this front, the pipeline selects the trial with the best primary metric (first listed). The full Pareto front is saved in `results["multi_objective"]["pareto_front"]` and logged to MLflow.

When `multi_objective` is `None` (default), standard single-objective Optuna tuning is used.

---

## Testing

Run the test suite:

```bash
PYTHONPATH=/workspace python -m pytest api/src/ml/modeling/gddt/tests/test_gbdt_pipeline.py -v
```

29 tests covering:

| # | Test | What It Verifies |
|---|------|-----------------|
| 1 | `test_config_backward_compat` | Legacy GDDTConfig defaults unchanged |
| 2 | `test_config_new_fields` | New full-pipeline fields work |
| 3 | `test_gbdt_schema_loads` | YAML loads into GBDTSchemaConfig |
| 4 | `test_gbdt_schema_column_categories` | All 5 ColumnCategory types populated correctly |
| 5 | `test_gbdt_schema_forbidden_features` | Per-target leakage lists load correctly |
| 6 | `test_gbdt_schema_target_config` | Task type, recommended models per target |
| 7 | `test_gbdt_schema_validation_drift` | Detects missing/unexpected columns |
| 8 | `test_gbdt_filter_registry` | Filters apply correctly |
| 9 | `test_dataset_registry` | Register, get, list datasets |
| 10 | `test_schema_generator` | Generates valid YAML from DataFrame |
| 11 | `test_eda_analyzer` | Suitability scored, multicollinearity flagged |
| 12 | `test_eda_decisions_bridge` | EDA findings propagate to preprocessing |
| 13 | `test_preprocessor_leakage` | Forbidden features excluded per target |
| 14 | `test_preprocessor_categorical_handling` | Native categorical encoding per model type |
| 15 | `test_preprocessor_inverse_transform` | Preprocessing reversibility |
| 16 | `test_feature_selector_strategies` | All 3 strategies produce valid output |
| 17 | `test_model_zoo_comparison` | At least 2 models compared |
| 18 | `test_conformal_intervals` | Coverage within expected bounds |
| 19 | `test_champion_promotion` | First champion + improvement comparison |
| 20 | `test_full_pipeline_smoke` | End-to-end on synthetic data |
| 21 | `test_suitability_score_penalty_table` | Penalty table keys/values correct, score interpretation |
| 22 | `test_feature_profile` | Per-feature FeatureProfile populated correctly |
| 23 | `test_validate_schema` | Pre-flight check catches cross-category duplicates, missing forbidden lists |
| 24 | `test_suggest_forbidden_features` | Leakage detection: name match, correlation, stat family |
| 25 | `test_dataset_spec_filters` | Dataset-specific filters resolved before global registry |
| 26 | `test_champion_version_history_and_rollback` | Version history saved, rollback restores previous champion |
| 27 | `test_multi_objective_presets` | Multi-objective presets have valid metrics/directions |
| 28 | `test_multi_objective_tuning` | Multi-objective Optuna returns Pareto front |
| 29 | `test_config_multi_objective` | GDDTConfig.multi_objective defaults correctly |
| 30 | `test_ensemble_feature_selector_known_signal` | Known-signal features (y=3x1+2x2+noise) selected over noise; all Tier 1 methods run; ranks are 1..N |
| 31 | `test_ensemble_rrf_math_correctness` | Hand-computed RRF scores match to 6 decimal places; ranking order verified |
| 32 | `test_ensemble_with_permutation` | Permutation importance included when enabled; signal features still selected |
| 33 | `test_ensemble_custom_weights_change_outcome` | Heavy correlation weight favors linear features; heavy MI weight favors nonlinear features |
| 34 | `test_ensemble_report_artifact_round_trip` | JSON serialization/deserialization preserves all report fields |

---

## Design Principles

1. **Self-contained** — No imports from the Bayesian pipeline. Own schema, config, filters, paths.
2. **Schema-driven** — All decisions (targets, forbidden features, imputation, Optuna budget, promotion criteria) sourced from YAML files.
3. **No feature engineering** — Feature engineering belongs in the Silver layer (upstream). This pipeline strictly consumes gold data.
4. **Backward compatible** — The original `GDDTConfig` and `run_pipeline()` work unchanged. New functionality is opt-in via new config fields.
5. **Leakage-safe** — Forbidden features enforced automatically at the schema level.
6. **Modular stages** — Each pipeline stage can run independently for debugging and EDA.
7. **Budget-aware tuning** — Optuna trial count is schema-driven per target (low/medium/high).
8. **Dual-save promotion** — Champions saved to both training artifacts and production serving directories.
9. **Drift monitoring** — Training statistics captured during preprocessing; inference compares new data against these baselines.
10. **Metadata-first discovery** — Unified registry reads `metadata.json` before parsing directory names, ensuring compound targets like `TS_PCT` are correctly identified.

---

## Changelog

### v1.5 (2026-02-12)

- **Added**: `EnsembleFeatureSelector` — multi-method ensemble feature selection via weighted reciprocal rank fusion (RRF). Tier 1 (always-on): tree importance, correlation, mutual information. Tier 2 (opt-in): permutation importance, RFE
- **Added**: `EnsembleFeatureReport` dataclass with selected features, per-method ranks, ensemble scores, method weights, timing
- **Added**: `feature_selection_report.json` artifact — saved alongside champion when `strategy=ensemble`
- **Added**: `mutual_info` strategy implementation (was declared in config but never implemented)
- **Added**: Strategy dispatch in `trainer.py` Stage 4 — routes `ensemble`, `mutual_info`, `importance`, `correlation`, `variance` to appropriate selectors
- **Added**: 5 config fields: `ensemble_run_permutation`, `ensemble_run_rfe`, `ensemble_rfe_step`, `ensemble_permutation_repeats`, `ensemble_weights`
- **Added**: MLflow logging for ensemble metrics (`ensemble_n_candidates`, `ensemble_n_selected`, `ensemble_n_methods`, `ensemble_selection_time_s`) and `feature_selection_report.json` artifact
- **Updated**: Tests expanded from 29 to 34 — added ensemble known-signal, RRF math correctness, permutation, custom weights, artifact round-trip

### v1.4 (2026-02-12)

- **Added**: Champion rollback — `list_versions()` and `rollback(version)` methods in `GBDTChampionChallenger`. Each promotion saves a versioned copy in `champion_{version}/`
- **Added**: Multi-objective Optuna support — `tune_multi_objective()` in `ModelZoo` with presets `rmse+mae`, `rmse+r2`, `rmse+coverage`. Returns Pareto-optimal trials
- **Added**: `GDDTConfig.multi_objective` field — preset name for multi-objective tuning (`None` = single-objective)
- **Added**: `ParetoTrial` dataclass for Pareto front representation
- **Updated**: MLflow `_log_to_mlflow()` with model signatures via `infer_signature()`, input examples (3-row sample), dataset logging via `mlflow.log_input()`, conformal quantiles artifact, training stats artifact, and multi-objective metrics (`mo_selected_*`, `pareto_front_size`)
- **Updated**: `_save_champion()` accepts optional `training_stats` for saving alongside champion artifacts
- **Updated**: Tests expanded from 25 to 29 — added rollback, multi-objective presets, multi-objective tuning, config multi_objective


### v1.3 (2026-02-12)

- **Added**: Predictor Feature Alignment section — documents 3-tier mismatch handling (drop extras, impute missing, error on zero overlap)
- **Added**: Concurrent Training Safety section — 409 Conflict for duplicate target training requests
- **Added**: Structured Logging section — `gddt.*` namespace, per-stage timing breakdown
- **Added**: MLflow per-stage conventions — EDA, diagnostics, champion, and timing metrics with `gbdt/{granularity}/{target}` experiment naming
- **Implemented**: `GBDTPredictor.predict()` now handles feature alignment gracefully instead of raising ValueError for any missing feature
- **Implemented**: `POST /gbdt/train` returns 409 if training already in progress for the target
- **Implemented**: Per-stage timing in `run_full_pipeline()` with `stage_timings` in results dict
- **Implemented**: `_log_to_mlflow()` now logs per-stage metrics (EDA, diagnostics, champion, timings)

### v1.2 (2026-02-12)

- **Added**: Serving Architecture section — dual-save mechanism, artifact directories, two access paths (unified vs direct), artifact file inventory, unified registry integration, MLflow role clarification
- **Fixed**: `GBDT_SERVING_DIR` corrected from `serving/gbdt/` to `serving/artifacts/gbdt/` (aligned with `UnifiedModelRegistry` scan path)
- **Fixed**: Champion/challenger serving directory naming from `{target}/champion/` to `{target}_{granularity}/champion/` (matches registry's `_extract_gbdt_metadata()` parsing)
- **Fixed**: `UnifiedModelRegistry._extract_gbdt_metadata()` now reads `metadata.json` first, falls back to directory name parsing (handles compound targets like `TS_PCT`)
- **Fixed**: `GBDTAPI.list_models()` reads target/granularity from `metadata.json` instead of directory name
- **Updated**: Module Purposes Serving table — added unified serving layer modules, corrected artifact paths
- **Updated**: Data Flow diagram — shows dual-save destination paths
- **Updated**: Design Principles — added metadata-first discovery principle

### v1.1 (2026-02-11)

- **Added**: Suitability Score section with transparent penalty table
- **Added**: Feature Profiling section with `FeatureProfile` dataclass
- **Added**: Schema Validation section with pre-flight `validate_schema()` checks
- **Added**: Forbidden Feature Suggestion section with 3-strategy leakage detection
- **Added**: Dataset-specific filters documentation
- **Updated**: Tests section expanded from 20 to 25 tests

### v1.0 (2026-02-10)

- Initial guide covering full 32-file GBDT pipeline
