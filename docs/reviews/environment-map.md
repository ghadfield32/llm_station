# Environment map — one environment per activity

> **Archived — folded into `docs/MASTER.md` §7.** The environment table and
> the "mapping activity → environment" list below now live there. Kept only
> in case the original phrasing is useful.

Defined in `configs/environments.yaml`, validated by the `EnvironmentsConfig` contract.
Open that file to answer "what can X access?". Invariant (enforced): a `repo_task` is
ephemeral and holds NO secrets — that's how per-task isolation stays real.

| Environment | Kind | Host | Persistent | GPU | Egress | Secrets |
|---|---|---|---|---|---|---|
| cc-control-vps | control_plane | VPS | yes | no | tailscale, provider_apis, github_api | LiteLLM master, virtual keys, ledger secret |
| cc-worker-4090 | worker | 4090 | yes | yes | tailscale, litellm, github, registries | GITHUB_TOKEN |
| cc-repo-task | repo_task | 4090 | **no** | no | litellm, github, registries | **none** |
| cc-judge | judge | VPS | yes | no | litellm | judge virtual key |
| cc-relay | relay | mini-PC | yes | no | tailscale | none |

## Mapping activity → environment
- Orchestration / memory / channels → **cc-control-vps** (always-on brain)
- Model routing + budgets (LiteLLM) → cc-control-vps
- Mission audit / approvals / leases → Ledger on cc-control-vps
- Judge execution → cc-judge
- Heavy repo builds / DAGs / CV / local models → **cc-worker-4090**
- Human IDE → VS Code Remote Tunnel from the 5080 into the 4090 workspace
- Per-task edits → **cc-repo-task** devcontainer (one mission → one branch → one worktree → one devcontainer → one lease)
- CI validation → GitHub Actions (independent verification after push)
- Wake-on-LAN / watchdog / backup mirror → cc-relay (optional)

## Why devcontainers for repo_task
The Dev Container spec exists for reproducible, isolated dev environments; `.devcontainer/devcontainer.json` pins the runtime so every mission builds/tests identically and can't pollute the host or another task.
