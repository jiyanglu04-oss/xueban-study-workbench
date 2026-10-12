@echo off
rem ============================================================
rem  Rebuild the runtime from scratch.
rem  Use this only when the normal launcher fails (e.g. the
rem  runtime folder got damaged halfway through a download).
rem  Kept ASCII-only on purpose - see 启动工作台.bat for why.
rem ============================================================
setlocal
cd /d "%~dp0"

echo.
echo   Rebuilding the runtime. This downloads about 50 MB.
echo.

if exist "runtime" rmdir /s /q "runtime"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_runtime.ps1"

echo.
echo   Done. Now run  启动工作台.bat  to start.
echo.
pause
endlocal
