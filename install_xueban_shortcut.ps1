# 学伴桌面入口：在桌面创建带图标的快捷方式。
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$launcher = Join-Path $root 'launch_xueban.ps1'
if (-not (Test-Path -LiteralPath $launcher)) { throw '找不到 launch_xueban.ps1，请确认压缩包解压完整。' }

$icon = Join-Path $root 'assets\xueban-v1.ico'
if (-not (Test-Path -LiteralPath $icon)) { $icon = Join-Path $env:SystemRoot 'System32\shell32.dll' }

$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop '学伴.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPath)
$link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$link.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
$link.WorkingDirectory = $root
$link.IconLocation = $icon + ',0'
$link.Description = '学伴 · 课程、待办与通知，一处掌握'
$link.WindowStyle = 7
$link.Save()
Write-Output ('已创建桌面快捷方式：' + $linkPath)
