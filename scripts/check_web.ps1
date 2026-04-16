param(
    [Parameter(Mandatory = $true)]
    [string[]]$RelativePaths,

    [string]$Url = "http://43.202.209.122/view/6075"
)

$scriptPath = Join-Path $PSScriptRoot "after_save_check.ps1"
& powershell -ExecutionPolicy Bypass -File $scriptPath -RelativePaths $RelativePaths -Url $Url
