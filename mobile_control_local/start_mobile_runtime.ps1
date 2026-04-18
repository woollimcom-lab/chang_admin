$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $root 'output\mobile_control\runtime'
$logsDir = Join-Path $runtimeDir 'logs'
$runtimeFile = Join-Path $runtimeDir 'runtime.json'
$mysqlRuntimeFile = Join-Path $runtimeDir 'mysql-runtime.json'
$publishScript = Join-Path $PSScriptRoot 'publish_mobile_control_link.ps1'
$configPath = Join-Path $root '.vscode\sftp.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$runtimeCloudflaredPath = Join-Path $runtimeDir 'bin\cloudflared.exe'

New-Item -ItemType Directory -Force $logsDir | Out-Null

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\start_local_mysql.ps1') | Out-Null

function Get-PythonPath {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path $cmd.Source)) {
        return $cmd.Source
    }

    $patterns = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe'),
        'C:\Users\*\AppData\Local\Programs\Python\Python*\python.exe',
        'C:\Program Files\Python*\python.exe',
        'C:\Program Files (x86)\Python*\python.exe'
    )

    foreach ($pattern in $patterns) {
        $candidates = Get-ChildItem $pattern -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
        foreach ($candidate in $candidates) {
            if (Test-Path $candidate.FullName) {
                return $candidate.FullName
            }
        }
    }

    throw 'python.exe path not found'
}

function Get-CodexPath {
    if (-not [string]::IsNullOrWhiteSpace($env:MOBILE_CONTROL_CODEX_PATH) -and (Test-Path $env:MOBILE_CONTROL_CODEX_PATH)) {
        return $env:MOBILE_CONTROL_CODEX_PATH
    }

    $cmd = Get-Command codex -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path $cmd.Source)) {
        return $cmd.Source
    }

    $patterns = @(
        (Join-Path $env:USERPROFILE '.vscode\extensions\openai.chatgpt-*-win32-x64\bin\windows-x86_64\codex.exe'),
        (Join-Path $env:USERPROFILE '.vscode-insiders\extensions\openai.chatgpt-*-win32-x64\bin\windows-x86_64\codex.exe')
    )
    foreach ($pattern in $patterns) {
        $candidate = Get-ChildItem $pattern -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($candidate -and (Test-Path $candidate.FullName)) {
            return $candidate.FullName
        }
    }

    return ''
}

function Test-CloudflaredExecutable {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) {
        return $false
    }

    try {
        $null = & $Path --version 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-ConfiguredCloudflaredPath {
    if (-not (Test-Path $configPath)) {
        return ''
    }

    try {
        $config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
        $value = [string]$config.cloudflaredPath
        if ([string]::IsNullOrWhiteSpace($value)) {
            return ''
        }
        return [Environment]::ExpandEnvironmentVariables($value)
    } catch {
        return ''
    }
}

function Resolve-CloudflaredCandidate {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($candidate in @(
        [string]$env:MOBILE_CONTROL_CLOUDFLARED_PATH,
        (Get-ConfiguredCloudflaredPath),
        $runtimeCloudflaredPath
    )) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and -not $candidates.Contains($candidate)) {
            $candidates.Add($candidate)
        }
    }

    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and -not $candidates.Contains($cmd.Source)) {
        $candidates.Add($cmd.Source)
    }

    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\Cloudflare.cloudflared_*\cloudflared.exe'),
        'C:\Users\*\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_*\cloudflared.exe',
        'C:\Program Files\cloudflared\cloudflared.exe',
        'C:\Program Files (x86)\cloudflared\cloudflared.exe'
    )) {
        $items = Get-ChildItem $candidate -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
        foreach ($item in $items) {
            if (-not $candidates.Contains($item.FullName)) {
                $candidates.Add($item.FullName)
            }
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-CloudflaredExecutable -Path $candidate) {
            return [pscustomobject]@{ Path = $candidate; Error = '' }
        }
    }

    $firstExisting = $candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path $_) } | Select-Object -First 1
    if ($firstExisting) {
        return [pscustomobject]@{ Path = ''; Error = "cloudflared executable is present but cannot be launched: $firstExisting" }
    }

    return [pscustomobject]@{ Path = ''; Error = 'cloudflared executable not found' }
}

function Get-WorkerProcess {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'mobile_control_worker\.py' } |
        Select-Object -First 1
}

function Get-TunnelProcess {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq 'cloudflared.exe' -and $_.CommandLine -match 'tunnel' -and $_.CommandLine -match '127\.0\.0\.1:8001' } |
        Select-Object -First 1
}

function Get-AppProcess {
    $conn = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) { return $null }
    Get-CimInstance Win32_Process -Filter "ProcessId = $($conn.OwningProcess)" -ErrorAction SilentlyContinue
}

function Get-AvailableLogPath {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Test-Path $Path)) {
        return $Path
    }
    try {
        Remove-Item $Path -Force -ErrorAction Stop
        return $Path
    } catch {
        $dir = Split-Path -Parent $Path
        $name = [System.IO.Path]::GetFileNameWithoutExtension($Path)
        $ext = [System.IO.Path]::GetExtension($Path)
        return Join-Path $dir ("{0}.{1}{2}" -f $name, (Get-Date).ToString('yyyyMMdd-HHmmss'), $ext)
    }
}

function Start-ManagedProcess {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][string[]]$ArgumentList,
        [Parameter(Mandatory=$true)][string]$StdOutPath,
        [Parameter(Mandatory=$true)][string]$StdErrPath
    )

    $resolvedStdOutPath = Get-AvailableLogPath -Path $StdOutPath
    $resolvedStdErrPath = Get-AvailableLogPath -Path $StdErrPath

    $process = Start-Process -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $resolvedStdOutPath `
        -RedirectStandardError $resolvedStdErrPath `
        -PassThru

    return [pscustomobject]@{
        Process = $process
        StdOutPath = $resolvedStdOutPath
        StdErrPath = $resolvedStdErrPath
    }
}

function Get-ManagedProcId {
    param($Process)
    if (-not $Process) { return $null }
    if ($Process.PSObject.Properties['Process'] -and $Process.Process) {
        return Get-ManagedProcId $Process.Process
    }
    if ($Process.PSObject.Properties['ProcessId']) { return $Process.ProcessId }
    if ($Process.PSObject.Properties['Id']) { return $Process.Id }
    return $null
}

function Find-TunnelUrlInLogs {
    param([string[]]$LogPaths)

    foreach ($logPath in $LogPaths) {
        if (-not (Test-Path $logPath)) {
            continue
        }
        $line = Get-Content $logPath -ErrorAction SilentlyContinue | Select-String -Pattern 'https://[a-z0-9.-]+\.trycloudflare\.com' | Select-Object -Last 1
        if (-not $line) {
            continue
        }
        $match = [regex]::Match($line.Line, 'https://[a-z0-9.-]+\.trycloudflare\.com')
        if ($match.Success) {
            return $match.Value.TrimEnd('/')
        }
    }

    return ''
}

function Wait-ForTunnelUrl {
    param(
        [Parameter(Mandatory=$true)][string[]]$LogPaths,
        [int]$TimeoutSeconds = 40,
        [int]$PollIntervalSeconds = 2
    )

    $timeoutSeconds = [Math]::Max(2, $TimeoutSeconds)
    $pollIntervalSeconds = [Math]::Max(1, $PollIntervalSeconds)
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)

    do {
        $currentUrl = Find-TunnelUrlInLogs -LogPaths $LogPaths
        if (-not [string]::IsNullOrWhiteSpace($currentUrl)) {
            return $currentUrl
        }
        Start-Sleep -Seconds $pollIntervalSeconds
    } while ((Get-Date) -lt $deadline)

    return ''
}

$appLog = Join-Path $logsDir 'app.log'
$appErr = Join-Path $logsDir 'app.err.log'
$workerLog = Join-Path $logsDir 'worker.log'
$workerErr = Join-Path $logsDir 'worker.err.log'
$tunnelLog = Join-Path $logsDir 'tunnel.log'
$tunnelErr = Join-Path $logsDir 'tunnel.err.log'
$publishLog = Join-Path $logsDir 'publish.log'
$publishErr = Join-Path $logsDir 'publish.err.log'
$codexProfile = if ([string]::IsNullOrWhiteSpace($env:MOBILE_CONTROL_CODEX_PROFILE)) { 'mobile_worker' } else { [string]$env:MOBILE_CONTROL_CODEX_PROFILE }
$pythonExe = Get-PythonPath
$codexPath = Get-CodexPath
if (-not [string]::IsNullOrWhiteSpace($codexPath)) {
    $env:MOBILE_CONTROL_CODEX_PATH = $codexPath
}
$powershellExe = (Get-Command powershell.exe | Select-Object -ExpandProperty Source)
$currentSessionId = (Get-Process -Id $PID -ErrorAction SilentlyContinue).SessionId
$skipWorkerStart = ($null -ne $currentSessionId -and [int]$currentSessionId -eq 0)
$cloudflaredCandidate = Resolve-CloudflaredCandidate
$cloudflaredPath = [string]$cloudflaredCandidate.Path
$cloudflaredError = [string]$cloudflaredCandidate.Error

$appProc = Get-AppProcess
if (-not $appProc) {
    $appProc = Start-ManagedProcess `
        -FilePath $pythonExe `
        -ArgumentList @('-X', 'utf8', '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8001') `
        -StdOutPath $appLog `
        -StdErrPath $appErr
    if ($appProc -and $appProc.PSObject.Properties['StdOutPath']) {
        $appLog = $appProc.StdOutPath
        $appErr = $appProc.StdErrPath
    }
    Start-Sleep -Seconds 5
}

$workerProc = Get-WorkerProcess
if ((-not $workerProc) -and (-not $skipWorkerStart)) {
    $workerProc = Start-ManagedProcess `
        -FilePath $pythonExe `
        -ArgumentList @('-X', 'utf8', 'scripts/mobile_control_worker.py') `
        -StdOutPath $workerLog `
        -StdErrPath $workerErr
    if ($workerProc -and $workerProc.PSObject.Properties['StdOutPath']) {
        $workerLog = $workerProc.StdOutPath
        $workerErr = $workerProc.StdErrPath
    }
    Start-Sleep -Seconds 2
}

if (-not $cloudflaredPath) {
    throw "cloudflared.exe를 실행할 수 없습니다. $cloudflaredError. MOBILE_CONTROL_CLOUDFLARED_PATH 또는 output\\mobile_control\\runtime\\bin\\cloudflared.exe를 확인해 주세요."
}

$tunnelProc = Get-TunnelProcess
if (-not $tunnelProc) {
    $tunnelProc = Start-ManagedProcess `
        -FilePath $cloudflaredPath `
        -ArgumentList @('tunnel', '--url', 'http://127.0.0.1:8001') `
        -StdOutPath $tunnelLog `
        -StdErrPath $tunnelErr
    if ($tunnelProc -and $tunnelProc.PSObject.Properties['StdOutPath']) {
        $tunnelLog = $tunnelProc.StdOutPath
        $tunnelErr = $tunnelProc.StdErrPath
    }
}

$tunnelUrl = Wait-ForTunnelUrl -LogPaths @($tunnelLog, $tunnelErr)

$publishedInfo = $null
$publishProcessInfo = [ordered]@{
    pid = $null
    stdout_path = ''
    stderr_path = ''
    elapsed_ms = 0
    exit_code = $null
    completion_reason = ''
}
if ($tunnelUrl -and (Test-Path $publishScript)) {
    $publishStartedAt = Get-Date
    try {
        $publishLog = Get-AvailableLogPath -Path $publishLog
        $publishErr = Get-AvailableLogPath -Path $publishErr
        $publishProcessInfo.stdout_path = $publishLog
        $publishProcessInfo.stderr_path = $publishErr
        $publishProcessInfo.completion_reason = 'direct_invoke'
        Push-Location $root
        try {
            $publishStdoutRaw = & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $publishScript -TunnelBaseUrl $tunnelUrl 2> $publishErr
        } finally {
            Pop-Location
        }
        $publishProcessInfo.elapsed_ms = [math]::Round(((Get-Date) - $publishStartedAt).TotalMilliseconds, 1)
        $publishProcessInfo.exit_code = $LASTEXITCODE
        $publishProcessInfo.completion_reason = 'process_exit'

        $publishStdoutText = ''
        if ($null -ne $publishStdoutRaw) {
            $publishStdoutText = [string]($publishStdoutRaw | Out-String)
        }
        [System.IO.File]::WriteAllText($publishLog, $publishStdoutText, $utf8NoBom)

        $publishStderrText = ''
        if (Test-Path $publishErr) {
            $publishStderrRead = Get-Content -Raw -Path $publishErr -ErrorAction SilentlyContinue
            if ($null -ne $publishStderrRead) {
                $publishStderrText = [string]$publishStderrRead
            }
        }

        $publishStdoutSummary = ($publishStdoutText -replace '\s+', ' ').Trim()
        $publishStderrSummary = ($publishStderrText -replace '\s+', ' ').Trim()
        if ([string]::IsNullOrWhiteSpace($publishStdoutSummary)) {
            $publishStdoutSummary = 'none'
        }
        if ([string]::IsNullOrWhiteSpace($publishStderrSummary)) {
            $publishStderrSummary = 'none'
        }

        if ($publishProcessInfo.exit_code -ne 0) {
            $publishFailureMessage = if ($publishStderrSummary -ne 'none') { $publishStderrSummary } elseif ($publishStdoutSummary -ne 'none') { $publishStdoutSummary } else { 'publish process failed' }
            throw $publishFailureMessage
        }

        if (-not [string]::IsNullOrWhiteSpace($publishStdoutText)) {
            try {
                $publishedInfo = $publishStdoutText | ConvertFrom-Json
            } catch {
                $publishProcessInfo.completion_reason = 'process_result_parse_failed'
                throw 'publish result parse failed'
            }
        }
        if (-not $publishedInfo) {
            $publishProcessInfo.completion_reason = 'process_result_empty'
            throw 'publish result is empty'
        }
    }
    catch {
        $publishedInfo = @{
            status = 'failed'
            error = $_.Exception.Message
            mobile_control_url = ('{0}/mobile-control' -f $tunnelUrl.TrimEnd('/'))
            tunnel_url = $tunnelUrl
            updated_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        }
    }
} elseif (-not $tunnelUrl) {
    $publishedInfo = @{
        status = 'pending'
        error = 'tunnel url not found in logs yet'
        mobile_control_url = ''
    }
}

$payload = @{
    updated_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    mysql_pid = $null
    mysql_running = $false
    mysql_managed = $false
    app_pid = Get-ManagedProcId $appProc
    worker_pid = Get-ManagedProcId $workerProc
    tunnel_pid = Get-ManagedProcId $tunnelProc
    codex_profile = $codexProfile
    tunnel_url = $tunnelUrl
    cloudflared_path = $cloudflaredPath
    cloudflared_ready = [bool](-not [string]::IsNullOrWhiteSpace($cloudflaredPath))
    cloudflared_error = $cloudflaredError
    published = $publishedInfo
    publish_process = $publishProcessInfo
    logs = @{
        app = (Resolve-Path $appLog -ErrorAction SilentlyContinue).Path
        app_err = (Resolve-Path $appErr -ErrorAction SilentlyContinue).Path
        worker = (Resolve-Path $workerLog -ErrorAction SilentlyContinue).Path
        worker_err = (Resolve-Path $workerErr -ErrorAction SilentlyContinue).Path
        tunnel = (Resolve-Path $tunnelLog -ErrorAction SilentlyContinue).Path
        tunnel_err = (Resolve-Path $tunnelErr -ErrorAction SilentlyContinue).Path
        publish = (Resolve-Path $publishLog -ErrorAction SilentlyContinue).Path
        publish_err = (Resolve-Path $publishErr -ErrorAction SilentlyContinue).Path
    }
}

if (Test-Path $mysqlRuntimeFile) {
    try {
        $mysqlRuntime = Get-Content $mysqlRuntimeFile -Raw | ConvertFrom-Json
        if ($mysqlRuntime) {
            $payload.mysql_pid = $mysqlRuntime.mysql_pid
            $payload.mysql_running = [bool]$mysqlRuntime.running
            $payload.mysql_managed = [bool]$mysqlRuntime.started_by_script
        }
    } catch {
    }
}

[System.IO.File]::WriteAllText($runtimeFile, ($payload | ConvertTo-Json -Depth 4), $utf8NoBom)

Write-Host "app_pid=$($payload.app_pid)"
Write-Host "worker_pid=$($payload.worker_pid)"
Write-Host "tunnel_pid=$($payload.tunnel_pid)"
Write-Host "mysql_pid=$($payload.mysql_pid)"
Write-Host "mysql_managed=$($payload.mysql_managed)"
Write-Host "codex_profile=$($payload.codex_profile)"
Write-Host "cloudflared_ready=$($payload.cloudflared_ready)"
if ($payload.cloudflared_path) {
    Write-Host "cloudflared_path=$($payload.cloudflared_path)"
}
if ($payload.cloudflared_error) {
    Write-Host "cloudflared_error=$($payload.cloudflared_error)"
}
if ($publishedInfo -and $publishedInfo.server_relative_html_url) {
    Write-Host ("published_relative_url={0}" -f $publishedInfo.server_relative_html_url)
}
if ($publishedInfo -and $publishedInfo.status) {
    Write-Host ("publish_status={0}" -f $publishedInfo.status)
}
if ($publishProcessInfo.pid) {
    Write-Host ("publish_pid={0}" -f $publishProcessInfo.pid)
}
if ($null -ne $publishProcessInfo.exit_code) {
    Write-Host ("publish_exit_code={0}" -f $publishProcessInfo.exit_code)
}
if (-not [string]::IsNullOrWhiteSpace([string]$publishProcessInfo.completion_reason)) {
    Write-Host ("publish_completion_reason={0}" -f $publishProcessInfo.completion_reason)
}
if ($tunnelUrl) {
    Write-Host "tunnel_url=$tunnelUrl"
} else {
    Write-Host 'tunnel_url=(로그에서 아직 찾지 못함)'
}
