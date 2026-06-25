$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Project = "C:\Users\MSI\Documents\Codex\天天樂鐵律專用版-20260615"
$ReportDir = Join-Path $Project "reports"
New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $ReportDir "startup_cleanup_admin_$Stamp.txt"
$StartupDir = [Environment]::GetFolderPath("Startup")
$LatestLauncher = Join-Path $StartupDir "Tiantianle_Ironlaw_AutoUpdate.cmd"
$RunScript = Join-Path $Project "run_california_fantasy5_once.ps1"

$RemoveTaskNames = @(
  "539 Mobile Control Server",
  "539 Startup Full Run",
  "CA_FANTASY5_BOOT_AUTO",
  "California Fantasy5 539 Latest Engine Daily Auto Update",
  "California Fantasy5 Daily Auto Update",
  "TW539_One_Click_Report",
  "TW539_Research_Platform"
)

$Log = New-Object System.Collections.Generic.List[string]
$Log.Add("Startup cleanup admin run: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
$Log.Add("Keep latest launcher: $LatestLauncher")
$Log.Add("Keep latest daily task: Tiantianle Ironlaw Daily Auto Update")
$Log.Add("")
$Log.Add("Removed scheduled tasks:")

foreach ($Name in $RemoveTaskNames) {
  $Task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
  if ($Task) {
    $Log.Add("REMOVE TASK: $Name")
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
  } else {
    $Log.Add("NOT FOUND: $Name")
  }
}

$LauncherLines = @(
  "@echo off",
  "chcp 65001 >nul",
  "start `"`" /min powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`" -NoOpen"
)
Set-Content -LiteralPath $LatestLauncher -Value $LauncherLines -Encoding UTF8

$Log.Add("")
$Log.Add("Rewritten latest launcher:")
$Log.Add($LatestLauncher)
$Log.Add(($LauncherLines -join " | "))
$Log | Set-Content -LiteralPath $LogPath -Encoding UTF8
Write-Host "Done: $LogPath"
