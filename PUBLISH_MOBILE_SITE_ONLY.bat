@echo off
chcp 65001 >nul
cd /d "%~dp0"
wscript.exe "%~dp0天天樂背景手機同步.vbs"
exit /b
