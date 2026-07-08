$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartupDir = [Environment]::GetFolderPath("Startup")
$Launcher = Join-Path $StartupDir "Tiantianle_Ironlaw_AutoUpdate.vbs"
$OldLauncher = Join-Path $StartupDir "Tiantianle_Ironlaw_AutoUpdate.cmd"
$SafeScriptDir = $ScriptDir.Replace('"', '""')
$Lines = @(
  "Option Explicit",
  "Dim shell, root, cmd",
  "Set shell = CreateObject(""WScript.Shell"")",
  ("root = """ + $SafeScriptDir + """"),
  "shell.CurrentDirectory = root",
  "cmd = ""powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "" & Chr(34) & root & ""\run_california_fantasy5_once.ps1"" & Chr(34) & "" -NoOpen""",
  "shell.Run cmd, 0, False"
)
try {
  if (Test-Path -LiteralPath $OldLauncher) {
    Remove-Item -LiteralPath $OldLauncher -Force
  }
  Set-Content -LiteralPath $Launcher -Value $Lines -Encoding Unicode
} catch {
  $IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $IsAdmin) {
    Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
  }
  throw
}
Write-Host "Startup auto update installed hidden: $Launcher"
