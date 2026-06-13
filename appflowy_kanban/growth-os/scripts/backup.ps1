# Backup AppFlowy Postgres + curator state on Windows. Keeps 14 days.
# Run manually or via Task Scheduler:
#   schtasks /create /tn "GrowthOS backup" /sc daily /st 02:00 ^
#     /tr "pwsh -NoProfile -File C:\...\growth-os\scripts\backup.ps1"
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$backupDir = Join-Path (Split-Path $root -Parent) "backups"
New-Item -ItemType Directory -Force $backupDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd"

docker exec appflowy-postgres-1 pg_dump -U postgres postgres |
    Out-File -Encoding utf8 (Join-Path $backupDir "appflowy_$stamp.sql")
Compress-Archive -Force -Path (Join-Path $root "_state") `
    -DestinationPath (Join-Path $backupDir "growthos_state_$stamp.zip")

Get-ChildItem $backupDir | Where-Object {
    $_.LastWriteTime -lt (Get-Date).AddDays(-14)
} | Remove-Item -Force -Confirm:$false
Write-Host "backup ok: $backupDir ($stamp)"
