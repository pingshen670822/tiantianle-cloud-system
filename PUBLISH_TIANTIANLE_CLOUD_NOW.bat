@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
python "%~dp0cloud_update_request.py"
set "UpdateExit=%errorlevel%"
if not "%UpdateExit%"=="0" pause
exit /b %UpdateExit%
