# Continuous upgrade capability register

This register follows the state machine in the continuous capability prompt.
Each capability has exactly one current state. This file records state; detailed
evidence stays in candidate-specific artifacts.

## State table

| Capability | Current state | Evidence | Blocker / next transition |
| --- | --- | --- | --- |
| Config-derived Judge Gate routing | `INDEPENDENT_VERIFICATION_PASSED` | `BASELINE.md`, `baseline.json`, `mission-1-config-derived-judge-routing/GAP.md`, `EXPERIMENT.md`, `THREAT_PRIVACY_AUTHORITY.md`, `ROLLBACK.md`, `RESULTS.md`, `VERIFIER_REPORT.md` | Human promotion not requested; Mission 2 may start next. |
| Typed Ledger routing artifacts | `DISCOVERED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Wait for Mission 1; artifact schema must cite real route config hashes. |
| Route failure taxonomy and deterministic attribution | `DISCOVERED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Wait for Mission 1 and Mission 2; taxonomy must be schema/config validated. |
| codebase-memory-mcp read-only benchmark | `RESEARCH_VERIFIED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Wait until native routing artifacts are underway; no auto config/MCP/hooks. |
| abtop observability validation | `PILOT_APPROVED` | `evaluation/capability-assessment/DECISION.md`, `evaluation/capability-assessment/abtop/` | Keep opt-in; re-test Codex detection on a newer release or Linux migration. |
| Git/Markdown knowledge projection | `DISCOVERED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Needs recurring-query gold set and approved/proposed knowledge states. |
| Semble integration | `DEFERRED` | `evaluation/capability-assessment/DECISION.md`, `evaluation/capability-assessment/semble/` | Re-enter only after reproducible install/pinning and Windows path blockers are solved. |
| ASM / agent-skill-manager | `DEFERRED` | `evaluation/capability-assessment/asm/PARKED.md` | Re-enter only after real multi-provider skill inventory exists and provenance behavior is verified. |
| Puppetmaster runtime | `REJECTED` | `docs/MASTER.md` Section 5.1, `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Pattern-only unless native artifacts prove a gap that a one-mission adapter can test. |
| ClawCodex runtime | `REJECTED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | UI/status/journaling reference only. |
| Agno AgentOS | `REJECTED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | GitWiki pattern only; no second control plane. |
| SIA in production | `REJECTED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Offline/toy benchmark only; no evaluator mutation or self-promotion. |
| MAPPA distributed training | `REJECTED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Attribution pattern only. |
| Docker Model Runner backend | `DEFERRED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Re-enter only after measured Ollama throughput/context/reproducibility bottleneck. |
| dbt Agent Skills | `DEFERRED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Run only in a repo with dbt and `dbt parse/compile/test` validation. |
| dbt Wizard CLI in command center | `REJECTED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Provider credentials and second runtime conflict with this repo. |
| A2UI | `DEFERRED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Presentation only; re-enter when first-party UI has a declared rendering gap. |
| BigQuery trace/graph store | `DEFERRED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Re-enter only if Ledger/SQLite trace queries are insufficient at real scale. |
| BigSet | `REJECTED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Not routing/performance relevant; external provider/license concerns. |
| agentcookie | `REJECTED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Violates secret-free/browser-credential boundary. |
| OpenClaw | `REJECTED` | `docs/routing-performance-candidate-evaluation-2026-06-14.md` | Competing control plane. |

## Mission order

1. Mission 1: config-derived Judge Gate routing.
2. Mission 2: typed Ledger routing artifacts.
3. Mission 3: route failure taxonomy and deterministic attribution.
4. Mission 4: codebase-memory-mcp benchmark.
5. Mission 5: abtop observability validation.
6. Mission 6: Git/Markdown knowledge projection benchmark.
7. Mission 7: conditional improvements only when their triggers are true.

No mission advances until the preceding mission has evidence, validation,
verification, rollback, and `docs/MASTER.md` updates.
