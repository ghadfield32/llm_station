# One-time registration for the aggregate-only Life Center growth snapshot.
#   Enable:  pwsh -File scripts/register_life_center_growth_schedule.ps1
#   Disable: Unregister-ScheduledTask -TaskName "LLMStation-LifeCenterGrowth" -Confirm:$false
$ErrorActionPreference = "Stop"
$taskName = "LLMStation-LifeCenterGrowth"
$runner = Join-Path $PSScriptRoot "measure_life_center_growth.ps1"
$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwsh) { $pwsh = (Get-Command powershell).Source }

$action = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At 7:30PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings `
    -Description "Aggregate-only storage growth measurement for Life Center Gate 0" `
    -Force | Out-Null

Write-Host "Registered '$taskName' for 7:30 PM daily (runs when next available if missed)."
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
