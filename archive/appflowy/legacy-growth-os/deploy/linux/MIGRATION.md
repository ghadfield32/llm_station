# Migrating Growth OS to `betts-airflow-prod-01` (+ Tailscale HTTPS)

The stack currently runs on **VENGEANCE** (this Windows box — note: the
tailnet machine list calls the Windows machine `msi`; verify which physical
machine is which before assuming). The Linux box is the right long-term home:
always-on, no Docker Desktop, native systemd timers.

I could not run this remotely (SSH to the prod box was not authorized), so
this is a copy-paste runbook. Data is young, so it's a fresh stand-up, not a
volume migration. Budget ~30 minutes.

## 0. Preflight on the Linux box

```bash
free -h          # want ~4GB headroom (AppFlowy stack uses ~2-3GB)
df -h /          # want ~10GB free
docker --version && docker compose version
tailscale status # should already be on the tailnet
```

## 1. Copy the two folders over

From this Windows machine (Tailscale must be installed here first, or use scp
over LAN):

```powershell
scp -r c:\Users\ghadf\vscode_projects\docker_projects\llm_station\appflowy_kanban\AppFlowy-Cloud  user@betts-airflow-prod-01:~/appflowy/AppFlowy-Cloud
scp -r c:\Users\ghadf\vscode_projects\docker_projects\llm_station\appflowy_kanban\growth-os       user@betts-airflow-prod-01:~/appflowy/growth-os
```

Exclude `growth-os/.venv` and `growth-os/_state` (Windows venv is useless on
Linux; state restarts clean). `AppFlowy-Cloud/.env` carries the secrets — fine
to reuse them, or regenerate.

## 2. Point the stack at the tailnet HTTPS name

In the Tailscale **admin console → DNS**: enable **MagicDNS** and **HTTPS
certificates** (one-time, per tailnet).

Edit `~/appflowy/AppFlowy-Cloud/.env`:

```bash
FQDN=betts-airflow-prod-01.<your-tailnet>.ts.net   # tailscale status shows the full name
SCHEME=https
WS_SCHEME=wss
NGINX_PORT=127.0.0.1:8080        # loopback only - tailscale serve fronts it
NGINX_TLS_PORT=127.0.0.1:8443
```

(`APPFLOWY_BASE_URL`, `API_EXTERNAL_URL`, `APPFLOWY_WEB_URL` all derive from
FQDN/SCHEME in that file already.) The GoTrue admin quirk applies unchanged:
`GOTRUE_ADMIN_EMAIL=admin@example.com` stays a *system* account; your gmail is
the real user you sign up in step 4.

## 3. Stand up AppFlowy + Tailscale Serve

```bash
cd ~/appflowy/AppFlowy-Cloud
docker compose up -d nginx minio postgres redis gotrue appflowy_cloud admin_frontend appflowy_worker appflowy_search appflowy_web
# TLS-terminated, tailnet-only (do NOT use `tailscale funnel` - that is public):
sudo tailscale serve --bg https / http://127.0.0.1:8080
curl -s https://betts-airflow-prod-01.<tailnet>.ts.net/api/health   # expect 200
```

## 4. Recreate the user, databases, and curator

```bash
cd ~/appflowy/growth-os
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then edit:
#   APPFLOWY_BASE_URL=http://127.0.0.1:8080   <- INTERNAL url for the curator
#   APPFLOWY_EMAIL / APPFLOWY_PASSWORD = your gmail + a password
#   OLLAMA_BASE_URL=http://<gpu-box-tailnet-name>:11434   (see step 6)
#   GROWTHOS_DRY_RUN=false

# sign up the regular user (autoconfirm is on), then verify + get workspace id:
curl -s -X POST http://127.0.0.1:8080/gotrue/signup \
  -H 'content-type: application/json' \
  -d '{"email":"ghadfield32@gmail.com","password":"<password>"}'
PYTHONPATH=. .venv/bin/python scripts/bootstrap_appflowy.py   # 401? run the verify flow: login -> GET /api/user/verify/<token>
# put APPFLOWY_WORKSPACE_ID in .env, then:
PYTHONPATH=. .venv/bin/python scripts/setup_workspace.py      # creates the 8 DBs -> config/databases.json
.venv/bin/python -m growthos.curate                            # first live run
```

Important: the curator talks to AppFlowy via the **internal** loopback URL;
only phones/laptops use the `https://…ts.net` name. Two URLs, by design —
keep it that way or GoTrue token redirects break.

## 5. systemd timers (replaces the container sleep-loop)

```bash
sudo cp deploy/linux/systemd/*.{service,timer} /etc/systemd/system/
# edit the three .service files first: set User= and the WorkingDirectory= paths
sudo systemctl daemon-reload
sudo systemctl enable --now growthos-curate.timer growthos-brief.timer appflowy-backup.timer
systemctl list-timers 'growthos*' 'appflowy*'
```

## 6. Ollama over the tailnet (scoring + brief stay smart)

Ollama (with the GPU + models) stays on the Windows box. For the Linux
curator to use it:

- On the Windows box: set the user env var `OLLAMA_HOST=0.0.0.0` and restart
  Ollama (this is the step I was not permitted to do for you). Tailscale's
  interface is covered by 0.0.0.0; Windows Firewall will prompt once.
- In the Linux `growth-os/.env`:
  `OLLAMA_BASE_URL=http://<windows-box-tailnet-name>:11434`
- If the GPU box is off, the curator logs a warning and falls back to keyword
  scoring; the brief falls back to the plain link list. Nothing breaks.

## 7. Phone

Tailscale app on the phone (same account) → AppFlowy mobile app → Settings →
Self-hosted → `https://betts-airflow-prod-01.<tailnet>.ts.net` → log in with
the gmail account. The 1-user free-tier limit is per account, not per device.

## 8. Decommission on Windows (after the Linux box is verified)

```powershell
docker stop growthos-curator
docker compose -p appflowy down       # volumes survive; add -v to delete data
```
