# Security Policy

## Reporting a vulnerability

Email **ghadfield32@gmail.com** with details and reproduction steps. Please do not
open a public issue for a security report. You'll get an acknowledgement within a
few days.

## Security posture (by design)

This is a personal control plane built to be hard to misuse:

- **Local LiteLLM lane; explicit external lanes.** LiteLLM routes only to local
  Ollama, and `make forbidden-providers` is the deliberately strict audit that
  rejects every OpenAI/Anthropic/OpenRouter route or API key. `cc validate` checks
  the configured posture instead: it permits only the key names owned by a lane
  whose committed budget and safety controls prove readiness. Local model routes
  remain cloud-free in every mode. Coding executors (Claude Code / Codex) normally
  authenticate through their own subscription/OAuth login.
- **No secrets in git.** Secrets live only in gitignored `.env` files. `make doctor`
  and CI scan tracked configuration for secret literals; `.env.example` files carry
  names, never values. The retired board runtime and its
  former defaults remain under `archive/appflowy/` and must never be started or copied
  into an active environment.
- **LiteLLM pinned by immutable digest**, not a tag and never `pip install`ed — a
  guard against registry/supply-chain tampering. `make verify` checks the pin.
- **Human-gated external writes.** Agents can push a feature branch and open a PR;
  they cannot merge, deploy, publish, or approve their own mission cards. L3/L4
  actions require human approval and GitHub branch protection is the final wall.
- **Reach over Tailscale**, not public URLs. Nothing is exposed to the internet by
  default.

## Scope

Reports about the control-plane code, contracts, and configs in this repo are in
scope. The pinned `archive/appflowy/AppFlowy-Cloud` submodule is retirement provenance
only; its upstream issues belong to that project.
