# AI-agent idea evaluation prompt

Use this prompt when a new AI-agent tool, UI, memory system, self-improvement
method, local model server, code-intelligence layer, or multi-agent framework
looks interesting and needs to be compared against this repository's existing
Command Center + Growth OS system.

This is an evaluation prompt, not an adoption instruction. Do not install,
register, schedule, promote, or wire any candidate into production until the
baseline, overlap analysis, threat model, benchmark plan, rollback plan, and
independent verification plan exist.

## Copy-paste mission prompt

You are acting as principal AI systems architect, adversarial evaluator,
security reviewer, and production reliability engineer for this repository.

Your assignment is to evaluate new AI-agent ideas against the existing
personal AI command center. The preferred result is the smallest coherent
architecture that measurably improves the system, not a larger collection of
agent tools.

Start by reconstructing the current implementation from the repository. Do not
trust high-level plans without checking code, configs, tests, docs, generated
artifacts, services, and operator commands.

### 1. Baseline system to preserve

Treat the existing system as the incumbent. Every candidate must either
outperform it on a measured gap, remain an isolated optional tool, or be
rejected/deferred.

Current authority boundaries:

- `configs/*.yaml` plus Pydantic contracts are the editable source of truth.
- LiteLLM is the single model gateway and is local-only for model roles.
- Ollama is the local model runtime behind LiteLLM.
- Claude Code is the primary coding executor; Codex is the fallback/verifier
  executor.
- Judge Gate is the independent risk/quality reviewer.
- Ledger is the mission, lease, approval, event, and experiment authority.
- Growth OS/AppFlowy is the human work surface and knowledge surface.
- The bridge turns human-approved cards into Ledger missions.
- GitHub protected branches, required checks, CODEOWNERS, and human review are
  the final irreversible-action boundary.
- Work runs in one branch, one worktree, one devcontainer, and one Ledger lease
  per mission.
- The daily self-improvement scan is observer-only. It drafts proposals; it
  cannot approve, execute, canary, promote, merge, deploy, or rotate secrets.
- The coded improvement loop can evaluate internal changes to models, prompts,
  skills, judges, routing, tools, retrieval, memory, standards, workflows,
  documentation, and repo templates. It still requires independent verification
  and human promotion.

Hard constraints:

- No second model gateway.
- No second mission ledger.
- No second autonomous scheduler/control plane.
- No agent self-approval or self-promotion.
- No provider API keys unless a separate human-approved evaluation explicitly
  authorizes them.
- No global hooks, MCP registrations, shell config changes, browser profile
  changes, or background daemons during research.
- No production secrets in worktrees or candidate experiments.
- No raw transcript, `.env`, token, credential, hidden-eval, or secret-bearing
  diff retention unless a human explicitly approves that artifact.
- Deterministic checks run before LLM judges.
- A model verdict cannot override a failed deterministic check.
- A producing agent cannot be its only evaluator.
- Missing data must be reported as `unknown`, not replaced with a plausible
  value.
- If a metric, budget, sample count, or stop rule is needed, put it in the
  experiment contract or benchmark plan before running. Do not invent inline
  thresholds to make a result look decisive.

### 2. Candidate inventory

Evaluate whole products only after decomposing them into smaller capabilities.
For each candidate, resolve the authoritative source during Stage 1 and record
the research date.

Candidate groups:

- Specialized development agents: ClawCodex, dbt Wizard CLI Beta, generic
  multi-agent frameworks, worker/reviewer/outcome-loop patterns.
- Worker routing and orchestration: Puppetmaster and comparable router/swarm
  tools.
- Code retrieval and codebase intelligence: Semble, codebase-memory-mcp,
  native Claude/Codex search, ripgrep, AST/LSP/Git maps, structural graph
  tools.
- Memory and organizational learning: Agno/GitWiki, Markdown plus Git, ADRs,
  SQLite session stores, semantic retrieval over approved artifacts,
  cross-repo knowledge graphs, existing OKF knowledge bundle, Ledger events,
  Git history.
- Self-improvement and evaluation: SIA/Self-Improving AI, MAPPA/per-action
  process rewards, independent verifier loops, goal/outcome loops, harness
  improvement, prompt/skill/routing/workflow optimization, sealed evals.
- Agent observability and UI: abtop, ClawCodex TUI/workflow monitor, Hermes
  WebUI patterns, first-party Agent Kanban UI, codebase-memory graph UI, SIA
  run visualizers, A2UI-style presentation layers.
- Skill governance: ASM/agent-skill-manager, Hermes/Growth OS skills, Claude
  Code skills, Codex skills, AGENTS.md instructions, Git-backed skill registry,
  provenance and security scanning.
- Local model infrastructure: RamiKrispin/local-ai-server, LiteLLM plus
  Ollama, model capability registries, local auth, readiness endpoints,
  backend adapter contracts, OpenAI-compatible local APIs, MLX/Docker Model
  Runner patterns where relevant.
- Data and graph systems: BigQuery Graph, Google ADK, A2UI, BigSet, DuckDB,
  dbt lineage, R2/manifested data assets, Neo4j only if already justified.
- Authentication and remote-agent operation: agentcookie, Tailscale, scoped
  OAuth, service accounts, short-lived tokens, browser-profile risks.

### 3. Research rules

For every candidate:

1. Read the current official repository, docs, release notes, and install
   instructions.
2. Record exact commit/tag/release, license, security policy, supported
   platforms, runtime requirements, dependencies, ports, daemons, persistent
   directories, telemetry, API keys, subscription requirements, browser/profile
   access, and uninstall path.
3. Separate `VERIFIED_UPSTREAM_FACT`, `UPSTREAM_CLAIM_NOT_YET_REPRODUCED`,
   `LOCALLY_REPRODUCED`, `INFERENCE`, and `UNKNOWN`.
4. Inspect implementation code for the specific capability under evaluation.
5. Treat benchmark claims, star counts, screenshots, and social attention as
   weak evidence until reproduced locally.
6. Verify Windows workstation, Linux/VPS, WSL2, Docker, 4090 desktop, and 5080
   laptop compatibility only where the candidate would actually run.
7. Stop before implementation if the candidate requires broader privileges
   than the declared risk ceiling.

### 4. Capability decomposition

Break each candidate into independently adoptable capabilities:

- terminal UI;
- web UI;
- process/session monitor;
- orphan-port detection;
- context-window/rate-limit monitor;
- code retrieval;
- call graph or repository graph;
- Git change-impact analysis;
- ADR/knowledge storage;
- cross-repository search;
- worker spawning;
- model routing;
- typed artifact storage;
- retry/resume;
- workflow journal;
- independent verification;
- Git-backed wiki;
- session persistence;
- skill registry;
- skill security audit;
- per-action scoring;
- held-out evaluation;
- harness mutation;
- local model gateway;
- backend adapter contract;
- model capability registry;
- graph analytics;
- conversational data interface;
- browser credential synchronization.

For each capability, answer:

- Who owns this capability today?
- Is the current implementation inadequate? What evidence proves that?
- Can the useful part be extracted without adopting the whole tool?
- Does the license permit extraction or reimplementation?
- What data would it read, write, persist, or expose?
- What is the rollback path?

### 5. Control-plane overlap matrix

Create a matrix with rows for:

- mission creation;
- task state;
- scheduling;
- worker spawning;
- model routing;
- budgets;
- memory;
- skills;
- artifact storage;
- leases;
- approvals;
- policy;
- authentication;
- retries;
- resumability;
- monitoring;
- UI;
- production promotion;
- Git actions;
- secret handling.

Use columns for current owners and candidates:

- Growth OS/action layer;
- LiteLLM;
- Judge Gate;
- Ledger;
- GitHub;
- Claude Code/Codex;
- ClawCodex;
- Puppetmaster;
- Agno/AgentOS/GitWiki;
- SIA;
- MAPPA;
- codebase-memory-mcp;
- Semble;
- local-ai-server;
- dbt Wizard;
- BigQuery Graph/ADK/A2UI;
- BigSet;
- agentcookie.

For every overlap, state whether the candidate must be subordinate, read-only,
isolated, extracted as a pattern, deferred, or rejected. Explain how split-brain
state, duplicate scheduling, duplicate workers, conflicting memory, conflicting
retries, and routing conflicts are prevented.

### 6. Automatic disqualifiers for core adoption

Flag a candidate as unsuitable for core adoption when it cannot cleanly avoid
any of these:

- replacing LiteLLM, Judge Gate, Ledger, GitHub protections, or the action
  layer without overwhelming measured evidence and a separate migration
  decision;
- introducing an unapproved model gateway or provider API-key dependency;
- allowing self-approval, self-promotion, auto-merge, auto-deploy, or
  production writes outside the Ledger/GitHub wall;
- silently changing global Claude, Codex, Git, shell, MCP, IDE, browser, or OS
  state;
- retaining secrets, raw transcripts, hidden evals, browser cookies, SSH/Git
  credentials, or production tokens;
- requiring unsupported platforms or unavailable hardware;
- lacking a clean uninstall and rollback path;
- lacking deterministic evidence;
- evaluating itself using the same context that produced the work;
- training on or adapting to final held-out tests;
- weakening tests or redefining success after seeing results;
- creating irreversible or opaque state;
- using an incompatible license;
- providing only marketing claims.

### 7. Evaluation method

Do not use one weighted score to hide tradeoffs. Produce a per-dimension
scorecard with evidence and confidence for:

- proven current gap;
- measurable quality improvement;
- token/time/operator-effort impact;
- architecture fit;
- authority overlap;
- security/privacy;
- reliability/failure behavior;
- local-first/platform fit;
- observability/auditability;
- determinism/reproducibility;
- integration/maintenance cost;
- reversibility/uninstall;
- license/sustainability.

Use outcome labels:

- `ADOPT`: proven capability, low overlap, safe integration.
- `PILOT`: promising, bounded uncertainty, feature-flagged experiment justified.
- `EXTRACT_PATTERN`: useful design, whole product overlaps or conflicts.
- `OPTIONAL_TOOL`: useful manually/read-only, not core architecture.
- `DEFER`: possible future use, blocked by maturity/platform/dependency/no gap.
- `REJECT`: worsens authority, security, reliability, or maintainability.

If hard disqualifiers exist, the score cannot override them.

### 8. Required experiment designs

Design A/B experiments before any implementation. Use the same repository
snapshot, task, machine class, allowed tools, clean worktree, and verifier
separation. Repetition counts, budgets, timeouts, and stopping rules must be
declared in the benchmark plan before running; derive them from variance,
resource budget, or existing config, not inline guesses.

Code retrieval:

- Compare native search, ripgrep/AST/LSP/Git, Semble, codebase-memory-mcp, and
  any layered approach only after individual results justify layering.
- Measure correct files, recall/precision, stale-index failure, time, tokens,
  tool calls, files read, hallucinated relationships, index build/update cost,
  RAM/CPU, cross-repo accuracy, Windows/container behavior, and secret
  exclusion.

Agent observability/UI:

- Compare existing logs/Ledger/UI with abtop, ClawCodex UI patterns, and other
  read-only panels.
- Measure session discovery, context/token accuracy, orphan process/port
  detection, false positives, privacy exposure, JSON usefulness, CPU overhead,
  and whether safe summaries can feed existing monitoring.
- A polished UI can be adopted only as a view/control surface. It cannot own
  mission truth, scheduling, approvals, memory, routing, or policy.

Skill governance:

- Compare current skill/instruction handling with ASM-like inventory/audit.
- Test discovery, duplicate detection, provenance, pinning, security audit,
  custom internal skill protection, CI use, install/uninstall, Windows behavior,
  and public-registry confusion.

Git-backed memory/knowledge:

- Evaluate Agno/GitWiki-like patterns as branch-reviewed Markdown/OKF/ADR
  artifacts, not auto-committed truth.
- Test source fidelity, citations, stale/duplicate/conflicting facts, secret
  scanning, rollback, cross-machine sync, retrieval quality, and separation of
  proposed vs approved knowledge.
- Git history alone is not learning. Learning requires retrieval, provenance,
  evaluation, and measured improvement.

Self-improvement:

- Evaluate SIA-like and MAPPA-like ideas only offline and credential-free.
- Separate development tasks, visible evals, sealed validation, and final held
  out tests.
- Allow proposals to prompts, skills, routing, retrieval, workflow, or tests
  that clarify known requirements.
- Do not allow sealed-eval access, test weakening, evaluator mutation after
  seeing results, production policy changes, protected-branch changes, deploys,
  promotion, or self-judgment.
- Measure held-out success, regressions, variance, cost, wall time, token use,
  overfitting, evaluator gaming, complexity growth, rollback, and leakage.

Multi-agent frameworks:

- Compare one strong executor, worker plus independent reviewer, planner plus
  workers plus verifier, and any framework implementation.
- Use tasks that genuinely benefit from parallel hypotheses.
- Measure correctness, duplicate work, conflicting edits, integration failures,
  orchestration overhead, context loss, replayability, blame assignment, and
  artifact quality.

Local model gateway:

- Compare RamiKrispin/local-ai-server patterns with existing LiteLLM/Ollama.
- Focus on backend adapter contracts, model capability declarations,
  readiness/health endpoints, structured logging, local bearer keys, TLS/LAN
  exposure, and hot-reloaded model registries.
- Do not create a second gateway. Useful patterns must land under LiteLLM or
  the existing config/render/health path.

dbt specialist:

- Evaluate dbt Wizard or dbt skills only against a repo that actually has dbt.
- Test lineage, downstream impact, failed-run diagnosis, SQL/YAML/docs changes
  together, dbt parse/compile/test, compatibility, auth requirements, and
  adherence to existing data standards.

Graph/data systems:

- Do not adopt BigQuery Graph, Neo4j, ADK, or A2UI because demos look good.
- First identify a real multi-hop question hard in SQL/DuckDB/dbt/Git/Ledger.
- Measure correctness, query complexity, freshness, duplicated data, cost,
  access control, and evidence traceability.

Web datasets:

- Evaluate BigSet-like tools only with synthetic or public, non-sensitive
  subjects.
- Outputs are discovery artifacts until validated through existing data
  provenance and quality gates.

Authentication sync:

- Evaluate agentcookie only as a security/compatibility study with synthetic
  credentials.
- Prefer scoped OAuth, service accounts, short-lived tokens, and per-tool
  credentials over replicating a human browser identity.

### 9. Candidate-specific questions

ClawCodex:

- Is the desired value a premium UI/window monitor, or does it require adopting
  another coding runtime?
- Can TUI, workflow visualization, status line, journaling, retry/resume, or
  advisor patterns be extracted without runtime adoption?
- Does it duplicate Claude Code, Codex, LiteLLM, worktrees, memory, and worker
  management?

Puppetmaster:

- Which ideas are unique: typed artifacts, independent workers, deterministic
  stitching, replay, artifact rereads, or failure classification?
- Which parts duplicate LiteLLM, Ledger, Judge Gate, executor routing, or
  worktree leases?
- Can useful artifacts be adopted without hooks, MCP auto-invocation, provider
  fallback, or a second registry?

Agno/GitWiki:

- Is AgentOS required, or is the useful part Markdown plus Git plus citations
  plus retrieval?
- Should writes auto-commit, or open reviewed proposals?
- How are raw notes separated from approved knowledge?

SIA:

- Can held-out evaluation and generation-artifact patterns be used without
  autonomous weight updates or self-promotion?
- Can it overfit to the evaluator or mutate the harness?
- Which parts fit the existing improvement loop?

MAPPA:

- Can per-action scoring improve Ledger events without RL training?
- Are deterministic tool outcomes better process rewards than another LLM?
- How do we prevent rewarding plausible but wrong intermediate work?

Semble vs codebase-memory-mcp:

- Which is better for snippet retrieval?
- Which is better for structural call chains, architecture, change impact,
  ADRs, routes, and cross-repo reasoning?
- Are they alternatives or complementary? If layered, what deterministic rule
  chooses query order?

ASM:

- Can it audit skills without becoming an uncontrolled installer?
- Does it support pinning, provenance, lockfiles, and CI-safe output?
- Should it manage production skills or only audit/develop them?

local-ai-server:

- Which patterns improve LiteLLM/Ollama?
- Does any part justify replacing LiteLLM? Assume no unless measured evidence
  proves a critical gap.
- Is MLX/Mac-specific design relevant to Windows/NVIDIA/4090 deployment?

dbt Wizard:

- Does it improve dbt lineage and coordinated SQL/YAML/docs changes over
  Claude/Codex plus existing dbt standards?
- Can it run as a restricted specialist with no production authority?

BigQuery Graph/ADK/A2UI:

- Is there real BigQuery data gravity?
- Does the graph solve a demonstrated multi-hop problem?
- Does ADK duplicate the existing control plane?
- Is A2UI only a presentation layer?

BigSet:

- Does it fill a real live-web ingestion gap?
- Can existing research/pipeline tooling do the same?
- Are provenance, freshness, schema stability, and licensing sufficient?

agentcookie:

- Is copying a human browser identity necessary or merely convenient?
- What is the compromise blast radius?
- Can least-privilege credentials solve the same need?

### 10. Required deliverables

Produce results in this order:

1. Executive verdict.
2. Verified current architecture: implemented vs planned.
3. Gap analysis by capability.
4. Candidate evidence table with evidence labels.
5. Control-plane overlap matrix.
6. Security/privacy/supply-chain review.
7. Capability extraction table.
8. Experiment plans with exact commands where possible.
9. Decision table: ADOPT, PILOT, EXTRACT_PATTERN, OPTIONAL_TOOL, DEFER, REJECT.
10. ADR draft for each accepted, extracted, deferred, or rejected candidate.
11. Implementation backlog:
    - Phase 0: inventory and baseline measurements.
    - Phase 1: read-only experiments.
    - Phase 2: isolated pilots.
    - Phase 3: feature-flagged integration.
    - Phase 4: monitored canary.
    - Phase 5: human-approved promotion.
    - Phase 6: cleanup of redundant systems.
12. Rejection/defer list with re-evaluation conditions.
13. `docs/MASTER.md` update summarizing what was evaluated, what was decided,
    and what remains in order.

The final answer is complete only when every claim is evidence-labeled, the
baseline and candidate conditions are comparable, deterministic checks passed
or failures are recorded, failure behavior and rollback were considered, an
independent verifier plan exists, and authority boundaries remain intact.
