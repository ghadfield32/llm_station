# Evidence — asm (Stage 1)

Collected 2026-06-12 by Investigator (independent context) from authoritative
sources: github.com/luongnv89/asm (README, LICENSE, src/config.ts,
src/security-auditor.ts, src/publisher.ts, postinstall, issues),
registry.npmjs.org/agent-skill-manager, github.com/luongnv89/asm-registry.
Labels: VUF / UC / LR / INF / UNK.

## Identity & maturity

- VUF: `github.com/luongnv89/asm` exists ("The universal skill manager for AI
  coding agents"); TypeScript (Ink/React TUI); MIT (LICENSE file).
- VUF: npm `agent-skill-manager` v2.11.0 (release 2026-06-09); Node >=18 <23.
- VUF: **576 stars** (the "313 stars" claim was stale), 27 open issues,
  created 2026-03-11 (~3 months old).
- VUF: **single-maintainer project** — luongnv89 399 commits, next
  contributor has 1. CI + Vitest tests present.

## Claim-vs-reality (the important deltas)

| Claim | Verdict |
| --- | --- |
| TUI manager across 19 providers | VUF — 19 providers enumerated in `src/config.ts` |
| `asm audit security` | VUF feature exists — but it is **purely static regex heuristics** (8 pattern families). No LLM, no signatures, no sandboxing. |
| "Signed manifests" | **FALSE** — manifests are plain JSON with a pinned commit SHA; `checksum` field is reserved/unimplemented; trust root is GitHub identity only. |
| Registry | VUF: `luongnv89/asm-registry` — a personal repo, **0 stars**, ~7 commits, mostly the maintainer's own manifests; gatekeeping is automated CI, no human security review. |
| "No telemetry" | UC — consistent with inspected postinstall/config code; full runtime not audited. |

## Writes / Windows / rollback

- VUF: writes to per-agent skill dirs (`~/.claude/skills/`, `~/.codex/skills/`,
  `~/.cursor/rules/`, ... 19 providers) + its own state under
  `~/.config/agent-skill-manager/`. No hooks/services found in inspected code;
  `asm link` uses symlinks.
- VUF: **no `process.platform === 'win32'` handling, no APPDATA logic, bash
  install.sh** — Windows untested/unsupported in practice (may incidentally
  run via os.homedir()). Windows CI: UNK.
- INF: full rollback = `npm uninstall -g agent-skill-manager` + delete
  `~/.config/agent-skill-manager/` + remove any skill files/symlinks it wrote
  into agent dirs. No documented bulk-purge command (UNK).

## Supply-chain risk profile (INF, well-grounded)

One individual controls the CLI, the npm package, and the registry; audit is
regex-only and evadable; manifests unsigned; registry has ~zero community
adoption. A compromised maintainer account or a regex-evading skill defeats
every current protection — and skills execute inside coding agents, a
high-trust position.

## Stage-0 cross-check

This environment has **zero skill files** across all providers
(repository-baseline.md): there is no inventory to manage, no duplicates to
detect, nothing to audit. The problem asm solves does not exist here today.
