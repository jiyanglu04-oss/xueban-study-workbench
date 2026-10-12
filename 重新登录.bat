@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "VENV_PY=%~dp0runtime\python\python.exe"
if exist "%VENV_PY%" goto checkenv
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto checkenv
set "VENV_PY=%USERPROFILE%\.workbuddy\binaries\python\envs\lwb\Scripts\python.exe"
:checkenv
if not exist "%VENV_PY%" goto noenv

echo.
echo   Relogin only - it will NOT re-fetch any data.
echo.
echo   Only the platforms whose login has expired will pop up a browser
echo   window. Scan the QR code, then close the window when it is done.
echo.

"%VENV_PY%" "sync\relogin.py" %*
echo.
pause
exit /b %errorlevel%

:noenv
echo.
echo   Environment is not ready yet.
echo   Please double-click  "安装环境.bat"  first (only once).
echo.
pause
exit /b 1
