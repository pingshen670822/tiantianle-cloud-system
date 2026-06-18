$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $ScriptDir "run_california_fantasy5_once.ps1"
$StartupDir = [Environment]::GetFolderPath("Startup")
$Launcher = Join-Path $StartupDir "Tiantianle_Ironlaw_AutoUpdate.cmd"
$Lines = @(
  "@echo off",
  "start `"`" /min powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`" -NoOpen"
)
try {
  Set-Content -LiteralPath $Launcher -Value $Lines -Encoding ASCII
} catch {
  $IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $IsAdmin) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
  }
  throw
}
Write-Host "Startup auto update installed: $Launcher"
