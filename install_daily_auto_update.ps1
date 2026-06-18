$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "python_embed\python.exe"
if (!(Test-Path $Python)) { $Python = "python" }
$MainScriptName = -join @([char]0x7F8E, [char]0x570B, [char]0x52A0, [char]0x5DDE, [char]0x5929, [char]0x5929, [char]0x6A02, "_20260618_", [char]0x7B2C, "1", [char]0x7248, ".py")
$Script = Join-Path $Root $MainScriptName
$TaskName = "Tiantianle Ironlaw Daily Auto Update"
$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At 21:45
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Auto update Tiantianle data and prediction reports." -Force
Write-Host "Installed: $TaskName"
