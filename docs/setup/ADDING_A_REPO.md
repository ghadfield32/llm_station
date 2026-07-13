# Adding a local repo

Onboard another repo on this machine under the same safety contract as
`llm_station`. Autonomy stays **off** until every gate passes.

## 1. Register (disabled, with blockers)

```bash
uv run cc repo-register \
  --repo-id betts_basketball \
  --local-path C:/path/to/betts_basketball \
  --remote-url https://github.com/<owner>/betts_basketball.git \
  --kanban-board <board_id>          # a board from `cc kanban-verify` / kanban_boards.yaml
```

Dry-run by default — it prints the manifest block and the env var to set. The
local path is **never committed**: it's stored as `local_path_ref: env:BETTS_BASKETBALL_LOCAL_PATH`,
and you put the absolute path in `.env`. Re-run with `--apply` to write the
disabled manifest into `configs/autonomy.yaml`, then set the env var.

## 2. Verify the gates

```bash
uv run cc repo-verify --repo-id betts_basketball
```

Reports each gate PASS/BLOCKED/NOT_RUN:

- devcontainer present, CI commands declared, CODEOWNERS present;
- `kanban_board_id` maps to a registered board that lists this repo;
- `local_path_ref` resolves (`self` or `env:NAME` present);
- GitHub App installed for the repo; branch protection verified;
- `secret_policy: no_runtime_secrets_inside_container`;
- **branch-mission** and **PR-check-evidence** both PASS (proven, not faked).

Steps 6–7 require the repo to actually go through the bounded loops once:

```bash
uv run cc branch-mission --repo-id betts_basketball              # local loop
uv run cc pr-check-verify --repo-id betts_basketball --apply     # live PR loop
```

## 3. Enable autonomy (only when green)

```bash
uv run cc repo-enable-autonomy --repo-id betts_basketball        # dry-run: re-verifies
uv run cc repo-enable-autonomy --repo-id betts_basketball --apply # flips the flag if clean
```

`enable-autonomy` **refuses** while any gate blocks. On `--apply` it sets
`autonomous_edits_enabled: true` and clears blockers, re-validating the
enabled-manifest invariants (github_app auth, devcontainer, CODEOWNERS,
kanban_board_id, local_path_ref) before writing.

## Prerequisites the new repo needs

A `.devcontainer/devcontainer.json`, a `.github/CODEOWNERS`, the
`protect-main-command-center`-equivalent branch protection on its `main`, and the
GitHub App installed on it. Until those exist, `repo-verify` blocks — by design.
