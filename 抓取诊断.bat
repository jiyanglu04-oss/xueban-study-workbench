@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem  Grab messages / todos with full debug logging.
rem  Use this when a platform returns nothing: every request and
rem  response is written to  sync\debug\  so it can be sent back
rem  and the parser fixed in one go.
rem ---------------------------------------------------------------

set "VENV_PY=%~dp0runtime\python\python.exe"
if exist "%VENV_PY%" goto checkenv
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto checkenv
set "VENV_PY=%USERPROFILE%\.workbuddy\binaries\python\envs\lwb\Scripts\python.exe"
:checkenv
if not exist "%VENV_PY%" goto noenv
"%VENV_PY%" -c "import sys" >nul 2>nul
if errorlevel 1 goto badenv

echo.
echo   Diagnostic sync - every request/response is logged.
echo   A browser window will open. First time: please scan the QR code to log in.
echo.

"%VENV_PY%" "sync\sync.py" --debug %*

echo.
echo   Debug files are in:  %~dp0sync\debug
echo   Opening that folder for you...
start "" "%~dp0sync\debug"
exit /b 0

:noenv
echo.
echo   Environment is not ready yet.
echo   Please double-click  "安装环境.bat"  first (only once).
echo.
pause
exit /b 1

:badenv
echo.
echo   The existing Python environment is no longer valid.
echo   Please double-click  "安装环境.bat"  to rebuild it.
echo.
pause
exit /b 1
