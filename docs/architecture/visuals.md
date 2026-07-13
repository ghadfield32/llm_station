# Visuals — the command center, stage by stage

Fourteen diagrams, one per concern. Read top to bottom for the full picture, or jump to the stage you're setting up. These render on GitHub, in VS Code (Mermaid preview), and at mermaid.live.

---

## 1. Top-level architecture — what runs where

```mermaid
flowchart TD
    U["You, anywhere<br/>5080 laptop · desktop · phone"] --> TS["Tailscale private mesh<br/>no public SSH / no public dashboards"]

    TS --> VPS["VPS control plane — always-on brain"]
    VPS --> H["Hermes Agent<br/>orchestration · memory · channels · scheduling"]
    VPS --> L["LiteLLM<br/>model gateway · virtual keys · budgets · fallback · MCP"]
    VPS --> J["Judge Gate<br/>risk classification · judge arrays"]
    VPS --> G["Ledger (SQLite)<br/>missions · leases · approvals · kill switch"]
    VPS --> M["Uptime Kuma + restic<br/>monitoring · backups"]

    TS --> W["RTX 4090 desktop — heavy worker"]
    W --> LM["Local models<br/>Ollama / vLLM (triage + cheap judges, ~$0)"]
    W --> DC["git worktrees + devcontainers<br/>one isolated checkout per mission"]
    W --> EX["Executor<br/>Claude Code (primary) · Codex CLI · OpenHands later"]

    TS --> IDE["VS Code Remote Tunnel<br/>human IDE into the SAME worktree"]
    IDE --> DC

    EX --> CK["static checks + LLM judge arrays"]
    CK --> PR["GitHub PR (feature branch only)"]
    PR --> WALL["Branch protection · CODEOWNERS · required CI · your review"]

    L -. cheap-first, escalate .-> LM
    J --> L

    classDef brain fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef worker fill:#2d4a2d,stroke:#5cb85c,color:#fff
    classDef wall fill:#5f1e1e,stroke:#d9534f,color:#fff
    class VPS,H,L,J,G,M brain
    class W,LM,DC,EX worker
    class PR,WALL wall
```

**Read it as:** the brain (blue) is always up on a cheap VPS; the muscle (green) is your 4090, reached privately; GitHub (red) is the wall the agent can prepare work against but never cross alone.

---

## 2. Config contract flow — why it's hard to break

```mermaid
flowchart LR
    Y["configs/*.yaml<br/>editable source of truth"] --> P["Pydantic contracts<br/>schemas/base.py + contracts.py"]
    P -->|make validate| OK{Valid?}
    OK -->|"no — typo, dup priority,<br/>L3 w/o approval, repo_task secret"| STOP["STOP<br/>nothing runs"]
    OK -->|yes| R["make render"]
    R --> GEN["generated/litellm-config.yaml<br/>generated/json-schema/"]
    GEN --> LL["LiteLLM proxy reads it"]
    Y --> IMP["make impact<br/>reads git diff + breakage.yaml"]
    IMP --> REQ["prints blast radius<br/>+ required checks"]

    classDef stop fill:#5f1e1e,stroke:#d9534f,color:#fff
    classDef good fill:#2d4a2d,stroke:#5cb85c,color:#fff
    class STOP stop
    class R,GEN,LL good
```

**The guarantee:** a bad edit fails at `make validate`, not at 2am. Tested invariants that get rejected: unknown keys, duplicate model priorities, two canaries in one role, `canary_weight` outside 0–1, missing risk tiers, L3/L4 without approval, and any `repo_task` that's persistent or holds secrets.

---

## 3. Environment map — one environment per activity

```mermaid
flowchart TB
    subgraph VPS["VPS · persistent · control plane"]
        HERMES["Hermes"]
        LITELLM["LiteLLM"]
        JUDGE["Judge Gate"]
        LEDGER["Ledger"]
        KUMA["Uptime Kuma"]
    end

    subgraph GPU["4090 desktop · persistent · heavy worker"]
        OLLAMA["Ollama / vLLM<br/>local open models"]
        WORKTREE["git worktrees"]
        DEVC["devcontainers · EPHEMERAL · no secrets"]
        EXEC["Claude Code / Codex CLI"]
    end

    subgraph HUMAN["Human devices · clients"]
        LAPTOP["5080 laptop"]
        PHONE["phone"]
    end

    subgraph OPT["Optional relay · mini-PC or Pi"]
        RELAY["Wake-on-LAN · watchdog<br/>subnet router · backup mirror"]
    end

    PHONE --> HERMES
    LAPTOP --> WORKTREE
    HERMES --> JUDGE --> LEDGER
    JUDGE --> LITELLM --> OLLAMA
    LEDGER -->|grants 1 lease| WORKTREE --> DEVC --> EXEC
    RELAY -.wakes.-> GPU

    classDef eph fill:#4a3a1e,stroke:#d9a534,color:#fff
    class DEVC eph
```

**Isolation invariant (enforced by the contract):** the `repo_task`/devcontainer environment (amber) is ephemeral and holds **no secrets**. That's what keeps one mission from contaminating another or leaking credentials into a sandbox.

---

## 4. Mission lifecycle — every request, same gates

```mermaid
sequenceDiagram
    participant U as You
    participant H as Hermes
    participant L as Ledger
    participant J as Judge Gate
    participant W as 4090 Workspace
    participant LL as LiteLLM
    participant G as GitHub

    U->>H: Request mission
    H->>L: Open mission ID
    H->>J: Triage L0–L4
    J->>LL: cheap/local model first
    J-->>H: risk tier + model route
    H->>J: Plan + validation plan
    J-->>H: plan critique (scope + value)
    H->>L: request branch/worktree lease
    L-->>W: grant ONE isolated lease
    H->>W: executor edits in devcontainer
    W->>W: static checks (ruff/mypy/pytest/gitleaks/semgrep)
    W->>J: pre-commit judge array
    J-->>W: pass / warn / block
    W->>J: pre-push cross-provider skeptic
    J-->>L: approval required if L3/L4
    U->>L: approve external write (signed)
    W->>G: push branch / open PR
    G->>G: required CI + CODEOWNERS + your review
    note over G: agent CANNOT merge/deploy/publish
```

**The principle:** deterministic checks before LLM judges (cheaper, less ambiguous), and a human gate before anything leaves the sandbox.

---

## 5. Risk tiers — what's allowed to be automatic

```mermaid
flowchart TD
    REQ["Request"] --> TRIAGE["Triage judge (local/cheap)"]
    TRIAGE --> L0["L0 read-only<br/>summarize · inspect · search"]
    TRIAGE --> L1["L1 plan-only<br/>architecture/migration plan"]
    TRIAGE --> L2["L2 local edits<br/>branch/worktree edits"]
    TRIAGE --> L3["L3 external write<br/>push · open PR · comment"]
    TRIAGE --> L4["L4 dangerous<br/>merge · deploy · publish · secrets · delete"]

    L0 --> AUTO["✅ Auto"]
    L1 --> PC["plan critic"] --> AUTO
    L2 --> LOCAL["leased worktree"] --> CHK["static + pre-commit judges"] --> AUTO
    L3 --> SK["pre-push skeptic"] --> AP["🧑 human approval"] --> PRPUSH["push / open PR"]
    L4 --> MAN["🧑 manual only<br/>no automation"]

    classDef auto fill:#2d4a2d,stroke:#5cb85c,color:#fff
    classDef human fill:#4a3a1e,stroke:#d9a534,color:#fff
    classDef danger fill:#5f1e1e,stroke:#d9534f,color:#fff
    class AUTO auto
    class AP,PRPUSH human
    class MAN danger
```

Hard rule: **full power inside the sandbox, narrow audited power outside it.** L3/L4 *cannot* be configured to skip approval — the contract rejects it.

---

## 6. Judge arrays — cheap-first, cross-provider

```mermaid
flowchart LR
    WRITER["Writer model<br/>Claude Code / Codex / local"] --> DIFF["Diff"]
    DIFF --> STATIC["Static tools FIRST<br/>ruff · mypy · pytest · gitleaks · semgrep"]
    STATIC --> J1["diff judge"]
    STATIC --> J2["scope judge"]
    STATIC --> J3["defensive-coding judge"]
    STATIC --> J4["secret/security judge"]
    J1 --> D{Verdict}
    J2 --> D
    J3 --> D
    J4 --> D
    D -->|pass| COMMIT["✅ allow commit"]
    D -->|warn| ESC["escalate to stronger,<br/>cross-provider judge"]
    D -->|block| STOP["⛔ block + required changes"]

    classDef ok fill:#2d4a2d,stroke:#5cb85c,color:#fff
    classDef no fill:#5f1e1e,stroke:#d9534f,color:#fff
    class COMMIT ok
    class STOP no
```

**Cross-provider rule:** whatever family *wrote* the code, a *different* family reviews it (Claude writes → GPT reviews, and vice-versa). The **defensive-coding judge** blocks bloat — swallowed exceptions, redundant guards, hardcoded fallbacks where data-driven values belong, dead flags, fake retries, out-of-scope rewrites — while allowing legitimate boundary validation and clear error propagation.

---

## 7. Model update flow — no auto-promotion

```mermaid
flowchart TD
    SOURCES["local Ollama tags<br/>open-model leaderboards"] --> SCOUT["make model-scout<br/>generated/model-scout-report.md"]
    SCOUT --> DECIDE{Worth testing?}
    DECIDE -->|no| ARCHIVE["archive report"]
    DECIDE -->|yes| PATCH["gated edit/PR<br/>configs/models.yaml"]
    PATCH --> V["make validate<br/>(license · priority · canary rules)"]
    V --> EVALS["make evals<br/>routing/judge regression"]
    EVALS --> R["make models<br/>(render + pull local tags + restart)"]
    R --> CAN["make models-canary<br/>small traffic slice"]
    CAN --> MET["compare: cost · latency<br/>false blocks · missed issues"]
    MET --> DEC{Good enough?}
    DEC -->|yes| PROM["make models-promote"]
    DEC -->|no| RB["make models-rollback"]

    classDef good fill:#2d4a2d,stroke:#5cb85c,color:#fff
    class PROM good
```

**Updating the system = report → YAML edit → evals → canary.** Local picks (on the 4090): `qwen3-coder:30b`, `qwen3:30b`, `devstral:24b`. Provider routes are contract-forbidden in LiteLLM roles. `scout.propose_only: false` fails validation.

---

## 8. First-boot build flow — the order that actually works

```mermaid
flowchart TD
    S1["make setup<br/>deps · .env · validate · build images"] --> S2["verify pinned LiteLLM digest<br/>update only during upgrades"]
    S2 --> S3["make bootstrap<br/>litellm-db + litellm + ledger ONLY"]
    S3 --> S4["make keys<br/>mint 2 virtual keys"]
    S4 --> S5["✋ paste keys into .env<br/>HERMES_LITELLM_KEY · JUDGE_GATE_LITELLM_KEY"]
    S5 --> S6["make up<br/>verify → render → full stack"]
    S6 --> S7["make health"]
    S7 --> S8["make mission-dryrun<br/>L0–L4, no real model calls"]

    classDef manual fill:#4a3a1e,stroke:#d9a534,color:#fff
    class S2,S5 manual
```

**Why `bootstrap` before `up`:** hermes reads its model key from `.env`, but that key doesn't exist until LiteLLM is running and `make keys` mints it. `bootstrap` starts just the infra so you can mint keys first; `up` then brings up the full stack with keys in place. The two amber steps are the only manual ones.

---

## Phase roadmap (the whole build, one picture)

```mermaid
flowchart TD
    A["Phase 1 · VPS control plane<br/>setup → digest → bootstrap → keys → up → health"] --> B["Phase 2 · 4090 worker<br/>Tailscale → Ollama → VS Code tunnel → worktrees → devcontainers"]
    B --> C["Phase 3 · GitHub hardening<br/>App/PAT → protected main → CI → CODEOWNERS → review"]
    C --> D["Phase 4 · workspace expansion (optional)<br/>Coder · OpenHands · Codespaces fallback"]
    D --> E["Phase 5 · relay (optional)<br/>mini-PC/Pi · Wake-on-LAN · watchdog · backup mirror"]

    classDef done fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef opt fill:#3a3a3a,stroke:#888,color:#fff
    class A,B,C done
    class D,E opt
```

Phases 1–3 are the real system (blue). Phases 4–5 are optional (grey) — add only when you hit a need they solve.

---

## 10. Per-stage model & judge routing (tier-colored)

```mermaid
flowchart TD
    S1["1 · Sort<br/>risk-judge → tier L0–L4"] --> S2["2 · Plan<br/>scope-judge → plan-critic"]
    S2 --> S3["3–4 · Docs + Scaffold<br/>scope-judge proportional"]
    S3 --> S5["5 · Implement<br/>static FIRST, then diff/secret/defensive"]
    S5 --> S6["6 · Stuck-escalation<br/>stuck-detector → segment-fixer"]
    S6 --> S7["7 · Debug + log-scan<br/>log-scanner → root-cause-debugger"]
    S7 --> S8["8 · Pre-push<br/>security-skeptic + human approval"]
    S8 --> S9["9 · Architecture<br/>architect-skeptic + cost-judge"]

    classDef local fill:#2d4a2d,stroke:#5cb85c,color:#fff
    classDef mid fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef heavy fill:#5f1e1e,stroke:#d9534f,color:#fff
    class S1 local
    class S2,S3,S5 mid
    class S6,S7,S8,S9 heavy
```

Green = local/free (4090), blue = mid cloud (Sonnet/GPT-5.4), red = heavy frontier (Opus/GPT-5.5). Money is only spent climbing when a cheaper judge can't clear the call. Stages 6–7 are where cheap models would otherwise degrade the codebase silently — a frontier model takes the stuck segment, fixes it correctly, then the pipeline continues. Full detail in `docs/MASTER.md` §5.

---

## 11. Proactive ops lane (watching already-done work)

```mermaid
flowchart TD
    TRIG["Scheduled trigger<br/>DAG · data · service · repo"] --> EVID["Collect evidence<br/>logs · freshness · checks · tree"]
    EVID --> SCAN["Local scanner (cheap)<br/>freshness · log · data-contract"]
    SCAN --> HEALTHY{Healthy?}
    HEALTHY -->|yes| OK["Ledger event<br/>no action"]
    HEALTHY -->|unclear| VERIFY["Mid verifier<br/>Sonnet/GPT-5.4"]
    HEALTHY -->|no| RCA["Open RCA mission"]
    VERIFY -->|real issue| RCA
    VERIFY -->|noise| OK
    RCA --> DEBUG["Root-cause debugger<br/>cross-provider · lineage"]
    DEBUG --> GATED["Rejoins gated pipeline<br/>lease → checks → judges → approval → PR"]
    GATED --> WATCH["Post-watch<br/>1h · 24h · 7d"]
    STEW["Repo stewardship findings"] -->|report, never auto-edit| OK
    USAGE["Usage digest<br/>spend · escalation · blocks"] --> OK

    classDef local fill:#2d4a2d,stroke:#5cb85c,color:#fff
    classDef mid fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef heavy fill:#5f1e1e,stroke:#d9534f,color:#fff
    class SCAN,OK local
    class VERIFY,WATCH mid
    class RCA,DEBUG heavy
```

A scheduled check observes, classifies, and at most opens a gated mission — it never edits directly. Healthy → benign ledger event. Unclear → cheap escalation to a mid verifier. Real problem → RCA mission that rejoins the same lease/checks/judges/human-gate pipeline as any other work. Repo-stewardship findings become reports (capped at L2, never an auto-edit). Usage digest summarizes LiteLLM spend and Ledger activity. Full detail in `docs/proactive-ops.md`; config in `configs/proactive.yaml`.

---

## 12. Ten-config contract flow (with standards)

```mermaid
flowchart TD
    M[models] --> VAL
    J[judges] --> VAL
    G[gates] --> VAL
    E[environments] --> VAL
    S[standards] --> VAL
    B[breakage] --> VAL
    P[proactive] --> VAL
    T[targets] --> VAL
    TO[tools] --> VAL
    EV[evals] --> VAL
    VAL["make validate<br/>Pydantic + cross-file refs"] --> OK{Valid?}
    OK -->|invalid| STOP["STOP — nothing runs"]
    OK -->|valid| RENDER["make render<br/>litellm config + json-schema"]
    S --> STD["make repo-install<br/>CLAUDE.md + AGENTS.md"]
    S --> JUDGE["Judge Gate standards prompt"]
    RENDER --> RUN["proactive reads targets<br/>judges cite tools<br/>evals gate models"]
    RUN --> PROMOTE["model promotion gate<br/>report → evals → canary → promote/rollback"]

    classDef new fill:#0f6e56,stroke:#5dcaa5,color:#fff
    classDef stop fill:#5f1e1e,stroke:#d9534f,color:#fff
    classDef good fill:#2d4a2d,stroke:#5cb85c,color:#fff
    class S new
    class STOP stop
    class RENDER,RUN,PROMOTE,STD,JUDGE good
```

Teal = `standards.yaml`, the durable operating contract for Claude Code, Codex, and Judge Gate. All thirteen configs validate through Pydantic plus a cross-file linter. The contract model is unchanged — standards, model scouting, usage digest, and skill-update caps are data-driven additions, not new architecture. Detail in `docs/MASTER.md`.

---

## 13. Ecosystem layers (what's load-bearing vs convenience vs skip)

```mermaid
flowchart TD
    subgraph CORE["core · load-bearing"]
        HERMES["Hermes Agent<br/>orchestrator"] --> KANBAN["Hermes Kanban<br/>task board"]
        LITELLM["LiteLLM<br/>gateway · budgets"]
        SAFETY["Judge Gate + Ledger<br/>risk · approvals"]
    end
    OLLAMA["Ollama on 4090<br/>local models · num_ctx≥64k"] --> LITELLM
    HERMES --> LITELLM
    HERMES --> SAFETY
    WEBUI["Hermes WebUI · Phase 4<br/>nesquena/hermes-webui · Tailscale+password"] -->|drives, doesn't govern| HERMES
    INSTALL["ollama launch hermes<br/>install path → same agent"] -.installs.-> HERMES
    SAFETY --> GH["GitHub protections<br/>final wall"]
    SKIP["local-ai-server — skip<br/>Mac/MLX-only · LiteLLM already does it"]

    classDef core fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef local fill:#2d4a2d,stroke:#5cb85c,color:#fff
    classDef conv fill:#3c3489,stroke:#7f77dd,color:#fff
    classDef wall fill:#5f1e1e,stroke:#d9534f,color:#fff
    classDef skip fill:#3a3a3a,stroke:#888,color:#fff
    class HERMES,KANBAN,LITELLM,SAFETY core
    class OLLAMA local
    class WEBUI,INSTALL conv
    class GH wall
    class SKIP skip
```

Blue = core (load-bearing). Green = local runtime, always reached *through* LiteLLM. Purple = optional convenience: the WebUI (`nesquena/hermes-webui`, MIT, ~8.2k stars, 430 releases — mature, works with the Ollama-launched Hermes via `~/.hermes` auto-detection) drives the agent but never governs it; `ollama launch hermes` just installs the same agent. Red = the GitHub wall. Grey = `local-ai-server`, skipped (Mac/MLX-only, WIP, and LiteLLM already does the gateway job). Full reasoning in `docs/ecosystem.md`; safe WebUI defaults in `configs/ui.yaml`.

---

## 14. Standards, skills, and usage feedback loop

```mermaid
flowchart TD
    STD["configs/standards.yaml<br/>principles + profiles"] --> VALID["make standards-validate"]
    VALID --> RENDER["make repo-install<br/>PROFILE=python_ml_pipeline"]
    RENDER --> CLAUDE["CLAUDE.md<br/>Claude Code memory"]
    RENDER --> AGENTS["AGENTS.md<br/>Codex/repo agents"]
    STD --> JUDGE["Judge Gate<br/>standards in prompts"]

    LITELLM["LiteLLM virtual keys<br/>spend by role/key"] --> DIGEST["make usage-digest"]
    LEDGER["Ledger<br/>missions + verdicts"] --> DIGEST
    DIGEST --> REPORT["generated/usage-digest.md"]
    REPORT --> TUNE["budget/model/standard changes<br/>as gated missions"]

    RCA["RCA output<br/>incident prevention"] --> DRAFT["draft skill/prompt/standard update"]
    DRAFT --> L2["L2 local edit cap<br/>normal judges apply"]
    L2 --> STD

    classDef source fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef good fill:#2d4a2d,stroke:#5cb85c,color:#fff
    classDef cap fill:#4a3a1e,stroke:#d9a534,color:#fff
    class STD,LITELLM,LEDGER source
    class VALID,RENDER,CLAUDE,AGENTS,JUDGE,DIGEST,REPORT,TUNE good
    class L2 cap
```

The feedback loop is automatic up to evidence and drafts, then gated for edits. Standards update once and render into both executors; usage spend is pulled from LiteLLM and operational behavior from the Ledger; skill/prompt improvements can be proposed by RCA, but cannot self-apply outside L2 gated work.
