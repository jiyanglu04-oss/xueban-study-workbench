# 学伴桌面入口：先看服务在不在；不在就拉起来，然后打开工作台。
# 本机和发布包共用这一个脚本：
#   · 本机有 .venv，直接用 .venv
#   · 发布包第一次运行时还没有 runtime\，就转交给带窗口的「启动工作台.bat」
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskUrl = 'http://127.0.0.1:8765'

function Test-Workbench {
    try {
        $taskHealth = Invoke-RestMethod -Uri "$taskUrl/api/health" -TimeoutSec 2
        return ($null -ne $taskHealth -and $taskHealth.ok -eq $true)
    } catch { return $false }
}

function Find-Python {
    $taskCands = @(
        (Join-Path $taskRoot 'runtime\python\python.exe'),
        (Join-Path $taskRoot '.venv\Scripts\python.exe'),
        (Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\lwb\Scripts\python.exe')
    )
    foreach ($taskCand in $taskCands) {
        if (Test-Path -LiteralPath $taskCand) { return $taskCand }
    }
    return $null
}

try {
    if (-not (Test-Workbench)) {
        $taskPython = Find-Python
        if (-not $taskPython) {
            # 还没有运行环境。转交给带窗口的启动脚本 —— 首次要下载约 50 MB，
            # 用户得看得见进度，否则会以为双击没反应。
            Start-Process -FilePath (Join-Path $taskRoot '启动工作台.bat') -WorkingDirectory $taskRoot
            exit 0
        }
        Start-Process -FilePath $taskPython -ArgumentList '-m', 'backend.server', '--no-open' -WorkingDirectory $taskRoot -WindowStyle Hidden
        for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
            if (Test-Workbench) { break }
            Start-Sleep -Milliseconds 750
        }
        if (-not (Test-Workbench)) { throw '工作台未能启动。请检查端口 8765 是否被占用，或双击「启动工作台.bat」查看错误。' }
    }
    Start-Process $taskUrl
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '学伴 · 启动失败') | Out-Null
    exit 1
}
