<#
  Manager for the host-side agent-session worker (`cc agent-worker`, see
  src/command_center/agent_sessions/worker_app.py). Runs on the HOST, not in
  the cockpit container — it owns real Claude/Codex SDK/CLI authentication,
  same reasoning as the existing host.docker.internal pattern for Ollama/
  AppFlowy. Binds 127.0.0.1 only; the cockpit container reaches it via
  host.docker.internal:8791 (see docker-compose.yml's agent-kanban-ui env).

  Usage (normal, non-admin PowerShell):
    .\scripts\start_agent_worker.ps1 status
    .\scripts\start_agent_worker.ps1 start
    .\scripts\start_agent_worker.ps1 stop
    .\scripts\start_agent_worker.ps1 restart
    .\scripts\start_agent_worker.ps1 autostart   # run on every login (Startup folder)

  Requires AGENT_WORKER_TOKEN in the environment or .env (LEDGER_BASE_URL
  defaults to http://localhost:8091, matching .env.example) — the worker
  itself refuses to start without a token, this script just fails the same
  way earlier with a clearer message. Generate a token with:
    uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("status", "start", "stop", "restart", "autostart")]
  [string]$Action = "status"
)
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$RepoRoot = Split-Path $ScriptDir -Parent
$Log = Join-Path $RepoRoot "agent-worker.log"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Load-DotEnv {
  # Minimal .env loader (KEY=VALUE lines, # comments) — only fills vars not
  # already set in the environment, so an explicit `$env:X=...` before
  # calling this script always wins.
  # -PathType Leaf: skip if .env is absent OR is a directory. Docker's
  # bind-mount of `./.env` (docker-compose.yml) CREATES an empty .env
  # DIRECTORY in a checkout that has no real .env file (e.g. a stacked
  # worktree used only for deployment proofs) — Get-Content on a directory
  # throws, and there's nothing to load from it anyway.
  $envFile = Join-Path $RepoRoot ".env"
  if (-not (Test-Path $envFile -PathType Leaf)) { return }
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $k, $v = $_ -split '=', 2
    $k = $k.Trim()
    if ($k -and -not (Test-Path "env:$k")) {
      [Environment]::SetEnvironmentVariable($k, $v.Trim(), "Process")
    }
  }
}

function Get-Procs {
  Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*command_center.cli.agent_worker*' }
}

function Show-Status {
  $p = @(Get-Procs)
  if ($p.Count -ge 1) {
    Write-Host "agent-worker: RUNNING ($($p.Count) process(es), pid $($p[0].ProcessId))"
  } else {
    Write-Host "agent-worker: NOT running"
  }
  if (Test-Path $Log) {
    Write-Host "last log line: $((Get-Content $Log -Tail 1))"
  }
}

function Stop-Worker {
  $p = @(Get-Procs)
  if ($p.Count -eq 0) { Write-Host "agent-worker: nothing to stop"; return }
  foreach ($proc in $p) { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue }
  Write-Host "agent-worker: stopped $($p.Count) process(es)"
}

function Start-Worker {
  $existing = @(Get-Procs)
  if ($existing.Count -ge 1) {
    Write-Host "agent-worker: already running - leaving it; use restart to bounce"
    return
  }
  Load-DotEnv
  if (-not $env:AGENT_WORKER_TOKEN) {
    throw "AGENT_WORKER_TOKEN is not set (env or .env) - refusing to start. " +
          "Generate one with: uv run python -c `"import secrets; print(secrets.token_urlsafe(48))`""
  }
  if (-not $env:LEDGER_BASE_URL) { $env:LEDGER_BASE_URL = "http://localhost:8091" }
  Start-Process -FilePath $Python `
    -ArgumentList "-m", "command_center.cli.main", "agent-worker" `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $Log `
    -RedirectStandardError "$Log.err"
  Start-Sleep -Seconds 3
  Show-Status
}

switch ($Action) {
  "status"  { Show-Status }
  "stop"    { Stop-Worker }
  "start"   { Start-Worker }
  "restart" { Stop-Worker; Start-Sleep -Seconds 2; Start-Worker }
  "autostart" {
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup "CC Agent Worker.lnk"
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $s.TargetPath = "powershell.exe"
    $s.Arguments = "-NoProfile -WindowStyle Hidden -File `"$ScriptDir\start_agent_worker.ps1`" start"
    $s.WorkingDirectory = $RepoRoot
    $s.Save()
    Write-Host "autostart: registered '$lnk' (runs on every login, no admin)"
    Write-Host "run '.\scripts\start_agent_worker.ps1 start' now to launch this session too"
  }
}
