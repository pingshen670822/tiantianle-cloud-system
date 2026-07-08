@echo off
chcp 65001 >nul
cd /d "%~dp0"
wscript.exe "%~dp0天天樂背景更新.vbs"
exit /b
