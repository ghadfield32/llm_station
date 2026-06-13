# Contributing

Command Center is a small, contract-driven control plane. The bar is *boring and
hard to break*, not clever. Three rules carry most of the weight.

## 1. The contract loop

`configs/*.yaml` is the source of truth → `src/command_center/schemas/` validates it
→ `generated/` is disposable rendered output → the Ledger SQLite is the only runtime
state. So:

- **Edit YAML, never `generated/`.** Regenerate with `make render` / `make schema`.
- **Every config edit runs `make validate`** (Pydantic per-file + cross-file refs +
  render + the local-only provider check). A typo fails here, not at 2am.
- Adding a config file means adding its contract to
  `src/command_center/schemas/contracts.py` and registering it in `CONFIG_CONTRACTS`.
- **Secrets never live in YAML.** Tokens/keys live only in `.env` (gitignored); configs
  reference them by env-var name.

## 2. Engineering standards (mirrors `configs/standards.yaml`)

The defensive-coding judge enforces these on every mission; honor them by hand too:

- **No defensive coding** — no swallowed excepts, no redundant guards, no dead flags,
  no fake retries. Surface errors; don't hide them.
- **No hardcoded thresholds or fake/fallback values** where a real, data-derived value
  belongs. A magic default that masks missing data is a bug.
- **Minimal diffs.** Change what the task needs; don't wander into out-of-scope rewrites.
- **Never weaken a test to make it pass.** Fix the cause.

Legitimate boundary validation (fail-fast on missing required env, strict Pydantic) is
*not* defensive coding — that's the point of the contracts.

## 3. The uv dependency workflow

The package is uv-managed (`pyproject.toml` + `uv.lock`). To add a dependency:

```bash
uv pip install <pkg>                 # try it
# then pin it in pyproject.toml with a sensible lower bound, e.g. "<pkg>>=X.Y"
#   core dep            -> [project.dependencies]
#   channel transport   -> [project.optional-dependencies].gateways
#   lint/test only      -> [project.optional-dependencies].dev
uv sync                              # confirm the lock still resolves
```

Run `make lint` (ruff + mypy) and `make test` (pytest) before opening a PR. Channel work
needs the extras: `uv pip install -e ".[gateways,dev]"`.

## 4. Multi-session git safety (single-writer rules)

Multiple Claude Code / Codex sessions may touch this repo at once. The git half of
`docs/backend/engineering/MULTI_SESSION_R2.md` applies verbatim (the R2/Railway/Airflow
half does **not** — this is a control plane, not the forecasting pipeline; see
`docs/MASTER.md` §13.1):

- **Stage explicit paths you own**: `git add path/a path/b`. Never `git add -A` / `git add .`.
- **Never** force-push a shared branch, `--amend` a pushed commit, or `--no-verify`.
- Before pushing: `git log origin/main..HEAD --oneline`. If another session's commit is in
  the tree, **rebase to keep their work**, don't overwrite it.
- The `appflowy_kanban/AppFlowy-Cloud` submodule is **pinned**. Don't bump it as a side
  effect of unrelated work; update it deliberately in its own commit.
- Work on a branch off `main`; open a PR. The agent may push a feature branch and open a
  PR; it never merges, deploys, or publishes — those stay human-gated.

## Before you open a PR

```bash
make validate        # contracts + cross-refs + render + provider boundary
make mission-dryrun  # L0–L4 lifecycle is coherent (no model calls)
make lint && make test
python -m command_center.channels --dry-run   # if you touched channels
```

CI (`.github/workflows/contracts.yml`) runs the validate gate plus `ruff check src` and
`pytest` on every PR.
