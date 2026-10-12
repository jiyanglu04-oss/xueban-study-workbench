@echo off
rem ============================================================
rem  StudyMate launcher
rem  - Reuses a local runtime if one is already there
rem  - Otherwise prepares one automatically (see setup_runtime.ps1)
rem  - Kept ASCII-only on purpose: a .bat with non-ASCII bytes gets
rem    mis-decoded by cmd and can silently mangle commands.
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY="

if not defined PY (
  echo.
  echo   First run - preparing the runtime. This happens only once.
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_runtime.ps1"
  if exist "%~dp0runtime\python\python.exe" set "PY=%~dp0runtime\python\python.exe"
)

if not defined PY (
  echo.
  echo   [FAILED] Could not prepare the runtime.
  echo   Please check your network connection, then run this file again.
  echo.
  pause
  exit /b 1
)

"%PY%" -c "import playwright; import PIL; import winrt.windows.media.ocr; import winrt.windows.graphics.imaging; import winrt.windows.storage" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Installing sync and timetable OCR components, please wait...
  echo.
  "%PY%" -m pip install -r "%~dp0sync\requirements.txt" -i https://mirrors.aliyun.com/pypi/simple/ --no-warn-script-location
  if errorlevel 1 (
    echo   [FAILED] Component installation failed. Please retry online.
    pause
    exit /b 1
  )
)

"%PY%" -m backend.server
if errorlevel 1 (
  echo.
  echo   The service exited unexpectedly.
  echo.
  pause
)
endlocal
