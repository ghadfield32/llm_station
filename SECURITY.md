# Security Policy

## Reporting a vulnerability

Email **ghadfield32@gmail.com** with details and reproduction steps. Please do not
open a public issue for a security report. You'll get an acknowledgement within a
few days.

## Security posture (by design)

This is a personal control plane built to be hard to misuse:

- **Local-only models.** LiteLLM routes only to local Ollama; the contract
  (`make forbidden-providers`) rejects any OpenAI/Anthropic/OpenRouter route or API
  key. Coding executors (Claude Code / Codex) authenticate through their own
  subscription/OAuth login, never through this repo.
- **No secrets in git.** Secrets live only in `.env` files, which are gitignored
  (`make doctor` / CI assert no provider keys are present). `.env.example` files carry
  names, never values. The AppFlowy stack ships dev-default secrets that must be
  rotated before any non-local exposure (see [docs/SETUP-FROM-SCRATCH.md](docs/SETUP-FROM-SCRATCH.md)).
- **LiteLLM pinned by immutable digest**, not a tag and never `pip install`ed — a
  guard against registry/supply-chain tampering. `make verify` checks the pin.
- **Human-gated external writes.** Agents can push a feature branch and open a PR;
  they cannot merge, deploy, publish, or approve their own mission cards. L3/L4
  actions require human approval and GitHub branch protection is the final wall.
- **Reach over Tailscale**, not public URLs. Nothing is exposed to the internet by
  default.

## Scope

Reports about the control-plane code, contracts, and configs in this repo are in
scope. The vendored `appflowy_kanban/AppFlowy-Cloud` submodule is upstream
(AppFlowy-IO) — report issues there to that project.
