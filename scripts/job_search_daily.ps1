# Daily job-search pipeline runner (host scheduler, no Airflow needed).
# Runs the full discover -> publish -> process sequence inside the running
# cockpit container, then re-sorts every card against the current standing
# answers. Registered as a Windows Scheduled Task by scripts/register_job_search_schedule.ps1.
#
# Manual run:  pwsh -File scripts/job_search_daily.ps1
$ErrorActionPreference = "Stop"
$container = "llm_station-agent-kanban-ui-1"
$logDir = Join-Path $PSScriptRoot "..\generated"
$log = Join-Path $logDir "job-search-daily.log"
$stamp = (Get-Date).ToString("s")

if (-not (docker ps --format '{{.Names}}' | Select-String -SimpleMatch $container)) {
  "$stamp  SKIP: $container is not running" | Out-File -Append $log
  exit 0
}

"$stamp  START daily pipeline" | Out-File -Append $log
# discover + publish + process (writes the internal board); --apply persists
docker exec $container python -m command_center.job_search.cli daily --apply --backend internal --executor codex 2>&1 |
  Out-File -Append $log
# re-sort so freshly discovered cards land on the right board with the current
# standing answers already applied (the cockpit reclassify endpoint, no auth on loopback)
try {
  Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8787/api/job-search/reclassify" -TimeoutSec 120 |
    ConvertTo-Json -Depth 4 | Out-File -Append $log
} catch {
  "$stamp  reclassify call failed: $_" | Out-File -Append $log
}
"$((Get-Date).ToString('s'))  DONE" | Out-File -Append $log
