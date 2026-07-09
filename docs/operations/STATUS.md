# Status — done / in progress / next

The multi-session work tracker. Newest changes are in `MASTER.md` §14; this is the
forward-looking "what's left, in what order" list. Keep it short and honest.
(Absorbs the former `SETUP-REMAINING.md` deployment checklist and
`growth-os-system.md` status snapshot.)

For the high-level, whole-system map (control plane + knowledge base + managed
projects + fleet, with the module tree and the strategic order) see
[system-roadmap.md](../reviews/system-roadmap.md). This file stays the tactical tracker.

_Last updated: 2026-07-09._

## Done

- **Cockpit full sweep (2026-07-09).** The first-party cockpit is the shipped
  primary surface: 9 typed domains (`configs/domain_surfaces.yaml`), internal
  job board with live discovery (62 real cards), LLM agent-writer + packet
  review/finalize gate, PWA over Tailscale Serve. 930 tests green (serial),
  authority/secrets/chat/setup sweeps adversarially verified, all confirmed
  findings fixed (`f8924d3`: true one-button `cc start`, stricter profile
  gate, fixture/timestamp hygiene, doc fixes). Evidence:
  `evaluation/system-validation/cockpit-full-sweep-20260709/`. Operator items
  left: AppFlowy Group-by-Status (optional projection), kill 2 stale June
  test missions, `DISCORD_ALLOWED_CHANNEL_IDS`, LinkedIn draft approval +
  schtasks. Next build slices (ranked): Papers→research-digest binding,
  Repos→registry binding, UX density polish, DAGs→Airflow binding.

- **GitHub-ready hygiene.** Comprehensive `.gitignore`; all secrets/caches/dumps confirmed
  ignored via `git check-ignore`; stray tarball + egg-info removed; `AppFlowy-Cloud`
  pinned as a submodule; MIT `LICENSE`, `CONTRIBUTING.md`, PR template.
- **`src/command_center/` layout.** `schemas` / `registry` / `cli` relocated and installed
  editable; all imports, the Makefile, `cc.ps1`, CI, `breakage.yaml`, the evaluation
  gold-set, and the growth-os cross-imports rewired. `ruff check src` clean; `pytest` green.
- **Multi-channel gateway.** `GatewayCore` + Discord/Slack/Telegram/WhatsApp adapters +
  `configs/channels.yaml` (validated by `ChannelsConfig`, channel→model cross-checked) +
  `python -m command_center.channels` runner.
- **Docs.** `SETUP-FROM-SCRATCH.md`, `channels.md`, this file; `MASTER.md` module tree +
  doc index + §13 N/A note refreshed; reference standards copied to `docs/backend/`.

- **Docs consolidated (2026-06-12).** `runbook.md`, `COMPLETE-SETUP.md`, and
  `SETUP-REMAINING.md` folded into `SETUP-FROM-SCRATCH.md`; `growth-os-system.md` folded
  here; `PREFLIGHT-FIXES.md` retired (its history lives in `MASTER.md` §14 — note its
  provider-key advice was superseded by the local-only correction). Stale `_staging/`
  bundle copies removed from disk.
- **Local control plane green (2026-06-12).** Validation green, LiteLLM digest-pinned,
  local models installed, virtual keys minted, health + live smoke passing, Growth OS
  selftest 22/22, kanban bridge live with writeback.

## Autonomy hardening (2026-06-19)

The whole-system autonomy track is contract-backed in `configs/autonomy.yaml` (validated by
`AutonomyConfig`) and evidenced under `evaluation/system-validation/`. State:

- **GitHub wall verified.** `uv run cc branch-protection-verify` **PASS** against the active
  `protect-main-command-center` ruleset: required PR review (1) + CODEOWNERS, conversation
  resolution, linear history, deletion + force-push blocked, empty bypass list, required checks
  `validate` + `lint-test`. `uv run cc github-app-verify` **PASS** (App installed on the selected
  repo, mints an in-memory installation token, reads repo + check/status; no Administration).
  PR #9 proved the correct protected-branch path: the GitHub App authored the PR, `ghadfield32`
  approved it, required checks passed, and squash merge completed without weakening branch
  protection. PR #10 repeated the same pattern for the desktop no-op canary telemetry work.
  PR #8 is obsolete historical evidence of why user-authored PRs cannot satisfy the same
  user's required approval.
- **Repo autonomy.** `uv run cc branch-mission` proves the bounded local
  branch->worktree->docs-only change->declared checks->redacted evidence loop.
  It does not push, open a PR, merge, deploy, change settings, or touch secrets.
  `uv run cc pr-check-verify --apply --poll-interval 15 --poll-timeout 1800`
  proves the remote feature-branch->draft-PR->required-check loop through PR #6:
  `validate` and `lint-test` both completed successfully. `llm_station`
  repo autonomy is now enabled only for registered L2 feature-branch-only work;
  merge, deploy, settings, secrets, and branch deletion remain human-gated.
- **Desktop automation** (`appflowy_browser_staging`) has declared
  timeout/takeover, human-takeover, screenshot/evidence policy, a read-only
  no-op sample plan, and three no-op timing samples. `cc desktop-timing-derive`
  now proposes provisional TTL/action-timeout candidates from measured evidence
  only. The target remains disabled: no production TTL/action-timeout controls
  are written, and no desktop live actions are enabled until the candidates are
  reviewed and the adapter gate passes.
- **Future-facing capability routing.** `configs/capabilities.yaml` adds
  ARD-style metadata for internal tools, workflows, skills, and model
  candidates. `airflow-failure-rca-intake` is declared but dormant until real
  redacted snapshots are supplied through `PROACTIVE_AIRFLOW_EVIDENCE_DIR`.
  Headroom compression is a manual proposed experiment (`automated: false`), and
  Gemma 4 12B remains a gated candidate, not an active routing change.

## In progress / awaiting a human

- **Channels are wired but off.** Discord is `enabled: true` in `channels.yaml` but needs
  `DISCORD_*` tokens in `.env` to actually connect; Slack/Telegram/WhatsApp are `enabled:
  false` pending tokens. Live-test each once tokens exist (`make gateway CHANNELS=<one>`).
- **Growth OS end-to-end proof-drag** (from the former growth-os-system doc): two
  acceptance cards sit in Backlog on mission_intake — an L1 freshness-check card and an
  L4 wall-test card. Drag both to **Approved**, run the bridge with `--apply`, confirm the
  L1 card gets a MissionID/In Progress and the L4 mission holds at the Ledger awaiting
  approval. Then schedule the bridge (schtasks one-liner in `kanban-integration.md`).
- **Deployment remainder** (machine-by-machine, against the SETUP-FROM-SCRATCH §12
  definition of done): VPS rent + Docker/Tailscale + same bootstrap flow; Tailscale on the
  4090 + point VPS `OLLAMA_API_BASE` at it + `make live-smoke` from the VPS. GitHub branch
  protection + GitHub App identity are now **verified** (see Autonomy hardening above). Local
  items (digest pin, keys, health, live smoke, `cc.ps1 check`) are all done.

## Next (suggested order)

1. **Review the provisional desktop TTL/action-timeout candidates** and keep
   them non-production until accepted by the operator.
2. **Wire accepted timing controls only through the adapter gate**, then rerun
   `cc desktop-adapter`; do not enable desktop live actions while the adapter
   still reports missing production controls.
3. **Enable the desktop target only after timeout/takeover and canary policy**
   are verified by evidence, including accepted telemetry-derived TTL and
   action-timeout controls.
4. **Derive the GUI loop-breaker policy from event history** before allowing
   autonomous GUI retries.
5. **Enable no-op canaries only after blockers clear**, then decide telemetry
   from structured event gaps.
6. **Evaluate external runtimes only after measured gaps** show the current
   control plane cannot cover the needed capability.
7. **Bring one new channel live end-to-end** (Telegram is the lowest-friction — no public
   webhook, no app review) to exercise `GatewayCore` on a second transport in production.
8. **WhatsApp webhook** when wanted: stand up the public tunnel + Meta app, register the
   webhook (`docs/channels.md`), confirm the `GET` verify + `POST` inbound round-trip.
9. **`make lint` mypy pass.** Ruff is clean and CI runs ruff; mypy over `src/` is available
   via `make lint` but not yet wired into CI — tighten types and add it to CI when green.
10. **Path-independence (optional).** The config-pipeline CLIs read `configs/` relative to
   the CWD (run from repo root via `make` / `python -m`). If you want the console scripts to
   work from any directory, anchor their file reads to the repo root and expose the rest as
   entry points.

### Model selection (Track A in `system-roadmap.md`; gated in order)

1. **WS1 — hardware-fit selector. ✅ done 2026-06-13.** `registry/vram.py` (GQA-aware
   formula, data from Ollama `/api/show` + `/api/tags`, `/api/ps` ground-truth) +
   `cli/model_fit.py` + `make model-fit` + `tests/test_vram.py` (13 green). Budget reads
   `gpu_vram_gb` from `environments.yaml`. Confirmed live: 30B-class fit, 70B does not.
   (Built on Ollama metadata instead of wrapping quantest — same GGUF fields, no Go-binary dep.)
2. **WS2 — fix the scout. ✅ done 2026-06-13.** Rewrote `model_scout.py`: fixed the dead
   source-gate, dropped the archived HF leaderboard + AA-shaped score keys; keyless-first
   sources (Aider polyglot + Ollama tags, AA optional via `AA_API_KEY`); every candidate
   annotated with the WS1 fit gate. `tests/test_model_scout.py` (6 green). Live run surfaced
   that the 30B incumbents need ~39k ctx (not 64k) to fit the 4090.
3. **WS3 — evaluate upgrades. ✅ already built (no new code).** The `model` target was already
   wired end to end: `harness_library.ModelHarness` (deterministic stand-in), the generic model
   promotion adapter, `EXP-model-ref` in `configs/improvement-targets.yaml`, and
   `test_all_target_types.py::test_target_type_full_lifecycle` (parametrized over model). Also
   deleted the dead `llama3-groq-tool-use:70b`. **Remaining real work:** a LIVE-model A/B harness
   (real Ollama inference, currently env-blocked) + a pulled candidate. Until then the working,
   human-gated upgrade path is `make models-canary ROLE=… MODEL=ollama_chat/<tag>` → `make evals`
   → `make models-promote`.
4. **Routing check. ✅ done 2026-06-13.** Confirmed coding is executor-driven (Claude primary,
   Codex cross-provider fallback "if Claude stalls"); local models never do primary coding, so
   they can't flail; `stuck-escalation` escalates *judging* to a stronger local `architect-judge`.
   Added judge-route cross-ref validation to `check_cross_refs.py` (a typo'd `escalation_role` was
   previously unchecked) + `tests/test_routing.py` (5 green).
5. **WS4 — Hermes spike. ✅ ran 2026-06-13 → DEFER (do not adopt).** Installed v0.16.0 in an
   isolated uv venv (`C:\tmp\hermes-spike`, since removed), pointed at host Ollama `:11434` direct
   (provider `custom`), no keys/`.env`/Nous login. **Cross-session memory: PASS** (fresh session
   recalled the taught fact; artifact `memories/MEMORY.md` verified) — but it's a local `MEMORY.md`,
   the same pattern this stack already uses. **Self-improving skills: FAIL** — the curator found
   "no candidates" and auto-created 0 skills (explicit authoring works, but that's not the claim).
   Gates 1 & 3 of the adoption rubric fail → DEFER. Evidence + disposition:
   `evaluation/capability-assessment/hermes/DECISION.md`. Tested `safety_preflight.py` (9 green)
   was corrected to the REAL v0.16.0 schema (the drafted `data_collection` key doesn't exist).
   Note: a pre-existing retrieval-equivalence test (`runner.py:452`) flakes when the IDE/linter
   writes files mid-test — fail-loud-on-changed-corpus is by design; passes on a clean retry.

## Honest scope notes (carried from growth-os-system)

- **AppFlowy in-app AI is blocked on this machine**, not configured away: the server AI
  container needs an OpenAI key (no base-URL override in shipped compose) and the desktop
  Local-AI path white-screens on this GPU/driver. Assistant + MCP + boards cover the same
  asks; revisit when upstream moves.
- **Claude mobile remote connectors run from Anthropic's cloud** — they can't reach a
  tailnet-only URL, and public Funnel is on the do-not-build list. Phone control today =
  AppFlowy boards (drag to approve) + chat channels.
- Everything lives on the Windows workstation; the Linux migration runbook is
  `appflowy_kanban/growth-os/deploy/linux/MIGRATION.md`.

## Known non-goals (don't cargo-cult)

- The forecasting-pipeline standards in `docs/reference/betts-basketball-standards/`
  (R2 locks, DAG run-location, medallion layers, GPU training, dbt, champion promotion)
  **do not apply** to this control plane — see `MASTER.md` §13.1. Only the git
  multi-session rules and the engineering standards transfer.
