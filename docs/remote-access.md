# Remote access — Option C (desktop-hosted + Tailscale, no VPS)

_Decided 2026-06-13._ The control plane runs entirely on the **4090 desktop**
("vengeance"); you reach it from your phone/laptop over **Tailscale**. No VPS.
Cost $0. The one trade-off: surfaces only respond while the desktop is powered
and awake (see "Keep it awake"). Revisit a VPS only if you need 24/7 response
while the desktop is off, want internet-facing services off your home network,
or need WhatsApp's public webhook. See [system-roadmap.md](system-roadmap.md) for
the full VPS-vs-desktop trade-off.

## Tailnet

- Tailnet: `taile6a055.ts.net` (MagicDNS + HTTPS enabled).
- Desktop "vengeance" = `100.96.18.108` — hosts everything.
- On the tailnet already: `iphone-12` (your phone), `msi` (laptop). Install the
  Tailscale app and sign in as `ghadfield32@` on any new device to add it.
- **Security posture:** every service binds `127.0.0.1` (localhost only — nothing
  on your LAN or the public internet). Tailscale **Serve** exposes a service to
  the **tailnet only** (your devices). Never use `tailscale funnel` (public) — it's
  on the do-not-build list.

## Access map (from any tailnet device)

| Surface | Local port | Tailnet URL | Status |
|---|---|---|---|
| AppFlowy (boards/knowledge) | 8081 | **https://vengeance.taile6a055.ts.net** | ✅ served + verified reachable |
| Uptime Kuma (health) | 3001 | add Serve (below) | localhost-only |
| Airflow (betts DAGs) | 8090 | add Serve | localhost-only |
| Ledger (missions/audit) | 8091 | add Serve | localhost-only |
| LiteLLM (gateway/usage) | 4000 | add Serve | localhost-only |

**Phone now:** with the Tailscale app connected, open
`https://vengeance.taile6a055.ts.net` in Safari → AppFlowy boards. That's the
"anywhere" surface for approving cards. Discord/Telegram/Slack also work from the
desktop behind NAT (outbound) — no Serve needed for chat.

### To expose a dashboard over the tailnet (optional, run yourself)

AppFlowy already owns `/` on 443. Serve each extra dashboard on its own HTTPS
port (tailnet-only). Run from an elevated shell:

```powershell
tailscale serve --bg --https=8443  http://127.0.0.1:8090   # Airflow  -> :8443
tailscale serve --bg --https=10000 http://127.0.0.1:8091   # Ledger   -> :10000
# then reach e.g. https://vengeance.taile6a055.ts.net:8443
tailscale serve status      # list what's exposed
tailscale serve --https=8443 off    # stop exposing one
```
If Tailscale rejects a port, use the standard Serve HTTPS ports `443 / 8443 /
10000` (older builds restrict to those). Only expose what you actually want on
your phone — each is operational data.

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
