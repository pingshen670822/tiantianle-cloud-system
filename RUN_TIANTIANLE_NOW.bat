@echo off
chcp 65001 >nul
title Tiantianle One-Click Run
cd /d "%~dp0"
echo Starting Tiantianle one-click update and prediction...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run_california_fantasy5_once.ps1" -ForceRun
echo.
echo Done. Press any key to close.
pause >nul
