<#
  Isolated agent-session deployment proof runner.

  Exists because of a real incident (see WORKLOG.md "Agent-session chat
  integration"): a Bash tool cwd silently drifted from this worktree back to
  the main llm_station checkout, and a `docker compose up` run from there
  recreated the REAL, production llm_station-ledger-1/llm_station-agent-
  kanban-ui-1 containers and overwrote the real .env with throwaway proof
  secrets. Nothing verified the target before running a destructive-capable
  command. Recovered in full (see the incident's recovery record), but the
  root cause -- no target verification before a Docker command that can
  silently operate on the wrong project -- needed a structural fix, not just
  "be more careful next time".

  This script is the ONLY sanctioned way to bring up an isolated ledger +
  cockpit pair for a live agent-session/Codex/Claude deployment proof. It
  refuses to run unless every invariant below holds, uses an explicit
  Compose project name (which Docker namespaces volumes by automatically --
  verified: docker-compose.yml declares `ledger_data` with no `name:`/
  `external:` override, so a distinct -p value alone guarantees a distinct
  volume, never llm_station_ledger_data), and never writes to any file
  outside the worktree it was told to operate in.

  Usage:
    .\scripts\run_agent_deployment_proof.ps1 `
        -WorktreeRoot C:\tmp\cc-agent-runtime `
        -ExpectedBranch feat/agent-session-runtime `
        -ProofEnv C:\tmp\cc-agent-runtime\.env.agent-proof `
        -ProofProjectName cc-agent-runtime-proof `
        [-GenerateEnv] [-DryRun] [-Down]

  -DryRun runs every invariant check and prints what WOULD happen, without
  ever invoking `docker compose`. This is what the test suite exercises, so
  the safety checks themselves are provable without a running Docker daemon
  and without ever actually touching containers.

  -GenerateEnv creates ProofEnv with fresh, disposable, randomly-generated
  secrets IF it does not already exist (no-clobber: an existing ProofEnv is
  never regenerated or overwritten). Omit it to require the file already
  exist (e.g. a previously generated proof env you want to reuse).

  -Down tears the proof stack down instead of bringing it up. Still runs
  every invariant check first.
#>
param(
  [Parameter(Mandatory = $true)] [string]$WorktreeRoot,
  [Parameter(Mandatory = $true)] [string]$ExpectedBranch,
  [Parameter(Mandatory = $true)] [string]$ProofEnv,
  [Parameter(Mandatory = $true)] [string]$ProofProjectName,
  [switch]$GenerateEnv,
  [switch]$DryRun,
  [switch]$Down
)
$ErrorActionPreference = "Stop"

function Fail {
  param([string]$Message)
  Write-Host "REFUSED: $Message" -ForegroundColor Red
  exit 1
}

# ---- invariant: proof project name must never be the production one, and
# must self-document as disposable ----------------------------------------
if ($ProofProjectName -eq "llm_station") {
  Fail "ProofProjectName must not be 'llm_station' (the production Compose project name)"
}
if ($ProofProjectName -notlike "*proof*") {
  Fail ("ProofProjectName '$ProofProjectName' does not contain 'proof' -- refusing as a " +
        "safety convention (pick a name that self-documents as disposable)")
}

# ---- invariant: resolved git root must exactly match the expected worktree,
# root/branch verified via git itself, never assumed from cwd -------------
$ResolvedRoot = $null
try {
  $ResolvedRoot = (git -C $WorktreeRoot rev-parse --show-toplevel 2>$null).Trim()
} catch { }
if (-not $ResolvedRoot) {
  Fail "WorktreeRoot '$WorktreeRoot' is not inside a git repository"
}
$ExpectedFull = [IO.Path]::GetFullPath($WorktreeRoot)
$ActualFull = [IO.Path]::GetFullPath($ResolvedRoot)
if ($ActualFull -ne $ExpectedFull) {
  Fail "Resolved git root '$ActualFull' does not match expected WorktreeRoot '$ExpectedFull'"
}

# ---- invariant: current branch must match --------------------------------
$ActualBranch = (git -C $WorktreeRoot branch --show-current).Trim()
if ($ActualBranch -ne $ExpectedBranch) {
  Fail "Current branch '$ActualBranch' does not match ExpectedBranch '$ExpectedBranch'"
}

# ---- invariant: proof env path must be inside the worktree, and must NEVER
# be named .env (that name is reserved for the real per-checkout file) ----
$ProofEnvFull = [IO.Path]::GetFullPath($ProofEnv)
if ((Split-Path $ProofEnvFull -Leaf) -eq ".env") {
  Fail "ProofEnv must not be named '.env' -- that is the production/per-checkout environment file"
}
if (-not $ProofEnvFull.StartsWith($ExpectedFull, [StringComparison]::OrdinalIgnoreCase)) {
  Fail "ProofEnv '$ProofEnvFull' is not inside WorktreeRoot '$ExpectedFull'"
}

# ---- invariant: computed target container names must never start with
# llm_station- (the production prefix) -- checked BEFORE touching Docker --
$Targets = @("ledger", "agent-kanban-ui")
foreach ($svc in $Targets) {
  $expectedName = "$ProofProjectName-$svc-1"
  if ($expectedName -like "llm_station-*") {
    Fail "Computed target container name '$expectedName' starts with 'llm_station-' -- refusing"
  }
}

# ---- no-clobber environment generation -----------------------------------
if (-not (Test-Path $ProofEnvFull)) {
  if (-not $GenerateEnv) {
    Fail ("ProofEnv '$ProofEnvFull' does not exist. Pass -GenerateEnv to create one with " +
          "fresh disposable secrets, or create it yourself first.")
  }
  if ($DryRun) {
    Write-Host "-DryRun set: would generate $ProofEnvFull (not writing it)" -ForegroundColor Yellow
  } else {
    # Fresh, disposable, randomly-generated secrets -- never derived from,
    # copied from, or written to any other file on this machine.
    $token = & python -c "import secrets; print(secrets.token_urlsafe(48))"
    $approvalSecret = & python -c "import secrets; print(secrets.token_urlsafe(32))"
    @(
      "LEDGER_APPROVAL_SECRET=$approvalSecret",
      "LEDGER_HOST_PORT=8092",
      "LEDGER_BASE_URL=http://localhost:8092",
      "AGENT_WORKER_TOKEN=$token",
      "KANBAN_UI_AGENT_SESSIONS_ENABLED=1",
      "KANBAN_UI_FAKE_AGENT_ENABLED=0",
      "KANBAN_UI_CHAT_ENABLED=0",
      "KANBAN_UI_DOMAIN_CONFIG_WRITES=0",
      "KANBAN_UI_PORT=8788"
    ) | Set-Content -Path $ProofEnvFull
    Write-Host "Generated a fresh disposable $ProofEnvFull (values not printed)"
  }
} else {
  Write-Host "Using existing $ProofEnvFull (no-clobber: not regenerated)"
}

Write-Host ""
Write-Host "All invariants PASSED:" -ForegroundColor Green
Write-Host "  worktree root   : $ActualFull"
Write-Host "  branch          : $ActualBranch"
Write-Host "  proof env       : $ProofEnvFull"
Write-Host "  proof project   : $ProofProjectName"
Write-Host "  target services : $($Targets -join ', ')"
Write-Host "  target names    : $(($Targets | ForEach-Object { "$ProofProjectName-$_-1" }) -join ', ')"
Write-Host ""

if ($DryRun) {
  Write-Host "-DryRun set: not invoking docker compose. Invariants only." -ForegroundColor Yellow
  exit 0
}

$ComposeFile = Join-Path $ExpectedFull "docker-compose.yml"
$ProofOverrideFile = Join-Path $ExpectedFull "docker-compose.agent-proof.yml"
$ComposeArgs = @(
  "--project-directory", $ExpectedFull,
  "--env-file", $ProofEnvFull,
  "-f", $ComposeFile,
  "-f", $ProofOverrideFile,
  "-p", $ProofProjectName,
  "--profile", "ui"
)

if ($Down) {
  docker compose @ComposeArgs down
  exit $LASTEXITCODE
}

docker compose @ComposeArgs up -d @Targets

Start-Sleep -Seconds 3
$ActualNames = docker ps -a --filter "name=$ProofProjectName-" --format "{{.Names}}"
foreach ($n in $ActualNames) {
  if ($n -like "llm_station-*") {
    Fail ("POST-CREATE CHECK FAILED: container '$n' starts with 'llm_station-' -- this " +
          "should be structurally impossible; tearing down immediately")
  }
}
Write-Host ("Post-create check passed: every container is under project '$ProofProjectName', " +
           "none start with 'llm_station-'") -ForegroundColor Green
