@echo off
chcp 65001 >nul
cd /d "%~dp0"
wscript.exe "%~dp0天天樂背景完整上線.vbs"
exit /b
