# Remote access — Option C (desktop-hosted + Tailscale, no VPS)

_Decided 2026-06-13._ The control plane runs entirely on the **4090 desktop**
("vengeance"); you reach it from your phone/laptop over **Tailscale**. No VPS.
Cost $0. The one trade-off: surfaces only respond while the desktop is powered
and awake (see "Keep it awake"). Revisit a VPS only if you need 24/7 response
while the desktop is off, want internet-facing services off your home network,
or need WhatsApp's public webhook. See [system-roadmap.md](../reviews/system-roadmap.md) for
the full VPS-vs-desktop trade-off.

## Tailnet

- Tailnet: `taile6a055.ts.net` (MagicDNS + HTTPS enabled).
- Desktop "vengeance" = `100.96.18.108` — hosts everything.
- On the tailnet: `iphone-12` (your phone), `msi` (laptop). Install the
  Tailscale app and sign in as `ghadfield32@` on any new device to add it.
  **Being signed in is not enough — the Tailscale VPN must be actively
  connected (toggle ON) for the tailnet URLs to resolve.** A phone that goes
  "offline" in `tailscale status` cannot reach any `*.taile6a055.ts.net`
  surface (Serve is tailnet-only), which surfaces in the AppFlowy mobile app
  as **"can't sync."** See "Phone can't sync" below.
- **Security posture:** every service binds `127.0.0.1` (localhost only — nothing
  on your LAN or the public internet). Tailscale **Serve** exposes a service to
  the **tailnet only** (your devices). Never use `tailscale funnel` (public) — it's
  on the do-not-build list.

## Access map (from any tailnet device)

| Surface | Local port | Tailnet URL | Status |
|---|---|---|---|
| AppFlowy (boards/knowledge) | 8081 | **https://vengeance.taile6a055.ts.net** | ✅ served + verified reachable |
| Airflow (DAGs) | 8090 | https://vengeance.taile6a055.ts.net:8443 | ✅ served + verified (2026-06-13) |
| Ledger (missions/audit) | 8091 | https://vengeance.taile6a055.ts.net:10000 | ✅ served + verified (2026-06-13) |
| LiteLLM (gateway/usage) | 4000 | https://vengeance.taile6a055.ts.net:11000 | ✅ served + verified (2026-06-13) |
| Uptime Kuma (health) | 3001 | https://vengeance.taile6a055.ts.net:12000 | ✅ served + verified (2026-06-13) |

**Phone now:** with the Tailscale app connected, open
`https://vengeance.taile6a055.ts.net` in Safari → AppFlowy boards. That's the
"anywhere" surface for approving cards. Discord/Telegram/Slack also work from the
desktop behind NAT (outbound) — no Serve needed for chat.

### Dashboards over the tailnet (all four are served as of 2026-06-13)

AppFlowy owns `/` on 443; each extra dashboard gets its own HTTPS port (tailnet-only).
These four are currently running (Tailscale 1.98 accepts arbitrary high ports):

```powershell
tailscale serve --bg --https=8443  http://127.0.0.1:8090   # Airflow  -> :8443
tailscale serve --bg --https=10000 http://127.0.0.1:8091   # Ledger   -> :10000
tailscale serve --bg --https=11000 http://127.0.0.1:4000   # LiteLLM  -> :11000
tailscale serve --bg --https=12000 http://127.0.0.1:3001   # Kuma     -> :12000
tailscale serve status                  # list what's exposed
tailscale serve --https=8443 off        # stop exposing one
```
`--bg` persists the proxy across reboots (re-served by the Tailscale service). If an
older build rejects a port, fall back to the standard Serve HTTPS ports `443 / 8443 /
10000`. Everything stays tailnet-only — never `tailscale funnel` (public, on the
do-not-build list). Each surface is operational data; turn off any you don't want on
your phone with the `off` command above.

## Packages watcher — run on the HOST (not the curator container)

The curator container can't see the repo filesystems, so dependency-drift
watching belongs on the host where the repos live. Verified working on the host:
`watching 2 repos (betts_basketball, llm_station) → 80 update rows upserted`.
Schedule it yourself (agent-created persistence is deliberately blocked):

```powershell
schtasks /create /tn "GrowthOS packages watch" /sc daily /st 06:30 /tr ^
 "cmd /c cd /d C:\Users\ghadf\vscode_projects\docker_projects\llm_station\appflowy_kanban\growth-os && set PYTHONPATH=. && .venv\Scripts\python.exe -m growthos.packages"
```

The other feeds (papers/repos/signals + guidelines + brief + retention + DAG
sync) already run in the `growthos-curator` container; the kanban bridge already
runs via the "CC kanban bridge" scheduled task.

## Keep it awake (Option C's only requirement)

Surfaces respond only while the desktop is on and not asleep. So scheduled work
and the Discord channel keep working:

```powershell
powercfg /change standby-timeout-ac 0     # never sleep on AC
powercfg /change hibernate-timeout-ac 0
# (display can still sleep: powercfg /change monitor-timeout-ac 15)
```
A reboot stops the stack until Docker Desktop + the compose services restart; set
Docker Desktop to "start on login" and the curator's `restart: unless-stopped`
brings it back. If the desktop is off, nothing responds until it's back on — that
is the deliberate Option-C trade-off.

## Phone can't sync (AppFlowy mobile) — diagnosis & fix

Two independent causes were verified on 2026-06-20. The mobile "can't sync"
error and the slow desktop loads are **not the same problem**.

### Cause 1 — the phone dropped off the tailnet (this is the "can't sync")

The AppFlowy mobile app points at `https://vengeance.taile6a055.ts.net`, which
is **tailnet-only** (Serve, never Funnel). When the phone's Tailscale isn't
connected, that hostname does not resolve/route at all → the app reports
**"can't sync."** Verified state:

```text
tailscale status   →  iphone-12  iOS  offline, last seen 6 days ago
                      key expiry 2026-12-09 (NOT expired)
```

Because the node key is still valid, **no re-login is needed** — the phone just
isn't connected. Fix, in order:

1. On the iPhone, open the **Tailscale** app and toggle the VPN **ON** (the
   key-icon / "Connected" state). iOS silently drops the Tailscale VPN profile
   after backgrounding, OS updates, or Low-Power Mode — this is the usual cause.
2. Confirm it rejoined — from the desktop:

   ```powershell
   tailscale status | Select-String iphone     # should NOT say "offline"
   ```

3. In the AppFlowy mobile app, confirm the self-hosted server URL is exactly
   `https://vengeance.taile6a055.ts.net` (Settings → Cloud Settings →
   Self-hosted). Then pull-to-refresh / reopen — sync resumes.
4. **Durable fix so it doesn't silently drop again:** in the Tailscale admin
   console → Machines → `iphone-12` → **disable key expiry**, and in the iOS
   Tailscale app enable **"Run when signed in / VPN On Demand"** so the profile
   reconnects automatically. (Done in the console, not from this host.)

Server side was confirmed healthy and correctly proxied — no change needed:
Serve mapping intact (`/ → 127.0.0.1:8081`, HTTPS 200, valid `*.ts.net` cert),
MagicDNS on, and the WebSocket sync path is proxied (`location /ws`,
`proxy_read_timeout 86400s`); a desktop collab client was observed joining the
realtime session.

### Cause 2 — slow desktop loads are host contention, not AppFlowy

When the boards "take forever to load," `appflowy_cloud`'s per-request
`SELECT signature FROM af_self_host_commercial_license` (a trivial 0-row query)
was logged stalling **17–441 s** (slow_threshold 1 s). A 0-row query on a tiny
table can't be slow by plan — it is **starved** during host contention windows.
The starvation source was measured carefully (one tool disagreed with another,
so both were checked):

```text
docker stats betts...scheduler  →  spiked to ~2000% (a SPIKE sample, misleading)
in-container top (same window)  →  ~73% idle / load avg 8.1, 14.4, 17.9 (24 CPUs)
  ⇒ betts load is BURSTY (15-min avg ~17), NOT a constant 20-core pin.
WSL2 VM memory: 15.5 GB cap, ~1.5 GB free, SWAP 3.3/4.0 GB used, 25+ containers
  ⇒ steadier pressure is MEMORY/SWAP thrash, amplified by betts CPU bursts.
airflow dags list-import-errors → "No data found"  (no broken-DAG re-parse loop)
```

So the slow loads are **intermittent oversubscription** of the shared single-VM
host, not an AppFlowy defect and not a permanent betts "runaway." A long-running
manual sportsbook backfill (`manual_verify_sb_...`, 1h+ at inspection) was an
active amplifier. Data-derived fixes, highest-leverage first:

1. **Raise the WSL2 memory cap** in `C:\Users\ghadf\.wslconfig` (host has 31 GB;
   WSL2 sees only 15.5 GB and is swapping) → stops the swap thrash that drives
   the worst stalls; helps **every** stack. Needs `wsl --shutdown` (restarts all
   containers — disruptive but fast and reversible).
2. **Bound the betts scheduler** so its bursts can't starve neighbors.
   **APPLIED 2026-06-21 (live, non-disruptive):**
   `docker update --cpus 16 betts_basketball-airflow-scheduler-1` — ceiling =
   its configured `AIRFLOW__CORE__PARALLELISM=16`, leaving 8/24 cores for
   AppFlowy + neighbors. Verified `cpu.max=1600000 100000`, AppFlowy back to
   2–3 ms, scheduler load 18→4.5. **Not persistent across container recreate** —
   to persist, add `cpus: "16"` to the `airflow-scheduler` service in the
   betts_basketball compose. Remove the live cap with `docker update --cpus 0 …`.
3. Let the manual backfill finish (transient).

Tracked in [/WORKLOG.md](../WORKLOG.md); not yet applied (host-level + separate
stack — needs a decision, especially while a betts backfill is in flight).
