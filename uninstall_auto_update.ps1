$TaskName = "Tiantianle Ironlaw Daily Auto Update"
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
} catch {
}
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupLaunchers = @(
  (Join-Path $StartupDir "Tiantianle_Ironlaw_AutoUpdate.cmd"),
  (Join-Path $StartupDir "Tiantianle_Ironlaw_AutoUpdate.vbs")
)
foreach ($StartupLauncher in $StartupLaunchers) {
  if (Test-Path -LiteralPath $StartupLauncher) {
    Remove-Item -LiteralPath $StartupLauncher -Force
  }
}
Write-Host "Tiantianle auto update tasks removed."
