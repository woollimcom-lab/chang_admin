param(
    [string]$BaseUrl = 'http://127.0.0.1:8001',
    [string]$Message = 'codex-chat bridge verify',
    [string]$OutputDir = 'output/playwright/codex-chat-bridge',
    [switch]$Submit
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
$verifyScript = Join-Path $scriptPath 'verify_codex_chat_bridge.js'
if (-not (Test-Path -LiteralPath $verifyScript)) {
    throw "bridge verify script missing: $verifyScript"
}

$arguments = @(
    $verifyScript
    $BaseUrl
    $Message
    '--output-dir'
    $OutputDir
)
if ($Submit) {
    $arguments += '--submit'
}

Push-Location $projectRoot
try {
    Write-Output 'goal=mobile one-line command -> local Codex bridge -> minimal status -> last result'
    if ($Submit) {
        Write-Output 'submit=on; this may create a real queued Codex task'
    } else {
        Write-Output 'submit=off; safe UI/API guard only, no Codex task is created'
    }
    & node @arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Output ("bridge_verify_json=" + (Join-Path $projectRoot (Join-Path $OutputDir 'bridge_verify.json')))
        throw "bridge verify failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
