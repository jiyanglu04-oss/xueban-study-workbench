<#
学伴 · 每日提醒注册脚本

加一条 Windows 计划任务「学伴-每日提醒」，每天 08:00 / 20:30 各弹一条系统通知：
    早报（中午前）＝ 逾期未处理 + 今天到点的待办 + 今天的课
    晚报（中午后）＝ 今天还没勾完的 + 明天/后天到点的

它和「自动同步」是两条互不干扰的任务：
    自动同步 管的是「数据是不是新的」；
    每日提醒 管的是「你有没有看见」。
两个都不需要工作台页面开着，也不需要浏览器。

用法（正常情况双击上级目录的「注册每日提醒.bat」就行）：
    powershell -File sync\register_digest.ps1 -Mode register
    powershell -File sync\register_digest.ps1 -Mode register -Times 07:30,21:30
    powershell -File sync\register_digest.ps1 -Mode unregister
    powershell -File sync\register_digest.ps1 -Mode status

执行完会把状态写到 sync\state\digest-task.json。
#>
[CmdletBinding()]
param(
    [ValidateSet('register', 'unregister', 'status')]
    [string]$Mode = 'register',
    [string]$Times = '08:00,20:30'
)

$ErrorActionPreference = 'Stop'

$Root      = Split-Path -Parent $PSScriptRoot
$TaskName  = '学伴-每日提醒'
$LogDir    = Join-Path $Root 'sync\logs'
$StateDir  = Join-Path $Root 'sync\state'
$StateFile = Join-Path $StateDir 'digest-task.json'

$timeList = @($Times -split '[,，;；\s]+' | Where-Object { $_ -match '^\d{1,2}:\d{2}$' })
if ($timeList.Count -eq 0) { $timeList = @('08:00', '20:30') }

function Find-PythonW {
    $cands = @(
        (Join-Path $Root 'runtime\python\pythonw.exe'),
        (Join-Path $Root '.venv\Scripts\pythonw.exe'),
        (Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\lwb\Scripts\pythonw.exe')
    )
    foreach ($c in $cands) { if (Test-Path -LiteralPath $c) { return $c } }
    return $null
}

function Write-State {
    param([string]$Mode, [string[]]$Times = @())
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $payload = [ordered]@{
        mode      = $Mode
        times     = $Times
        taskName  = $TaskName
        updatedAt = (Get-Date).ToString('s')
    }
    # 必须是不带 BOM 的 UTF-8：带 BOM 的话 Python 的 json.loads 会抛异常，
    # 工作台就会一直把状态显示成「未开启」。
    $json = $payload | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($StateFile, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "  状态：已开启" -ForegroundColor Green
        Write-Host "  提醒时间：每天 $($timeList -join ' / ')（不需要开着工作台）"
        if ($info) {
            Write-Host "  上次提醒：$($info.LastRunTime)"
            Write-Host "  下次提醒：$($info.NextRunTime)"
        }
    } else {
        Write-Host "  状态：未开启 —— 不会自动提醒你" -ForegroundColor Yellow
        Write-Host "  双击「注册每日提醒.bat」即可开启。"
    }
}

if ($Mode -eq 'status') {
    Show-Status
    exit 0
}

if ($Mode -eq 'unregister') {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "  已删除计划任务：$TaskName" -ForegroundColor Green
    } else {
        Write-Host "  本来就没有开启，什么都没做。"
    }
    Write-State -Mode 'none' -Times @()
    exit 0
}

# ---------------- register ----------------
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

$py = Find-PythonW
if (-not $py) {
    Write-Host "  找不到 pythonw.exe，无法开启每日提醒。" -ForegroundColor Red
    exit 1
}

$pyScript = Join-Path $Root 'sync\daily_digest.py'
if (-not (Test-Path -LiteralPath $pyScript)) {
    Write-Host "  找不到 sync\daily_digest.py，无法开启每日提醒。" -ForegroundColor Red
    exit 1
}

Write-Host "  项目目录：$Root"
Write-Host "  运行环境：$py"
Write-Host "  提醒时间：每天 $($timeList -join ' / ')"
Write-Host ""

try {
    $action = New-ScheduledTaskAction `
        -Execute $py `
        -Argument ('"' + $pyScript + '" --auto') `
        -WorkingDirectory $Root
    $triggers = @($timeList | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    $desc = '每天定时弹一条整合通知：今天/明天到点的待办和课程。'
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Description $desc -Force | Out-Null
    Write-Host "  √ 已注册 Windows 计划任务：$TaskName" -ForegroundColor Green
    Write-Host "    错过的时段会在这台电脑开机后补跑一次。"
    Write-State -Mode 'task' -Times $timeList
} catch {
    Write-Host "  注册失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  可以改用「开机自启」方案，或手动双击「立刻提醒我.bat」查看。"
    exit 1
}

Write-Host ""
Show-Status
Write-Host ""
Write-Host "  想立刻看一条效果：双击「立刻提醒我.bat」。"
Write-Host "  想关掉：双击「取消每日提醒.bat」。"
