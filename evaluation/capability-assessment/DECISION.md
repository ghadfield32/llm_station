# Batch 1 — final dispositions & comparison matrix (Stage 11)

Date: 2026-06-12. Authoritative over the Part C pre-registration in
`docs/capability-evaluation-loop.md`. All numbers are LOCALLY_REPRODUCED and
independently verified (`verifier-report.md`) unless labeled otherwise.

## Comparison matrix

| Field | semble | abtop | asm |
| --- | --- | --- | --- |
| repository_problem | high token cost / term-guessing in repo retrieval | no live agent-session visibility | manage scattered skills |
| current_baseline | ripgrep + native Glob/Read | retrospective usage_digest.py | **none — zero skills exist** |
| proposed_seam | repository retrieval (optional) | observability (read-only) | skill layer |
| measured_quality_delta | recall@5 **7/10** small repo · **6/8** on betts (but indexing crashes w/o `.sembleignore`) | **7/7** Claude sessions detected on Windows | n/a (not run) |
| measured_token_delta | **no clear reduction** vs skilled rg (operator-dependent) | n/a (out-of-band) | n/a |
| measured_cost_delta | $0 (local CPU) | $0 | n/a |
| measured_latency_delta | +1.7–1.9 s/query warm | +0.54 s one-shot, out-of-band | n/a |
| resource_delta | 18 MB index + ~50 MB model | 16.9 MB RAM, ~0.5% CPU | n/a |
| security_result | PASS (.env excluded; 1 one-time HF download) | PASS (read-only verified; --setup avoided) | regex-only audit, unsigned "manifests", single-maintainer registry |
| license_result | MIT | MIT | MIT |
| operational_burden | low; index freshness auto-managed | very low; single binary | n/a |
| rollback_result | PASS (uninstall + delete cache) | PASS (delete bin/) | n/a |
| verifier_result | safety all PASS; R1 at bar; R2 INCONCLUSIVE | all PASS; Codex 0/4 caveat | n/a |
| confidence | medium-high | high | high (on the no-use-case finding) |
| **decision** | **PILOT — blocked on betts** (needs `.sembleignore` + lockfile pin) | **PILOT** | **DEFER** |

Ranking (correctness/safety → repo value → measurable improvement → fit →
simplicity → cost): **abtop > semble > asm.**

## Dispositions & rationale

### abtop → PILOT (operator tool)

All safety + required criteria pass; read-only confirmed; 7/7 Claude
detection on Windows; stable `--json` that can feed `usage_digest.py` / the
morning brief. **Not ADOPT yet** only because: (1) Codex detection is 0/4 on
Windows — a real gap given Codex is the fallback executor here; (2) it's a
2.5-month-old single-author project. **Smallest safe next step:** keep the
pinned binary in the eval dir; manually run `abtop --json` when an operator
wants a live view. Wiring it into the brief is a *separate* L2 mission and
must (a) shell the pinned binary read-only, (b) never run `--setup`. Re-test
Codex detection on a new release before ADOPT.

### semble → PILOT (optional retrieval path)

Safety clean (the key result: `.env` never surfaced), 7/10 NL-query recall
with no term-guessing, auto-reindex with no silent staleness. **Not ADOPT**
because the headline "98% fewer tokens" did not reproduce as a real reduction
against a skilled targeted-ripgrep flow (its genuine edge is natural-language
queries, not raw token savings), and R2 (corrupt-index loudness) is
inconclusive. **Smallest safe next step:** keep `semble==0.3.4` available for
manual `semble search` on the larger betts_basketball repo (where
term-guessing costs more), measured the same way, before deciding on MCP
registration. Registering it as an MCP server in Claude Code is a *separate*
L2 decision — do not run `semble install` (it edits agent config); use the
explicit `claude mcp add` line instead, and keep native Glob/Grep as the
primary path (semble stays optional).

### asm → DEFER (no current use case)

Knocked out at Stage 0/2: **zero skill files exist across all providers**, so
there is nothing to inventory or audit; no Windows support in source; the
"signed manifests" claim is false (unsigned JSON + pinned commit) and the
registry is a single-maintainer surface feeding code into agent skill dirs.
**Re-evaluation conditions:** ≥5 real skill files across ≥2 providers AND
verified Windows support (or post-Linux-migration) AND real manifest signing
or genuine registry curation. Until then, manage skills as ordinary gated
worktree edits under the existing `skill_updates` L2 cap.

## PILOT next-step outcomes (2026-06-12, human-approved)

- **abtop → wired (read-only, opt-in).** Added `--abtop` / `--abtop-bin` to
  `src/command_center/cli/usage_digest.py`: an opt-in "Active Agent Sessions"
  section that shells the pinned binary with `--json` only (never `--setup`),
  fail-loud if the binary is missing (exit 1), section omitted by default.
  Verified live (8 Claude sessions). ruff/mypy/compile clean, no new deps,
  baseline still PASS, vendored binary gitignored (reproducible from the
  manifest). **ADOPT still blocked** by Codex 0/4 on Windows; the
  re-test-on-newer-release step is **deferred because v0.4.8 is still the
  latest abtop release** — nothing newer exists to test yet. Detail:
  `abtop/PILOT-NOTES.md`.
- **asm → parked (DEFER).** No action; re-evaluation conditions written down
  in `asm/PARKED.md` (≥5 skills across ≥2 providers AND verified Windows
  support AND real manifest signing/registry curation).
- **semble → benchmarked on betts_basketball** (39k-file repo); result in
  `semble/betts-benchmark.md`. **Recall@5 6/8** (NL search held up on harder
  semantic queries — the large-repo hypothesis was supported), **secret
  exclusion PASS** (structural: `.env`/`.parquet`/`.duckdb` aren't in semble's
  index allowlist; caveat: `.pem` *is* indexable). **But two real blockers
  surfaced, so MCP registration is NOT recommended yet:**
  1. **Hard crash indexing betts out-of-the-box** — semble's Windows file
     walker dies with `WinError 1920` on a WSL-style symlink
     (`api/src/airflow_project/data/gold/marts -> products`); `Path.is_symlink()`
     returns False on Windows and the following `is_dir()` isn't guarded.
     Confirmed independently (even bash `ls` fails on that path with "Function
     not implemented"). As-is, recall on betts is **0/8**; the 6/8 required a
     temporary `.sembleignore` (the agent added it, measured, then **deleted
     it — betts left unmodified**, verified clean).
  2. **Package pruned mid-run** — semble vanished from `.venv` after a
     concurrent `uv sync` because it is **not in `uv.lock`**. Reinstalled;
     index cache survived. A real pilot must pin it (lockfile or `uv tool
     install`), not a bare `uv pip install`.
  - 283 MB index, ~5.9 s warm query (n=7) on this repo — notably slower/larger
    than the small repo. No MCP registration performed; `semble install` not
    run (it edits agent config).
  - **Gate before any semble MCP pilot on betts:** (a) a committed
    `.sembleignore` excluding the symlinked data/reparse trees, (b) a
    lockfile-pinned install, (c) acceptance of ~6 s warm latency. Until then
    semble is **not pilot-ready on betts** — keep native Glob/Grep primary.

## What changed / did NOT change (authority boundaries intact)

The **evaluation itself** modified no config, contract, service, or pipeline
file. The **approved abtop PILOT next step** made exactly one source edit:
`src/command_center/cli/usage_digest.py` gained an opt-in, read-only `--abtop`
section (operator-surface only — `usage_digest` is an operator/scheduled
script, not the secret-free proactive runner; it touches no gateway, Ledger,
gate, judge, or contract). semble lives in `.venv` only (not in
`pyproject.toml`); abtop's binary lives in `evaluation/.../bin/` only (not on
PATH, gitignored). No MCP registration, no hooks, no `--setup`, no provider
keys, no scheduled work, no branch pushed. Deterministic baseline re-runs PASS
at the (concurrently relocated) `src/command_center/cli/` module paths.

## Files produced

```text
evaluation/capability-assessment/
├── repository-baseline.md / .json
├── stage2-3-gates-and-fit.md
├── DECISION.md                      (this file)
├── verifier-report.md
├── semble/{evidence.md, threat-model.md, benchmark-plan.yaml,
│           acceptance-rubric.yaml, results.md, betts-benchmark.md,
│           install-manifest.json, rollback.md,
│           raw/q01..q10, secret-test, stale, rebuild, timing}
├── abtop/{evidence.md, threat-model.md, benchmark-plan.yaml,
│           acceptance-rubric.yaml, results.md, PILOT-NOTES.md,
│           install-manifest.json, rollback.md,
│           bin/ (gitignored), raw/snapshot-1..2.json}
└── asm/{evidence.md, PARKED.md}

Source edit (approved abtop PILOT): src/command_center/cli/usage_digest.py
(+ .gitignore rule for the vendored abtop binary).
```

## Completion-rule check (loop §20)

Every claim labeled by evidence type ✓ · baseline vs candidate compared under
equal conditions ✓ · deterministic checks passed ✓ · failure behavior tested
(missing index; Codex-absent) ✓ · rollback demonstrated ✓ · independent
verifier reproduced critical evidence ✓ · authority/approval boundaries
intact ✓ · dispositions justified by measured repo-specific results ✓.
**Nothing installed into production, promoted, scheduled, pushed, merged, or
deployed.** Stop here; await human approval for any PILOT next step.
