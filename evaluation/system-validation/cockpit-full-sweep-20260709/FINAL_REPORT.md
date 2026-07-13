# Cockpit Full Sweep — 2026-07-09

Verdict: **PASS_WITH_BLOCKERS** (all blockers are operator-only items, listed at
the end; no code or safety failures remain).

Scope: full sweep of the first-party cockpit (website + phone PWA) after the
07-08/07-09 build sessions — verification of all uncommitted work, commit
hygiene, data freshness per domain, security from every angle, chat runtime,
setup simplicity, and fixes for every adversarially-confirmed finding.

## What was verified (ground truth)

| Gate | Result | Evidence |
|---|---|---|
| job-search suite | **70/70 pass** | includes internal board, cache-io, live-sources, packet review |
| full backend suite (serial) | **860/860 pass** | 7 earlier "failures" were concurrency artifacts — two pytest processes share repo state; NEVER run pytest suites in parallel here |
| frontend | **tsc + vite build clean** | 221.61 kB bundle (67 kB gzip), 32 modules |
| configs | **26/26 validate**, cross-refs PASS, forbidden-providers PASS | `cc validate` |
| lint | PASS | `cc lint` + ruff over services/tests/dags |
| doctor | 19 PASS / 0 FAIL / 2 BLOCKED | blockers: growth-os AppFlowy env refs (optional), discord channel env ref (operator) |
| kanban | kanban-verify PASS; event-log fold live with real cards | `cc kanban-project` |
| repo autonomy | `repo-verify --repo llm_station` PASS | merge wall, gates green |
| LinkedIn | **preflight READY** | OAuth valid to 2026-08-12, member + WMS org URNs cached |

## Commits landed this sweep (in dependency order, tree now clean)

1. `14cc384` live source discovery (Jobicy/Remotive/RemoteOK), atomic caches, balanced 50/25 limits
2. `9fe126e` LLM agent writer + packet review + finalize gate (claim-validated, trace on disk)
3. `a45974a` internal (cockpit-native) job board on the BoardProvider + balanced publish
4. `8ca56da` typed domain-surfaces contract + 9-domain config
5. `8517a86` cockpit typed domains, Jobs console, chat runtime, PWA + mobile
6. `2ef1651` docs: cockpit-as-primary, mobile/PWA setup, work log, privacy gitignores
7. `ce18b33` packet endpoint tests + registry test fix
8. `f8924d3` sweep-finding fixes (below)

Kept local-only (gitignored, verified): `generated/boards/` (real job pipeline
with employment-history data), `generated/cockpit-*.png` (screenshots of the
real pipeline), `generated/chat-threads.json` (chat content), `.tmp-*/`
(browser-automation profiles — deleted, 20 orphaned Edge processes killed).

## Security sweep — all adversarially verified

- **Authority wall: PASS.** Every mutating endpoint enumerated; ACTION_VERBS
  excludes approve/merge/deploy/publish/delete; live probes on the running
  container: `approve_card` and `delete_board` → HTTP 400. Approve/kill stays
  in the signed Ledger UI (external link only). Finalize cannot reach an
  external portal; email is `recorded_only` unless SMTP env is fully set.
- **Exposure: PASS.** Every compose port binds 127.0.0.1; `tailscale serve`
  shows all six proxies "(tailnet only)"; **funnel OFF**.
- **Service worker: PASS.** `/api/*` bypassed at the first line of the fetch
  handler; static-only cache with destination allowlist; no private payloads
  offline.
- **Secrets: PASS.** No secrets in diffs/untracked/image/web; Dockerfile bakes
  no .env or data; `/api/debug/runtime` leaks paths only; data/job_search +
  generated/boards + screenshots + chat threads all confirmed gitignored.
- **Chat safety: PASS.** Live refusal probes: "approve mission + merge PR" →
  refused/routed to human; "read LITELLM_MASTER_KEY" → refused. Model roles
  validated against models.yaml; chat role is tool-safe qwen3:30b.
- **Fixed this sweep:** profile-controls PUTs now require
  `KANBAN_UI_DOMAIN_CONFIG_WRITES=1` (chat alone insufficient; negative test
  added).

## Data freshness by domain (live API)

| Domain | Origin | Count | State | Gap to close |
|---|---|---|---|---|
| Jobs | board_store (internal) | 62 real (3 fixtures retired this sweep) | FRESH — all 2026-07-09 | timestamps normalized to one UTC ISO shape (done) |
| Missions | Ledger (live) | 2 | real but stale (2026-06-12 test missions) | operator: kill/resolve T-c8e1d7d6 + T-b5f2e70f |
| Posts | fixtures (demo-labeled) | 2 | demo | bind to the AppFlowy content boards / publisher queue |
| Books | fixtures | 1 | demo | bind to Growth OS library board |
| Papers | fixtures | 1 | demo | bind to research-digest / curator feed |
| Repos | fixtures | 1 | demo | bind to repo registry + repo-verify results |
| DAGs | fixtures | 2 | demo | bind to Airflow when scheduler is running |
| Upkeep | fixtures | 1 | demo | bind to doctor/weekly checks |
| Tasks | fixtures | 1 | demo | bind to todos board |

Origin is explicit in every payload; fixture domains show the demo badge; no
fixture data can masquerade as live (and live publish paths now exclude
fixture-sourced postings by default — `--include-fixtures` to override).

## Chat integration (as requested)

Runtime = **GatewayCore + LiteLLM** (unchanged, the only brain). ORCA /
OmniAgent-Omnigent / OxyGent appear as optional specialist **handoff links**
driven purely by `*_CHAT_URL` env vars — unset renders "unlinked", never an
error, and they carry no write authority. Threads are stored server-side
(shared desktop/laptop/phone via the tailnet URL) in a gitignored runtime
file. Card-scoped chat handoff (job cards carry their context + per-card
conversation ids) was live-validated by the earlier sessions and re-probed.

## Setup simplicity (fresh user, any platform)

Minimal path (Docker + uv + Ollama + git; **node not required** — the SPA
builds inside the image):

```text
git clone --recurse-submodules <repo> && cd llm_station
uv run cc init-env
uv run cc models-light        # small-GPU profile; skip on a 24GB+ box
uv run cc start               # doctor -> build -> up -> keys -> health -> cockpit -> opens UIs
```

`cc start` now genuinely starts the cockpit (the sweep's one FAIL — the ui
profile was never passed — is fixed). Phone: install the PWA from
`https://<your-machine>.<your-tailnet>.ts.net:8787/` (Tailscale Serve;
never funnel). AppFlowy is optional at every step; docs now say so and the
mobile guide gained the .env/control-plane prerequisite.

## Fixes applied from verified findings (`f8924d3` + runtime repairs)

1. FAIL → fixed: `cc start` starts the cockpit container (ui profile).
2. Warn → fixed: profile-controls writes gated like the config editor.
3. Warn → fixed: 3 fixture cards retired from Needs Geoff via governed
   reject events; live publish paths exclude `source: fixture` by default.
4. Warn → fixed: `last_seen_at` normalized at ingest + 51 store values
   repaired to one format.
5. Warn → fixed: fixtures file comment states the public-persona intent.
6. Warn → fixed: docs (tailnet hostname note ×3 files, mobile prerequisite,
   SETUP-FROM-SCRATCH dev-only step + anchor, GETTING_STARTED --build,
   `cc open` help mentions cockpit).

## Remaining operator items (nothing blocks daily use)

1. **AppFlowy board one-time fix** (only if you keep the projection): open
   `job_search_pipeline` → Board → Group by → Status; delete the 3 blank
   starter rows (`cc job-search board-doctor` prints the steps).
2. **Stale Ledger test missions**: kill/resolve `T-c8e1d7d6` (L4 wall test)
   and `T-b5f2e70f` in the Ledger UI so Missions shows current work.
3. **Discord env ref**: set `DISCORD_ALLOWED_CHANNEL_IDS` or disable the
   channel (doctor's remaining blocker).
4. **LinkedIn**: preflight is READY — approve drafts (drag In Queue → In
   Progress) and schedule `linkedin_publish --apply` via schtasks when you
   want the queue moving.
5. **Windows-only test env notes**: `test_merge_guard` needs a POSIX bash on
   PATH (WSL bash path issue) — passes serially here, covered in CI either way.

## Suggested next build slices (ranked)

1. Bind Papers → research-digest feed and Repos → repo registry (the two
   highest-value fixture domains; both sources already exist).
2. UX polish list: desktop card density, in-lane empty-state hints, phone
   above-the-fold queue chips, drawer text clamping.
3. Bind DAGs → Airflow REST when the containerized scheduler (PR #30) merges.
4. Posts domain → live content-board binding + publisher queue view.

## Daily / weekly operator workflow

Daily: open the cockpit (desktop or phone PWA) → All Boards → Jobs: review
Suggested, drag winners to Selected by Geoff (packet prep auto-runs on drag),
work the Needs Geoff queue, mark submitted by dragging to Completed → glance
at Posts/Missions → use chat (card-scoped) for questions/drafts → approve
anything L3/L4 only in the Ledger UI.

Weekly: `uv run cc doctor` · `uv run cc validate` · `uv run cc job-search
retention --dry-run` · `uv run cc usage-digest` · `uv run cc
self-improvement-report` · review WORK_LOG.md.

Extending: new repo → `uv run cc onboard repo`; new domain/board → Controls →
All Boards schema editor (or edit `configs/domain_surfaces.yaml`) → `uv run
cc validate` → add a fixture or source binding.
