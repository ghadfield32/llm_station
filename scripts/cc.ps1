Param(
  [Parameter(Position = 0)]
  [string]$Task = "help",
  [string]$Role = "",
  [string]$Model = "",
  [string]$Judge = "",
  [string]$Files = "",
  [string]$Repo = "",
  [string]$Profile = "python_ml_pipeline",
  [switch]$Apply,
  [switch]$Details,
  [switch]$Offline
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-Python {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  $VenvPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
  if (Test-Path $VenvPython) {
    & $VenvPython @Args
  } elseif (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run python @Args
  } else {
    & python @Args
  }
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Invoke-Compose {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  & docker compose @Args
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Show-Help {
  @"
Command Center Windows helper

  .\scripts\cc.ps1 init-env          Create .env with generated local secrets
  .\scripts\cc.ps1 validate          Validate configs/*.yaml
  .\scripts\cc.ps1 render            Validate and render LiteLLM config
  .\scripts\cc.ps1 schema            Render JSON Schema
  .\scripts\cc.ps1 evals             Run routing/gate eval dry-run
  .\scripts\cc.ps1 mission-dryrun    Run L0-L4 smoke missions
  .\scripts\cc.ps1 verify-base       Check digest + base secrets before bootstrap
  .\scripts\cc.ps1 verify            Check digest + all runtime keys before up
  .\scripts\cc.ps1 keys              Mint local-only LiteLLM virtual keys
  .\scripts\cc.ps1 standards-validate Validate standing engineering standards
  .\scripts\cc.ps1 forbidden-providers Assert local-only LiteLLM/provider-key boundary
  .\scripts\cc.ps1 kanban-validate  Validate AppFlowy/GrowthOS intake config
  .\scripts\cc.ps1 kanban-bridge [-Apply]
                                  Dry-run or open Ledger missions from Kanban cards
  .\scripts\cc.ps1 appflowy-audit [-Details]
                                  Read-only audit of AppFlowy board fields/views/blank rows
  .\scripts\cc.ps1 model-scout [-Offline] Write generated/model-scout-report.md
  .\scripts\cc.ps1 usage-digest      Write generated/usage-digest.md
  .\scripts\cc.ps1 usage-report      Alias for usage-digest
  .\scripts\cc.ps1 live-smoke [-Role triage] [-Model planner] [-Judge local-judge]
                                  Print real local model replies through Ollama/LiteLLM
  .\scripts\cc.ps1 compose-config    Parse docker-compose.yml
  .\scripts\cc.ps1 check             Run validate, cross-refs, render, evals, smoke
  .\scripts\cc.ps1 repo-install -Repo C:\path\repo [-Profile python_ml_pipeline]
  .\scripts\cc.ps1 bootstrap         Start first-boot LiteLLM/Postgres/Ledger
  .\scripts\cc.ps1 up                Start the full stack
  .\scripts\cc.ps1 down              Stop the stack
  .\scripts\cc.ps1 health            Check local service health endpoints
"@
}

switch ($Task.ToLowerInvariant()) {
  "help" { Show-Help }
  "init-env" { Invoke-Python "-m" "command_center.cli.init_env" }
  "validate" { Invoke-Python "-m" "command_center.cli.validate_config" }
  "cross-refs" { Invoke-Python "-m" "command_center.cli.check_cross_refs" }
  "forbidden-providers" { Invoke-Python "-m" "command_center.cli.check_forbidden_providers" }
  "schema" { Invoke-Python "-m" "command_center.cli.render_json_schema" }
  "render" {
    Invoke-Python "-m" "command_center.cli.validate_config"
    Invoke-Python "-m" "command_center.registry.render"
  }
  "evals" { Invoke-Python "-m" "command_center.cli.run_evals" }
  "verify-base" { Invoke-Python "-m" "command_center.cli.verify_env" "--mode" "base" }
  "verify" { Invoke-Python "-m" "command_center.cli.verify_env" "--mode" "full" }
  "keys" {
    Invoke-Python "-m" "command_center.cli.verify_env" "--mode" "base"
    $EnvValues = @{}
    Get-Content -LiteralPath ".env" | ForEach-Object {
      $Line = $_.Trim()
      if ($Line -and -not $Line.StartsWith("#") -and $Line.Contains("=")) {
        $Parts = $Line.Split("=", 2)
        $EnvValues[$Parts[0]] = $Parts[1]
      }
    }
    $Master = $EnvValues["LITELLM_MASTER_KEY"]
    if (-not $Master) {
      Write-Error "LITELLM_MASTER_KEY missing from .env"
      exit 1
    }
    $Headers = @{ Authorization = "Bearer $Master" }
    $HermesBody = @{
      key_alias = "hermes-orchestrator"
      models = @("triage", "planner", "coder", "architect-judge", "security-judge", "local-judge")
      metadata = @{ routing = "local-only" }
      rpm_limit = 60
      max_parallel_requests = 4
    } | ConvertTo-Json -Depth 5
    $JudgeBody = @{
      key_alias = "judge-gate"
      models = @("triage", "planner", "architect-judge", "security-judge", "local-judge")
      metadata = @{ routing = "local-only" }
      rpm_limit = 120
      max_parallel_requests = 4
    } | ConvertTo-Json -Depth 5
    Write-Host "hermes-orchestrator:"
    Invoke-RestMethod -Method Post -Uri "http://localhost:4000/key/generate" -Headers $Headers -ContentType "application/json" -Body $HermesBody | ConvertTo-Json -Depth 8
    Write-Host "judge-gate:"
    Invoke-RestMethod -Method Post -Uri "http://localhost:4000/key/generate" -Headers $Headers -ContentType "application/json" -Body $JudgeBody | ConvertTo-Json -Depth 8
    Write-Host "paste BOTH keys above into .env as HERMES_LITELLM_KEY / JUDGE_GATE_LITELLM_KEY"
  }
  "compose-config" { Invoke-Compose "config" }
  "env-smoke" {
    Invoke-Python "-c" "import yaml; from command_center.schemas import EnvironmentsConfig; EnvironmentsConfig.model_validate(yaml.safe_load(open('configs/environments.yaml'))); print('env-smoke: PASS')"
  }
  "proactive-validate" {
    Invoke-Python "-c" "import yaml; from command_center.schemas import ProactiveConfig; ProactiveConfig.model_validate(yaml.safe_load(open('configs/proactive.yaml'))); print('proactive-validate: PASS')"
  }
  "proactive-smoke" {
    Invoke-Python "-c" "import yaml; from command_center.schemas import ProactiveConfig; c=ProactiveConfig.model_validate(yaml.safe_load(open('configs/proactive.yaml'))); [print(f'  {x.name:34s} {x.schedule:14s} on_fail={x.on_fail:18s} max={x.auto_patch_max_risk.value}') for x in c.runtime_checks+c.repo_stewardship]; print('proactive-smoke: PASS')"
  }
  "targets-validate" {
    Invoke-Python "-c" "import yaml; from command_center.schemas import TargetsConfig; TargetsConfig.model_validate(yaml.safe_load(open('configs/targets.yaml'))); print('targets-validate: PASS')"
  }
  "kanban-validate" {
    Invoke-Python "-c" "import yaml; from command_center.schemas import KanbanConfig; KanbanConfig.model_validate(yaml.safe_load(open('configs/kanban.yaml'))); print('kanban-validate: PASS')"
  }
  "kanban-bridge" {
    $BridgeArgs = @("-m", "command_center.cli.kanban_bridge")
    if ($Apply) { $BridgeArgs += "--apply" }
    Invoke-Python @BridgeArgs
  }
  "appflowy-audit" {
    $GrowthRoot = Join-Path (Get-Location) "appflowy_kanban\growth-os"
    $GrowthPython = Join-Path $GrowthRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $GrowthPython)) {
      Write-Error "missing GrowthOS venv: $GrowthPython"
      exit 1
    }
    Push-Location $GrowthRoot
    try {
      $env:PYTHONPATH = (Get-Location).Path
      $AuditArgs = @("scripts/audit_workspace.py")
      if ($Details) { $AuditArgs += "--details" }
      & $GrowthPython @AuditArgs
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
      Pop-Location
    }
  }
  "tools-validate" {
    Invoke-Python "-c" "import yaml; from command_center.schemas import ToolsConfig; ToolsConfig.model_validate(yaml.safe_load(open('configs/tools.yaml'))); print('tools-validate: PASS')"
  }
  "ui-validate" {
    Invoke-Python "-c" "import yaml; from command_center.schemas import UIConfig; UIConfig.model_validate(yaml.safe_load(open('configs/ui.yaml'))); print('ui-validate: PASS')"
  }
  "standards-validate" {
    Invoke-Python "-c" "import yaml; from command_center.schemas import StandardsConfig; StandardsConfig.model_validate(yaml.safe_load(open('configs/standards.yaml'))); print('standards-validate: PASS')"
  }
  "model-scout" {
    $ScoutArgs = @("-m", "command_center.registry.model_scout", "--output", "generated/model-scout-report.md")
    if ($Offline) { $ScoutArgs += "--offline" }
    $VenvPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
      & $VenvPython @ScoutArgs
    } elseif (Get-Command uv -ErrorAction SilentlyContinue) {
      & uv run python @ScoutArgs
    } else {
      & python @ScoutArgs
    }
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "model-scout completed with source errors; review generated/model-scout-report.md"
      $global:LASTEXITCODE = 0
    } else {
      Write-Host "review generated/model-scout-report.md, then edit configs/models.yaml manually if warranted"
    }
  }
  "usage-digest" {
    Invoke-Python "-m" "command_center.cli.usage_digest" "--output" "generated/usage-digest.md"
  }
  "usage-report" {
    Invoke-Python "-m" "command_center.cli.usage_digest" "--output" "generated/usage-digest.md"
  }
  "live-smoke" {
    $SmokeArgs = @("-ExecutionPolicy", "Bypass", "-File", "scripts/live_smoke.ps1")
    if ($Role) { $SmokeArgs += @("-TriageAlias", $Role) }
    if ($Model) { $SmokeArgs += @("-PlannerAlias", $Model) }
    if ($Judge) { $SmokeArgs += @("-JudgeAlias", $Judge) }
    & powershell @SmokeArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
  "repo-install" {
    if (-not $Repo) {
      Write-Error "usage: .\scripts\cc.ps1 repo-install -Repo C:\path\repo [-Profile python_ml_pipeline]"
      exit 1
    }
    Copy-Item -LiteralPath "repo-template/.pre-commit-config.yaml", "repo-template/CODEOWNERS" -Destination $Repo -Force
    Copy-Item -LiteralPath "repo-template/.github", "repo-template/scripts", "repo-template/.devcontainer" -Destination $Repo -Recurse -Force
    Invoke-Python "-m" "command_center.cli.render_standards" $Profile $Repo
    Write-Host "installed into $Repo"
  }
  "mission-dryrun" {
    foreach ($Tier in @("L0", "L1", "L2", "L3", "L4")) {
      Invoke-Python "-m" "command_center.cli.smoke_mission" $Tier "demo" "smoke"
      Write-Host ""
    }
  }
  "check" {
    Invoke-Python "-m" "command_center.cli.validate_config"
    Invoke-Python "-m" "command_center.cli.check_cross_refs"
    Invoke-Python "-m" "command_center.registry.render"
    Invoke-Python "-m" "command_center.cli.check_forbidden_providers"
    Invoke-Python "-m" "command_center.cli.render_json_schema"
    Invoke-Python "-m" "command_center.cli.run_evals"
    foreach ($Tier in @("L0", "L1", "L2", "L3", "L4")) {
      Invoke-Python "-m" "command_center.cli.smoke_mission" $Tier "demo" "smoke"
    }
  }
  "bootstrap" {
    Invoke-Python "-m" "command_center.cli.verify_env" "--mode" "base"
    Invoke-Python "-m" "command_center.registry.render"
    Invoke-Compose "up" "-d" "litellm-db" "litellm" "ledger"
  }
  "up" {
    Invoke-Python "-m" "command_center.cli.verify_env" "--mode" "full"
    Invoke-Python "-m" "command_center.registry.render"
    Invoke-Compose "up" "-d"
  }
  "down" { Invoke-Compose "down" }
  "health" {
    $LedgerUrl = $env:LEDGER_BASE_URL
    if (-not $LedgerUrl) {
      $LedgerUrl = "http://localhost:8091"
    }
    foreach ($Svc in @(
      @{Name = "litellm"; Url = "http://localhost:4000/health/liveliness"},
      @{Name = "judge-gate"; Url = "http://localhost:8088/health"},
      @{Name = "ledger"; Url = "$LedgerUrl/health"}
    )) {
      try {
        Invoke-WebRequest -UseBasicParsing -Uri $Svc.Url -TimeoutSec 5 | Out-Null
        "{0,-12} OK" -f $Svc.Name
      } catch {
        "{0,-12} DOWN" -f $Svc.Name
      }
    }
  }
  default {
    Write-Error "unknown task '$Task'. Run .\scripts\cc.ps1 help"
    exit 1
  }
}
