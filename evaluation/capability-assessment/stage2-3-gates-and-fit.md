# Stage 2 (knockout gates) + Stage 3 (architecture fit) — Batch 1

Date: 2026-06-12. Inputs: repository-baseline.md + per-candidate evidence.md.

## Stage 2 — Knockout gates

### asm — KNOCKED OUT → DEFER (does not proceed to installation)

Failed gates (loop §6 / Stage 0 rule):

1. **No measurable repository-specific benefit / NO_JUSTIFIED_USE_CASE**
   (Stage 0): zero skill files exist across every provider dir — there is no
   inventory, duplication, or audit surface to manage.
2. **Platform**: no Windows handling in source (no win32 branch, no APPDATA,
   bash installer); primary host is Windows. "Minimum infrastructure
   unavailable" in practice.
3. Supply-chain posture (supporting, not primary): "signed manifests" claim is
   false; single-maintainer registry with regex-only gating would become a
   trusted code source into agent skill dirs — exactly the surface our
   skill_updates L2 cap exists to control.

**Re-evaluation conditions** (Mirage-style): we accumulate ≥5 real skill
files across ≥2 providers AND asm ships verified Windows support (or we've
migrated to Linux) AND manifests gain real signing or the registry gains
genuine curation. Until then: manage skills as ordinary gated worktree edits.

### semble — PASSES all knockout gates

MIT · pinnable (`semble==0.3.4`) · no API keys · no provider routing · CPU ·
isolated cache (`%LOCALAPPDATA%\semble\Cache\`) · removable · Windows CI.
Two recorded caveats, both mitigated: first-run HF model download (one-time,
registry-equivalent, recorded); `semble install` agent-config modification is
opt-in and **excluded** from this experiment (CLI only).

### abtop — PASSES all knockout gates

MIT · pinnable (v0.4.8 release binary) · no API keys · local-files-only data
flow · read-only by default · removable (delete binary). One caveat,
mitigated: `--setup` modifies `~/.claude/settings.json` with no teardown —
**excluded** from this experiment.

## Stage 3 — Architecture fit (0–5; survivors only)

| Dimension | semble | abtop |
| --- | --- | --- |
| problem_relevance | 4 | 3 |
| expected_measurable_benefit | 4 | 3 |
| integration_fit (seam) | 5 (optional retrieval path; stdio MCP) | 5 (read-only observer) |
| authority_boundary_fit | 5 (no authority) | 5 (no authority) |
| security_fit | 4 (local; model download caveat) | 4 (local; --setup caveat) |
| privacy_fit | 5 (code never leaves machine) | 5 |
| license_fit | 5 (MIT) | 5 (MIT) |
| platform_fit | 4 (Windows CI-tested) | 4 (native Windows, some detection issues reported) |
| operational_simplicity | 4 | 5 (single binary) |
| maintainability | 3 (2-person, 2-month-old) | 3 (1-dominant-author, 2.5-month-old) |
| observability | 3 | 4 (--json) |
| reversibility | 5 | 5 |
| testability | 5 (gold set ready) | 4 (live sessions available) |
| evidence_quality | 4 (upstream benchmarks/ dir) | 3 |
| cost_efficiency | 5 ($0) | 5 ($0) |
| latency_impact | 4 (claims unverified) | 5 (out-of-band) |

Penalties (0 = none, higher = worse):

| Penalty | semble | abtop |
| --- | --- | --- |
| duplication_penalty | 1 (overlaps ripgrep/native search — but optional) | 1 (overlaps usage_digest — but live vs retrospective) |
| new_authority_penalty | 0 | 0 |
| secret_expansion_penalty | 0 | 0 |
| vendor_lock_in_penalty | 0 | 0 |
| maintenance_penalty | 2 (young project; index freshness to manage) | 1 (single binary) |

Intended seam (exactly one each): semble → **repository retrieval**;
abtop → **observability**. Neither touches a control-plane boundary.
