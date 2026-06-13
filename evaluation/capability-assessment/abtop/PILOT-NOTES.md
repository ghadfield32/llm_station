# abtop — PILOT next-step outcome (2026-06-12)

Approved next step: "wire the pinned binary's read-only `--json` into
usage_digest.py / the morning brief — never `--setup`. Re-test Codex
detection on a newer release before ADOPT."

## Done

- **Wired into `src/command_center/cli/usage_digest.py`** as an **opt-in,
  read-only** section:
  - New flags: `--abtop` (include the snapshot) and `--abtop-bin PATH`
    (override). Resolution order: `--abtop-bin` > `ABTOP_BIN` env >
    `evaluation/capability-assessment/abtop/bin/abtop.exe`.
  - Invokes **only `<bin> --json`** — `--setup` (the one mutating path) is
    never called, so `~/.claude/settings.json` is never touched.
  - **Fail-loud**, no defensive fallback: if `--abtop` is requested and the
    binary is absent, the command exits 1 with an actionable message (verified:
    exit code 1). A *runtime* exec/parse failure surfaces as a visible
    `abtop unavailable: ...` line in the report (not swallowed).
  - Default behavior unchanged: without `--abtop`, the section is omitted and
    `evidence["abtop"]` is `None`.
  - Adds a "## Active Agent Sessions (abtop, read-only)" table: pid, cli,
    model, status, context %, project; plus a by-CLI count.

- **Verified live**: `usage_digest --abtop` rendered 8 live Claude sessions
  across llm_station and betts_basketball with correct model/status/context
  attribution.

- **Checks**: `py_compile` OK · `ruff` clean · `mypy` clean on all added code
  (the one mypy error in the file is pre-existing on line 168, untouched) ·
  no new dependencies (`json`/`subprocess` are stdlib, so the uv standard
  needs nothing added) · `validate_config` still PASS.

- **Binary hygiene**: the vendored `abtop.exe` is now gitignored
  (`evaluation/capability-assessment/abtop/bin/`); it is reproducible from the
  pinned `v0.4.8` + sha256 `412de3…f454` recorded in `install-manifest.json`.

## Still blocking ADOPT (unchanged)

- **Codex detection 0/4 on Windows** remains the gap. The re-test could not be
  performed against a *newer* release because **v0.4.8 (2026-06-08) is still
  the latest** abtop release as of 2026-06-12 — there is nothing newer to test.
  Re-run the Stage-7 Codex check when a release > v0.4.8 ships; promote to
  ADOPT only if Codex sessions are then detected on Windows.

## Scope guard

This wiring is operator-surface only (`usage_digest` is an operator/scheduled
script, not the secret-free proactive runner). It does not touch the gateway,
Ledger, gates, judges, or any contract. The morning-brief integration in
Growth OS (`growthos/brief.py`) is intentionally **not** done here — that's a
separate repo/surface and a separate decision; this PILOT proves the
read-only data path in the command-center digest first.
