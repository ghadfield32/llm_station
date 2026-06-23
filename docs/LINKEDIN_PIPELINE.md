# LinkedIn / Content Pipeline — living doc

The single place to see **what's built, what's blocked, and how to improve** the LinkedIn content
operation. Operational setup steps live in [linkedin-setup.md](linkedin-setup.md); the architecture
summary is [MASTER.md §6.6](MASTER.md). This doc is the working memory — update it as the system grows.

Last updated: 2026-06-22.

---

## 1. What this is

A content operation, run inside the existing self-hosted AppFlowy + LLM control plane, for two LinkedIn
identities:

- **geoffhadfield32** — personal *profile* (`author: member`). Voice: your data-science image.
- **World Model Sports LLC** — company *Page* (`author: organization`). Voice: basketball-science company.

One ordered, single-direction pipeline (idempotent by a stable per-row `Key`):

```
source material ─▶ draft (Claude/local) ─▶ In Queue ─▶ [you approve: drag to In Progress + ScheduledFor]
   ─▶ publisher posts at due time (official API) ─▶ Completed (+ PostURN)
```

The human drag from **In Queue → In Progress** is the only thing that authorizes a post; the agent never
self-approves. The publisher is mechanical (no LLM in the publish path).

---

## 2. Current status (the honest snapshot)

| Piece | State |
|---|---|
| Two AppFlowy content boards (3-col kanban) | **Done, live** — `geoffhadfield32_content`, `world_model_sports_content` |
| 60 seeded source-attributed drafts (In Queue) | **Done** — 30/account, from real repos/curriculum |
| Official-API publisher (`cc linkedin-publish`) | **Done, 9 tests** — dry-run/`--apply`/`--login`/`--orgs`/`--preflight` |
| Anti-double-post ledger + process lock | **Done** — `linkedin/ledger.py` |
| Hook+Body composition, token-expiry reminder | **Done** |
| **Personal posting (member)** | **READY NOW** — token valid → 2026-08-12, member URN cached |
| **WMS Page posting (organization)** | **BLOCKED** — needs Community Management API on a *separate* app (see §5) |
| Content engine (gather→draft→judge→stage) | **In progress** — Phase 1 (gather) underway |
| Content UX: preview + find-by-intent + routing seam | **Done** — `cc content-preview`, `cc content-find`, `cc reference`, `ContentLLMClient` (see §3.5) |

`cc linkedin-publish --preflight` prints the live readiness at any time.

---

## 3.5 Content UX — preview, find-by-intent, routing (make it usable, not just bigger)

The engine was too exact-name-dependent and shipped raw text. This makes a post
**reviewable before publish**, makes lookup work **by intent**, and makes model
routing **local-first with a clean seam**. None of it makes a live paid call.

### Preview a post the way LinkedIn shows it

```bash
cc content-preview --post "that glm router post" --device desktop   # resolve by intent
cc content-preview --post-id p_glm --device mobile                  # exact id
cc content-preview --author "Geoff Hadfield" --hook "..." --body "..."  # ad-hoc text
```

Emits all three forms (the **preview contract**): a terminal **markdown** preview,
a self-contained **LinkedIn-styled HTML** file (`generated/preview/<id>.html`,
inline CSS, opens offline — shows the desktop *and* mobile "…see more" fold), and
**copy-ready** export text. Every preview runs pre-publish **lints**: over the
3,000-char cap (a hard fail, exit 1), a weak hook that spills past the fold, a
missing question/CTA, and markdown LinkedIn renders literally. (`src/command_center/content/post_model.py`, `renderers/linkedin.py`.)

### Find things by meaning, not exact names

```bash
cc reference index --rebuild          # build data/reference/index.jsonl (+ embeddings)
cc content-find "the linkedin engine" # alias of: cc reference find "..."
cc reference find "fronteer router"   # misspelling still resolves
```

A cascade resolves the query — **exact id → alias → normalized → RapidFuzz
(misspellings) → BM25 keyword → local-embedding cosine** — and if the top two are
too close it returns the **top 3** instead of guessing. Curated entries live in
`configs/content_reference.yaml`; live posts are folded in at index time. The
semantic tier uses local `nomic-embed-text` via Ollama and **degrades to lexical
(with a note) if the model is down** — never a silent failure. **Invariant: no
user-facing command relies on exact names only.** (`content/reference_*.py`.)

### Routing seam — local-first, paid is gated

`ContentLLMClient` is one Protocol with four adapters: `LiteLLMContentClient`
(local default, free), `OllamaContentClient` (direct), `DryRunRouterClient`
(prices a paid route and **refuses** the live call), `TestContentClient`. Policies
live in `content_pipeline.yaml › content_llm`: `local_first` (Ollama, the only
default-on path), `cheap_external` (GLM-4.7-Flash), `frontier_external` (GLM-5.2,
escalation only). Paid policies are **metadata** — they carry a budget + require
redaction, and there is intentionally **no live external client** in this layer
(the cheap-external smoke test is operator-gated). GLM-5.2 is escalation, never
the post formatter. (`content/llm_client.py`.)

### Live boards — index, preview, and note REAL AppFlowy cards

The above resolves a curated config + a JSON store; this points the same engine at
the **live boards** so it fixes the day-to-day pain (find a library/book/note/post
without the exact name, view a real draft, update a note):

```bash
cc reference index --rebuild --live          # index EVERY database in databases.json
cc content-find "the basketball library"     # resolves a real `library` card
cc content-preview --post "glm router post" --live   # previews a real In-Queue card
cc content-note --card "standup note" --append "remember to push"        # dry-run
cc content-note --card "standup note" --append "remember to push" --apply
```

`--live` indexes every database (`library`, `papers`, `repos`, `signals`, `notes`,
`lessons`, the LinkedIn content boards, …) with `kind` derived from the database,
so a fuzzy/semantic query lands on a real card (`content/reference_live.py`).

**Updating a note is governed, never a raw board write.** `cc content-note`
resolves the card by intent, then records the note as a **`progress_comment`
kanban event** via `emit_event` — the single legal writer, which structurally
rejects wall actions (approve/merge/delete) and never sets a status. Dry-run by
default; `--apply` appends to `generated/kanban-events.jsonl`, and the existing
`cc kanban-reconcile --apply` writes it through to the board. So the agent can
annotate cards by intent without ever touching the human approval gate.

---

## 3. Architecture & components

### Boards (Growth OS / AppFlowy)
- Created from `content_template` in [config/schema.yaml](../appflowy_kanban/growth-os/config/schema.yaml)
  by [new_content_board.py](../appflowy_kanban/growth-os/scripts/new_content_board.py) (create + reconcile).
- Columns: **In Queue → In Progress → Completed**. Fields: `Hook` (primary), `Body`, `Status`,
  `ScheduledFor`, `Pillar`, `Format`, `Media`, `Source` (the data-derivation), `PostURN`, `PublishedAt`,
  `Notes`, `Key` (round-trips the writeback `pre_hash`).
- Seed/draft loader: [seed_content.py](../appflowy_kanban/growth-os/scripts/seed_content.py) (clobber-safe,
  insert-only) from `config/content_seed/*.json`.

### Publisher (command-center)
- [linkedin/client.py](../src/command_center/linkedin/client.py) — official LinkedIn API: 3-legged OAuth,
  `create_text_post(author_urn, text)` (member + org), `resolve_member_urn()`, `list_admined_orgs()`.
- [linkedin/ledger.py](../src/command_center/linkedin/ledger.py) — `PublishLedger` (durable PUBLISHING→
  PUBLISHED state, reconciles a failed writeback instead of reposting; ambiguous send → RECONCILE_REQUIRED,
  never auto-retried) + `ProcessLock` (OS advisory, no stale-timeout).
- [cli/linkedin_publish.py](../src/command_center/cli/linkedin_publish.py) — the operator surface; reads
  approved+due rows, posts, stamps Completed by `Key`. Flags: `--preflight` (readiness), `--login`
  [`--include-org`], `--orgs`, `--account`, `--apply`.
- Config: [configs/content.yaml](../configs/content.yaml) (`ContentConfig`) — accounts, statuses,
  official-API endpoints/version/scopes, `token_warn_days`. Secrets named-not-stored (live in `.env`).
- Runtime state (all gitignored): `generated/linkedin-token.json` (OAuth token — secret),
  `generated/linkedin-published.json` (ledger), `generated/linkedin-publish.lock`.

---

## 4. Safety / discipline invariants (do not regress these)

- **Human approval gate** — only `In Progress` rows publish; the agent cannot set that status.
- **No double-post** — durable ledger + process lock; never repost on an ambiguous/uncertain send.
- **Temporal safety** — a row publishes only when `ScheduledFor <= now`.
- **No fake values / no silent fallback** — failures stay In Progress and retry; media/non-text refused
  loudly; a row is never marked Completed without a real `PostURN`; every post traces to a `Source`.
- **No data leakage** — official API direct from this host; token store + ledger gitignored; no third-party
  scheduler; secrets only in `.env`.
- **Data-derived + least privilege** — endpoints/scopes/version/statuses are config; LinkedIn-Version has
  no code default; scopes are posting-only.
- **Single publish path** — `cc linkedin-publish` is the only publisher. No external posting MCP
  (`.mcp.json` is empty by design); `stickerdaniel` scraper can't post; future conversational control
  wraps *our* publisher, never an independent one.

---

## 5. LinkedIn app reality (the gotchas, learned the hard way)

- **LinkedIn has no native "schedule" API** — `POST /rest/posts` is immediate; *we* hold the queue.
- **LinkedIn-Version** is monthly `YYYYMM`, sunset ~12 months out. `202605` as of 2026-06; verify before
  going live ([recent-changes](https://learn.microsoft.com/linkedin/marketing/integrations/recent-changes)).
- **Personal posting** needs *Sign In with OpenID Connect* + *Share on LinkedIn* (both self-serve). ✅ done.
- **Company-Page posting needs TWO apps.** The **Community Management API** (which grants
  `w_organization_social`) **must be the ONLY product on its app** — it cannot coexist with OpenID /
  Share on LinkedIn. So: App A = personal (current), **App B = Community Management API only** for the WMS
  Page. App B requires Page verification + a **reviewed Dev-Tier form** (Standard within 12 months).
  This is why "Request access" errored on the current app. **Code support for two apps is Phase 3 (below).**
- **No refresh token** is issued to standard apps → ~60-day token, renew with `--login`. The tool warns
  `token_warn_days` (14) before expiry.
- **Fallback while App B is in review:** publish WMS posts by hand (board drafts them; WMS Page → *Start a
  post* → paste). Personal stays automated.

---

## 6. The content engine (gather → draft → multi-judge → stage)

Goal: continually gather the most interesting material in our field, turn it into simple **breakdown
posts** (what it is / why it's helpful / how I've used or would use it / how it helps), validate accuracy
+ currency with a **multi-judge panel from different viewpoints**, and surface the top ~5/account/week as
In Queue drafts. Status: **building (Phase 1).**

### Streams & sources
- **Personal:** external papers/repos (the Growth OS curator already scores ~421 papers / 64 repos / 175
  signals against the `sources.yaml` interest profile) + **your own developments** (git log + READMEs of
  llm_station / betts_basketball / bball_homography).
- **Business (WMS):** basketball science + applicable sports science (curator subset by pillar/topic) +
  **Idea cards** you drop on the WMS board (topic + direction → I expand) + worldmodelsports.com projects.

### Engine: tiered (best local → escalate advanced)
Mirrors the repo's cheap-first→cross-provider-escalate philosophy ([judgectl.py](../services/judge_gate/judgectl.py)):
- **Bulk (local):** gather-rank, first-draft, first-pass judging on local roles (`qwen3:30b`,
  `qwen3-coder:30b`, `devstral:24b` failover) via LiteLLM.
- **Advanced (escalate):** the **factual-accuracy & currency** viewpoint (needs live web) and any
  **contested** draft escalate to Claude Code / a Workflow judge panel. Aggregated with the existing
  `Jury` ([improvement/jury.py](../src/command_center/improvement/jury.py)) — majority + disagreement +
  Cohen's κ + bias controls.

### Judge viewpoints (all four, blocking)
factual accuracy & currency · technical correctness · brand/audience fit & voice · no overreach / no fake
metrics.

### Scale
~25 candidates/run, weekly; **top ~5 per account** surfaced as In Queue (with verdicts + evidence in
`Source`/`Notes`). Idempotent + clobber-safe.

### Build phases
1. **Foundation (in progress):** `content_pipeline.yaml` + contract; `growthos/content_sources.py` gather
   (curator DBs per stream + own-repo digest) → `generated/content-brief.json`.
2. **Draft + judge:** `growthos/content_draft.py` (local draft) + `growthos/content_judge.py` (4-viewpoint
   panel, escalate advanced) → stage top-5.
3. **Two-app LinkedIn:** split `LinkedInApi` into member app + `org_app`; publisher picks by author.
4. **Docs:** this file + MASTER + content-engine runbook.

---

## 7. Operating it (command reference)

```
cc linkedin-publish --preflight        # readiness + the next step (offline, no secrets)
cc linkedin-publish --login            # one-time OAuth (personal); add --include-org for App B
cc linkedin-publish --orgs             # list admined Page URNs (needs org scope)
cc linkedin-publish                     # dry-run: what's approved & due
cc linkedin-publish --account <board> --apply   # publish approved+due rows for one account
```

Daily loop: Claude Code drafts into **In Queue** → you edit/approve (drag to **In Progress**, set
`ScheduledFor`) → the scheduled publisher (Task Scheduler q15min, see [linkedin-setup.md §8](linkedin-setup.md))
posts and stamps **Completed**.

---

## 8. How to improve (roadmap & open ideas)

**Near-term (committed):**
- [ ] Finish the content engine Phases 1–2 (gather → draft → multi-judge → stage top-5).
- [ ] Two-app support (Phase 3) so WMS Page posting works once App B is approved.
- [ ] `Idea` status on the WMS board (live select-option add) for topic intake.

**Backlog / ideas:**
- [ ] **Image/carousel posting** — the publisher refuses non-text today. Wire LinkedIn's image/document
  Assets API (`registerUpload` → PUT bytes → reference) and a real `Media` flow.
- [ ] **Engagement feedback loop** — pull post performance (impressions/reactions) and feed it into the
  ranking so the engine learns what resonates (data-derived, like the improvement-scan acceptance model).
- [ ] **Refresh-token / longer sessions** — if you enroll the app for programmatic refresh tokens, add
  auto-refresh so re-`--login` isn't a 60-day chore.
- [ ] **A thin MCP over our own publisher** — conversational "draft & post" without a second publish path.
- [ ] **De-dup against posted history** — a triage step (like `discovery/triage.py`) so the engine never
  re-proposes a topic already shipped or human-rejected.
- [ ] **Version self-check** — warn when `linkedin.version` is within ~30 days of LinkedIn's sunset.
- [ ] **Per-card visibility** — `visibility` is currently hardcoded `PUBLIC`; make it a board field if
  connections-only posts are ever wanted.
- [ ] **Cross-posting / other channels** — the draft+judge engine is channel-agnostic; could feed X/blog.

**Guardrails to preserve when improving:** the §4 invariants. Any new automation keeps the human approval
gate and the no-fake-values / no-leak / single-path rules.

---

## 9. Pointers
- Setup runbook (go-live, two-app, token renewal): [linkedin-setup.md](linkedin-setup.md)
- Architecture in the system guide: [MASTER.md §6.6](MASTER.md)
- Memory: `linkedin-content-pipeline.md` (cross-session summary)
- Tests: [tests/test_linkedin_publish.py](../tests/test_linkedin_publish.py)
