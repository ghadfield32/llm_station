# Repository Capability Evaluation Loop

A reusable mission prompt for deciding whether an external tool, repository,
agent pattern, skill, or library should be adopted. The job is not to advocate
and not to install everything — it is to produce **reproducible evidence**
showing whether each candidate solves a real problem better than the current
approach, then stop at a reviewable recommendation.

This doc has three parts: **Part A** maps the loop onto this command center's
existing stages, gates, and contracts (read this first — it resolves the
loop's open inputs for this stack). **Part B** is the full evaluation prompt,
usable verbatim as a mission brief. **Part C** is the pre-registered candidate
roster — the current batch of candidates with sources, claims (all unverified
until Stage 1), target seams, and stack-specific knockout risks, plus a
ready-to-run mission brief for the first batch.

---

## Part A — How this runs inside the command center

### Entry and risk

An evaluation enters like any other work: a kanban card (section
`Command Center`, Risk **L2**) dragged to Approved → bridge → Ledger mission,
or a direct mission. The loop's `MAX_RISK_LEVEL: L2` is exactly our gate
model:

| Loop stage | Our tier | Meaning here |
| --- | --- | --- |
| Stage 0–5 (preflight, evidence, gates, fit, threat model, benchmark design) | L0/L1 | read-only + plans; runs unattended |
| Stage 6–10 (minimal implementation, test ladder, chaos, verification, correction) | L2 | one leased worktree, one branch, one devcontainer; feature-flagged, removable |
| Opening the recommendation PR | L3 | human approval at the Ledger |
| Actual adoption (promote, schedule, deploy) | separate mission | never part of the evaluation |

### Constraint cross-walk (the loop's §2 ↔ this repo's enforcement)

| Loop constraint | Already enforced by |
| --- | --- |
| No second control-plane authority; don't bypass gateway/Ledger/approval wall | the contract model + `configs/gates.yaml`; L3/L4 cannot skip approval |
| Agents may not approve their own work | `actions.set_status` refuses Approved; bridge applies Approved-only; Ledger holds L3/L4 |
| No push to default branch / merge / deploy / secrets | GitHub wall (`docs/github-safety.md`) + L4 manual-only |
| One isolated mission branch/worktree/environment | the lease invariant; `repo_task` is ephemeral + secret-free |
| No persistent scheduled work created by the candidate | agent-created persistence is deliberately blocked (classifier-enforced) |
| Deterministic checks before model review; a verdict can't override a failed check | the standing pipeline rule (static tools first, fail closed) |
| Stop if a candidate needs broader privileges than the ceiling | mirrors `proactive.yaml` contract rejections — don't work around a failed gate |

### Repo-specific input defaults

Resolve the loop's §1 inputs this way unless the mission says otherwise:

```text
TARGET_REPOSITORY:  this repo (llm_station) or the repo named by the mission
REPOSITORY_PROFILE: docs/MASTER.md §11 (module tree) + configs/*.yaml
BASELINE_TASKS:     make validate · make mission-dryrun · make evals ·
                    make live-smoke · growth-os selftest.py (22 checks)
MAX_RISK_LEVEL:     L2 (hard ceiling; L3 = the recommendation PR only)
NETWORK_POLICY:     tailnet + package registries + the candidate's pinned
                    source; no public exposure; no new outbound services
SECRET_POLICY:      no provider API keys anywhere (validation forbids them);
                    no production secrets in worktrees (repo_task is secret-free);
                    candidates needing OpenAI/Anthropic/OpenRouter keys ⇒ knockout
LICENSE_POLICY:     permissive (MIT/Apache-2.0/BSD) adoptable; copyleft or
                    unresolved ⇒ DEFER/REJECT with the gate documented
SUPPORTED_HOSTS:    Windows workstation (current) · Linux/VPS (target) · 4090 worker
OUTPUT_DIRECTORY:   evaluation/capability-assessment (inside the mission worktree,
                    committed on the mission branch, shipped in the PR)
```

### Role mapping

- **Investigator / Implementer / Verifier** are three contexts, not one chat.
  Run the Verifier **cross-provider** (the standing rule: whatever family
  implemented, a different family verifies — Claude Code ↔ Codex), or at
  minimum a fresh context with no access to the Implementer's reasoning.
- Local judge aliases (`local-judge`, `security-judge`) handle the cheap
  passes; the cross-provider executor handles Stage 9 verification. Verdicts
  log to the Ledger like any judge verdict.

### Repo-specific amendments (gaps the generic loop doesn't cover)

1. **Dependencies follow the uv standard** (standards.yaml
   `python_ml_pipeline`): any adapter dependency is `uv pip install` → pinned
   range in `pyproject.toml` → `uv sync` resolves cleanly → committed with the
   code. A candidate that can't be expressed this way fails the
   "cannot be pinned reproducibly" knockout.
2. **Local-only gateway is a knockout gate**: a candidate that requires its
   own cloud-provider key, or that routes model calls around LiteLLM, fails
   §6 ("requires a provider prohibited by repository policy").
3. **Watch-list precedent**: `docs/optional-mirage.md` is the house example of
   a correctly-deferred candidate (young project in a high-trust seam →
   DEFER + re-evaluation criteria). Match its rigor when writing DEFER
   dispositions.
4. **Where the verdict lives**: the final comparison matrix and disposition go
   in the mission's PR; a one-line pointer lands in the relevant doc
   (`docs/ecosystem.md` for ecosystem-level candidates). ADOPT/PILOT
   documentation (§18) is prepared on the branch but **not merged** — the PR
   review is the human gate.

---

## Part B — The evaluation prompt (verbatim mission brief)

You are evaluating whether one or more external tools, repositories, agent
patterns, skills, or libraries should be adopted by this repository.

Your job is not to advocate for the candidates and not to install everything.
Your job is to produce reproducible evidence showing whether each candidate
solves a real problem better than the repository's current approach.

### 1. Inputs

Resolve or explicitly report the following:

```text
TARGET_REPOSITORY:
CANDIDATES:
REPOSITORY_PROFILE:
BASELINE_TASKS:
MAX_RISK_LEVEL: L2
MAX_ITERATIONS_PER_CANDIDATE: 3
MAX_COST_PER_CANDIDATE:
MAX_WALL_TIME_PER_CANDIDATE:
NETWORK_POLICY:
SECRET_POLICY:
LICENSE_POLICY:
SUPPORTED_HOSTS:
OUTPUT_DIRECTORY: evaluation/capability-assessment
```

### 2. Non-negotiable operating constraints

Preserve the repository's existing authority boundaries.

1. Do not create a second control-plane authority.
2. Do not replace or bypass the existing model gateway, action layer, Ledger,
   risk classifier, approval wall, or GitHub protections.
3. Agents may not approve their own work.
4. No candidate may push to the default branch, merge, deploy, publish, delete
   remote resources, modify repository settings, create persistent scheduled
   work, or handle production secrets.
5. Work only in one isolated mission branch, worktree, and development
   environment.
6. Do not modify global shell configuration, editor configuration, agent
   configuration, authentication stores, browser profiles, or operating-system
   startup settings.
7. Do not install global hooks or background services.
8. Use feature flags or removable adapters for every experiment.
9. Pin candidate versions or commits. Do not depend on floating branches or
   unpinned installation scripts.
10. Deterministic checks run before model-based review.
11. A model verdict may not override a failed deterministic check.
12. External project claims are hypotheses until reproduced locally.
13. Never fabricate benchmark data, test results, cost estimates, security
    findings, or compatibility.
14. Stop immediately if a candidate requires broader privileges than the
    declared risk ceiling.
15. L3 and L4 operations require explicit human approval and are outside this
    evaluation.

### 3. Required roles and separation

Use three logically separated roles.

**Role A — Investigator.** Collect facts about the target repository and
candidate. Do not implement.

**Role B — Implementer.** Create the smallest reversible experiment necessary
to test the candidate. The Implementer receives the approved experiment design
but must not grade its own work.

**Role C — Independent Verifier.** Receives: the original goal; acceptance
rubric; repository diff; benchmark commands; raw outputs; logs; artifacts;
dependency and license information. Do not give the Verifier the Implementer's
persuasive summary or intended conclusion. The Verifier must reproduce
important commands independently. When distinct model providers are available,
prefer a different provider or model family for the Verifier; otherwise use a
fresh context with no access to the Implementer's reasoning.

### 4. Stage 0 — Repository preflight

Before evaluating candidates:

1. Read the repository's governing documentation: README, architecture
   documents, AGENTS.md, CLAUDE.md, contribution guide, standards and policy
   files, package-management files, CI configuration, security policy, testing
   documentation.
2. Record: current branch; worktree path; clean/dirty status; uncommitted
   files; languages and frameworks; package manager; supported runtime
   versions; current agent surfaces; current search and retrieval tools;
   current skills; current observability; current model-routing mechanism;
   current approval mechanism; current knowledge-management mechanism; current
   test, lint, typing, security, and evaluation commands.
3. Do not alter or discard pre-existing user changes.
4. Establish the unmodified baseline: run the existing deterministic test
   suite; record failures already present; capture wall time and peak resource
   use where practical; capture existing token/context consumption for
   representative agent tasks; record test flakiness through repeated runs
   where practical.
5. Identify the concrete problem each candidate is expected to solve.

A candidate with no repository-specific problem statement must be classified
`NO_JUSTIFIED_USE_CASE` and may not proceed to installation.

Create:

```text
evaluation/capability-assessment/repository-baseline.md
evaluation/capability-assessment/repository-baseline.json
```

### 5. Stage 1 — Candidate evidence collection

For each candidate, inspect the authoritative source and record: repository
and package identity; exact commit/tag/release evaluated; license; security
policy; release activity; test and CI presence; supported operating systems;
supported runtimes; dependencies; installation method; required API keys;
required network access; required data retention; telemetry; external
services; files and directories written; shell commands executed; hooks
installed; background processes created; ports opened; authentication material
accessed; global state modified; default write authority; rollback procedure;
maintenance burden; known limitations; open issues relevant to this
repository.

Label every statement as one of:

```text
VERIFIED_UPSTREAM_FACT
UPSTREAM_CLAIM_NOT_YET_REPRODUCED
LOCALLY_REPRODUCED
INFERENCE
UNKNOWN
```

Do not repeat marketing claims as facts.

Create:

```text
evaluation/capability-assessment/<candidate>/evidence.md
evaluation/capability-assessment/<candidate>/evidence.json
```

### 6. Stage 2 — Knockout gates

A candidate may not proceed to implementation when any of the following
applies:

- license is incompatible or unresolved;
- installation requires unapproved global modification;
- it requires production secrets;
- it replicates cookies, tokens, or authentication stores;
- it requires a provider prohibited by repository policy;
- it bypasses the existing human approval wall;
- it writes directly to the default branch;
- it can merge, deploy, publish, or delete without human approval;
- it requires broader network access than allowed;
- it requires persistent privileges or services not approved for the test;
- it cannot be isolated or cleanly removed;
- it would become a second source of truth without an explicit migration
  decision;
- it cannot be pinned reproducibly;
- it has no measurable repository-specific benefit;
- its minimum compute or infrastructure requirement is unavailable.

A knocked-out candidate receives one of:

```text
REJECT
DEFER
BORROW_PATTERN_ONLY
```

Document the exact failed gate. Do not attempt to work around a failed safety
gate.

### 7. Stage 3 — Architecture-fit analysis

Score each surviving candidate from 0 to 5 on:

```text
problem_relevance        expected_measurable_benefit   integration_fit
authority_boundary_fit   security_fit                  privacy_fit
license_fit              platform_fit                  operational_simplicity
maintainability          observability                 reversibility
testability              evidence_quality              cost_efficiency
latency_impact
```

Also calculate:

```text
duplication_penalty      new_authority_penalty   secret_expansion_penalty
vendor_lock_in_penalty   maintenance_penalty
```

Do not hide the individual scores behind one weighted total.

For every candidate, identify exactly one intended seam:

```text
repository retrieval · skill layer · observability · knowledge generation ·
model routing · worker execution · verification · evaluation ·
data discovery · graph analytics · documentation · post-run attribution
```

If a candidate attempts to own more than one major control-plane boundary,
explain why it should be decomposed rather than adopted wholesale.

### 8. Stage 4 — Threat model and supply-chain review

Evaluate at least: arbitrary shell execution; prompt injection through
repository content; prompt injection through retrieved web content; credential
discovery; environment-variable access; browser-cookie access; SSH or Git
credential access; source-code exfiltration; unexpected telemetry; dependency
confusion; typosquatting; unpinned dependencies; install-script execution;
binary provenance; model-generated code execution; path traversal; writes
outside the worktree; unauthorized network destinations; background-process
persistence; stale index or cache poisoning; insecure artifact
deserialization; compromised skill files; evaluator leakage; benchmark
contamination; self-modification; privilege escalation; rollback failure.

Run available repository-native checks first. Add candidate-specific scans
only when they are isolated and justified. At minimum consider:

```text
secret scanning · dependency vulnerability auditing · license scanning ·
static analysis · malicious-package review · skill or prompt audit ·
network observation · filesystem write observation · process and port observation
```

Create:

```text
evaluation/capability-assessment/<candidate>/threat-model.md
evaluation/capability-assessment/<candidate>/supply-chain.md
```

### 9. Stage 5 — Benchmark design before implementation

Define the benchmark before changing code. Use an A/B design:

```text
A = repository's current baseline
B = baseline plus the smallest candidate integration
```

Use the same: task definitions; repository commit; input files; acceptance
tests; time limits; cost accounting; machine; model configuration where
possible; cache state. Run both cold-cache and warm-cache scenarios when the
candidate maintains an index or cache. Use at least five repetitions for
timing-sensitive tests when affordable. Report median, range, failures, and
sample count. Do not report false precision.

Measure applicable metrics:

- **Outcome quality** — acceptance-test pass rate; task completion rate;
  regression count; incorrect-change count; unsupported-claim count; reviewer
  acceptance; evidence completeness.
- **Retrieval** — recall@K; precision@K; mean reciprocal rank; files required
  but not retrieved; irrelevant files retrieved; stale-result rate;
  changed-file detection latency; generated-file handling; ignored-file
  compliance; secret-file exclusion.
- **Agent efficiency** — input/output/cached tokens; total context consumed;
  model calls; retries; tool calls; wall time; estimated or actual monetary
  cost; human interventions; operator steps.
- **Runtime resources** — CPU; peak memory; disk use; index size; startup
  time; query latency; persistent processes; open ports; network traffic.
- **Reliability** — clean-install success; repeated-run success; idempotency;
  offline behavior; degraded-mode behavior; worker crash recovery; timeout
  recovery; corrupted-cache recovery; partial-output recovery; rollback
  success.
- **Governance** — actions attempted beyond permission; approval-bypass
  attempts; writes outside the worktree; secret-access attempts; direct
  default-branch operations; untracked global modifications; audit-log
  completeness.

Create before running:

```text
evaluation/capability-assessment/<candidate>/benchmark-plan.yaml
evaluation/capability-assessment/<candidate>/acceptance-rubric.yaml
```

### 10. Candidate-specific benchmark requirements

- **Repository search layer (e.g. Semble)** — test retrieval recall against a
  manually established gold set; token consumption vs ripgrep and native agent
  search; indexing and re-indexing time; renamed/deleted/new files;
  uncommitted changes; monorepo boundaries; ignored and secret files; binary
  and generated files; fallback when its index is missing or corrupt. It must
  remain an optional retrieval path.
- **Agent monitor (e.g. abtop)** — test detection of active Claude Code and
  Codex sessions; correct process ownership; token/context estimates;
  rate-limit display; child-process detection; open-port reporting;
  JSON-output stability; Windows and Linux behavior; CPU and memory overhead;
  behavior when no agents are active. It must remain read-only.
- **Skill manager (e.g. asm)** — test complete inventory; duplicate detection;
  broken-link detection; malicious/suspicious skill detection; install
  reproducibility; commit pinning; checksum/manifest handling;
  provider-specific path correctness; uninstall completeness; behavior with
  local unpublished skills; false-positive/negative security findings. Do not
  install unreviewed registry skills.
- **dbt agent skills** — run only when dbt is actually present. Test correct
  vs irrelevant skill triggering; generated SQL validity; dbt
  parse/compile/test; semantic-model correctness; documentation accuracy;
  compatibility with the repo's dbt/adapter versions; changed-model blast
  radius; avoidance of unrelated edits; adherence to data quality and lineage
  requirements.
- **Worker router (e.g. Puppetmaster)** — do not let it replace the Ledger or
  approval wall. Test routing decision quality; cost vs fixed-model baseline;
  routing regret; worker isolation; timeout behavior; crash recovery; typed
  artifact completeness; artifact reuse; SQLite concurrency; duplicate-work
  prevention; approval-bypass attempts; global-hook behavior; failure when no
  provider is available; auditability of every worker decision. Prefer an
  adapter invoked by one existing Ledger mission.
- **Web-data agents (e.g. BigSet)** — use synthetic or non-sensitive subjects
  first. Test field correctness; source coverage; source-URL preservation;
  row/field-level provenance; duplicate handling; contradictory sources;
  blocked pages; refresh stability; data drift; extraction cost;
  legal/terms-of-service review; prompt injection from web pages; invalid
  schema generation; independently sampled manual verification. Outputs are
  discovery artifacts, not canonical truth, until validated.
- **BigQuery Graph** — proceed only when an existing BigQuery dataset and
  graph-shaped question exist. Compare graph query vs SQL baseline; node/edge
  correctness; multi-hop path correctness; explainability; query cost;
  latency; maintenance effort; schema evolution; access controls; preview
  limitations; benefit over existing warehouse modeling. Do not create a
  second database merely for visualization.
- **Generated wiki (e.g. Agno GitWiki)** — test source fidelity;
  citation/path accuracy; stale-page detection; incremental update quality;
  duplicate-page handling; diff readability; history usefulness; rollback;
  prompt-injection resistance; incorrect claims; branch-only write behavior.
  Every write stays on a mission branch and requires normal PR review.
- **Self-improving system (e.g. SIA)** — run offline only. Freeze training
  set, development set, hidden held-out set, evaluator, resource budget,
  stopping criteria. Test real held-out improvement; regression on prior
  capabilities; data leakage; benchmark overfitting; evaluator gaming; unsafe
  self-modification; reproducibility; resource consumption; rollback to the
  prior generation. It may produce candidate patches or artifacts only; it may
  not promote itself.
- **Agent coaching (e.g. MAPPA)** — evaluate the concept separately from the
  training stack. Test whether per-action event scoring improves root-cause
  localization, blame accuracy, retry decisions, mission debugging, postmortem
  quality, repeated-failure prevention. Compare deterministic event
  attribution with model-based coaching before introducing reinforcement
  learning.
- **Full coding runtime (e.g. ClawCodex)** — require proof it solves a
  capability unavailable through existing Claude Code, Codex, and LiteLLM
  surfaces. Test tool permission boundaries; provider-key handling; session
  isolation; filesystem scope; compatibility; runtime stability; test
  coverage; maintenance burden; duplicate functionality; migration and
  rollback cost. Default to reference-only when it duplicates the existing
  runtime.
- **Authentication-state replication (e.g. AgentCookie)** — security-sensitive
  and outside the normal experiment path. Do not test with real credentials.
  Require explicit platform compatibility; synthetic credentials; compromise
  analysis; revocation testing; source-host and destination-host compromise
  analysis; replay analysis; audit logging; secure deletion; proof the use
  case cannot be solved with independent OAuth or scoped credentials. Default
  to rejection when mission environments are intended to be secret-free
  (ours are).

### 11. Stage 6 — Minimal implementation

Only after the benchmark and rubric are committed:

1. Create the smallest possible adapter or configuration.
2. Keep all candidate work behind a feature flag.
3. Avoid broad refactoring.
4. Do not replace current interfaces.
5. Do not weaken existing tests.
6. Do not rewrite unrelated code.
7. Do not add defensive fallbacks that conceal failures.
8. Fail loudly when the candidate is unavailable.
9. Pin the exact candidate version or commit.
10. Record every added dependency.
11. Generate or update the software bill of materials when supported.
12. Record files written outside the repository; the expected value is zero.
13. Record processes, ports, and network destinations used.
14. Provide one-command removal.

Create:

```text
evaluation/capability-assessment/<candidate>/implementation-notes.md
evaluation/capability-assessment/<candidate>/install-manifest.json
evaluation/capability-assessment/<candidate>/rollback.md
```

### 12. Stage 7 — Deterministic test ladder

Run in order:

1. configuration and schema validation;
2. formatting;
3. linting;
4. static typing;
5. unit tests;
6. contract tests;
7. integration tests;
8. security scans;
9. secret scans;
10. dependency audit;
11. license checks;
12. candidate-native tests;
13. repository-specific evaluation suite;
14. benchmark A;
15. benchmark B;
16. failure-injection tests;
17. rollback test;
18. baseline tests again after rollback.

Stop on a failed required gate. Do not ask a judge to excuse it. Save raw
commands, exit codes, stdout, stderr, durations, environment information, and
artifact hashes.

Create:

```text
evaluation/capability-assessment/<candidate>/raw/
evaluation/capability-assessment/<candidate>/results.json
evaluation/capability-assessment/<candidate>/results.md
```

### 13. Stage 8 — Failure and chaos testing

Where safe, test: candidate service unavailable; model provider unavailable;
network unavailable; invalid credentials; expired credentials; rate limiting;
malformed response; timeout; killed worker; corrupt cache; stale index; locked
SQLite database; invalid skill; malicious repository instruction; prompt
injection in retrieved content; missing dependency; incompatible version; disk
full simulation; interrupted installation; interrupted rollback; concurrent
missions.

The expected result is explicit failure, bounded retry, useful logs, preserved
repository state, and no unauthorized escalation.

### 14. Stage 9 — Independent verification

The Verifier must:

1. Confirm the repository remained inside the allowed risk level.
2. Inspect the complete diff.
3. Re-run every critical deterministic command.
4. Reproduce a statistically meaningful sample of benchmark runs.
5. Check that baseline and candidate used equivalent conditions.
6. Challenge every upstream performance claim.
7. Search for hidden global changes.
8. Search for new credential or network requirements.
9. Confirm the candidate cannot approve or dispatch itself.
10. Confirm the default branch was untouched.
11. Confirm rollback restores the prior behavior.
12. Check for benchmark leakage and evaluator contamination.
13. Confirm failures were not excluded from reported averages.
14. Confirm raw artifacts support every reported number.
15. Mark each acceptance criterion: `PASS` / `FAIL` / `INCONCLUSIVE` /
    `NOT_APPLICABLE`.

The candidate cannot pass with an `INCONCLUSIVE` safety criterion.

Create:

```text
evaluation/capability-assessment/<candidate>/verifier-report.md
evaluation/capability-assessment/<candidate>/verifier-results.json
```

### 15. Stage 10 — Bounded correction loop

When the Verifier reports failures:

1. Convert each failure into one narrowly scoped repair item.
2. Prioritize deterministic, safety, and correctness failures before
   performance.
3. Permit the Implementer to change only files required for failed criteria.
4. Re-run the complete affected test ladder.
5. Start a fresh Verifier context.
6. Record before-and-after metrics.

Stop when any condition is met: all required criteria pass; maximum iterations
reached; cost budget exhausted; wall-time budget exhausted; safety boundary
fails; license remains unresolved; two iterations produce no material
improvement; the candidate requires architectural scope expansion; the
candidate performs worse than baseline on a critical metric; rollback cannot
be demonstrated.

Never widen permissions merely to make a candidate pass.

### 16. Stage 11 — Decision framework

Assign exactly one disposition:

- **ADOPT** — a real repository problem is solved; required criteria pass;
  benefit is measurable and repeatable; safety boundaries remain intact;
  maintenance and rollback are acceptable.
- **PILOT** — evidence is promising; remaining uncertainty is bounded; use can
  remain feature-flagged; a limited production-like trial is justified.
- **BORROW_PATTERN_ONLY** — a design idea is valuable; adopting the runtime
  would duplicate authority or introduce excessive risk; the useful portion
  can be implemented through the existing architecture.
- **DEFER** — the use case may become relevant; a dependency, platform,
  maturity, infrastructure, or upstream limitation currently blocks
  responsible adoption.
- **REJECT** — no repository-specific problem exists; risk exceeds benefit;
  authority boundaries would be weakened; the candidate is incompatible,
  unreproducible, or not reversible; it adds a duplicate control plane without
  a justified migration.

### 17. Required final comparison

Produce a matrix containing:

```text
candidate · repository_problem · current_baseline · proposed_seam ·
measured_quality_delta · measured_token_delta · measured_cost_delta ·
measured_latency_delta · resource_delta · security_result · license_result ·
operational_burden · rollback_result · verifier_result · confidence · decision
```

Rank candidates by: 1. correctness and safety; 2. repository-specific value;
3. measurable improvement; 4. architectural fit; 5. operational simplicity;
6. cost. Do not rank primarily by stars, social-media claims, novelty, or
benchmark results from unrelated repositories.

### 18. Documentation requirements

For any `ADOPT` or `PILOT` result, prepare but do not merge: architecture
decision record; installation and upgrade instructions; pinned version;
configuration contract; threat model; operator runbook; testing runbook;
rollback procedure; observability and alerting; ownership and maintenance
expectations; known limitations; data and secret boundaries; impact-map
update; repository instructions update; evaluation-regression test.

Document where the capability belongs and which existing component remains
authoritative.

### 19. Final response format

Return: **Executive finding** (one paragraph: did the candidate solve a real
repository problem); **Baseline** (what exists today and how it performs);
**Candidate evidence** (verified facts, unverified claims, dependencies,
permissions, maturity); **Architecture fit** (the exact integration seam and
any duplicated authority); **Security and supply chain** (threats, scans,
secret exposure, network behavior, license status); **Benchmark results**
(baseline vs candidate, with raw sample count, failures, median, range,
uncertainty); **Failure-injection results** (what broke, how it failed,
whether repository state remained safe); **Independent verifier result**
(passed, failed, or inconclusive criteria); **Decision** (ADOPT / PILOT /
BORROW_PATTERN_ONLY / DEFER / REJECT); **Smallest safe next step** (the next
reversible action requiring human approval); **Files produced** (every
evidence, result, log, decision, and rollback artifact).

### 20. Completion rule

The evaluation is complete only when: every claim is classified by evidence
type; baseline and candidate were compared under equivalent conditions;
deterministic checks passed; failure behavior was tested; rollback was
demonstrated; an independent verifier reproduced critical evidence; authority
and approval boundaries remained intact; the final disposition is justified by
measured repository-specific results.

Do not install, promote, schedule, push, merge, deploy, or publish the
selected candidate after evaluation. Stop at a reviewable recommendation and
wait for the existing human approval process.

---

## Part C — Pre-registered candidate roster (2026-06-12)

The current batch, captured from the source posts. **Every claim below is
`UPSTREAM_CLAIM_NOT_YET_REPRODUCED`** — including star counts, token savings,
speed-ups, and "beat X" results — until Stage 1 reproduces it against the
pinned source. Hypotheses are pre-registered *before* testing so Stage 3
scoring can be checked against them rather than anchored by them; the loop's
evidence, not this table, decides the disposition.

Target repos: **CC** = llm_station (command center) · **BB** =
betts_basketball · **WS** = the workstation/fleet level (not a repo).

### Batch 1 — run first (narrow seams, local-only compatible)

| Candidate | Source | Claimed value (unverified) | Seam | Target | Pre-registered hypothesis + stack-specific risks |
| --- | --- | --- | --- | --- | --- |
| **Semble** | github.com/MinishLab/semble | local CPU code search for agents; "98% fewer tokens", "~250 ms indexing", MCP server, no API keys | repository retrieval | CC + BB | Likely PILOT: local-only and key-free fits our policy exactly. Test recall vs ripgrep/native search on a gold set; secret/generated-file exclusion; stale-index behavior. Must stay an optional retrieval path. |
| **abtop** | github.com/graykode/abtop | htop for coding agents: Claude Code + Codex sessions, tokens, context, rate limits, ports | observability | WS | Likely ADOPT/PILOT: read-only, fits the usage-digest/morning-brief lane. Test Windows behavior, process-detection accuracy, JSON stability, overhead. Must remain read-only; could feed `make usage-digest`. |
| **asm** | github.com/luongnv89/asm | TUI skill manager across 19 providers; inventory, dedupe, `asm audit security`, signed manifests; "313 stars, MIT" | skill layer | WS | Likely PILOT for inventory/audit only. Registry is untrusted: pin commits, allowlist, never unattended install/publish — consistent with our skill_updates L2 cap. Test uninstall completeness and false-positive/negative audit rates. |

### Batch 2 — conditional on the target repo or borrowed as patterns

| Candidate | Source | Claimed value (unverified) | Seam | Target | Pre-registered hypothesis + stack-specific risks |
| --- | --- | --- | --- | --- | --- |
| **dbt-agent-skills** | github.com/dbt-labs/dbt-agent-skills | first-party skills for analytics engineering, semantic layer, migrations, with evals | skill layer | **BB only** | dbt actually exists at `api/de/basketball`, so a justified use case exists. Test trigger precision, generated-SQL validity vs `dbt parse/compile/test`, blast radius, and adherence to the §0.x data-engineering standards. Import only relevant skills. |
| **Independent-verifier loop** (/goal, Outcomes, "loops > prompts") | pattern, no repo; "~6x over Opus 4.7" unverified | goal + rubric + independent grader; never self-grade | verification | CC | BORROW_PATTERN_ONLY → implement natively: we already have cross-provider judges + Ledger; the gap is explicit per-mission acceptance rubrics and a verifier stage that reproduces evidence. Extend `configs/judges.yaml`/mission flow, don't add a framework. |
| **Puppetmaster** | github.com/professorpalmer/Puppetmaster (PyPI: puppetmaster; URL to confirm at Stage 1) | queen-worker routing to cheapest capable model; independent worker processes; typed SQLite artifacts; zero-token follow-ups | worker execution | CC | BORROW_PATTERN_ONLY expected: its router duplicates Ledger/LiteLLM authority, and cheap-first *cloud* routing conflicts with the no-provider-keys rule (knockout for that mode). The testable ideas: typed artifact store for worker outputs, artifact reuse, failure classification. At most an adapter invoked by one Ledger mission. |
| **MAPPA / multiagent-coaching** | github.com/ltjed/multiagent-coaching | per-action 0–10 coaching scores; cross-agent blame attribution; distributed RL training | post-run attribution | CC | BORROW_PATTERN_ONLY: the RL stack is impractical on a 4090/5080 and adds provider dependencies. The portable idea — per-event scoring/attribution — maps onto the existing executor event stream (`POST /mission/{id}/event`). Compare deterministic attribution first. |
| **Agno GitWiki** | github.com/agno-agi/agno (cookbook/01_demo) | git-backed generated wiki; ingest → markdown → auto-commit-push; query via the same agent | knowledge generation / documentation | CC + BB | BORROW_PATTERN_ONLY: auto-commit-push violates the GitHub wall. Pattern worth testing: generated wiki pages on a mission branch + PR review. Decide explicitly whether AppFlowy or the repo stays the authoritative knowledge surface — no second source of truth by accident. |

### Watch-list / likely knockouts (pre-registered Stage 2 outcomes)

| Candidate | Source | Expected gate | Why |
| --- | --- | --- | --- |
| **BigSet** | github.com/tinyfish-io/bigset | KNOCKOUT → DEFER | Requires external provider credentials (forbidden by validation) and is AGPL (license policy). If ever run: isolated discovery only, synthetic subjects, outputs are never canonical truth. |
| **BigQuery Graph + ADK + A2UI** | Google products, no single repo | NO_JUSTIFIED_USE_CASE → DEFER | We have no BigQuery dataset anywhere — the stack is DuckDB + R2. Re-evaluate only if data genuinely lands in BigQuery *and* a multi-hop graph question exists that SQL can't serve. Never create a second database for visualization. |
| **SIA** | github.com/hexo-ai/sia | offline research only | Self-rewriting scaffolding/weights/memory directly contradicts the gated skill-update contract (self-promotion is unrepresentable here). Only as a frozen, offline, credential-free experiment producing candidate patches a human promotes. |
| **ClawCodex** | github.com/agentforce314/clawcodex | REJECT (reference-only) | "Claude Code rebuilt in Python, 6 providers" duplicates Claude Code + Codex + LiteLLM wholesale and expands provider-key surface. Read it for design reference; do not run it. |
| **AgentCookie** | github.com/mvanhorn/agentcookie | REJECT | Replicates authenticated browser/agent state between Macs. Our mission environments are deliberately secret-free and our hosts are Windows/Linux — this weakens the exact boundary the architecture enforces. Fails the §6 cookie/token-replication gate by design. |

### Batch 1 — EXECUTED 2026-06-12 (results in `evaluation/capability-assessment/`)

The loop has been run end-to-end against this repo for all three Batch-1
candidates. Full evidence, raw outputs, threat models, the independent
verifier report, and the comparison matrix are under
`evaluation/capability-assessment/`; the authoritative dispositions are in
`evaluation/capability-assessment/DECISION.md`.

| Candidate | Pre-registered guess | **Measured disposition** | Key measured result |
| --- | --- | --- | --- |
| abtop v0.4.8 | ADOPT/PILOT | **PILOT** | 7/7 Claude sessions detected on Windows, read-only verified, stable `--json`; **Codex 0/4 on Windows** (real gap) |
| semble v0.3.4 | PILOT | **PILOT — blocked on betts** | small repo recall@5 **7/10**, `.env` never surfaced, "98% fewer tokens" did NOT reproduce vs skilled ripgrep. On betts (39k files): recall **6/8** but **crashes indexing out-of-the-box** (WinError 1920 on a WSL symlink) and got **pruned by a concurrent `uv sync`** (not in lockfile). Gate MCP on a committed `.sembleignore` + lockfile pin. |
| asm | PILOT | **DEFER** | knocked out at Stage 0: **zero skill files exist** to manage; no Windows support; "signed manifests" claim is false |

Nothing was installed into production, registered as MCP, scheduled, or
pushed. semble lives in `.venv` only; abtop's pinned binary lives in the eval
dir only. Each PILOT's smallest safe next step is a separate, human-approved
L2 mission (see DECISION.md). The unparameterized brief below remains valid
for re-running or for Batch 2.

**PILOT next steps executed 2026-06-12:** abtop wired into `usage_digest.py`
as an opt-in read-only `--abtop` section (never `--setup`; fail-loud; vendored
binary gitignored) — ADOPT still gated on Codex-on-Windows detection, deferred
because v0.4.8 is the latest release. asm parked (`asm/PARKED.md`). semble
benchmarked on betts and found **not pilot-ready there** (indexing crash on a
WSL symlink; lockfile-pruning) — MCP registration gated on a committed
`.sembleignore` + pinned install. Full record: `evaluation/capability-assessment/`.

Paste Part B as the mission body with these inputs resolved:

```text
TARGET_REPOSITORY:  llm_station (Semble also indexes betts_basketball read-only)
CANDIDATES:         MinishLab/semble · graykode/abtop · luongnv89/asm
REPOSITORY_PROFILE: docs/MASTER.md §11 + configs/*.yaml
BASELINE_TASKS:     make validate · make mission-dryrun · make evals ·
                    make live-smoke · growth-os selftest.py ·
                    3 representative retrieval tasks (gold set, hand-built)
MAX_RISK_LEVEL:     L2
MAX_ITERATIONS_PER_CANDIDATE: 3
MAX_COST_PER_CANDIDATE:      local models $0; executor time ≤ 1 session each
MAX_WALL_TIME_PER_CANDIDATE: 4h
NETWORK_POLICY:     tailnet + PyPI/GitHub for the pinned source only
SECRET_POLICY:      no provider keys; repo_task stays secret-free
LICENSE_POLICY:     MIT/Apache-2.0/BSD adoptable; copyleft ⇒ DEFER
SUPPORTED_HOSTS:    Windows workstation now; Linux/VPS later
OUTPUT_DIRECTORY:   evaluation/capability-assessment
```

Sequencing after Batch 1: **dbt-agent-skills** as its own mission against
betts_basketball; the **verifier-loop and MAPPA patterns** as native
extensions of judges/Ledger (design first, no third-party runtime); everything
in the knockout table stays parked with its re-evaluation condition written
down, Mirage-style.
