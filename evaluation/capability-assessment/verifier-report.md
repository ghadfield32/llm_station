# Independent Verifier report (Stage 9)

Verifier: fresh agent context, no access to Implementer conclusions
(results.md / stage2-3 / evidence.md were excluded from its inputs). It
re-ran sample gold queries, the secret test, fresh abtop snapshots, hash
verification, read-only checks, and the full deterministic baseline.

## semble v0.3.4

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| S1 no keys/offline | PASS (caveat) | query + full rebuild succeed with `HF_HUB_OFFLINE=1`; only network = one-time HF model download |
| S2 .env excluded | PASS | re-ran secret query; `.env` (which exists and holds LITELLM_MASTER_KEY) never returned; `.env.example` only |
| S3 writes recorded | PASS | footprint = %LOCALAPPDATA%\semble (18 MB) + HF cache only |
| S4 no agent-config changes | PASS | `claude mcp list` clean; ~/.claude.json has no semble; no AGENTS.md |
| S5 pinned + removable | PASS | 0.3.4 exact; not in pyproject (trial-scoped); one-command removal |
| R1 recall@5 ≥ 7/10 | **PASS — exactly at bar (7/10)** | verifier scored file_path-strict: misses q04, q09, q10; its 4 re-run queries matched raw rankings |
| R2 loud failure | INCONCLUSIVE | missing index silently auto-rebuilds (no empty-as-success, but not loud); corrupt-index test blocked by permission classifier |
| R3 latency < 2 s | PASS — marginal | verifier's own timings 1.70 s / 1.89 s |
| I1 tokens proxy | no clear reduction | spot check q08: semble 7,568 B vs rg 6,250 B; highly operator-dependent |
| I2 stale index | favorable | auto-reindex per query confirmed (found post-refactor src/ paths without manual reindex) |

**Scoring discrepancy resolved against the Implementer**: the Implementer's
initial 10/10 used basename grep over whole result files, which also matched
filenames mentioned inside chunk *text*; the Verifier scored the `file_path`
field only → **7/10 is the official recall figure**. Raw files are
authoritative and support the Verifier.

**Verifier disposition for semble: PILOT, not ADOPT** (rubric's own rule:
ADOPT requires a real token reduction; not demonstrated).

## abtop v0.4.8

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| S1 read-only | PASS | no ~/.claude/abtop*, no statusLine, no ~/.cache/abtop after TUI + JSON runs |
| S2 no keys | PASS | provider env vars clean; full output produced |
| S3 network | PASS (caveat) | only documented indirect path (`claude --print` summaries — unused); summaries shown are verbatim local transcript text; no packet capture performed |
| S4 pinned + removable | PASS | zip sha256 matches `412de3…f454`; removal = delete bin/ |
| R1 Claude detection | PASS | fresh run: 7/7 claude.exe detected with plausible per-session attribution |
| R2 overhead | PASS | TUI sampled: 16.9 MB RAM, ~0.49% machine CPU (24 cores) |
| I1 Codex detection | **FINDING: 0/4** | 4 codex.exe running, 0 detected — complete miss on Windows |
| I2 JSON stability | PASS | 3 independent snapshots: identical schema |

**Verifier disposition for abtop: ADOPT for operator use** (all safety +
required pass), with the Codex-on-Windows gap documented.

## Repository safety

validate_config PASS · run_evals PASS (6/6) · smoke_mission PASS ·
check_forbidden_providers PASS · provider env vars clean · footprint as
declared · stale-test scratch file confirmed cleaned up · staged
`.gitmodules`/AppFlowy-Cloud submodule flagged as other-session work (not
eval-related). **No fabrication indicators; no hidden changes; no network
surprises.**

## Process notes

- The deterministic baseline moved mid-evaluation (`scripts/*.py` →
  `src/command_center/cli/`, schemas → `src/command_center/schemas/`) due to
  a concurrent session's refactor; both Implementer and Verifier re-ran the
  suite at the new paths (PASS). The benchmark-plan gold-set paths were
  updated to the new locations.
- semble raw `timing-*.txt` files contain query outputs, not timings — the
  Implementer's latency figures are not reconstructible from raw; the
  Verifier's own measurements (1.70/1.89 s) are the official ones.
