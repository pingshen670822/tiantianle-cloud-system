@echo off
setlocal
cd /d "%~dp0"
echo Publishing Tiantianle cloud mobile system...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_tiantianle_cloud.ps1"
echo.
pause
