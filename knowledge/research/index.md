# Research intake (curated — NOT the generated OKF bundle)

This directory is **hand-authored** and is not produced by `cc knowledge-generate`.
The OKF producers do not own it, so it will not be clobbered by a bundle regeneration.

## What lives here

- [`source_catalog.yaml`](source_catalog.yaml) — the durable, typed record of external
  ideas/repos/links evaluated against this stack. Validated on load by
  `command_center.research.catalog` (a typo'd key or bad verdict fails loudly).

## Why it exists

It productizes the MASTER.md §5.2 intake ("broad prompt first, then no adoption without a
measured gap, control-plane overlap matrix, threat model, and pre-registered experiment").
A link dump becomes rows here instead of a one-off chat that gets lost.

## The loop

```
cc research-digest validate      # load + Pydantic-validate the catalog (blocking gate)
cc research-digest report        # human digest grouped by verdict (stdout or --out)
cc research-digest feed          # -> generated/research-digest-feed.json (evaluate rows only)
cc self-improvement-scan --feeds generated/research-digest-feed.json
```

Only rows marked `verdict: evaluate` emit a feed record, and each drafts a **read-only (L1)
evaluation card** through the same observer-only, propose-only wall model-scout uses. Adoption
still requires the full human wall. Everything else (`build` / `already_have` / `watch` /
`reject`) is durable memory so the same source is never re-litigated from scratch.

## Seed

The catalog is seeded with the 2026-07-02 agent-infrastructure batch (Cline, Agent-Native,
RushDB, TurboVec, SLayer, STORM, local-ai-server, Library Skills, GLM-5.2, AIonDemandCluster,
argithub, career-ops, Hermes, Google Agents CLI). That batch was fully adjudicated, so the
feed is **empty by design** — nothing auto-flows to a card without a genuine open evaluation.
