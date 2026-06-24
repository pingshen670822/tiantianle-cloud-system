$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $Root "run_california_fantasy5_once.ps1"
$TaskName = "Tiantianle Ironlaw Daily Auto Update"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`" -NoOpen" -WorkingDirectory $Root
$Trigger = @()
function New-DailyRepeatingTrigger {
  param([string]$At, [int]$DurationMinutes)
  $trigger = New-ScheduledTaskTrigger -Daily -At $At
  $repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Minutes $DurationMinutes)).Repetition
  $trigger.Repetition = $repetition
  return $trigger
}
$Trigger += New-DailyRepeatingTrigger "09:50" 40
$Trigger += New-DailyRepeatingTrigger "10:50" 40
$Trigger += New-ScheduledTaskTrigger -Daily -At "21:45"
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Auto update Tiantianle data and prediction reports." -Force
Write-Host "Installed: $TaskName"
Write-Host "Triggers: 09:50-10:30 every 1 minute, 10:50-11:30 every 1 minute, 21:45 Taiwan time"
