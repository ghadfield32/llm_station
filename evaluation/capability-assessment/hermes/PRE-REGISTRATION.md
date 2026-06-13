# Hermes Agent — capability-assessment pre-registration (WS4)

Date pre-registered: 2026-06-13. Mirrors the semble/abtop template
(`evaluation/capability-assessment/DECISION.md`). **This file fixes the criteria
BEFORE the spike runs** so the bar can't move after seeing results (anti-Goodhart).
Nothing here installs Hermes or touches a production config; the live run is a
separate, operator-gated step (see "Execution gate").

---

## 0. What this is and is NOT

Hermes Agent (Nous Research, MIT, v0.16.0) is a self-hosted autonomous-agent runtime
(persistent memory in `~/.hermes`, skills, cron, channels, kanban). The standing
recommendation (system-roadmap "Settled decisions") is **evaluate in isolation, do not
adopt** — everything it orchestrates is already covered by this stack (Discord gateway,
proactive runner, kanban bridge, Ledger, MCP). This spike exists ONLY to test the two
claims that are *not* cleanly covered elsewhere, against a hard adoption bar.

**In scope (the only two dimensions measured):**
1. **Self-improving skills** — does it auto-generate/refine reusable skills from experience
   in a way the existing `skill_updates` (L2-capped, gated) path does not?
2. **Curated cross-session memory** — does memory persist and *measurably help* across
   separate sessions in a way the Ledger + MCP do not already give us?

**Explicitly out of scope** (the stack already covers these; testing them would be
re-litigating a settled decision): channels, cron/scheduling, kanban, model serving.

---

## 1. Threat model (why the run must be isolated)

| Risk | Mitigation (enforced by the safety preflight before any run) |
|---|---|
| Pre-1.0 churn / instability (6 releases in 3 weeks, ~20k open issues) | Pin **exactly v0.16.0**; never `latest`. |
| LiteLLM+Ollama hang bug (#26489) | Point Hermes at Ollama **`:11434/v1` directly**, NOT at the LiteLLM proxy. |
| New credential exposure | No provider/cloud API keys. `model.api_key` empty/local only. |
| Vendor billing pull (default provider = Nous Portal) | `model.provider: custom` — never `nous-portal`. |
| Telemetry / data exfiltration | v0.16.0 has NO `data_collection` config key (verified in source — the original draft was wrong). Controlled structurally instead: no cloud provider, no API key, local-only `:11434` endpoint; verified post-run by an egress scan of the logs. |
| Secret leakage into agent memory | Isolated `HERMES_HOME` (a temp dir), NOT real `~/.hermes`; scan it for secrets after the run; the spike dir holds no `.env`/keys. |
| Touching production | No edits to `configs/`, the Ledger, judges, or any repo. Spike lives entirely under `evaluation/capability-assessment/hermes/`. |
| A second always-on brain | The agent is run **on-demand for the spike only** and stopped after; never registered as a service or scheduled. |

The preflight (`safety_preflight.py`, unit-tested) parses the Hermes profile config and
**fails the spike before launch** if any isolation invariant is violated.

---

## 2. Safe-run protocol (operator steps; gated)

1. Run `safety_preflight.py <hermes-config.yaml>` → must print `PREFLIGHT: PASS`.
2. Launch Hermes pinned to v0.16.0 with `HERMES_HOME=$(spike tmp dir)`, provider `custom`,
   base_url `http://localhost:11434/v1`, `data_collection: deny`.
3. Run the benchmark below; capture raw transcripts under `raw/`.
4. After the run: scan `HERMES_HOME` for secrets; confirm no telemetry egress; delete the
   temp home (rollback = remove the dir; nothing else changed).

## 3. Benchmark (what is measured)

| Dimension | Procedure | Raw evidence |
|---|---|---|
| Self-improving skills | Give a repeatable multi-step task twice in fresh sessions; check whether a reusable skill is auto-created in `HERMES_HOME/skills/` and whether run-2 uses it (fewer steps / less prompting). | `raw/skills-run1.txt`, `raw/skills-run2.txt`, `HERMES_HOME/skills/` listing |
| Cross-session memory | Teach a fact in session A; in a *new* session B (no shared context window) ask a question that requires it; record whether it's recalled and correct. | `raw/memory-A.txt`, `raw/memory-B.txt` |
| Safety (gating) | Confirm no secrets in `HERMES_HOME`, no telemetry egress, provider=custom, no new keys. | preflight + post-run scan |

## 4. Acceptance rubric (the adoption bar — must clear ALL to graduate)

A pass on the two capability dimensions is necessary but **not sufficient**. To move from
a DECISION.md note to any production integration, Hermes must clear every gate:

- [ ] **Skills**: auto-creates a reusable skill AND run-2 demonstrably uses it (measured
      reduction in steps/prompting), not just stores a transcript.
- [ ] **Memory**: recalls the taught fact correctly in a genuinely separate session.
- [ ] **Beyond-stack**: does something the bridge + Ledger + MCP cannot already do on the
      real workflow (not a re-implementation of an existing surface).
- [ ] **No new credential exposure** (preflight pass).
- [ ] **No second always-on brain** (on-demand spike only).
- [ ] **Respects the L2 skill cap**: any skill it would write to a managed repo goes through
      the existing gated `skill_updates` path (max_auto_risk = L2), not Hermes' own writer.

**If any gate fails → disposition is DEFER/DECISION-only; no container, no service.**

## 5. Execution gate (why this turn stops here)

Running the spike requires installing a pre-1.0 agent via `curl … | bash` (outward-facing,
hard to reverse, network egress). Per the repo's confirm-before-irreversible-outward-action
rule, the **install + live run is operator-gated** — not auto-executed. This pre-registration
+ the tested preflight are the do-now deliverables; the run produces the final DECISION.md
disposition once the operator green-lights the install.
