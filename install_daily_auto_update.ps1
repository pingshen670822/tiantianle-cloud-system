$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $Root "run_california_fantasy5_once.ps1"
$AfterDrawScript = Join-Path $Root "天天樂開獎後自動更新.ps1"
$AfterDrawTaskName = "Tiantianle Ironlaw After Draw Auto Update"
$DeepTaskName = "Tiantianle Ironlaw Daily Deep Review"
$SafetyTaskName = "Tiantianle Ironlaw Night Safety Sync"
$LegacyTaskName = "Tiantianle Ironlaw Daily Auto Update"

foreach ($TaskName in @($LegacyTaskName, $AfterDrawTaskName, $DeepTaskName, $SafetyTaskName)) {
  try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
  } catch {
  }
}

function New-DailyRepeatingTrigger {
  param([string]$At, [int]$IntervalMinutes, [int]$DurationMinutes)
  $trigger = New-ScheduledTaskTrigger -Daily -At $At
  $repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Minutes $DurationMinutes)).Repetition
  $trigger.Repetition = $repetition
  return $trigger
}

$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

$AfterDrawAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$AfterDrawScript`" -NoOpen" -WorkingDirectory $Root
$AfterDrawTriggers = @()
$AfterDrawTriggers += New-DailyRepeatingTrigger "09:50" 5 65
$AfterDrawTriggers += New-ScheduledTaskTrigger -Daily -At "10:55"
Register-ScheduledTask -TaskName $AfterDrawTaskName -Action $AfterDrawAction -Trigger $AfterDrawTriggers -Settings $Settings -Description "After Taiwan draw time, keep retrying until latest draw, review archive, next prediction, and mobile sync are complete." -Force | Out-Null

$DeepAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`" -All -NoOpen" -WorkingDirectory $Root
$DeepTrigger = New-ScheduledTaskTrigger -Daily -At "13:00"
Register-ScheduledTask -TaskName $DeepTaskName -Action $DeepAction -Trigger $DeepTrigger -Settings $Settings -Description "Daily deep recalculation and backtest after latest draw update." -Force | Out-Null

$SafetyAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`" -NoOpen" -WorkingDirectory $Root
$SafetyTrigger = New-ScheduledTaskTrigger -Daily -At "21:45"
Register-ScheduledTask -TaskName $SafetyTaskName -Action $SafetyAction -Trigger $SafetyTrigger -Settings $Settings -Description "Night safety sync without opening windows." -Force | Out-Null

Write-Host "Installed hidden auto update tasks:"
Write-Host ("1. " + $AfterDrawTaskName + ": 09:50 every 5 minutes for 65 minutes, plus 10:55 safety")
Write-Host ("2. " + $DeepTaskName + ": 13:00 deep recompute")
Write-Host ("3. " + $SafetyTaskName + ": 21:45 safety sync")
