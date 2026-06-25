@echo off
chcp 65001 >nul
set "SCRIPT=%~dp0cleanup_old_startup_tasks_admin.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%SCRIPT%""'"
echo 已呼叫管理員清理。若出現 Windows 權限確認，請按「是」。
pause
