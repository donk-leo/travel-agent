#requires -Version 5.1
<#
.SYNOPSIS
    T5.3 干净 clone 一条命令：git clone -> 新 venv -> requirements.lock -> 9 项 checks -> 离线 unittest。

.DESCRIPTION
    在仓库**外**的临时目录里用真正的 `git clone` 拉取指定分支的已提交状态，创建全新的 venv，
    安装 requirements.lock，按 .github/workflows/ci.yml 的顺序执行 9 项 checks，
    再执行 P7 离线 unittest（>=327）与 eval schema unittest（>=17）。

    约束：
      * 不依赖本机 .venv 的包，不复制 .venv / 缓存 / 模型 / 运行中服务；
      * 不调用模型、不跑网页、不跑真实评测；网络只用于 pip 安装 requirements.lock；
      * 任何一步退出码非 0 立即失败并写 JSON，不用 mock 结果；
      * 克隆目录默认保留在临时目录，脚本不会删除它（便于复查），也绝不写进仓库。

.PARAMETER Repo
    源仓库根目录。默认由脚本位置推导（runtime/ 的上一级），即从仓库根直接执行时无需传参。

.PARAMETER Branch
    要克隆的分支，默认 agent/d4-hardening。

.PARAMETER WorkDir
    仓库外的临时目录（克隆目标）。默认 %TEMP%\clean_clone_<yyyyMMdd_HHmmss>。
    必须不存在或为空目录；脚本拒绝在仓库内部或仓库上级目录中创建。

.PARAMETER OutJson
    结果 JSON 路径。默认 <WorkDir>\clean_clone_result.json。

.PARAMETER Python
    用于创建隔离 venv 的解释器（路径或命令）。默认优先 `py -3.11`，其次 PATH 上的 python；
    要求 3.11.x（requirements.lock 为 cp311 口径）。它只用来创建新 venv，不会使用其已装包。

.PARAMETER MinTests
    P7 离线 unittest 最少条数，默认 327。

.PARAMETER MinEvalTests
    eval schema unittest 最少条数，默认 17。

.PARAMETER MaxSeconds
    全流程时间上限（秒），默认 900（15 分钟）。实测总耗时超过该值即判 fail。

.PARAMETER NoPipCache
    仅用于对照测量：给 pip install 追加 --no-cache-dir。默认不加，保持与 CI 命令一致。

.PARAMETER DryRun
    只做参数校验并打印将要执行的命令，不 clone、不建 venv、不安装、不写 JSON。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File runtime\clean_clone_check.ps1 -OutJson "$env:TEMP\clean_clone_result.json"

.EXAMPLE
    powershell -NoProfile -File runtime\clean_clone_check.ps1 -WorkDir "$env:TEMP\clean_clone_manual" -OutJson "$env:TEMP\result.json"

.NOTES
    Windows PowerShell 5.1+。`pwsh`（PowerShell 7）不是本机必备；两者语法均兼容。
#>
[CmdletBinding()]
param(
    [string]$Repo = "",
    [string]$Branch = "agent/d4-hardening",
    [string]$WorkDir = "",
    [string]$OutJson = "",
    [string]$Python = "",
    [int]$MinTests = 327,
    [int]$MinEvalTests = 17,
    [int]$MaxSeconds = 900,
    [switch]$NoPipCache,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

$script:startedAt = Get-Date
$script:pipelineSw = $null
$script:preflightSw = [System.Diagnostics.Stopwatch]::StartNew()
$script:log = New-Object 'System.Collections.Generic.List[string]'
$script:checkEntries = New-Object 'System.Collections.Generic.List[object]'
$script:outFull = ""
$script:logPath = ""

# ---------------------------------------------------------------- 结果骨架
$script:result = [ordered]@{
    schema         = "clean_clone_check/v1"
    verdict        = "fail"
    failure_reason = $null
    started_at     = $script:startedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
    finished_at    = $null
    host           = [ordered]@{ os = ""; ps_version = ""; git_version = ""; cpu = ""; ram_gb = 0 }
    source         = [ordered]@{
        repo = ""; branch = ""; current_branch = ""; head = ""; tree = "";
        head_is_branch_tip = $false; status_porcelain = ""; clean = $false
    }
    clone          = [ordered]@{
        dir = ""; command = ""; exit_code = -1; head = ""; tree = ""; branch = "";
        status_porcelain = ""; clean = $false; tree_matches_source = $false;
        remote = ""; files = 0; has_venv_before_creation = $false; has_downloads = $false
    }
    python         = [ordered]@{
        creator = ""; creator_version = ""; venv_python = ""; venv_python_version = "";
        pip_version_before = ""; pip_version_after = ""; venv_prefix = ""; venv_base_prefix = "";
        isolation_ok = $false; packages_before = @()
    }
    install        = [ordered]@{
        command = ""; exit_code = -1; seconds = 0; cache_hits = 0; downloads = 0;
        no_pip_cache = [bool]$NoPipCache; successfully_installed = "";
        lock_pins_verified = 0; lock_pins_total = 0; lock_missing = @(); lock_mismatch = @()
    }
    pip_check      = [ordered]@{ command = ""; exit_code = -1; seconds = 0; output = "" }
    checks         = @()
    checks_passed  = 0
    checks_total   = 9
    tests          = [ordered]@{
        command = ""; exit_code = -1; seconds = 0; ran = -1; min_required = $MinTests;
        ok = $false; output_tail = ""
    }
    eval_schema    = [ordered]@{
        command = ""; exit_code = -1; seconds = 0; ran = -1; min_required = $MinEvalTests;
        ok = $false; output_tail = ""
    }
    timing         = [ordered]@{
        preflight_seconds = 0; clone_seconds = 0; venv_seconds = 0; install_seconds = 0;
        pip_check_seconds = 0; checks_seconds = 0; tests_seconds = 0; eval_schema_seconds = 0;
        total_seconds = 0; script_total_seconds = 0; max_seconds = $MaxSeconds
    }
    post_status_porcelain = ""
    post_status_clean     = $false
    notes                 = @()
}

# ---------------------------------------------------------------- 小工具
function Add-Log {
    param([string]$Text)
    [void]$script:log.Add($Text)
}

function Write-Utf8File {
    param([string]$Path, [string]$Content)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Save-Artifacts {
    if ($script:outFull) {
        try {
            $json = $script:result | ConvertTo-Json -Depth 12
            # 非 ASCII 统一转 \uXXXX：JSON 保持合法且纯 ASCII，避免 Windows PowerShell 5.1
            # 的 Get-Content 默认按 ANSI 读 UTF-8 时把中文读坏（Python/JS 解析不受影响）。
            $ascii = New-Object System.Text.StringBuilder
            foreach ($ch in $json.ToCharArray()) {
                $code = [int]$ch
                if ($code -gt 126) { [void]$ascii.Append(('\u{0:x4}' -f $code)) }
                else { [void]$ascii.Append($ch) }
            }
            Write-Utf8File -Path $script:outFull -Content ($ascii.ToString() + "`r`n")
        } catch {
            Write-Host ("[warn] 写 JSON 失败: " + $_.Exception.Message) -ForegroundColor Yellow
        }
    }
    if ($script:logPath -and $script:log.Count -gt 0) {
        try {
            [System.IO.File]::WriteAllLines($script:logPath, $script:log.ToArray(), [System.Text.UTF8Encoding]::new($true))
        } catch { }
    }
}

function Get-Tail {
    param([string]$Text, [int]$MaxLines = 12, [int]$MaxChars = 900)
    $lines = @($Text -split "`r?`n" | Where-Object { $_.Trim() -ne "" })
    $tail = (@($lines | Select-Object -Last $MaxLines) -join " | ")
    if ($tail.Length -gt $MaxChars) { $tail = $tail.Substring($tail.Length - $MaxChars) }
    return $tail
}

function Resolve-ExePath {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { return $null }
    if ($cmd.CommandType -eq "Application") { return $cmd.Path }
    if ($cmd.Source) { return $cmd.Source }
    return $null
}

# 运行原生命令；stdout/stderr 合并捕获，返回退出码 / 输出 / 耗时 / 可读命令。
function Invoke-Native {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [string]$Cwd
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $captured = @()
    $exit = -1
    try {
        Push-Location -LiteralPath $Cwd
        try {
            $captured = & $Exe @Arguments 2>&1
            if ($null -ne $LASTEXITCODE) { $exit = [int]$LASTEXITCODE }
        } finally {
            Pop-Location
        }
    } catch {
        $captured = @($_.Exception.Message)
        $exit = -1
    }
    $sw.Stop()
    $lineArray = @($captured | ForEach-Object {
        if ($null -eq $_) { "" }
        elseif ($_ -is [System.Management.Automation.ErrorRecord]) { [string]$_.Exception.Message }
        else { [string]$_ }
    })
    $text = $lineArray -join "`n"
    $display = $Exe
    foreach ($a in $Arguments) {
        if ($a -match '[\s"]') { $display += ' "' + ($a -replace '"', '\"') + '"' } else { $display += ' ' + $a }
    }
    [pscustomobject]@{
        ExitCode = $exit
        Output   = $text
        Seconds  = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        Command  = $display
    }
}

function Write-Summary {
    $r = $script:result
    Write-Host ""
    Write-Host "=== 干净 clone 门禁摘要 ===" -ForegroundColor Cyan
    Write-Host ("分支/提交      : {0} @ {1}" -f $r.source.branch, $r.source.head)
    Write-Host ("克隆目录       : {0}" -f $r.clone.dir)
    Write-Host ("克隆 HEAD      : {0}（tree 与源一致: {1}）" -f $r.clone.head, $r.clone.tree_matches_source)
    Write-Host ("克隆后 git 状态: {0}" -f $(if ($r.clone.clean) { "clean（空）" } else { "DIRTY / 未验证" }))
    Write-Host ("Python (venv)  : {0} / {1}" -f $r.python.venv_python_version, $r.python.pip_version_after)
    Write-Host ("安装 lock      : exit {0}, {1}s（cache hits {2}, downloads {3}）" -f $r.install.exit_code, $r.install.seconds, $r.install.cache_hits, $r.install.downloads)
    Write-Host ("pip check      : exit {0}" -f $r.pip_check.exit_code)
    Write-Host ("checks         : {0}/{1} exit 0（{2}s）" -f $r.checks_passed, $r.checks_total, $r.timing.checks_seconds)
    Write-Host ("p07 unittest   : {0} tests（min {1}）, exit {2}（{3}s）" -f $r.tests.ran, $r.tests.min_required, $r.tests.exit_code, $r.tests.seconds)
    Write-Host ("eval schema    : {0} tests（min {1}）, exit {2}（{3}s）" -f $r.eval_schema.ran, $r.eval_schema.min_required, $r.eval_schema.exit_code, $r.eval_schema.seconds)
    Write-Host ("阶段耗时(s)    : clone={0} venv={1} install={2} pipcheck={3} checks={4} tests={5} eval={6}" -f `
        $r.timing.clone_seconds, $r.timing.venv_seconds, $r.timing.install_seconds, `
        $r.timing.pip_check_seconds, $r.timing.checks_seconds, $r.timing.tests_seconds, $r.timing.eval_schema_seconds)
    Write-Host ("总耗时         : {0}s / 上限 {1}s" -f $r.timing.total_seconds, $r.timing.max_seconds)
    if ($r.verdict -eq "pass") {
        Write-Host "判定           : PASS" -ForegroundColor Green
    } else {
        Write-Host ("判定           : FAIL — {0}" -f $r.failure_reason) -ForegroundColor Red
    }
    if ($script:outFull) { Write-Host ("JSON           : {0}" -f $script:outFull) }
    if ($script:logPath) { Write-Host ("日志           : {0}" -f $script:logPath) }
    Write-Host ""
}

function Complete-Fail {
    param([string]$Reason)
    if ($null -ne $script:pipelineSw) {
        if ($script:pipelineSw.IsRunning) { $script:pipelineSw.Stop() }
        $script:result.timing.total_seconds = [math]::Round($script:pipelineSw.Elapsed.TotalSeconds, 2)
    }
    $script:result.timing.script_total_seconds = [math]::Round(((Get-Date) - $script:startedAt).TotalSeconds, 2)
    $script:result.verdict = "fail"
    $script:result.failure_reason = $Reason
    $script:result.finished_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    Add-Log ""
    Add-Log ("[FAIL] " + $Reason)
    Save-Artifacts
    Write-Summary
    exit 1
}

function Complete-Pass {
    if ($script:pipelineSw.IsRunning) { $script:pipelineSw.Stop() }
    $script:result.timing.total_seconds = [math]::Round($script:pipelineSw.Elapsed.TotalSeconds, 2)
    $script:result.timing.script_total_seconds = [math]::Round(((Get-Date) - $script:startedAt).TotalSeconds, 2)
    $script:result.verdict = "pass"
    $script:result.failure_reason = $null
    $script:result.finished_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    Save-Artifacts
    Write-Summary
    exit 0
}

# 逐条 check 定义：顺序与 .github/workflows/ci.yml 完全一致（P1 x3 -> P2 -> ... -> P7）。
$script:checkDefs = @(
    [ordered]@{ name = "P1 changlong"; args = @("checks/check_scenic.py", "scenic/changlong/data/processed/changlong_guides.csv") },
    [ordered]@{ name = "P1 baiyunshan"; args = @("checks/check_scenic.py", "scenic/baiyunshan/data/processed/baiyunshan_guides.csv") },
    [ordered]@{ name = "P1 wugongshan"; args = @("checks/check_scenic.py", "scenic/wugongshan/data/processed/wugongshan_guides.csv") },
    [ordered]@{ name = "P2 entities"; args = @("checks/check_entities.py") },
    [ordered]@{ name = "P3 routes"; args = @("checks/check_routes.py") },
    [ordered]@{ name = "P4 coref"; args = @("checks/check_coref.py") },
    [ordered]@{ name = "P5 conditions"; args = @("checks/check_conditions.py") },
    [ordered]@{ name = "P6 graph"; args = @("checks/check_graph.py", "analysis/p06_graph/outputs") },
    [ordered]@{ name = "P7 agent"; args = @("checks/check_agent.py", "analysis/p07_agent") }
)

# ---------------------------------------------------------------- 1) 主机事实
try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    if ($os) { $script:result.host.os = ("{0} build {1} {2}" -f $os.Caption, $os.BuildNumber, $os.OSArchitecture) }
    $cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cpu) { $script:result.host.cpu = $cpu.Name.Trim() }
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    if ($cs) { $script:result.host.ram_gb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1) }
} catch { }
$script:result.host.ps_version = $PSVersionTable.PSVersion.ToString()
$gitProbe = Invoke-Native "git" @("--version") (Get-Location).Path
if ($gitProbe.ExitCode -ne 0) { Complete-Fail "git 不可用（git --version 失败）" }
$script:result.host.git_version = $gitProbe.Output.Trim()

# ---------------------------------------------------------------- 2) 参数校验
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($Repo)) { $Repo = Split-Path -Parent $scriptDir }
if (-not (Test-Path -LiteralPath $Repo -PathType Container)) { Complete-Fail ("Repo 不存在: " + $Repo) }
$Repo = (Resolve-Path -LiteralPath $Repo).Path.TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $Repo ".git"))) { Complete-Fail ("Repo 不是 git 仓库（缺少 .git）: " + $Repo) }
$script:result.source.repo = $Repo
$script:result.source.branch = $Branch

$branchProbe = Invoke-Native "git" @("-C", $Repo, "rev-parse", "--verify", "--quiet", ("refs/heads/" + $Branch)) $Repo
if ($branchProbe.ExitCode -ne 0) { Complete-Fail ("分支不存在: " + $Branch) }
$sourceHead = (Invoke-Native "git" @("-C", $Repo, "rev-parse", "HEAD") $Repo).Output.Trim()
$sourceTip = (Invoke-Native "git" @("-C", $Repo, "rev-parse", ("refs/heads/" + $Branch)) $Repo).Output.Trim()
$sourceTree = (Invoke-Native "git" @("-C", $Repo, "rev-parse", ($Branch + "^{tree}")) $Repo).Output.Trim()
$sourceCurrent = (Invoke-Native "git" @("-C", $Repo, "branch", "--show-current") $Repo).Output.Trim()
$sourceStatus = (Invoke-Native "git" @("-C", $Repo, "status", "--porcelain", "-uall") $Repo).Output.Trim()
$script:result.source.head = $sourceTip
$script:result.source.tree = $sourceTree
$script:result.source.current_branch = $sourceCurrent
$script:result.source.head_is_branch_tip = ($sourceHead -eq $sourceTip)
$script:result.source.status_porcelain = $sourceStatus
$script:result.source.clean = ($sourceStatus -eq "")
Add-Log ("源仓库: " + $Repo)
Add-Log ("源分支: " + $Branch + " / HEAD " + $sourceHead + " / tip " + $sourceTip)
Add-Log ("源工作区 git status --porcelain -uall: " + $(if ($sourceStatus -eq "") { "<空>" } else { $sourceStatus }))

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
    $tempBase = [System.IO.Path]::GetTempPath()
    try { $tempBase = (Get-Item -LiteralPath $tempBase).FullName } catch { }
    $WorkDir = Join-Path $tempBase ("clean_clone_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
}
if (-not [System.IO.Path]::IsPathRooted($WorkDir)) { $WorkDir = Join-Path (Get-Location).Path $WorkDir }
$workFull = [System.IO.Path]::GetFullPath($WorkDir).TrimEnd('\')

$sep = [System.IO.Path]::DirectorySeparatorChar
if (($workFull -eq $Repo) -or $workFull.StartsWith($Repo + $sep, [System.StringComparison]::OrdinalIgnoreCase)) {
    Complete-Fail ("WorkDir 不能位于仓库内（本任务要求仓库外）: " + $workFull)
}
if ($Repo.StartsWith($workFull + $sep, [System.StringComparison]::OrdinalIgnoreCase)) {
    Complete-Fail ("WorkDir 不能是仓库的上级目录: " + $workFull)
}
$workExisted = Test-Path -LiteralPath $workFull
if ($workExisted) {
    if (-not (Test-Path -LiteralPath $workFull -PathType Container)) { Complete-Fail ("WorkDir 已存在且不是目录: " + $workFull) }
    $existing = @(Get-ChildItem -LiteralPath $workFull -Force)
    if ($existing.Count -gt 0) { Complete-Fail ("WorkDir 已存在且非空，请换一个目录或先清空: " + $workFull) }
}

if ([string]::IsNullOrWhiteSpace($OutJson)) {
    $OutJson = Join-Path $workFull "clean_clone_result.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutJson)) {
    $OutJson = Join-Path (Get-Location).Path $OutJson
}
$script:outFull = [System.IO.Path]::GetFullPath($OutJson)
$script:logPath = Join-Path $workFull "clean_clone_check.log"
Add-Log ("克隆目录: " + $workFull)
Add-Log ("结果 JSON: " + $script:outFull)

# ---------------------------------------------------------------- 3) Python 解释器
$creatorExe = $null
$creatorArgs = @()
if (-not [string]::IsNullOrWhiteSpace($Python)) {
    if (Test-Path -LiteralPath $Python) { $creatorExe = (Resolve-Path -LiteralPath $Python).Path }
    else { $creatorExe = $Python }
} else {
    $pyExe = Resolve-ExePath "py"
    if ($pyExe) {
        $probe = Invoke-Native $pyExe @("-3.11", "-c", "import sys; print(sys.version.split()[0])") (Get-Location).Path
        if ($probe.ExitCode -eq 0 -and $probe.Output.Trim().StartsWith("3.11")) {
            $creatorExe = $pyExe
            $creatorArgs = @("-3.11")
        }
    }
    if ($null -eq $creatorExe) {
        $py3 = Resolve-ExePath "python"
        if ($py3) {
            $probe = Invoke-Native $py3 @("-c", "import sys; print(sys.version.split()[0])") (Get-Location).Path
            if ($probe.ExitCode -eq 0 -and $probe.Output.Trim().StartsWith("3.11")) { $creatorExe = $py3 }
        }
    }
}
if ($null -eq $creatorExe) { Complete-Fail "找不到 Python 3.11 解释器（可用 -Python 显式指定）" }
$creatorProbe = Invoke-Native $creatorExe ($creatorArgs + @("-c", "import sys; print(sys.version); print(sys.executable)")) (Get-Location).Path
if ($creatorProbe.ExitCode -ne 0) { Complete-Fail ("创建 venv 的解释器不可用: " + $creatorExe) }
$creatorLines = @($creatorProbe.Output -split "`r?`n" | Where-Object { $_.Trim() -ne "" })
$creatorVersion = $creatorLines[0].Trim()
if (-not $creatorVersion.StartsWith("3.11.")) { Complete-Fail ("需要 Python 3.11.x，实际: " + $creatorVersion) }
$script:result.python.creator = $creatorExe
$script:result.python.creator_version = $creatorVersion
Add-Log ("创建 venv 的解释器: " + $creatorExe + " / " + $creatorVersion)

# ---------------------------------------------------------------- 4) DryRun
if ($DryRun) {
    $venvPyShown = Join-Path $workFull ".venv\Scripts\python.exe"
    $planned = New-Object 'System.Collections.Generic.List[string]'
    [void]$planned.Add('git clone --branch ' + $Branch + ' --single-branch --no-hardlinks "' + $Repo + '" "' + $workFull + '"')
    [void]$planned.Add('"' + $creatorExe + '" ' + (($creatorArgs + @('-m', 'venv', (Join-Path $workFull '.venv'))) -join ' '))
    [void]$planned.Add('"' + $venvPyShown + '" -m pip install --disable-pip-version-check -r requirements.lock' + $(if ($NoPipCache) { ' --no-cache-dir' } else { '' }))
    [void]$planned.Add('"' + $venvPyShown + '" -m pip check')
    foreach ($def in $script:checkDefs) {
        [void]$planned.Add('"' + $venvPyShown + '" ' + ($def.args -join ' '))
    }
    [void]$planned.Add('"' + $venvPyShown + '" -m unittest discover -s analysis/p07_agent/tests -q')
    [void]$planned.Add('"' + $venvPyShown + '" -m unittest analysis.p07_agent.eval.tests.test_eval_schema -q')
    Write-Host "=== DRY RUN：仅校验参数，不执行 ===" -ForegroundColor Cyan
    Write-Host ("源仓库   : {0}" -f $Repo)
    Write-Host ("分支     : {0} @ {1}（branch tip: {2}）" -f $Branch, $sourceTip, $script:result.source.head_is_branch_tip)
    Write-Host ("工作区   : {0}" -f $(if ($sourceStatus -eq "") { "clean" } else { "dirty（clone 仍只取已提交状态）" }))
    Write-Host ("临时目录 : {0}" -f $workFull)
    Write-Host ("结果 JSON: {0}" -f $script:outFull)
    Write-Host ("解释器   : {0} / {1}" -f $creatorExe, $creatorVersion)
    Write-Host ""
    Write-Host "将执行以下命令（工作目录 = 克隆目录）:"
    foreach ($line in $planned) { Write-Host ("  " + $line) }
    Write-Host ""
    Write-Host "DryRun 校验通过。" -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------- 5) 计时 + clone
if (-not (Test-Path -LiteralPath $workFull)) { New-Item -ItemType Directory -Path $workFull -Force | Out-Null }
$script:result.timing.preflight_seconds = [math]::Round($script:preflightSw.Elapsed.TotalSeconds, 2)
$script:pipelineSw = [System.Diagnostics.Stopwatch]::StartNew()

Add-Log ""
$cloneArgs = @("clone", "--branch", $Branch, "--single-branch", "--no-hardlinks", $Repo, $workFull)
$clone = Invoke-Native "git" $cloneArgs (Get-Location).Path
$script:result.clone.command = $clone.Command
$script:result.clone.exit_code = $clone.ExitCode
$script:result.clone.dir = $workFull
$script:result.timing.clone_seconds = $clone.Seconds
Add-Log ("`n$ " + $clone.Command)
Add-Log $clone.Output
Write-Host ("[clone] exit={0} {1}s -> {2}" -f $clone.ExitCode, $clone.Seconds, $workFull)
if ($clone.ExitCode -ne 0) { Complete-Fail ("git clone 失败（exit " + $clone.ExitCode + "）: " + (Get-Tail $clone.Output 8 600)) }

$cloneHead = (Invoke-Native "git" @("-C", $workFull, "rev-parse", "HEAD") $workFull).Output.Trim()
$cloneTree = (Invoke-Native "git" @("-C", $workFull, "rev-parse", "HEAD^{tree}") $workFull).Output.Trim()
$cloneBranch = (Invoke-Native "git" @("-C", $workFull, "rev-parse", "--abbrev-ref", "HEAD") $workFull).Output.Trim()
$cloneStatus = (Invoke-Native "git" @("-C", $workFull, "status", "--porcelain", "-uall") $workFull).Output.Trim()
$cloneRemote = (Invoke-Native "git" @("-C", $workFull, "remote", "get-url", "origin") $workFull).Output.Trim()
$cloneFiles = @((Invoke-Native "git" @("-C", $workFull, "ls-files") $workFull).Output -split "`r?`n" | Where-Object { $_.Trim() -ne "" }).Count
$hasVenv = Test-Path -LiteralPath (Join-Path $workFull ".venv")
$hasDownloads = Test-Path -LiteralPath (Join-Path $workFull ".downloads")

$script:result.clone.head = $cloneHead
$script:result.clone.tree = $cloneTree
$script:result.clone.branch = $cloneBranch
$script:result.clone.status_porcelain = $cloneStatus
$script:result.clone.clean = ($cloneStatus -eq "")
$script:result.clone.tree_matches_source = ($cloneTree -eq $sourceTree)
$script:result.clone.remote = $cloneRemote
$script:result.clone.files = $cloneFiles
$script:result.clone.has_venv_before_creation = $hasVenv
$script:result.clone.has_downloads = $hasDownloads

Add-Log ("克隆 HEAD: " + $cloneHead + " / tree " + $cloneTree + " / branch " + $cloneBranch)
Add-Log ("克隆 remote: " + $cloneRemote + " / tracked files: " + $cloneFiles)
Add-Log ("克隆后 git status --porcelain -uall: " + $(if ($cloneStatus -eq "") { "<空>" } else { $cloneStatus }))

Write-Host ("[clone] HEAD={0} branch={1} clean={2} tree_match={3}" -f $cloneHead, $cloneBranch, $script:result.clone.clean, $script:result.clone.tree_matches_source)
if (-not $script:result.clone.clean) { Complete-Fail ("克隆点 git status 非空: " + $cloneStatus) }
if ($cloneHead -ne $sourceTip) { Complete-Fail ("克隆 HEAD 与分支 tip 不一致: " + $cloneHead + " != " + $sourceTip) }
if (-not $script:result.clone.tree_matches_source) { Complete-Fail "克隆 tree 与源分支 tree 不一致（不是同一份已提交状态）" }
if ($cloneBranch -ne $Branch) { Complete-Fail ("克隆分支不正确: " + $cloneBranch + " != " + $Branch) }
if ($hasVenv -or $hasDownloads) { Complete-Fail "克隆目录出现 .venv/.downloads，说明不是纯 git clone" }
if ($cloneFiles -le 0) { Complete-Fail "克隆目录没有任何 tracked 文件" }

# ---------------------------------------------------------------- 6) 新 venv
$venvDir = Join-Path $workFull ".venv"
$venvArgs = $creatorArgs + @("-m", "venv", $venvDir)
$venv = Invoke-Native $creatorExe $venvArgs (Get-Location).Path
$script:result.timing.venv_seconds = $venv.Seconds
Add-Log ("`n$ " + $venv.Command)
Add-Log $venv.Output
Write-Host ("[venv] exit={0} {1}s -> {2}" -f $venv.ExitCode, $venv.Seconds, $venvDir)
if ($venv.ExitCode -ne 0) { Complete-Fail ("创建 venv 失败（exit " + $venv.ExitCode + "）: " + (Get-Tail $venv.Output 8 600)) }

$venvPy = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) { Complete-Fail ("venv 中没有 python.exe: " + $venvPy) }
$script:result.python.venv_python = $venvPy

$venvProbe = Invoke-Native $venvPy @("-c", "import sys; print(sys.version.split()[0]); print(sys.prefix); print(sys.base_prefix)") $workFull
if ($venvProbe.ExitCode -ne 0) { Complete-Fail ("新 venv 的 python 不可用: " + (Get-Tail $venvProbe.Output 6 400)) }
$venvLines = @($venvProbe.Output -split "`r?`n" | Where-Object { $_.Trim() -ne "" })
$script:result.python.venv_python_version = $venvLines[0].Trim()
$script:result.python.venv_prefix = $venvLines[1].Trim()
$script:result.python.venv_base_prefix = $venvLines[2].Trim()
$script:result.python.isolation_ok = (
    $script:result.python.venv_prefix.StartsWith($workFull, [System.StringComparison]::OrdinalIgnoreCase) -and
    ($script:result.python.venv_prefix -ne $script:result.python.venv_base_prefix)
)
if (-not $script:result.python.isolation_ok) { Complete-Fail "新 venv 隔离校验失败（sys.prefix 不在克隆目录内）" }

$pipBefore = Invoke-Native $venvPy @("-m", "pip", "--version") $workFull
if ($pipBefore.ExitCode -eq 0) {
    $m = [regex]::Match($pipBefore.Output, "pip\s+([0-9][^\s]*)")
    if ($m.Success) { $script:result.python.pip_version_before = $m.Groups[1].Value }
} else {
    Complete-Fail ("新 venv 中 pip 不可用: " + (Get-Tail $pipBefore.Output 6 400))
}
$pkgBefore = Invoke-Native $venvPy @("-m", "pip", "list", "--format=json", "--disable-pip-version-check") $workFull
if ($pkgBefore.ExitCode -eq 0) {
    try {
        $parsed = $pkgBefore.Output | ConvertFrom-Json
        $script:result.python.packages_before = @($parsed | ForEach-Object { $_.name + "==" + $_.version })
    } catch { }
}
Add-Log ("新 venv: " + $venvPy + " / " + $script:result.python.venv_python_version + " / pip " + $script:result.python.pip_version_before)
Add-Log ("创建 venv 前已装包: " + ($script:result.python.packages_before -join ", "))

# ---------------------------------------------------------------- 7) 安装 lock
$installArgs = @("-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.lock")
if ($NoPipCache) { $installArgs += "--no-cache-dir" }
$install = Invoke-Native $venvPy $installArgs $workFull
$script:result.install.command = $install.Command
$script:result.install.exit_code = $install.ExitCode
$script:result.install.seconds = $install.Seconds
$script:result.timing.install_seconds = $install.Seconds
$script:result.install.cache_hits = ([regex]::Matches($install.Output, "(?m)^\s*Using cached\s")).Count
$script:result.install.downloads = ([regex]::Matches($install.Output, "(?m)^\s*Downloading\s")).Count
$m = [regex]::Match($install.Output, "Successfully installed ([^\r\n]+)")
if ($m.Success) { $script:result.install.successfully_installed = $m.Groups[1].Value.Trim() }
Add-Log ("`n$ " + $install.Command)
Add-Log $install.Output
Write-Host ("[install] exit={0} {1}s（cache hits {2}, downloads {3}）" -f $install.ExitCode, $install.Seconds, $script:result.install.cache_hits, $script:result.install.downloads)
if ($install.ExitCode -ne 0) { Complete-Fail ("pip install requirements.lock 失败（exit " + $install.ExitCode + "）: " + (Get-Tail $install.Output 12 900)) }

$pipAfter = Invoke-Native $venvPy @("-m", "pip", "--version") $workFull
if ($pipAfter.ExitCode -eq 0) {
    $m = [regex]::Match($pipAfter.Output, "pip\s+([0-9][^\s]*)")
    if ($m.Success) { $script:result.python.pip_version_after = $m.Groups[1].Value }
}

# 校验 lock 的每条 pin 都按精确版本装上（pip freeze 可能多出 setuptools，多出项不算失败）。
$freeze = Invoke-Native $venvPy @("-m", "pip", "freeze", "--exclude-editable") $workFull
$lockPath = Join-Path $workFull "requirements.lock"
$lockPins = [ordered]@{}
if (Test-Path -LiteralPath $lockPath) {
    foreach ($line in @(Get-Content -LiteralPath $lockPath)) {
        $t = $line.Trim()
        if (($t -eq "") -or $t.StartsWith("#")) { continue }
        $eq = $t.IndexOf("==")
        if ($eq -lt 0) { continue }
        $name = $t.Substring(0, $eq).Trim().ToLower().Replace("_", "-")
        $lockPins[$name] = $t.Substring($eq + 2).Trim()
    }
}
$freezePins = @{}
if ($freeze.ExitCode -eq 0) {
    foreach ($line in @($freeze.Output -split "`r?`n")) {
        $t = $line.Trim()
        if (($t -eq "") -or $t.StartsWith("#")) { continue }
        $eq = $t.IndexOf("==")
        if ($eq -lt 0) { continue }
        $name = $t.Substring(0, $eq).Trim().ToLower().Replace("_", "-")
        $freezePins[$name] = $t.Substring($eq + 2).Trim()
    }
}
$missing = New-Object 'System.Collections.Generic.List[string]'
$mismatch = New-Object 'System.Collections.Generic.List[string]'
foreach ($name in $lockPins.Keys) {
    if (-not $freezePins.ContainsKey($name)) {
        [void]$missing.Add($name + "==" + $lockPins[$name])
    } elseif ($freezePins[$name] -ne $lockPins[$name]) {
        [void]$mismatch.Add($name + ": lock=" + $lockPins[$name] + " freeze=" + $freezePins[$name])
    }
}
$script:result.install.lock_pins_total = $lockPins.Count
$script:result.install.lock_pins_verified = $lockPins.Count - $missing.Count - $mismatch.Count
$script:result.install.lock_missing = @($missing)
$script:result.install.lock_mismatch = @($mismatch)
Add-Log ("lock pins: " + $script:result.install.lock_pins_verified + "/" + $script:result.install.lock_pins_total + "；missing=" + ($missing -join ", ") + "；mismatch=" + ($mismatch -join ", "))
if ($missing.Count -gt 0 -or $mismatch.Count -gt 0) {
    Complete-Fail ("requirements.lock 的 pin 未全部按精确版本安装（missing=" + ($missing -join ", ") + "；mismatch=" + ($mismatch -join ", ") + "）")
}
if ($freeze.ExitCode -ne 0) { Add-Log "[warn] pip freeze 失败，但安装退出码为 0" }

# ---------------------------------------------------------------- 8) pip check
$pipCheck = Invoke-Native $venvPy @("-m", "pip", "check") $workFull
$script:result.pip_check.command = $pipCheck.Command
$script:result.pip_check.exit_code = $pipCheck.ExitCode
$script:result.pip_check.seconds = $pipCheck.Seconds
$script:result.pip_check.output = $pipCheck.Output.Trim()
$script:result.timing.pip_check_seconds = $pipCheck.Seconds
Add-Log ("`n$ " + $pipCheck.Command)
Add-Log $pipCheck.Output
Write-Host ("[pip check] exit={0} {1}s" -f $pipCheck.ExitCode, $pipCheck.Seconds)
if ($pipCheck.ExitCode -ne 0) { Complete-Fail ("pip check 失败（exit " + $pipCheck.ExitCode + "）: " + (Get-Tail $pipCheck.Output 8 600)) }

# ---------------------------------------------------------------- 9) 九项 checks
$checksSw = [System.Diagnostics.Stopwatch]::StartNew()
$passed = 0
foreach ($def in $script:checkDefs) {
    $step = Invoke-Native $venvPy $def.args $workFull
    $entry = [ordered]@{
        name        = $def.name
        command     = $step.Command
        exit_code   = $step.ExitCode
        seconds     = $step.Seconds
        output_tail = (Get-Tail $step.Output 10 800)
    }
    [void]$script:checkEntries.Add($entry)
    # 注意：PowerShell 5.1 对 @(List[object]) 会抛 "Argument types do not match"，必须用 ToArray()。
    $script:result.checks = $script:checkEntries.ToArray()
    Add-Log ("`n$ " + $step.Command)
    Add-Log ("exit=" + $step.ExitCode + " seconds=" + $step.Seconds)
    Add-Log $step.Output
    Write-Host ("[check] {0,-14} exit={1} {2}s" -f $def.name, $step.ExitCode, $step.Seconds)
    if ($step.ExitCode -ne 0) {
        $script:result.checks_passed = $passed
        $script:result.timing.checks_seconds = [math]::Round($checksSw.Elapsed.TotalSeconds, 2)
        Complete-Fail ("check 失败: " + $def.name + "（exit " + $step.ExitCode + "）: " + (Get-Tail $step.Output 12 900))
    }
    $passed++
    $script:result.checks_passed = $passed
}
$checksSw.Stop()
$script:result.timing.checks_seconds = [math]::Round($checksSw.Elapsed.TotalSeconds, 2)
if ($passed -ne $script:checkDefs.Count) { Complete-Fail ("checks 只通过 " + $passed + "/" + $script:checkDefs.Count) }
# 结果 JSON 必须逐条含 9 项 check（防止 PS 5.1 集合转换失败导致静默缺项）。
$checkCountInResult = @($script:result.checks).Count
if ($checkCountInResult -ne $script:checkDefs.Count) {
    Complete-Fail ("结果 JSON 的 checks 条数异常: " + $checkCountInResult + " != " + $script:checkDefs.Count)
}

# ---------------------------------------------------------------- 10) P7 离线 unittest
$testsArgs = @("-m", "unittest", "discover", "-s", "analysis/p07_agent/tests", "-q")
$tests = Invoke-Native $venvPy $testsArgs $workFull
$script:result.tests.command = $tests.Command
$script:result.tests.exit_code = $tests.ExitCode
$script:result.tests.seconds = $tests.Seconds
$script:result.timing.tests_seconds = $tests.Seconds
$ranMatch = [regex]::Match($tests.Output, "Ran (\d+) tests?")
if ($ranMatch.Success) { $script:result.tests.ran = [int]$ranMatch.Groups[1].Value }
$script:result.tests.ok = ($tests.ExitCode -eq 0 -and $script:result.tests.ran -ge $MinTests -and ($tests.Output -match "(?m)^OK\s*$"))
$script:result.tests.output_tail = (Get-Tail $tests.Output 10 800)
Add-Log ("`n$ " + $tests.Command)
Add-Log $tests.Output
Write-Host ("[tests] exit={0} ran={1} {2}s" -f $tests.ExitCode, $script:result.tests.ran, $tests.Seconds)
if ($tests.ExitCode -ne 0) { Complete-Fail ("P7 unittest 失败（exit " + $tests.ExitCode + "）: " + (Get-Tail $tests.Output 12 900)) }
if ($script:result.tests.ran -lt 0) { Complete-Fail "P7 unittest 输出中找不到 'Ran N tests'" }
if ($script:result.tests.ran -lt $MinTests) { Complete-Fail ("P7 unittest 条数不足: " + $script:result.tests.ran + " < " + $MinTests) }
if ($tests.Output -notmatch "(?m)^OK\s*$") { Complete-Fail "P7 unittest 没有输出 OK" }

# ---------------------------------------------------------------- 11) eval schema unittest
$evalArgs = @("-m", "unittest", "analysis.p07_agent.eval.tests.test_eval_schema", "-q")
$eval = Invoke-Native $venvPy $evalArgs $workFull
$script:result.eval_schema.command = $eval.Command
$script:result.eval_schema.exit_code = $eval.ExitCode
$script:result.eval_schema.seconds = $eval.Seconds
$script:result.timing.eval_schema_seconds = $eval.Seconds
$evalMatch = [regex]::Match($eval.Output, "Ran (\d+) tests?")
if ($evalMatch.Success) { $script:result.eval_schema.ran = [int]$evalMatch.Groups[1].Value }
$script:result.eval_schema.ok = ($eval.ExitCode -eq 0 -and $script:result.eval_schema.ran -ge $MinEvalTests -and ($eval.Output -match "(?m)^OK\s*$"))
$script:result.eval_schema.output_tail = (Get-Tail $eval.Output 10 800)
Add-Log ("`n$ " + $eval.Command)
Add-Log $eval.Output
Write-Host ("[eval] exit={0} ran={1} {2}s" -f $eval.ExitCode, $script:result.eval_schema.ran, $eval.Seconds)
if ($eval.ExitCode -ne 0) { Complete-Fail ("eval schema unittest 失败（exit " + $eval.ExitCode + "）: " + (Get-Tail $eval.Output 12 900)) }
if ($script:result.eval_schema.ran -lt 0) { Complete-Fail "eval schema unittest 输出中找不到 'Ran N tests'" }
if ($script:result.eval_schema.ran -lt $MinEvalTests) { Complete-Fail ("eval schema unittest 条数不足: " + $script:result.eval_schema.ran + " < " + $MinEvalTests) }
if ($eval.Output -notmatch "(?m)^OK\s*$") { Complete-Fail "eval schema unittest 没有输出 OK" }

# ---------------------------------------------------------------- 12) 收尾校验
$postStatus = Invoke-Native "git" @("-C", $workFull, "status", "--porcelain", "-uall") $workFull
$script:result.post_status_porcelain = $postStatus.Output.Trim()
$script:result.post_status_clean = ($postStatus.Output.Trim() -eq "")
if (-not $script:result.post_status_clean) {
    Add-Log ("[warn] 运行后克隆目录 git status 非空: " + $script:result.post_status_porcelain)
}
$trackedVenv = (Invoke-Native "git" @("-C", $workFull, "ls-files", ".venv") $workFull).Output.Trim()
if ($trackedVenv -ne "") { Complete-Fail "克隆目录里 .venv 被 git 跟踪（不应发生）: " + $trackedVenv }

if ($script:pipelineSw.IsRunning) { $script:pipelineSw.Stop() }
$total = [math]::Round($script:pipelineSw.Elapsed.TotalSeconds, 2)
$script:result.timing.total_seconds = $total
$script:result.timing.script_total_seconds = [math]::Round(((Get-Date) - $script:startedAt).TotalSeconds, 2)
Add-Log ("`n总耗时（clone -> tests）: " + $total + "s；脚本总耗时: " + $script:result.timing.script_total_seconds + "s")
if ($total -gt $MaxSeconds) {
    Complete-Fail ("总耗时 " + $total + "s 超过上限 " + $MaxSeconds + "s")
}

Complete-Pass
