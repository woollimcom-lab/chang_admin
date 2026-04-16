param(
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backupRoot = Join-Path $projectRoot "backup"

if (-not (Test-Path $backupRoot)) {
    Write-Output "Backup folder not found: $backupRoot"
    exit 0
}

$protectedPatterns = @(
    "backup\\templates\\stats.*.html",
    "backup\\templates\\view.*.html",
    "backup\\templates\\apt_manager.*.html",
    "backup\\static\\js\\view_ui.*.js"
)

$cutoff = (Get-Date).AddDays(-1 * $RetentionDays)
$removed = @()

Get-ChildItem -Path $backupRoot -Recurse -File | ForEach-Object {
    $fullPath = $_.FullName
    $normalized = $fullPath.Replace('/', '\').ToLowerInvariant()

    $isProtected = $false
    foreach ($pattern in $protectedPatterns) {
        if ($normalized -like (Join-Path $projectRoot $pattern).ToLowerInvariant()) {
            $isProtected = $true
            break
        }
    }

    if ($isProtected) {
        return
    }

    if ($_.LastWriteTime -lt $cutoff) {
        Remove-Item -Path $fullPath -Force
        $removed += $fullPath
    }
}

Write-Output ("Removed backups: {0}" -f $removed.Count)
$removed | ForEach-Object { Write-Output $_ }
