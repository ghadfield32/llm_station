# lc.ps1 — Windows wrapper around lc.py (dev-lane / desktop use).
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command python3 -ErrorAction SilentlyContinue)
if (-not $py) { throw "python not found on PATH" }
& $py.Source (Join-Path $dir "lc.py") @args
exit $LASTEXITCODE
