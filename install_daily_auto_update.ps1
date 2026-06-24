$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $Root "run_california_fantasy5_once.ps1"
$TaskName = "Tiantianle Ironlaw Daily Auto Update"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`" -NoOpen" -WorkingDirectory $Root
$Trigger = @()
$TriggerTimes = @(
  "09:50", "09:53", "09:56", "09:59",
  "10:02", "10:05", "10:08", "10:11", "10:14", "10:17", "10:20", "10:25", "10:30", "10:40",
  "10:50", "10:53", "10:56", "10:59",
  "11:02", "11:05", "11:08", "11:11", "11:14", "11:17", "11:20", "11:25", "11:30",
  "21:45"
)
foreach ($TimeText in $TriggerTimes) {
  $Trigger += New-ScheduledTaskTrigger -Daily -At $TimeText
}
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Auto update Tiantianle data and prediction reports." -Force
Write-Host "Installed: $TaskName"
Write-Host ("Triggers: " + ($TriggerTimes -join ", ") + " Taiwan time")
