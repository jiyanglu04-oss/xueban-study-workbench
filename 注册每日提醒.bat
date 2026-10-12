@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   学伴 · 开启每日提醒
echo   ============================================
echo.
echo   会向 Windows 计划任务里加一条定时提醒：
echo     每天 08:00 和 20:30 各弹一条系统通知。
echo.
echo     早报（中午前）：逾期未处理的 + 今天到点的待办 + 今天的课
echo     晚报（中午后）：今天还没勾完的 + 明天/后天到点的
echo.
echo   不需要开着工作台，也不会弹浏览器窗口。
echo   电脑关机错过了时间，开机后会自动补跑一次。
echo.
echo   想让它先响一声试试，稍后双击「立刻提醒我.bat」。
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync\register_digest.ps1" -Mode register %*

echo.
echo   （想改时间，例如每天 07:30 / 21:30，可以执行：
echo     register_digest.ps1 -Mode register -Times 07:30,21:30）
echo.
pause
