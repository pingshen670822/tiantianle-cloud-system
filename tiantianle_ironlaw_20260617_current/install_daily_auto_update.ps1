$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "python_embed\python.exe"
if (!(Test-Path $Python)) { $Python = "python" }
$Script = Join-Path $Root "california_fantasy5_system.py"
$TaskName = "Tiantianle Ironlaw Daily Auto Update"
$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At 21:45
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Auto update Tiantianle data and prediction reports." -Force
Write-Host "Installed: $TaskName"
