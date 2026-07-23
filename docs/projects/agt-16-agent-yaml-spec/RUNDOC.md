# AGT-16 · Typed runtime-agnostic agent-session spec — RUNDOC

Stage 3 run-doc per [TODO_PROCESS.md](../../todos/TODO_PROCESS.md). Status:
**awaiting Stage-4 answers** — do not start execution with §5 open.

## 1. Objective & definition of done

A Pydantic `extra="forbid"` session-spec where the runtime is **one swappable
enum field**: `name`, `instructions` (inline or file ref), `harness` (enum
over our registered adapters), model selection **by capability profile**
(strategic_steward / generalist / deep_code / throughput — resolved live,
never a remembered slug), limits, and policy refs (AGT-14). Done when:
(a) the schema validates under `make validate` with round-trip tests;
(b) all four current adapters are constructible from a spec instance through
the existing registry (no adapter rewrites); (c) one seam consumer is proven:
the kanban chat session boot path (KAN-15's auto-engage) reads a spec instead
of code-shaped defaults.

## 2. Research (verified)

- Pattern source: omnigent `docs/AGENT_YAML_SPEC.md` @ commit c8828ed, read
  raw 2026-07-23 — one YAML: `executor.harness` enum + model + auth, `tools`
  (function/mcp/agent/inherit), `policies` co-located. Precision: in their
  spec the whole `executor` block is runtime-entangled (cursor/kiro carry
  harness-specific model/auth rules); collapsing the runtime choice to ONE
  swappable enum field is **our intended adaptation**, stronger than the
  source. Full analysis:
  [2026-07-23-omnigent-borrow-patterns.md](../../reviews/2026-07-23-omnigent-borrow-patterns.md).
- Deliberately not borrowed: their auth plumbing, Databricks profiles, and
  harness breadth. Claude/Codex remain **coding executors on their own
  subscription auth — never LiteLLM chat models** (CLAUDE.md wall); the spec
  must encode that distinction, not blur it. Concretely (per
  `agent_sessions/registry.py`): `claude_code_local` / `codex_agent` are
  subscription/CLI-auth lanes while `claude_agent` is API-key-backed.
  **Contract decision: auth is registry-owned** — the spec has NO auth field
  and never carries credentials or lane choices; selecting a `harness` value
  resolves its auth lane inside the registry. This is what keeps the
  "one swappable enum field, everything else runtime-agnostic" claim true.
- Our seam today: `src/command_center/agent_sessions/registry.py` +
  adapters; assistant selection in the cockpit is the "assistant chooser",
  not a GatewayCore model pick (chat-first boards decision). KAN-26's
  DESIGN.md contract needs exactly this spec to render runtime-agnostic
  chrome; AGT-10's allocator needs it as its output artifact.

## 3. KPIs & baseline

- Baseline (measured 2026-07-23): **0** typed session specs; 4 adapters
  selected/configured code-shaped; KAN-15 auto-engage unconfigurable without
  code edits.
- KPI-1: runtimes constructible behind one validated spec (baseline 0,
  target 4 = all current adapters).
- KPI-2: seam consumers reading the spec (baseline 0; target ≥1 = KAN-15
  boot path; KAN-26 chrome and AGT-10 emission are later challengers).
- Stop condition: 4 adapters + 1 consumer proven, then reassess.

## 4. Plan (bounded)

1. Schema under `src/command_center/schemas/` (+ example specs in
   `configs/`), `make validate` coverage, capability-profile → live-resolution
   contract documented in-schema (profile names, never slugs).
2. Registry bridge: spec instance → existing adapter construction.
3. KAN-15 consumer: session boot path reads a spec (flagged).
4. Tests: round-trip, unknown-field rejection, harness-enum drift guard
   (enum ↔ registry membership reconciled — a mini AGT-15 cell).
- Allowed: `src/command_center/schemas/`,
  `src/command_center/agent_sessions/`, `configs/`, `tests/`.
- Forbidden: UI chrome (KAN-26's packet), model-picker changes, `.env`,
  adding Claude/Codex to any LiteLLM/chat-model surface.
- Validation: `make validate`, targeted pytest, `make lint`.

## 5. Open questions (Stage-4 gate)

1. Spec location: `configs/agent_sessions/*.yaml` (validated set) or
   per-board attachments in the board store?
2. Should the spec carry model *slugs* ever, or capability profiles only
   with resolution always live? (Recommendation: profiles only.)
3. Is the KAN-15 flagged boot-path consumer in scope for packet 1, or does
   packet 1 stop at schema + registry bridge?
4. Sequencing: AGT-16 before AGT-14 (policy refs need somewhere to live) or
   AGT-14 first (spec references existing policy docs)? Recommendation:
   AGT-16 schema first with a placeholder policy-ref field.

## 6. Model allocation

- Profile split: schema/contract design = **strategic_steward (Fable)** —
  this run-doc + schema shape review; implementation = **throughput, Sol
  writes**: `codex exec --sandbox workspace-write --full-auto -C <isolated
  worktree>`, effort **high** (bump to xhigh only if registry-bridge
  concurrency proves hairy).
- Resolved live 2026-07-23: `codex debug models` → **gpt-5.6-sol**
  (priority 1, lowest = current).
- Fallback: classifier-blocked write-mode → surface to operator; never a
  silent handoff.
- Independent review: Sol wrote → **Fable/Opus** read-only fresh session
  (contract semantics + the executor-vs-chat-model wall).

## 7. Links

- Master item: `docs/todos/GRAND_TODO_LIST.md` → AGT-16 (feeds KAN-26,
  KAN-15, AGT-10).
- Board/mission card: pending Stage-5 human approval — not created before
  that gate (the importer projects the AGT-16 card from the master list).
- Pattern doc: `docs/reviews/2026-07-23-omnigent-borrow-patterns.md`.
- Catalog row: `knowledge/research/source_catalog.yaml` →
  `omnigent-meta-harness`.
- Siblings: AGT-14 (policies referenced by the spec), AGT-15 (enum↔registry
  drift guard shares its reconciliation idea).
