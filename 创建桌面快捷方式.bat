@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   学伴 · 创建桌面快捷方式
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_xueban_shortcut.ps1"
if errorlevel 1 (
  echo.
  echo   创建失败。可以手动把「启动工作台.bat」右键 - 发送到 - 桌面快捷方式。
)
echo.
pause
