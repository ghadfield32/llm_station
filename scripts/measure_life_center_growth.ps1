# Capture aggregate-only storage measurements for the Life Center capacity gate.
# No filenames, file contents, credentials, device identifiers, or network
# addresses are written. Targets overlap intentionally and must not be summed.
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "..\generated\life-center-growth"),
    [string]$BackupScopeManifest = ""
)

$ErrorActionPreference = "Stop"
$timestamp = [DateTimeOffset]::Now
$runId = $timestamp.ToString("yyyyMMdd-HHmmss")
$outputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
if (-not $BackupScopeManifest) { $BackupScopeManifest = Join-Path $outputDirectory "backup-scope.json" }
$BackupScopeManifest = [IO.Path]::GetFullPath($BackupScopeManifest)

$homePath = $env:USERPROFILE
if (-not $homePath) {
    $homePath = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
}
if (-not $homePath) {
    throw "Unable to resolve the current user's profile directory."
}
$projects = Join-Path $homePath "vscode_projects"
$dockerProjects = Join-Path $projects "docker_projects"

$targets = @(
    @{ Name = "personal_synced"; Path = (Join-Path $homePath "OneDrive"); Class = "retained-review" },
    @{ Name = "betts_data"; Path = (Join-Path $dockerProjects "betts_basketball\data"); Class = "retained-review" },
    @{ Name = "betts_models"; Path = (Join-Path $dockerProjects "betts_basketball\models"); Class = "retained-review" },
    @{ Name = "betts_reports"; Path = (Join-Path $dockerProjects "betts_basketball\reports"); Class = "retained-review" },
    @{ Name = "betts_serving"; Path = (Join-Path $dockerProjects "betts_basketball\serving"); Class = "retained-review" },
    @{ Name = "betts_r2_mirror"; Path = (Join-Path $dockerProjects "betts_basketball\.r2_mirror"); Class = "retained-review" },
    @{ Name = "homography_data"; Path = (Join-Path $dockerProjects "bball_homography\data"); Class = "retained-review" },
    @{ Name = "homography_runs"; Path = (Join-Path $dockerProjects "bball_homography\runs"); Class = "retained-review" },
    @{ Name = "ollama_models"; Path = (Join-Path $homePath ".ollama\models"); Class = "reproducible" },
    @{ Name = "huggingface_cache"; Path = (Join-Path $homePath ".cache\huggingface"); Class = "reproducible" },
    @{ Name = "docker_runtime"; Path = (Join-Path $homePath "AppData\Local\Docker\wsl\disk\docker_data.vhdx"); Class = "runtime-envelope" }
)

# Do not recursively measure the entire project root. It contains overlapping
# repositories, generated dependencies, and junctions, so it is neither an
# authoritative capacity category nor a reliable aggregate. The named child
# targets and system-volume signal cover the planning evidence without this
# noisy envelope scan.

function Measure-Target {
    param([hashtable]$Target)

    $path = $Target.Path
    if (-not (Test-Path -LiteralPath $path)) {
        return [pscustomobject]@{
            Timestamp = $timestamp.ToString("o")
            RunId = $runId
            Target = $Target.Name
            Class = $Target.Class
            Exists = $false
            Bytes = 0
            FileCount = 0
            ErrorCount = 0
        }
    }

    $item = Get-Item -LiteralPath $path -Force
    if (-not $item.PSIsContainer) {
        return [pscustomobject]@{
            Timestamp = $timestamp.ToString("o")
            RunId = $runId
            Target = $Target.Name
            Class = $Target.Class
            Exists = $true
            Bytes = [int64]$item.Length
            FileCount = 1
            ErrorCount = 0
        }
    }

    $enumerationErrors = @()
    $measure = Get-ChildItem -LiteralPath $path -File -Recurse -Force `
        -ErrorAction SilentlyContinue -ErrorVariable +enumerationErrors |
        Measure-Object -Property Length -Sum

    [pscustomobject]@{
        Timestamp = $timestamp.ToString("o")
        RunId = $runId
        Target = $Target.Name
        Class = $Target.Class
        Exists = $true
        Bytes = [int64]($measure.Sum ?? 0)
        FileCount = [int64]$measure.Count
        ErrorCount = [int64]$enumerationErrors.Count
    }
}

function Get-BackupScopeTargets {
    param([string]$ManifestPath)
    if (-not (Test-Path -LiteralPath $ManifestPath)) { return @() }
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ($null -eq $manifest.targets -or @($manifest.targets).Count -eq 0) {
        throw "Backup scope manifest must define at least one target."
    }
    $allowedClasses = @("authoritative-retained", "critical-backup", "offsite-protected")
    $seen = @{}
    $result = foreach ($target in @($manifest.targets)) {
        $name = [string]$target.name; $class = [string]$target.class; $path = [string]$target.path
        if ($name -notmatch "^[a-z0-9][a-z0-9_-]{2,63}$") { throw "Backup target name must be a stable id: $name" }
        if ($seen.ContainsKey($name)) { throw "Duplicate backup target: $name" }
        if ($class -notin $allowedClasses) { throw "Unsupported backup target class: $class" }
        if (-not $path) { throw "Backup target $name is missing path" }
        $seen[$name] = $true
        @{ Name = $name; Class = $class; Path = $path }
    }
    return @($result)
}

$scopeTargets = Get-BackupScopeTargets -ManifestPath $BackupScopeManifest
$rows = foreach ($target in @($targets) + @($scopeTargets)) { Measure-Target -Target $target }

$drive = Get-PSDrive -Name C
$rows += [pscustomobject]@{
    Timestamp = $timestamp.ToString("o")
    RunId = $runId
    Target = "system_volume_used"
    Class = "envelope-only"
    Exists = $true
    Bytes = [int64]$drive.Used
    FileCount = 0
    ErrorCount = 0
}
$rows += [pscustomobject]@{
    Timestamp = $timestamp.ToString("o")
    RunId = $runId
    Target = "system_volume_free"
    Class = "capacity-signal"
    Exists = $true
    Bytes = [int64]$drive.Free
    FileCount = 0
    ErrorCount = 0
}

$historyPath = Join-Path $outputDirectory "history.csv"
if (Test-Path -LiteralPath $historyPath) {
    $rows | Export-Csv -LiteralPath $historyPath -NoTypeInformation -Append
} else {
    $rows | Export-Csv -LiteralPath $historyPath -NoTypeInformation
}

$latestPath = Join-Path $outputDirectory "latest.json"
$rows | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $latestPath -Encoding utf8

$summary = $rows | Select-Object Target, Class, Exists,
    @{Name="GiB"; Expression={[math]::Round($_.Bytes / 1GB, 2)}},
    FileCount, ErrorCount
$summary | Format-Table -AutoSize
if ($scopeTargets.Count -eq 0) {
    Write-Host "No backup-scope.json found; authoritative, critical, and off-site totals remain unclassified."
}
Write-Host "Aggregate snapshot $runId recorded in $outputDirectory"
