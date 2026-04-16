param(
    [string]$TaskFile = ".\night_agent.json"
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom

function Resolve-CodexCommand {
    $command = Get-Command codex -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_CLI_PATH) -and (Test-Path $env:CODEX_CLI_PATH)) {
        return $env:CODEX_CLI_PATH
    }

    $extensionRoot = Join-Path $env:USERPROFILE ".vscode\extensions"
    if (Test-Path $extensionRoot) {
        $candidate = Get-ChildItem $extensionRoot -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }

    return $null
}

function Resolve-TaskValue {
    param(
        [Parameter(Mandatory = $true)]
        $Task,

        [Parameter(Mandatory = $true)]
        $Defaults,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        $Fallback = $null
    )

    $taskValue = $Task.PSObject.Properties[$Name]
    if ($taskValue -and -not [string]::IsNullOrWhiteSpace([string]$taskValue.Value)) {
        return [string]$taskValue.Value
    }

    if ($Defaults) {
        $defaultValue = $Defaults.PSObject.Properties[$Name]
        if ($defaultValue -and -not [string]::IsNullOrWhiteSpace([string]$defaultValue.Value)) {
            return [string]$defaultValue.Value
        }
    }

    return $Fallback
}

function Resolve-TaskIntValue {
    param(
        [Parameter(Mandatory = $true)]
        $Task,

        [Parameter(Mandatory = $true)]
        $Defaults,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [int]$Fallback
    )

    $taskValue = $Task.PSObject.Properties[$Name]
    if ($taskValue -and -not [string]::IsNullOrWhiteSpace([string]$taskValue.Value)) {
        return [int]$taskValue.Value
    }

    if ($Defaults) {
        $defaultValue = $Defaults.PSObject.Properties[$Name]
        if ($defaultValue -and -not [string]::IsNullOrWhiteSpace([string]$defaultValue.Value)) {
            return [int]$defaultValue.Value
        }
    }

    return $Fallback
}

function Invoke-CodexExec {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CodexCommand,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$Prompt,

        [Parameter(Mandatory = $true)]
        [string]$LogPath,

        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $CodexCommand
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = $utf8NoBom
    $startInfo.StandardErrorEncoding = $utf8NoBom
    $quotedArguments = foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') {
            '"' + ($argument -replace '"', '\"') + '"'
        } else {
            $argument
        }
    }
    $startInfo.Arguments = ($quotedArguments -join " ")

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo

    [void]$process.Start()
    $process.StandardInput.Write($Prompt)
    $process.StandardInput.Close()

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()

    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result
    $combined = ($stdout, $stderr | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join [Environment]::NewLine

    if ([string]::IsNullOrWhiteSpace($combined)) {
        Set-Content -Path $LogPath -Value "" -Encoding UTF8
    } else {
        Set-Content -Path $LogPath -Value $combined -Encoding UTF8
        Write-Output $combined
    }

    return [PSCustomObject]@{
        ExitCode = $process.ExitCode
        Output = $combined
    }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$taskPath = if ([System.IO.Path]::IsPathRooted($TaskFile)) { $TaskFile } else { Join-Path $projectRoot $TaskFile }
$backupScript = Join-Path $projectRoot "scripts\backup_before_edit.ps1"
$restoreScript = Join-Path $projectRoot "scripts\restore_backup.ps1"
$afterSaveScript = Join-Path $projectRoot "scripts\after_save_check.ps1"
$uploadScript = Join-Path $projectRoot "scripts\upload_changed_files.ps1"

if (-not (Test-Path $taskPath)) {
    throw "task file not found: $taskPath"
}

${codexCommand} = Resolve-CodexCommand
if (-not $codexCommand) {
    throw "codex command not found"
}

$raw = Get-Content -Raw -Path $taskPath
$config = $raw | ConvertFrom-Json

if (-not $config.tasks -or $config.tasks.Count -eq 0) {
    throw "no tasks found in task file"
}

$defaults = $config.defaults
$runStamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$runRoot = Join-Path $projectRoot ("output\night_agent\{0}" -f $runStamp)
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

$summary = New-Object System.Collections.Generic.List[string]

foreach ($task in $config.tasks) {
    $name = [string]$task.name
    $instruction = [string]$task.instruction
    $url = [string]$task.url
    $paths = @($task.paths | ForEach-Object { [string]$_ })
    $maxAttempts = Resolve-TaskIntValue -Task $task -Defaults $defaults -Name "maxAttempts" -Fallback 3
    $sshTarget = Resolve-TaskValue -Task $task -Defaults $defaults -Name "sshTarget" -Fallback ""
    $sshKeyPath = Resolve-TaskValue -Task $task -Defaults $defaults -Name "sshKeyPath" -Fallback ""
    $serviceName = Resolve-TaskValue -Task $task -Defaults $defaults -Name "serviceName" -Fallback "mysite"
    $remotePath = Resolve-TaskValue -Task $task -Defaults $defaults -Name "remotePath" -Fallback ""
    $model = Resolve-TaskValue -Task $task -Defaults $defaults -Name "model" -Fallback ""

    if ([string]::IsNullOrWhiteSpace($name)) {
        throw "task name is required"
    }
    if ([string]::IsNullOrWhiteSpace($instruction)) {
        throw "task instruction is required: $name"
    }
    if ([string]::IsNullOrWhiteSpace($url)) {
        throw "task url is required: $name"
    }
    if (-not $paths -or $paths.Count -eq 0) {
        throw "task paths are required: $name"
    }

    $taskRoot = Join-Path $runRoot ($name -replace '[\\/:*?""<>| ]', "_")
    New-Item -ItemType Directory -Path $taskRoot -Force | Out-Null

    $backupItems = @()
    foreach ($path in $paths | Select-Object -Unique) {
        $fullPath = Join-Path $projectRoot $path
        if (Test-Path $fullPath) {
            $backupPath = & powershell -ExecutionPolicy Bypass -File $backupScript $path
            $backupItems += [PSCustomObject]@{
                RelativePath = $path
                ExistedBefore = $true
                BackupPath = [string]$backupPath
            }
        } else {
            $backupItems += [PSCustomObject]@{
                RelativePath = $path
                ExistedBefore = $false
                BackupPath = ""
            }
        }
    }

    Write-Output ""
    Write-Output ("=== night agent task: {0} ===" -f $name)
    Write-Output ("- paths: {0}" -f ($paths -join ", "))
    Write-Output ("- url: {0}" -f $url)
    Write-Output ("- max attempts: {0}" -f $maxAttempts)

    $lastFailureLog = ""
    $completed = $false
    $uploadUser = ""
    $uploadHost = ""
    if (-not [string]::IsNullOrWhiteSpace($sshTarget)) {
        $sshMatch = [regex]::Match($sshTarget, '^(?<user>[^@]+)@(?<host>.+)$')
        if (-not $sshMatch.Success) {
            throw "invalid sshTarget format: $sshTarget"
        }
        $uploadUser = $sshMatch.Groups["user"].Value
        $uploadHost = $sshMatch.Groups["host"].Value
    }

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        Write-Output ("[attempt {0}/{1}] codex execution" -f $attempt, $maxAttempts)

        $attemptRoot = Join-Path $taskRoot ("attempt-{0}" -f $attempt)
        New-Item -ItemType Directory -Path $attemptRoot -Force | Out-Null
        $agentMessagePath = Join-Path $attemptRoot "agent_last_message.txt"
        $codexLogPath = Join-Path $attemptRoot "codex_exec.log"
        $verifyLogPath = Join-Path $attemptRoot "verification.log"
        $screenshotPath = Join-Path $attemptRoot "screenshot.png"

        $prompt = @"
You are working in d:\dev\chang_admin.
Task name: $name
Target files: $($paths -join ", ")
User instruction:
$instruction

Requirements:
- Follow AGENTS.md in the repo.
- Work only within the listed target files unless a strictly necessary helper file must be added.
- Use the existing backup and verification workflow already present in this repo.
- Finish the requested code changes in this attempt.
"@

        if ($attempt -gt 1 -and -not [string]::IsNullOrWhiteSpace($lastFailureLog)) {
            $prompt += @"

Previous verification failure log:
$lastFailureLog

Fix the issue shown above and re-run the necessary reasoning before finishing.
"@
        }

        $codexArgs = @("-a", "never", "-s", "workspace-write", "exec", "--skip-git-repo-check", "-C", $projectRoot, "-o", $agentMessagePath)
        if (-not [string]::IsNullOrWhiteSpace($model)) {
            $codexArgs += @("-m", $model)
        }
        $codexArgs += "-"

        $codexResult = Invoke-CodexExec -CodexCommand $codexCommand -Arguments $codexArgs -Prompt $prompt -LogPath $codexLogPath -WorkingDirectory $projectRoot
        $codexExit = $codexResult.ExitCode

        if ($codexExit -ne 0) {
            $lastFailureLog = $codexResult.Output
            Write-Output ("codex exec failed on attempt {0}" -f $attempt)
            continue
        }

        $uploadLogPath = Join-Path $attemptRoot "upload.log"
        $uploadArgs = @(
            "-ExecutionPolicy", "Bypass",
            "-File", $uploadScript,
            "-RelativePaths"
        )
        $uploadArgs += $paths
        $uploadArgs += @("-RemoteHost", $uploadHost, "-Username", $uploadUser, "-SshKeyPath", $sshKeyPath)
        if (-not [string]::IsNullOrWhiteSpace($remotePath)) {
            $uploadArgs += @("-RemoteRoot", $remotePath)
        }
        Write-Output ("[attempt {0}/{1}] upload changed files" -f $attempt, $maxAttempts)
        & powershell @uploadArgs 2>&1 | Tee-Object -FilePath $uploadLogPath
        $uploadExit = $LASTEXITCODE

        if ($uploadExit -ne 0) {
            $lastFailureLog = Get-Content -Raw -Path $uploadLogPath
            Write-Output ("upload failed on attempt {0}" -f $attempt)
            continue
        }

        Write-Output ("[attempt {0}/{1}] verification" -f $attempt, $maxAttempts)
        & powershell -ExecutionPolicy Bypass -File $afterSaveScript -RelativePaths $paths -Url $url -SshTarget $sshTarget -SshKeyPath $sshKeyPath -ServiceName $serviceName -OutputPath $screenshotPath 2>&1 | Tee-Object -FilePath $verifyLogPath
        $verifyExit = $LASTEXITCODE

        if ($verifyExit -eq 0) {
            $completed = $true
            $summary.Add(("SUCCESS | {0} | attempts={1} | screenshot={2}" -f $name, $attempt, $screenshotPath))
            break
        }

        $lastFailureLog = Get-Content -Raw -Path $verifyLogPath
        Write-Output ("verification failed on attempt {0}" -f $attempt)
    }

    if ($completed) {
        continue
    }

    Write-Output ("task failed after {0} attempts, restoring backups" -f $maxAttempts)
    foreach ($item in $backupItems) {
        $targetPath = Join-Path $projectRoot $item.RelativePath
        if ($item.ExistedBefore) {
            & powershell -ExecutionPolicy Bypass -File $restoreScript $item.RelativePath $item.BackupPath | Out-Null
        } elseif (Test-Path $targetPath) {
            Remove-Item -Path $targetPath -Force
        }
    }

    $restoreUploadLogPath = Join-Path $taskRoot "restore_upload.log"
    $restoreUploadArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", $uploadScript,
        "-RelativePaths"
    )
    $restoreUploadArgs += $paths
    $restoreUploadArgs += @("-RemoteHost", $uploadHost, "-Username", $uploadUser, "-SshKeyPath", $sshKeyPath)
    if (-not [string]::IsNullOrWhiteSpace($remotePath)) {
        $restoreUploadArgs += @("-RemoteRoot", $remotePath)
    }
    & powershell @restoreUploadArgs 2>&1 | Tee-Object -FilePath $restoreUploadLogPath
    $restoreUploadExit = $LASTEXITCODE
    if ($restoreUploadExit -ne 0) {
        $summary.Add(("FAILED_UPLOAD_RESTORE | {0} | attempts={1}" -f $name, $maxAttempts))
        continue
    }

    $restoreLogPath = Join-Path $taskRoot "restore_verification.log"
    $restoreScreenshotPath = Join-Path $taskRoot "restore_screenshot.png"
    & powershell -ExecutionPolicy Bypass -File $afterSaveScript -RelativePaths $paths -Url $url -SshTarget $sshTarget -SshKeyPath $sshKeyPath -ServiceName $serviceName -OutputPath $restoreScreenshotPath 2>&1 | Tee-Object -FilePath $restoreLogPath
    $restoreExit = $LASTEXITCODE

    if ($restoreExit -eq 0) {
        $summary.Add(("RESTORED | {0} | attempts={1} | screenshot={2}" -f $name, $maxAttempts, $restoreScreenshotPath))
    } else {
        $summary.Add(("FAILED_RESTORE | {0} | attempts={1}" -f $name, $maxAttempts))
    }
}

$summaryPath = Join-Path $runRoot "summary.txt"
$summary | Set-Content -Path $summaryPath -Encoding UTF8
Write-Output ""
Write-Output ("Night agent run complete. Summary: {0}" -f $summaryPath)
