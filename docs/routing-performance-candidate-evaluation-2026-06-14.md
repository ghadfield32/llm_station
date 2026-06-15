# Routing and performance candidate evaluation - 2026-06-14

This is the read-only evaluation pass for the broad AI-agent idea batch in
[agent-ideas-evaluation-prompt.md](agent-ideas-evaluation-prompt.md), focused
only on whether a candidate can improve model routing, execution performance,
retrieval performance, observability, or self-improvement quality without
breaking [MASTER.md](MASTER.md).

No candidate was installed, configured, registered as MCP, given credentials,
scheduled, or run as a daemon during this review.

## Evidence labels

- `LOCAL_FACT`: verified from this repository's code, config, docs, or prior
  measured evaluation artifacts.
- `LOCALLY_REPRODUCED_PRIOR`: measured previously under
  `evaluation/capability-assessment/`.
- `VERIFIED_UPSTREAM_FACT`: verified from the upstream source on 2026-06-14.
- `UPSTREAM_CLAIM_NOT_REPRODUCED`: upstream claim not reproduced here.
- `INFERENCE`: architecture judgement derived from local facts plus upstream
  facts.
- `UNKNOWN`: not established in this pass.

## Executive verdict

The best routing/performance improvement is not to add a new router. The first
fix is internal: make Judge Gate's risk-to-role route data-derived from
validated config, then add Ledger route-decision artifacts and failure classes.
Puppetmaster is useful as the reference pattern for that artifact shape, but not
as a runtime dependency.

For performance, the strongest new pilot candidate is `codebase-memory-mcp`,
because it targets structural code intelligence, impact analysis, and
cross-repo graph questions that `rg` and Semble do not cover well. It must be
tested as a binary-only, no-auto-config, no-hooks retrieval tool first.

The next most useful already-measured item is `abtop`, but it improves operator
visibility, not routing. Semble remains optional for semantic snippet retrieval,
but prior local results did not reproduce a clear token reduction and it has
Windows/symlink/pinning blockers on the large repo.

Everything that wants to become a second control plane - ClawCodex, Agno
AgentOS, ADK, OpenClaw, Puppetmaster runtime, generic multi-agent frameworks,
and dbt Wizard as a coding runtime - should not become core. The useful parts
are patterns: typed routing artifacts, branch-reviewed generated knowledge,
per-event attribution, domain skills, declarative UI, and local model-server
benchmarks.

## Local baseline

`LOCAL_FACT`: `MASTER.md` defines the current system as: `configs/*.yaml` plus
Pydantic contracts as source of truth; LiteLLM as the single local-only model
gateway; Ollama as the model runtime; Claude Code as primary executor; Codex as
fallback/verifier; Judge Gate, Ledger, Growth OS/AppFlowy, GitHub wall, and
one worktree/branch/devcontainer/lease per mission.

`LOCAL_FACT`: `configs/models.yaml` keeps LiteLLM roles on `provider: ollama`
and `local: true`. Provider API keys are forbidden by validation.

`LOCAL_FACT`: `configs/judges.yaml` keeps judge budgets at `max_cost_usd: 0.0`
and role aliases local.

`LOCAL_FACT`: `configs/improvement-targets.yaml` already has a `routing` target
with `routing_accuracy`, `unsafe_downgrades`, and `routing_regret`.

`LOCAL_FACT`: `services/judge_gate/app.py` still contains an inline `ROUTE`
table mapping risk tiers to aliases. That is a local hardcoded routing seam:
it is auditable, but it is not data-derived from `configs/gates.yaml`,
`configs/judges.yaml`, and `configs/models.yaml`.

`LOCAL_FACT`: prior Batch 1 evaluation already measured Semble, abtop, and asm
under `evaluation/capability-assessment/DECISION.md`.

## Ranked safe opportunities

| Rank | Opportunity | Decision | Why |
| --- | --- | --- | --- |
| 1 | Data-derived Judge Gate routing | `ADOPT_INTERNAL` | Fixes the real local hardcoded routing seam without adding a control plane. |
| 2 | Ledger routing artifacts + failure taxonomy | `ADOPT_INTERNAL`, borrow from Puppetmaster | Enables data-derived routing learning and postmortems without using a third-party router. |
| 3 | `codebase-memory-mcp` read-only retrieval benchmark | `PILOT_PLAN` | Potentially improves structural code retrieval, impact analysis, and token use; must avoid auto-install/hooks. |
| 4 | abtop read-only live session telemetry | `PILOT_ALREADY` | Already measured safe for Claude on Windows; helps performance visibility, not routing. |
| 5 | MAPPA-style per-event attribution | `EXTRACT_PATTERN` | Could improve stuck routing and retry decisions; deterministic attribution first, no RL stack. |
| 6 | Agno/GitWiki-style branch-reviewed knowledge | `EXTRACT_PATTERN` | Can improve reuse and reduce re-analysis if repo/AppFlowy authority remains clear. |
| 7 | Docker Model Runner backend benchmark | `DEFER_TO_BENCHMARK` | Potential backend behind LiteLLM only; no second gateway. |

## One-by-one evaluation

### 1. Puppetmaster

Sources: [GitHub README](https://github.com/professorpalmer/Puppetmaster/blob/main/README.md),
[PyPI](https://pypi.org/project/puppetmaster-ai/),
[pyproject](https://github.com/professorpalmer/Puppetmaster/blob/main/pyproject.toml).

`VERIFIED_UPSTREAM_FACT`: Published as `puppetmaster-ai` 0.9.47 on PyPI,
released 2026-06-14; Python >=3.9; MIT; development status Alpha.

`VERIFIED_UPSTREAM_FACT`: Upstream positions it as a supervisor that routes
Cursor, Claude Code, OpenAI API, or Codex CLI work to the cheapest model,
spawns independent workers, and stores typed SQLite artifacts.

`VERIFIED_UPSTREAM_FACT`: `puppetmaster setup` installs MCP registrations,
rules, auto-invocation hooks, and model registry state; uninstall removes
Puppetmaster-owned integrations but leaves state unless purged.

`UPSTREAM_CLAIM_NOT_REPRODUCED`: Claims include cheaper routing, faster runs,
zero-token follow-ups, and self-healing provider reroutes. None were reproduced
in this pass.

Routing/performance fit:

- `INFERENCE`: Strong pattern fit for route-decision artifacts, rejected-route
  reasons, typed worker artifacts, and failure classification.
- `INFERENCE`: Poor runtime fit. It duplicates LiteLLM, Judge Gate, Ledger,
  leases, model registry, and executor routing.
- `INFERENCE`: Its provider/API cost router conflicts with this repo's
  local-only/no-provider-key rule.

Decision: `EXTRACT_PATTERN`, not runtime adoption.

Smallest safe next step: implement native Ledger route artifacts after Judge
Gate routing is made config-derived. Do not install Puppetmaster unless a later
one-mission adapter experiment proves a gap after native artifacts exist.

### 2. codebase-memory-mcp

Sources: [GitHub README](https://github.com/DeusData/codebase-memory-mcp),
[project site](https://deusdata.github.io/codebase-memory-mcp/).

`VERIFIED_UPSTREAM_FACT`: MIT project; latest release shown upstream as v0.8.1
on 2026-06-12; single static binary; macOS, Linux, and Windows binaries; no API
keys; 158 tree-sitter grammars; 14 MCP tools; optional graph UI at
`localhost:9749`.

`VERIFIED_UPSTREAM_FACT`: Upstream says it auto-detects Claude Code, Codex CLI,
Gemini CLI, Zed, OpenCode, Antigravity, Aider, KiloCode, VS Code, OpenClaw,
and Kiro and configures MCP entries, instruction files, skills, and pre-tool
hooks. It also has `--skip-config`, uninstall, checksums, signatures, SLSA, and
VirusTotal claims.

`UPSTREAM_CLAIM_NOT_REPRODUCED`: 10x to 120x token reduction, sub-ms structural
queries, Linux-kernel indexing time, and answer-quality claims were not
reproduced here.

Routing/performance fit:

- `INFERENCE`: Best candidate for structural retrieval performance, especially
  questions like "what routes call this?", "what breaks if this changes?",
  "which symbols are affected by this diff?", and cross-repo architecture.
- `INFERENCE`: It should not be allowed to auto-write agent config, hooks, or
  instruction files during an evaluation. Use binary-only/manual mode first.
- `INFERENCE`: It could outperform Semble for graph and impact analysis;
  Semble remains better-shaped for lightweight natural-language snippet search.

Decision: `PILOT_PLAN`.

Smallest safe next step:

1. Download a pinned Windows binary into an evaluation directory only.
2. Verify checksum/signature manually.
3. Run with `--skip-config` or equivalent binary-only setup; no global MCP
   registration, hooks, instructions, or auto-index.
4. Build a gold set against `rg`, Semble, and current native search:
   structural recall@K, precision@K, latency, index size, stale-index behavior,
   secret exclusion, generated-file handling, and Windows symlink behavior.
5. If it wins, expose it only through a first-party wrapper controlled by
   `configs/tools.yaml`, not through uncontrolled auto-install.

### 3. Semble

Sources: [GitHub README](https://github.com/MinishLab/semble),
local evidence under `evaluation/capability-assessment/semble/`.

`VERIFIED_UPSTREAM_FACT`: Semble is CPU-only, local, no API keys, and claims
fast agent-oriented code search with large token reductions.

`LOCALLY_REPRODUCED_PRIOR`: Small repo recall@5 was 7/10. On the large
`betts_basketball` repo, recall@5 was 6/8 only after excluding a broken
Windows symlink/reparse path; out-of-the-box indexing crashed. `.env` did not
surface. A clear token reduction versus skilled `rg` was not reproduced.

Routing/performance fit:

- `INFERENCE`: Useful optional semantic retrieval path, especially for natural
  language query terms that are hard to guess.
- `INFERENCE`: Not a routing improvement. It can reduce search thrash on some
  tasks but cannot decide model role/executor.
- `INFERENCE`: It should not be layered ahead of `rg` by default until the
  symlink, pinning, and latency blockers are solved.

Decision: `PILOT_BLOCKED_ON_LARGE_REPO`.

Smallest safe next step: no MCP registration. First create committed ignore
rules for problematic reparse/data paths in target repos and pin the package in
a reproducible tool environment.

### 4. abtop

Sources: [GitHub README](https://github.com/graykode/abtop/blob/main/README.md),
[GitHub releases](https://github.com/graykode/abtop/releases),
local evidence under `evaluation/capability-assessment/abtop/`.

`VERIFIED_UPSTREAM_FACT`: Latest release remains v0.4.8 from 2026-06-08.
Upstream supports Claude Code, Codex CLI, and OpenCode session discovery, token
tracking, context windows, status, ports, and child processes; README describes
it as read-only with no API keys.

`LOCALLY_REPRODUCED_PRIOR`: On Windows, it detected 7/7 Claude sessions but
0/4 Codex sessions. Read-only behavior and JSON output were verified.

Routing/performance fit:

- `INFERENCE`: Helps operator performance by exposing active sessions,
  context, ports, and rate limits.
- `INFERENCE`: Does not improve model routing directly. It can provide
  evidence for future stuck-session or orphan-port routing decisions.

Decision: `PILOT_ALREADY`, keep opt-in.

Smallest safe next step: re-test Codex detection only when a newer release
exists or after Linux migration. Keep `--setup` prohibited.

### 5. ASM / agent-skill-manager

Sources: local evidence under `evaluation/capability-assessment/asm/`.

`LOCALLY_REPRODUCED_PRIOR`: This repo had no current skill inventory to manage
at the time of the prior evaluation. Windows support was not verified, and the
"signed manifests" claim did not hold under inspection.

Routing/performance fit:

- `INFERENCE`: No routing impact today.
- `INFERENCE`: Could become useful later for skill inventory/audit if this
  repo grows real skills across multiple providers.

Decision: `DEFER`.

Re-evaluate only when there are at least five real skills across at least two
providers, Windows support is verified or the system has migrated to Linux, and
manifest signing/provenance is real.

### 6. ClawCodex

Source: [GitHub README](https://github.com/agentforce314/clawcodex).

`VERIFIED_UPSTREAM_FACT`: MIT, Python 3.10+, described as a production-oriented
Python rebuild of Claude Code and a Claude Code-style terminal workflow with
streaming replies, tool calls, context, and skills.

`VERIFIED_UPSTREAM_FACT`: Upstream security section says API keys are
obfuscated in config and `.env` files are ignored.

Routing/performance fit:

- `INFERENCE`: As a runtime, it duplicates Claude Code, Codex, LiteLLM routing,
  worktree execution, tool permissions, skills, and session handling.
- `INFERENCE`: It would likely expand provider-key/config surface and create a
  third executor path.
- `INFERENCE`: It may contain UI/status/journaling ideas worth reading, but not
  a reason to replace the current executor boundary.

Decision: `REJECT_CORE`, `REFERENCE_ONLY`.

Smallest safe next step: if UI/window polish is desired, compare screenshots
and status-line concepts against the first-party Agent Kanban UI. Do not run it
as an executor.

### 7. Agno / AgentOS / GitWiki pattern

Source: [Agno GitHub README](https://github.com/agno-agi/agno).

`VERIFIED_UPSTREAM_FACT`: Agno is an SDK for building agent platforms; upstream
highlights production services, tracing, scheduling, RBAC, a single control
plane, memory, permissions, human-review loops, and UI.

Routing/performance fit:

- `INFERENCE`: As a platform/control plane it overlaps with Ledger, Judge
  Gate, LiteLLM, Growth OS/AppFlowy, channels, memory, permissions, and
  scheduling.
- `INFERENCE`: The useful idea is not AgentOS adoption. It is branch-reviewed,
  Git-backed generated knowledge with citations and retrieval.
- `INFERENCE`: Git history alone is not learning. Learning requires approved
  artifacts, provenance, retrieval, evaluation, and demonstrated reduced
  re-analysis or higher task success.

Decision: `EXTRACT_PATTERN`.

Smallest safe next step: add a native "knowledge projection benchmark" for
approved Markdown/OKF/ADR pages versus current AppFlowy/Ledger memory, with
secret scanning and PR review. No auto-commit-push.

### 8. SIA / Self-Improving AI

Source: [hexo-ai/sia GitHub](https://github.com/hexo-ai/sia).

`VERIFIED_UPSTREAM_FACT`: MIT project; official implementation of "SIA: Self
Improving AI with Harness & Weight Updates"; described as a loop where a
language-model agent updates both the harness and the weights of a
task-specific agent.

`UPSTREAM_CLAIM_NOT_REPRODUCED`: Upstream reports large gains on benchmark
tasks. None were reproduced here.

Routing/performance fit:

- `INFERENCE`: The concept overlaps with this repo's coded improvement loop,
  but SIA's harness and weight updates are too powerful for production here.
- `INFERENCE`: The safe extract is generation-artifact discipline: freeze
  train/dev/held-out splits, produce candidate patches, and independently
  verify them.
- `INFERENCE`: It must not mutate the evaluator, weaken tests, see sealed
  evals, self-promote, rotate secrets, or update model weights in production.

Decision: `OFFLINE_RESEARCH_ONLY`, `EXTRACT_PATTERN`.

Smallest safe next step: no runtime integration. If researched, run on a toy
offline benchmark with synthetic data and zero credentials, producing candidate
patches only.

### 9. MAPPA / multiagent-coaching

Sources: [GitHub README](https://github.com/ltjed/multiagent-coaching),
[project page](https://ltjed.github.io/MAPPA/).

`VERIFIED_UPSTREAM_FACT`: MIT project for fine-tuning multi-agent systems with
per-action process rewards. Setup includes Python 3.11, `uv`, and SandboxFusion
with a separate conda/poetry environment.

`UPSTREAM_CLAIM_NOT_REPRODUCED`: Per-action reward improvements were not
reproduced here.

Routing/performance fit:

- `INFERENCE`: The full RL/fine-tuning stack is not appropriate for this repo's
  local routing path.
- `INFERENCE`: The per-action attribution idea is highly relevant. Ledger
  events can label where a mission went wrong: bad route, missing retrieval,
  model truncation, tool parser failure, stale index, unsafe downgrade, or bad
  executor choice.
- `INFERENCE`: Deterministic event attribution should be tried before any LLM
  coach or RL training.

Decision: `EXTRACT_PATTERN`.

Smallest safe next step: add post-run attribution fields to Ledger events after
route artifacts exist, then evaluate whether attribution improves stuck
escalation and retry choices.

### 10. Generic multi-agent frameworks

Sources: represented by Agno, Google ADK, Puppetmaster, MAPPA, and dbt Wizard
sources in this document.

Routing/performance fit:

- `INFERENCE`: A framework only helps when tasks genuinely benefit from
  parallel hypotheses or independent verification.
- `INFERENCE`: This repo already has the safer version: one strong executor,
  independent judges/verifier, leases, Ledger events, and human promotion.
- `INFERENCE`: Framework adoption would create duplicate worker spawning,
  scheduling, memory, retries, approvals, and routing.

Decision: `REJECT_AS_CORE`, `BORROW_PATTERNS_ONLY`.

Smallest safe next step: only run a benchmark when a task type is explicitly
parallel, such as multi-hypothesis root cause analysis. Compare against the
baseline "one executor plus independent reviewer" under the existing loop.

### 11. dbt Wizard CLI and dbt Agent Skills

Sources: [dbt Wizard quickstart](https://docs.getdbt.com/docs/dbt-ai/wizard-quickstart),
[dbt Wizard skills docs](https://docs.getdbt.com/docs/dbt-ai/wizard-skills),
[dbt-agent-skills GitHub](https://github.com/dbt-labs/dbt-agent-skills).

`VERIFIED_UPSTREAM_FACT`: dbt Wizard CLI is beta, installed by shell/PowerShell
scripts, supports OpenAI subscription or BYOK plus multiple provider keys, and
stores provider credentials under `~/.dbt/wizard/provider-auth.json`.

`VERIFIED_UPSTREAM_FACT`: dbt Wizard works with a built dbt project, uses dbt
project metadata, can propose diffs, can review uncommitted changes, can manage
MCPs, and can use subagents. dbt Agent Skills are Apache-2.0 and maintained by
dbt Labs.

Routing/performance fit:

- `INFERENCE`: dbt Wizard runtime is not a fit for `llm_station`; it requires
  provider credentials and is a second coding runtime.
- `INFERENCE`: dbt Agent Skills are a good conditional fit for repos that
  actually contain dbt. They can improve domain accuracy and reduce failed
  analytics-engineering loops.
- `INFERENCE`: No current route/performance benefit for command-center routing.

Decision: `DEFER_FOR_THIS_REPO`, `PILOT_SKILLS_IN_DBT_REPOS_ONLY`.

Smallest safe next step: for a dbt repo, import only relevant dbt skills as
reviewed files on a branch and measure trigger precision plus `dbt parse`,
`dbt compile`, and `dbt test` results. Do not use dbt Wizard CLI unless a
separate human-approved provider-key evaluation exists.

### 12. OpenClaw plus Docker Model Runner / Rami local assistant pattern

Sources: [OpenClaw GitHub](https://github.com/openclaw/openclaw),
[Docker Model Runner docs](https://docs.docker.com/ai/model-runner/),
[Docker Model Runner API docs](https://docs.docker.com/ai/model-runner/api-reference/).

`VERIFIED_UPSTREAM_FACT`: OpenClaw is a personal AI assistant control plane
that answers on channels and has its own Gateway. Docker Model Runner stores
models locally and exposes OpenAI- and Ollama-compatible APIs; it supports
llama.cpp, vLLM, and Diffusers, with vLLM requiring NVIDIA GPUs on Linux x86_64
or Windows with WSL2.

Routing/performance fit:

- `INFERENCE`: OpenClaw duplicates Growth OS channels, Gateway, action layer,
  memory, skills, and control plane. It should not be adopted.
- `INFERENCE`: Docker Model Runner is not a control plane if used only as a
  backend behind LiteLLM. It might improve reproducibility, containerized local
  serving, or future vLLM throughput after Linux/WSL2 benchmarking.
- `INFERENCE`: It must not become a second model gateway next to LiteLLM.

Decision: `REJECT_OPENCLAW_CORE`, `DEFER_DMR_BACKEND_BENCHMARK`.

Smallest safe next step: when local model throughput is a proven bottleneck,
benchmark Ollama versus Docker Model Runner through LiteLLM using the same
model, context size, concurrency, GPU, and prompt set.

### 13. Google ADK

Sources: [ADK official site](https://adk.dev/),
[Google ADK Python GitHub](https://github.com/google/adk-python).

`VERIFIED_UPSTREAM_FACT`: ADK is an open-source framework for building,
debugging, and deploying agents at enterprise scale across Python, TypeScript,
Go, Java, and Kotlin.

Routing/performance fit:

- `INFERENCE`: As a framework, ADK overlaps with this repo's control plane,
  tools, scheduling, multi-agent patterns, deployment path, and observability.
- `INFERENCE`: It is useful as reference material for agent-testing and
  tracing patterns, not as a replacement for Ledger/Judge Gate/LiteLLM.

Decision: `REFERENCE_ONLY`.

Smallest safe next step: borrow test/tracing ideas only if they can be
implemented natively in the improvement loop.

### 14. BigQuery Agent Analytics / Agent Context Graph

Sources: [BigQuery Agent Analytics SDK GitHub](https://github.com/GoogleCloudPlatform/BigQuery-Agent-Analytics-SDK),
[ADK BigQuery Agent Analytics docs](https://adk.dev/integrations/bigquery-agent-analytics/).

`VERIFIED_UPSTREAM_FACT`: The SDK analyzes, evaluates, and curates agent traces
stored in BigQuery and exposes Agent Context Graph capabilities at scale.

Routing/performance fit:

- `INFERENCE`: No current BigQuery data gravity exists in this repo's routing
  path. The authoritative trace store is Ledger/SQLite.
- `INFERENCE`: The idea of querying agent traces is relevant, but BigQuery is
  too heavy and would create a second data store.

Decision: `DEFER`, `BORROW_QUERY_PATTERNS_ONLY`.

Smallest safe next step: first add route artifacts to Ledger. If SQLite queries
become insufficient at real scale, re-evaluate BigQuery with a migration
decision.

### 15. A2UI

Sources: [A2UI site](https://a2ui.org/),
[Google announcement](https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/).

`VERIFIED_UPSTREAM_FACT`: A2UI is Apache-2.0, created by Google with community
contributions, and is a declarative protocol for agents to send rich UI
descriptions across trust boundaries without sending executable code.

Routing/performance fit:

- `INFERENCE`: No direct model-routing impact.
- `INFERENCE`: It could improve operator performance in the Agent Kanban UI by
  rendering route artifacts, experiment results, and verifier reports as
  declarative panels.
- `INFERENCE`: It must remain a presentation layer. It cannot own missions,
  approvals, memory, routing, or policy.

Decision: `OPTIONAL_UI_PATTERN`.

Smallest safe next step: no dependency. Revisit when the first-party UI needs a
structured way to render agent-proposed forms or route evidence.

### 16. BigSet

Source: [BigSet GitHub](https://github.com/tinyfish-io/bigset).

`VERIFIED_UPSTREAM_FACT`: BigSet builds structured datasets from natural
language by sending agents to research the live web, verify, deduplicate, and
export CSV/XLSX. GitHub metadata shows AGPL-3.0.

`UPSTREAM_CLAIM_NOT_REPRODUCED`: Dataset quality, freshness, and verification
claims were not reproduced.

Routing/performance fit:

- `INFERENCE`: No routing benefit for this system.
- `INFERENCE`: AGPL-3.0 and likely external agent/API dependencies conflict
  with this repo's license and no-provider-key constraints for core adoption.
- `INFERENCE`: If used at all, it belongs outside this control plane as a
  synthetic/public-data research experiment.

Decision: `REJECT_CORE`, `DEFER_EXTERNAL_RESEARCH_ONLY`.

Smallest safe next step: none for routing/performance.

### 17. agentcookie

Sources: [agentcookie GitHub](https://github.com/mvanhorn/agentcookie),
[protocol docs](https://github.com/mvanhorn/agentcookie/blob/main/docs/protocol.md).

`VERIFIED_UPSTREAM_FACT`: MIT, macOS peer-to-peer over Tailscale; synchronizes
Chrome cookies and a secrets bus to a second Mac; includes plaintext sidecar
cookies and per-CLI secret files; protocol decrypts and validates envelopes.

Routing/performance fit:

- `INFERENCE`: It directly violates this repo's secret-free worktree and
  no-browser-credential replication boundary.
- `INFERENCE`: It may improve convenience for browser-driven agents, but it
  worsens blast radius and does not improve model routing.

Decision: `REJECT`.

Smallest safe next step: none. Prefer scoped OAuth, service accounts, and
short-lived per-tool credentials.

### 18. Git/Markdown knowledge and history learning

Sources: local [knowledge-format.md](knowledge-format.md), [MASTER.md](MASTER.md),
Agno source above.

`LOCAL_FACT`: This repo already has an OKF knowledge producer and Git-backed
docs. Growth OS/AppFlowy is the human work surface; Ledger is mission truth.

Routing/performance fit:

- `INFERENCE`: Git-backed knowledge can improve performance by avoiding repeat
  analysis and giving agents approved facts with citations.
- `INFERENCE`: Git history alone is not learning. It becomes learning only when
  a retriever can use approved artifacts, cite provenance, avoid stale facts,
  and demonstrate better task outcomes.
- `INFERENCE`: Auto-commit/generated wiki truth would create a second source of
  truth. Branch-reviewed proposals fit the system.

Decision: `EXTRACT_PATTERN_NATIVE`.

Smallest safe next step: add a benchmark for "approved knowledge projection":
current memory/AppFlowy/OKF versus branch-reviewed ADR/Markdown pages on a set
of recurring architecture questions.

### 19. Independent verifier / outcome-loop pattern

Sources: local [improvement-loop.md](improvement-loop.md),
[independent-verification.md](independent-verification.md), and existing
`configs/improvement-targets.yaml`.

`LOCAL_FACT`: This pattern is already implemented conceptually in the coded
improvement loop: independent verification, sealed eval rules, human
promotion, canary, rollback, and target-specific metrics.

Routing/performance fit:

- `INFERENCE`: Highest-value native pattern for routing. Every route change
  should be an improvement experiment, not an unmeasured prompt tweak.
- `INFERENCE`: Add per-mission acceptance rubrics and route artifacts before
  training/tuning anything.

Decision: `ADOPT_NATIVE_ALREADY`, extend with route artifacts.

Smallest safe next step: tie Judge Gate route decisions to Ledger artifacts and
the `EXP-routing-ref` lifecycle.

### 20. Hermes/WebUI-style ideas

Sources: local `evaluation/capability-assessment/hermes/DECISION.md`.

`LOCALLY_REPRODUCED_PRIOR`: Hermes was evaluated and deferred: memory worked
as local `MEMORY.md`, but headline self-improving skills did not materialize
enough to justify adoption.

Routing/performance fit:

- `INFERENCE`: No routing improvement over LiteLLM/Ollama/action layer.
- `INFERENCE`: UI and memory concepts remain reference material only.

Decision: `DEFER`.

Smallest safe next step: none for routing.

## Control-plane overlap summary

| Candidate | Model gateway | Routing | Ledger/state | Scheduler | Memory/knowledge | UI | Secret risk | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Puppetmaster | duplicates | duplicates | duplicates | partial | duplicates | optional | provider/API hooks | extract artifacts only |
| codebase-memory-mcp | none | none | separate graph DB | watcher optional | ADR/graph overlap | optional port | code/index exposure | pilot as manual retrieval |
| Semble | none | none | cache only | none | retrieval overlap | none | index exposure | blocked pilot |
| abtop | none | none | none | none | none | terminal | reads local session files | opt-in pilot |
| ClawCodex | likely duplicates | duplicates executor choice | duplicates session state | possible | skills overlap | terminal | provider keys/config | reject core |
| Agno | can integrate, but broad | can own | duplicates control plane | duplicates | duplicates | strong | depends on deployment | extract GitWiki pattern |
| SIA | no direct | mutates candidates | can mutate harness | possible | learning overlap | none | eval leakage | offline only |
| MAPPA | no direct | indirect | training artifacts | training loop | none | none | low if offline | extract attribution |
| dbt Wizard | provider-bound | domain runtime | session state | subagents | dbt metadata | terminal | provider creds | dbt repos only |
| OpenClaw | can own gateway | can own | own gateway state | own assistant | duplicates | Canvas/channels | skills/browser/actions | reject core |
| Docker Model Runner | backend only | no | none | none | none | Docker UI | model pulls | benchmark behind LiteLLM |
| ADK | can own | can own | duplicates | duplicates | duplicates | dev UI | provider/cloud possible | reference only |
| BigQuery Analytics | no | analytics only | second trace store | none | trace graph | dashboards | cloud data | defer |
| A2UI | no | no | no | no | no | presentation | low | optional UI pattern |
| BigSet | no | no | external datasets | scheduled refresh | data source | web UI | external keys/web | reject core |
| agentcookie | no | no | auth state | sync daemon | secrets bus | none | very high | reject |
| Git/Markdown | no | no | Git docs only | no | approved knowledge | docs | secret-in-doc risk | native pattern |
| Verifier loops | no | improves route eval | Ledger-native | no | eval artifacts | reports | eval leakage if mishandled | native |

## Ordered work left

1. Replace `services/judge_gate/app.py` inline `ROUTE` with validated,
   config-derived routing. Source configs: `configs/gates.yaml`,
   `configs/judges.yaml`, `configs/models.yaml`. Missing aliases must fail
   validation/startup. No inline defaults, fake costs, or silent fallback.
2. Add a typed Ledger route-decision artifact: mission id, risk tier, selected
   role/executor, candidate alternatives, rejection reasons, config hashes,
   usage fields when present, and `unknown` when absent.
3. Add explicit failure classes: model unavailable, missing model, OOM/context
   fit, truncated output, invalid JSON, tool parser failure, executor missing,
   timeout, auth/session failure, human approval required, stale index, and
   unsafe downgrade.
4. Feed those artifacts into the existing `routing` improvement target only
   after a benchmark plan exists. Metrics come from the experiment contract,
   not inline thresholds.
5. Run the `codebase-memory-mcp` read-only benchmark against `rg`, Semble, and
   native search. Do not register MCP or hooks before it wins.
6. Add deterministic post-run attribution inspired by MAPPA only after events
   and route artifacts exist.
7. Evaluate Git/Markdown knowledge projection against the existing OKF/AppFlowy
   memory only after recurring-query gold cases exist.
8. Benchmark Docker Model Runner behind LiteLLM only if Ollama throughput,
   context, or reproducibility becomes a measured bottleneck.
9. Keep all rejected/deferred control planes out of core unless a separate
   migration decision explicitly replaces the current architecture.

## Final decision table

| Candidate | Routing improvement | Performance improvement | Decision |
| --- | --- | --- | --- |
| Native Judge Gate route config | high | medium | `ADOPT_INTERNAL` |
| Native Ledger route artifacts | high | medium | `ADOPT_INTERNAL` |
| Puppetmaster | pattern high, runtime negative | pattern medium | `EXTRACT_PATTERN` |
| codebase-memory-mcp | none direct | potentially high retrieval/impact | `PILOT_PLAN` |
| Semble | none | moderate, currently blocked | `PILOT_BLOCKED` |
| abtop | indirect observability | medium operator visibility | `PILOT_ALREADY` |
| ASM | none | none now | `DEFER` |
| ClawCodex | negative as runtime | unknown UI reference | `REJECT_CORE` |
| Agno/GitWiki | negative as platform | medium knowledge pattern | `EXTRACT_PATTERN` |
| SIA | unsafe direct | offline research only | `OFFLINE_ONLY` |
| MAPPA | indirect | medium attribution pattern | `EXTRACT_PATTERN` |
| Generic multi-agent frameworks | usually negative | task-specific unknown | `BORROW_PATTERNS_ONLY` |
| dbt Wizard CLI | none here | dbt-only possible | `DEFER_HERE` |
| dbt Agent Skills | none here | dbt-only possible | `PILOT_IN_DBT_REPOS` |
| OpenClaw | negative | duplicates channels/control | `REJECT_CORE` |
| Docker Model Runner | backend only | possible future throughput | `DEFER_BENCHMARK` |
| Google ADK | negative as platform | reference only | `REFERENCE_ONLY` |
| BigQuery Agent Analytics | none now | scale-only future | `DEFER` |
| A2UI | none | UI presentation only | `OPTIONAL_PATTERN` |
| BigSet | none | not relevant | `REJECT_CORE` |
| agentcookie | none | convenience with high risk | `REJECT` |
| Git/Markdown knowledge | indirect | possible reuse gains | `EXTRACT_NATIVE_PATTERN` |
| Independent verifier loops | high via eval quality | high via safer promotion | `ADOPT_NATIVE_ALREADY` |
