param(
    [string]$BaseUrl = 'http://127.0.0.1:8001',
    [string]$Message = 'codex-chat live verify',
    [string]$OutputDir = 'output/playwright/codex-chat-live',
    [switch]$NoAlert,
    [switch]$LegacyTaskManagement
)

$ErrorActionPreference = 'Stop'

$scriptPath = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}
$projectRoot = Split-Path -Parent $scriptPath

if (-not $LegacyTaskManagement) {
    Write-Output 'deprecated=run_codex_live_verify.ps1 now delegates to thin bridge verification'
    Write-Output 'goal=mobile one-line command -> local Codex bridge -> minimal status -> last result'
    & (Join-Path $scriptPath 'run_codex_bridge_verify.ps1') -BaseUrl $BaseUrl -Message $Message -OutputDir 'output/playwright/codex-chat-bridge'
    exit $LASTEXITCODE
}

Write-Output 'deprecated=legacy task-management verify requested explicitly'
Write-Output 'warning=this path checks the old rich codex-chat UX, not the thin mobile Codex bridge goal'

if (-not $NoAlert) {
    & (Join-Path $scriptPath 'codex_raise_attention.ps1') -Kind 'approval' -Message 'Live verify will run. Local Chrome permission is required.'
}

$verifyScript = Join-Path $scriptPath 'verify_codex_chat_live.js'
if (-not (Test-Path -LiteralPath $verifyScript)) {
    throw "verify script missing: $verifyScript"
}

$arguments = @(
    $verifyScript
    $BaseUrl
    $Message
    '--output-dir'
    $OutputDir
)

Push-Location $projectRoot
try {
    & node @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "live verify failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
