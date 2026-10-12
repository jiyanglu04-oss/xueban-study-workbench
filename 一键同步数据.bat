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
"%VENV_PY%" -c "import sys" >nul 2>nul
if errorlevel 1 goto badenv

echo.
echo   Syncing your learning platforms...
echo   A browser window will open. First time: please scan the QR code to log in.
echo.
echo   Tip: want this to run by itself twice a day (08:00 / 20:00)?
echo        double-click  "注册自动同步.bat"  once. Check it with
echo        "自动同步状态.bat", remove it with "取消自动同步.bat".
echo.

"%VENV_PY%" "sync\sync.py" %*
exit /b %errorlevel%

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
