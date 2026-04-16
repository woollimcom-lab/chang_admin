param(
    [string]$RequestFile = ".\brain\TASK_QUEUE\request.example.json",
    [string]$GeneratedTaskFile = "",
    [switch]$CompileOnly,
    [switch]$AllowRiskyHotspots
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom

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

function Convert-YamlScalarValue {
    param([string]$Text)

    if ($null -eq $Text) { return $null }
    $value = $Text.Trim()
    if (($value.StartsWith("'") -and $value.EndsWith("'")) -or ($value.StartsWith('"') -and $value.EndsWith('"'))) {
        $value = $value.Substring(1, $value.Length - 2)
    }

    if ($value -match '^(true|false)$') {
        return [System.Convert]::ToBoolean($value)
    }
    if ($value -match '^-?\d+$') {
        return [int]$value
    }
    return $value
}

function Read-V3RiskConfig {
    param([string]$StateMapPath)

    $config = @{
        execution_guard = [ordered]@{
            block_on_risky_hotspot = $true
            default_hotspot_threshold = 2
        }
        risk_files = @()
    }

    if (-not (Test-Path $StateMapPath)) {
        return [pscustomobject]$config
    }

    $section = ""
    $currentRisk = $null
    foreach ($rawLine in Get-Content -Path $StateMapPath) {
        $line = ($rawLine -replace "`t", "    ").TrimEnd()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) { continue }

        if ($line -match '^execution_guard:\s*$') {
            if ($currentRisk) {
                $config.risk_files += [pscustomobject]$currentRisk
                $currentRisk = $null
            }
            $section = "execution_guard"
            continue
        }

        if ($line -match '^risk_files:\s*$') {
            if ($currentRisk) {
                $config.risk_files += [pscustomobject]$currentRisk
                $currentRisk = $null
            }
            $section = "risk_files"
            continue
        }

        if ($section -eq "execution_guard" -and $line -match '^\s{2}([a-zA-Z0-9_]+):\s*(.+?)\s*$') {
            $config.execution_guard[$matches[1]] = Convert-YamlScalarValue $matches[2]
            continue
        }

        if ($section -eq "risk_files") {
            if ($line -match '^\s{2}-\s*path:\s*(.+?)\s*$') {
                if ($currentRisk) {
                    $config.risk_files += [pscustomobject]$currentRisk
                }
                $currentRisk = [ordered]@{
                    path = Normalize-RelativePath (Convert-YamlScalarValue $matches[1])
                    risk_level = "medium"
                    max_tasks_per_run = 1
                    prefer_batch_isolation = $false
                    note = ""
                }
                continue
            }

            if ($currentRisk -and $line -match '^\s{4}([a-zA-Z0-9_]+):\s*(.+?)\s*$') {
                $currentRisk[$matches[1]] = Convert-YamlScalarValue $matches[2]
                if ($matches[1] -eq "path") {
                    $currentRisk[$matches[1]] = Normalize-RelativePath ([string]$currentRisk[$matches[1]])
                }
            }
        }
    }

    if ($currentRisk) {
        $config.risk_files += [pscustomobject]$currentRisk
    }

    return [pscustomobject]$config
}

function Get-V3RiskFindings {
    param(
        [Parameter(Mandatory = $true)] $Queue,
        [Parameter(Mandatory = $true)] $RiskConfig
    )

    $findings = @()
    $warnings = @()
    $blockingFindings = @()
    $taskFileMap = @{}

    foreach ($task in @($Queue.tasks)) {
        $taskId = [string]$task.task_id
        $batch = if ($task.PSObject.Properties["batch"]) { [string]$task.batch } else { "default" }
        foreach ($file in @($task.target_files)) {
            $normalized = Normalize-RelativePath ([string]$file)
            if (-not $taskFileMap.ContainsKey($normalized)) {
                $taskFileMap[$normalized] = @()
            }
            $taskFileMap[$normalized] += [pscustomobject]@{
                task_id = $taskId
                batch = if ([string]::IsNullOrWhiteSpace($batch)) { "default" } else { $batch }
            }
        }
    }

    foreach ($riskFile in @($RiskConfig.risk_files)) {
        $path = Normalize-RelativePath ([string]$riskFile.path)
        if (-not $taskFileMap.ContainsKey($path)) { continue }

        $refs = @($taskFileMap[$path] | ForEach-Object { $_ })
        $taskIds = @($refs | ForEach-Object { $_.task_id } | Sort-Object -Unique)
        $batches = @($refs | ForEach-Object { $_.batch } | Sort-Object -Unique)
        $maxTasks = if ($riskFile.PSObject.Properties["max_tasks_per_run"]) { [int]$riskFile.max_tasks_per_run } else { 1 }
        $preferIsolation = $false
        if ($riskFile.PSObject.Properties["prefer_batch_isolation"]) {
            $preferIsolation = [bool]$riskFile.prefer_batch_isolation
        }

        $taskCount = $taskIds.Count
        $exceedsLimit = $taskCount -gt $maxTasks
        $crossBatch = $batches.Count -gt 1
        $isBlocking = $exceedsLimit -or ($preferIsolation -and $crossBatch)

        $finding = [pscustomobject]@{
            path = $path
            risk_level = [string]$riskFile.risk_level
            max_tasks_per_run = $maxTasks
            task_count = $taskCount
            task_ids = $taskIds
            batches = $batches
            prefer_batch_isolation = $preferIsolation
            note = [string]$riskFile.note
            exceeds_limit = $exceedsLimit
            cross_batch = $crossBatch
            blocking = $isBlocking
        }

        $findings += $finding

        if ($isBlocking) {
            $blockingFindings += $finding
            $warnings += ("risky hotspot: {0} -> {1} task(s), batches={2}" -f $path, $taskCount, ($batches -join ","))
        }

        $threshold = 2
        if ($RiskConfig.execution_guard -is [System.Collections.IDictionary]) {
            if ($RiskConfig.execution_guard.Contains("default_hotspot_threshold")) {
                $threshold = [int]$RiskConfig.execution_guard["default_hotspot_threshold"]
            }
        } elseif ($RiskConfig.execution_guard.default_hotspot_threshold) {
            $threshold = [int]$RiskConfig.execution_guard.default_hotspot_threshold
        }

        if (-not $isBlocking -and $taskCount -ge $threshold) {
            $warnings += ("hotspot watch: {0} -> {1} task(s)" -f $path, $taskCount)
        }
    }

    return [pscustomobject]@{
        findings = @($findings)
        blocking_findings = @($blockingFindings)
        warnings = @($warnings)
    }
}

function Get-V3TaskBatchName {
    param($Task)

    if ($Task.PSObject.Properties["batch"] -and -not [string]::IsNullOrWhiteSpace([string]$Task.batch)) {
        return [string]$Task.batch
    }
    return "default"
}

function Get-V3TaskId {
    param($Task)

    return [string]$Task.task_id
}

function Get-V3TaskDependencyIds {
    param($Task)

    if (-not $Task.PSObject.Properties["depends_on"] -or $null -eq $Task.depends_on) {
        return @()
    }

    return @(
        @($Task.depends_on) |
            ForEach-Object { [string]$_ } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
}

function Sort-V3TasksByDependencies {
    param([Parameter(Mandatory = $true)] [object[]]$Tasks)

    if ($Tasks.Count -le 1) {
        return @($Tasks)
    }

    $taskMap = @{}
    $taskOrder = @{}
    $incomingCounts = @{}
    $dependentMap = @{}

    for ($index = 0; $index -lt $Tasks.Count; $index++) {
        $task = $Tasks[$index]
        $taskId = Get-V3TaskId $task
        if ([string]::IsNullOrWhiteSpace($taskId)) {
            throw "task_id is required for dependency ordering"
        }
        if ($taskMap.ContainsKey($taskId)) {
            throw "duplicate task_id in queue: $taskId"
        }

        $taskMap[$taskId] = $task
        $taskOrder[$taskId] = $index
        $incomingCounts[$taskId] = 0
        $dependentMap[$taskId] = New-Object System.Collections.ArrayList
    }

    foreach ($task in $Tasks) {
        $taskId = Get-V3TaskId $task
        foreach ($dependencyId in @(Get-V3TaskDependencyIds $task)) {
            if (-not $taskMap.ContainsKey($dependencyId)) {
                throw ("depends_on reference not found: {0} -> {1}" -f $taskId, $dependencyId)
            }
            if ($dependencyId -eq $taskId) {
                throw ("task cannot depend on itself: {0}" -f $taskId)
            }

            $incomingCounts[$taskId] = [int]$incomingCounts[$taskId] + 1
            [void]$dependentMap[$dependencyId].Add($task)
        }
    }

    $ready = New-Object System.Collections.ArrayList
    foreach ($task in $Tasks) {
        $taskId = Get-V3TaskId $task
        if ([int]$incomingCounts[$taskId] -eq 0) {
            [void]$ready.Add($task)
        }
    }

    $ordered = New-Object System.Collections.ArrayList
    while ($ready.Count -gt 0) {
        $next = @($ready | Sort-Object { [int]$taskOrder[(Get-V3TaskId $_)] })[0]
        [void]$ready.Remove($next)
        [void]$ordered.Add($next)

        $nextId = Get-V3TaskId $next
        foreach ($dependentTask in @($dependentMap[$nextId])) {
            $dependentId = Get-V3TaskId $dependentTask
            $incomingCounts[$dependentId] = [int]$incomingCounts[$dependentId] - 1
            if ([int]$incomingCounts[$dependentId] -eq 0) {
                [void]$ready.Add($dependentTask)
            }
        }
    }

    if ($ordered.Count -ne $Tasks.Count) {
        $orderedIds = @($ordered | ForEach-Object { Get-V3TaskId $_ })
        $remaining = @(
            $Tasks |
                Where-Object { (Get-V3TaskId $_) -notin $orderedIds } |
                ForEach-Object { Get-V3TaskId $_ }
        )
        throw ("depends_on cycle detected: {0}" -f ($remaining -join ", "))
    }

    return @($ordered)
}

function Get-V3RiskRuleMap {
    param([Parameter(Mandatory = $true)] $RiskConfig)

    $map = @{}
    foreach ($riskFile in @($RiskConfig.risk_files)) {
        $path = Normalize-RelativePath ([string]$riskFile.path)
        if ([string]::IsNullOrWhiteSpace($path)) { continue }
        $map[$path] = $riskFile
    }
    return $map
}

function Test-V3TaskFitsPhase {
    param(
        [Parameter(Mandatory = $true)] $Task,
        [Parameter(Mandatory = $true)] [object[]]$PhaseTasks,
        [Parameter(Mandatory = $true)] $RiskRuleMap
    )

    $candidateTasks = @($PhaseTasks) + @($Task)
    foreach ($path in @($RiskRuleMap.Keys)) {
        $rule = $RiskRuleMap[$path]
        $refs = @()
        foreach ($candidate in $candidateTasks) {
            $targetFiles = @($candidate.target_files | ForEach-Object { Normalize-RelativePath ([string]$_) })
            if ($targetFiles -contains $path) {
                $refs += $candidate
            }
        }

        if ($refs.Count -eq 0) { continue }

        $maxTasks = 1
        if ($rule.PSObject.Properties["max_tasks_per_run"]) {
            $maxTasks = [int]$rule.max_tasks_per_run
        }
        if ($refs.Count -gt $maxTasks) {
            return $false
        }

        $preferIsolation = $false
        if ($rule.PSObject.Properties["prefer_batch_isolation"]) {
            $preferIsolation = [bool]$rule.prefer_batch_isolation
        }
        if ($preferIsolation) {
            $batches = @($refs | ForEach-Object { Get-V3TaskBatchName $_ } | Sort-Object -Unique)
            if ($batches.Count -gt 1) {
                return $false
            }
        }
    }

    return $true
}

function New-V3AutoRebatchPlan {
    param(
        [Parameter(Mandatory = $true)] $Queue,
        [Parameter(Mandatory = $true)] $RiskConfig
    )

    $riskRuleMap = Get-V3RiskRuleMap -RiskConfig $RiskConfig
    $rawPhases = @()
    $taskPhaseMap = @{}

    foreach ($task in @($Queue.tasks)) {
        $taskId = Get-V3TaskId $task
        $minimumPhase = 1
        foreach ($dependencyId in @(Get-V3TaskDependencyIds $task)) {
            if (-not $taskPhaseMap.ContainsKey($dependencyId)) {
                throw ("task dependency phase missing: {0} -> {1}" -f $taskId, $dependencyId)
            }
            $minimumPhase = [Math]::Max($minimumPhase, [int]$taskPhaseMap[$dependencyId])
        }

        $placed = $false
        for ($index = ($minimumPhase - 1); $index -lt $rawPhases.Count; $index++) {
            if (Test-V3TaskFitsPhase -Task $task -PhaseTasks @($rawPhases[$index].tasks) -RiskRuleMap $riskRuleMap) {
                $rawPhases[$index].tasks += @($task)
                $taskPhaseMap[$taskId] = [int]$rawPhases[$index].index
                $placed = $true
                break
            }
        }

        if (-not $placed) {
            $rawPhases += [pscustomobject]@{
                index = $rawPhases.Count + 1
                tasks = @($task)
            }
            $taskPhaseMap[$taskId] = [int]$rawPhases[-1].index
        }
    }

    $phases = @()
    foreach ($phase in @($rawPhases)) {
        $riskPaths = @()
        foreach ($task in @($phase.tasks)) {
            foreach ($file in @($task.target_files)) {
                $normalized = Normalize-RelativePath ([string]$file)
                if ($riskRuleMap.ContainsKey($normalized)) {
                    $riskPaths += $normalized
                }
            }
        }

        $phases += [pscustomobject]@{
            index = [int]$phase.index
            task_count = @($phase.tasks).Count
            task_ids = @($phase.tasks | ForEach-Object { [string]$_.task_id })
            batches = @($phase.tasks | ForEach-Object { Get-V3TaskBatchName $_ } | Sort-Object -Unique)
            risk_paths = @($riskPaths | Sort-Object -Unique)
            tasks = @($phase.tasks)
        }
    }

    return [pscustomobject]@{
        phase_count = @($phases).Count
        phases = @($phases)
    }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$requestPath = if ([System.IO.Path]::IsPathRooted($RequestFile)) { $RequestFile } else { Join-Path $projectRoot $RequestFile }
if (-not (Test-Path $requestPath)) {
    throw "request file not found: $RequestFile"
}

$compileScript = Join-Path $projectRoot "scripts\compile_request_to_tasks.js"
$validatorScript = Join-Path $projectRoot "scripts\validate_task_queue.js"
$schemaPath = Join-Path $projectRoot "brain\TASK_QUEUE\task.schema.json"
$runnerPath = Join-Path $projectRoot "scripts\night_agent_v2.ps1"
$stateMapPath = Join-Path $projectRoot "brain\CORE_STATE_MAP.yaml"

foreach ($path in @($compileScript, $validatorScript, $schemaPath, $runnerPath, $stateMapPath)) {
    if (-not (Test-Path $path)) {
        throw "required file not found: $path"
    }
}

$runRoot = New-UniqueRunRoot -ParentPath (Join-Path $projectRoot "output\night_agent_v3")

$queuePath = if ([string]::IsNullOrWhiteSpace($GeneratedTaskFile)) {
    Join-Path $runRoot "compiled.queue.json"
} elseif ([System.IO.Path]::IsPathRooted($GeneratedTaskFile)) {
    $GeneratedTaskFile
} else {
    Join-Path $projectRoot $GeneratedTaskFile
}

$reportPath = Join-Path $runRoot "compile_report.json"
$riskReportPath = Join-Path $runRoot "risk_report.json"
$rebatchPlanPath = Join-Path $runRoot "rebatch_plan.json"
$rebatchRoot = Join-Path $runRoot "rebatched"
$summaryPath = Join-Path $runRoot "summary.txt"
$requestCopyPath = Join-Path $runRoot "request.json"
Copy-Item -LiteralPath $requestPath -Destination $requestCopyPath -Force

Write-Host ("== night agent v3 compile ==")
Write-Host ("- request: {0}" -f $requestPath)
Write-Host ("- queue:   {0}" -f $queuePath)

$compileOutput = & node $compileScript $requestPath $queuePath --report $reportPath 2>&1
if ($LASTEXITCODE -ne 0) {
    $compileOutput | Out-String | Set-Content -Path $summaryPath -Encoding utf8
    throw ("compile_request_to_tasks.js failed`n{0}" -f ($compileOutput | Out-String).Trim())
}

$validationOutput = & node $validatorScript $queuePath $schemaPath 2>&1
if ($LASTEXITCODE -ne 0) {
    $validationOutput | Out-String | Set-Content -Path $summaryPath -Encoding utf8
    throw ("validate_task_queue.js failed`n{0}" -f ($validationOutput | Out-String).Trim())
}

$report = $null
if (Test-Path $reportPath) {
    $report = Get-Content -Raw -Path $reportPath | ConvertFrom-Json
}

$queue = Get-Content -Raw -Path $queuePath | ConvertFrom-Json
$queue.tasks = @(Sort-V3TasksByDependencies -Tasks @($queue.tasks))
($queue | ConvertTo-Json -Depth 12) | Set-Content -Path $queuePath -Encoding utf8

$riskConfig = Read-V3RiskConfig -StateMapPath $stateMapPath
$riskSummary = Get-V3RiskFindings -Queue $queue -RiskConfig $riskConfig
$rebatchPlan = $null

if (@($riskSummary.blocking_findings).Count -gt 0) {
    $rebatchPlan = New-V3AutoRebatchPlan -Queue $queue -RiskConfig $riskConfig
    New-Item -ItemType Directory -Path $rebatchRoot -Force | Out-Null

    foreach ($phase in @($rebatchPlan.phases)) {
        $phasePath = Join-Path $rebatchRoot ("batch-{0:d2}.json" -f [int]$phase.index)
        $phaseQueue = [ordered]@{
            defaults = $queue.defaults
            tasks = @($phase.tasks)
        }
        ($phaseQueue | ConvertTo-Json -Depth 12) | Set-Content -Path $phasePath -Encoding utf8

        $phaseValidation = & node $validatorScript $phasePath $schemaPath 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw ("rebatched queue validation failed for {0}`n{1}" -f $phasePath, ($phaseValidation | Out-String).Trim())
        }

        $phase | Add-Member -NotePropertyName "queue_path" -NotePropertyValue $phasePath -Force
    }

    ($rebatchPlan | ConvertTo-Json -Depth 12) | Set-Content -Path $rebatchPlanPath -Encoding utf8
}

$shouldBlock = $false
if ($riskConfig.execution_guard -is [System.Collections.IDictionary]) {
    if ($riskConfig.execution_guard.Contains("block_on_risky_hotspot")) {
        $shouldBlock = [bool]$riskConfig.execution_guard["block_on_risky_hotspot"]
    }
} else {
    $shouldBlock = [bool]$riskConfig.execution_guard.block_on_risky_hotspot
}

$executionMode = "single-queue"
$executionQueuePaths = @($queuePath)
if ($shouldBlock -and @($riskSummary.blocking_findings).Count -gt 0 -and -not $AllowRiskyHotspots) {
    if ($rebatchPlan -and @($rebatchPlan.phases).Count -gt 0) {
        $executionMode = "rebatch-phase-run"
        $executionQueuePaths = @($rebatchPlan.phases | Sort-Object index | ForEach-Object { [string]$_.queue_path })
    } else {
        $blockingText = @($riskSummary.blocking_findings | ForEach-Object {
            "{0} ({1} task(s))" -f $_.path, $_.task_count
        }) -join ", "
        throw ("risky hotspot guard blocked execution: {0}`nUse -AllowRiskyHotspots to override after reviewing {1}" -f $blockingText, $riskReportPath)
    }
} elseif (@($riskSummary.blocking_findings).Count -gt 0 -and $AllowRiskyHotspots) {
    $executionMode = "single-queue-override"
}

if ($report) {
    $report | Add-Member -NotePropertyName "state_map" -NotePropertyValue ([pscustomobject]@{
        path = $stateMapPath
        mode = "v3-risk-guard"
    }) -Force
    $report | Add-Member -NotePropertyName "risk_summary" -NotePropertyValue $riskSummary -Force
    $report | Add-Member -NotePropertyName "task_execution_order" -NotePropertyValue @($queue.tasks | ForEach-Object { Get-V3TaskId $_ }) -Force
    $report | Add-Member -NotePropertyName "execution_plan" -NotePropertyValue ([pscustomobject]@{
        mode = $executionMode
        queue_paths = @($executionQueuePaths)
    }) -Force
    if ($rebatchPlan) {
        $report | Add-Member -NotePropertyName "rebatch_plan" -NotePropertyValue ([pscustomobject]@{
            path = $rebatchPlanPath
            phase_count = [int]$rebatchPlan.phase_count
            queue_paths = @($rebatchPlan.phases | ForEach-Object { $_.queue_path })
        }) -Force
    }
    ($report | ConvertTo-Json -Depth 10) | Set-Content -Path $reportPath -Encoding utf8
}

($riskSummary | ConvertTo-Json -Depth 10) | Set-Content -Path $riskReportPath -Encoding utf8

$summaryLines = @()
$summaryLines += "night agent v3 compile complete"
$summaryLines += ("request: {0}" -f $requestPath)
$summaryLines += ("queue: {0}" -f $queuePath)
$summaryLines += ("report: {0}" -f $reportPath)
$summaryLines += ("risk report: {0}" -f $riskReportPath)
$summaryLines += ("execution mode: {0}" -f $executionMode)
if ($rebatchPlan) {
    $summaryLines += ("rebatch plan: {0}" -f $rebatchPlanPath)
}
if ($report) {
    $summaryLines += ("tasks: {0}" -f $report.task_count)
    $summaryLines += ("features: {0}" -f $report.feature_count)
    if ($report.hotspot_files -and $report.hotspot_files.Count -gt 0) {
        $summaryLines += "hotspot files:"
        foreach ($hotspot in $report.hotspot_files) {
            $summaryLines += ("- {0} ({1})" -f $hotspot.file, $hotspot.count)
        }
    } else {
        $summaryLines += "hotspot files: none"
    }
    if ($report.warnings -and $report.warnings.Count -gt 0) {
        $summaryLines += "warnings:"
        foreach ($warning in $report.warnings) {
            $summaryLines += ("- {0}" -f $warning)
        }
    }
}
$summaryLines += ("risk findings: {0}" -f @($riskSummary.findings).Count)
if ($riskSummary.warnings -and $riskSummary.warnings.Count -gt 0) {
    $summaryLines += "risk warnings:"
    foreach ($warning in $riskSummary.warnings) {
        $summaryLines += ("- {0}" -f $warning)
    }
}
if ($rebatchPlan) {
    $summaryLines += ("rebatch phases: {0}" -f [int]$rebatchPlan.phase_count)
    foreach ($phase in @($rebatchPlan.phases)) {
        $summaryLines += ("- batch-{0:d2}: {1}" -f [int]$phase.index, ($phase.task_ids -join ", "))
    }
}
$summaryLines | Set-Content -Path $summaryPath -Encoding utf8

Write-Host ("- report:  {0}" -f $reportPath)
Write-Host ("- risk:    {0}" -f $riskReportPath)
Write-Host ("- execute: {0}" -f $executionMode)
if ($rebatchPlan) {
    Write-Host ("- rebatch: {0}" -f $rebatchPlanPath)
}
Write-Host ("- summary: {0}" -f $summaryPath)

if ($CompileOnly) {
    Write-Host "compile-only mode enabled; skipping v2 execution"
    return
}

Write-Host ""
if ($executionMode -eq "rebatch-phase-run") {
    Write-Host "== night agent v3 execute (rebatched phases) =="
    $phaseCount = @($executionQueuePaths).Count
    for ($index = 0; $index -lt $phaseCount; $index++) {
        $phasePath = [string]$executionQueuePaths[$index]
        Write-Host ("- phase {0}/{1}: {2}" -f ($index + 1), $phaseCount, $phasePath)
        & $runnerPath -TaskFile $phasePath
        if ($LASTEXITCODE -ne 0) {
            throw ("night_agent_v2.ps1 failed for phase queue: {0}" -f $phasePath)
        }
    }
    return
}

Write-Host "== night agent v3 execute =="
& $runnerPath -TaskFile $queuePath
if ($LASTEXITCODE -ne 0) {
    throw ("night_agent_v2.ps1 failed for queue: {0}" -f $queuePath)
}
