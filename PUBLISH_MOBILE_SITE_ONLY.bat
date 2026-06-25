@echo off
setlocal
cd /d "%~dp0"
echo Publishing Tiantianle mobile site/data/reports only...
echo.
"C:\Users\MSI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "%~dp0publish_mobile_site_only.py"
echo.
pause
