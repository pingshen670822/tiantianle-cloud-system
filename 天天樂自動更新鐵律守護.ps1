param(
  [switch]$NoOpen,
  [switch]$SkipUpdateRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$ReportsDir = Join-Path $Root "reports"
New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null
$LogPath = Join-Path $ReportsDir "auto_update_watchdog.log"
$StatusPath = Join-Path $ReportsDir "auto_update_watchdog_status.json"
$Installer = Join-Path $Root "install_daily_auto_update.ps1"
$AfterDrawScript = Join-Path $Root "天天樂開獎後自動更新.ps1"
$RunScript = Join-Path $Root "run_california_fantasy5_once.ps1"
$WatchdogScript = Join-Path $Root "天天樂自動更新鐵律守護.ps1"
$AnalysisPath = Join-Path $ReportsDir "latest_analysis.json"

$Checks = @(
  @{ Name = "Tiantianle Ironlaw After Draw Auto Update"; Contains = "天天樂開獎後自動更新.ps1" },
  @{ Name = "Tiantianle Ironlaw Daily Deep Review"; Contains = "run_california_fantasy5_once.ps1" },
  @{ Name = "Tiantianle Ironlaw Night Safety Sync"; Contains = "run_california_fantasy5_once.ps1" },
  @{ Name = "Tiantianle Ironlaw Auto Update Watchdog"; Contains = "天天樂自動更新鐵律守護.ps1" }
)

function Write-WatchLog {
  param([string]$Text)
  $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $Text
  Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value $line
  Write-Host $line
}

function Get-ExpectedTaiwanSafeTime {
  $now = Get-Date
  $todaySafeText = $now.ToString("yyyy-MM-dd") + " 09:50"
  $todaySafe = [datetime]::ParseExact($todaySafeText, "yyyy-MM-dd HH:mm", [Globalization.CultureInfo]::InvariantCulture)
  if ($now -lt $todaySafe) {
    return $todaySafe.AddDays(-1)
  }
  return $todaySafe
}

function Get-FieldValue {
  param($Object, [string]$Name)
  if ($null -eq $Object) {
    return $null
  }
  if ($Object.PSObject.Properties.Name -contains $Name) {
    return $Object.$Name
  }
  return $null
}

function Parse-SafeTime {
  param([string]$Text)
  if ([string]::IsNullOrWhiteSpace($Text)) {
    return $null
  }
  return [datetime]::ParseExact($Text, "yyyy-MM-dd HH:mm", [Globalization.CultureInfo]::InvariantCulture)
}

function Test-TaskHealthy {
  param([string]$Name, [string]$Needle)
  try {
    $task = Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -eq $Name } | Select-Object -First 1
  } catch {
    return $false
  }
  if ($null -eq $task) {
    return $false
  }
  if ($task.State -eq "Disabled") {
    return $false
  }
  if (-not $task.Settings.Hidden) {
    return $false
  }
  foreach ($action in @($task.Actions)) {
    if (([string]$action.Arguments).Contains($Needle)) {
      return $true
    }
  }
  return $false
}

function Get-LatestSafeTimeFromAnalysis {
  if (-not (Test-Path -LiteralPath $AnalysisPath)) {
    return $null
  }
  $analysis = Get-Content -LiteralPath $AnalysisPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $freshness = Get-FieldValue $analysis "freshness"
  $latestText = Get-FieldValue $freshness "latest_taiwan_safe_update_time"
  if ([string]::IsNullOrWhiteSpace($latestText)) {
    $latestText = Get-FieldValue $analysis "latest_draw_taiwan_update_time"
  }
  return Parse-SafeTime $latestText
}

function Save-Status {
  param($Status)
  Set-Content -LiteralPath $StatusPath -Encoding UTF8 -Value ($Status | ConvertTo-Json -Depth 20)
}

Write-WatchLog "watchdog start"
$missingOrBroken = @()
foreach ($check in $Checks) {
  $checkName = [string]$check["Name"]
  $checkNeedle = [string]$check["Contains"]
  if (-not (Test-TaskHealthy $checkName $checkNeedle)) {
    $missingOrBroken += $checkName
  }
}

$repaired = $false
if ($missingOrBroken.Count -gt 0) {
  Write-WatchLog ("repair tasks: " + ($missingOrBroken -join ", "))
  & powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $Installer
  if ($LASTEXITCODE -ne 0) {
    throw "auto update task repair failed"
  }
  $repaired = $true
}

$expected = Get-ExpectedTaiwanSafeTime
$latest = Get-LatestSafeTimeFromAnalysis
$stale = ($null -eq $latest -or $latest -lt $expected)
$updateExit = $null

if ($stale -and -not $SkipUpdateRun) {
  Write-WatchLog ("stale report detected; expected=" + $expected.ToString("yyyy-MM-dd HH:mm"))
  & powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $AfterDrawScript -MaxAttempts 3 -SleepSeconds 120 -NoOpen
  $updateExit = $LASTEXITCODE
  Write-WatchLog ("stale update exit code: " + $updateExit)
}

$latestAfter = Get-LatestSafeTimeFromAnalysis
$status = [ordered]@{
  checked_at_taiwan = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
  repaired_tasks = $repaired
  missing_or_broken_before_repair = $missingOrBroken
  expected_taiwan_safe_update_time = $expected.ToString("yyyy-MM-dd HH:mm")
  latest_taiwan_safe_update_time_before = if ($null -eq $latest) { $null } else { $latest.ToString("yyyy-MM-dd HH:mm") }
  latest_taiwan_safe_update_time_after = if ($null -eq $latestAfter) { $null } else { $latestAfter.ToString("yyyy-MM-dd HH:mm") }
  stale_before_update = $stale
  update_exit_code = $updateExit
}
Save-Status $status
Write-WatchLog "watchdog done"

