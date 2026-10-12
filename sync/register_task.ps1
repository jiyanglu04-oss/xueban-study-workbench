<#
学伴 · 自动同步注册脚本

给 Windows 计划任务里加一条「学伴-自动同步」，每天 08:00 / 20:00 各跑一次
数据同步。跑的时候**不弹浏览器窗口**，也不需要工作台页面开着 —— 结果直接写进
data\workbench.sqlite3，下次打开工作台就能看到。

为什么用计划任务而不是「工作台开着才同步」：
    学生不会整天开着一个命令行窗口。电脑关着、工作台没开的时候照样该更新数据。

「错过了怎么办」：
    计划任务带了 StartWhenAvailable（错过后尽快补跑）。比如 08:00 时电脑还没开机，
    9 点开机后它会立刻补跑一次，不会一整天都是旧数据。

用法（正常情况双击上级目录的「注册自动同步.bat」就行）：
    powershell -File sync\register_task.ps1 -Mode register
    powershell -File sync\register_task.ps1 -Mode register -Times 07:30,12:30,21:00
    powershell -File sync\register_task.ps1 -Mode unregister
    powershell -File sync\register_task.ps1 -Mode status

执行完会把状态写到 sync\state\schedule.json，工作台的「设置」页读它来显示状态。
#>
[CmdletBinding()]
param(
    [ValidateSet('register', 'unregister', 'status')]
    [string]$Mode = 'register',
    [string]$Times = '08:00,20:00'
)

$ErrorActionPreference = 'Stop'

$Root      = Split-Path -Parent $PSScriptRoot        # sync\ 的上一级就是项目根目录
$TaskName  = '学伴-自动同步'
$LogDir    = Join-Path $Root 'sync\logs'
$StateDir  = Join-Path $Root 'sync\state'
$StateFile = Join-Path $StateDir 'schedule.json'
$Startup   = [Environment]::GetFolderPath('Startup')
$Fallback  = Join-Path $Startup '学伴-自动同步.cmd'

$timeList = @($Times -split '[,，;；\s]+' | Where-Object { $_ -match '^\d{1,2}:\d{2}$' })
if ($timeList.Count -eq 0) { $timeList = @('08:00', '20:00') }

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
    # ⚠️ 必须用「不带 BOM 的 UTF-8」写。
    # Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会加 BOM，
    # 而 Python 的 json.loads 遇到开头的 \ufeff 会直接抛 JSONDecodeError，
    # 结果是工作台永远把状态读成「未开启」—— 明明已经注册好了。
    $json = $payload | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($StateFile, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "  状态：已开启（Windows 计划任务）" -ForegroundColor Green
        Write-Host "  执行时间：每天 $($timeList -join ' / ')（不需要开着工作台）"
        if ($info) {
            Write-Host "  上次运行：$($info.LastRunTime)"
            Write-Host "  下次运行：$($info.NextRunTime)"
        }
    } elseif (Test-Path -LiteralPath $Fallback) {
        Write-Host "  状态：已开启（开机自启，计划任务不可用时的备用方案）" -ForegroundColor Yellow
        Write-Host "  只在每次登录后跑一次。"
    } else {
        Write-Host "  状态：未开启 —— 不会自动同步" -ForegroundColor Yellow
        Write-Host "  双击「注册自动同步.bat」即可开启。"
    }
}

function Install-Fallback {
    param([string]$PythonW)
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $cmd = @"
@echo off
rem 学伴自动同步（计划任务不可用时的备用方案：每次登录后跑一次）
"$PythonW" "$Root\sync\sync.py" --headless --no-pause --reason schedule >> "$LogDir\startup.log" 2>&1
"@
    Set-Content -LiteralPath $Fallback -Value $cmd -Encoding ASCII
}

if ($Mode -eq 'status') {
    Show-Status
    exit 0
}

if ($Mode -eq 'unregister') {
    $removed = $false
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "  已删除计划任务：$TaskName" -ForegroundColor Green
        $removed = $true
    }
    if (Test-Path -LiteralPath $Fallback) {
        Remove-Item -LiteralPath $Fallback -Force
        Write-Host "  已删除开机启动项" -ForegroundColor Green
        $removed = $true
    }
    if (-not $removed) { Write-Host "  本来就没有开启，什么都没做。" }
    Write-State -Mode 'none' -Times @()
    Write-Host ""
    Write-Host "  自动同步已关闭。想手动更新数据，双击「一键同步数据.bat」即可。"
    exit 0
}

# ---------------- register ----------------
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

$py = Find-PythonW
if (-not $py) {
    Write-Host "  找不到 pythonw.exe，无法开启自动同步。" -ForegroundColor Red
    Write-Host "  请先双击一次「安装环境.bat」把运行环境装好。"
    exit 1
}

$pyScript = Join-Path $Root 'sync\sync.py'
if (-not (Test-Path -LiteralPath $pyScript)) {
    Write-Host "  找不到 sync\sync.py，无法开启自动同步。" -ForegroundColor Red
    exit 1
}

Write-Host "  项目目录：$Root"
Write-Host "  运行环境：$py"
Write-Host "  执行时间：每天 $($timeList -join ' / ')（不弹窗口）"
Write-Host ""

$usedFallback = $false
try {
    $action = New-ScheduledTaskAction `
        -Execute $py `
        -Argument ('"' + $pyScript + '" --headless --no-pause --reason schedule') `
        -WorkingDirectory $Root
    $triggers = @($timeList | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    $desc = '每天自动抓取超星学习通、雨课堂、中国大学 MOOC 的通知与作业，写入学伴数据库。'
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Description $desc -Force | Out-Null
    Write-Host "  √ 已注册 Windows 计划任务：$TaskName" -ForegroundColor Green
    Write-Host "    错过的时段会在这台电脑开机后自动补跑一次。"
    Write-State -Mode 'task' -Times $timeList
} catch {
    Write-Host "  注册计划任务失败：$($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "  改用备用方案：放进开机启动文件夹（每次登录后跑一次）。"
    try {
        Install-Fallback -PythonW $py
        Write-Host "  √ 已添加开机启动项" -ForegroundColor Green
        Write-State -Mode 'startup' -Times @()
        $usedFallback = $true
    } catch {
        Write-Host "  备用方案也失败了：$($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# 顺手把工作台里的「自动同步」开关也打开，免得开了定时任务、界面却还显示关闭
try {
    $pyExe = Join-Path (Split-Path -Parent $py) 'python.exe'
    if (Test-Path -LiteralPath $pyExe) {
        & $pyExe (Join-Path $Root 'sync\enable_autosync.py') | Out-Null
    }
} catch {
    Write-Host "  （工作台里的开关没改成功，请在「设置」页手动打开）" -ForegroundColor Yellow
}

Write-Host ""
Show-Status
Write-Host ""
if ($usedFallback) {
    Write-Host "  注意：当前用的是开机自启动方案，只在登录后才跑一次，不是每天两次。"
} else {
    Write-Host "  以后每天会自动更新消息和待办，你不需要做任何事。"
}
Write-Host "  想立刻试一次：双击「一键同步数据.bat」。"
Write-Host "  想关掉：双击「取消自动同步.bat」。"
