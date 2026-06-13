<#
  One reusable manager for the channels gateway. No admin, no Docker build —
  it supervises the exact `python -m command_center.channels` command that
  already works, via a hidden self-restarting loop (start_gateway.cmd run by
  start_gateway.vbs), and can register itself to start on login.

  Usage (normal, non-admin PowerShell):
    .\scripts\gateway.ps1 status      # is it running? how many instances?
    .\scripts\gateway.ps1 start       # ensure exactly one running instance
    .\scripts\gateway.ps1 stop        # stop it (and the supervisor loop)
    .\scripts\gateway.ps1 restart     # stop then start
    .\scripts\gateway.ps1 autostart   # run on every login (Startup folder)

  Reusable for any service: copy this trio and change the module in
  start_gateway.cmd. `restart`/`status`/`autostart` are the repeatable verbs.
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("status", "start", "stop", "restart", "autostart")]
  [string]$Action = "status"
)
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Vbs = Join-Path $ScriptDir "start_gateway.vbs"
$Log = Join-Path (Split-Path $ScriptDir -Parent) "gateway.log"

function Get-Procs {
  # Both the python worker and its cmd supervisor loop, matched by command line.
  Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'cmd.exe'" |
    Where-Object { $_.CommandLine -and
      ($_.CommandLine -like '*command_center.channels*' -or
       $_.CommandLine -like '*start_gateway.cmd*') }
}

function Show-Status {
  $p = @(Get-Procs)
  $py = @($p | Where-Object { $_.Name -eq 'python.exe' })
  if ($py.Count -ge 1) {
    Write-Host "gateway: RUNNING ($($py.Count) python worker(s), $($p.Count) total procs)"
  } else {
    Write-Host "gateway: NOT running"
  }
  if (Test-Path $Log) {
    Write-Host "last log line: $((Get-Content $Log -Tail 1))"
  }
}

function Stop-Gateway {
  $p = @(Get-Procs)
  if ($p.Count -eq 0) { Write-Host "gateway: nothing to stop"; return }
  # Kill cmd supervisors first so the loop can't relaunch, then the workers.
  foreach ($proc in ($p | Sort-Object { $_.Name -eq 'python.exe' })) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Write-Host "gateway: stopped $($p.Count) process(es)"
}

function Start-Gateway {
  $existing = @(Get-Procs | Where-Object { $_.Name -eq 'python.exe' })
  if ($existing.Count -ge 1) {
    Write-Host "gateway: already running ($($existing.Count) worker) - leaving it; use restart to bounce"
    return
  }
  Stop-Gateway   # clear any orphaned supervisor with no worker
  Start-Process -FilePath "wscript.exe" -ArgumentList "`"$Vbs`"" -WindowStyle Hidden
  Start-Sleep -Seconds 8
  Show-Status
}

switch ($Action) {
  "status"    { Show-Status }
  "stop"      { Stop-Gateway }
  "start"     { Start-Gateway }
  "restart"   { Stop-Gateway; Start-Sleep -Seconds 2; Start-Gateway }
  "autostart" {
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup "CC Gateway.lnk"
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $s.TargetPath = $Vbs
    $s.WorkingDirectory = Split-Path $ScriptDir -Parent
    $s.Save()
    Write-Host "autostart: registered '$lnk' (runs on every login, no admin)"
    Write-Host "run '.\scripts\gateway.ps1 start' now to launch this session too"
  }
}
