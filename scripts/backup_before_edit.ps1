param(
    [Parameter(Mandatory = $true)]
    [string]$RelativePath
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot $RelativePath

if (-not (Test-Path $sourcePath)) {
    throw "Source file not found: $RelativePath"
}

$backupRoot = Join-Path $projectRoot "backup"
if (-not (Test-Path $backupRoot)) {
    New-Item -ItemType Directory -Path $backupRoot | Out-Null
}

$relativeDir = Split-Path $RelativePath -Parent
$targetDir = if ([string]::IsNullOrWhiteSpace($relativeDir)) {
    $backupRoot
} else {
    Join-Path $backupRoot $relativeDir
}

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$name = [System.IO.Path]::GetFileNameWithoutExtension($sourcePath)
$ext = [System.IO.Path]::GetExtension($sourcePath)
$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$targetPath = Join-Path $targetDir ("{0}.{1}{2}" -f $name, $stamp, $ext)

Copy-Item -Path $sourcePath -Destination $targetPath -Force
Write-Output $targetPath
