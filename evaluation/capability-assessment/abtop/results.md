# Results — abtop v0.4.8 (Stage 7, LOCALLY_REPRODUCED)

Run 2026-06-12, Windows 11. Binary: GitHub release asset
`abtop-x86_64-pc-windows-msvc.zip`, sha256
`412de34188f12af646b44e28d9958e18bbbb867cab4766d4c829621007f3f454`, kept in
`bin/` (never on PATH). Raw: `raw/snapshot-1.json`, `raw/snapshot-2.json`.

## Detection (vs `tasklist` ground truth at run time)

| Agent | Running (ground truth) | Detected | Verdict |
| --- | ---: | ---: | --- |
| Claude Code | 7 × claude.exe | **7 sessions** (agent_cli=claude) | **PASS** — full detection |
| Codex CLI | 4 × codex.exe | **0 sessions** | **FAIL on Windows** — real gap (upstream uses mtime heuristics on Windows for fd mapping) |

Detected Claude sessions carried rich, correct-looking data: pid, model
(claude-fable-5 / claude-opus-4-8 — including this very session), status
(Waiting/Executing), context_percent, input/output/cache tokens, cwd, git
branch, tool_calls, subagents, mem_mb.

## Output quality

- `--json` one-shot: exit 0, **valid JSON**, 60.8 KB, **schema stable across
  two runs** (identical top-level + session field sets).
- 32 session fields — directly consumable by `usage_digest.py` / morning
  brief.
- `rate_limits`: **empty** — populating it requires `abtop --setup` (the
  statusLine hook we forbid). Rate-limit visibility is therefore unavailable
  under our constraints.

## Overhead

One-shot snapshot: **0.54 s wall**. Steady-state TUI overhead not measured
(one-shot is the integration-relevant mode); R2 marked NOT_APPLICABLE for
one-shot, INCONCLUSIVE for TUI.

## Read-only verification (S1)

After two runs: no files created in `~/.claude/` (no abtop-statusline.sh, no
abtop-rate-limits.json), no `~/.cache/abtop/`, `settings.json` contains no
statusLine. **PASS** — strictly read-only as exercised.

## Rubric outcome (self-assessment; Verifier confirms)

S1 PASS · S2 PASS (no keys) · S3 PASS (no network observed; UC label on full
no-telemetry claim stands) · S4 PASS (pinned asset + hash; removal = delete
dir) · R1 PASS (7/7 Claude on Windows) · R2 NOT_APPLICABLE (one-shot) ·
I1: Codex detection FAIL on Windows; token figures plausible, no local ground
truth · I2 PASS (stable JSON, digest-ready).
