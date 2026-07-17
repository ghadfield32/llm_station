# Phase 7 — Governed Mission Execution: Gate Design (FOR SIGN-OFF)

Status: **PLANNED — awaiting explicit human sign-off. No execution code is
built from this document.** Phase 7 is the only arc that writes real code into a
repository, so per CLAUDE.md ("never take destructive/irreversible actions
autonomously") it must be reviewed and approved before any mutation is wired.

This is the scope + gate design for review. It builds on machinery that already
exists and is tested; it does not restate it.

---

## 1. What already exists (the foundation)

- **`cc branch-mission`** (`src/command_center/cli/branch_mission.py`): the
  smallest safe repo-autonomy loop, already implemented and tested. It creates
  **one local feature branch in a temporary worktree**, makes **one docs-only
  change**, runs the repo's **declared validation commands**, and writes
  **redacted evidence**. It **never** pushes, opens a PR, merges, deploys,
  changes repo settings, or reads `.env`. It has an OS-env allowlist + a
  secret-name regex + a completion `verify_completion` + canonical events.
- **`cc mission-dryrun`** (`smoke_mission.py`): fake L0–L4 missions through the
  gates + judge, with no side effects.
- **Gate contracts** (`schemas/contracts.py`): `RiskTier` (L0–L4),
  `GatesConfig` forcing `requires_approval` on L3/L4, `SelfImprovementScan`
  with unrepresentable `forbidden_actions` (approve/promote/canary/merge/deploy/
  mark_verified), `KanbanBoardSpec` wall verbs.
- **Packet review chain** (Phase 6, deployed): advisory agent reviews +
  human-only approval + revision-bound staleness; `orchestrate_reviews` fills
  slots but can never approve/commit.
- **Board-change + work-item governance** (Phase 5, deployed): preview → commit
  → receipt → rollback, human-gated, double opt-in.
- **`secret_paths.is_secret_path`**: the one shared denylist (used by the
  OpenRouter egress wall, Home workspace, and attachments) — reused here.
- **`cc assistant-verify` + leaderboard** (Phases 8/9, deployed): the evidence
  producers/consumer that mission outcomes will feed.

**Phase 7 is therefore the extension of `branch-mission` from a docs-only change
to a bounded CODE change, plus the tail of the chain (frozen diff → independent
review → draft PR → human merge), with every zero-tolerance gate enforced
structurally.**

---

## 2. The execution state machine

Each transition is a gate; a mission can only advance when the gate passes, and
every transition emits a canonical event + a durable receipt.

```text
approved task (human)          ← the ONLY entry; from a committed WorkItem/packet
   │  gate: task is human-approved + has a Readiness Packet marked ready
   ▼
mission (L-tier assigned)      ← risk tier from the change surface; L3/L4 require approval
   │  gate: requires_approval satisfied for the tier (human)
   ▼
feature branch                 ← never main/protected; name derived from mission id
   │  gate: branch ∉ protected set; base is the intended SHA
   ▼
leased worktree                ← a temp worktree with a TTL lease; NOT the primary checkout
   │  gate: lease acquired; workspace path ≠ primary checkout root
   ▼
selected executor              ← EXPLICIT selection (Claude Code / Codex); auto-routing later
   │  gate: executor available (probe) + eligible for write mode
   ▼
bounded implementation         ← writes confined to the leased worktree only
   │  gate: every write path clamped inside the worktree; no secret paths; no .env
   ▼
declared tests                 ← the repo's declared validation commands only
   │  gate: commands come from the manifest, not agent-chosen; run in the worktree
   ▼
frozen diff / evidence         ← the diff is hashed + frozen; evidence redacted
   │  gate: diff digest recorded; no post-freeze mutation reviewed
   ▼
independent reviewer           ← a DIFFERENT executor reviews, READ-ONLY, advisory
   │  gate: reviewer ≠ implementer; review is advisory (cannot approve/merge)
   ▼
draft PR                       ← draft only, never a merge; links diff + evidence + reviews
   │  gate: PR is draft; no merge capability granted
   ▼
human merge (human)            ← the ONLY exit; a person merges
```

Two human bookends (approve the task, merge the PR) with an agent-run middle
that is structurally incapable of crossing either.

---

## 3. The six zero-tolerance gates and how each is ENFORCED (not asserted)

| # | Gate | Structural enforcement |
|---|------|------------------------|
| 1 | **primary-checkout writes = 0** | Every write path is clamped to the leased-worktree root with the same `_clamp` + `is_secret_path` teeth used by attachments/OpenRouter; a resolved path outside the worktree raises `GovernanceViolation` before any write. The primary checkout root is an explicit deny-root. |
| 2 | **protected-branch writes = 0** | The mission's branch is validated against a protected set (`main` + configured) at lease time; the worktree is checked out on the feature branch only; a push to a protected ref is not a capability the mission is granted (no push at all in the first slice). |
| 3 | **unleased writes = 0** | Writes require a live lease (TTL). On lease expiry the worktree is read-only; a write after expiry raises. The lease id is bound to the mission + recorded in every write receipt. |
| 4 | **agent merges = 0** | No merge verb exists in the mission vocabulary (mirrors the kanban `_WALL_ACTIONS` pattern). The tail emits a **draft** PR; merge is a separate human action outside the mission. The GitHub App has no merge-granting scope. |
| 5 | **secret leaks = 0** | `is_secret_path` denies `.env`/keys/credentials for reads AND writes; the OS-env allowlist + secret-name regex from `branch_mission` redact evidence; egress to any paid lane re-uses the external-egress ack wall. |
| 6 | **silent permission widening = 0** | Permissions are a typed, expiring lease with a fixed scope; there is no code path that broadens a lease in place. A wider scope requires a new human-approved mission. Every scope is recorded in the receipt + canonical event. |

Each gate gets an adversarial test (per §12 mission-execution matrix) that
constructs the violating input and asserts it raises before any side effect —
the same "assert `calls == []`" discipline used for the board-change wall.

---

## 4. Executor & trust model

- **Explicit executor selection first.** The operator picks Claude Code or Codex
  for the implementation; **auto-routing comes only after the leaderboard has
  enough repo-task-success evidence** (Phase 8) — never before.
- **OpenRouter stays read-only** for write missions until it independently
  passes the same gates (plan §7 "write execution"): no path escape, no secret
  access, no primary-checkout/protected-branch write, deterministic tests, cost
  cap, frozen diff, independent review, human activation. It is NOT eligible in
  the first slice.
- **The reviewer must differ from the implementer** (independence), and the
  review is **advisory** — it reuses the Phase 6 invariant: an agent review can
  never approve/merge; only a human merges.

---

## 5. Evidence, receipts, and the leaderboard loop

Every mission emits canonical events (`mission_promoted`, `worktree_leased`,
`diff_frozen`, `review_completed`, plus the existing vocabulary) and a durable
receipt. Mission outcomes become leaderboard evidence — appended to the same
`leaderboard-evidence.jsonl` `cc assistant-verify` already writes — filling the
currently-insufficient dimensions:

- `task_success` (did declared tests pass on the frozen diff),
- `latency` (wall-clock of the bounded implementation),
- `review_quality` (findings that a human upheld),
- `post_merge_defects` (defects attributed after a human merge).

So Phase 7 is also the producer that makes the leaderboard's hard dimensions
real — but only for missions a human approved and merged.

---

## 6. Proposed FIRST slice (the smallest safe extension) — pending your go

Build **exactly one** new capability, gated OFF by default (a third opt-in flag
on top of the existing autonomy switches), fully tested, no live push:

1. Extend the `branch-mission` loop to make a **bounded CODE change** (not just
   docs) in a leased worktree, confined by gates 1/2/3/5/6, running the repo's
   declared tests, producing a **frozen diff digest + redacted evidence**.
2. Add the **independent-reviewer** step (a different executor, read-only,
   advisory) over the frozen diff.
3. Stop at a **local draft-PR artifact** (a prepared branch + PR body on disk) —
   **no push, no PR creation, no merge** in the first slice. Pushing/PR-open is a
   later slice with its own sign-off once the local loop is proven.
4. Emit mission-outcome evidence to the leaderboard.

Everything is behind a `KANBAN_UI_MISSION_EXECUTION` (or equivalent) flag that
defaults OFF and fails closed, exactly like the board-change apply wall.

**Not in the first slice (each needs its own later sign-off):** live `git push`,
real PR creation via the GitHub App, auto-routing, OpenRouter write eligibility,
any home-workspace write.

---

## 7. Test matrix (acceptance gate for the first slice)

```text
worktree required                 (write refused without a live lease)
primary checkout unchanged        (write outside the worktree raises, no side effect)
protected branch unchanged        (feature-branch-only; protected ref never written)
permission expiry                 (write after lease TTL raises)
declared tests run                (only manifest-declared commands, in the worktree)
diff frozen                       (post-freeze mutation is rejected / re-review required)
independent reviewer read-only    (reviewer ≠ implementer; cannot approve/merge)
draft PR only                     (artifact is a draft; no merge capability exists)
secret denial                     (is_secret_path blocks read+write of .env/keys)
no silent widening                (lease scope is fixed; broadening requires a new mission)
fails closed                      (flag off ⇒ mission execution refused, 0 writes)
```

**Exit gate:** one real Kanban task completes the entire local loop
(approve → mission → branch → leased worktree → bounded code change → declared
tests → frozen diff → independent review → local draft-PR artifact) with the
primary checkout provably unchanged, and every zero-tolerance counter at 0.

---

## 8. Decisions I need from you before building anything

1. **First-slice scope** — is "local draft-PR artifact, no push/PR/merge" the
   right smallest step, or do you want the push/PR (via the GitHub App) included
   from the start? (I recommend local-only first.)
2. **Executor for the first mission** — Claude Code or Codex as the implementer?
   (The reviewer will be the other one.)
3. **Independent review before it's considered done** — same as the board-change
   wall, I'd run an independent adversarial review of the mission-execution gates
   before wiring; confirm you want that.
4. **Flag name + default** — confirm `KANBAN_UI_MISSION_EXECUTION=0` (off,
   fails closed) as the third opt-in.

No code is written until these are answered.
