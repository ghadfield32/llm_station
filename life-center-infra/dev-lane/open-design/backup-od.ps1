# Back up Open Design .od/ project files to the Life Center (Class B). Windows.
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$od = if ($env:OPEN_DESIGN_OD_DIR) { $env:OPEN_DESIGN_OD_DIR } else { Join-Path $dir "open-design\.od" }
$target = if ($env:OPEN_DESIGN_BACKUP_TARGET) { $env:OPEN_DESIGN_BACKUP_TARGET } else { "\\life-center\tank\models-archive\open-design" }

if (-not (Test-Path $od)) { throw "[open-design] no .od/ at $od — run up.ps1 first" }
New-Item -ItemType Directory -Force -Path $target | Out-Null
Write-Host "[open-design] syncing $od -> $target"
robocopy $od $target /MIR /NFL /NDL /NJH /NJS | Out-Null
Write-Host "[open-design] done. Ensure $target is included in the restic 3-2-1 job."
