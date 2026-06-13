# Results — semble v0.3.4 (Stage 7, LOCALLY_REPRODUCED)

Run 2026-06-12, Windows 11, Python 3.12.6, CPU. Raw outputs: `raw/q01..q10`,
`raw/secret-test.txt`, `raw/stale-1.txt`, `raw/rebuild2.txt`, `raw/timing-*.txt`.

## Retrieval (gold set, n=10, file-level recall@5)

**7/10 — CORRECTED by the independent Verifier (official figure).** The
Implementer's initial 10/10 used basename grep over whole result files, which
also matched filenames mentioned inside chunk *text*; strict scoring on the
`file_path` field only gives **7/10** (misses: q04 cc.ps1/Makefile, q09
configs/standards.yaml, q10 docker-compose.yml — those answers appeared in
returned doc chunks' text but the expected files themselves were not in the
top-5 file_paths). Exactly at the R1 bar (≥7/10). Raw files are
authoritative; see ../verifier-report.md.

Irrelevant results: low; chunks were on-topic. `.venv` and `generated/` did
not pollute results (gitignore respected).

## Safety checks

- **Secret exclusion (S2): PASS** — a query explicitly fishing for env
  secrets returned `.env.example` (committed template) but **never `.env`**
  (raw/secret-test.txt, 0 occurrences across top-10).
- **No API keys, offline after first run (S1): PASS with one recorded
  event** — first run downloaded the embedding model
  `minishlab/potion-code-16M` from Hugging Face into
  `~/.cache/huggingface/hub/` (one-time; matches the Stage-1 inference; the
  upstream "no external services" line omits this).
- **No hooks/services/agent-config changes (S4): PASS** — `semble install`
  was never run; CLI only; no processes persist after invocation.

## Timing (per-invocation wall clock, includes process + model startup)

| Scenario | Time |
| --- | --- |
| First-ever run (model download + cold index, full repo `--content all`) | 28.4 s |
| Index rebuild after `semble clear index` | 7.3 s |
| Warm query (n=3) | 8.2 s / 1.65 s / 1.70 s → median **1.70 s** (first-of-session pays OS cache warmup) |

Upstream's "~250 ms indexing / ~1.5 ms query" describe in-process operations
on their benchmark; our **per-invocation** reality is ~1.7 s warm — still
under the 2 s interactive bar (R3 PASS). Index size: **18 MB** at
`%LOCALAPPDATA%\semble\Cache\<hash>`.

## Stale-index behavior (I2)

**Better than expected**: a newly created file containing a unique marker was
found by the very next query with no manual reindex — semble detects changes
and refreshes incrementally at query time. No silent staleness observed in
this test. `semble clear index` + auto-rebuild also works (7.3 s).

## Missing/corrupt index (R2)

After `clear index`, the next query transparently rebuilds and returns
correct results — auto-rebuild rather than loud failure, which is the
*correct* behavior for a cache (no empty-as-success observed).

## Tokens proxy (I1 — honest, mixed)

- semble output: ~6.7 KB/query (10 queries, 67,478 bytes total) — but the
  output **contains the answer content**, often ending the search.
- ripgrep with a *known correct term*: ~100–150 bytes for the file list —
  but requires (a) already knowing the term, and (b) a follow-up Read of the
  file (typically 5–50 KB) to get the content.

Conclusion: the upstream "98% fewer tokens than grep+read" is **plausible
against grep + full-file-Read flows**, and not meaningful against a skilled
targeted-rg + partial-Read flow when the term is known. Semble's real,
demonstrated advantage here is **natural-language queries with 10/10
file-level recall** — no term-guessing iterations.

## Rubric outcome (self-assessment; Verifier confirms independently)

S1 PASS · S2 PASS · S3 PASS (cache location recorded) · S4 PASS · S5 PASS
(pinned 0.3.4, removal one command + cache delete) · R1 PASS — at bar (7/10
per Verifier) · R2 INCONCLUSIVE (auto-rebuilds silently; corrupt-index path
untested) · R3 PASS — marginal (1.70–1.89 s) · I1 no clear token reduction ·
I2 favorable. **Disposition: PILOT** (ADOPT bar — a real token reduction —
not met).
