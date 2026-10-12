@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   学伴 · 关闭每日提醒
echo   ============================================
echo.
echo   关闭后不再自动弹通知，工作台本身完全不受影响，
echo   数据照常同步，随时可以再双击本目录的「注册每日提醒.bat」开回来。
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync\register_digest.ps1" -Mode unregister %*

echo.
pause
