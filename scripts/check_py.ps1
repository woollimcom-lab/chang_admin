param(
    [Parameter(Mandatory = $true)]
    [string[]]$RelativePaths,

    [string]$Url = "http://43.202.209.122/view/6075",
    [string]$SshTarget = "ubuntu@43.202.209.122",
    [string]$SshKeyPath = "d:\dev\changarum.pem",
    [string]$ServiceName = "mysite"
)

$scriptPath = Join-Path $PSScriptRoot "after_save_check.ps1"
& powershell -ExecutionPolicy Bypass -File $scriptPath -RelativePaths $RelativePaths -Url $Url -SshTarget $SshTarget -SshKeyPath $SshKeyPath -ServiceName $ServiceName
