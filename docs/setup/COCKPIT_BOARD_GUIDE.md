# Cockpit Board Guide

The cockpit now treats **Kanban Boards** as the primary operator surface.

- **Kanban Boards** is the typed domain view. Use this for day-to-day work because
  each board has the right card shape, fields, progress drawer, and chat
  handoff.
- **Missions** lives inside Kanban Boards as a Ledger-backed board. The old
  top-level Missions view remains URL-addressable for debugging, but it is not
  the primary mobile nav.
- **Workspace boards** are first-party local state. The top-level Kanban Boards view is
  a debugging view over the same governed store, not a second source of truth.

## Sections

| Section | Use it for | Source today | How to add/update |
| --- | --- | --- | --- |
| Betts Grand TODO — Source Tracker | Complete Betts Basketball master tracker, including raw Idea Bank and source history | `betts_basketball_grand_todo` board store; canonical source remains `betts_basketball/docs/backend/projects/GRAND_TODO_LIST.md` | Preview with `uv run cc grand-todo-import`; merge with `uv run cc grand-todo-import --apply` |
| General Todos | Durable personal and cross-project tasks created from Capture or chat | `personal_todos` board store projected from the canonical Work Graph | Use **Prepare now**, **Route TODOs**, or the routing wizard and choose **General Todos** |
| Jobs | Job search pipeline, resumes, application memory, manual checklist | `job_search_pipeline_internal` board store | `uv run cc job-search suggest --from-file <posting.md> --write`, then `uv run cc job-search publish-suggestions --apply --backend internal` |
| Posts | LinkedIn/content composition, review, and scheduling | `linkedin_content_pipeline_internal` board store | Compose in the cockpit; scheduling moves the card to `Scheduled` for explicit publishing |
| Books | Reading list, details, and ordered notes | `reading_library` board store | Add/edit in the Books library desk; historical bulk recovery uses the audited AppFlowy importer |
| Papers | Research queue and implementation-oriented paper notes | `research_papers` board store | Use **Shared research setup** to add readable topic chips, choose arXiv areas, tune the pull, and save + refresh |
| Repos | Research repositories and implementation-oriented evaluation notes | `research_repos` board store | Use **Shared research setup** to add readable topic chips, tune recency/stars, and save + refresh |
| DAGs | Scheduled jobs and automation health | `dag_operations` board store | Historical AppFlowy rows were migrated; `growthos-watcher` refreshes live Airflow state hourly |
| Self Improvement | Ranked opportunities discovered across registered boards and control-plane signals | `self_improvement` board store | `self_improvement_daily` drafts the top evidence-backed findings as human-gated Backlog cards |
| Missions | Ledger mission execution | Ledger | Created by agent workflows; approve/kill stays in the signed Ledger UI |

Self Improvement reads the validated repository catalog from
`configs/autonomy.yaml`, independently of whether cockpit chat is enabled. Its top
bar creates one tab per `repo_manifests` entry and refreshes that catalog with the
rest of the cockpit, so registering a repository automatically adds its tab. The
selected repository displays why it is checked and its declared research
capabilities. KPIs summarize shown, backlog, active/review, blocked, and average
score; the adjacent dropdown filters by text, status, pillar, risk, source, and
minimum score. The daily DAG uses the same manifest to create one isolated
code-health scan per repository and preserves repository attribution on every
drafted card.

The remaining fixture-backed sections are intentionally visible so their UI shape
is testable before a real pipeline is wired. Papers, Repos, DAGs, Books, and Posts
are now real `board_store` domains: `0` means their board directory/event fold is
empty. The 2026-07-15 audited recovery migrated 1,922 authoritative AppFlowy
rows into these stores (1,351 Papers, 89 Repos, 118 DAGs, 283 Books, and 81
Posts). AppFlowy is historical recovery input, not the live board. Exact source
cells, row/database IDs, hashes, and revisions remain attached to every card.
See `docs/operations/APPFLOWY_FIRST_PARTY_MIGRATION.md`.

## What each Kanban pulls in

Every active board exposes the same collapsible **What this Kanban pulls in**
panel above its filters and lanes. The panel is the readable intake contract:
producer ID, mode, schedule, source references, inclusion instructions, and
typed parameters. It deliberately separates the producer from the board store;
changing what enters Papers does not change where Paper cards are stored.

For editable producers, **Adjust intake** edits only the declared instructions
and parameter values. List inputs use a creatable select: type or select a
value and it becomes a removable chip, without hand-editing YAML. Saving uses an
optimistic revision: a stale browser receives a conflict and writes nothing.
Producer ID, mode, schedule, source references, and editability remain
registry-owned so an in-board edit cannot silently disconnect an automation or
claim to change a cadence that is actually wired in Compose/a scheduler.

`configs/domain_surfaces.yaml` is the canonical contract. Growth OS resolves
the Papers and Repos parameters from that file on every curator run and fails
closed if the mounted config is absent, duplicated in
`growth_os/config/sources.yaml`, or has an invalid shape. Specialized
read-only producers still show their complete contract and exact source
references. Manual boards expose an `instructions` input. Boards created with
**New kanban** receive the standard `universal_intake` event input
automatically; custom domain
schemas that omit intake receive the same typed default.

Papers and Repos share a specialized setup at the top of either board. Its
readable research-topic chips are the single user-facing input for both sources;
raw arXiv `all:` expressions and GitHub qualifiers are compiled only inside the
source adapters. Each topic is also a selectable sub-board that projects the
same governed cards and lanes, so moving a card in one topic view updates the
one canonical card. Paper-only arXiv areas and per-source limits remain separate.

**Save and refresh** atomically validates and saves both source settings, then
places a durable request in `growth_os/_state/research_refresh.json`. The
Growth OS watcher checks that request every five seconds, takes the required
backup, pulls new source results, and processes bounded detail batches until no
titled card is missing complete analysis. The panel reports exact complete and
pending counts. A missing or invalid local model marks the request **blocked**
with an actionable message; **Refresh both now** retries explicitly.

## Papers and Repos research detail

Paper and repository cards now require a visible canonical `title`. Fresh
Growth OS writes map source `Title`/`Name` fields to that canonical field.
For migrated cards created before that mapping, the API recovers the exact
retained AppFlowy `Title` or `Name` for display before bulk provenance is
redacted. It labels the result `title_integrity=recovered_from_source` and does
not rewrite the store. If neither canonical nor source title exists, the card
shows a visible unavailable-title warning instead of a blank heading. Rerunning
the audited importer is the durable repair path.

The research drawer distinguishes two evidence classes:

- Source-derived metadata: title, authors/owner, abstract/description, paper or
  repository URL, topics, stars, language, published/updated/pushed date,
  arXiv category/DOI/journal/author notes, GitHub license/default branch/forks/
  open issues/archive state, code links, and related links.
- Local-model analysis: **How this could help us**, pros, cons, key
  implementation details, and implementation notes, plus explicit analysis
  status, model, timestamp, input SHA-256, origin, and error code in the drawer
  and storage.

Source adapters discover code/related links; the model is explicitly forbidden
from inventing links, benchmarks, results, dependencies, or repository
contents. If local enrichment is unavailable or invalid, the card still lands
with source metadata and a loud `unavailable` or `failed` analysis status.
An analysis is counted complete only when usefulness, pros, cons, key details,
and implementation notes are all populated. Existing cards—including cards
whose exact title is retained only in migration provenance—are processed by the
durable board refresh. An operator can still run one bounded batch manually:

```powershell
docker compose --profile ui run --rm growthos-watcher python -m growthos.curate --reanalyze papers --limit 25
docker compose --profile ui run --rm growthos-watcher python -m growthos.curate --reanalyze repos --limit 25
```

Open a Paper or Repo card and use **Use this in one of our repos** to choose a
registered repository. **Prepare implementation handoff** opens a read-only
Codex agent session pinned to that repo with the complete source-backed card.
The requested packet covers fit, pros/cons, prerequisites, smallest experiment,
likely files, KPIs, risks, rollback, and unknowns. This action does not edit the
repository, create a mission, or claim implementation. Tracking or authorizing
implementation remains an explicit follow-up after review.

## Books library desk

The Books board shows the stored book title as its primary heading, followed by
author, priority, genre, collection details, current reading position, and the
latest real note. Reading progress is shown only when an explicit percentage is
stored or when it can be calculated exactly from current page and total pages;
an unset position is never presented as progress. When a historical row has not
received its canonical `title` repair yet, the API projects only the exact retained
AppFlowy `Title` or `Name` value and labels it
`title_integrity=recovered_from_source`; this read-time projection does not
rewrite the board store. A visible missing-title warning therefore means neither
canonical nor governed source title exists. The UI never derives a title from a
card ID, author, or other unrelated field. The seven genuinely blank source rows
remain selectable by card ID and editable.

Expand the optional **Library desk — Add a book or reading note** disclosure
above the board, then choose **+ Add book** for a new record. Title and starting
lane are required; author, details, priority, genre, format/source label,
collection/module, section, estimated hours, ISBN, starting reading position,
and an existing-notes overview are optional and remain editable in the card
drawer. Genre is an explicit editable field: the historical `type` values are
retained as source labels and are not reclassified or guessed. Duplicate
title+author pairs are compared after
Unicode and whitespace normalization across canonical and exact retained source
titles in active and archived books, so retries cannot silently create a second
record.

Use **+ Add note** in the expanded Library desk or **Add a note** in the drawer.
The top desk includes a title/author/genre/collection lookup before its book
dropdown. Enter an explicit author plus note text, and optionally record chapter,
page, total pages, and progress. Submitted note context is stored on the
immutable ordered note and advances the card's current reading position in the
same board-locked write; omitted context leaves the position unchanged. Each
note receives an immutable ID, timestamp, and next sequence number, then appears
inside the card in insertion order. Existing imported overview notes remain
visible separately. Malformed stored note history or impossible page/total
values block the append and report the exact contract error without reordering,
replacing, or partially updating anything.

The **Library filters** shelf appears before the optional entry desk and searches
title, author, details, ISBN, collection, current chapter, imported overview
notes, and every ordered note. Space-separated keywords may match across
different fields. Counted dropdowns cover every meaningful categorical grouping:
status, priority, author, explicit genre, collection/module, section, and
format/source label. Each stored grouping also exposes **Not set**, which finds
metadata gaps without inventing a replacement value. Notes and reading-position
state remain separate filters.

Paired sliders bound estimated reading hours and exact reading progress. Books
without the selected numeric value remain visible until that range is activated,
then are excluded explicitly. Any registered grouping plus title, status, length,
progress, or note count can be sorted ascending or descending. Open a card to
search within that book's notes or use **Reading position** to update chapter,
page, total pages, and progress without opening the full metadata editor.

Book creation holds the board lock through its first governed status event and
rolls back the new field document if that append fails. Moves and archive also
read, validate, and append under one board lock, so two simultaneous requests
cannot both act on an obsolete lane. A one-book move reads the target event fold
and field document under that lock; it does not load every book field file.
After the server commits, the board and open drawer replace only the returned
card. This is a committed-response update, not optimistic UI, and it does not
refresh Papers or unrelated boards. Background job preparation remains
domain-scoped. A pre-fix card with no status is shown as unstaged and may enter
only **To read**; no status is inferred automatically.

**Done** is a governed `finish_todo` move; completed books may be moved back to
Reading. **Remove book** is intentionally archive-only: every field, ordered
note, provenance value, and history event is retained in the visible Archived
lane. **Restore to To read** reverses it. There is no hard-delete book endpoint.
All book mutations require full-console write mode.

## Betts GRAND TODO synchronization and archive safety

The source Markdown remains canonical. Board reads and the 15-second on-screen
refresh are read-only: they report whether the stored projection is current,
stale, not imported, or has an unavailable source. Use **Sync canonical source**
for an explicit full-console reconciliation. Cockpit task edits and moves
atomically update the Markdown first, then reconcile the board.
Tracked IDs become stable cards; the unnumbered Idea Bank is retained as one exact
card, and a metadata card retains the complete source snapshot. Reruns append exact
source revisions and preserve manual fields. A tracked item may be edited or
moved to the listable `Archived` lane; Archive changes only its badge and keeps
the complete task block. `Archived -> Backlog` restores it.

The Idea Bank and full-source metadata cards are read-only. If a stable tracked
ID disappears, synchronization blocks before every write; it does not infer
deletion or mass-archive a truncated file. Divergent simultaneous source and
board changes append a conflict record and choose neither side. Source locks are
always acquired before board locks. A killed same-host writer is recovered only
after its PID is proven dead; unknown-host locks remain blocked. Live contention
returns HTTP 423 with `Retry-After: 2` and changes no card.

Docker Desktop does not make Linux flock and Windows msvcrt locks interoperable
across bind mounts, so an aged foreign lock is never guessed stale. Compose
grants the cockpit 90 seconds and the signal-aware watcher 300 seconds to finish
active writes during replacement. After a hard container kill, stop both
agent-kanban-ui and
growthos-watcher, verify they are stopped, inspect the exact lock-file owner
metadata, and remove only the confirmed transient lock artifacts before
restart. Never remove board JSON, the event log, source Markdown, or revisions.

`uv run cc grand-todo-import` is a no-write preview;
`uv run cc grand-todo-import --apply --expected-items 148` reconciles manually.

## Ongoing board upkeep

`growthos-watcher` runs the real curator and Airflow synchronizer hourly, then
brief/guidelines/retention after 06:00. It uses the same board/event locks as the
cockpit. Failures are not swallowed: each task outcome is atomically written to
`growth_os/_state/watcher_status.json`, failed daily tasks retry next hour, and
`GET /api/upkeep/status` exposes the current record.

Every upkeep cycle and both daily mutation DAGs are blocked until the current
canonical source watermark has an immutable verified backup. The local default
is retained forever with no automatic deletes; use an encrypted external/off-host
`KANBAN_BACKUP_HOST_PATH` for disk-loss protection. Creation, verification, and
staging-only restore procedures are in
`docs/operations/KANBAN_DATA_RECOVERY.md`.

## Master TODO List, repository sections, story ledger, assignment, and archived boards

**Master TODO List** is the completeness-reporting index across canonical WorkItems,
unconverted task-like captures, and direct/imported generic board cards. It folds
duplicate projections instead of dropping source records. Every row exposes its
stored type, stored canonical/source status when recorded, provenance, all Kanban links,
and **Unassigned** when no destination exists. Search plus type/status/source/
assignment/Kanban filters are evaluated by the backend. A source failure produces
a visible **PARTIAL INVENTORY** banner with a safe source/code/message; detailed
provider exceptions stay in protected server logs, and the UI never renders a false
empty board.

Stored capture links and Work Graph projections are validated against the exact
WorkItem inventory before a source is folded away. A malformed or dangling link keeps
the raw/source row visible and marks the inventory partial with the exact unavailable
reference; it is never counted as a complete deduplication.

The list reads repository ownership only from validated
`configs/kanban_boards.yaml` `repo_ids` and the registered manifests in
`configs/autonomy.yaml`. It renders one section for every registered repository,
including an explicit zero-result section after filtering. Multi-repository work
appears once under **Shared repositories**; personal, life, and unassigned work
appears once under **General & unassigned**. An unknown repository reference
blocks the API with the exact invalid mapping instead of guessing ownership.
Each filtered row therefore appears in exactly one section.

Open a row title to see its **TODO story**. The drawer keeps the four authorities
separate instead of flattening them:

- **Inbox / Capture** owns immutable original wording and its append-only intake
  events. The drawer renders that source read-only.
- **Work Graph** owns each permanent WorkItem ID, its editable organized
  description, canonical status, placements, relationships, and work events. A
  capture can link to zero, one, or many WorkItems; the UI never silently chooses
  one when the stored relationship is plural.
- **Master TODO List** is the comprehensive user-facing ledger. It records whether
  the requested `capture:` or `card:` identity is still emitted, not materialized,
  or folded into exact `work:` rows without creating a duplicate task.
- **Kanban Boards** are execution/organization projections. Active and removed
  placements remain in the story. Board events appear only when storage provides
  an exact board ID and card ID; a generated projection card ID is never treated as
  historical evidence.

The same detail includes exact source-card/repository attribution, active and
removed dependencies/children, routing classifications and human corrections,
linked conversations/captures, Betts source revisions and sync conflicts,
explicitly linked mission verdict/evidence records, and reversible archive events.
Mission evidence is read from the Ledger's stored
`mission.verification` and `mission.completion_verdict` events. A completion
verdict is accepted only when its status/evidence structure matches that durable
contract; a substitute row property or unprefixed event name is not treated as
evidence.
Unavailable or malformed optional authorities produce a visible **PARTIAL STORY**
entry; the response never fills missing history with the current time, a title
match, a repository match, or an empty placeholder presented as fact.

Editing the organized description uses an atomic compare-and-swap on the
WorkItem: the description and `description_edited` event commit together. A stale
writer receives 409 and must refresh; an identical retry reuses the committed
result. This endpoint cannot update Capture raw text, source-card text, Betts
Markdown, a board placement, or mission evidence. TODO, Capture, Inbox, WorkItem,
Work Edge, Work Graph, and work-permalink success/error responses are
`Cache-Control: no-store`.

The 148 stable Betts Grand TODO — Source Tracker tasks appear in the
`betts_basketball` section.
This is a read projection, not a migration: the canonical Markdown, exact Idea
Bank, full-source snapshot, revision history, synchronization controls, task
editing, and reversible archive behavior remain on the governed Betts Grand TODO
board described above.

Use **Assign / add kanban** to add a projection to a validated existing generic
board or create a standard governed board from a broad topic. Capture and direct
board sources remain intact. When no canonical WorkItem exists, the form requires the
operator to confirm the permanent title, organized description, and kind. The backend
will not promote a capture's first line/raw text or a card ID/notes into missing
canonical fields.

Source validation covers `work:`, `capture:`, and `card:` identities before a
new-board configuration transaction starts. A generated Work Graph card resolves back
to its stored `work_item_id`; assigning that projection can only add a placement to the
same WorkItem. Missing, ambiguous, malformed, or divergent source history returns
404/409 without creating a board, WorkItem, or placement. Exact retries reuse the same
identity, and an imported direct card retains its exact source link.

Canonical WorkItem creation commits its `created` event in one store transaction.
Placement creation/removal commits active-primary state and its placement event in one
transaction, backed by SQLite partial unique indexes. Blocking/structural cycle checks
and edge/event insertion share the same `BEGIN IMMEDIATE` transaction. The Ledger
refuses eventless WorkItem, placement, edge, and field-update writes. A legacy repair
reconciles the exact active placement, canonical primary, and missing event together;
an old removal retry cannot clear a newer primary on another domain of the same board.

Duplicate resolution validates the complete chosen operation first, allocates any new
WorkItem IDs, then records an exact capture `operation_key` and those IDs before child,
project, placement, edge, occurrence, or expansion mutations. An interrupted exact
retry rolls forward the recorded IDs and source-keyed events. Changed canonical fields,
members, deltas, destination inputs, or resolution return 409 without duplicating work.
The operation key is audit metadata, not a conversation ID. The chat and duplicate
forms keep immutable raw wording visible and require explicit confirmation of permanent
canonical child/project/title/description/kind fields.

Duplicate resolution uses the same serialized capture-link preflight. Any pending,
mixed, malformed, routed, or archived link history blocks Work Graph mutation first.
Resolutions that create a child or project require explicitly confirmed canonical
title, organized description, and kind; capture raw text and extracted deltas remain
source evidence and are never promoted into missing canonical fields.

Board removal in Controls is archive-only. Archiving keeps the schema, cards,
source provenance, revisions, and event history, makes the surface read-only,
removes it from routing choices, and places it in the listable **Archived boards**
section. **Restore** explicitly returns it to active routing. No cockpit board
endpoint hard-deletes a domain schema. The TODO story's reversible-history view
includes both sides of each recorded transition: archive/reject and later status
restoration, plus placement/relationship add-remove events.

The **Kanban maintenance review** detects deterministic evidence such as duplicate
normalized titles, identical/subset WorkItem membership, and empty generic boards.
Protected personal/Grand boards and already archived boards are never candidates.
Reject records the exact evidence decision; accepting creates one idempotent
maintenance TODO on General Todos. It never automatically merges, moves, archives,
or deletes boards. Changed evidence receives a new stable suggestion ID, so a
prior rejection is respected without suppressing genuinely new conditions.

## Route chat TODOs into a board

The cockpit can turn a pasted checklist or a chat message into durable,
connected work without asking a model to mutate a board directly.

1. Paste the list into Gateway chat and choose **Route TODOs**, or use
   **Route as TODOs** on an existing user/assistant message.
2. Review the deterministic split. Each item shows its inferred kind,
   evidence-backed board suggestion, exact-title duplicate warning, and board
   selector.
3. Choose **General Todos** for the durable personal task board, pick another compatible
   existing generic-task board, or choose
   **Create a new board**; this creates the governed board and surface with the
   standard governed lanes, including explicit unblock, reopen, and
   reject/restore paths. **Awaiting Approval** remains a human-owned wall.
4. Resolve every duplicate/dependency question and choose **Confirm & create**.
   Unresolved items cannot be silently committed.
5. Follow the backend-generated receipt links to the board or Work Map.

Examples covered by the hermetic routing suite:

| TODO text | Result |
| --- | --- |
| `research feasibility study for player health` | Suggests the Research Queue after prior human corrections provide that evidence. |
| `write linkedin post about the findings` | Suggests the Content Queue after prior corrections; it does not route merely because it says “post.” |
| `replace furnace filter` | With no learned match, asks which compatible board to use. |
| `confirm footage rights before implementation` | Raises a dependency question and creates no invented edge. |
| An exact existing title | Requires **Reuse existing work** or **Create separate work**; it is never dropped or duplicated automatically. |
| `investigate biomechanics evidence` + `draft newsletter campaign` + `schedule furnace maintenance` | A reviewed mixed chat list can route one item each to Research Queue, Content Studio, and Home Care; each becomes its own durable capture-backed WorkItem. |
| `prepare a biomechanics newsletter` | If evidence matches both Research and Content, the wizard offers only those two matched boards and requires a human choice. |
| A topic the operator repeatedly overrides | Later proposals immediately use the newer correction evidence without restarting the cockpit; every proposal still remains reviewable. |
| A TODO projected onto Home Projects and Quarterly Planning | Both cards display the same canonical status; moving either projection updates both on their next read. |

New-board examples in the integration suite include **Home Maintenance**,
**Learning Lab**, **Launch Plan 2027**, **Fitness Plan**, **Travel Plans**, and
**Finance Ops**. Each begins empty, receives the standard governed lanes and
fixed delete/approval wall, and appears in the destination selector before its
first card exists. If no existing destination fits, **New kanban** remains next
to the board selector throughout review.

The wizard saves each chat TODO as its own durable capture, then converts those
captures sequentially, never in parallel. Each successful item keeps its
receipt; on a later failure the remaining items stop and are not automatically
retried. **Repair / create remaining** reuses the saved capture ID, repairs any
missing placement, and cannot create a second WorkItem for that TODO.

Capture mode is provenance-preserving. **Prepare now** saves the complete raw
capture, opens a stable `capture:<id>` chat, and presents explicit choices for
**General Todos**, a compatible existing kanban, or a new kanban; it creates no work
until the routing review is confirmed. Repeating Prepare now reopens the same
conversation and does not duplicate its prepare event. **Create a task** first
saves the immutable capture, then opens the same routing review. With **bulk list**
enabled, each bullet is an independent capture and is converted one at a time.
Conversion apply accepts exactly one item and no edges per capture; a connected
multi-item plan must first be split into independent captures and reviewed.
Retrying an interrupted conversion repairs the capture→WorkItem link by
`capture_id` and does not create another WorkItem.

Only validated `board_store` + `generic_task` boards with a unique reversible
status mapping are offered. The source-managed Grand TODO and specialized
Jobs/Posts/Papers/Repos/DAGs are deliberately excluded from generic projection.
The canonical WorkItem remains in the Ledger; compatible board cards are live
placements, not copied task records. The active compatible board refreshes
every 15 seconds after the prior refresh completes, and every read recomputes
from the current Work Graph.

Full-console Compose enables both `KANBAN_UI_CAPTURE_LEDGER=1` and
`KANBAN_UI_WORKGRAPH_LEDGER=1`. A write-capable console refuses canonical
work writes without durable Work Graph backing.

Board creation is protected by one cross-process config lock and an intent
journal spanning `kanban_boards.yaml` and `domain_surfaces.yaml`. A graceful
stop releases the lock; the next read reconciles an interrupted config pair.
After a Docker hard kill, first stop the cockpit and every config writer, inspect
`configs/.locks/board-module-config.write.lock`, and remove that exact transient
lock only after confirming its recorded owner is dead. Never remove either YAML
config or the transaction journal. The next read then completes the exact
validated pair, abandons an untouched intent, or fails closed on unrelated
divergence; it never guesses or deletes a board. The journal is crash-recovery
coordination, not a claim of storage-device power-loss atomicity.

## Jobs Flow

Jobs are prepare/manual-first:

1. `Suggested Jobs`: ranked jobs from a daily DAG or pasted posting.
2. `Selected by Geoff`: Geoff has approved spending time on it.
3. `In Progress`: material generation can run.
4. `Needs Geoff`: resume, cover letter, answer bank, checklist, and follow-up
   memory are ready; Geoff must review and submit manually where required.
5. `Completed`: Geoff confirms a real submission by dragging the card here.
6. `Interviewing`: recruiter/hiring-manager process is active.
7. `Rejected / Skip`: not pursuing or rejected.
8. `Closed / Archived`: stale/final outcome after retention.

The processor accepts either `Selected by Geoff` cards or `In Progress` cards
that do not yet have `application_id`/`materials_path`. This lets a cockpit drag
to `In Progress` act as the approval signal without losing the material
generation step. Already prepared `In Progress` cards are ignored so reruns do
not duplicate applications.

The Jobs header shows queue chips for `Bot Possible`, `Manual Required`, and
`Prepare Only`. Click a chip, or use the `any automation` dropdown, to split
the board into the bot-preparable and Geoff/manual queues. The daily publish
target is 50 surfaced cards: up to 25 bot-possible and up to 25 manual-required,
with the remaining slots filled by score-ranked jobs only when one side has too
few eligible postings.

Daily limits and role focus can be adjusted from **Controls -> Job Search**.
Those edits write to `data/job_search/profile/search_settings.yml`; the shared
job-search config loader merges that override with `configs/job_search.yaml`, so
CLI and DAG runs see the same effective settings.

Company watchlists and the rich-record retention window are adjusted in the
same panel. Company groups are explicit search inputs, not a background web
monitor. Public-API company searches are deduplicated and rotate through a
polite 24-query daily budget, so a large watchlist is covered over successive
runs without one rate limit discarding the rest of the run. The retention
window is 30 days by default (1–365 days configurable).
Only a note explicitly marked **This communication furthers the process**
refreshes it. The minimal applied-job outcome row is retained; the control marks
submitted rich records eligible for compaction and does not silently delete
their files. Prepared-but-never-submitted packets do not enter that outcomes DB.

Desktop: drag cards between lanes. Mobile: use each card's `Move to...` menu;
it calls the same governed move endpoint as drag/drop.

### Page-by-page application companion

Open a prepared job card and choose **work page-by-page in chat**. The scoped
chat includes the real card and application provenance and asks for one visible
portal page at a time. Paste only the non-secret fields and questions currently
shown; the cockpit does not co-browse, type into, or submit the employer site.
Never paste passwords, one-time codes, MFA prompts, CAPTCHA contents, or secret
tokens. Self-identification, disability, veteran, work-authorization/legal, and
other protected questions stop for operator review rather than being guessed.

### Packet review (Needs Geoff)

Open a prepared card's drawer and press **review packet**. The modal shows the
complete application across tabs — Resume, Cover Letter, Answers, Recruiter
Msg, Follow-ups, Checklist, Job Description — plus:

- **Agent Trace**: the exact prompts (full achievement bank + job description +
  your notes) and raw model outputs behind every generation, with timing and
  claim ids. Materials are agent-written via LiteLLM by default; if the model
  was unreachable the packet says `template_fallback` and the trace shows why.
- **Validation**: the submit gate. Errors (missing files, unresolved change
  requests, invalid claim ids, already submitted) block submission; warnings
  (template-mode materials) are shown but do not block.
- **Request changes & regenerate**: type what is wrong ("lead with the NBA
  work") — the note is recorded in `review_notes.md`, the agent rewrites the
  materials against ALL accumulated notes, and the revision counter bumps.
- **I submitted externally — record it**: after you submit on the employer
  portal, this runs validation, records the application as applied, moves the
  card to `Completed` through the same governed event as a drag, writes
  `submission_record.json` evidence, and emails you the full record (resume,
  cover letter, answers, job description attached). Dragging to `Completed`
  runs the identical gate — an invalid packet is refused before any event is
  logged.

Email records always land on disk as `submission_email.html`. Real delivery
needs `DISCOVERY_SMTP_HOST/USER/PASSWORD/FROM` and `JOB_SEARCH_EMAIL_TO` (or
`DISCOVERY_SMTP_TO`) in `.env`; the Overview tab names exactly which are
missing. CLI equivalents: `cc job-search packet <id> [--trace]`,
`cc job-search request-changes <id> --notes "..."`, `cc job-search finalize <id>`.

## Controls

Use **Controls** for operator settings:

| Panel | What it shows/edits |
| --- | --- |
| Runtime APIs | Ledger, LiteLLM, board store, GatewayCore, and the action/chat endpoints |
| Kanban Boards | Add/remove/update `configs/domain_surfaces.yaml` domain boards; view `configs/kanban_boards.yaml` provider registry |
| Job Search | Daily search limits, company watchlists, retention, role-focus keywords, local relationship/question memory, profile file paths, and draft application defaults |

`configs/domain_surfaces.yaml` controls the visible Kanban Boards sections, card
components, data source, columns, column actions, summary fields, drawer fields,
and empty states. Controls -> Kanban Boards edits that file in full-console mode
and validates the whole document with `DomainSurfacesConfig` before saving.
Provider-backed board wiring still belongs in `configs/kanban_boards.yaml`, so a
new `board_store` domain needs a matching provider registry entry.

## Applying

The MVP does **not** auto-submit applications. It prepares the packet and records
why Geoff is needed:

- `application.yml`: status, stage, salary, portal, manual blockers.
- `generated_resume.md`: tailored resume.
- `cover_letter.md`: draft cover letter.
- `answer_bank.md`: default answers and evidence-backed claims.
- `manual_checklist.md`: exact manual steps/blockers.
- `followups.md`: ready follow-up context.
- `communications.jsonl` and `recruiter_notes.md`: recruiter/hiring-manager
  notes during the process.

Run Codex-backed preparation with:

```powershell
uv run cc job-search process-selected --apply --backend internal --executor codex
```

The executor choice is recorded in `executor.json`. It does not change the
submit policy, claim validation, or manual blockers.

After Geoff manually submits, drag the job card to `Completed`. The cockpit
updates the application record, applied date, retention window, and follow-up
pack from the card's `application_id`.

To add notes from a recruiter call or email, open the job card and use
`Next-Step Notes`. Check the furthering-process box only when that communication
actually advances the process. Saving a `portal question` note and adding the
same non-sensitive question to the reusable question library are two separate
buttons: a failure in either one never pretends the other succeeded. Candidate
answers stay scoped to the recorded job type and inert until you explicitly
review and save one as a Standing Answer.

Known LinkedIn relationships are operator-entered private records. Job outreach
matches only an exact normalized company name, produces unsent draft-only
messages without private notes, and offers role search phrases for finding new
people. It does not search LinkedIn, invent named contacts, send messages, or
mark anything sent.

The CLI is still available as a fallback:

```powershell
uv run cc job-search note <application_id> --type recruiter_call --file notes.md --furthers-process
uv run cc job-search followup <application_id>
```

## Codex Handoff

Open any section card and use `open in chat` to prefill the cockpit chat with
the card context. For jobs, Codex can run the CLI workflow, inspect generated
materials, summarize blockers, draft follow-ups, and update notes. It should not
claim submission unless the card is moved to `Completed` after Geoff confirms the
application was actually submitted.
