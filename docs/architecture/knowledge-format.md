# The knowledge bundle (OKF · growth-os-0.1)

A portable, Git-backed projection of system knowledge that agents (Claude, Codex, the independent
verifier, the proactive runner) can load as shared, token-cheap context — **without** mistaking it
for the source of truth. It is the Open Knowledge Format (Markdown + YAML frontmatter), tightened
into a strict `growth-os-0.1` profile.

> One rule, the same wall as the discovery scan: **source systems produce OKF; OKF never modifies
> source systems.** Every concept is `authority: derived` and points back at its authoritative
> source (a config, the Ledger, the code). The bundle is a read-only mirror, regenerable any time.

```bash
make knowledge-generate     # read sources → write the knowledge/ bundle (never touches a source)
make knowledge-validate     # blocking N/N PASS gate
# Windows: .\scripts\cc.ps1 knowledge-generate | knowledge-validate
```

## 1. Why it exists (and what it is NOT)

It gives every agent the *same* structure for context, with `index.md` progressive disclosure so a
mission reads one section index and a handful of concepts instead of scanning the whole repo. It is
a neutral, versioned context package the implementer and the independent verifier can both load.

It is **not** a second source of truth, a service, a database, or an orchestrator. It does not
replace `configs/*.yaml` (policy), the Pydantic contracts (validation), the Ledger (runtime state),
AppFlowy (human curation), the code (implementation), or the GitHub wall. Those stay authoritative;
OKF points at them.

## 2. The strict profile (`growth-os-0.1`)

Base OKF v0.1 requires only `type`. That is too loose here, where everything is a contract. The
profile (`src/command_center/knowledge/profile.py`, `OkfConcept`) adds the fields an agent needs to
know how far to trust a concept and where it came from — validated, strict (unknown fields rejected):

| Field | Purpose |
|---|---|
| `source_system` / `source_path` / `source_revision` / `source_hash` | exactly where the facts came from |
| `authority` | `authoritative` · **`derived`** (default) · `curated` · `observed` · `experimental` · `historical` |
| `status` · `confidence` · `sensitivity` | how current / trusted / sensitive (a `secret` concept is refused) |
| `owner` · `generated_by` · `generator_version` | provenance |
| `review_after` | when a consumer should re-verify |

`authority` is load-bearing: our producers emit `derived`, so an agent never confuses the projection
for the source.

## 3. Module tree

```
src/command_center/knowledge/
  profile.py      OkfConcept — the strict growth-os-0.1 frontmatter contract
  document.py     concept read/write: frontmatter + GENERATED block + human notes (clobber-safe)
  producers.py    deterministic, observer-only extractors (source → ConceptDraft); no source → no concept
  bundle.py       run all producers → write concepts + per-section index.md + top index.md + log.md
  validate.py     the blocking N/N PASS gate
src/command_center/cli/knowledge.py    generate | validate
knowledge/                              the bundle itself (Git-backed, committed)
```

## 4. Bundle layout (progressive disclosure)

```
knowledge/
  index.md                 sections + counts (start here)
  log.md                   generation record
  system/  standards/  repositories/  models/  pipelines/  dags/  datasets/
  metrics/  APIs/  runbooks/  incidents/  decisions/  experiments/{active,promoted,
                                                       rejected,inconclusive,rolled-back}/  skills/
```

Every section always exists; an empty one carries an honest "no concepts yet" index rather than a
fabricated concept. Each concept is one file:

```markdown
---
<frontmatter validated by OkfConcept>
---

<!-- generated:start -->
…deterministic facts produced from the source…
<!-- generated:end -->

## Human notes
…preserved verbatim across regenerations…
```

## 5. Guarantees (all tested)

- **Observer-only** — producers only read sources; the bundle is the only thing written.
- **Clobber-safe** — regeneration replaces only the frontmatter + generated block; human notes
  survive (the same rule the Kanban board sync uses).
- **No churn on unchanged source** — freshness is *data-derived*: if a concept's `source_hash` and
  generated block are unchanged, the prior timestamps are kept, so a regeneration is byte-identical
  (compare hashes, not the clock — the standards' cache rule). The clock is injectable (`--now`).
- **No fabricated content** — a source that is absent yields no concept.
- **Blocking gate** — `knowledge-validate` checks every concept's frontmatter, that source paths
  exist, that internal links resolve, and that no secret leaked into a generated block; a single
  FAIL exits non-zero.

## 6. Producers (what reads what)

| Section | Source | Authority |
|---|---|---|
| system (risk-tiers, operator-interface, configuration-model) | `configs/gates.yaml`, `Makefile`, `configs/` | derived |
| standards | `configs/standards.yaml` | derived |
| repositories | Growth OS `projects.yaml` | observed |
| models | `configs/models.yaml` | derived |
| pipelines | the scan / proactive / model-update code+configs | derived |
| dags | `dags/*.py` | derived |
| metrics | `improvement/selfmetrics.py` | derived |
| APIs | `services/ledger`, `services/judge_gate` | derived |
| experiments | the Ledger experiment registry (`data/ledger.db`) | experimental / historical |

Adding a producer is a function `(root, now_iso) -> list[ConceptDraft]` added to `ALL_PRODUCERS`.

## 7. Status & follow-ups

Implemented + tested + validating (14 concepts on first generation). Pilot scope is llm_station; the
`betts_basketball` repository is currently a one-line `observed` concept (the analysis's deeper
betts pilot — odds pipelines, R2 assets, metrics — would be produced from that repo). Tier/role
*descriptions* are thin where the source YAML doesn't carry them; enriching the extractors is
additive. See also [daily-self-improvement-dag.md](../improvement/daily-self-improvement-dag.md) for the sibling
observer-only subsystem this mirrors.
