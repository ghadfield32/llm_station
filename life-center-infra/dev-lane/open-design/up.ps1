# Open Design dev-lane bring-up (Windows). See README.md.
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = "https://github.com/nexu-io/open-design.git"
$checkout = if ($env:OPEN_DESIGN_DIR) { $env:OPEN_DESIGN_DIR } else { Join-Path $dir "open-design" }

foreach ($t in @("git", "node", "pnpm")) {
  if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { throw "[open-design] missing: $t" }
}

$agent = $null
foreach ($a in @("claude", "codex", "cursor", "gemini", "opencode", "aider")) {
  if (Get-Command $a -ErrorAction SilentlyContinue) { $agent = $a; break }
}
if ($agent) { Write-Host "[open-design] coding agent detected: $agent" }
else { Write-Host "[open-design] WARN no coding agent on PATH (BYOK API key/local model still works)" }

if (-not (Test-Path (Join-Path $checkout ".git"))) {
  Write-Host "[open-design] cloning into $checkout"
  git clone $repo $checkout
} else {
  Write-Host "[open-design] repo present; pulling latest"
  git -C $checkout pull --ff-only
}

Set-Location $checkout
Write-Host "[open-design] installing deps (pnpm install)"
pnpm install
Write-Host "[open-design] starting local canvas (see upstream README if the command changed)"
pnpm tools-dev run web
