param(
    [string]$TaskFile = ".\night_agent.v2.example.json"
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom

function Resolve-CodexCommand {
    $command = Get-Command codex -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_CLI_PATH) -and (Test-Path $env:CODEX_CLI_PATH)) {
        return $env:CODEX_CLI_PATH
    }

    $extensionRoot = Join-Path $env:USERPROFILE ".vscode\extensions"
    if (Test-Path $extensionRoot) {
        $candidate = Get-ChildItem $extensionRoot -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }

    return $null
}

function Resolve-TaskValue {
    param(
        [Parameter(Mandatory = $true)] $Task,
        $Defaults = $null,
        [Parameter(Mandatory = $true)] [string]$Name,
        $Fallback = $null
    )

    $taskValue = $Task.PSObject.Properties[$Name]
    if ($taskValue -and -not [string]::IsNullOrWhiteSpace([string]$taskValue.Value)) {
        return $taskValue.Value
    }

    if ($Defaults) {
        $defaultValue = $Defaults.PSObject.Properties[$Name]
        if ($defaultValue -and -not [string]::IsNullOrWhiteSpace([string]$defaultValue.Value)) {
            return $defaultValue.Value
        }
    }

    return $Fallback
}

function Resolve-TaskIntValue {
    param(
        [Parameter(Mandatory = $true)] $Task,
        $Defaults = $null,
        [Parameter(Mandatory = $true)] [string]$Name,
        [int]$Fallback
    )

    $value = Resolve-TaskValue -Task $Task -Defaults $Defaults -Name $Name -Fallback $null
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
        return $Fallback
    }

    return [int]$value
}

function Resolve-TaskArrayValue {
    param(
        [Parameter(Mandatory = $true)] $Task,
        [string]$PrimaryName,
        [string]$AlternateName = ""
    )

    $values = @()
    foreach ($name in @($PrimaryName, $AlternateName)) {
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $property = $Task.PSObject.Properties[$name]
        if ($property -and $null -ne $property.Value) {
            $values = @($property.Value | ForEach-Object { [string]$_ })
            if ($values.Count -gt 0) { break }
        }
    }

    return @($values | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Normalize-RelativePath {
    param([string]$PathText)

    if ([string]::IsNullOrWhiteSpace($PathText)) { return "" }
    $value = $PathText.Trim() -replace "/", "\"
    if ($value.StartsWith(".\")) { $value = $value.Substring(2) }
    return $value.TrimStart("\")
}

function New-UniqueRunRoot {
    param([Parameter(Mandatory = $true)] [string]$ParentPath)

    if (-not (Test-Path $ParentPath)) {
        New-Item -ItemType Directory -Path $ParentPath -Force | Out-Null
    }

    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        $stamp = Get-Date -Format "yyyy-MM-dd-HHmmss-fff"
        $token = [guid]::NewGuid().ToString("N").Substring(0, 6)
        $candidate = Join-Path $ParentPath ("{0}-{1}-{2}" -f $stamp, $PID, $token)
        try {
            New-Item -ItemType Directory -Path $candidate -ErrorAction Stop | Out-Null
            return $candidate
        } catch {
            if (Test-Path $candidate) {
                Start-Sleep -Milliseconds 5
                continue
            }
            throw
        }
    }

    throw "failed to allocate unique run root"
}

function To-RelativePath {
    param(
        [string]$ProjectRoot,
        [string]$FullPath
    )

    $prefix = $ProjectRoot.TrimEnd("\", "/")
    $value = $FullPath
    if ($value.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $value = $value.Substring($prefix.Length)
    }

    return ($value.TrimStart("\", "/") -replace "/", "\")
}

function Get-SkipRegex {
    return '(^|\\|/)(backup|output|node_modules|__pycache__|\.git|\.venv|venv)(\\|/|$)|\.pyc$'
}

function Get-CandidateFiles {
    param([string]$ProjectRoot)

    $skipRegex = Get-SkipRegex
    return Get-ChildItem -LiteralPath $ProjectRoot -Recurse -Force -File |
        Where-Object {
            $rel = To-RelativePath -ProjectRoot $ProjectRoot -FullPath $_.FullName
            return ($rel -notmatch $skipRegex)
        }
}

function New-WorkspaceSnapshot {
    param(
        [string]$ProjectRoot,
        [string]$SnapshotRoot
    )

    if (Test-Path $SnapshotRoot) {
        Remove-Item -LiteralPath $SnapshotRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $SnapshotRoot -Force | Out-Null

    $manifest = New-Object System.Collections.Generic.List[string]
    foreach ($file in Get-CandidateFiles -ProjectRoot $ProjectRoot) {
        $rel = To-RelativePath -ProjectRoot $ProjectRoot -FullPath $file.FullName
        $dest = Join-Path $SnapshotRoot $rel
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $file.FullName -Destination $dest -Force
        $manifest.Add($rel)
    }

    $manifestPath = Join-Path $SnapshotRoot "snapshot_manifest.json"
    $manifest | ConvertTo-Json | Set-Content -Path $manifestPath -Encoding UTF8
}

function Get-SnapshotManifest {
    param([string]$SnapshotRoot)

    $manifestPath = Join-Path $SnapshotRoot "snapshot_manifest.json"
    if (-not (Test-Path $manifestPath)) { return @() }

    $raw = Get-Content -Raw -Path $manifestPath
    if ([string]::IsNullOrWhiteSpace($raw)) { return @() }

    $data = $raw | ConvertFrom-Json
    if ($data -is [System.Array]) { return @($data) }
    if ($null -eq $data) { return @() }
    return @($data)
}

function Get-ChangedFilesFromSnapshot {
    param(
        [string]$ProjectRoot,
        [string]$SnapshotRoot
    )

    $snapshotFiles = Get-SnapshotManifest -SnapshotRoot $SnapshotRoot | ForEach-Object { Normalize-RelativePath $_ }
    $currentFiles = @(Get-CandidateFiles -ProjectRoot $ProjectRoot | ForEach-Object { To-RelativePath -ProjectRoot $ProjectRoot -FullPath $_.FullName })
    $all = @($snapshotFiles + $currentFiles | Sort-Object -Unique)
    $changed = New-Object System.Collections.Generic.List[string]

    foreach ($rel in $all) {
        if ([string]::IsNullOrWhiteSpace($rel)) { continue }

        $snapPath = Join-Path $SnapshotRoot $rel
        $currPath = Join-Path $ProjectRoot $rel
        $snapExists = Test-Path $snapPath
        $currExists = Test-Path $currPath

        if ($snapExists -and -not $currExists) {
            $changed.Add($rel)
            continue
        }
        if (-not $snapExists -and $currExists) {
            $changed.Add($rel)
            continue
        }
        if ($snapExists -and $currExists) {
            $snapHash = (Get-FileHash -LiteralPath $snapPath -Algorithm SHA256).Hash
            $currHash = (Get-FileHash -LiteralPath $currPath -Algorithm SHA256).Hash
            if ($snapHash -ne $currHash) {
                $changed.Add($rel)
            }
        }
    }

    return @($changed | Sort-Object -Unique)
}

function Restore-WorkspaceSnapshot {
    param(
        [string]$ProjectRoot,
        [string]$SnapshotRoot
    )

    $manifest = Get-SnapshotManifest -SnapshotRoot $SnapshotRoot | ForEach-Object { Normalize-RelativePath $_ }
    $manifestSet = @{}
    foreach ($rel in $manifest) { $manifestSet[$rel] = $true }

    foreach ($rel in $manifest) {
        $source = Join-Path $SnapshotRoot $rel
        $dest = Join-Path $ProjectRoot $rel
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $dest -Force
    }

    foreach ($file in Get-CandidateFiles -ProjectRoot $ProjectRoot) {
        $rel = To-RelativePath -ProjectRoot $ProjectRoot -FullPath $file.FullName
        if (-not $manifestSet.ContainsKey($rel)) {
            Remove-Item -LiteralPath $file.FullName -Force
        }
    }
}

function Invoke-CodexExec {
    param(
        [Parameter(Mandatory = $true)] [string]$CodexCommand,
        [Parameter(Mandatory = $true)] [string[]]$Arguments,
        [Parameter(Mandatory = $true)] [string]$Prompt,
        [Parameter(Mandatory = $true)] [string]$LogPath,
        [Parameter(Mandatory = $true)] [string]$WorkingDirectory,
        [int]$TimeoutSeconds = 300
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
    $timedOut = $false
    $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max($TimeoutSeconds, 30))
    while (-not $process.HasExited) {
        if ([DateTime]::UtcNow -ge $deadline) {
            $timedOut = $true
            try { $process.Kill() } catch {}
            break
        }
        Start-Sleep -Milliseconds 250
    }

    if (-not $process.HasExited) {
        $process.WaitForExit()
    }

    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result
    $combined = ($stdout, $stderr | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join [Environment]::NewLine
    if ($timedOut) {
        $combined = (($combined, "night_agent_v2: codex exec timed out after $TimeoutSeconds seconds") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join [Environment]::NewLine
    }
    Set-Content -Path $LogPath -Value $combined -Encoding UTF8

    return [PSCustomObject]@{
        ExitCode = $(if ($timedOut) { 124 } else { $process.ExitCode })
        Output   = $combined
    }
}

function ConvertFrom-JsonLoose {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }

    try {
        return ($Text | ConvertFrom-Json)
    } catch {}

    $fenceMatch = [regex]::Match($Text, '```json\s*(\{[\s\S]*?\})\s*```', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if ($fenceMatch.Success) {
        try { return ($fenceMatch.Groups[1].Value | ConvertFrom-Json) } catch {}
    }

    for ($start = 0; $start -lt $Text.Length; $start++) {
        if ($Text[$start] -ne '{') { continue }

        $depth = 0
        $inString = $false
        $escape = $false

        for ($index = $start; $index -lt $Text.Length; $index++) {
            $ch = $Text[$index]

            if ($inString) {
                if ($escape) {
                    $escape = $false
                    continue
                }
                if ($ch -eq '\') {
                    $escape = $true
                    continue
                }
                if ($ch -eq '"') {
                    $inString = $false
                }
                continue
            }

            if ($ch -eq '"') {
                $inString = $true
                continue
            }
            if ($ch -eq '{') {
                $depth++
                continue
            }
            if ($ch -eq '}') {
                $depth--
                if ($depth -eq 0) {
                    $jsonText = $Text.Substring($start, $index - $start + 1)
                    try {
                        return ($jsonText | ConvertFrom-Json)
                    } catch {
                        break
                    }
                }
            }
        }
    }

    return $null
}

function Get-BulletText {
    param([string[]]$Items)

    if (-not $Items -or $Items.Count -eq 0) { return "- none" }
    return (($Items | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { "- $_" }) -join [Environment]::NewLine)
}

function New-TaskRunDirectoryName {
    param(
        [int]$Sequence,
        [string]$TaskId,
        [string]$Name
    )

    $labels = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in @($TaskId, $Name)) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        if ($labels.Contains($candidate)) { continue }
        $labels.Add($candidate)
    }

    $label = if ($labels.Count -gt 0) { $labels -join "__" } else { "task" }
    $safeLabel = $label -replace '[\\/:*?""<>| ]', "_"
    return ("{0:d3}_{1}" -f $Sequence, $safeLabel)
}

function Invoke-LocalVerification {
    param(
        [string]$ProjectRoot,
        [string[]]$RelativePaths,
        [string]$BaselineRoot,
        [string]$LogPath
    )

    $scriptPath = Join-Path $ProjectRoot "scripts\run_edit_verification.ps1"
    if (-not (Test-Path $scriptPath)) {
        throw "run_edit_verification.ps1 not found"
    }

    $relativePathArgs = @($RelativePaths | ForEach-Object {
        "'{0}'" -f ($_.Replace("'", "''"))
    }) -join ", "
    $command = "& '{0}' -RelativePaths @({1})" -f ($scriptPath.Replace("'", "''")), $relativePathArgs
    if (-not [string]::IsNullOrWhiteSpace($BaselineRoot)) {
        $command += " -BaselineRoot '{0}'" -f ($BaselineRoot.Replace("'", "''"))
    }

    $output = & powershell -ExecutionPolicy Bypass -Command $command 2>&1
    $exitCode = $LASTEXITCODE
    @($output) | Tee-Object -FilePath $LogPath | Out-Null
    return [int]$exitCode
}

function Invoke-ReviewerGate {
    param(
        [Parameter(Mandatory = $true)] [string]$ProjectRoot,
        [Parameter(Mandatory = $true)] [string]$TaskFile,
        [Parameter(Mandatory = $true)] [string]$TaskId,
        [Parameter(Mandatory = $true)] [string]$BeforeDir,
        [Parameter(Mandatory = $true)] [string[]]$ChangedFiles,
        [Parameter(Mandatory = $true)] [string]$LogPath
    )

    $reviewerScript = Join-Path $ProjectRoot "scripts\review_patch_against_contract.js"
    if (-not (Test-Path $reviewerScript)) {
        throw "review_patch_against_contract.js not found"
    }

    $changedFilesPath = [System.IO.Path]::ChangeExtension($LogPath, ".changed_files.txt")
    $ChangedFiles | Set-Content -Path $changedFilesPath -Encoding UTF8

    try {
        $output = & node $reviewerScript `
            --project-root $ProjectRoot `
            --task-file $TaskFile `
            --task-id $TaskId `
            --before-dir $BeforeDir `
            --changed-files $changedFilesPath 2>&1
        $exitCode = $LASTEXITCODE
        @($output) | Tee-Object -FilePath $LogPath | Out-Null
        return [int]$exitCode
    } catch {
        $errorText = $_ | Out-String
        if (-not [string]::IsNullOrWhiteSpace($errorText)) {
            Set-Content -Path $LogPath -Value $errorText -Encoding UTF8
        }
        return 1
    }
}

function Invoke-UploadChangedFiles {
    param(
        [string]$ProjectRoot,
        [string[]]$RelativePaths,
        [string]$RemoteHost,
        [string]$Username,
        [string]$SshKeyPath,
        [string]$RemoteRoot,
        [string]$LogPath
    )

    $uploadScript = Join-Path $ProjectRoot "scripts\upload_changed_files.ps1"
    if (-not (Test-Path $uploadScript)) { throw "upload_changed_files.ps1 not found" }

    $invokeParams = @{
        RelativePaths = $RelativePaths
    }
    if (-not [string]::IsNullOrWhiteSpace($RemoteHost)) { $invokeParams.RemoteHost = $RemoteHost }
    if (-not [string]::IsNullOrWhiteSpace($Username)) { $invokeParams.Username = $Username }
    if (-not [string]::IsNullOrWhiteSpace($SshKeyPath)) { $invokeParams.SshKeyPath = $SshKeyPath }
    if (-not [string]::IsNullOrWhiteSpace($RemoteRoot)) { $invokeParams.RemoteRoot = $RemoteRoot }

    try {
        $output = & $uploadScript @invokeParams 2>&1
        $exitCode = $LASTEXITCODE
        @($output) | Tee-Object -FilePath $LogPath | Out-Null
        return [int]$exitCode
    } catch {
        $errorText = $_ | Out-String
        if (-not [string]::IsNullOrWhiteSpace($errorText)) {
            Add-Content -Path $LogPath -Value $errorText -Encoding UTF8
        }
        return 1
    }
}

function Invoke-RemoteRestartIfNeeded {
    param(
        [string[]]$RelativePaths,
        [string]$SshTarget,
        [string]$SshKeyPath,
        [string]$ServiceName,
        [string]$LogPath
    )

    $needsRestart = $false
    foreach ($p in $RelativePaths) {
        if ([System.IO.Path]::GetExtension($p).ToLowerInvariant() -eq ".py") {
            $needsRestart = $true
            break
        }
    }

    if (-not $needsRestart) {
        Set-Content -Path $LogPath -Value "remote restart skipped (no python file)" -Encoding UTF8
        return 0
    }

    if ([string]::IsNullOrWhiteSpace($SshTarget)) {
        Set-Content -Path $LogPath -Value "python file changed but sshTarget missing" -Encoding UTF8
        return 1
    }

    $restartCommand = "sudo systemctl restart $ServiceName && sudo systemctl status $ServiceName --no-pager"
    if ([string]::IsNullOrWhiteSpace($SshKeyPath)) {
        $output = & ssh $SshTarget $restartCommand 2>&1
    } else {
        $output = & ssh -i $SshKeyPath $SshTarget $restartCommand 2>&1
    }
    $exitCode = $LASTEXITCODE
    @($output) | Tee-Object -FilePath $LogPath | Out-Null
    return [int]$exitCode
}

function Restore-RemoteStateIfPossible {
    param(
        [string]$ProjectRoot,
        [string]$SnapshotRoot,
        [string[]]$RelativePaths,
        [string]$RemoteHost,
        [string]$Username,
        [string]$SshTarget,
        [string]$SshKeyPath,
        [string]$RemoteRoot,
        [string]$ServiceName,
        [string]$AttemptRoot,
        [string]$Prefix
    )

    Restore-WorkspaceSnapshot -ProjectRoot $ProjectRoot -SnapshotRoot $SnapshotRoot

    if ([string]::IsNullOrWhiteSpace($RemoteHost) -or [string]::IsNullOrWhiteSpace($Username)) {
        return
    }

    $restoreUploadLogPath = Join-Path $AttemptRoot ("{0}_upload.log" -f $Prefix)
    [void](Invoke-UploadChangedFiles -ProjectRoot $ProjectRoot -RelativePaths $RelativePaths -RemoteHost $RemoteHost -Username $Username -SshKeyPath $SshKeyPath -RemoteRoot $RemoteRoot -LogPath $restoreUploadLogPath)

    $restoreRestartLogPath = Join-Path $AttemptRoot ("{0}_restart.log" -f $Prefix)
    [void](Invoke-RemoteRestartIfNeeded -RelativePaths $RelativePaths -SshTarget $SshTarget -SshKeyPath $SshKeyPath -ServiceName $ServiceName -LogPath $restoreRestartLogPath)
}

function Invoke-BrowserVerification {
    param(
        [string]$ProjectRoot,
        [string[]]$RelativePaths,
        $Verification,
        [string]$DefaultUrl,
        [string]$OutputPath,
        [string]$LogPath
    )

    if ($Verification) {
        $verificationRunner = Join-Path $ProjectRoot "scripts\run_task_verification.js"
        if (-not (Test-Path $verificationRunner)) {
            throw "run_task_verification.js not found"
        }

        $spec = @{}
        foreach ($property in $Verification.PSObject.Properties) {
            $spec[$property.Name] = $property.Value
        }

        if (-not $spec.ContainsKey("url") -or [string]::IsNullOrWhiteSpace([string]$spec.url)) {
            $spec["url"] = $DefaultUrl
        }
        if (-not $spec.ContainsKey("outputPath") -or [string]::IsNullOrWhiteSpace([string]$spec.outputPath)) {
            $spec["outputPath"] = $OutputPath
        }

        $specPath = [System.IO.Path]::ChangeExtension($OutputPath, ".verification.json")
        $spec | ConvertTo-Json -Depth 20 | Set-Content -Path $specPath -Encoding UTF8

        try {
            $output = & node $verificationRunner $specPath 2>&1
            $exitCode = $LASTEXITCODE
            @($output) | Tee-Object -FilePath $LogPath | Out-Null
            return [int]$exitCode
        } catch {
            $errorText = $_ | Out-String
            if (-not [string]::IsNullOrWhiteSpace($errorText)) {
                Set-Content -Path $LogPath -Value $errorText -Encoding UTF8
            }
            return 1
        }
    }

    $fallbackScript = Join-Path $ProjectRoot "scripts\run_edit_verification.ps1"
    $verificationRunner = Join-Path $ProjectRoot "scripts\run_task_verification.js"
    try {
        if (Test-Path $verificationRunner) {
            $specPath = [System.IO.Path]::ChangeExtension($OutputPath, ".verification.json")
            $useAuth = (-not [string]::IsNullOrWhiteSpace($env:CHANG_ADMIN_ID)) -and (-not [string]::IsNullOrWhiteSpace($env:CHANG_ADMIN_PW))
            $spec = @{
                url = $DefaultUrl
                useAuth = $useAuth
                forbidDialogs = $false
                forbidPageErrors = $true
                outputPath = $OutputPath
                steps = @(
                    @{
                        action = "waitFor"
                        selector = "body"
                        timeout = 15000
                    },
                    @{
                        action = "screenshot"
                    }
                )
            }
            $spec | ConvertTo-Json -Depth 20 | Set-Content -Path $specPath -Encoding UTF8
            $output = & node $verificationRunner $specPath 2>&1
            $exitCode = $LASTEXITCODE
            @($output) | Tee-Object -FilePath $LogPath | Out-Null
            return [int]$exitCode
        }

        $output = & powershell -ExecutionPolicy Bypass -File $fallbackScript -RelativePaths $RelativePaths -Url $DefaultUrl -OutputPath $OutputPath 2>&1
        $exitCode = $LASTEXITCODE
        @($output) | Tee-Object -FilePath $LogPath | Out-Null
        return [int]$exitCode
    } catch {
        $errorText = $_ | Out-String
        if (-not [string]::IsNullOrWhiteSpace($errorText)) {
            Set-Content -Path $LogPath -Value $errorText -Encoding UTF8
        }
        return 1
    }
}

function Get-ExistingRepoPrompt {
    param([string]$ProjectRoot)

    $promptPath = Join-Path $ProjectRoot ".codex_prompt.md"
    if (-not (Test-Path $promptPath)) { return "" }
    return Get-Content -Raw -Path $promptPath
}

function New-TaskInstructionFromGoal {
    param(
        [string]$Goal,
        [string[]]$Acceptance,
        [string[]]$DoNotTouch,
        [string]$RollbackPlan,
        [string]$PromotionRule
    )

    $sections = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($Goal)) {
        $sections.Add("Goal:`n$Goal")
    }
    if ($Acceptance -and $Acceptance.Count -gt 0) {
        $sections.Add("Acceptance:`n" + (Get-BulletText -Items $Acceptance))
    }
    if ($DoNotTouch -and $DoNotTouch.Count -gt 0) {
        $sections.Add("Do not touch:`n" + (Get-BulletText -Items $DoNotTouch))
    }
    if (-not [string]::IsNullOrWhiteSpace($RollbackPlan)) {
        $sections.Add("Rollback plan:`n- $RollbackPlan")
    }
    if (-not [string]::IsNullOrWhiteSpace($PromotionRule)) {
        $sections.Add("Promotion rule:`n- $PromotionRule")
    }

    return ($sections -join [Environment]::NewLine + [Environment]::NewLine)
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$taskPath = if ([System.IO.Path]::IsPathRooted($TaskFile)) { $TaskFile } else { Join-Path $projectRoot $TaskFile }

if (-not (Test-Path $taskPath)) {
    throw "task file not found: $taskPath"
}

$schemaPath = Join-Path $projectRoot "brain\TASK_QUEUE\task.schema.json"
if (Test-Path $schemaPath) {
    $queueValidator = Join-Path $projectRoot "scripts\validate_task_queue.js"
    if (-not (Test-Path $queueValidator)) {
        throw "validate_task_queue.js not found"
    }

    $schemaValidationLogPath = Join-Path $projectRoot "output\night_agent_v2\last_schema_validation.json"
    $schemaValidationDir = Split-Path -Parent $schemaValidationLogPath
    if (-not (Test-Path $schemaValidationDir)) {
        New-Item -ItemType Directory -Path $schemaValidationDir -Force | Out-Null
    }

    $schemaValidationOutput = & node $queueValidator $taskPath $schemaPath 2>&1
    $schemaValidationExit = $LASTEXITCODE
    @($schemaValidationOutput) | Set-Content -Path $schemaValidationLogPath -Encoding UTF8
    if ($schemaValidationExit -ne 0) {
        throw ("task schema validation failed: {0}" -f $schemaValidationLogPath)
    }
}

$codexCommand = Resolve-CodexCommand
if (-not $codexCommand) {
    throw "codex command not found"
}

$config = (Get-Content -Raw -Path $taskPath | ConvertFrom-Json)
if (-not $config.tasks -or $config.tasks.Count -eq 0) {
    throw "no tasks found"
}

$defaults = $config.defaults
$repoPrompt = Get-ExistingRepoPrompt -ProjectRoot $projectRoot
$runRoot = New-UniqueRunRoot -ParentPath (Join-Path $projectRoot "output\night_agent_v2")

$summary = New-Object System.Collections.Generic.List[string]
$hadFailure = $false
$taskSequence = 0

foreach ($task in $config.tasks) {
    $taskSequence += 1
    $taskId = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "task_id" -Fallback "")
    $name = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "name" -Fallback "")
    if ([string]::IsNullOrWhiteSpace($name)) {
        $name = $taskId
    }
    if ([string]::IsNullOrWhiteSpace($name)) {
        $name = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "goal" -Fallback "")
    }

    $goal = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "goal" -Fallback "")
    $reuseSymbols = Resolve-TaskArrayValue -Task $task -PrimaryName "reuseSymbols" -AlternateName "reuse_symbols"
    $doNotTouch = Resolve-TaskArrayValue -Task $task -PrimaryName "doNotTouch" -AlternateName "do_not_touch"
    $acceptance = Resolve-TaskArrayValue -Task $task -PrimaryName "acceptance"
    $rollbackPlan = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "rollback_plan" -Fallback "")
    $promotionRule = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "promotion_rule" -Fallback "")

    $instruction = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "instructionKo" -Fallback "")
    if ([string]::IsNullOrWhiteSpace($instruction)) {
        $instruction = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "instruction" -Fallback "")
    }
    if ([string]::IsNullOrWhiteSpace($instruction) -and -not [string]::IsNullOrWhiteSpace($goal)) {
        $instruction = New-TaskInstructionFromGoal -Goal $goal -Acceptance $acceptance -DoNotTouch $doNotTouch -RollbackPlan $rollbackPlan -PromotionRule $promotionRule
    }

    if ([string]::IsNullOrWhiteSpace($name)) { throw "task name or task_id is required" }
    if ([string]::IsNullOrWhiteSpace($instruction)) { throw "instruction or goal is required: $name" }

    $taskUrl = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "url" -Fallback "")
    $taskPathValues = Resolve-TaskArrayValue -Task $task -PrimaryName "paths" -AlternateName "target_files"
    $taskPaths = @($taskPathValues | ForEach-Object { Normalize-RelativePath $_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    if ($taskPaths.Count -eq 0) { throw "task paths are required: $name" }
    $verification = $task.verification
    if ([string]::IsNullOrWhiteSpace($taskUrl) -and $verification) {
        $taskUrl = [string](Resolve-TaskValue -Task $verification -Defaults $null -Name "url" -Fallback "")
    }
    $maxAttempts = Resolve-TaskIntValue -Task $task -Defaults $defaults -Name "maxAttempts" -Fallback 2
    $maxChangedFiles = Resolve-TaskIntValue -Task $task -Defaults $defaults -Name "maxChangedFiles" -Fallback $taskPaths.Count
    $allowNewFiles = [System.Convert]::ToBoolean((Resolve-TaskValue -Task $task -Defaults $defaults -Name "allowNewFiles" -Fallback $false))
    $requirePlanJson = [System.Convert]::ToBoolean((Resolve-TaskValue -Task $task -Defaults $defaults -Name "requirePlanJson" -Fallback $true))
    $sshTarget = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "sshTarget" -Fallback "")
    $sshKeyPath = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "sshKeyPath" -Fallback "")
    $serviceName = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "serviceName" -Fallback "mysite")
    $remotePath = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "remotePath" -Fallback "")
    $model = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "model" -Fallback "")
    $modelReasoningEffort = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "modelReasoningEffort" -Fallback "")
    if ([string]::IsNullOrWhiteSpace($modelReasoningEffort)) {
        $modelReasoningEffort = [string](Resolve-TaskValue -Task $task -Defaults $defaults -Name "model_reasoning_effort" -Fallback "")
    }
    $codexTimeoutSeconds = Resolve-TaskIntValue -Task $task -Defaults $defaults -Name "codexTimeoutSeconds" -Fallback 300

    $taskRoot = Join-Path $runRoot (New-TaskRunDirectoryName -Sequence $taskSequence -TaskId $taskId -Name $name)
    New-Item -ItemType Directory -Path $taskRoot -Force | Out-Null
    $snapshotRoot = Join-Path $taskRoot "workspace_snapshot"
    New-WorkspaceSnapshot -ProjectRoot $projectRoot -SnapshotRoot $snapshotRoot

    $uploadUser = ""
    $uploadHost = ""
    if (-not [string]::IsNullOrWhiteSpace($sshTarget)) {
        $sshMatch = [regex]::Match($sshTarget, '^(?<user>[^@]+)@(?<host>.+)$')
        if (-not $sshMatch.Success) { throw "invalid sshTarget format: $sshTarget" }
        $uploadUser = $sshMatch.Groups["user"].Value
        $uploadHost = $sshMatch.Groups["host"].Value
    }

    Write-Output ""
    Write-Output ("=== night agent v2 task: {0} ===" -f $name)
    Write-Output ("- paths: {0}" -f ($taskPaths -join ", "))
    Write-Output ("- max attempts: {0}" -f $maxAttempts)

    $completed = $false
    $lastFailureLog = ""

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        Restore-WorkspaceSnapshot -ProjectRoot $projectRoot -SnapshotRoot $snapshotRoot

        $attemptRoot = Join-Path $taskRoot ("attempt-{0}" -f $attempt)
        New-Item -ItemType Directory -Path $attemptRoot -Force | Out-Null

        $planOutPath = Join-Path $attemptRoot "plan_message.txt"
        $planLogPath = Join-Path $attemptRoot "plan_exec.log"
        $applyOutPath = Join-Path $attemptRoot "apply_message.txt"
        $applyLogPath = Join-Path $attemptRoot "apply_exec.log"
        $localVerifyLogPath = Join-Path $attemptRoot "local_verification.log"
        $reviewLogPath = Join-Path $attemptRoot "reviewer_gate.log"
        $uploadLogPath = Join-Path $attemptRoot "upload.log"
        $restartLogPath = Join-Path $attemptRoot "restart.log"
        $browserLogPath = Join-Path $attemptRoot "browser_verification.log"
        $screenshotPath = Join-Path $attemptRoot "browser_check.png"

        $planPrompt = @"
You are in planning mode only.
Do not edit files.

Task name:
$name

Allowed target files:
$(Get-BulletText -Items $taskPaths)

User instruction:
$instruction

Reuse existing structure and symbols:
$(Get-BulletText -Items $reuseSymbols)

Do not touch:
$(Get-BulletText -Items $doNotTouch)

Acceptance:
$(Get-BulletText -Items $acceptance)

Existing repo prompt:
$repoPrompt

Planning rules:
- Edit nothing in plan stage.
- Do not create new files.
- Do not broaden scope.
- Return one JSON object only.

Return exactly:
{
  "files": [
    {
      "path": "relative\\path",
      "why": "short reason",
      "symbols": ["existing ids/functions/classes to reuse"],
      "touch": "minimal"
    }
  ],
  "checks": ["verification points"],
  "blocked": ["blocked or empty"],
  "risk": "main risk summary"
}
"@

        if ($attempt -gt 1 -and -not [string]::IsNullOrWhiteSpace($lastFailureLog)) {
            $planPrompt += @"

Previous failure log:
$lastFailureLog
"@
        }

        $planArgs = @("-a", "never", "-s", "workspace-write", "exec", "--skip-git-repo-check", "-C", $projectRoot, "-o", $planOutPath)
        if (-not [string]::IsNullOrWhiteSpace($model)) { $planArgs += @("-m", $model) }
        if (-not [string]::IsNullOrWhiteSpace($modelReasoningEffort)) { $planArgs += @("-c", ('model_reasoning_effort="{0}"' -f $modelReasoningEffort)) }
        $planArgs += "-"

        $planResult = Invoke-CodexExec -CodexCommand $codexCommand -Arguments $planArgs -Prompt $planPrompt -LogPath $planLogPath -WorkingDirectory $projectRoot -TimeoutSeconds $codexTimeoutSeconds
        if ($planResult.ExitCode -ne 0) {
            $lastFailureLog = $planResult.Output
            Write-Output ("plan step failed on attempt {0}" -f $attempt)
            continue
        }

        $planTouchedFiles = Get-ChangedFilesFromSnapshot -ProjectRoot $projectRoot -SnapshotRoot $snapshotRoot
        if ($planTouchedFiles.Count -gt 0) {
            $lastFailureLog = "plan step modified files unexpectedly: " + ($planTouchedFiles -join ", ")
            Write-Output $lastFailureLog
            continue
        }

        $planSourceText = $planResult.Output
        if (Test-Path $planOutPath) {
            $planSourceText = Get-Content -Raw -Encoding UTF8 -Path $planOutPath
        }
        $planJson = ConvertFrom-JsonLoose -Text $planSourceText
        if ($requirePlanJson -and $null -eq $planJson) {
            $lastFailureLog = "plan step did not return valid JSON"
            Write-Output $lastFailureLog
            continue
        }

        if ($planJson -and $planJson.files) {
            $plannedPaths = @($planJson.files | ForEach-Object { Normalize-RelativePath $_.path } | Select-Object -Unique)
            $outsidePlan = @($plannedPaths | Where-Object { $taskPaths -notcontains $_ })
            if ($outsidePlan.Count -gt 0) {
                $lastFailureLog = "plan includes non-target paths: " + ($outsidePlan -join ", ")
                Write-Output $lastFailureLog
                continue
            }
        }

        $approvedPlanText = if ($planJson) { ($planJson | ConvertTo-Json -Depth 20) } else { $planResult.Output }

        $applyPrompt = @"
Apply a minimal patch for this task.

Task name:
$name

Allowed target files:
$(Get-BulletText -Items $taskPaths)

Approved plan:
$approvedPlanText

User instruction:
$instruction

Reuse existing structure and symbols:
$(Get-BulletText -Items $reuseSymbols)

Do not touch:
$(Get-BulletText -Items $doNotTouch)

Acceptance:
$(Get-BulletText -Items $acceptance)

Existing repo prompt:
$repoPrompt

Apply rules:
- Edit only allowed target files.
- No helper file creation unless task explicitly allows it.
- Keep patches small.
- Preserve existing ids/functions/classes where possible.
- Do not reformat unrelated sections.

Return:
1. changed files
2. why
3. unified diff
4. checks
5. residual risks
"@

        $applyArgs = @("-a", "never", "-s", "workspace-write", "exec", "--skip-git-repo-check", "-C", $projectRoot, "-o", $applyOutPath)
        if (-not [string]::IsNullOrWhiteSpace($model)) { $applyArgs += @("-m", $model) }
        if (-not [string]::IsNullOrWhiteSpace($modelReasoningEffort)) { $applyArgs += @("-c", ('model_reasoning_effort="{0}"' -f $modelReasoningEffort)) }
        $applyArgs += "-"

        $applyResult = Invoke-CodexExec -CodexCommand $codexCommand -Arguments $applyArgs -Prompt $applyPrompt -LogPath $applyLogPath -WorkingDirectory $projectRoot -TimeoutSeconds $codexTimeoutSeconds
        if ($applyResult.ExitCode -ne 0) {
            $lastFailureLog = $applyResult.Output
            Write-Output ("apply step failed on attempt {0}" -f $attempt)
            continue
        }

        $changedFiles = @(Get-ChangedFilesFromSnapshot -ProjectRoot $projectRoot -SnapshotRoot $snapshotRoot | Where-Object { $_ -notmatch (Get-SkipRegex) })
        if ($changedFiles.Count -eq 0) {
            $lastFailureLog = "no file changed"
            Write-Output $lastFailureLog
            continue
        }

        $outsideScope = @($changedFiles | Where-Object { $taskPaths -notcontains $_ })
        if ($outsideScope.Count -gt 0) {
            $lastFailureLog = "changed files outside target scope: " + ($outsideScope -join ", ")
            Write-Output $lastFailureLog
            continue
        }

        if (-not $allowNewFiles) {
            $manifest = @(Get-SnapshotManifest -SnapshotRoot $snapshotRoot | ForEach-Object { Normalize-RelativePath $_ })
            $newFiles = @($changedFiles | Where-Object { $manifest -notcontains $_ })
            if ($newFiles.Count -gt 0) {
                $lastFailureLog = "new files created but not allowed: " + ($newFiles -join ", ")
                Write-Output $lastFailureLog
                continue
            }
        }

        if ($changedFiles.Count -gt $maxChangedFiles) {
            $lastFailureLog = "too many changed files: $($changedFiles.Count) > $maxChangedFiles"
            Write-Output $lastFailureLog
            continue
        }

        if (-not [string]::IsNullOrWhiteSpace($taskId)) {
            $reviewExit = Invoke-ReviewerGate -ProjectRoot $projectRoot -TaskFile $taskPath -TaskId $taskId -BeforeDir $snapshotRoot -ChangedFiles $changedFiles -LogPath $reviewLogPath
            if ($reviewExit -ne 0) {
                $lastFailureLog = Get-Content -Raw -Path $reviewLogPath
                Write-Output ("reviewer gate failed on attempt {0}" -f $attempt)
                continue
            }
        }

        $localVerifyExit = Invoke-LocalVerification -ProjectRoot $projectRoot -RelativePaths $changedFiles -BaselineRoot $snapshotRoot -LogPath $localVerifyLogPath
        if ($localVerifyExit -ne 0) {
            $lastFailureLog = Get-Content -Raw -Path $localVerifyLogPath
            Write-Output ("local verification failed on attempt {0}" -f $attempt)
            continue
        }

        $uploadExit = Invoke-UploadChangedFiles -ProjectRoot $projectRoot -RelativePaths $changedFiles -RemoteHost $uploadHost -Username $uploadUser -SshKeyPath $sshKeyPath -RemoteRoot $remotePath -LogPath $uploadLogPath
        if ($uploadExit -ne 0) {
            $lastFailureLog = Get-Content -Raw -Path $uploadLogPath
            Write-Output ("upload failed on attempt {0}" -f $attempt)
            Restore-RemoteStateIfPossible -ProjectRoot $projectRoot -SnapshotRoot $snapshotRoot -RelativePaths $changedFiles -RemoteHost $uploadHost -Username $uploadUser -SshTarget $sshTarget -SshKeyPath $sshKeyPath -RemoteRoot $remotePath -ServiceName $serviceName -AttemptRoot $attemptRoot -Prefix "restore_after_upload_failure"
            continue
        }

        $restartExit = Invoke-RemoteRestartIfNeeded -RelativePaths $changedFiles -SshTarget $sshTarget -SshKeyPath $sshKeyPath -ServiceName $serviceName -LogPath $restartLogPath
        if ($restartExit -ne 0) {
            $lastFailureLog = Get-Content -Raw -Path $restartLogPath
            Write-Output ("restart failed on attempt {0}" -f $attempt)
            Restore-RemoteStateIfPossible -ProjectRoot $projectRoot -SnapshotRoot $snapshotRoot -RelativePaths $changedFiles -RemoteHost $uploadHost -Username $uploadUser -SshTarget $sshTarget -SshKeyPath $sshKeyPath -RemoteRoot $remotePath -ServiceName $serviceName -AttemptRoot $attemptRoot -Prefix "restore_after_restart_failure"
            continue
        }

        $browserExit = Invoke-BrowserVerification -ProjectRoot $projectRoot -RelativePaths $changedFiles -Verification $verification -DefaultUrl $taskUrl -OutputPath $screenshotPath -LogPath $browserLogPath
        if ($browserExit -ne 0) {
            $lastFailureLog = Get-Content -Raw -Path $browserLogPath
            Write-Output ("browser verification failed on attempt {0}" -f $attempt)
            Restore-RemoteStateIfPossible -ProjectRoot $projectRoot -SnapshotRoot $snapshotRoot -RelativePaths $changedFiles -RemoteHost $uploadHost -Username $uploadUser -SshTarget $sshTarget -SshKeyPath $sshKeyPath -RemoteRoot $remotePath -ServiceName $serviceName -AttemptRoot $attemptRoot -Prefix "restore_after_browser_failure"
            continue
        }

        $summary.Add(("SUCCESS | {0} | changed={1} | screenshot={2}" -f $name, ($changedFiles -join ", "), $screenshotPath))
        $completed = $true
        break
    }

    if (-not $completed) {
        Restore-RemoteStateIfPossible -ProjectRoot $projectRoot -SnapshotRoot $snapshotRoot -RelativePaths $taskPaths -RemoteHost $uploadHost -Username $uploadUser -SshTarget $sshTarget -SshKeyPath $sshKeyPath -RemoteRoot $remotePath -ServiceName $serviceName -AttemptRoot $taskRoot -Prefix "final_restore"
        $summary.Add(("FAILED | {0}" -f $name))
        $hadFailure = $true
    }
}

$summaryPath = Join-Path $runRoot "summary.txt"
$summary | Set-Content -Path $summaryPath -Encoding UTF8
Write-Output ""
Write-Output ("Night agent v2 run complete. Summary: {0}" -f $summaryPath)
if ($hadFailure) {
    throw ("night agent v2 completed with failed task(s). Summary: {0}" -f $summaryPath)
}
