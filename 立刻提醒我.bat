@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   学伴 · 立刻弹一条提醒
echo   ============================================
echo.

set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\lwb\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%~dp0sync\daily_digest.py" --auto --force

echo.
echo   （上面是通知里的内容。这次试发不会占用今天定时提醒的名额。）
echo.
pause
