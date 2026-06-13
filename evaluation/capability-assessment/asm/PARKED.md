# asm — PARKED (DEFER), 2026-06-12

No action taken, by decision. asm was knocked out at Stage 0/2 (DECISION.md):
there are **zero skill files** across every provider directory, so there is no
inventory to manage, no duplicates to detect, and nothing to audit; no Windows
support in source; the "signed manifests" claim is false; and the registry is
a single-maintainer surface that would feed code into agent skill dirs.

## Re-evaluation conditions (re-run the loop only when ALL hold)

1. **A real problem exists**: ≥5 skill files accumulate across ≥2 provider
   directories (e.g. `~/.claude/skills/`, `~/.codex/skills/`) — enough scatter
   that manual inventory is genuinely painful.
2. **Platform fit**: asm ships verified Windows support (win32 path handling,
   not just incidental `os.homedir()`), OR this stack has migrated to Linux.
3. **Trust surface improves**: manifests gain real cryptographic signing
   (the `checksum`/content-addressing field becomes implemented), OR the
   registry gains genuine multi-party curation — so installing a skill isn't
   trusting one person's account.

## Until then

Manage skills the way the system already prescribes: as ordinary gated
worktree edits under the `configs/standards.yaml` `skill_updates` policy
(auto-propose from RCA, capped at L2, normal judges apply). No third-party
skill manager is in the trusted path.

Review cadence: same as the model registry / Mirage watch-list — revisit when
a condition above plausibly changes, not on a timer.
