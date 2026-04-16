param(
    [Parameter(Mandatory = $true)]
    [string[]]$RelativePaths,

    [string]$RemoteHost = "",
    [string]$Username = "",
    [string]$SshKeyPath = "",
    [string]$RemoteRoot = "",
    [int]$Port = 22
)

$ErrorActionPreference = "Stop"

function Get-ConfigValue {
    param(
        $Config,
        [string]$Name,
        $Fallback = $null
    )

    if ($Config) {
        $property = $Config.PSObject.Properties[$Name]
        if ($property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            return $property.Value
        }
    }

    return $Fallback
}

function Get-RemotePath {
    param(
        [string]$Root,
        [string]$RelativePath
    )

    $cleanRoot = $Root.TrimEnd("/")
    $cleanRelative = ($RelativePath -replace "\\", "/").TrimStart("./").TrimStart("/")
    return "{0}/{1}" -f $cleanRoot, $cleanRelative
}

function Get-RemoteParent {
    param([string]$RemotePath)

    $lastSlash = $RemotePath.LastIndexOf("/")
    if ($lastSlash -lt 0) {
        return "/"
    }

    return $RemotePath.Substring(0, $lastSlash)
}

function Escape-RemotePath {
    param([string]$Value)

    return $Value.Replace("'", "'\''")
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $projectRoot ".vscode\sftp.json"
$config = $null

if (Test-Path $configPath) {
    $config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
}

$RemoteHost = if ([string]::IsNullOrWhiteSpace($RemoteHost)) { [string](Get-ConfigValue -Config $config -Name "host" -Fallback "") } else { $RemoteHost }
$Username = if ([string]::IsNullOrWhiteSpace($Username)) { [string](Get-ConfigValue -Config $config -Name "username" -Fallback "") } else { $Username }
$SshKeyPath = if ([string]::IsNullOrWhiteSpace($SshKeyPath)) { [string](Get-ConfigValue -Config $config -Name "privateKeyPath" -Fallback "") } else { $SshKeyPath }
$RemoteRoot = if ([string]::IsNullOrWhiteSpace($RemoteRoot)) { [string](Get-ConfigValue -Config $config -Name "remotePath" -Fallback "") } else { $RemoteRoot }
if ($Port -eq 22) {
    $Port = [int](Get-ConfigValue -Config $config -Name "port" -Fallback 22)
} else {
    $Port = [int]$Port
}

if ([string]::IsNullOrWhiteSpace($RemoteHost)) {
    throw "upload host is required"
}
if ([string]::IsNullOrWhiteSpace($Username)) {
    throw "upload username is required"
}
if ([string]::IsNullOrWhiteSpace($RemoteRoot)) {
    throw "upload remote root is required"
}

$sshCommand = Get-Command ssh -ErrorAction SilentlyContinue
$scpCommand = Get-Command scp -ErrorAction SilentlyContinue
if (-not $sshCommand) {
    throw "ssh command not found"
}
if (-not $scpCommand) {
    throw "scp command not found"
}

$sshBaseArgs = @("-p", [string]$Port)
$scpBaseArgs = @("-P", [string]$Port)

if (-not [string]::IsNullOrWhiteSpace($SshKeyPath)) {
    $sshBaseArgs += @("-i", $SshKeyPath)
    $scpBaseArgs += @("-i", $SshKeyPath)
}

$target = "{0}@{1}" -f $Username, $RemoteHost

foreach ($relativePath in $RelativePaths | Select-Object -Unique) {
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        continue
    }

    $localPath = Join-Path $projectRoot $relativePath
    $remotePath = Get-RemotePath -Root $RemoteRoot -RelativePath $relativePath
    $remoteDir = Get-RemoteParent -RemotePath $remotePath
    $escapedRemotePath = Escape-RemotePath -Value $remotePath
    $escapedRemoteDir = Escape-RemotePath -Value $remoteDir

    if (Test-Path $localPath) {
        Write-Output ("[upload] {0}" -f $relativePath)

        & $sshCommand.Source @sshBaseArgs $target ("mkdir -p '{0}'" -f $escapedRemoteDir) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "remote directory create failed: $remoteDir"
        }

        & $scpCommand.Source @scpBaseArgs $localPath ("{0}:{1}" -f $target, $remotePath) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "upload failed: $relativePath"
        }

        $localHash = (Get-FileHash -Path $localPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $remoteHash = (& $sshCommand.Source @sshBaseArgs $target ("sha256sum '{0}' | cut -d ' ' -f1" -f $escapedRemotePath)).Trim().ToLowerInvariant()
        if ($LASTEXITCODE -ne 0) {
            throw "remote hash check failed: $relativePath"
        }
        if ($remoteHash -ne $localHash) {
            throw "uploaded file hash mismatch: $relativePath"
        }

        Write-Output ("[uploaded] {0}" -f $relativePath)
        continue
    }

    Write-Output ("[remote delete] {0}" -f $relativePath)
    & $sshCommand.Source @sshBaseArgs $target ("rm -f '{0}'" -f $escapedRemotePath) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "remote delete failed: $relativePath"
    }
    Write-Output ("[deleted] {0}" -f $relativePath)
}
