param(
    [string]$TaskFile = ".\night_tasks.json"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$taskPath = if ([System.IO.Path]::IsPathRooted($TaskFile)) { $TaskFile } else { Join-Path $projectRoot $TaskFile }

if (-not (Test-Path $taskPath)) {
    throw "task file not found: $taskPath"
}

$raw = Get-Content -Raw -Path $taskPath
$config = $raw | ConvertFrom-Json

if (-not $config.tasks -or $config.tasks.Count -eq 0) {
    throw "no tasks found in task file"
}

foreach ($task in $config.tasks) {
    $name = [string]$task.name
    $url = [string]$task.url
    $paths = @($task.paths)
    if (-not $url) {
        throw "task url is required: $name"
    }
    if (-not $paths -or $paths.Count -eq 0) {
        throw "task paths are required: $name"
    }

    $needsRestart = $false
    foreach ($p in $paths) {
        if ([System.IO.Path]::GetExtension([string]$p).ToLowerInvariant() -eq ".py") {
            $needsRestart = $true
            break
        }
    }

    Write-Output ""
    Write-Output ("=== task: {0} ===" -f $name)
    Write-Output ("- paths: {0}" -f (($paths | ForEach-Object { [string]$_ }) -join ", "))
    Write-Output ("- url: {0}" -f $url)
    Write-Output ("- mode: {0}" -f ($(if ($needsRestart) { "python" } else { "web" })))

    if ($needsRestart) {
        $sshTarget = if ($task.sshTarget) { [string]$task.sshTarget } elseif ($config.defaults.sshTarget) { [string]$config.defaults.sshTarget } else { "" }
        $sshKeyPath = if ($task.sshKeyPath) { [string]$task.sshKeyPath } elseif ($config.defaults.sshKeyPath) { [string]$config.defaults.sshKeyPath } else { "" }
        $serviceName = if ($task.serviceName) { [string]$task.serviceName } elseif ($config.defaults.serviceName) { [string]$config.defaults.serviceName } else { "mysite" }

        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "check_py.ps1") -RelativePaths $paths -Url $url -SshTarget $sshTarget -SshKeyPath $sshKeyPath -ServiceName $serviceName
    } else {
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "check_web.ps1") -RelativePaths $paths -Url $url
    }

    if ($LASTEXITCODE -ne 0) {
        throw "night task failed: $name"
    }
}

Write-Output ""
Write-Output "All night tasks completed."
