# Evidence — abtop (Stage 1)

Collected 2026-06-12 by Investigator (independent context) from authoritative
sources: github.com/graykode/abtop (README, source, releases, issues),
crates.io/crates/abtop. Labels: VERIFIED_UPSTREAM_FACT (VUF),
UPSTREAM_CLAIM_NOT_YET_REPRODUCED (UC), LOCALLY_REPRODUCED (LR), INFERENCE
(INF), UNKNOWN (UNK).

## Identity & maturity

- VUF: `github.com/graykode/abtop` exists, matches the description; default
  branch `main`, created 2026-03-29; MIT (LICENSE file + registry metadata).
- VUF: crates.io crate `abtop`, latest **v0.4.8** (2026-06-08), 14 versions,
  ~1,537 downloads; also Homebrew tap + shell/powershell installers via
  cargo-dist.
- VUF: ~2,810 stars, 266 forks, 25 contributors (graykode 334 commits
  dominant), CI present, last push 2026-06-08.
- INF: ~2.5-month-old, single-dominant-author, actively released.

## Mechanism (decides the read-only question)

- VUF: Claude Code detection = process scan + reading
  `~/.claude/sessions/{PID}.json` + incrementally tailing JSONL transcripts
  under `~/.claude/projects/`; tokens parsed from transcript `message.usage`.
- VUF: Codex detection = process scan + fd/mtime mapping to
  `~/.codex/sessions/.../rollout-*.jsonl`; rate limits parsed from local
  `token_count` events.
- VUF: **Default operation is read-only** (files + process metadata). README:
  "All read-only. No API keys. No auth."
- VUF (CAVEAT): **`abtop --setup` is NOT read-only** — it edits
  `~/.claude/settings.json` (adds a `statusLine` hook) and writes
  `~/.claude/abtop-statusline.sh`; **no automated teardown exists**.
- VUF: No HTTP clients in the rate-limit/codex collectors — limits come from
  local cache files, not provider APIs. One indirect network path: optional
  session-summary shells out to `claude --print` (user's own auth).
- UC: "no telemetry" — consistent with inspected modules; full source tree
  not audited.

## Install / Windows / output

- VUF: `cargo install abtop`, or release binaries (x64+ARM64 windows-msvc),
  or PowerShell installer script. Native Windows (sysinfo, `netstat -ano`,
  `%USERPROFILE%\.claude`), no WSL.
- VUF: `abtop --json` = one-shot JSON snapshot; serializable `Snapshot`
  struct. UNK: no formal schema/stability guarantee documented.
- VUF: context-window % is an **estimate** (input + cache_read, window size
  guessed from model name); open issue #135 "did not see my claude code
  sessions" (2026-06-11) — detection is not guaranteed.

## Rollback

- VUF: no uninstall docs; INF: `cargo uninstall abtop` (or delete binary) +
  if `--setup` was ever run, manually revert `~/.claude/settings.json` and
  delete the statusline script + cache files. **Mitigation for this
  evaluation: never run `--setup`.**

## Stage-2 relevance summary

No keys, no auth, local-only data flow, MIT, pinnable (`cargo install
abtop --version 0.4.8` or pinned binary), isolated, removable. The only
global-modification path (`--setup`) is optional and excluded from the
experiment.
