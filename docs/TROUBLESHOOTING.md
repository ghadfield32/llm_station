# Troubleshooting & known gotchas

Start with `uv run cc doctor` — it reports PASS/FAIL/BLOCKED/NOT_RUN with the
exact next command for each check.

## Known gotchas (these are by design)

- **GitHub App has no `workflows:write`.** It cannot push changes to
  `.github/workflows/**`. A PR that edits a workflow file must be pushed with
  **human/user git credentials**, not the App token (an App push of a workflow
  change 403s). Do not grant the App `workflows` unless policy changes.
- **`require_last_push_approval` + solo maintainer.** The ruleset requires the
  most-recent reviewable push to be approved by *someone other than the pusher*.
  A PR you pushed yourself can't be approved by you. The fix is the documented
  pattern: the **GitHub App** authors+pushes the PR; then your approval counts.
  (If you push a PR yourself as the sole maintainer, you must temporarily relax
  that one sub-rule to merge it.)
- **Test suite needs the dev/gateway extras.** Tests import channel adapters
  (fastapi/discord/slack/uvicorn). CI installs `.[dev,gateways]`; locally run
  `uv run --extra dev --extra gateways pytest`. A `.[dev]`-only run fails on
  `ModuleNotFoundError: fastapi`.
- **Retrieval-equivalence tests fail loudly if files change mid-run.** That's by
  design (fail-on-changed-corpus). Don't edit files while the suite runs; re-run
  clean.
- **`rtk`/console encoding.** Some wrappers mis-summarize `pytest` output; run
  `rtk proxy <cmd>` to bypass filtering. Console may render em-dashes oddly —
  cosmetic only.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `cc validate` FileNotFoundError on a `configs/*.yaml` | a config registered in CONFIG_CONTRACTS but the file isn't staged/committed | stage the yaml; CI checks out only committed files |
| `validate: PASS` but CI red on `lint-test` | missing gateway dep at runtime | run/CI with `--extra dev --extra gateways` |
| `pr-check` checks never report | the PR's changed files don't match the CI `paths`/branch trigger | touch a CI-triggering path (configs/src/tests/pyproject/workflow) |
| `desktop-action-canary: BLOCKED representative_action_source_not_configured` | no AppFlowy sandbox wired | set `APPFLOWY_SANDBOX_*` in `.env` to a sandbox board, then re-run |
| `desktop-timing-derive: BLOCKED action_latency_evidence_required…` | only read-only no-op evidence exists | produce real action-latency evidence first (it's not a code bug) |
| `repo-enable-autonomy: BLOCKED` | a gate fails (devcontainer/CODEOWNERS/branch-protection/board/evidence) | run `cc repo-verify --repo-id <id>` and clear each blocker |
| `memory-add: BLOCKED` | secret-bearing value or missing `--source-ref` | remove the secret / supply provenance |
| Ollama/LiteLLM DOWN in `cc health` | stack not up or Ollama not running | `cc up`; start Ollama; check `OLLAMA_API_BASE` in `.env` |

## Where to look

- System map + change log: [MASTER.md](MASTER.md) (§14)
- Security boundaries: [SECURITY_MODEL.md](SECURITY_MODEL.md)
- Compact "has this been done?" index: `WORKLOG.md` (repo root)
- Evidence packages: `evaluation/system-validation/`
