# Compare the first and latest aggregate-only Life Center storage snapshots.
# Reports remain local under generated/life-center-growth and contain no paths,
# filenames, file contents, credentials, or device identifiers.
param(
    [string]$HistoryPath = (Join-Path $PSScriptRoot "..\generated\life-center-growth\history.csv"),
    [string]$OutputPath = (Join-Path $PSScriptRoot "..\generated\life-center-growth\growth-report.md"),
    [int]$MinimumDays = 30
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

$baselineByTarget = @{}
foreach ($row in $baseline.Rows) { $baselineByTarget[$row.Target] = $row }
$latestByTarget = @{}
foreach ($row in $latest.Rows) { $latestByTarget[$row.Target] = $row }

$comparison = foreach ($target in ($baselineByTarget.Keys | Sort-Object)) {
    if (-not $latestByTarget.ContainsKey($target)) { continue }
    $before = $baselineByTarget[$target]
    $after = $latestByTarget[$target]
    $delta = $after.Bytes - $before.Bytes
    $annualized = if ($mature -and $elapsed.TotalDays -gt 0) {
        [math]::Round(($delta / 1GB) * (365.25 / $elapsed.TotalDays), 2)
    } else { $null }
    [pscustomobject]@{
        Target = $target
        Class = $after.Class
        BaselineGiB = [math]::Round($before.Bytes / 1GB, 2)
        LatestGiB = [math]::Round($after.Bytes / 1GB, 2)
        DeltaGiB = [math]::Round($delta / 1GB, 2)
        AnnualizedGiB = $annualized
        LatestErrors = $after.ErrorCount
    }
}

$retainedTargets = $comparison | Where-Object Class -eq "retained-review"
$retainedBaseline = ($retainedTargets | Measure-Object BaselineGiB -Sum).Sum
$retainedLatest = ($retainedTargets | Measure-Object LatestGiB -Sum).Sum
$retainedDelta = $retainedLatest - $retainedBaseline
$retainedAnnualized = if ($mature -and $elapsed.TotalDays -gt 0) {
    [math]::Round($retainedDelta * (365.25 / $elapsed.TotalDays), 2)
} else { $null }

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
$lines.Add("## Decision rule")
$lines.Add("")
if (-not $mature) {
    $lines.Add("Do not close the growth gate yet. Continue daily snapshots until the first eligible closeout date.")
} else {
    $lines.Add("Keep the 12 TB mirror when classified retained data remains below 5 TiB and annualized retained growth remains below 1.5 TiB/year. Otherwise re-run the 12 TB versus 16 TB capacity and price decision.")
}

$parent = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$lines | Set-Content -LiteralPath $outputPath -Encoding utf8
$lines
Write-Host "Growth report written to $outputPath"
