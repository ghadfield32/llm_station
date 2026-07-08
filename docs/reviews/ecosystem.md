# Ecosystem — Hermes, Ollama, WebUI, and what's load-bearing

> **Archived — superseded.** This file predates the settled verdict and is
> self-contradictory: the reconciliation note below says Hermes was deferred,
> but the body still calls it the "core orchestrator." Trust `docs/MASTER.md`
> §4 instead ("Hermes is not the active coordinator"). The Ollama gotchas
> further down are accurate and already duplicated in `docs/MASTER.md` §5.
>
> **Reconciliation note (2026-06-13).** Hermes Agent was **evaluated → DEFER** (MASTER.md change log),
> and the Cline CLI was likewise deferred. As a result the **WebUI/Kanban sections below are historical**:
> the Phase-4 WebUI slot (`configs/ui.yaml`) is being repurposed from `nesquena/hermes-webui` + Hermes
> Kanban to a **first-party agent kanban + observability** surface over AppFlowy/Ledger. The contract
> guarantees (loopback/Tailscale, password, `governed_by_ledger`, single-container) are unchanged. Current
> direction + tracker: `docs/kanban/AGENT_KANBAN_SURFACE.md`. The Ollama gotchas and the
> `local-ai-server` verdict below still apply.

This answers three questions: how Ollama-Hermes relates to Hermes open source, whether
`nesquena/hermes-webui` fits (and works with the Ollama-launched Hermes), and whether
`RamiKrispin/local-ai-server` helps. Short version: **hybrid ecosystem, nothing replaced.**

## The three "Hermes" things (they're layers, not rivals)

| Thing | What it is | Role here |
|-------|-----------|-----------|
| Hermes Agent (Nous, MIT, v0.14.0) | the actual agent: memory in `~/.hermes/`, 70+ skills, self-improving skills, cron, 10+ channels, tools, subagents, Kanban, code exec | **core orchestrator** |
| `ollama launch hermes` | one-command installer/configurator: installs Hermes if missing, picks a model, points it at Ollama's `…:11434/v1`, optionally wires a channel | **easy install path + local-model provider** |
| `hermes3` / `qwen3.6` on Ollama | Nous/Qwen *models* you run | **just an LLM**, not the agent |

"Ollama Hermes" is **not a separate Hermes**. It installs and configures the same Hermes
Agent and points it at local models. Use Ollama as the **local-model runtime on the 4090,
reached through LiteLLM** so budgets/routing/fallback still apply; `ollama launch hermes` is
fine as a fast first install, but Hermes should ultimately target **LiteLLM** as its endpoint,
not Ollama directly.

**Two Ollama gotchas the docs call out (put these in Phase-2 notes):**
- Hermes needs **≥64k context; Ollama defaults to 4,096.** Raise `num_ctx` (Modelfile or env) or Hermes misbehaves after 3–4 tool calls.
- Ollama is **one request at a time by default.** Set `OLLAMA_NUM_PARALLEL` (VRAM permitting) and `OLLAMA_KEEP_ALIVE=-1` so parallel judge calls don't queue or trigger reloads.

## `nesquena/hermes-webui` — yes, and it's mature

Verified against the live repo (not the secondhand summary): **MIT, ~8.2k stars, 430 releases,
137 contributors, 5,303 tests across 488 files, latest May 2026**, official home `get-hermes.ai`.
This is a real, actively-maintained project — not a young side repo.

**Does it work with the Ollama-launched Hermes?** Yes. It auto-detects the existing Hermes
agent dir (`~/.hermes`) and uses your existing models, so whether Hermes was installed manually
or via `ollama launch hermes`, the WebUI finds the same config. It also has explicit per-profile
custom-endpoint fields (Ollama/LM Studio) — so local endpoints work without hand-editing files.

**What it gives you:** browser chat with SSE streaming, tool-call cards, **dangerous-shell-command
approval cards**, Mermaid rendering, workspace file browser with git detection, CLI session bridge,
profiles/skills/memory/tasks panels, password auth, and a mobile layout designed for Tailscale
phone access. That covers the "operate from any laptop/desktop/phone" goal well.

**The two real caveats (now encoded in `configs/ui.yaml`):**
- Two-container mode (#681): tools triggered from the WebUI run in the *WebUI* container, not the agent container. Use **single-container** (the config default) or extend the image.
- The agent-source mount is "an implementation-coupling bridge, not a stable API boundary" (#2453) — fine for a personal UI, not something to build policy on.

**So:** add it as an optional **Phase-4 human UI behind Tailscale + password**, governed by
`configs/ui.yaml`. It does not replace the Ledger, Judge Gate, LiteLLM budgets, workspace leases,
or GitHub gates. Its own shell-approval card is a convenience, not the policy layer — external
writes still flow through the mission pipeline. The contract enforces this: `external_write_policy`
must be `governed_by_ledger`, and exposing it beyond loopback without a password fails validation.

## First-party Hermes Kanban vs the WebUI

These are complementary. **Hermes Kanban** (first-party, SQLite-backed durable task board) is
*coordination infrastructure* — multi-agent task state, handoffs, worker lanes, decompose →
parallel worktrees → review → PR. The **WebUI** is the *browser interface* you drive it from.
Use Kanban for durable multi-agent coordination; use the WebUI for chat, file browsing, and
approvals from a laptop or phone.

## `RamiKrispin/local-ai-server` — skip it for this stack

It's a clean OpenAI-compatible local gateway, but it's **Mac-Studio / Apple-Metal / MLX-specific**
("MLX has no Linux wheels," "Apple Metal has no GPU passthrough into Docker on Mac"), and it's
**WIP, ~4 stars, 1 contributor, just initialized.** You're on an RTX 4090 (CUDA/Linux), and you
already run **LiteLLM** doing the same OpenAI-compatible-gateway job *plus* budgets, virtual keys,
and fallback that this repo doesn't have. It's a nice Mac-homelab project; for your hardware it's
the wrong platform and a redundant layer. If you ever add a Mac Studio inference node, it'd still
sit *behind* LiteLLM — same as Ollama. Not on the watch-list for the core.

## Final ecosystem placement

```
Core:          Nous Hermes Agent + Hermes Kanban + LiteLLM + Judge Gate + Ledger
Local models:  Ollama on the 4090, reached THROUGH LiteLLM (not directly)
UI:            Hermes CLI + messaging channels + first-party Kanban
               + nesquena/hermes-webui as optional Phase-4 browser UI (Tailscale + password)
Coding:        VS Code Remote Tunnel + devcontainers + one executor first
Safety:        GitHub protections + pre-commit/pre-push judges + human approval
```

**One sentence:** Ollama helps Hermes run local models, Hermes runs the agent, the WebUI helps
you operate Hermes from anywhere, LiteLLM governs model access, the Judge Gate and Ledger govern
safety, and GitHub enforces the final boundary. Nothing in that chain is replaced by adding the
WebUI or by `ollama launch hermes` — they slot into the layers that were already there.
