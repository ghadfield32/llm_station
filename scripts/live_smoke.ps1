Param(
  [string]$TriageAlias = "triage",
  [string]$PlannerAlias = "planner",
  [string]$JudgeAlias = "local-judge",
  [string]$LiteLLMUrl = $env:LITELLM_URL
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not $LiteLLMUrl) {
  $LiteLLMUrl = "http://localhost:4000"
}

function Fail-IfProviderEnvExists {
  $Forbidden = @("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
  foreach ($Key in $Forbidden) {
    if (Test-Path "Env:$Key") {
      Write-Host "$Key must not exist in the executor process environment. [FAIL]"
      exit 1
    }
    if ([Environment]::GetEnvironmentVariable($Key, "User")) {
      Write-Host "$Key must not exist in User environment variables. [FAIL]"
      exit 1
    }
    if ([Environment]::GetEnvironmentVariable($Key, "Machine")) {
      Write-Host "$Key must not exist in Machine environment variables. [FAIL]"
      exit 1
    }
  }
}

function Read-DotEnvValue {
  param([Parameter(Mandatory = $true)][string]$Name)
  if (-not (Test-Path -LiteralPath ".env")) {
    return ""
  }
  foreach ($Line in Get-Content -LiteralPath ".env") {
    $Trimmed = $Line.Trim()
    if (-not $Trimmed -or $Trimmed.StartsWith("#") -or -not $Trimmed.Contains("=")) {
      continue
    }
    $Parts = $Trimmed.Split("=", 2)
    if ($Parts[0] -eq $Name) {
      return $Parts[1]
    }
  }
  return ""
}

function Invoke-LiteLLMChat {
  param(
    [Parameter(Mandatory = $true)][string]$Model,
    [Parameter(Mandatory = $true)][string]$Prompt,
    [Parameter(Mandatory = $true)][string]$BearerToken
  )
  $Headers = @{
    "Content-Type" = "application/json"
    "Authorization" = "Bearer $BearerToken"
  }
  $Body = @{
    model = $Model
    messages = @(@{ role = "user"; content = $Prompt })
    max_tokens = 160
  } | ConvertTo-Json -Depth 5

  $Response = Invoke-RestMethod -Method Post -Uri "$LiteLLMUrl/v1/chat/completions" -Headers $Headers -Body $Body -TimeoutSec 120
  $Content = $Response.choices[0].message.content.Trim()
  if (-not $Content) {
    throw "LiteLLM model '$Model' returned empty content"
  }
  return $Content
}

function Assert-LiteLLMDeniesModel {
  param(
    [Parameter(Mandatory = $true)][string]$Model,
    [Parameter(Mandatory = $true)][string]$BearerToken
  )
  $Headers = @{
    "Content-Type" = "application/json"
    "Authorization" = "Bearer $BearerToken"
  }
  $Body = @{
    model = $Model
    messages = @(@{ role = "user"; content = "Reply with exactly: SHOULD-NOT-RUN" })
    max_tokens = 20
  } | ConvertTo-Json -Depth 5

  try {
    Invoke-RestMethod -Method Post -Uri "$LiteLLMUrl/v1/chat/completions" -Headers $Headers -Body $Body -TimeoutSec 60 | Out-Null
    Write-Host "forbidden model '$Model' unexpectedly succeeded [FAIL]"
    exit 1
  } catch {
    Write-Host "forbidden model '$Model' denied [OK]"
  }
}

function Invoke-OllamaChat {
  param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$Model,
    [Parameter(Mandatory = $true)][string]$Prompt
  )
  $Body = @{
    model = $Model
    stream = $false
    messages = @(@{ role = "user"; content = $Prompt })
  } | ConvertTo-Json -Depth 5

  $Response = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/chat" -ContentType "application/json" -Body $Body -TimeoutSec 180
  return $Response.message.content.Trim()
}

Fail-IfProviderEnvExists

$OllamaBase = Read-DotEnvValue "OLLAMA_API_BASE"
$HermesKey = Read-DotEnvValue "HERMES_LITELLM_KEY"

if (-not $OllamaBase) {
  Write-Host "OLLAMA_API_BASE empty in .env - set it to local Ollama or the 4090 Tailscale URL"
  exit 1
}

if (-not $HermesKey) {
  Write-Host "HERMES_LITELLM_KEY empty in .env - run bootstrap + keys first"
  exit 1
}

$OllamaDirectBase = $env:OLLAMA_DIRECT_BASE
if (-not $OllamaDirectBase) {
  if ($OllamaBase -match "^http://host\.docker\.internal(:\d+)?/?$") {
    $OllamaDirectBase = "http://127.0.0.1:11434"
  } else {
    $OllamaDirectBase = $OllamaBase
  }
}

Write-Host "== 1. Ollama direct ($OllamaBase) =="
if ($OllamaDirectBase -ne $OllamaBase) {
  Write-Host "host direct URL: $OllamaDirectBase"
}
$Reply = Invoke-OllamaChat -BaseUrl $OllamaDirectBase -Model "qwen3-coder:30b" -Prompt "Reply with exactly: LOCAL-TIER-OK"
Write-Host "reply: $Reply"

Write-Host ""
Write-Host "== 2. LiteLLM -> local triage alias '$TriageAlias' =="
$Reply = Invoke-LiteLLMChat -BearerToken $HermesKey -Model $TriageAlias -Prompt "Reply with exactly: GATEWAY-TRIAGE-OK"
Write-Host "reply: $Reply"

Write-Host ""
Write-Host "== 3. LiteLLM -> local planner alias '$PlannerAlias' =="
$Reply = Invoke-LiteLLMChat -BearerToken $HermesKey -Model $PlannerAlias -Prompt "Reply with exactly: GATEWAY-PLANNER-OK"
Write-Host "reply: $Reply"

Write-Host ""
Write-Host "== 4. LiteLLM -> local judge alias '$JudgeAlias' =="
$Reply = Invoke-LiteLLMChat -BearerToken $HermesKey -Model $JudgeAlias -Prompt "Reply with exactly: GATEWAY-JUDGE-OK"
Write-Host "reply: $Reply"

Write-Host ""
Write-Host "== 5. Denied-model checks =="
Assert-LiteLLMDeniesModel -BearerToken $HermesKey -Model "gpt-4o"
Assert-LiteLLMDeniesModel -BearerToken $HermesKey -Model "claude-3-5-sonnet-latest"

Write-Host ""
Write-Host "== 6. Executor auth (subscription/OAuth, not API keys) =="
Write-Host "provider API keys absent from process/user/machine environments [OK]"
if (Get-Command claude -ErrorAction SilentlyContinue) {
  Write-Host "claude installed [OK] - run 'claude' then /status; auth should show subscription/OAuth"
} else {
  Write-Host "claude not installed on this machine (fine if executors run elsewhere)"
}

if (Get-Command codex -ErrorAction SilentlyContinue) {
  Write-Host "codex installed [OK] - run 'codex login status' manually; expected: Logged in using ChatGPT"
} else {
  Write-Host "codex not installed on this machine (fine if executors run elsewhere)"
}

Write-Host ""
Write-Host "== 7. Forbidden-provider config scan =="
if (Get-Command uv -ErrorAction SilentlyContinue) {
  & uv run python -m command_center.cli.check_forbidden_providers
} else {
  & python -m command_center.cli.check_forbidden_providers
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "live smoke complete: all model replies came from Ollama direct or LiteLLM local aliases."
