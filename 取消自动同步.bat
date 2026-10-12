@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   学伴 · 关闭每天自动同步
echo   ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync\register_task.ps1" -Mode unregister

echo.
pause
