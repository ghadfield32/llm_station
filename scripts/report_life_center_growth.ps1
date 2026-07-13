# Compare the first and latest aggregate-only Life Center storage snapshots.
# Reports remain local under generated/life-center-growth and contain no paths,
# filenames, file contents, credentials, or device identifiers.
param(
    [string]$HistoryPath = (Join-Path $PSScriptRoot "..\generated\life-center-growth\history.csv"),
    [string]$OutputPath = (Join-Path $PSScriptRoot "..\generated\life-center-growth\growth-report.md"),
    [int]$MinimumDays = 30,
    [double]$PlannedNewCollectionTiB = 0
)

$ErrorActionPreference = "Stop"
$historyPath = [IO.Path]::GetFullPath($HistoryPath)
$outputPath = [IO.Path]::GetFullPath($OutputPath)
if (-not (Test-Path -LiteralPath $historyPath)) {
    throw "Growth history not found: $historyPath"
}

$rows = Import-Csv -LiteralPath $historyPath | ForEach-Object {
    [pscustomobject]@{
        Timestamp = [DateTimeOffset]::Parse($_.Timestamp)
        RunId = $_.RunId
        Target = $_.Target
        Class = $_.Class
        Exists = [bool]::Parse($_.Exists)
        Bytes = [int64]$_.Bytes
        FileCount = [int64]$_.FileCount
        ErrorCount = [int64]$_.ErrorCount
    }
}

$runs = $rows | Group-Object RunId | ForEach-Object {
    [pscustomobject]@{
        RunId = $_.Name
        Timestamp = ($_.Group | Measure-Object Timestamp -Minimum).Minimum
        Rows = $_.Group
    }
} | Sort-Object Timestamp

if ($runs.Count -lt 1) { throw "No valid snapshot runs were found." }
$baseline = $runs[0]
$latest = $runs[-1]
$elapsed = $latest.Timestamp - $baseline.Timestamp
$eligibleAt = $baseline.Timestamp.AddDays($MinimumDays)
$mature = $elapsed.TotalDays -ge $MinimumDays

$comparison = foreach ($targetRows in ($rows | Group-Object Target | Sort-Object Name)) {
    $ordered = @($targetRows.Group | Sort-Object Timestamp)
    $before = $ordered[0]
    $after = $ordered[-1]
    $targetElapsed = $after.Timestamp - $before.Timestamp
    $delta = $after.Bytes - $before.Bytes
    $annualized = if ($targetElapsed.TotalDays -ge $MinimumDays) {
        [math]::Round(($delta / 1GB) * (365.25 / $targetElapsed.TotalDays), 2)
    } else { $null }
    [pscustomobject]@{
        Target = $targetRows.Name
        Class = $after.Class
        BaselineGiB = [math]::Round($before.Bytes / 1GB, 2)
        LatestGiB = [math]::Round($after.Bytes / 1GB, 2)
        DeltaGiB = [math]::Round($delta / 1GB, 2)
        AnnualizedGiB = $annualized
        LatestErrors = $after.ErrorCount
        TargetElapsedDays = $targetElapsed.TotalDays
    }
}

$retainedTargets = $comparison | Where-Object Class -eq "retained-review"
$retainedBaseline = ($retainedTargets | Measure-Object BaselineGiB -Sum).Sum
$retainedLatest = ($retainedTargets | Measure-Object LatestGiB -Sum).Sum
$retainedDelta = $retainedLatest - $retainedBaseline
$retainedAnnualized = if (($retainedTargets | Where-Object { $_.TargetElapsedDays -lt $MinimumDays }).Count -eq 0) {
    [math]::Round(($retainedTargets | Measure-Object AnnualizedGiB -Sum).Sum, 2)
} else { $null }

function Get-ClassRollup {
    param([string]$ClassName)
    $targets = @($comparison | Where-Object Class -eq $ClassName)
    if ($targets.Count -eq 0) { return $null }
    $annualized = if (($targets | Where-Object { $_.TargetElapsedDays -lt $MinimumDays }).Count -eq 0) {
        [math]::Round(($targets | Measure-Object AnnualizedGiB -Sum).Sum, 2)
    } else { $null }
    [pscustomobject]@{
        Class = $ClassName
        LatestGiB = ($targets | Measure-Object LatestGiB -Sum).Sum
        AnnualizedGiB = $annualized
    }
}
$authoritative = Get-ClassRollup -ClassName "authoritative-retained"
$criticalBackup = Get-ClassRollup -ClassName "critical-backup"
$offsiteProtected = Get-ClassRollup -ClassName "offsite-protected"

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Life Center growth report")
$lines.Add("")
$lines.Add("**Status:** " + $(if ($mature) { "MATURE ($MinimumDays-day minimum met)" } else { "COLLECTING" }))
$lines.Add(('**Baseline:** {0} (`{1}`)  ' -f $baseline.Timestamp.ToString('o'), $baseline.RunId))
$lines.Add(('**Latest:** {0} (`{1}`)  ' -f $latest.Timestamp.ToString('o'), $latest.RunId))
$lines.Add("**Elapsed:** $([math]::Round($elapsed.TotalDays, 2)) days  ")
$lines.Add("**First eligible closeout:** $($eligibleAt.ToString('yyyy-MM-dd HH:mm zzz'))")
$lines.Add("")
$lines.Add("Targets are policy categories, not proof that every byte is durable. Envelope and runtime categories overlap retained-review categories and must not be added together.")
$lines.Add("")
$lines.Add("| Target | Class | Baseline GiB | Latest GiB | Delta GiB | Annualized GiB/year | Errors |")
$lines.Add("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
foreach ($row in $comparison) {
    $annual = if ($null -eq $row.AnnualizedGiB) { "not available" } else { $row.AnnualizedGiB.ToString("0.00") }
    $lines.Add("| $($row.Target) | $($row.Class) | $($row.BaselineGiB.ToString('0.00')) | $($row.LatestGiB.ToString('0.00')) | $($row.DeltaGiB.ToString('0.00')) | $annual | $($row.LatestErrors) |")
}
$lines.Add("")
$lines.Add("## Retained-review rollup")
$lines.Add("")
$lines.Add("The retained-review paths are distinct in the current tracker, but still require human keep/delete/reproducible classification.")
$lines.Add("")
$lines.Add("- Baseline: $([math]::Round($retainedBaseline, 2)) GiB")
$lines.Add("- Latest: $([math]::Round($retainedLatest, 2)) GiB")
$lines.Add("- Net change: $([math]::Round($retainedDelta, 2)) GiB")
$lines.Add("- Annualized change: " + $(if ($null -eq $retainedAnnualized) { "not available before the minimum interval" } else { "$retainedAnnualized GiB/year" }))
$lines.Add("")
$lines.Add("## Scoped recovery rollups")
$lines.Add("")
$lines.Add("Critical and off-site classes may overlap authoritative data, and must never be summed with it.")
foreach ($rollup in @($authoritative, $criticalBackup, $offsiteProtected)) {
    if ($null -eq $rollup) { continue }
    $annual = if ($null -eq $rollup.AnnualizedGiB) { "not available" } else { "$($rollup.AnnualizedGiB) GiB/year" }
    $lines.Add("- $($rollup.Class): $([math]::Round($rollup.LatestGiB, 2)) GiB; annualized $annual")
}
if ($null -eq $authoritative) { $lines.Add("- authoritative-retained: UNCLASSIFIED") }
if ($null -eq $criticalBackup) { $lines.Add("- critical-backup: UNCLASSIFIED") }
if ($null -eq $offsiteProtected) { $lines.Add("- offsite-protected: UNCLASSIFIED") }
$lines.Add("")
$lines.Add("## Three-year authoritative capacity forecast")
$lines.Add("")
if ($null -eq $authoritative -or $null -eq $authoritative.AnnualizedGiB) {
    $lines.Add("UNAVAILABLE: every authoritative-retained target needs 30 days of observations.")
} else {
    $forecastTiB = ($authoritative.LatestGiB / 1024) + (3 * $authoritative.AnnualizedGiB / 1024) + $PlannedNewCollectionTiB
    $lines.Add("Three-year forecast: $([math]::Round($forecastTiB, 2)) TiB")
    if ($forecastTiB -le 6.3) { $lines.Add("Drive decision: 10 TB mirror is capacity-eligible.") }
    elseif ($forecastTiB -le 7.6) { $lines.Add("Drive decision: 12 TB mirror is capacity-eligible.") }
    else { $lines.Add("Drive decision: re-price 16 TB or larger.") }
}
$lines.Add("")
$lines.Add("## Decision rule")
$lines.Add("")
if (-not $mature) {
    $lines.Add("Do not close the growth gate yet. Continue daily snapshots until the first eligible closeout date.")
} else {
    $lines.Add("Use the scoped authoritative forecast: 10 TB only at or below 6.3 TiB, 12 TB only at or below 7.6 TiB, otherwise re-price 16 TB or larger. A laptop can defer full-pool backup only for a measured critical subset below 1.2 TiB that separately passes health, restore, append-only, and off-site gates.")
}

$parent = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$lines | Set-Content -LiteralPath $outputPath -Encoding utf8
$lines
Write-Host "Growth report written to $outputPath"
