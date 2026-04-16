param(
    [Parameter(Mandatory = $true)]
    [string]$RelativePath,

    [Parameter(Mandatory = $true)]
    [string]$BackupPath
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$targetPath = Join-Path $projectRoot $RelativePath

if (-not (Test-Path $BackupPath)) {
    throw "Backup file not found: $BackupPath"
}

$targetDir = Split-Path -Parent $targetPath
if (-not [string]::IsNullOrWhiteSpace($targetDir) -and -not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

Copy-Item -Path $BackupPath -Destination $targetPath -Force
Write-Output $targetPath
