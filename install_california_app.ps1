$ErrorActionPreference = "Stop"

$AppName = "Tiantianle Ironlaw Engine"
$ChineseAppName = [char]0x52A0 + [char]0x5DDE + [char]0x5929 + [char]0x5929 + [char]0x6A02 + [char]0x9810 + [char]0x6E2C + [char]0x7CFB + [char]0x7D71
$InstallRoot = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Codex\Tiantianle_IronlawEngine"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Get-ChildItem -Path $SourceDir -Force | Where-Object { $_.Name -ne "__pycache__" } | ForEach-Object {
  $Target = Join-Path $InstallRoot $_.Name
  if ($_.PSIsContainer) {
    Copy-Item -Path $_.FullName -Destination $Target -Recurse -Force
  } else {
    Copy-Item -Path $_.FullName -Destination $Target -Force
  }
}

$StartBat = Join-Path $InstallRoot "START_CALIFORNIA_FANTASY5.bat"
$ChineseStartBat = Join-Path $InstallRoot ($ChineseAppName + ".bat")
$Lines = @(
  "@echo off",
  "cd /d `"$InstallRoot`"",
  "powershell -NoProfile -ExecutionPolicy Bypass -File `"$InstallRoot\run_california_fantasy5_once.ps1`"",
  "pause"
)
Set-Content -Path $StartBat -Value $Lines -Encoding ASCII
Set-Content -Path $ChineseStartBat -Value $Lines -Encoding ASCII

Write-Host "Installed: $InstallRoot"
Write-Host "Launcher: $StartBat"
Write-Host "Chinese launcher: $ChineseStartBat"
