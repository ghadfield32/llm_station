# life-center-infra (design seed)

> **This is a seed, not a running deployment.** It is a self-contained skeleton of
> the future **private** `life-center-infra` repository described in
> [`docs/operations/HARDWARE_AND_LIFE_CENTER_PLAN.md`](../docs/operations/HARDWARE_AND_LIFE_CENTER_PLAN.md).
> It intentionally lives *outside* the `llm_station` main Compose stack. Before any
> real personal data is admitted, **extract this directory into its own private
> git repository** and complete the Gate 0/1 exits and the
> [`LIFE_CENTER_SECURITY_BASELINE.md`](../docs/operations/LIFE_CENTER_SECURITY_BASELINE.md)
> gates. Nothing here contains secrets — only `.env.example` references.

## What this delivers

A CasaOS-style **one-command** experience for the open-source Life Center
portfolio, **without** ceding authority to a launcher that hides the real
configuration. The authoritative installer is an idempotent **`lc` CLI** that
mirrors the `llm_station` `cc` CLI + `Makefile` idiom
(`doctor -> setup -> bootstrap -> up -> health`). Docker Compose, secrets, and
backups stay the single source of truth.

[Dockge](https://github.com/louislam/dockge) is bundled as an **optional
admin pane**, but it is **not** foundation and **not** read-only. It has
Docker Engine API access via the mounted socket — Docker's own docs note the
daemon normally runs with root-equivalent host privilege, and mounting the
socket `:ro` only blocks filesystem-style writes to the socket *path*, not API
calls over it. A container that can reach the socket at all is
privilege-equivalent to root on this machine. So Dockge lives in its own
`admin-gui` tier: start it only to do human administration
(`lc gui`), then stop it (`lc down --profile admin-gui`). Never expose it
beyond the management tailnet/VLAN; never let an agent or the Life Center MCP
reach it.

See the doc's
[One-command bootstrap and optional launcher](../docs/operations/HARDWARE_AND_LIFE_CENTER_PLAN.md#one-command-bootstrap-and-optional-launcher)
section for the comparison (CasaOS vs Umbrel/Runtipi vs Cosmos vs Dockge) and
the rationale.

## One command (the everyday production interface)

```bash
# Bring up the foundation (monitoring + backups only — Dockge is separate)
./lc first-boot

# Then admit tiers by what they actually are, one gate at a time:
./lc up --profile core        # Nextcloud + Immich + Paperless-ngx
./lc up --profile media       # Jellyfin + Audiobookshelf
./lc up --profile ebooks      # Calibre-Web — ONLY if you actually need OPDS/
                               # metadata editing/conversion beyond Audiobookshelf
./lc up --profile lifestyle   # Linkwarden + FreshRSS + Mealie + Homebox + Stirling-PDF
./lc up --profile finance     # Actual Budget — sensitive-data gate
./lc up --profile network     # AdGuard Home — household DNS-recovery gate
./lc up --profile smart-home  # Home Assistant (convenience container; see note below)
./lc up --profile vault       # Vaultwarden — admitted last
./lc gui                      # Dockge — privileged, human-only, on demand
```

`core`/`all`/`everything` are convenience aliases, not new authorities —
`files`/`photos`/`docs` stay individually admissible too (the plan's
"admit one at a time" gate).

On Windows use `lc.ps1` (`.\lc.ps1 first-boot`); on any platform with Python you
can call `python lc.py first-boot`. `make first-boot` is the Makefile mirror.

## Why `all` isn't literally everything

`lc up --profile all` brings up the non-sensitive, non-conditional app tiers
(`core` + `media` + `lifestyle`) in one command. Excluded from `all`, each
needing an explicit `--profile`:

| Tier | Why excluded |
| --- | --- |
| `ebooks` | conditional — off by default; enable only when justified (real Calibre DB, OPDS, metadata editing, conversion) |
| `finance` | sensitive financial data |
| `network` | household DNS dependency |
| `smart-home` | physical-home dependency |
| `vault` | critical identity dependency, admitted last |
| `admin-gui` | privileged host administration (Docker socket access) |

For your own **pre-purchase evaluation** on a desktop, with dummy/sample data,
`lc up --profile everything` brings up literally every tier in one command —
that's the disposable proof-of-concept mode described below, not the day-to-day
production interface once this becomes the real appliance.

## Desktop proof-of-concept trial (before buying Life Center hardware)

The plan explicitly allows this: *"home services may be tested on the desktop
with noncritical sample data"* before the real appliance exists. Use this to
decide what you actually want before spending money on hardware.

```bash
./lc setup                    # generates .env with local secrets (once)
./lc up --profile everything  # foundation + every tier, dummy data only
./lc health                   # confirm containers are healthy
```

Then open each app's URL (below) and try it with sample data. When you're done
evaluating (or want to reclaim disk):

```bash
./lc down --profile everything   # stop everything (foundation stays up)
./lc down --profile foundation   # stop monitoring/backups too
```

**On this desktop specifically:** `.env`'s `LC_DATA`/`LC_APPDATA` point at
`./testdata/` (relative, disposable, gitignored) instead of the real `/tank` —
that mount doesn't exist until the actual Life Center host is built. Postgres
data directories and Nextcloud's application code are **named Docker
volumes**, not host bind mounts — on Windows/Docker Desktop, bind-mounting an
app's first-boot file unpack (tens of thousands of small files) or a Postgres
data directory across the WSL2↔Windows filesystem boundary is catastrophically
slow and can hang indefinitely. Only genuine user data (photos, documents,
media) stays on a host bind mount, under `./testdata/data/`, so you can browse
it in Explorer.

**Ports** are chosen to avoid the `llm_station` main stack (litellm 4000,
ledger 8091, judge-gate 8088, uptime-kuma 3001, agent-kanban-ui 8787, airflow
8080/8090) and common desktop stacks (traefik 8081/8095). If you run other
Docker stacks, `docker ps` before bringing tiers up and adjust `.env` if needed.

**Disk:** this pulls roughly 15 images. Check free space first — the plan's own
Gate 0 audit already flagged this desktop as tight on space. `docker system df`
and `Get-PSDrive C` before and after each batch.

### URLs (all loopback; open in a browser)

Don't keep this table in your head — `lc links [--profile <tier>]` prints
every admitted service's URL, docs link, runbook, and credential **reference
name** (never a value) straight from the version-controlled catalog
(`catalog.py`). The table below is a static snapshot for quick reference.

| App | URL | Notes |
| --- | --- | --- |
| Dockge (`admin-gui`, privileged) | <http://127.0.0.1:5001> | human-only, on demand — `lc down --profile admin-gui` when done |
| Uptime Kuma | <http://127.0.0.1:3011> | Set up a monitor per app once they're up |
| Nextcloud | <http://127.0.0.1:8085> | admin / see `NEXTCLOUD_ADMIN_PASSWORD` in `.env` |
| Immich | <http://127.0.0.1:2283> | first run: create an account in-app |
| Jellyfin | <http://127.0.0.1:8096> | first run: setup wizard |
| Audiobookshelf | <http://127.0.0.1:13378> | first run: setup wizard |
| Calibre-Web (`ebooks`, conditional) | <http://127.0.0.1:8083> | default admin/admin123 — change immediately |
| Paperless-ngx | <http://127.0.0.1:8000> | create a superuser: see runbook |
| Linkwarden | <http://127.0.0.1:3010> | first run: create an account in-app |
| FreshRSS | <http://127.0.0.1:8082> | first run: setup wizard |
| Mealie | <http://127.0.0.1:9925> | default changeme@example.com / MyPassword |
| Homebox | <http://127.0.0.1:7745> | first run: create an account in-app |
| Stirling-PDF | <http://127.0.0.1:8084> | no login by default |
| Actual Budget (`finance`, sensitive) | <http://127.0.0.1:5006> | see `ACTUAL_PASSWORD` in `.env` |
| AdGuard Home (`network`, sensitive) | <http://127.0.0.1:3000> | **do not** point your system DNS at it during a trial |
| Home Assistant (`smart-home`, sensitive) | <http://127.0.0.1:8123> | convenience container only — see compose/smart-home.yml note |
| Vaultwarden (`vault`, sensitive) | <http://127.0.0.1:8222> | evaluation only — do not put real credentials in a trial vault |

## Operator commands

```bash
./lc links [--profile <tier>]   # URL/docs/runbook/credential-NAME per service, never a value
./lc verify [--profile <tier>]  # health + HTTP reachability + image-pinning + exposure posture
```

`lc verify` only reports what it actually checked — container health, HTTP
reachability, `@sha256` digest pinning, loopback-only port exposure. Anything
not yet automated (default-credential detection, registration-closed state,
export freshness, backup age, last clean-restore-test age) is listed as
**not automated — see runbook**, never faked as a pass. "Installed and starts
successfully" is not the same as admitted — see `runbooks/app-admission.md`
for the actual completion gate (import, backup, clean restore, upgrade,
rollback, client access, export all proven).

## Layout

| Path | Purpose |
| --- | --- |
| `lc.py` / `lc` / `lc.ps1` | the bootstrap CLI (dict-dispatch, shells out to `docker compose`) |
| `catalog.py` | typed, version-controlled service catalog backing `lc links` |
| `Makefile` | composite-target mirror of the CLI |
| `.env.example` | grouped env references — **no secrets**; copy to `.env` (gitignored) |
| `compose/` | one Compose file per tier, loopback-bound, healthchecked, image-digest-pinnable |
| `dev-lane/open-design/` | Open Design bring-up for the desktop/laptop dev lane + `.od/` backup hook |
| `runbooks/` | backup/restore drill and per-application admission checklist |
| `policy/` | action risk tiers and versioned retention policy |

## Boundary (do not violate)

- Runs **outside** `llm_station/docker-compose.yml`; the Life Center is a separate
  infrastructure product.
- No plaintext secrets in the repo; `.env` and `secrets/` are gitignored.
  `lc links`/`lc verify` print credential **reference names** only, never values.
- Every service binds `127.0.0.1` and is reached over Tailscale (`tailscale serve`),
  not exposed publicly (no Funnel).
- Images must be pinned by `@sha256:` digest before real-data admission (the
  placeholders here use version tags with a `# pin` TODO; `lc verify` flags
  every unpinned image).
- Dockge (`admin-gui`) is privileged host administration, not a viewer — never
  bring it up as part of a default/production bundle; never expose it beyond
  the management tailnet; never let an agent or the Life Center MCP reach it.
- The status/control gateway is read-only first; any future action is a named,
  allowlisted, audited workflow — never a raw Docker socket or shell string.
- Command Center's Work Graph/Kanban is the sole task/project/life-operations
  authority — do not add Nextcloud Deck or Vikunja; that would create a second
  task authority.
