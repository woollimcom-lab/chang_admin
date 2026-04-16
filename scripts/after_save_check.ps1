param(
    [Parameter(Mandatory = $true)]
    [string[]]$RelativePaths,

    [Parameter(Mandatory = $true)]
    [string]$Url,

    [string]$SshTarget = "",
    [string]$SshKeyPath = "",
    [string]$ServiceName = "mysite",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$verificationScript = Join-Path $projectRoot "scripts\run_edit_verification.ps1"
$authenticatedCaptureScript = Join-Path $projectRoot "scripts\run_authenticated_capture.js"
$uploadScript = Join-Path $projectRoot "scripts\upload_changed_files.ps1"

if (-not (Test-Path $verificationScript)) {
    throw "run_edit_verification.ps1 not found"
}
if (-not (Test-Path $uploadScript)) {
    throw "upload_changed_files.ps1 not found"
}

$pythonExtensions = @(".py")
$needsRestart = $false
$hasLoginCredentials = -not [string]::IsNullOrWhiteSpace($env:CHANG_ADMIN_ID) -and -not [string]::IsNullOrWhiteSpace($env:CHANG_ADMIN_PW)

foreach ($relativePath in $RelativePaths) {
    $extension = [System.IO.Path]::GetExtension($relativePath)
    if ($pythonExtensions -contains $extension.ToLowerInvariant()) {
        $needsRestart = $true
        break
    }
}

Write-Output "[step 1/4] verify edited files"
& $verificationScript -RelativePaths $RelativePaths -Url ""
if ($LASTEXITCODE -ne 0) {
    throw "edit verification failed"
}

Write-Output "[step 2/4] upload changed files"
$uploadArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $uploadScript,
    "-RelativePaths"
)
$uploadArgs += $RelativePaths
if (-not [string]::IsNullOrWhiteSpace($SshKeyPath)) {
    $uploadArgs += @("-SshKeyPath", $SshKeyPath)
}
if (-not [string]::IsNullOrWhiteSpace($SshTarget)) {
    $sshMatch = [regex]::Match($SshTarget, '^(?<user>[^@]+)@(?<host>.+)$')
    if (-not $sshMatch.Success) {
        throw "invalid -SshTarget format. use user@host"
    }
    $uploadArgs += @("-Username", $sshMatch.Groups["user"].Value, "-RemoteHost", $sshMatch.Groups["host"].Value)
}

& powershell @uploadArgs
if ($LASTEXITCODE -ne 0) {
    throw "upload failed"
}

if ($needsRestart) {
    Write-Output "[step 3/4] restart remote service"

    if ([string]::IsNullOrWhiteSpace($SshTarget)) {
        throw "python file changed. provide -SshTarget like user@host"
    }

    $restartCommand = "sudo systemctl restart $ServiceName && sudo systemctl status $ServiceName --no-pager"
    if ([string]::IsNullOrWhiteSpace($SshKeyPath)) {
        & ssh $SshTarget $restartCommand
    } else {
        & ssh -i $SshKeyPath $SshTarget $restartCommand
    }

    if ($LASTEXITCODE -ne 0) {
        throw "remote service restart failed"
    }
} else {
    Write-Output "[step 3/4] remote restart skipped (no python file)"
}

Write-Output "[step 4/4] browser smoke check"
if ($hasLoginCredentials) {
    if (-not (Test-Path $authenticatedCaptureScript)) {
        throw "run_authenticated_capture.js not found"
    }

    & npx.cmd playwright install chromium | Out-Null
    if ([string]::IsNullOrWhiteSpace($OutputPath)) {
        & node $authenticatedCaptureScript $Url
    } else {
        & node $authenticatedCaptureScript $Url $OutputPath
    }
} else {
    & $verificationScript -RelativePaths $RelativePaths -Url $Url -OutputPath $OutputPath
}

if ($LASTEXITCODE -ne 0) {
    throw "browser verification failed"
}

Write-Output ""
Write-Output "Summary"
Write-Output ("- edited: {0}" -f ($RelativePaths -join ", "))
Write-Output "- upload: direct"
Write-Output ("- restart: {0}" -f ($(if ($needsRestart) { "required" } else { "skipped" })))
Write-Output ("- url: {0}" -f $Url)
Write-Output ("- login: {0}" -f ($(if ($hasLoginCredentials) { "env credentials used" } else { "not used" })))
Write-Output ("- ssh key: {0}" -f ($(if ([string]::IsNullOrWhiteSpace($SshKeyPath)) { "default" } else { $SshKeyPath })))
Write-Output ("- screenshot: {0}" -f ($(if ([string]::IsNullOrWhiteSpace($OutputPath)) { (Join-Path $projectRoot "output\playwright\smoke.png") } else { $OutputPath })))
