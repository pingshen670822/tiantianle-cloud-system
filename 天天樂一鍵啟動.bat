@echo off
chcp 65001 >nul
title 天天樂一鍵啟動
cd /d "%~dp0"
echo 天天樂全系統一鍵啟動
echo 正在更新資料、重新運算、產生戰報、同步手機雲端版...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run_california_fantasy5_once.ps1" -ForceRun
echo.
echo 天天樂全系統已完成。若手機未立刻更新，請重新開啟手機頁或點清除快取。
pause
