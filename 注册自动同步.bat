@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   学伴 · 开启每天自动同步
echo   ============================================
echo.
echo   会向 Windows 计划任务里加一条定时任务：
echo     每天 08:00 和 20:00 自动抓一次消息通知和作业。
echo   抓取时不会弹浏览器窗口，也不需要开着工作台。
echo   电脑关机错过时间的话，开机后会自动补跑一次。
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync\register_task.ps1" -Mode register %*

echo.
echo   （想把时间改成别的，例如每天 7:30 / 12:30 / 21:00：
echo     在本文件上右键 ^-^> 编辑，或在命令行里执行
echo     register_task.ps1 -Mode register -Times 07:30,12:30,21:00）
echo.
pause
