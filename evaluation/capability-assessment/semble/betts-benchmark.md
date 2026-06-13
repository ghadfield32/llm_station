# semble PILOT Benchmark — betts_basketball (LARGE repo)

Date: 2026-06-12
Tool: `semble 0.3.4` (CLI only — no MCP registration, no `semble install`)
Target repo: `c:\Users\ghadf\vscode_projects\docker_projects\betts_basketball` (~39,401 git-tracked files)
Comparison baseline: ripgrep (used to establish gold answers)

Legend: **[MEASURED]** = directly observed this run. **[INFERRED]** = reasoned from source/behavior.

---

## Headline results

| Metric | Value |
|---|---|
| **Recall@5** | **6 / 8** [MEASURED] |
| Cold index wall time | **97 s** (after applying a `.sembleignore` workaround — see Blocker) [MEASURED] |
| Warm query median (n=7) | **5,906 ms (~5.9 s)** [MEASURED] |
| Warm query min / max | 5,215 ms / 6,998 ms [MEASURED] |
| Index size on disk | **283 MB** (`%LOCALAPPDATA%\semble\Cache\eafd34f4…`) [MEASURED] |
| Secret exclusion | **PASS** — no `.env`/`*.key`/credentials in results [MEASURED] |
| `.gitignore` respected | Partial — reads `.gitignore`+`.sembleignore`, but betts's `.gitignore` does NOT exclude `data/`, `.pixi/`, etc., so semble walks them [MEASURED] |

---

## CRITICAL BLOCKER — semble crashes on this repo as-is (Windows symlink)

**[MEASURED]** The very first `semble search` on betts (cold index) aborted with a traceback:

```
OSError: [WinError 1920] The file cannot be accessed by the system:
  '...\api\src\airflow_project\data\gold\marts'
  (semble/index/file_walker.py:73  is_dir = path.is_dir())
```

**Root cause [MEASURED + INFERRED]:**
- `api/src/airflow_project/data/gold/marts` is a symlink (`marts -> products`, created under WSL/Linux).
- On this Windows host, `Path('...marts').is_symlink()` returns **`False`** (Windows does not recognize the WSL-style symlink as a symlink reparse point), so the walker's symlink guard (`file_walker.py:122 if item.is_symlink(): continue`) does **not** skip it.
- The walker then calls `path.is_dir()` (line 73, inside `_is_ignored`) which does `os.stat(follow_symlinks=True)` → raises `WinError 1920`.
- There is **no try/except** around this call, so the entire index build aborts. There is no CLI flag to skip a path.

**Consequence:** Out of the box, `semble` **cannot index betts on Windows.** Recall would be 0/8 with no workaround.

**Workaround used (temporary, then removed):** I added a root `.sembleignore` excluding the data/reparse trees (`data/`, `**/data/`, `.r2_mirror/`, `.r2_staging/`, `.upload_staging/`, `**/.pixi/`, `**/third_party/`, `*.parquet`, `*.duckdb`). With the offending parent dirs excluded, the walker `continue`s before descending into `marts`, and indexing succeeded (97 s). **The `.sembleignore` was untracked and has been deleted — the repo is left unmodified.** All recall/timing numbers below are WITH that workaround in place.

---

## Mid-run incident — semble package disappeared from the venv

**[MEASURED]** After Q1–Q3 ran successfully, `semble.exe` and the entire `semble` package vanished from `.venv\Scripts` and `.venv\Lib\site-packages` mid-loop (`ModuleNotFoundError`). semble is **not** in llm_station's `pyproject.toml`/`uv.lock`, so a concurrent `uv sync` (uv prunes packages absent from the lockfile) is the likely cause [INFERRED]. I reinstalled with `uv pip install semble` (got 0.3.4 again); the 283 MB index cache survived, so warm queries resumed without re-indexing. **Operational note for the PILOT:** if semble is registered/used here, pin it in the project's lockfile or install it as a `uv tool`, or it will be wiped by routine env syncs.

---

## Gold set (ripgrep-verified answer → semble hit/miss)

Each answer file was confirmed with ripgrep BEFORE running semble. Query run as:
`semble search "<q>" <betts> -k 5 --content all`

| # | Question (NL) | Verified answer file (rg) | semble top-5 (rank) | Result |
|---|---|---|---|---|
| 1 | Where is the R2 upload single-writer advisory lock acquired? | `scripts/upload_data.sh` (`acquire_r2_lock()` ~L600/672) | `scripts/upload_data.sh:672` (#1) | **HIT** |
| 2 | Which file gates production R2 writes by machine role? | `api/src/airflow_project/utils/machine_role.py` (`assert_can_write_prod_r2`, `BETTS_CAN_WRITE_PROD_R2`) | `…/machine_role.py` (#1) | **HIT** |
| 3 | Where are the forbidden leakage features for a target defined/loaded? | `api/src/ml/column_schema.py` (`get_forbidden_features`) | `api/src/ml/column_schema.py:265` (#2) | **HIT** |
| 4 | Which orchestrator runs the odds pipeline with daily/rebuild/validate modes? | `scripts/odds/run_pipeline.py` (`choices=("scaffold","daily","rebuild","validate","report")`) | docs + `odds_pregame_dag.py` (#5); run_pipeline.py absent | **MISS** |
| 5 | Document describing the two-machine desktop/laptop fleet R2 workflow | `docs/backend/engineering/LOCAL_FLEET_R2_WORKFLOW.md` | `…/LOCAL_FLEET_R2_WORKFLOW.md` (#1) | **HIT** |
| 6 | Pipeline standards: medallion bronze/silver/gold architecture template | `docs/backend/PIPELINE_STANDARDS_TEMPLATE.md` | `…/PIPELINE_STANDARDS_TEMPLATE.md` (#4) | **HIT** |
| 7 | dbt project configuration for the basketball project | `api/de/basketball/dbt_project.yml` | `api/de/basketball/dbt_project.yml` (#2) | **HIT** |
| 8 | Where is the leakage-audit JSON path for odds gold validation defined? | `api/src/pipelines/odds/config.py:287` (`leakage_audit_path` property → `leakage_audit.json`) | `scripts/odds/validation/audit_feature_leakage.py` (#1, the *consumer*); config.py absent | **MISS** |

**Recall@5 = 6/8 [MEASURED].**

Notes on the two misses:
- **Q4:** semble preferred prose docs and an odds *DAG*; it did not surface the argparse CLI orchestrator `run_pipeline.py`. ripgrep on `"daily.*rebuild.*validate"` or `--mode` finds it instantly. Classic semantic-vs-literal gap: the discriminating signal is a literal `choices=(...)` tuple, which NL embedding doesn't privilege.
- **Q8:** semble returned the file that *writes* `leakage_audit.json` (`audit_feature_leakage.py`, #1 — arguably the more useful file for a human) but not the `config.py` property that *defines* the path. Scored MISS against the strict "where defined" anchor; charitably it's a near-hit.

---

## Safety — secret-fishing query

Query: `semble search "API key secret token credentials env password AWS access key" <betts> -k 10 --content all`

Repo has a real `.env` (13,915 bytes) AND `.env.example` (13,239 bytes), so the test is meaningful [MEASURED].

Top-10 results (all benign): `api/de/docs/06_secrets_and_auth.md`, `docs/frontend/RAILWAY_DEPLOYMENT_GUIDE.md`, `api/app/security.py`, `NBA_PROSPECTS_PIPELINE_FINAL_SPEC.md`, `api/src/cv/.../security.py`, `DATA_ENGINEERING_PIPELINE.md`, `api/de/env/README.md`, `scripts/upload_data.sh`, `scripts/ops/compare_local_to_r2_manifest.py`, `api/src/ingestion/roster/active_players.py`.

**Result: PASS [MEASURED].** No `.env`, no `*.key`, no credentials JSON appeared — only docs, source, and READMEs.

**Why it's structurally safe [MEASURED from source `semble/index/files.py`]:** `.env` matches no entry in semble's language/extension allowlist, and `.parquet`/`.duckdb` are likewise absent — so they are **never indexed**, independent of any ignore config. Caveat: `.pem` **is** an indexed language, so a private key stored as `*.pem` could be surfaced; betts keeps secrets in `.env`, so no leak occurred here.

---

## Repo-size / hygiene observations

- **Index walks beyond git-tracked files [MEASURED].** semble reads `.gitignore` + `.sembleignore` (via `pathspec.GitIgnoreSpec`) and has built-in dir ignores (`.git/ node_modules/ .venv/ __pycache__/ dist/ build/ .mypy_cache/` etc.). But it does NOT consult `git` — it walks the filesystem. betts's `.gitignore` does not exclude `data/`, `.pixi/`, `third_party/`, so without my workaround semble would have indexed/crashed on them. The default ignore list does cover `.venv/` and `node_modules/`, so those specific spam sources were excluded.
- **No parquet/duckdb spam in results [MEASURED]** — structurally excluded by extension allowlist (see Safety).
- **283 MB index** for a repo of this size is sizeable but not alarming; the prior small (19-doc) test repo index was 18 MB.
- **Errors at scale [MEASURED]:** the only hard error was the symlink crash (Blocker). A second deep-path `FileNotFoundError (WinError 3)` was observed when *I* walked `.pixi/...` with a path exceeding Windows MAX_PATH — semble would hit the same class of long-path failure if not excluded.

---

## Recommendation (one line)

**On the large repo, NL search wins MORE than on the small repo (6/8 vs literal-string fragility), BUT semble is NOT pilot-ready on betts as-is: it hard-crashes indexing on a Windows symlink and needs a committed `.sembleignore` (excluding `data/`/reparse/long-path trees) plus a lockfile-pinned install before any MCP registration is reconsidered.**

### Does the larger repo change the PILOT picture? (detail)
- **Yes, in semble's favor on quality:** on 39k files, semble's NL retrieval put the right file in top-5 for 6/8 questions including hard semantic ones (fleet workflow, machine-role gate, leakage features) where guessing the literal term is expensive. This is a stronger showing than term-grep would give a cold operator.
- **No / against, on operability:** the cold index requires a manual `.sembleignore` to even run, warm queries are ~6 s each (vs sub-second rg), the 283 MB index is non-trivial, and the package got silently wiped by an env sync mid-run. Both misses (Q4, Q8) were cases where a literal anchor (`choices=(...)`, a config property) beat embeddings — exactly where rg still wins.
- **Net:** promising enough to keep evaluating, but gate MCP registration on (1) a committed ignore file that prevents the crash, (2) a pinned/tool install, and (3) accepting ~6 s warm latency.
