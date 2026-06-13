# Hermes Agent — disposition (WS4)

Date: 2026-06-13. Authoritative for the Hermes spike. The live spike WAS RUN
(isolated, local-only); this records the measured result. Pairs with
[PRE-REGISTRATION.md](PRE-REGISTRATION.md) (criteria fixed up front) and the
tested [safety_preflight.py](safety_preflight.py).

## Disposition: DEFER — do not adopt

The spike ran Hermes Agent **v0.16.0** in an isolated uv venv (`C:\tmp\hermes-spike`),
pointed at host Ollama `:11434/v1` directly (provider `custom`), no cloud keys, no
Nous login, no `.env`. It confirms the standing recommendation **with evidence**:
of the two claimed differentiators, one works but is not beyond-stack, and the
other (the headline) did not materialize. Two of six adoption gates fail → DEFER.

## Measured results (all artifact- or transcript-verified)

| Stage | Result | Evidence |
|---|---|---|
| Install (isolated, reversible) | PASS | `uv pip install hermes-agent==0.16.0` into a temp venv; `hermes --version` = v0.16.0 |
| Connectivity to local Ollama | **PASS** | one-shot `-z` → `PONG` in 44.8s cold; provider `custom` → `:11434/v1` |
| Tool-calling on Ollama (#25629 risk) | **did NOT hang** | the memory-write tool call completed in 19.6s; #25629 did not bite on this path |
| Cross-session memory | **PASS (verified)** | session A taught `BANANA_MODE`; a FRESH session B (no `--continue`) recalled it; artifact `memories/MEMORY.md` literally contains the fact |
| Self-improving skills (autonomous) | **FAIL** | forced `curator run` → "auto: no changes; llm: skipped (no candidates)"; **0 skills auto-created** from real session history |
| Skills infra (explicit authoring) | works | explicitly asking created `skills/release-tag/SKILL.md` (+ script), enabled — but that is not "self-improving" |
| Safety: credentials | **PASS** | all provider API keys unset, no `.env`, no Nous login (`hermes status`) |
| Safety: external egress | **PASS** | log scan found no non-local hosts; Ollama localhost only |
| Safety: secrets in HERMES_HOME | **PASS** | scan found only the empty `api_key: ""` and the deliberate fake `BANANA_MODE` |

Raw transcripts: [raw/](raw/) (memory-A, memory-B, skills-run1, skills-explicit, curator-run).

## Adoption rubric (must clear ALL 6 — see PRE-REGISTRATION §4)

1. Skills auto-created AND reused — **FAIL** (0 auto-created; curator found no candidates).
2. Memory recalled in a separate session — **PASS** (verified).
3. Beyond-stack (does something bridge+Ledger+MCP can't) — **FAIL**: cross-session memory is a
   local `MEMORY.md` file — the *same pattern* this stack and Claude Code already use; it is not
   a capability the existing surfaces lack. Self-improving skills, the one genuinely novel claim,
   did not fire.
4. No new credential exposure — **PASS**.
5. No second always-on brain — **PASS** (on-demand one-shot only; nothing scheduled).
6. Respects the L2 skill cap — **N/A** (no autonomous skill writes occurred to test).

Gates 1 and 3 fail → **DEFER**. LiteLLM stays. Hermes stays a DECISION.md note, not a container.

## Honest correction discovered during the run

The first-draft `safety_preflight.py` checked a `data_collection: deny` config key (from
secondary sources). **v0.16.0 has no such key** — verified against `hermes_cli/config.py`. The
preflight was rewritten to the real schema (explicit local `provider`, local `:11434` `base_url`,
empty `api_key`, set `model`, local `custom_providers`) and telemetry is instead controlled
structurally (no cloud provider, no key, local endpoint) and verified by the egress log scan.
This is the spike correcting an assumed fact with a verified one — the point of running it.

## Re-evaluation trigger

Reconsider only if a future Hermes release demonstrates **autonomous** skill self-improvement that
beats the existing gated `skill_updates` path on the real workflow, AND offers a memory capability
beyond a local `MEMORY.md`. Until then: the working orchestration is the existing stack (Discord
gateway + proactive runner + kanban bridge + Ledger + MCP).

## Cleanup

The temp install (`C:\tmp\hermes-spike\venv` + `HERMES_HOME`) is removed after this run — rollback
is deleting that directory; nothing in the repo or production config was touched. The raw
transcripts above are retained under the repo eval dir as the evidence record.
