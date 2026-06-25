$TaskName = "Tiantianle Ironlaw Daily Auto Update"
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
} catch {
}
$StartupLauncher = Join-Path ([Environment]::GetFolderPath("Startup")) "Tiantianle_Ironlaw_AutoUpdate.cmd"
if (Test-Path $StartupLauncher) {
    Remove-Item $StartupLauncher -Force
}
Write-Host "Tiantianle auto update tasks removed."
