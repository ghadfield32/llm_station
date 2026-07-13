# One-time: register (or refresh) the daily job-search Windows Scheduled Task.
# Runs scripts/job_search_daily.ps1 every day at 08:00 local time.
#   Enable:   pwsh -File scripts/register_job_search_schedule.ps1
#   Disable:  Unregister-ScheduledTask -TaskName "LLMStation-JobSearchDaily" -Confirm:$false
$ErrorActionPreference = "Stop"
$taskName = "LLMStation-JobSearchDaily"
$runner = Join-Path $PSScriptRoot "job_search_daily.ps1"
$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwsh) { $pwsh = (Get-Command powershell).Source }

$action = New-ScheduledTaskAction -Execute $pwsh `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
  -Settings $settings -Description "Daily job-search discover/publish/process + re-sort" -Force |
  Out-Null
Write-Host "Registered scheduled task '$taskName' — runs daily at 08:00."
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
