@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set TIANTIANLE_RUN_MODE=realtime
python "%~dp0california_fantasy5_system.py"
if errorlevel 1 goto failed
python "%~dp0pages_build.py"
if errorlevel 1 goto failed
start "" "%~dp0site\index.html"
exit /b
:failed
echo 更新未完成，請查看上方錯誤訊息。
pause
exit /b 1
