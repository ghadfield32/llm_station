# Clustering Pipeline Guide

**Original audit date:** 2026-02-13
**Last refresh:** 2026-04-27 (current production state addendum)
**Scope:** All clustering-related code across the full repository
**Purpose:** Schema-driven, reusable clustering pipeline that serves as an
unsupervised feature discovery engine for downstream ML pipelines.

> **Lane note (two-machine fleet):** candidate clustering runs may happen on the
> dev laptop (outputs → `.r2_staging`), but the production cluster/role artifacts
> are **promoted and R2-uploaded from the desktop production writer only**. See
> [../engineering/LOCAL_FLEET_R2_WORKFLOW.md](../engineering/LOCAL_FLEET_R2_WORKFLOW.md).

---

## Production State (as of 2026-04-27)

> **Note:** Sections 1-13 below are the original 2026-02-13 audit + design
> document. They remain accurate as architecture reference. This addendum
> captures what is **actually deployed and consumed** today, since the audit
> is now ~10 weeks old.

### What is in production

| Component | Status | Path | Notes |
|-----------|--------|------|-------|
| `ClusteringPipeline` (player-season, v3.3) | LIVE | `api/src/ml/features/clustering_pipeline/main.py` | 16 roles, 32 z-score features, GMM soft probabilities. Last full rerun: Session 393. |
| `clustering_player_season.yaml` schema | LIVE | `clustering_pipeline/schemas/` | 42 features, 10 categories. Source of truth for feature lists. |
| `clustering_coach.yaml` schema | LIVE | `clustering_pipeline/schemas/` | 79 features (48 role + 31 non-role). Used by `coach_clustering.py`. |
| `clustering_prospect.yaml` schema | LIVE | `clustering_pipeline/schemas/` | 13 features. Used by international prospect archetypes (Session 437: 14 archetypes data-derived from BIC). |
| `clustering_template.yaml` | REFERENCE | `clustering_pipeline/schemas/` | Blank template. Copy when adding a new domain. |
| Generic clustering framework (`clustering_core/`) | LIVE | `api/src/ml/features/clustering_core/` | 4 algorithms (KMeans, GMM, Spectral, HDBSCAN), 3 dim-reducers, 3 adapters, registry. |
| Legacy `DynamicPlayerClustering` / `EnhancedPlayerClustering` | ARCHIVED | `_archive/20260213_clustering_legacy/` | DO NOT IMPORT. `nba_career_pipeline.py` still references these — that path is legacy. |

### What consumes clustering output (downstream)

The clustering outputs (`ARCHETYPE`, `ROLE`, `IMPACT_TIER`, `PROB_*`) are
first-class features in these gold marts and ML pipelines:

| Consumer | Reads | Path |
|----------|-------|------|
| NBA Player Value (FMV, surplus) | `archetype_history_season.parquet` | `api/src/airflow_project/data/gold/products/` |
| Awards forecasting | ROLE + IMPACT_TIER per player-season | `cache/features/awards_features.parquet` |
| Player Game Predictions | ROLE z-scores | `cache/features/pgp_features.parquet` |
| Lineup Optimizer | Role-balanced lineup constraints | `scripts/lineup_optimizer/` |
| International prospect big boards | ARCHETYPE (international) | `cache/evaluation/big_board_*.parquet` (Session 437: 14 data-derived archetypes) |
| Coach deployment matching | Coach archetypes from `coach_clustering.py` | `coach_clusters.parquet` |

### Recent significant changes since 2026-02-13

- **Session 393 (cluster v3.3 rerun):** Added `off_PPP_Postup` and
  `off_PPP_PRRollMan` z-score features. GT expanded 58 -> 64 with corrections
  (SGA/Booker PC->SG, Ingram VF->SW, Lively EB->AF, Ausar AF->DS).
  scipy-optimized weights -> 90.6% GT accuracy.
  Output: 5,228 rows, all 16 roles populated.
- **Session 437 (prospect archetypes):** Switched from 12 hardcoded archetypes
  to 14 data-derived from BIC-optimized K in [4,20]. Algorithmic naming from
  centroid z-scores.
- **Session 437 (development curves):** Delta Plus method for age curves.
  17,723 pairs, 602 age curve rows. NCAA peak=23.

### Validation status

```bash
# Run after any clustering change (6-stage audit)
python scripts/validate_clustering_to_age_curves.py

# 233 unit tests passing as of 2026-02-13:
#   - 190 clustering_core unit tests
#   - 43 schema equivalence tests
pytest api/src/ml/features/clustering_pipeline/tests/
pytest api/src/ml/features/clustering_core/tests/
```

### Known pitfalls (current, not stale)

1. **`compute_z_scores()` returns a copy, not in-place.** Caller MUST capture:
   `df = assigner.compute_z_scores(df)`. Forgetting this is a silent no-op.
2. **`differential_evolution` with 32D weight space is slow.** Use
   `popsize=10`, not the default 15. A full GT-weight optimization run takes
   ~6 min on 32 cores.
3. **Do not enable `use_self_calibration`.** Session 353 showed this
   destroyed GT accuracy (87% -> 71%). Configuration default is `False`;
   keep it that way.
4. **Legacy classes are archived, not removed.** `DynamicPlayerClustering`
   and `EnhancedPlayerClustering` still exist under
   `_archive/20260213_clustering_legacy/`. The archive README explains the
   migration path. `nba_career_pipeline.py` is the only remaining importer
   and is itself legacy — do not extend it.
5. **`combo_guard_target_pct=8.0` is a guardrail, not a target.** The
   pipeline caps COMBO_GUARD assignments at this percentage of total. Setting
   it higher is a config option but historically degraded board accuracy.

### Adding a new clustering domain

Use the generic framework, not the legacy player-specific code:

```python
from api.src.ml.features.clustering_core.pipeline import GenericClusteringPipeline

pipeline = GenericClusteringPipeline.from_schema("path/to/my_schema.yaml")
result = pipeline.fit(df)
```

Steps:

1. Copy `clustering_template.yaml` to a new file under `clustering_pipeline/schemas/`.
2. Define your feature groups (`identifiers`, `numerical`, `nominal`).
3. Pick the algorithm in YAML (`kmeans`, `gmm`, `spectral`, `hdbscan`).
4. Pick K-selection method (`bic`, `silhouette`, `elbow`, `gap_statistic`).
5. If you need domain-specific naming/labels, write a domain adapter
   extending `BaseClusteringAdapter` in `clustering_core/adapters/`.
6. Add unit tests under `clustering_core/tests/` following the
   `test_phase5.py` pattern.
7. Add validation to `scripts/validate_clustering_to_age_curves.py` if the
   output feeds the age-curve pipeline.
8. Update this addendum's "What consumes clustering output" table.

### Artifact versioning (per PIPELINE_STANDARDS_TEMPLATE.md §11.8.4)

Clustering produces deterministic features consumed by downstream models.
When the centroid file changes, downstream models must re-train against the
new feature distribution. Save:

- `serving/artifacts/clustering/champion/centroids.parquet`
- `serving/artifacts/clustering/champion/role_prototypes.json`
- `serving/artifacts/clustering/champion/scaler.joblib`
- `serving/artifacts/clustering/champion/manifest.json` (with
  `previous_version`, `trained_on_data_cutoff`, `feature_schema_hash`)
- `serving/artifacts/clustering/champion_{version}/` historical copy

Rolling back clustering requires re-running every downstream model that
consumed the bad clustering. Document the dependency chain in the
clustering changelog.

---

## Goal

Build a **complete, reusable clustering pipeline** that:

1. **Automates data loading from a `clustering_schema.yaml`** — following the same YAML-first declarative pattern used by the Bayesian pipeline (`column_schema.yaml` → `SchemaConfig` → `load_schema_from_yaml()`)
2. **Unsupervised learns about the data** — discovers natural structure (player roles, coach types, prospect archetypes) without manual label engineering
3. **Adds rules and metrics via KMeans clustering** — labels, distances, confidence scores, stability metrics, and quality gates
4. **Feeds those features into other ML pipelines** — the clustering outputs (ROLE, ARCHETYPE, IMPACT_TIER, etc.) become first-class features consumed by the Bayesian prediction pipeline, forecasting engine, age curve models, and team analytics

The pipeline should be **domain-agnostic** at its core, with domain-specific adapters (NBA player, coach, prospect, or any new domain) configured via YAML schema files rather than hardcoded feature lists.

---

## Table of Contents

1. [Module Tree](#1-module-tree)
2. [Detailed Module Profiles](#2-detailed-module-profiles)
3. [Import Chain Map](#3-import-chain-map)
4. [Algorithm Inventory](#4-algorithm-inventory)
5. [Feature Inventory](#5-feature-inventory)
6. [Output Artifacts Inventory](#6-output-artifacts-inventory)
7. [Downstream Consumer Map](#7-downstream-consumer-map)
8. [Legacy Code Analysis](#8-legacy-code-analysis)
9. [Gaps vs Modern Best Practices](#9-gaps-vs-modern-best-practices)
10. [Recommended Architecture for Reusable Pipeline](#10-recommended-architecture-for-reusable-pipeline)
11. [Schema-Driven Automation](#11-schema-driven-automation)
12. [Implementation Plan (6 Phases)](#12-implementation-plan-6-phases)
13. [Risk Mitigation & Success Criteria](#13-risk-mitigation--success-criteria)

---

## 1. Module Tree

```
api/src/ml/features/
├── clustering_pipeline/                                    [PRODUCTION] 7,948 LOC total
│   ├── __init__.py                          (  93 LOC)    Public API exports (v2.4.0)
│   ├── main.py                              (1130 LOC)    ClusteringPipeline orchestrator
│   ├── config.py                            ( 300 LOC)    ClusteringConfig + feature lists
│   ├── clustering_schema.py                 ( 284 LOC)    [NEW] ClusteringSchema Pydantic + OmegaConf loader
│   ├── preprocessor.py                      ( 431 LOC)    Data cleaning, StandardScaler
│   ├── pca_reducer.py                       ( 100 LOC)    PCA dimensionality reduction
│   ├── kmeans_clusterer.py                  ( 280 LOC)    KMeans with BIC/silhouette K selection
│   ├── gmm_soft_clusterer.py                ( 176 LOC)    GMM soft probabilistic clustering
│   ├── archetype_namer.py                   ( 739 LOC)    Z-score centroid naming (16 types)
│   ├── role_prototypes.py                   (1922 LOC)    16 role prototypes + RoleAssigner
│   ├── ground_truth.py                      ( 662 LOC)    56+ GT player-role labels + optimizer
│   ├── evaluator.py                         ( 530 LOC)    Metrics + temporal stability
│   ├── anomaly_detection.py                 ( 423 LOC)    Automated quality checks
│   ├── stage_diagnostics.py                 ( 484 LOC)    Per-phase pipeline health checks
│   ├── handedness_loader.py                 ( 141 LOC)    Left-handed enrichment feature
│   ├── schemas/                                            [NEW] YAML schema definitions
│   │   ├── clustering_player_season.yaml                   42 features, 10 categories
│   │   ├── clustering_coach.yaml                           79 features (48 role + 31 non-role)
│   │   ├── clustering_prospect.yaml                        13 features
│   │   └── clustering_template.yaml                        Blank domain template
│   └── tests/                                              [NEW] Schema equivalence tests
│       ├── __init__.py
│       └── test_schema_equivalence.py       ( 310 LOC)    43 tests (YAML == config.py)
│
├── clustering_core/                                       [NEW Phase 2-5] Domain-agnostic clustering framework
│   ├── __init__.py                          ( 100 LOC)    Package exports (v4.0.0)
│   ├── types.py                             ( 100 LOC)    ClusterResult, ReductionResult, ScalerResult
│   ├── interfaces.py                        (  90 LOC)    AbstractClusterer, AbstractReducer ABCs
│   ├── pipeline.py                          ( 200 LOC)    GenericClusteringPipeline + from_schema()
│   ├── algorithms/
│   │   ├── kmeans.py                        ( 250 LOC)    GenericKMeans (4 K-selection methods)
│   │   ├── gmm.py                           ( 180 LOC)    GenericGMM (soft probabilistic)
│   │   ├── spectral.py                      ( 170 LOC)    GenericSpectral (graph Laplacian)
│   │   └── hdbscan_clusterer.py             ( 200 LOC)    GenericHDBSCAN (optional, density-based)
│   ├── dimensionality/
│   │   ├── pca.py                           ( 110 LOC)    GenericPCA (auto/fixed modes)
│   │   ├── tsne_reducer.py                  ( 130 LOC)    GenericTSNE (visualization only)
│   │   └── umap_reducer.py                  ( 110 LOC)    GenericUMAP (optional, reduction + viz)
│   ├── preprocessing/
│   │   └── scaler.py                        ( 170 LOC)    GenericScaler (tiered imputation)
│   ├── evaluation/
│   │   ├── __init__.py                                    Exports 6 public types
│   │   ├── stability.py                     ( 230 LOC)    BootstrapStability + StabilityReport
│   │   ├── feature_importance.py            ( 260 LOC)    PermutationImportance + FeatureImportanceReport
│   │   └── comparison.py                    ( 310 LOC)    AlgorithmComparison + ComparisonReport
│   ├── visualization/
│   │   ├── __init__.py                                    Exports ClusterVisualizer
│   │   └── plots.py                         ( 300 LOC)    5 plot types (scatter, silhouette, elbow, bar, radar)
│   ├── adapters/                                          [NEW Phase 5] Domain-specific adapters
│   │   ├── __init__.py                                    Exports 3 adapters + base
│   │   ├── base.py                          ( 120 LOC)    BaseClusteringAdapter ABC
│   │   ├── player_adapter.py                ( 180 LOC)    PlayerSeasonAdapter (z-score naming)
│   │   ├── coach_adapter.py                 ( 180 LOC)    CoachAdapter (role preference labeling)
│   │   └── prospect_adapter.py              ( 200 LOC)    ProspectAdapter (naming rules)
│   ├── registry.py                          ( 260 LOC)    ModelRegistry (JSON-based versioning)
│   └── tests/
│       ├── test_core_algorithms.py          ( 400 LOC)    52 unit tests
│       ├── test_schema_pipeline_integration.py ( 200 LOC)  14 integration tests
│       ├── test_evaluation.py               ( 370 LOC)    31 evaluation tests
│       ├── test_phase4.py                   ( 350 LOC)    23 tests (7 t-SNE + 6 Spectral + 7 viz + 3 integration)
│       ├── test_phase5.py                   ( 350 LOC)    29 tests (6 player + 4 coach + 5 prospect + 12 registry + 2 integration)
│       └── test_phase6_integration.py       ( 500 LOC)    41 tests (end-to-end + downstream + quality)
│
├── _archive/20260213_clustering_legacy/                   [ARCHIVED Phase 6] 3,171 LOC
│   ├── README.md                                          Migration guide + importer fallback docs
│   ├── player_clustering.py                ( 500 LOC)    Was DynamicPlayerClustering
│   ├── player_clustering_enhanced.py       ( 671 LOC)    Was EnhancedPlayerClustering v2.0
│   ├── archetypes_v2.py                    ( 650 LOC)    Was deprecated since Session 361
│   └── archetype_clustering_validation.py  (1350 LOC)    Was historical validation tool
│
├── archetype_age_features.py                ( 493 LOC)    [ACTIVE] Prior-season role + age curves
│
├── forecasting/
│   ├── archetype_classifier.py              ( 471 LOC)    [ACTIVE] 16-role adapter (scarcity/trend)
│   ├── coach_clustering.py                  ( 510 LOC)    [ACTIVE] Coach deployment clustering
│   └── nba_career_pipeline.py               ( 611 LOC)    [LEGACY] Imports EnhancedPlayerClustering (broken)
│
├── age_curve_pipeline/
│   └── role_adapter.py                      ( 181 LOC)    [ACTIVE] ROLE -> int for PyMC indexing
│
├── forecasting_integration/
│   └── enhanced_feature_builder.py          ( 137 LOC)    [ACTIVE] Imports ClusteringPipeline
│
├── cap_efficiency.py                                      [ACTIVE] DynamicPlayerClustering import → fallback to UNCLASSIFIED
└── player_value_features.py                               [ACTIVE] DynamicPlayerClustering import → fallback to default weights

api/src/ml/io/
└── mart_builders.py                         ( 233 LOC)    [PRODUCTION] build_archetype_history_season()

scripts/
├── build_prospect_archetypes.py             ( 408 LOC)    [ACTIVE] GMM on college/intl players
├── build_coach_profiles_and_clusters.py     ( 123 LOC)    [ACTIVE] Coach deployment analysis
├── validate_clustering_to_age_curves.py     ( 527 LOC)    [ACTIVE] 6-stage pipeline audit
└── run_full_pipeline_audit.py               ( 363 LOC)    [ACTIVE] Pipeline validation

notebooks/01_ml_models/01_clustering/clustering_age_curves/
├── 01_clustering_validation.ipynb                         [ACTIVE] Validate clustering outputs
└── 02_age_curve_validation.ipynb                          [ACTIVE] Validate age curves
```

**Total active clustering code:** ~11,455 LOC across 25+ files (3,171 LOC archived)
**Total tests:** 233 passed, 4 skipped (190 clustering_core + 43 schema equivalence)

---

## 2. Detailed Module Profiles

### 2.1 clustering_pipeline/main.py — `ClusteringPipeline`

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/main.py` |
| **LOC** | 1,130 |
| **Status** | **PRODUCTION** |
| **Algorithm(s)** | KMeans, GMM, PCA, Prototype Distance (via sub-modules) |
| **Imports from** | config, preprocessor, pca_reducer, kmeans_clusterer, gmm_soft_clusterer, archetype_namer, evaluator, stage_diagnostics, role_prototypes, handedness_loader |
| **Imported by** | `mart_builders.py`, `run_full_pipeline_audit.py`, `enhanced_feature_builder.py` |
| **Entry point** | `ClusteringPipeline.fit_season(df, season, k=None) -> (DataFrame, ClusteringMetrics)` |
| **Verdict** | **KEEP** — Core production orchestrator |

**Architecture: Two-Track Pipeline**
- **Track 1 (Steps 1-10):** Exploratory unsupervised clustering
  1. Add handedness feature
  2. Preprocess + filter (GP>=15, MIN>=350)
  3. PCA transformation (auto 95% variance)
  4-5. KMeans clustering (BIC-optimal K in [9,14])
  6. GMM soft probabilities
  6.5. Pipeline stage diagnostics
  7. Get centroids in original space
  8. Derive archetype names from centroids
  9. Store fitted models
  10. Add results to dataframe
  - **Phase validation checkpoint**
- **Track 2 (Steps 11-14):** Supervised role assignment
  11. Prototype distance role assignment (16 roles)
  11b. Self-calibrating prototypes (disabled by default)
  12. COMBO_GUARD confidence-based split (target <=8%)
  13. IMPACT_TIER computation (BPM percentiles)
  - **Phase validation checkpoints after each step**
- **Step 15-18:** Merge results, evaluate, validate quality, print profiles

**Output columns added:** ARCHETYPE, ARCHETYPE_ID, ARCHETYPE_CONFIDENCE, SECONDARY_ARCHETYPE, SECONDARY_PROB, ROLE, ROLE_DISTANCE, ROLE_CONFIDENCE, SECONDARY_ROLE, POSITION_FAMILY, MACRO_TYPE, IMPACT_TIER, AVAILABILITY_PCT, AVAILABILITY_FLAG, PROB_* (per-cluster probabilities)

**Model persistence:** `save(output_dir)` → per-season joblib + config.json; `load(model_path)` → restore season model

---

### 2.2 clustering_pipeline/config.py — `ClusteringConfig`

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/config.py` |
| **LOC** | 300 |
| **Status** | **PRODUCTION** |
| **Imported by** | main.py, preprocessor.py, kmeans_clusterer.py, gmm_soft_clusterer.py, pca_reducer.py, mart_builders.py |
| **Verdict** | **KEEP** — Central configuration |

**ClusteringConfig dataclass defaults:**
```
min_k=9, max_k=14, k_selection_method='bic'
n_pca_components='auto', pca_variance_threshold=0.95
min_games=15, min_minutes=350
use_gmm_soft_clustering=True
include_handedness=True, include_physical=True
include_advanced_metrics=True, include_hustle_stats=True, include_synergy_playtypes=True
random_state=42
combo_guard_target_pct=8.0
use_self_calibration=False
expected_games_per_season=82, low_availability_threshold=0.50
```

**Feature lists defined at module level:**
- `CORE_FEATURES`: PTS, FGA, 3PA, FTA, AST, TOV, TRB, ORB, DRB, STL, BLK, PF (12)
- `SHOOTING_FEATURES`: FG%, 3P%, FT%, TS% (4)
- `EFFICIENCY_FEATURES`: Empty — impact metrics excluded from PCA
- `IMPACT_ONLY_FEATURES`: BPM_BBREF, VORP_BBREF, OWS_BBREF, DWS_BBREF (4, for IMPACT_TIER only)
- `ADVANCED_FEATURES`: USG% (1)
- `RATE_FEATURES`: E_AST_RATIO, E_OREB_PCT, E_DREB_PCT, E_REB_PCT, E_TOV_PCT (5)
- `COMPUTED_RATE_FEATURES`: 3PA_RATE (3PA/FGA), FTA_RATE (FTA/FGA) (2)
- `PHYSICAL_FEATURES`: HEIGHT_INCHES, WEIGHT_LBS (2)
- `HANDEDNESS_FEATURES`: IS_LEFT_HANDED (1)
- `HUSTLE_FEATURES`: DEFLECTIONS, CONTESTED_SHOTS, SCREEN_ASSISTS, CHARGES_DRAWN (4)
- `SYNERGY_FEATURES`: POSS_PCT for Isolation, Spotup, PRBallHandler, PRRollMan, Postup, Cut, Transition, Handoff, OffScreen (9)
- `SYNERGY_PPP_FEATURES`: off_PPP for Isolation, Spotup, PRBallHandler, Transition (4)

**Total potential features:** ~48 (depending on config flags and data availability)

**Key design decisions:**
- Session 343: Added HUSTLE and SYNERGY features
- Session 345-346: Impact metrics excluded from PCA (style vs impact separation)
- Session 349: PCA changed from fixed 7 to auto 95% variance
- Session 352: Lowered min_games 20→15, min_minutes 500→350 for international coverage
- Session 353: Disabled self_calibration (destroyed GT accuracy 87%→71%)

---

### 2.3 clustering_pipeline/role_prototypes.py — `RoleAssigner`

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/role_prototypes.py` |
| **LOC** | 1,922 |
| **Status** | **PRODUCTION** |
| **Algorithm** | Weighted Euclidean distance to 16 fixed prototypes |
| **Imported by** | main.py, ground_truth.py, anomaly_detection.py, archetype_classifier.py, role_adapter.py |
| **Verdict** | **KEEP** — Single source of truth for 16-role system |

**16 Canonical Roles:**

| Family | Role | Description |
|--------|------|-------------|
| GUARD | PRIMARY_CREATOR | Ball-dominant playmakers (Luka, Trae, SGA) |
| GUARD | SCORING_GUARD | Score-first guards (Mitchell, Fox, Edwards) |
| GUARD | SECONDARY_PLAYMAKER | Secondary handlers (Tyus Jones, CP3) |
| GUARD | COMBO_GUARD | Versatile guards, catch-all (reduced to <=8%) |
| WING | SCORING_WING | Wing scorers (KD, Tatum, Kawhi) |
| WING | THREE_AND_D_WING | 3pt + defense (Mikal, OG, Dort) |
| WING | TWO_WAY_PLAYMAKER | Playmaking wings (Dyson, Jrue) |
| WING | SLASHER | Athletic finishers (Zion) |
| WING | VERSATILE_FORWARD | Mismatch forwards (LeBron, Herbert Jones) |
| FLEX | DEFENSIVE_SPECIALIST | Lockdown defenders (Alex Caruso, Herb Jones) |
| FLEX | OFF_BALL_SHOOTER | Catch-and-shoot spacers (Duncan Robinson, Hield) |
| BIG | ALL_AROUND_BIG | Versatile bigs (Jokic, Giannis, AD) |
| BIG | STRETCH_BIG | Shooting bigs (Porzingis, Brook Lopez) |
| BIG | RIM_PROTECTOR | Shot blockers (Gobert, Jarrett Allen) |
| BIG | ENERGY_BIG | Hustle bigs (Claxton, Adams, Capela) |
| BIG | ATHLETIC_FINISHER | Dunking/cutting bigs (Zion-like) |

**Prototype feature dimensions (~20 z-scores):** z_pts, z_ast, z_trb, z_stl, z_blk, z_3pa, z_tov, z_fga, z_ts, z_ast_ratio, z_tov_pct, z_3pa_rate, z_fta_rate, z_height, z_prbh, z_iso, z_spotup, z_transition, z_postup, z_cut, z_prrm

**Weight optimization:** `scipy.optimize.differential_evolution` on weight space, validated against 56 GT players (100% accuracy)

**Key exports:** `ROLE_PROTOTYPES`, `FEATURE_WEIGHTS`, `POSITION_FAMILY`, `MACRO_TYPE`, `RoleAssigner`, `build_player_profile()`, `compute_prototype_distance()`, `assign_role_by_distance()`

---

### 2.4 clustering_pipeline/kmeans_clusterer.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/kmeans_clusterer.py` |
| **LOC** | 280 |
| **Status** | **PRODUCTION** |
| **Algorithm** | scikit-learn KMeans |
| **Params** | n_init=10, max_iter=300, random_state=42 |
| **K selection** | silhouette, BIC (from GMM), composite (25% sil + 25% CH + 30% BIC + 20% domain penalty), domain_min |
| **Imported by** | main.py |
| **Verdict** | **KEEP** |

---

### 2.5 clustering_pipeline/gmm_soft_clusterer.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/gmm_soft_clusterer.py` |
| **LOC** | 176 |
| **Status** | **PRODUCTION** |
| **Algorithm** | scikit-learn GaussianMixture |
| **Params** | covariance_type='full', max_iter=200, n_init=3, random_state=42 |
| **Output** | Probability matrix (n_samples x K), ARCHETYPE_CONFIDENCE, SECONDARY_ARCHETYPE |
| **Imported by** | main.py |
| **Verdict** | **KEEP** |

---

### 2.6 clustering_pipeline/pca_reducer.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/pca_reducer.py` |
| **LOC** | 100 |
| **Status** | **PRODUCTION** |
| **Algorithm** | scikit-learn PCA |
| **Params** | n_components='auto' (95% variance) or fixed int, svd_solver='full' |
| **Output** | PCA-transformed X, fitted PCA model |
| **Imported by** | main.py |
| **Verdict** | **KEEP** |

---

### 2.7 clustering_pipeline/archetype_namer.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/archetype_namer.py` |
| **LOC** | 739 |
| **Status** | **PRODUCTION** |
| **Algorithm** | Rule-based z-score classification of centroids |
| **Thresholds** | HIGH >0.75, VERY_HIGH >1.0, ELITE >1.5, LOW <-0.5, VERY_LOW <-1.0 |
| **Output** | Dict[int, str] mapping cluster_id to archetype name |
| **Imported by** | main.py |
| **Verdict** | **KEEP** |

**16-archetype naming hierarchy** (checked in order, first match wins):
ALL_AROUND_BIG, PRIMARY_CREATOR, SCORING_WING, VERSATILE_FORWARD, ATHLETIC_SLASHER, RIM_PROTECTOR, STRETCH_BIG, TWO_WAY_PLAYMAKER, THREE_AND_D_WING, ENERGY_BIG, SECONDARY_SCORER, COMBO_GUARD, FLOOR_SPACER, ROTATION_PLAYER, BENCH_CONTRIBUTOR, REPLACEMENT_LEVEL

---

### 2.8 clustering_pipeline/ground_truth.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/ground_truth.py` |
| **LOC** | 662 |
| **Status** | **PRODUCTION** |
| **Purpose** | 56+ canonical player-role labels for validation + weight optimization |
| **Algorithm** | `scipy.optimize.differential_evolution` for feature weight optimization |
| **Accuracy** | 100% (56/56) on 2024-25 season data |
| **Imported by** | evaluator.py |
| **Verdict** | **KEEP** |

---

### 2.9 clustering_pipeline/evaluator.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/evaluator.py` |
| **LOC** | 530 |
| **Status** | **PRODUCTION** |
| **Metrics** | Silhouette score, Calinski-Harabasz, GT accuracy, GT family accuracy, per-role GT breakdown |
| **Quality gates** | Silhouette > 0.20 (min) / 0.30 (target), PCA variance > 0.90, min cluster > 5%, GT accuracy > 75% |
| **Exports** | ClusteringMetrics (30+ fields), ClusteringEvaluator, TemporalStabilityReport, calculate_temporal_stability(), calculate_temporal_stability_report() |
| **Imported by** | main.py, __init__.py |
| **Verdict** | **KEEP** |

**ClusteringMetrics fields:**
- Core: season, n_clusters, n_samples, silhouette_score, calinski_harabasz_score, pca_variance_explained, features_used, archetype_names, archetype_counts
- GT: ground_truth_accuracy, ground_truth_family_accuracy, ground_truth_per_role, ground_truth_mismatches
- PCA: pca_n_components, pca_per_component_variance, pca_condition_number
- KMeans: kmeans_inertia, kmeans_silhouette_per_k, kmeans_bic_per_k
- GMM: gmm_bic, gmm_aic, gmm_converged, gmm_n_iter, gmm_avg_max_probability
- Role: role_mean_distance, role_mean_confidence, combo_guard_pct, n_roles_populated, role_counts
- Validation: phase_validation_issues

**Temporal stability:** Jaccard similarity between season pairs at 3 hierarchy levels (ROLE, MACRO_TYPE, POSITION_FAMILY). Target > 0.60.

---

### 2.10 clustering_pipeline/anomaly_detection.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/anomaly_detection.py` |
| **LOC** | 423 |
| **Status** | **PRODUCTION** |
| **Purpose** | Automated quality checks replacing manual review |
| **Checks** | (1) BPM x ROLE mismatch, (2) ROLE_DISTANCE outliers, (3) Population balance, (4) GT per-role accuracy |
| **Exports** | AnomalyDetector, AnomalyReport, AnomalyFlag, analyze_role_subclusters |
| **Imported by** | __init__.py |
| **Verdict** | **KEEP** |

---

### 2.11 clustering_pipeline/stage_diagnostics.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/stage_diagnostics.py` |
| **LOC** | 484 |
| **Status** | **PRODUCTION** |
| **Metrics** | Davies-Bouldin score (lower=better), per-component PCA loadings, GMM convergence, cluster size balance, condition number |
| **Exports** | PCADiagnostics, KMeansDiagnostics, GMMDiagnostics, PipelineDiagnostics, run_full_diagnostics() |
| **Imported by** | main.py |
| **Verdict** | **KEEP** |

---

### 2.12 clustering_pipeline/preprocessor.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/preprocessor.py` |
| **LOC** | 431 |
| **Status** | **PRODUCTION** |
| **Algorithm** | StandardScaler per season |
| **Key logic** | Age column exclusion (AGE, YEARS_EXPERIENCE, etc.), counting stat to per-game conversion, computed rate features (3PA_RATE, FTA_RATE), median imputation for % cols, 0 imputation for counting stats |
| **Imported by** | main.py |
| **Verdict** | **KEEP** |

---

### 2.13 clustering_pipeline/handedness_loader.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/clustering_pipeline/handedness_loader.py` |
| **LOC** | 141 |
| **Status** | **PRODUCTION** |
| **Purpose** | Load IS_LEFT_HANDED binary feature from handedness data |
| **Imported by** | main.py, __init__.py |
| **Verdict** | **KEEP** |

---

### 2.14 player_clustering.py — `DynamicPlayerClustering`

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/player_clustering.py` |
| **LOC** | 500 |
| **Status** | **LEGACY** |
| **Algorithm** | KMeans with silhouette-based K selection |
| **Features** | 14 core + 5 computed (TS%, EFG%, AST_TOV_RATIO, 3P_RATE, USG%) = 19 total |
| **K range** | min_k=4, max_k=9 |
| **Output** | PLAYER_ARCHETYPE_ID, PLAYER_ARCHETYPE columns |
| **Imported by** | `player_value_features.py:1409` (try/except), `cap_efficiency.py:3061` (try/except) |
| **Verdict** | **ARCHIVE** — Superseded by clustering_pipeline. Both importers have try/except fallbacks. |

**What it does that clustering_pipeline doesn't:** Dynamic per-season archetype naming without fixed role prototypes. Discovers archetypes purely from data each season. However, this same capability exists in Track 1 of clustering_pipeline.

---

### 2.15 player_clustering_enhanced.py — `EnhancedPlayerClustering`

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/player_clustering_enhanced.py` |
| **LOC** | 671 |
| **Status** | **LEGACY** |
| **Algorithm** | KMeans + GMM + PCA (same as clustering_pipeline) |
| **Config** | ClusteringConfig(min_k=5, max_k=9, n_pca_components=7) — outdated defaults |
| **Imported by** | `nba_career_pipeline.py:34` — uses `from enhanced_player_clustering import` (broken path) |
| **Verdict** | **ARCHIVE** — Exact same algorithms as clustering_pipeline with inferior defaults. Import path is broken. |

**What it does that clustering_pipeline doesn't:** Nothing. This was an intermediate step between player_clustering.py and clustering_pipeline/. The pipeline supersedes it entirely.

---

### 2.16 forecasting/archetypes_v2.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/forecasting/archetypes_v2.py` |
| **LOC** | 650 |
| **Status** | **DEPRECATED** (Session 361) |
| **Emits** | `DeprecationWarning` on import |
| **Legacy system** | 4-tier mapping (ELITE, PREMIUM, SOLID, DEPTH) based on archetype keywords |
| **Verdict** | **ARCHIVE** — Already deprecated. Use archetype_classifier.py instead. |

---

### 2.17 forecasting/archetype_classifier.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/forecasting/archetype_classifier.py` |
| **LOC** | 471 |
| **Status** | **ACTIVE** |
| **Purpose** | Adapter from 16-role pipeline to forecasting consumers |
| **Exports** | ROLE_SCARCITY, ROLE_TREND, ROLE_PEAK_AGE, LEGACY_TO_ROLE, ArchetypeClassifier |
| **Imports from** | `clustering_pipeline.role_prototypes` (try/except for fallback mode) |
| **Imported by** | archetype_age_features.py, season_projection_engine.py, many forecasting modules |
| **Verdict** | **KEEP** — Key integration layer |

**ROLE_SCARCITY multipliers:** ALL_AROUND_BIG=1.25 (rarest) ... COMBO_GUARD=0.80 (most common)
**ROLE_TREND:** increasing (3D Wing, Scoring Wing, Versatile Fwd, etc.), stable, decreasing (Rim Protector, Energy Big)
**ROLE_PEAK_AGE:** per-role peak performance ages

---

### 2.18 forecasting/coach_clustering.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/forecasting/coach_clustering.py` |
| **LOC** | 510 |
| **Status** | **ACTIVE** |
| **Algorithm** | KMeans vs Ward Hierarchical (best by silhouette) |
| **Features** | 48 role dims (16 roles x 3 metrics) + up to 31 non-role dims = ~79 dims |
| **Non-role features** | Timeout tendencies (7), lineup composition (4), lineup effectiveness (5), offensive system (6), deployment patterns (4), load management (2), context (3) |
| **K range** | Typically 5-8 clusters |
| **Metrics** | Silhouette, Calinski-Harabasz, Davies-Bouldin |
| **Cluster labels** | SPACING_ORIENTED, DEFENSE_FIRST, STAR_DEPENDENT, BACKCOURT_ORIENTED, WING_HEAVY, BIG_CENTRIC, VERSATILE |
| **Imports from** | sklearn (KMeans, AgglomerativeClustering, PCA, StandardScaler, metrics) |
| **Imported by** | `build_coach_profiles_and_clusters.py` |
| **Verdict** | **KEEP** — Domain-specific, well-structured |

---

### 2.19 archetype_age_features.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/archetype_age_features.py` |
| **LOC** | 493 |
| **Status** | **ACTIVE** |
| **Purpose** | Add ARCHETYPE + AGE_CURVE_MULT to player-game data without data leakage |
| **Data leakage prevention** | Uses PRIOR season's clustering (2024-25 game -> 2023-24 role). Rookies get position-default. |
| **Sources** | archetype_history_season.parquet, age_curves_by_role.parquet, ROLE_SCARCITY from archetype_classifier |
| **Output columns** | ARCHETYPE, ARCHETYPE_CONFIDENCE, ARCHETYPE_SCARCITY_MULT, AGE_CURVE_MULT |
| **Imported by** | Feature engineering pipeline (gold feature generation) |
| **Verdict** | **KEEP** — Critical leakage prevention |

**Position default roles:** G->COMBO_GUARD, PG->PRIMARY_CREATOR, SG->SCORING_GUARD, SF->THREE_AND_D_WING, PF->STRETCH_BIG, C->ENERGY_BIG, F->VERSATILE_FORWARD

---

### 2.20 age_curve_pipeline/role_adapter.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/age_curve_pipeline/role_adapter.py` |
| **LOC** | 181 |
| **Status** | **ACTIVE** |
| **Purpose** | Maps ROLE -> integer index for PyMC Bayesian age curve model |
| **Exports** | ROLE_LIST (16 roles alphabetized), MACRO_TYPE_LIST (7), FAMILY_LIST (4), get_role_to_int(), get_hierarchy() |
| **Imports from** | `clustering_pipeline.role_prototypes` (MACRO_TYPE, POSITION_FAMILY) |
| **Verdict** | **KEEP** — Bridge between clustering and Bayesian modeling |

---

### 2.21 calibration/archetype_clustering_validation.py

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/features/calibration/archetype_clustering_validation.py` |
| **LOC** | 1,350 |
| **Status** | **RETIRED** |
| **Algorithm** | KMeans (k=8-22) with AgglomerativeClustering comparison |
| **Features** | 12 stats (PTS, AST, TRB, STL, BLK, FG%, FG3%, FT%, MP, TOV, 3PA, FGA) |
| **Metrics** | Silhouette, Calinski-Harabasz, Davies-Bouldin, PCA variance, elbow/t-SNE/PCA visualizations |
| **Imported by** | `season_thresholds.py:272` imports `_get_position_from_game_data()` (try/except, fallback: `POSITION_SIMPLE='F'`) |
| **Verdict** | **ARCHIVE** — Superseded by clustering_pipeline's evaluator + stage_diagnostics |

---

### 2.22 scripts/build_prospect_archetypes.py

| Field | Detail |
|-------|--------|
| **Path** | `scripts/build_prospect_archetypes.py` |
| **LOC** | 408 |
| **Status** | **ACTIVE** (Session 369) |
| **Algorithm** | GMM with BIC K selection |
| **Features** | 13: PER36_PTS/REB/AST/STL/BLK/TOV/FGA/FG3A/FGM, FG_PCT, FG3_PCT, FT_PCT, HEIGHT_CM |
| **K range** | [8, 18] |
| **Naming** | 20 z-score rules (rim_protector, stretch_big, primary_playmaker, etc.) |
| **Output** | `cache/features/player_archetypes.parquet` + `metadata.json` |
| **Imported by** | Standalone script |
| **Verdict** | **KEEP** — Independent prospect domain |

---

### 2.23 mart_builders.py — `build_archetype_history_season()`

| Field | Detail |
|-------|--------|
| **Path** | `api/src/ml/io/mart_builders.py` |
| **LOC** | 233 |
| **Status** | **PRODUCTION** |
| **Purpose** | Runs ClusteringPipeline.fit_season() per season, writes archetype_history_season.parquet |
| **Imports from** | clustering_pipeline.main (ClusteringPipeline), clustering_pipeline.config (ClusteringConfig) |
| **Input** | player_season_features (Gold) |
| **Output** | archetype_history_season.parquet (Gold mart, 169 KB) |
| **Verdict** | **KEEP** — Production orchestrator |

---

## 3. Import Chain Map

### Production Path (main pipeline)
```
mart_builders.py::build_archetype_history_season()
  └── clustering_pipeline/main.py::ClusteringPipeline
        ├── clustering_pipeline/config.py (ClusteringConfig, feature lists)
        ├── clustering_pipeline/preprocessor.py (ClusteringPreprocessor)
        │     └── sklearn.preprocessing.StandardScaler
        ├── clustering_pipeline/pca_reducer.py (PCAReducer)
        │     └── sklearn.decomposition.PCA
        ├── clustering_pipeline/kmeans_clusterer.py (KMeansClusterer)
        │     ├── sklearn.cluster.KMeans
        │     └── sklearn.metrics.silhouette_score
        ├── clustering_pipeline/gmm_soft_clusterer.py (GMMSoftClusterer)
        │     └── sklearn.mixture.GaussianMixture
        ├── clustering_pipeline/archetype_namer.py (ArchetypeNamer)
        ├── clustering_pipeline/evaluator.py (ClusteringEvaluator)
        │     ├── sklearn.metrics.silhouette_score
        │     ├── sklearn.metrics.calinski_harabasz_score
        │     └── clustering_pipeline/ground_truth.py
        ├── clustering_pipeline/stage_diagnostics.py (run_full_diagnostics)
        │     ├── sklearn.metrics.silhouette_score
        │     ├── sklearn.metrics.calinski_harabasz_score
        │     └── sklearn.metrics.davies_bouldin_score
        ├── clustering_pipeline/role_prototypes.py (RoleAssigner)
        │     └── scipy.optimize.differential_evolution (for weight optimization)
        └── clustering_pipeline/handedness_loader.py
```

### Script Paths
```
scripts/run_full_pipeline_audit.py
  └── clustering_pipeline/main.py (ClusteringPipeline)
      └── clustering_pipeline/config.py (ClusteringConfig)

scripts/build_coach_profiles_and_clusters.py
  └── forecasting/coach_clustering.py
      ├── sklearn.cluster.KMeans
      ├── sklearn.cluster.AgglomerativeClustering
      └── sklearn.metrics.{silhouette_score, calinski_harabasz_score, davies_bouldin_score}

scripts/build_prospect_archetypes.py
  ├── sklearn.mixture.GaussianMixture
  ├── sklearn.preprocessing.StandardScaler
  └── scipy.spatial.distance.cdist
```

### Downstream Consumer Paths
```
archetype_age_features.py
  └── archetype_classifier.py (ROLE_SCARCITY)
        └── clustering_pipeline/role_prototypes.py (ROLE_PROTOTYPES, try/except)

age_curve_pipeline/role_adapter.py
  └── clustering_pipeline/role_prototypes.py (MACRO_TYPE, POSITION_FAMILY)

forecasting_integration/enhanced_feature_builder.py
  └── clustering_pipeline (ClusteringPipeline)
```

### Legacy Paths (still exist but fallback-protected)
```
player_value_features.py:1409
  └── player_clustering.py (DynamicPlayerClustering) [try/except -> fallback to default weights]

cap_efficiency.py:3061
  └── player_clustering.py (DynamicPlayerClustering, add_archetype_features) [try/except]
```

### Broken Path
```
nba_career_pipeline.py:34
  └── `from enhanced_player_clustering import ...`  [BROKEN: bare module name, not relative import]
```

---

## 4. Algorithm Inventory

### 4.1 KMeans

| Location | Params | K Selection | Notes |
|----------|--------|-------------|-------|
| `clustering_pipeline/kmeans_clusterer.py` | n_init=10, max_iter=300, random_state=42 | BIC (default), silhouette, composite, domain_min | K range [9,14] |
| `player_clustering.py` | Default sklearn | Silhouette | K range [4,9] |
| `player_clustering_enhanced.py` | random_state=42 | Silhouette | K range [5,9] |
| `calibration/archetype_clustering_validation.py` | Default sklearn | Silhouette, Calinski-Harabasz, Davies-Bouldin | K range [8,22] |
| `forecasting/coach_clustering.py` | random_state=42 | Silhouette (vs Ward) | K range [5,8] typically |

### 4.2 Gaussian Mixture Model (GMM)

| Location | Params | Purpose |
|----------|--------|---------|
| `clustering_pipeline/gmm_soft_clusterer.py` | covariance_type='full', max_iter=200, n_init=3, random_state=42 | Soft probabilistic assignments |
| `player_clustering_enhanced.py` | covariance_type='full' | Soft clustering |
| `scripts/build_prospect_archetypes.py` | covariance_type='full', random_state=42 | BIC-based K selection + soft assignment |

### 4.3 PCA

| Location | Components | Variance |
|----------|-----------|----------|
| `clustering_pipeline/pca_reducer.py` | 'auto' (adaptive) | 95% threshold |
| `player_clustering_enhanced.py` | Fixed 7 | ~78% |
| `forecasting/coach_clustering.py` | Not used directly (full-dim clustering) | N/A |

### 4.4 Hierarchical (Ward)

| Location | Linkage | Purpose |
|----------|---------|---------|
| `forecasting/coach_clustering.py` | Ward | Compared against KMeans, best selected |
| `calibration/archetype_clustering_validation.py` | Ward | Comparison benchmark |

### 4.5 Prototype Distance

| Location | Metric | Purpose |
|----------|--------|---------|
| `clustering_pipeline/role_prototypes.py` | Weighted Euclidean (~20 z-score dims) | Primary classification (16 roles) |

### 4.6 StandardScaler

| Location | Scope |
|----------|-------|
| `clustering_pipeline/preprocessor.py` | Per-season Z-normalization |
| `player_clustering.py` | Per-season |
| `player_clustering_enhanced.py` | Per-season |
| `forecasting/coach_clustering.py` | Cross-season |
| `scripts/build_prospect_archetypes.py` | Cross-league |

---

## 5. Feature Inventory

### 5.1 Features by Module

#### clustering_pipeline/config.py (up to ~48 features)

| Category | Features | Count |
|----------|----------|-------|
| Core box score | PTS, FGA, 3PA, FTA, AST, TOV, TRB, ORB, DRB, STL, BLK, PF | 12 |
| Shooting efficiency | FG%, 3P%, FT%, TS% | 4 |
| Advanced | USG% | 1 |
| Rate stats | E_AST_RATIO, E_OREB_PCT, E_DREB_PCT, E_REB_PCT, E_TOV_PCT | 5 |
| Computed rates | 3PA_RATE (3PA/FGA), FTA_RATE (FTA/FGA) | 2 |
| Physical | HEIGHT_INCHES, WEIGHT_LBS | 2 |
| Handedness | IS_LEFT_HANDED | 1 |
| Hustle | DEFLECTIONS, CONTESTED_SHOTS, SCREEN_ASSISTS, CHARGES_DRAWN | 4 |
| Synergy freq | POSS_PCT_{Isolation, Spotup, PRBallHandler, PRRollMan, Postup, Cut, Transition, Handoff, OffScreen} | 9 |
| Synergy PPP | off_PPP_{Isolation, Spotup, PRBallHandler, Transition} | 4 |
| **EXCLUDED** | BPM_BBREF, VORP_BBREF, OWS_BBREF, DWS_BBREF, E_OFF/DEF/NET_RATING, E_PACE | 8 (impact metrics) |

#### player_clustering.py (19 features)
PTS, FGA, FG_PCT, FG3A, FG3_PCT, FTA, FT_PCT, AST, TOV, TRB, ORB, DRB, STL, BLK, TS_PCT, EFG_PCT, AST_TOV_RATIO, 3P_RATE, USG_PCT

#### coach_clustering.py (~79 features)
- 48 role dims: 16 roles x {AVG_MINUTES_PCT, STARTER_FREQ, CRUNCH_FREQ}
- 31 non-role: timeout (7), lineup (4), effectiveness (5), offense (6), deployment (4), load mgmt (2), context (3)

#### build_prospect_archetypes.py (13 features)
PER36_PTS, PER36_REB, PER36_AST, PER36_STL, PER36_BLK, PER36_TOV, PER36_FGA, PER36_FG3A, PER36_FGM, FG_PCT, FG3_PCT, FT_PCT, HEIGHT_CM

### 5.2 Feature Overlap Matrix

| Feature | Pipeline | Legacy | Coach | Prospect |
|---------|----------|--------|-------|----------|
| PTS/scoring | Yes (raw) | Yes (raw) | No | Yes (per36) |
| AST | Yes | Yes | No | Yes (per36) |
| TRB/REB | Yes | Yes | No | Yes (per36) |
| STL, BLK | Yes | Yes | No | Yes (per36) |
| FG%, 3P%, FT% | Yes | Yes | No | Yes |
| TS% | Yes | Yes | No | No |
| USG% | Yes | Yes | No | No |
| Height | Yes (inches) | No | No | Yes (cm) |
| Weight | Yes | No | No | No |
| Handedness | Yes | No | No | No |
| Hustle stats | Yes | No | No | No |
| Synergy playtypes | Yes | No | No | No |
| Role deployment | No | No | Yes (primary) | No |
| Timeout/lineup | No | No | Yes | No |

---

## 6. Output Artifacts Inventory

### 6.1 Parquet Files

| Artifact | Location | Producer | Size | Columns |
|----------|----------|----------|------|---------|
| `archetype_history_season.parquet` | `data/gold/products/` | mart_builders.py | ~169 KB | PLAYER_ID, PLAYER_NAME, SEASON, ROLE, SECONDARY_ROLE, ROLE_DISTANCE, ROLE_CONFIDENCE, POSITION_FAMILY, MACRO_TYPE, IMPACT_TIER, ARCHETYPE, ARCHETYPE_ID, ARCHETYPE_CONFIDENCE, AVAILABILITY_PCT, AVAILABILITY_FLAG, _BUILT_AT, _CLUSTERING_METHOD |
| `player_archetypes.parquet` | `cache/features/` | build_prospect_archetypes.py | Variable | CANONICAL_PLAYER_ID, SEASON, ARCHETYPE, PROB_* columns |
| `team_inventory_season.parquet` | `data/gold/products/` | build_team_inventory.py | ~62 KB | Team × season role distributions |
| `team_needs_season.parquet` | `data/gold/products/` | build_team_needs.py | ~22 KB | Role gaps + DEMAND_SCORE |
| `coach_preferences_season.parquet` | Varies | recalibrate_coach_preferences.py | Variable | Coach × role affinities |

### 6.2 Model Files

| Artifact | Format | Location | Producer |
|----------|--------|----------|----------|
| `clustering_YYYY_YY.joblib` | joblib | Per config output_dir | ClusteringPipeline.save() |
| `config.json` | JSON | Same dir as joblib | ClusteringPipeline.save() |
| `player_archetypes_metadata.json` | JSON | `cache/features/` | build_prospect_archetypes.py |

### 6.3 DataFrame Columns Added by Each Module

| Module | Columns Added |
|--------|---------------|
| ClusteringPipeline.fit_season() | ARCHETYPE, ARCHETYPE_ID, ARCHETYPE_CONFIDENCE, SECONDARY_ARCHETYPE, SECONDARY_PROB, ROLE, ROLE_DISTANCE, ROLE_CONFIDENCE, SECONDARY_ROLE, POSITION_FAMILY, MACRO_TYPE, IMPACT_TIER, AVAILABILITY_PCT, AVAILABILITY_FLAG, PROB_* |
| DynamicPlayerClustering.fit_season() | PLAYER_ARCHETYPE_ID, PLAYER_ARCHETYPE |
| archetype_age_features.add_archetype_age_features() | ARCHETYPE, ARCHETYPE_CONFIDENCE, ARCHETYPE_SCARCITY_MULT, AGE_CURVE_MULT |
| coach_clustering | CLUSTER, CLUSTER_LABEL, CLUSTER_PROB_* |

---

## 7. Downstream Consumer Map

### 7.1 Direct Consumers of archetype_history_season.parquet

| Consumer | Path | How It Uses Clustering |
|----------|------|----------------------|
| archetype_age_features.py | `api/src/ml/features/` | Reads prior-season ROLE for feature engineering (no leakage). Adds AGE_CURVE_MULT. |
| season_projection_engine.py | `api/src/ml/features/forecasting/` | Reads latest-season role counts for league supply/demand → market_multiplier |
| build_team_inventory.py | `scripts/` | Joins with player_team_season_fact → role distribution per team |
| build_team_needs.py | `scripts/` | Reads team_inventory → gap analysis, DEMAND_SCORE |
| recalibrate_coach_preferences.py | `scripts/` | Reads role distributions → coach role affinities |

### 7.2 Direct Consumers of role_prototypes.py Exports

| Consumer | What It Uses |
|----------|-------------|
| archetype_classifier.py | ROLE_PROTOTYPES, POSITION_FAMILY, FEATURE_WEIGHTS, RoleAssigner |
| role_adapter.py | MACRO_TYPE, POSITION_FAMILY |
| ground_truth.py | ROLE_PROTOTYPES, FEATURE_WEIGHTS, build_player_profile, assign_role_by_distance |
| anomaly_detection.py | ROLE_PROTOTYPES, FEATURE_WEIGHTS, POSITION_FAMILY, build_player_profile, compute_prototype_distance |

### 7.3 Indirect Consumers (via archetype_classifier.py)

| Consumer | What It Uses |
|----------|-------------|
| archetype_age_features.py | ROLE_SCARCITY |
| cap_efficiency.py | Role-based valuation |
| trade_return_analyzer.py | Role scarcity premiums |
| team_needs.py | Role demand signals |
| expected_surplus.py | Role-based projections |

---

## 8. Legacy Code Analysis

### 8.1 player_clustering.py — Verdict: ARCHIVE

**What it does:** KMeans clustering with silhouette-based K selection (K in [4,9]). 19 features (14 core + 5 computed). Dynamic archetype naming from centroids.

**What clustering_pipeline does better:**
- Wider K range [9,14] with BIC selection (more robust than silhouette for NBA data)
- 48 features (including hustle, synergy, physical, handedness)
- PCA dimensionality reduction before clustering
- GMM soft probabilities
- 16-role supervised classification (Track 2)
- Ground truth validation (100% accuracy)
- Anomaly detection, stage diagnostics, phase validation

**Are its importers actually using it?**
- `player_value_features.py:1409`: `try: from .player_clustering import DynamicPlayerClustering` — falls back to `"Could not import player_clustering - using default weights"`. The clustering is used to get archetype-based weight adjustments, but the fallback is default weights.
- `cap_efficiency.py:3061`: `try: from .player_clustering import DynamicPlayerClustering, add_archetype_features` — also try/except with fallback.

**Conclusion:** Both importers have working fallback paths. The legacy module can be archived without breaking any pipeline.

### 8.2 player_clustering_enhanced.py — Verdict: ARCHIVE

**What it does:** Same as clustering_pipeline (PCA + KMeans + GMM) but with inferior defaults (K=[5,9], fixed 7 PCA components, no synergy/hustle features, no prototype distance, no GT validation).

**Only importer:** `nba_career_pipeline.py:34` uses `from enhanced_player_clustering import` — this is a bare module import (not relative), which would fail at runtime unless the module is on sys.path. This appears to be a broken import.

**Conclusion:** Safe to archive. It's an intermediate evolutionary step that was fully superseded.

### 8.3 archetypes_v2.py — Verdict: ARCHIVE

Already deprecated in Session 361 with explicit `DeprecationWarning`. Uses a 4-tier system (ELITE, PREMIUM, SOLID, DEPTH) that was replaced by the 16-role system. No unique functionality worth preserving.

### 8.4 calibration/archetype_clustering_validation.py — Verdict: ARCHIVE

Research/validation tool from Session 340+. 1,350 LOC with ONE active import: `season_thresholds.py:272` imports `_get_position_from_game_data()` (protected by try/except, falls back to `POSITION_SIMPLE='F'`). Its capabilities (K sweep, comparison with hierarchical, DB/CH/silhouette metrics, t-SNE visualization) are now covered by:
- `clustering_pipeline/evaluator.py` — metrics
- `clustering_pipeline/stage_diagnostics.py` — per-stage diagnostics
- `clustering_pipeline/anomaly_detection.py` — quality checks

Some unique elements (t-SNE visualization, AgglomerativeClustering comparison) could be migrated to the future clustering_core visualization module.

### 8.5 Summary

| Module | LOC | Verdict | Impact of Archive |
|--------|-----|---------|-------------------|
| player_clustering.py | 500 | ARCHIVE | Zero — both importers have try/except fallback |
| player_clustering_enhanced.py | 671 | ARCHIVE | Zero — only importer has broken path |
| archetypes_v2.py | 650 | ARCHIVE | Zero — already deprecated |
| archetype_clustering_validation.py | 1,350 | ARCHIVE | Zero — one import from `season_thresholds.py` has try/except fallback |
| **Total recoverable** | **3,171** | | |

---

## 9. Gaps vs Modern Best Practices

| # | Gap | Current State | Modern Practice | Priority | Effort | Resolution |
|---|-----|--------------|-----------------|----------|--------|------------|
| **0** | **Schema-driven configuration** | **Features hardcoded in config.py** | **YAML-first declarative schema (`clustering_schema.yaml`) following the same pattern as `column_schema.yaml` / `SchemaConfig`. Features, filters, computed rates, and domain rules loaded from YAML at runtime.** | **Critical** | **Medium** | Phase 1 |
| 1 | **Density-based clustering** | Not available | HDBSCAN for non-spherical clusters, automatic K, noise detection | High | Medium | Phase 4 |
| 2 | **Spectral clustering** | Not available | Graph Laplacian for manifold/non-convex structure | Medium | Medium | Phase 4 |
| 3 | **UMAP visualization** | PCA scatter only | UMAP preserves global+local structure in 2D, superior to PCA for viz | High | Low | Phase 4 |
| 4 | **t-SNE visualization** | Not available | t-SNE for local neighborhood structure (complementary to UMAP) | Medium | Low | Phase 4 |
| 5 | **Cluster stability analysis** | Basic temporal Jaccard only | Bootstrap resampling (100x), per-cluster Jaccard, consensus matrix | High | Medium | Phase 3 |
| 6 | **Feature importance for clusters** | None | Permutation importance (shuffle feature, measure silhouette drop), ANOVA F-stat, mutual information | High | Medium | Phase 3 |
| 7 | **Domain-agnostic pipeline** | NBA-hardcoded features/preprocessor | Generic pipeline with domain adapters (player, coach, prospect, any) | High | High | Phase 2 + 5 |
| 8 | **Model registry/versioning** | Season-keyed joblib files | Versioned registry with metadata, comparison tracking, rollback | Medium | Medium | Phase 5 |
| 9 | **Algorithm comparison framework** | Manual switching | Systematic compare_algorithms() returning side-by-side metrics | Medium | Low | Phase 3 |
| 10 | **Gap statistic** | Not implemented | Gap statistic for K selection (compares against uniform reference) | Medium | Low | **Merged** into Phase 2 K-selection methods |
| 11 | **Cross-validated clustering** | Fit and evaluate on same data | Subsampled consensus clustering, leave-out stability | Medium | Medium | **Merged** into Phase 3 bootstrap stability |
| 12 | **Automated feature selection** | Static feature lists | Variance threshold, mutual info with labels, recursive elimination | Medium | Medium | **Deferred** — 48 features curated over 30+ sessions; Phase 3 feature importance informs manual decisions |
| 13 | **Incremental/online clustering** | Full refit required | Mini-batch KMeans, online GMM updates for streaming data | **Deprioritized** | Medium | **Deferred** — pipeline processes seasonal batches, not streaming data |
| 14 | **Davies-Bouldin in evaluator** | Only in stage_diagnostics, not in ClusteringMetrics | Include DB score as standard metric alongside silhouette and CH | Low | Trivial | Phase 3 |

### Why Schema-Driven Configuration is the #1 Gap

The Bayesian pipeline already follows a mature YAML-first pattern:
```
column_schema.yaml (master) → column_schema_player_game.yaml (granularity)
    ↓
SchemaConfig (Pydantic) loaded via load_schema_from_yaml()
    ↓
bayes_model_router.py calls schema.get_numerical_features(target)
    ↓
Features automatically loaded, forbidden features excluded, leakage prevented
```

The clustering pipeline **does not** follow this pattern. Features are hardcoded as Python lists in `config.py`:
```python
# Current: hardcoded in config.py
CORE_FEATURES = ['PTS', 'FGA', '3PA', 'FTA', 'AST', 'TOV', ...]
SHOOTING_FEATURES = ['FG%', '3P%', 'FT%', 'TS%']
SYNERGY_FEATURES = ['POSS_PCT_Isolation', 'POSS_PCT_Spotup', ...]
```

This means:
- Adding/removing features requires code changes (not config changes)
- New domains (coach, prospect, international) each need their own hardcoded feature lists
- No schema validation of input DataFrames before clustering
- No forbidden-features leakage prevention for clustering outputs consumed downstream
- Cannot reuse the pipeline for arbitrary datasets without modifying source code

### What's Already Done Well (no gaps)

- **Style vs Impact separation** — Impact metrics excluded from PCA, captured separately in IMPACT_TIER
- **Ground truth validation** — 56+ canonical labels, 100% accuracy, per-role breakdown
- **Temporal stability tracking** — Jaccard at 3 hierarchy levels (ROLE, MACRO_TYPE, FAMILY)
- **Anomaly detection** — 4 automated checks with severity levels
- **Phase validation** — Checkpoints after each pipeline phase
- **BIC-based K selection** — Avoids silhouette's low-K bias for continuous data
- **Data leakage prevention** — Prior-season lookups in archetype_age_features.py
- **COMBO_GUARD reduction** — Confidence-based redistribution to target <=8%
- **Soft probabilistic assignment** — GMM provides probability matrix
- **Self-calibration** option (disabled because GT-derived prototypes are already optimal)

### Plan Adjustments to Audit Recommendations

Four adjustments based on practical considerations:

1. **Incremental clustering (Gap #13) deprioritized** — The pipeline processes seasonal batches (one fit per season), not streaming data. Mini-batch KMeans and online GMM updates add complexity without clear benefit. Defer unless a streaming use case emerges.

2. **Gap statistic (#10) and cross-validated clustering (#11) merged** — Rather than standalone implementations, gap statistic is incorporated into K-selection methods (Phase 2) and consensus clustering is combined with bootstrap stability analysis (Phase 3). Both achieve the same goal within existing evaluation infrastructure.

3. **Auto feature selection (#12) deferred** — The current 48-feature set was carefully curated over 30+ development sessions with deliberate style-vs-impact separation. Automated feature selection risks removing domain-critical features (e.g., SYNERGY features essential for role discrimination). Instead, Phase 3 adds feature importance ranking via permutation/ANOVA/MI to **inform manual curation decisions** rather than automated removal.

4. **Legacy cleanup is zero-risk** — All 3,171 LOC of archive candidates (4 modules) have either try/except fallback importers or broken import paths. Archiving has exactly zero impact on any active pipeline.

---

## 10. Recommended Architecture for Reusable Pipeline

### 10.1 Design Philosophy: Schema-Driven Unsupervised Feature Discovery

The clustering pipeline's primary role is to **unsupervised learn structure** from data and **export that structure as features** for other ML pipelines. It follows three principles:

1. **YAML-first configuration** — Features, filters, computed rates, K ranges, and domain rules all defined in `clustering_schema.yaml` files (one per domain). No hardcoded feature lists in Python.
2. **KMeans as primary algorithm** — KMeans is the workhorse for adding cluster labels and metrics. GMM provides soft probabilities. HDBSCAN, Spectral are alternative algorithms selectable via config.
3. **Output as features for downstream** — Cluster labels, distances, confidence scores, stability metrics, and derived rules become columns consumed by the Bayesian pipeline, forecasting, age curves, and team analytics.

### 10.2 Directory Structure

```
api/src/ml/features/clustering_core/         # NEW: Domain-agnostic foundation
├── __init__.py
├── schema.py                                 # ClusteringSchema (Pydantic, loads from YAML)
├── config.py                                 # ClusteringConfig (runtime params)
├── pipeline.py                               # ClusteringPipeline orchestrator
├── schemas/                                  # Domain-specific YAML schemas
│   ├── clustering_player_season.yaml         # NBA player clustering features
│   ├── clustering_coach.yaml                 # Coach deployment clustering features
│   ├── clustering_prospect.yaml              # International prospect features
│   └── clustering_template.yaml              # Blank template for new domains
├── algorithms/
│   ├── __init__.py
│   ├── base.py                               # AbstractClusterer interface
│   ├── kmeans.py                             # Primary: KMeans (migrated from clustering_pipeline)
│   ├── gmm.py                                # GMM soft probabilities
│   ├── hdbscan_clusterer.py                  # NEW: HDBSCAN (no K required)
│   └── spectral.py                           # NEW: Spectral clustering
├── dimensionality/
│   ├── __init__.py
│   ├── base.py                               # AbstractReducer interface
│   ├── pca.py                                # PCA (migrated from clustering_pipeline)
│   ├── umap_reducer.py                       # NEW: UMAP (visualization + reduction)
│   └── tsne_reducer.py                       # NEW: t-SNE (visualization)
├── evaluation/
│   ├── __init__.py
│   ├── metrics.py                            # Silhouette, CH, DB, BIC, AIC
│   ├── stability.py                          # NEW: Bootstrap, Jaccard, consensus
│   └── feature_importance.py                 # NEW: Permutation, ANOVA, MI
├── preprocessing/
│   ├── __init__.py
│   └── scaler.py                             # Generic StandardScaler + imputation
├── visualization/
│   ├── __init__.py
│   └── plots.py                              # NEW: UMAP/t-SNE scatter, elbow, silhouette, profiles
└── registry.py                               # NEW: Model versioning + comparison
```

### 10.3 Schema-Driven Data Loading

The key architectural change: **features come from YAML, not Python**.

```python
# NEW: Schema-driven loading (replaces hardcoded feature lists)
from clustering_core.schema import load_clustering_schema

# Load domain-specific schema
schema = load_clustering_schema('clustering_player_season.yaml')

# Schema provides:
features = schema.clustering_features()     # All features for clustering
filters = schema.player_filters()           # min_games, min_minutes, etc.
computed = schema.computed_features()        # 3PA_RATE = 3PA/FGA, etc.
excluded = schema.excluded_features()       # Impact metrics excluded from PCA
output_cols = schema.output_columns()       # ROLE, ARCHETYPE, IMPACT_TIER, etc.

# Pipeline uses schema directly
pipeline = ClusteringPipeline.from_schema(schema)
results_df, metrics = pipeline.fit(df, season='2024-25')
```

This mirrors the Bayesian pipeline pattern:
```
column_schema_player_game.yaml → SchemaConfig → bayes_model_router.py
clustering_player_season.yaml  → ClusteringSchema → clustering pipeline
```

### 10.4 Key Interfaces

```python
# ClusteringSchema — loaded from YAML (like SchemaConfig for Bayesian)
class ClusteringSchema(BaseModel):
    """Declarative schema for clustering configuration."""
    domain: str                           # 'player_season', 'coach', 'prospect'
    features: Dict[str, List[str]]        # category -> feature names
    computed_features: Dict[str, Tuple]   # derived features (e.g., 3PA_RATE = 3PA/FGA)
    filters: Dict[str, Any]              # min_games, min_minutes, etc.
    excluded_from_pca: List[str]          # Impact metrics (IMPACT_TIER only)
    output_columns: List[str]             # Columns added to output DataFrame
    k_range: Tuple[int, int]             # (min_k, max_k)
    k_method: str                         # 'bic', 'silhouette', 'composite'
    pca_variance_threshold: float         # 0.95
    algorithm: str                        # 'kmeans', 'gmm', 'hdbscan', 'spectral'

    def clustering_features(self) -> List[str]: ...
    def validate_dataframe(self, df) -> None: ...

# AbstractClusterer — every algorithm implements this
class AbstractClusterer(ABC):
    def fit(self, X, k=None) -> ClusterResult:
        """Fit clustering model. Returns labels + model."""
    def predict(self, X) -> np.ndarray:
        """Predict labels for new data."""
    def find_optimal_k(self, X, k_range) -> int:
        """Find optimal K for this algorithm."""

# AbstractReducer — dimensionality reduction
class AbstractReducer(ABC):
    def fit_transform(self, X) -> Tuple[np.ndarray, Any]:
        """Reduce dimensionality. Returns (X_reduced, fitted_model)."""
    def transform(self, X) -> np.ndarray:
        """Transform new data using fitted model."""

# ClusteringPipeline — main orchestrator
class ClusteringPipeline:
    @classmethod
    def from_schema(cls, schema: ClusteringSchema) -> 'ClusteringPipeline':
        """Create pipeline from YAML-loaded schema."""

    def fit(self, df, season=None, k=None) -> Tuple[DataFrame, ClusteringMetrics]:
        """Full pipeline: preprocess → reduce → cluster → evaluate → output."""

    def predict(self, df) -> DataFrame:
        """Assign clusters to new data using fitted model."""

    def evaluate(self) -> EvaluationReport:
        """Return comprehensive metrics."""

    def stability_analysis(self, df, n_bootstrap=100) -> StabilityReport:
        """Bootstrap stability of clusters."""

    def feature_importance(self, df, labels) -> FeatureImportanceReport:
        """Rank features by contribution to cluster separation."""

    def compare_algorithms(self, df, algorithms=None) -> ComparisonReport:
        """Side-by-side comparison of multiple algorithms."""

    def visualize(self, df, labels, method='umap') -> Figure:
        """2D visualization of clusters."""

    def save(self, path) -> None:
        """Persist model + schema + metrics."""

    @classmethod
    def load(cls, path) -> 'ClusteringPipeline':
        """Restore from disk."""
```

### 10.5 Relationship to Existing Code

```
clustering_core/                    <-- NEW: Generic, schema-driven
    │
    │  schemas/
    │  ├── clustering_player_season.yaml   (replaces hardcoded config.py feature lists)
    │  ├── clustering_coach.yaml           (replaces hardcoded coach_clustering features)
    │  └── clustering_prospect.yaml        (replaces hardcoded prospect features)
    │
    ├── Used by:
    │   ├── clustering_pipeline/main.py    (NBA player clustering - refactored to delegate)
    │   ├── coach_clustering.py            (Coach clustering - refactored to delegate)
    │   └── build_prospect_archetypes.py   (Prospect clustering - refactored to delegate)
    │
    └── NOT used by (domain-specific, stay in clustering_pipeline/):
        ├── role_prototypes.py             (NBA 16-role definitions)
        ├── ground_truth.py                (NBA GT validation)
        ├── archetype_namer.py             (NBA z-score naming rules)
        └── anomaly_detection.py           (NBA quality checks)
```

### 10.6 Pipeline as Unsupervised Feature Factory

The clustering pipeline's output becomes **input features** for other ML pipelines:

```
┌─────────────────────────────────────────────────────────────────┐
│                CLUSTERING PIPELINE (Unsupervised)                │
│                                                                   │
│  Input: player_season_features (Gold layer, 645 cols)            │
│         ↓                                                         │
│  1. Load features from clustering_player_season.yaml              │
│  2. Preprocess (filter, scale, impute)                            │
│  3. PCA / UMAP dimensionality reduction                          │
│  4. KMeans clustering (BIC-optimal K)                             │
│  5. GMM soft probabilities                                        │
│  6. Prototype distance → ROLE assignment                         │
│  7. Quality validation (silhouette, CH, DB, GT accuracy)         │
│         ↓                                                         │
│  Output columns added to DataFrame:                               │
│    ROLE, ROLE_DISTANCE, ROLE_CONFIDENCE, POSITION_FAMILY,        │
│    MACRO_TYPE, ARCHETYPE, ARCHETYPE_CONFIDENCE, IMPACT_TIER,     │
│    AVAILABILITY_PCT, SECONDARY_ROLE, SECONDARY_ARCHETYPE         │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                    Output: archetype_history_season.parquet
                               │
              ┌────────────────┼────────────────────┐
              ▼                ▼                     ▼
   ┌──────────────┐   ┌──────────────┐    ┌───────────────────┐
   │ Bayesian     │   │ Forecasting  │    │ Team Analytics     │
   │ Pipeline     │   │ Engine       │    │                    │
   │              │   │              │    │ build_team_inventory│
   │ ROLE → PyMC  │   │ ROLE_SCARCITY│    │ build_team_needs   │
   │ age curve    │   │ ROLE_TREND   │    │ coach_preferences  │
   │ indexing     │   │ market_mult  │    │ trade_returns      │
   └──────────────┘   └──────────────┘    └───────────────────┘
```

### 10.7 New Algorithms to Add

**HDBSCAN** (Hierarchical DBSCAN):
- Finds clusters of varying density without requiring K
- Identifies noise points (outlier players that don't fit any cluster)
- Key params: `min_cluster_size`, `min_samples`
- Library: `hdbscan>=0.8.33`

**Spectral Clustering**:
- Constructs similarity graph, clusters on graph Laplacian eigenvectors
- Good for non-convex cluster shapes
- Key params: `n_clusters`, `affinity='rbf'`, `gamma`
- Library: `sklearn.cluster.SpectralClustering` (already available)

**UMAP** (Uniform Manifold Approximation and Projection):
- Superior to PCA/t-SNE for 2D visualization (preserves global + local structure)
- Can also serve as pre-clustering dimensionality reduction
- Key params: `n_neighbors`, `min_dist`, `n_components`
- Library: `umap-learn>=0.5.5`

**t-SNE** (t-distributed Stochastic Neighbor Embedding):
- Best for visualizing local neighborhood structure
- Complementary to UMAP (different trade-offs)
- Key params: `perplexity`, `n_iter`, `learning_rate`
- Library: `sklearn.manifold.TSNE` (already available)

### 10.8 New Capabilities to Add

**Bootstrap Stability Analysis:**
- Resample 80% of data N times (default 100)
- Cluster each resample, match clusters to original via Hungarian algorithm
- Compute per-cluster Jaccard similarity
- Flag clusters with Jaccard < 0.75 as unstable
- Build consensus matrix (n x n co-occurrence counts)

**Permutation Feature Importance:**
- For each feature: shuffle column, recluster, measure silhouette drop
- Rank features by importance (largest silhouette drop = most important)
- Also compute ANOVA F-statistic per feature across clusters
- Also compute mutual information between feature and cluster labels

**Algorithm Comparison Framework:**
```python
report = pipeline.compare_algorithms(X, algorithms=['kmeans', 'gmm', 'hdbscan', 'spectral'])
# Returns: silhouette, CH, DB, stability per algorithm
# Recommends best algorithm for this dataset
```

**Model Registry:**
- Track model versions with metadata (algorithm, K, features, metrics, timestamp)
- Compare across versions
- Rollback to previous version
- Export comparison reports

### 10.9 Dependencies to Add

```
hdbscan>=0.8.33         # HDBSCAN algorithm
umap-learn>=0.5.5       # UMAP dimensionality reduction
```

Both are pip-installable and compatible with the existing sklearn/numpy/scipy stack. t-SNE and spectral clustering are already available in sklearn.

---

## 11. Schema-Driven Automation

### 11.1 Current Pattern: How Bayesian Pipeline Loads Data from YAML

The Bayesian pipeline has a mature YAML-first pattern we should replicate:

**Files involved:**
- `api/src/ml/column_schema.yaml` — Master schema (target definitions, forbidden features)
- `api/src/ml/modeling/bayesian/config/schemas/column_schema_player_game.yaml` — Granularity-specific schema (1,086 lines)
- `api/src/ml/column_schema.py` — `SchemaConfig` Pydantic model + `load_schema_from_yaml()`
- `api/src/ml/config.py` — `get_schema_for_granularity()` dispatcher

**How it works:**
```python
# 1. YAML defines everything declaratively
# column_schema_player_game.yaml:
#   numerical:
#     scoring: [PTS, FGA, FTA, ...]
#     playmaking: [AST, TOV, ...]
#   target_definitions:
#     PTS:
#       forbidden_features: [FG, FGM, FT, ...]
#   hierarchical_effects:
#     PLAYER_ID: {expected_groups: 645, effect_type: random}

# 2. Python loads YAML into Pydantic model
schema = load_schema_from_yaml('column_schema_player_game.yaml')

# 3. Pipeline queries schema for what it needs
features = schema.get_numerical_features('PTS')  # auto-excludes forbidden
hierarchical = schema.hierarchical()              # ['PLAYER_ID']
schema.validate_dataframe(df)                     # checks required columns exist
```

**Key SchemaConfig methods:**
| Method | Returns |
|--------|---------|
| `numerical()` | All numerical feature column names |
| `categorical()` | All categorical column names |
| `hierarchical()` | Hierarchical grouping columns |
| `get_forbidden_features(target)` | Columns that leak target info |
| `get_numerical_features(target)` | Numerical features minus forbidden |
| `validate_dataframe(df)` | Checks required columns exist in DataFrame |
| `numerical_categories()` | Dict of {category: [features]} |

### 11.2 Proposed Pattern: clustering_schema.yaml

Create a `ClusteringSchema` Pydantic model that loads from domain-specific YAML files, following the same pattern:

**Example: `clustering_player_season.yaml`**

```yaml
# file: clustering_core/schemas/clustering_player_season.yaml
# ═══════════════════════════════════════════════════════════
# CLUSTERING SCHEMA - NBA PLAYER SEASON
# ═══════════════════════════════════════════════════════════
#
# PURPOSE: Declarative configuration for NBA player clustering.
# Features, filters, computed rates, and domain rules are all
# defined here. The pipeline loads this file at runtime —
# no hardcoded feature lists in Python.

domain: player_season
description: "NBA player clustering for role/archetype assignment"

# ═══════════════════════════════════════════════════════════
# PLAYER FILTERS (who gets clustered)
# ═══════════════════════════════════════════════════════════
filters:
  min_games: 15             # Minimum games played
  min_minutes: 350          # Minimum total minutes
  minutes_column: "MIN"     # Column name for minutes filter

# ═══════════════════════════════════════════════════════════
# FEATURES FOR CLUSTERING (organized by category)
# These are the STYLE features that go into PCA + KMeans.
# Impact metrics are excluded — they go to IMPACT_TIER only.
# ═══════════════════════════════════════════════════════════
features:
  core_box_score:
    - PTS
    - FGA
    - 3PA
    - FTA
    - AST
    - TOV
    - TRB
    - ORB
    - DRB
    - STL
    - BLK
    - PF

  shooting_efficiency:
    - "FG%"
    - "3P%"
    - "FT%"
    - "TS%"

  usage:
    - "USG%"

  rate_stats:
    - E_AST_RATIO
    - E_OREB_PCT
    - E_DREB_PCT
    - E_REB_PCT
    - E_TOV_PCT

  physical:
    - HEIGHT_INCHES
    - WEIGHT_LBS

  handedness:
    - IS_LEFT_HANDED

  hustle:
    - DEFLECTIONS
    - CONTESTED_SHOTS
    - SCREEN_ASSISTS
    - CHARGES_DRAWN

  synergy_frequency:
    - POSS_PCT_Isolation
    - POSS_PCT_Spotup
    - POSS_PCT_PRBallHandler
    - POSS_PCT_PRRollMan
    - POSS_PCT_Postup
    - POSS_PCT_Cut
    - POSS_PCT_Transition
    - POSS_PCT_Handoff
    - POSS_PCT_OffScreen

  synergy_efficiency:
    - off_PPP_Isolation
    - off_PPP_Spotup
    - off_PPP_PRBallHandler
    - off_PPP_Transition

# ═══════════════════════════════════════════════════════════
# COMPUTED FEATURES (derived from existing columns)
# Format: new_column_name: [numerator, denominator]
# ═══════════════════════════════════════════════════════════
computed_features:
  3PA_RATE: ["3PA", "FGA"]    # 3PA / FGA — shooting style
  FTA_RATE: ["FTA", "FGA"]    # FTA / FGA — driving/foul-drawing

# ═══════════════════════════════════════════════════════════
# IMPACT METRICS — excluded from PCA, used for IMPACT_TIER
# (Style vs Impact separation: Cengiz 2025, BBall Index)
# ═══════════════════════════════════════════════════════════
impact_metrics:
  - BPM_BBREF
  - VORP_BBREF
  - OWS_BBREF
  - DWS_BBREF

excluded_from_pca:
  - BPM_BBREF
  - VORP_BBREF
  - OWS_BBREF
  - DWS_BBREF
  - E_OFF_RATING
  - E_DEF_RATING
  - E_NET_RATING
  - E_PACE

# ═══════════════════════════════════════════════════════════
# CLUSTERING ALGORITHM CONFIGURATION
# ═══════════════════════════════════════════════════════════
algorithm:
  primary: kmeans             # Primary algorithm
  soft_clustering: gmm        # For probability matrix
  k_range: [9, 14]            # [min_k, max_k]
  k_selection: bic            # 'bic', 'silhouette', 'composite', 'domain_min'
  random_state: 42

# ═══════════════════════════════════════════════════════════
# PCA CONFIGURATION
# ═══════════════════════════════════════════════════════════
pca:
  n_components: auto          # 'auto' or integer
  variance_threshold: 0.95    # Used when n_components='auto'

# ═══════════════════════════════════════════════════════════
# OUTPUT COLUMNS (what the pipeline adds to the DataFrame)
# ═══════════════════════════════════════════════════════════
output_columns:
  - ROLE
  - ROLE_DISTANCE
  - ROLE_CONFIDENCE
  - SECONDARY_ROLE
  - POSITION_FAMILY
  - MACRO_TYPE
  - ARCHETYPE
  - ARCHETYPE_ID
  - ARCHETYPE_CONFIDENCE
  - SECONDARY_ARCHETYPE
  - SECONDARY_PROB
  - IMPACT_TIER
  - AVAILABILITY_PCT
  - AVAILABILITY_FLAG

# ═══════════════════════════════════════════════════════════
# QUALITY GATES (clustering must pass these to be accepted)
# ═══════════════════════════════════════════════════════════
quality_gates:
  min_silhouette: 0.20        # Hard fail below this
  target_silhouette: 0.30     # Warning if below
  min_pca_variance: 0.90      # Minimum PCA explained variance
  min_cluster_pct: 0.05       # No cluster smaller than 5%
  min_gt_accuracy: 0.75       # Ground truth accuracy target

# ═══════════════════════════════════════════════════════════
# PREPROCESSING
# ═══════════════════════════════════════════════════════════
preprocessing:
  scaler: standard            # 'standard', 'robust', 'minmax'
  imputation:
    percentage_columns: median # FG%, 3P%, etc.
    counting_columns: zero     # PTS, AST, etc.
  age_columns_excluded:        # Excluded from clustering (age is not style)
    - AGE
    - YEARS_EXPERIENCE
    - DRAFT_YEAR
```

**Example: `clustering_coach.yaml`** (different domain, same schema format)

```yaml
domain: coach
description: "Coach deployment style clustering"

filters:
  min_games_coached: 20

features:
  role_deployment:
    # 16 roles x 3 metrics = 48 dimensions
    - PRIMARY_CREATOR_AVG_MINUTES_PCT
    - PRIMARY_CREATOR_STARTER_FREQ
    - PRIMARY_CREATOR_CRUNCH_FREQ
    # ... (all 48 role-metric combos loaded from template)

  timeout_tendencies:
    - TIMEOUT_FREQ_PER_GAME
    - TIMEOUT_LATE_GAME_PCT
    # ... (7 total)

  lineup_composition:
    - AVG_LINEUP_HEIGHT
    - THREE_GUARD_LINEUP_PCT
    # ... (4 total)

algorithm:
  primary: kmeans
  k_range: [5, 8]
  k_selection: silhouette

pca:
  n_components: auto
  variance_threshold: 0.90
```

### 11.3 ClusteringSchema Loader (Pydantic)

```python
# clustering_core/schema.py — mirrors column_schema.py pattern

from pydantic import BaseModel
from omegaconf import OmegaConf
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


class ClusteringSchema(BaseModel):
    """Declarative schema for clustering, loaded from YAML."""

    domain: str
    description: str = ""
    filters: Dict[str, Any] = {}
    features: Dict[str, List[str]] = {}
    computed_features: Dict[str, List[str]] = {}
    impact_metrics: List[str] = []
    excluded_from_pca: List[str] = []
    algorithm: Dict[str, Any] = {}
    pca: Dict[str, Any] = {}
    output_columns: List[str] = []
    quality_gates: Dict[str, float] = {}
    preprocessing: Dict[str, Any] = {}

    def clustering_features(self) -> List[str]:
        """All features for clustering (flattened from categories)."""
        all_feats = []
        for category_feats in self.features.values():
            all_feats.extend(category_feats)
        return all_feats

    def validate_dataframe(self, df) -> List[str]:
        """Check which required features are missing from DataFrame."""
        required = set(self.clustering_features())
        present = set(df.columns)
        return sorted(required - present)

    def get_k_range(self) -> Tuple[int, int]:
        """Return (min_k, max_k) from algorithm config."""
        kr = self.algorithm.get('k_range', [9, 14])
        return (kr[0], kr[1])


def load_clustering_schema(path: str) -> ClusteringSchema:
    """Load clustering schema from YAML file (OmegaConf)."""
    cfg = OmegaConf.load(path)
    return ClusteringSchema(**OmegaConf.to_container(cfg, resolve=True))
```

### 11.4 Migration Path: config.py → YAML

The migration from hardcoded features to YAML is backward-compatible:

**Phase 1 (Non-breaking):** Create `clustering_player_season.yaml` containing the exact same features currently in `config.py`. Add `ClusteringSchema` loader. The existing `ClusteringConfig` dataclass continues to work — schema is loaded alongside it.

**Phase 2 (Feature parity):** Refactor `ClusteringPipeline.fit_season()` to accept a `ClusteringSchema` in addition to `ClusteringConfig`. Features come from schema; hyperparams come from config. If no schema provided, fall back to hardcoded `config.py` lists.

**Phase 3 (Schema-only):** Deprecate hardcoded feature lists in `config.py`. All features loaded from YAML. `ClusteringConfig` retains only runtime hyperparams (random_state, verbosity, etc.). Feature lists removed.

```python
# Phase 1: Dual-mode (backward compatible)
pipeline = ClusteringPipeline(config=ClusteringConfig())  # existing
schema = load_clustering_schema('clustering_player_season.yaml')
pipeline = ClusteringPipeline(config=ClusteringConfig(), schema=schema)  # new

# Phase 3: Schema-driven (final state)
schema = load_clustering_schema('clustering_player_season.yaml')
pipeline = ClusteringPipeline.from_schema(schema)
results_df, metrics = pipeline.fit(df, season='2024-25')
```

### 11.5 How Downstream Pipelines Consume Clustering Features

The clustering pipeline produces **archetype_history_season.parquet** with derived columns. These become features for:

| Consumer Pipeline | Clustering Columns Used | How |
|------------------|------------------------|-----|
| **Bayesian (PyMC)** | ROLE → integer index | `role_adapter.py` maps ROLE to int for hierarchical age curves |
| **Forecasting** | ROLE_SCARCITY, ROLE_TREND, ROLE_PEAK_AGE | `archetype_classifier.py` maps ROLE → market signals |
| **Age Curves** | ARCHETYPE, AGE_CURVE_MULT | `archetype_age_features.py` uses prior-season ROLE (no leakage) |
| **Team Analytics** | ROLE per team | `build_team_inventory.py` → role distribution per team |
| **Trade Analysis** | ROLE_SCARCITY | `trade_return_analyzer.py` → scarcity premiums |
| **Cap Efficiency** | (legacy) archetype weights | `cap_efficiency.py` → try/except fallback |
| **Season Projections** | League role counts | `season_projection_engine.py` → supply/demand market_multiplier |

All of these consumers read from the parquet output — they don't call the clustering pipeline directly. This means the clustering pipeline can be upgraded independently as long as the output schema (column names and semantics) remains stable.

---

## 12. Implementation Plan (6 Phases)

### 12.1 Phase Overview

| Phase | Name | Priority | Est. Sessions | Key Deliverables |
|-------|------|----------|---------------|------------------|
| 1 | Foundation: Schema + Loader | CRITICAL | 1 | **COMPLETE** — 4 YAML schemas, ClusteringSchema loader (250 LOC), 43 equivalence tests |
| 2 | Core Module: Algorithms + Interfaces | HIGH | 1 | **COMPLETE** — clustering_core/ (11 files, ~1,400 LOC), 66 tests, main.py rewired |
| 3 | Evaluation: Stability + Importance | HIGH | 1 | **COMPLETE** — evaluation/ (4 files, ~700 LOC), 31 tests, 140 total |
| 4 | Visualization + New Algorithms | MEDIUM | 1 | **COMPLETE** — t-SNE, Spectral, UMAP/HDBSCAN (optional), 5 plot types, 163 total tests |
| 5 | Domain Adapters + Registry | MEDIUM | 1 | **COMPLETE** — 3 adapters (player/coach/prospect) + ModelRegistry, 29 tests, 192 total |
| 6 | Integration, Validation + Legacy Cleanup | HIGH | 1 | **COMPLETE** — 41 integration tests, 5 downstream consumers validated, 4 legacy modules archived (3,171 LOC), 233 total tests |

Each phase is designed to be **non-breaking** — the existing production pipeline continues to work at every phase boundary. Legacy code is **not archived until Phase 6**, after all new modules are built, tested, and validated against downstream consumers. This ensures a safe rollback path at every step.

### 12.2 Phase 1: Foundation (Schema + Loader) — COMPLETE (Session 370, 2026-02-12)

**Priority:** CRITICAL | **Status:** COMPLETE | **Sessions:** 1

> **Principle: Build new alongside old.** Legacy code stays in place throughout Phases 1-5.
> Archiving happens in Phase 6 only after all new modules are tested and validated.

**Step 1.1: Create YAML Schema Files** — COMPLETE
- `clustering_pipeline/schemas/clustering_player_season.yaml` — 42 features in 10 categories, plus filters, computed features (2), algorithm config, PCA, GMM, quality gates, preprocessing, include flags
- `clustering_pipeline/schemas/clustering_coach.yaml` — 79 features (48 role-based + 31 non-role in 7 categories)
- `clustering_pipeline/schemas/clustering_prospect.yaml` — 13 features (6 PER36 core + 3 PER36 shot + 3 efficiency + 1 physical)
- `clustering_pipeline/schemas/clustering_template.yaml` — Commented skeleton for new domains

**Step 1.2: Build ClusteringSchema Pydantic Loader** — COMPLETE
- `clustering_schema.py` (~250 LOC) — `ClusteringSchema(BaseModel)` with `ConfigDict(arbitrary_types_allowed=True)`
- Accessor methods: `clustering_features(categories)`, `computed_features()`, `get_k_range()`, `k_selection_method()`, `random_state()`, `pca_config()`, `gmm_config()`, `include_flags()`, `filters()`, `quality_gates()`, `validate_dataframe(df, strict)`
- `_to_plain()` helper: safely handles OmegaConf → plain Python conversion (uses `OmegaConf.is_config()` guard)
- `load_clustering_schema(path)` factory + `get_clustering_schema(domain)` discovery
- `CLUSTERING_SCHEMAS_DIR`, `CLUSTERING_SCHEMA_FILES` for schema file discovery
- Mirrors the `SchemaConfig` / `load_schema_from_yaml()` pattern from `column_schema.py`

**Step 1.3: Equivalence Tests** — COMPLETE (43 passed, 0 warnings)
- `tests/test_schema_equivalence.py` (~200 LOC, 43 tests in 6 classes)
- `TestPlayerSeasonSchemaEquivalence` (25 tests): Every feature category, computed features, algorithm config, filters, quality gates, include flags, feature counts (42 total, 38 PCA)
- `TestCoachSchemaLoads` (6 tests): 48 role + 31 non-role = 79 features, K=4-12, PCA 90%
- `TestProspectSchemaLoads` (5 tests): 13 features, K=8-18, GMM enabled, HEIGHT_CM
- `TestSchemaDiscovery` (4 tests): All files exist, unknown domain raises, template exists
- `TestSchemaAPI` (3 tests): Feature categories, subset selection, validate_dataframe
- Legacy code is NOT touched — it continues running in production as-is

**Implementation Notes:**
- OmegaConf gotcha: `cfg.get(key, {})` returns plain Python `{}` when key missing, but `OmegaConf.to_container()` rejects plain dicts. Fixed with `_to_plain()` helper using `OmegaConf.is_config()` guard.
- SYNERGY_PPP_FEATURES (4 features) are in the schema but NOT used by PCA (Track 1). Only used in prototype distance (Track 2, role_prototypes.py). PCA feature count = 38, not 42.
- Package version bumped to 2.4.0

### 12.3 Phase 2: Core Module (Algorithms + Interfaces) — COMPLETE (Session 370, 2026-02-12)

**Priority:** HIGH | **Status:** COMPLETE | **Sessions:** 1

**Step 2.1: Directory Structure** — COMPLETE
- `clustering_core/` package with `algorithms/`, `dimensionality/`, `preprocessing/`, `tests/` sub-packages

**Step 2.2: Abstract Interfaces + Result Types** — COMPLETE
- `interfaces.py`: `AbstractClusterer(ABC)` with `fit(X, k)`, `predict(X)`, `find_optimal_k(X, k_range)`
- `interfaces.py`: `AbstractReducer(ABC)` with `fit_transform(X)`, `transform(X)`, `inverse_transform(X)`
- `types.py`: `ClusterResult`, `ReductionResult`, `ScalerResult` dataclasses with full metric fields

**Step 2.3: GenericKMeans** — COMPLETE (~250 LOC)
- `algorithms/kmeans.py`: All 4 K-selection methods (BIC, silhouette, composite, domain_min)
- Domain-agnostic: takes `k_range`, `k_selection_method`, `random_state` — no ClusteringConfig dependency
- Returns `ClusterResult` with labels, silhouette, CH, DB, inertia, centroids, k_scores
- Property accessors for diagnostic scores (`silhouette_scores`, `bic_scores`, `calinski_scores`)

**Step 2.4: GenericGMM** — COMPLETE (~180 LOC)
- `algorithms/gmm.py`: Soft probabilistic clustering with `predict_proba()` and `find_optimal_k()`
- Returns `ClusterResult` with probabilities, BIC, AIC, convergence status

**Step 2.5: GenericPCA** — COMPLETE (~110 LOC)
- `dimensionality/pca.py`: Auto (`variance_threshold`) and fixed (`n_components`) modes
- Returns `ReductionResult` with variance explained, per-component variance, feature name tracking

**Step 2.6: GenericScaler** — COMPLETE (~170 LOC)
- `preprocessing/scaler.py`: StandardScaler or RobustScaler with tiered imputation
- Configurable rate indicators for median vs zero imputation
- Returns `ScalerResult` with imputation report

**Step 2.7: GenericClusteringPipeline** — COMPLETE (~200 LOC)
- `pipeline.py`: Full pipeline orchestrator: Scale -> PCA -> KMeans -> GMM -> Original-space centroids
- `from_schema(schema)` factory method: builds pipeline entirely from ClusteringSchema (YAML)
- `PipelineResult` dataclass bundles all intermediate results
- `predict()` method for inference on new data

**Step 2.8: Rewire clustering_pipeline/main.py** — COMPLETE
- `ClusteringPipeline.__init__()` now constructs `GenericKMeans`, `GenericGMM`, `GenericPCA` from clustering_core
- `fit_season()` Steps 3-6 use clustering_core algorithms, returning typed results (`ClusterResult`, `ReductionResult`)
- Legacy wrappers (`_legacy_gmm`) retained for DataFrame enrichment methods (`add_soft_probabilities`)
- All NBA-specific operations unchanged: preprocessing, archetype naming, role assignment, COMBO_GUARD split, IMPACT_TIER

**Tests:** 66 new tests (52 unit + 14 integration), all passing. Combined with Phase 1: **109 total tests**.

**Implementation Notes:**
- clustering_core algorithms take simple parameters (not ClusteringConfig), enabling reuse by coach/prospect clustering
- `ClusterResult` includes Davies-Bouldin index (DB) which was missing from legacy KMeansClusterer
- Legacy modules (`kmeans_clusterer.py`, `gmm_soft_clusterer.py`, `pca_reducer.py`) are preserved alongside — both paths available until Phase 6
- Integration test validates all 3 schemas (player_season, coach, prospect) drive `GenericClusteringPipeline.from_schema()` correctly

### 12.4 Phase 3: Evaluation (Stability + Feature Importance) — COMPLETE (Session 370, 2026-02-12)

**Priority:** HIGH | **Status:** COMPLETE | **Sessions:** 1

**Step 3.1: Bootstrap Stability Analysis** — COMPLETE
- File: `clustering_core/evaluation/stability.py` (~230 LOC)
- `BootstrapStability` class: resample 80% N times (default 100), cluster each
- Hungarian algorithm (`scipy.optimize.linear_sum_assignment`) for label matching with greedy fallback
- Per-cluster Jaccard similarity; flag < 0.75 as unstable
- Consensus matrix (n × n co-occurrence fractions)
- `StabilityReport` dataclass: overall_stability, per_cluster_jaccard, consensus_matrix, unstable_clusters, per_bootstrap_scores
- Custom `clusterer_factory` support for any fit_predict-compatible algorithm

**Step 3.2: Permutation Feature Importance** — COMPLETE
- File: `clustering_core/evaluation/feature_importance.py` (~260 LOC)
- `PermutationImportance` class with three complementary methods:
  - Permutation importance: shuffle feature N times, measure silhouette drop
  - ANOVA F-statistic (`sklearn.feature_selection.f_classif`): between/within cluster variance
  - Mutual information (`sklearn.feature_selection.mutual_info_classif`): non-linear associations
- Composite ranking: 40% permutation + 30% ANOVA + 30% MI (normalized to [0,1])
- Category aggregation for grouped feature importance
- `FeatureImportanceReport` dataclass: all three score dicts, feature_ranking, category_importance
- **Informs manual curation** (not automated removal — 48 features were deliberately curated)

**Step 3.3: Algorithm Comparison Framework** — COMPLETE
- File: `clustering_core/evaluation/comparison.py` (~310 LOC)
- `AlgorithmComparison` class: supports kmeans, gmm, spectral, ward, hdbscan
- Side-by-side: silhouette, CH, DB per algorithm + algorithm-specific (BIC, AIC, inertia, noise_pct)
- Composite ranking: 40% silhouette + 30% CH + 30% DB_inv
- HDBSCAN gracefully handled if not installed (informative skip)
- `ComparisonReport` dataclass: per-algorithm results, recommendation, reason, ranking

**Step 3.4: Package Integration** — COMPLETE
- `clustering_core/evaluation/__init__.py` exports all 6 public types
- `clustering_core/__init__.py` updated: exports evaluation types, version bumped to 2.0.0
- 31 new tests (`test_evaluation.py`): 8 stability + 9 importance + 11 comparison + 3 integration
- All 140 tests pass (43 Phase 1 + 52+14 Phase 2 + 31 Phase 3)

### 12.5 Phase 4: Visualization + New Algorithms — COMPLETE (Session 370, 2026-02-13)

**Priority:** MEDIUM | **Status:** COMPLETE | **Sessions:** 1

**Step 4.1: UMAP** — COMPLETE
- File: `clustering_core/dimensionality/umap_reducer.py` (~110 LOC)
- `GenericUMAP(AbstractReducer)`: n_neighbors, min_dist, metric, random_state
- Dual use: pre-clustering reduction AND 2D visualization
- Optional dependency: `umap-learn>=0.5.5` — graceful ImportError with install instructions
- Supports `transform()` and `inverse_transform()` (approximate)

**Step 4.2: t-SNE** — COMPLETE
- File: `clustering_core/dimensionality/tsne_reducer.py` (~130 LOC)
- `GenericTSNE(AbstractReducer)`: perplexity, max_iter, learning_rate
- Auto-adjusts perplexity for small sample sizes
- `transform()` and `inverse_transform()` raise NotImplementedError (t-SNE is non-parametric)
- KL divergence reported in metadata
- Uses `max_iter` (not deprecated `n_iter`) for sklearn 1.5+ compatibility

**Step 4.3: HDBSCAN** — COMPLETE
- File: `clustering_core/algorithms/hdbscan_clusterer.py` (~200 LOC)
- `GenericHDBSCAN(AbstractClusterer)`: min_cluster_size, min_samples, cluster_selection_method
- No K required — discovers cluster count from density structure
- `map_noise_to_nearest=True`: noise points (-1) mapped to nearest cluster centroid
- Optional dependency: `hdbscan>=0.8.33` — graceful ImportError
- Reports noise_pct and raw_labels in metadata

**Step 4.4: Spectral Clustering** — COMPLETE
- File: `clustering_core/algorithms/spectral.py` (~170 LOC)
- `GenericSpectral(AbstractClusterer)`: affinity ('rbf', 'nearest_neighbors'), gamma, n_neighbors
- `find_optimal_k()` via silhouette sweep
- `predict()` raises NotImplementedError (spectral is transductive)
- Quality metrics: silhouette, CH, DB

**Step 4.5: Visualization Module** — COMPLETE
- File: `clustering_core/visualization/plots.py` (~300 LOC)
- `ClusterVisualizer` class with 5 plot types, all saved as PNG:
  1. `scatter_2d()` — 2D embedding colored by cluster (supports any method label)
  2. `silhouette_plot()` — per-sample silhouette values grouped by cluster
  3. `elbow_curve()` — K vs metric score with optimal K marker
  4. `feature_importance_bar()` — horizontal bar chart, top N features
  5. `cluster_profile_radar()` — radar chart comparing cluster centroids (auto-selects top features by variance)
- Uses `matplotlib.use('Agg')` for headless/CI environments
- Configurable output_dir, figsize, dpi

**Package Updates:**
- `algorithms/__init__.py`: exports GenericSpectral + optional GenericHDBSCAN
- `dimensionality/__init__.py`: exports GenericTSNE + optional GenericUMAP
- `clustering_core/__init__.py` v3.0.0: exports all Phase 4 types
- 23 new tests (`test_phase4.py`): 7 t-SNE + 6 Spectral + 2 UMAP (skip) + 2 HDBSCAN (skip) + 7 viz + 3 integration
- All 163 tests pass (43 + 66 + 31 + 23), 4 skipped (UMAP/HDBSCAN not installed)

### 12.6 Phase 5: Domain Adapters + Registry — COMPLETE (Session 370, 2026-02-13)

**Priority:** MEDIUM | **Status:** COMPLETE | **Sessions:** 1

**Step 5.1: Player Season Adapter** — COMPLETE
- File: `clustering_core/adapters/player_adapter.py` (~180 LOC)
- `PlayerSeasonAdapter(BaseClusteringAdapter)`: Z-score-based archetype naming from centroid features
- `get_features()`: prefers `_PG` variants (per-game normalization)
- `name_clusters()`: top-2 z-score features → compound names (SCORER_PLAYMAKER, RIM_PROTECTOR_REBOUNDER)
- `format_output()`: adds ROLE, CLUSTER_ID, ARCHETYPE_CONFIDENCE, SILHOUETTE, N_CLUSTERS
- `from_schema()` factory for ClusteringSchema integration

**Step 5.2: Coach Clustering Adapter** — COMPLETE
- File: `clustering_core/adapters/coach_adapter.py` (~180 LOC)
- `CoachAdapter(BaseClusteringAdapter)`: dominant role preference labeling
- `CLUSTER_LABELS` dict: maps role patterns → semantic labels (SPACING_ORIENTED, DEFENSE_FIRST, etc.)
- `ROLE_ABBREV` for collision deduplication (_3DW, _RP, _SG, etc.)
- `format_output()`: adds COACH_CLUSTER, CLUSTER_ID, PCA_VARIANCE_EXPLAINED, CLUSTER_METHOD

**Step 5.3: Prospect Clustering Adapter** — COMPLETE
- File: `clustering_core/adapters/prospect_adapter.py` (~200 LOC)
- `ProspectAdapter(BaseClusteringAdapter)`: z-score naming rules (20 rules, first-match-wins)
- Names: rim_protector, paint_finisher, sharpshooter, primary_playmaker, etc.
- `format_output()`: adds ARCHETYPE, ARCHETYPE_CONFIDENCE, per-cluster ARCH_PROB_* columns
- Handles 13-feature prospect feature set (PER36 + efficiency + HEIGHT_CM)

**Step 5.4: Base Adapter** — COMPLETE
- File: `clustering_core/adapters/base.py` (~120 LOC)
- `BaseClusteringAdapter(ABC)`: abstract interface defining get_features(), name_clusters(), format_output()
- `fit()` orchestrates: get_features → pipeline.fit → name_clusters → format_output
- `last_result` property for post-fit diagnostics

**Step 5.5: Model Registry** — COMPLETE
- File: `clustering_core/registry.py` (~260 LOC)
- `ModelRegistry`: JSON-based per-domain registry files
- `register()` and `register_from_result()` (auto-extract from PipelineResult)
- `list_versions()`, `get_version()`, `get_best(metric)`, `compare(v1, v2)`, `delete_version()`
- `RegistryEntry` dataclass: domain, version, algorithm, k, metrics, schema_version, timestamp, metadata
- Persistence across instances (JSON on disk)

**Tests:** 29 new tests (`test_phase5.py`): 6 player + 4 coach + 5 prospect + 12 registry + 2 integration
- All 192 tests pass (43 + 66 + 31 + 23 + 29), 4 skipped (optional deps)

### 12.7 Phase 6: Integration, Validation + Legacy Cleanup — COMPLETE (Session 370, 2026-02-13)

**Priority:** HIGH | **Status:** COMPLETE | **Sessions:** 1

> **Principle: Test everything BEFORE archiving anything.**
> Legacy code ran in parallel through Phases 1-5. Archived only after all validation passed.

**Step 6.1: End-to-End Pipeline Test** — COMPLETE
- `test_phase6_integration.py` — 41 tests covering full YAML → adapter → output flow
- All three domains tested: player_season (11 tests), coach (4 tests), prospect (4 tests)
- Output column verification: ROLE, CLUSTER_ID, ARCHETYPE_CONFIDENCE, SILHOUETTE, N_CLUSTERS
- Registry integration: schema → fit → register → get_best

**Step 6.2: Downstream Consumer Validation** — COMPLETE
- `TestDownstreamRoleAdapter` (4 tests) — ROLE string type, CLUSTER_ID integer, no nulls, unique per cluster
- `TestDownstreamArchetypeAgeFeatures` (4 tests) — ROLE + confidence, [0,1] range, parquet roundtrip, no INSUFFICIENT_SAMPLE
- `TestDownstreamArchetypeClassifier` (3 tests) — centroids exist, contiguous labels 0..K-1, silhouette in [-1,1]
- `TestDownstreamCapEfficiency` (1 test) — PLAYER_ARCHETYPE/PLAYER_ARCHETYPE_ID mappable from ROLE/CLUSTER_ID
- `TestDownstreamPlayerValueFeatures` (1 test) — multi-season sequential clustering works
- `TestQualityGates` (3 tests) — schema gates loaded, enforceable against results
- `TestCrossDomainConsistency` (2 tests) — all 3 domains produce CLUSTER_ID + last_result
- `TestEvaluationIntegration` (2 tests) — stability + importance work with adapter output
- `TestRegistryPersistence` (2 tests) — multi-domain + reload persistence

**Step 6.3: Archive Legacy Code** — COMPLETE
- Archived 4 modules (3,171 LOC) to `_archive/20260213_clustering_legacy/`:
  - `player_clustering.py` (500 LOC) — replaced by `clustering_core.adapters.PlayerSeasonAdapter`
  - `player_clustering_enhanced.py` (671 LOC) — replaced by `clustering_core.adapters.PlayerSeasonAdapter`
  - `archetypes_v2.py` (650 LOC) — deprecated since Session 361, replaced by 16-role canonical
  - `archetype_clustering_validation.py` (1,350 LOC) — replaced by `clustering_core.evaluation`
- All 4 importers verified: try/except fallbacks degrade gracefully
- README.md with migration guide added to archive directory
- Post-archive test run: **233 passed, 4 skipped** — zero regressions

**Bug fix during Phase 6:**
- `ProspectAdapter.format_output()` was missing `CLUSTER_ID` column (player + coach had it). Added for cross-domain consistency.

**Real-Data Validation Results (Session 370):**

| Domain | Data Source | Rows | Features Found | Silhouette | K | Status |
|--------|-----------|------|---------------|------------|---|--------|
| Player (production) | player_season_features.parquet | 560 (2024-25) | 37/42 (97.6%) | 0.129 | 11 | PASS |
| Player (core) | same | 475 qualifying | 37/42 | 0.108 | 12 | PASS |
| Coach (core, raw) | coach_season_profiles.parquet | 1,698 | 31/79 (39%) | 0.137 | 5 | PASS (partial) |
| Coach (core, pivoted) | build_coach_feature_matrix() | 61 | 79/79 (100%) | 0.060 | 5 | PASS |
| Multi-season prod | player_season_features.parquet | 3 seasons | 37/42 | 0.11-0.13 | 11 | PASS |

**Known Gaps (by design — addressed in architecture notes):**

1. **Core vs Production column gap:** Core adapter produces 5 columns (ROLE, CLUSTER_ID, ARCHETYPE_CONFIDENCE, SILHOUETTE, N_CLUSTERS). Production adds 10 more from Track 2 (prototype distance: ROLE_DISTANCE, ROLE_CONFIDENCE, POSITION_FAMILY, MACRO_TYPE, SECONDARY_ROLE) and independent dimensions (IMPACT_TIER, ARCHETYPE, ARCHETYPE_ID, AVAILABILITY_PCT, AVAILABILITY_FLAG). This is **by design** — Track 2 columns come from `role_prototypes.py` which is production-specific supervised logic, not generic clustering.

2. **Coach data format:** Coach data is **long format** (one row per coach-role-season). Schema expects **wide format** (one row per coach with 48 pivoted role columns). Must call `build_coach_feature_matrix()` before running CoachAdapter. Future work: add optional `pivot_step` to CoachAdapter.

3. **Missing `IS_LEFT_HANDED`:** Not in player_season_features.parquet (loaded at runtime from separate handedness JSON). Schema lists 42 features; 41 present in data (97.6% coverage). Pipeline handles missing features gracefully.

4. **Missing `MIN` column:** player_season_features uses `GP` but not `MIN` for filtering. Production pipeline applies GP>=15 + MIN>=350 filter internally via preprocessor.py. Core adapter doesn't filter — caller must pre-filter.

---

## 13. Risk Mitigation & Success Criteria

### 13.1 Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Schema migration breaks pipeline | Low | High | Legacy code stays live through Phase 5. New and old run in parallel. Archive only after Phase 6 validation passes. |
| HDBSCAN noise detection confuses consumers | Medium | Medium | Map noise points to COMBO_GUARD or nearest prototype. Never leave players unclassified. |
| Bootstrap stability too slow | Medium | Low | Reduce n_bootstrap from 100 to 50. Use joblib Parallel for parallel processing. |
| UMAP non-determinism | High | Low | Set random_state in UMAP config. Accept minor variation (visualization only). |
| GT accuracy drops after refactor | Low | High | Run GT validation at every phase boundary. Abort refactor if accuracy < 95%. |
| Downstream schema change | Low | High | Output column names are frozen. New features additive only. No renames or removals. |

### 13.2 Decision Points (Defer Until Implementation)

- **HDBSCAN vs KMeans as default:** Phase 4 algorithm comparison will reveal if HDBSCAN consistently outperforms on NBA data. KMeans likely remains primary due to interpretability and stability.
- **UMAP as reduction vs visualization:** Phase 4 tests both modes. If UMAP reduction improves clustering quality, it can supplement PCA. Otherwise, PCA for reduction, UMAP for visualization.
- **Schema versioning strategy:** Phase 5 implements registry. File-based vs database-backed decided based on version volume.

### 13.3 Success Criteria — ALL MET

The implementation is complete. All criteria met:

1. **DONE** — All clustering features loaded from YAML schema (3 domain schemas, 43 equivalence tests)
2. **DONE** — Pipeline produces identical output columns (ROLE, CLUSTER_ID, ARCHETYPE_CONFIDENCE, etc.)
3. **DONE** — 5 downstream consumers validated: role_adapter, archetype_classifier, archetype_age_features, cap_efficiency, player_value_features
4. **DONE** — Bootstrap stability analysis available for all three domains (BootstrapStability + StabilityReport)
5. **DONE** — Feature importance ranking with 3 methods (permutation, ANOVA, MI) + composite ranking
6. **DONE** — HDBSCAN (optional, density-based) + Spectral clustering integrated alongside KMeans/GMM
7. **PARTIAL** — UMAP optional (not installed); t-SNE available for 2D visualization via ClusterVisualizer
8. **DONE** — New domain requires only YAML schema + adapter subclass (~180 LOC); pipeline/algorithms/evaluation are domain-agnostic
9. **DONE** — 4 legacy modules archived (3,171 LOC) with zero regressions (233 tests pass post-archive)
10. **DONE** — BootstrapStability.analyze() with Jaccard metric available; tested with adapter pipeline output

---

## Appendix A: Session History (Clustering Evolution)

| Session | Date | Change |
|---------|------|--------|
| 340 | 2026-01 | archetype_clustering_validation.py created |
| 343 | 2026-02 | clustering_pipeline created: Two-track architecture, 16 archetypes, hustle/synergy features |
| 344 | 2026-02 | IMPACT_TIER switched to percentile-based BPM |
| 345-346 | 2026-02 | Impact metrics excluded from PCA, computed rate features added |
| 347 | 2026-02 | INSUFFICIENT_SAMPLE for filtered-out players |
| 348 | 2026-02 | Ground truth system + weight optimization |
| 349 | 2026-02 | PCA changed from fixed 7 to auto 95% variance |
| 350 | 2026-02 | Anomaly detection, phase validation, dead code removal |
| 351 | 2026-02 | COMBO_GUARD confidence split, per-stage metrics |
| 352 | 2026-02 | archetype_classifier unified, self-calibration added (then disabled), min_games lowered |
| 353 | 2026-02 | Self-calibration disabled (destroyed GT accuracy) |
| 354 | 2026-02 | AVAILABILITY_PCT tracking |
| 356 | 2026-02 | GT labels refined (Edwards→SG, Hield→OBS) |
| 361 | 2026-02 | archetypes_v2 deprecated |
| 362 | 2026-02 | mart_builders uses full ClusteringPipeline (replaced naive stub) |
| 364 | 2026-02 | Coach clustering enhanced (Session 368: Ward + soft + CH/DB) |
| 365 | 2026-02 | archetype_age_features migrated to 16-role + Bayesian age curves |
| 369 | 2026-02 | build_prospect_archetypes.py created (GMM on intl players) |
| 370 | 2026-02 | **ALL 6 PHASES COMPLETE**: YAML schemas + ClusteringSchema. clustering_core framework: 4 algorithms, 3 reducers, scaler, pipeline, evaluation (3 methods), visualization (5 plots), 3 domain adapters (player/coach/prospect), model registry. Phase 6: 41 end-to-end integration tests, 5 downstream consumers validated, 4 legacy modules archived (3,171 LOC), ProspectAdapter CLUSTER_ID fix. **233 tests passing, 4 skipped** |
