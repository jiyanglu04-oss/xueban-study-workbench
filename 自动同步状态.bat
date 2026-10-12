@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   学伴 · 自动同步状态
echo   ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync\register_task.ps1" -Mode status

echo.
pause
