param(
    [Parameter(Mandatory = $true)]
    [string[]]$RelativePaths,
    [string]$Url = "",
    [string]$OutputPath = "",
    [string]$BaselineRoot = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonArgs = @("$projectRoot\scripts\verify_file_safety.py") + $RelativePaths
$uiStringArgs = @("$projectRoot\scripts\verify_ui_strings.py") + $RelativePaths
$inlineScriptArgs = @("$projectRoot\scripts\verify_template_inline_scripts.py")
if (-not [string]::IsNullOrWhiteSpace($BaselineRoot)) {
    $inlineScriptArgs += @("--baseline-root", $BaselineRoot)
}
$inlineScriptArgs += $RelativePaths

Write-Output "[1/3] file safety check"
python @pythonArgs
if ($LASTEXITCODE -ne 0) {
    throw "file safety check failed"
}

Write-Output "[2/3] runtime ui string check"
python @uiStringArgs
if ($LASTEXITCODE -ne 0) {
    throw "runtime ui string check failed"
}

Write-Output "[3/4] template inline script check"
python @inlineScriptArgs
if ($LASTEXITCODE -ne 0) {
    throw "template inline script check failed"
}

if ([string]::IsNullOrWhiteSpace($Url)) {
    Write-Output "[4/4] browser smoke check skipped (no url)"
    exit 0
}

if (Get-Command npx.cmd -ErrorAction SilentlyContinue) {
    $npxCommand = "npx.cmd"
} elseif (Get-Command npx -ErrorAction SilentlyContinue) {
    $npxCommand = "npx"
} else {
    Write-Output "[4/4] browser smoke check skipped (npx missing)"
    exit 0
}

$outputDir = Join-Path $projectRoot "output\playwright"
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

$shotPath = if ([string]::IsNullOrWhiteSpace($OutputPath)) { Join-Path $outputDir "smoke.png" } else { $OutputPath }
$shotDir = Split-Path -Parent $shotPath
if (-not [string]::IsNullOrWhiteSpace($shotDir) -and -not (Test-Path $shotDir)) {
    New-Item -ItemType Directory -Path $shotDir -Force | Out-Null
}
Write-Output "[4/4] browser smoke check"
$verificationRunner = Join-Path $projectRoot "scripts\run_task_verification.js"
if (Test-Path $verificationRunner) {
    $specPath = [System.IO.Path]::ChangeExtension($shotPath, ".verification.json")
    $useAuth = (-not [string]::IsNullOrWhiteSpace($env:CHANG_ADMIN_ID)) -and (-not [string]::IsNullOrWhiteSpace($env:CHANG_ADMIN_PW))
    $spec = @{
        url = $Url
        useAuth = $useAuth
        forbidDialogs = $false
        forbidPageErrors = $true
        outputPath = $shotPath
        steps = @(
            @{
                action = "waitFor"
                selector = "body"
                timeout = 15000
            },
            @{
                action = "screenshot"
            }
        )
    }
    $spec | ConvertTo-Json -Depth 10 | Set-Content -Path $specPath -Encoding UTF8
    & node $verificationRunner $specPath
    if ($LASTEXITCODE -eq 0) {
        Write-Output $shotPath
        exit 0
    }
    throw "browser smoke check failed"
}

$attempts = @(
    @{ Name = "default chromium"; Args = @("playwright", "screenshot", $Url, $shotPath) },
    @{ Name = "chrome channel"; Args = @("playwright", "screenshot", "--channel", "chrome", $Url, $shotPath) },
    @{ Name = "msedge channel"; Args = @("playwright", "screenshot", "--channel", "msedge", $Url, $shotPath) }
)

foreach ($attempt in $attempts) {
    Write-Output ("  - fallback attempt: {0}" -f $attempt.Name)
    & $npxCommand @($attempt.Args)
    if ($LASTEXITCODE -eq 0) {
        Write-Output $shotPath
        exit 0
    }
}

throw "browser smoke check failed"
