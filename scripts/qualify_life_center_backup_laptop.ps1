# Local-only evidence helper for the optional dedicated backup laptop.
# Read-only unless -RunWriteTest is explicitly supplied.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$BackupRoot,
    [switch]$RunWriteTest,
    [ValidateRange(1, 32)] [int]$WriteTestGiB = 8,
    [switch]$RecoveryKeyTested,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "..\generated\life-center-growth\laptop-qualification")
)

$ErrorActionPreference = "Stop"
$runId = [DateTimeOffset]::Now.ToString("yyyyMMdd-HHmmss")
$backupRoot = [IO.Path]::GetFullPath($BackupRoot)
if (-not (Test-Path -LiteralPath $backupRoot -PathType Container)) { throw "BackupRoot must exist." }
$root = [IO.Path]::GetPathRoot($backupRoot)
if ($root -notmatch "^[A-Za-z]:\\$") { throw "BackupRoot must be on a mounted Windows drive." }
$letter = $root.Substring(0, 1)
$volume = Get-Volume -DriveLetter $letter

$disk = [ordered]@{ health_status = "UNAVAILABLE"; operational_status = @("UNAVAILABLE"); bus_type = "UNAVAILABLE" }
try {
    $partition = Get-Partition -DriveLetter $letter
    $info = Get-Disk -Number $partition.DiskNumber
    $disk = [ordered]@{ health_status = [string]$info.HealthStatus; operational_status = @($info.OperationalStatus | ForEach-Object { [string]$_ }); bus_type = [string]$info.BusType }
} catch { }

$encryption = [ordered]@{ available = $false; volume_status = "UNAVAILABLE"; protection_status = "UNAVAILABLE"; recovery_key_tested = [bool]$RecoveryKeyTested }
try {
    $bitLocker = Get-BitLockerVolume -MountPoint $root
    $encryption.available = $true; $encryption.volume_status = [string]$bitLocker.VolumeStatus; $encryption.protection_status = [string]$bitLocker.ProtectionStatus
} catch { }

$write = [ordered]@{ requested = [bool]$RunWriteTest; completed = $false; throughput_mib_per_second = $null; test_file = $null; sha256 = $null }
if ($RunWriteTest) {
    [int64]$bytes = $WriteTestGiB * 1GB
    if ($volume.SizeRemaining -lt ($bytes + 2GB)) { throw "Insufficient free space for test plus safety margin." }
    $directory = Join-Path $backupRoot ".life-center-qualification-$runId"
    $file = Join-Path $directory "random-write-test.bin"
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $buffer = [byte[]]::new(4MB); $rng = [Security.Cryptography.RandomNumberGenerator]::Create(); $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
        $stream = [IO.FileStream]::new($file, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None, $buffer.Length, [IO.FileOptions]::WriteThrough)
        try { [int64]$remaining = $bytes; while ($remaining -gt 0) { $count = [int][math]::Min($buffer.Length, $remaining); $rng.GetBytes($buffer); $stream.Write($buffer, 0, $count); $remaining -= $count }; $stream.Flush($true) } finally { $stream.Dispose() }
    } finally { $rng.Dispose(); $watch.Stop() }
    $write.completed = $true; $write.throughput_mib_per_second = [math]::Round(($bytes / 1MB) / [math]::Max($watch.Elapsed.TotalSeconds, 0.001), 2); $write.test_file = $file; $write.sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
}

$result = [ordered]@{
    schema_version = "life-center.backup-laptop-qualification.v1"; run_id = $runId; backup_root = $backupRoot
    volume = [ordered]@{ filesystem = [string]$volume.FileSystem; size_gib = [math]::Round($volume.Size / 1GB, 2); free_gib = [math]::Round($volume.SizeRemaining / 1GB, 2) }
    disk = $disk; encryption = $encryption; write_test = $write
    qualification_status = "NOT_QUALIFIED_PENDING_SMART_APPEND_ONLY_RESTORE_OFFSITE_AND_LOCATION_EVIDENCE"
    required_manual_checks = @("SMART short/long and read/surface tests pass.", "Battery, adapter, cooling, reboot, patches, firewall, and suspend policy pass.", "Append-only writer cannot delete; offline maintainer alone can prune.", "Repository check plus file, database, writer-revocation, and B2 restores pass.", "Location is different room/building; same-home is not off-site.")
}
$outputDirectory = [IO.Path]::GetFullPath($OutputDirectory); New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputDirectory "qualification-$runId.json") -Encoding utf8
Write-Host "Local qualification evidence written to $outputDirectory"
Write-Host "Status remains NOT QUALIFIED until all manual recovery gates pass."
