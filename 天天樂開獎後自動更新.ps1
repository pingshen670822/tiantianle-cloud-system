param(
  [int]$MaxAttempts = 12,
  [int]$SleepSeconds = 180,
  [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ScriptDir

$ReportsDir = Join-Path $ScriptDir "reports"
New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null
$LogPath = Join-Path $ReportsDir "after_draw_auto_update.log"
$StatusPath = Join-Path $ReportsDir "after_draw_auto_update_status.json"
$ArchivePath = Join-Path $ReportsDir "daily_prediction_review_archive.jsonl"
$RunScript = Join-Path $ScriptDir "run_california_fantasy5_once.ps1"
$AnalysisPath = Join-Path $ReportsDir "latest_analysis.json"

function Write-RunLog {
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

function Read-Analysis {
  if (-not (Test-Path -LiteralPath $AnalysisPath)) {
    throw "latest_analysis.json missing"
  }
  return Get-Content -LiteralPath $AnalysisPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Parse-SafeTime {
  param([string]$Text)
  if ([string]::IsNullOrWhiteSpace($Text)) {
    return $null
  }
  return [datetime]::ParseExact($Text, "yyyy-MM-dd HH:mm", [Globalization.CultureInfo]::InvariantCulture)
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

function Save-Archive {
  param($Analysis, [datetime]$ExpectedTime)

  $freshness = Get-FieldValue $Analysis "freshness"
  $prediction = Get-FieldValue $Analysis "prediction"
  $review = Get-FieldValue $Analysis "failure_review"
  $settled = Get-FieldValue $review "last_settled"
  $latest = Get-FieldValue $Analysis "latest_draw"
  $recalc = Get-FieldValue $Analysis "recalculation_manifest"
  $actualNumbers = @(Get-FieldValue $settled "actual_numbers")
  $candidateNumbers = @(Get-FieldValue $settled "candidate_numbers")
  $top9Hits = Get-FieldValue $settled "top9_hits"
  if ($null -eq $top9Hits -and $actualNumbers.Count -gt 0 -and $candidateNumbers.Count -gt 0) {
    $top9Hits = @($candidateNumbers | Select-Object -First 9 | Where-Object { $actualNumbers -contains $_ }).Count
  }
  $top9HitNumbers = @()
  if ($actualNumbers.Count -gt 0 -and $candidateNumbers.Count -gt 0) {
    $top9HitNumbers = @($candidateNumbers | Select-Object -First 9 | Where-Object { $actualNumbers -contains $_ })
  }

  $record = [ordered]@{
    archived_at_taiwan = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
    expected_taiwan_safe_update_time = $ExpectedTime.ToString("yyyy-MM-dd HH:mm")
    latest_draw_date = Get-FieldValue $latest "draw_date"
    latest_numbers = Get-FieldValue $latest "numbers"
    latest_taiwan_safe_update_time = Get-FieldValue $freshness "latest_taiwan_safe_update_time"
    next_target_draw_date = Get-FieldValue $Analysis "target_draw_date"
    next_target_taiwan_time = Get-FieldValue $freshness "target_taiwan_safe_update_time"
    next_top9 = Get-FieldValue $prediction "top9"
    last_review_actual_date = Get-FieldValue $settled "actual_date"
    last_review_based_on_date = Get-FieldValue $settled "based_on_date"
    last_review_top5_hits = Get-FieldValue $settled "top5_hits"
    last_review_top9_hits = $top9Hits
    last_review_top10_hits = Get-FieldValue $settled "top10_hits"
    last_review_top15_hits = Get-FieldValue $settled "top15_hits"
    last_review_top9_hit_numbers = $top9HitNumbers
    last_review_actual_numbers = Get-FieldValue $settled "actual_numbers"
    recalculation_status = Get-FieldValue $recalc "status"
    every_draw_recomputed = Get-FieldValue $recalc "every_draw_recomputed"
    previous_prediction_reused = Get-FieldValue $recalc "previous_prediction_reused"
    backtest_recomputed = Get-FieldValue $recalc "backtest_recomputed"
    review_recomputed = Get-FieldValue $recalc "review_recomputed"
  }

  $json = $record | ConvertTo-Json -Compress -Depth 30
  Add-Content -LiteralPath $ArchivePath -Encoding UTF8 -Value $json
  Set-Content -LiteralPath $StatusPath -Encoding UTF8 -Value ($record | ConvertTo-Json -Depth 30)
}

function Test-UpdateComplete {
  param($Analysis, [datetime]$ExpectedTime)

  $freshness = Get-FieldValue $Analysis "freshness"
  $latest = Get-FieldValue $Analysis "latest_draw"
  $review = Get-FieldValue $Analysis "failure_review"
  $settled = Get-FieldValue $review "last_settled"
  $recalc = Get-FieldValue $Analysis "recalculation_manifest"
  $latestText = Get-FieldValue $freshness "latest_taiwan_safe_update_time"
  if ([string]::IsNullOrWhiteSpace($latestText)) {
    $latestText = Get-FieldValue $Analysis "latest_draw_taiwan_update_time"
  }
  $targetText = Get-FieldValue $freshness "target_taiwan_safe_update_time"
  if ([string]::IsNullOrWhiteSpace($targetText)) {
    $targetText = Get-FieldValue $Analysis "prediction_draw_taiwan_time"
  }
  $latestTime = Parse-SafeTime $latestText
  $targetTime = Parse-SafeTime $targetText
  $latestDrawDate = [string](Get-FieldValue $latest "draw_date")
  $settledActualDate = [string](Get-FieldValue $settled "actual_date")

  $freshOk = ($null -ne $latestTime -and $latestTime -ge $ExpectedTime)
  $nextOk = ($null -ne $targetTime -and $null -ne $latestTime -and $targetTime -gt $latestTime)
  $reviewOk = (-not [string]::IsNullOrWhiteSpace($settledActualDate) -and $settledActualDate -eq $latestDrawDate)
  $recalcOk = [bool](Get-FieldValue $recalc "every_draw_recomputed") -and
              [bool](Get-FieldValue $recalc "backtest_recomputed") -and
              [bool](Get-FieldValue $recalc "review_recomputed") -and
              (-not [bool](Get-FieldValue $recalc "previous_prediction_reused"))

  return [ordered]@{
    complete = ($freshOk -and $nextOk -and $reviewOk -and $recalcOk)
    fresh_ok = $freshOk
    next_prediction_ok = $nextOk
    review_saved_ok = $reviewOk
    recalculation_ok = $recalcOk
    latest_taiwan_safe_update_time = $latestText
    target_taiwan_safe_update_time = $targetText
    latest_draw_date = $latestDrawDate
    settled_actual_date = $settledActualDate
  }
}

Set-Content -LiteralPath $LogPath -Encoding UTF8 -Value ("after draw auto update start: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
$expected = Get-ExpectedTaiwanSafeTime
Write-RunLog ("expected latest Taiwan safe update time: " + $expected.ToString("yyyy-MM-dd HH:mm"))

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
  Write-RunLog ("attempt " + $attempt + "/" + $MaxAttempts + " run update, settle review, recompute next prediction")
  & powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $RunScript -ForceRun -NoOpen
  $exit = $LASTEXITCODE
  Write-RunLog ("main update exit code: " + $exit)
  if ($exit -ne 0) {
    if ($attempt -lt $MaxAttempts) {
      Start-Sleep -Seconds $SleepSeconds
      continue
    }
    throw "main update failed after attempts: $exit"
  }

  $analysis = Read-Analysis
  $status = Test-UpdateComplete $analysis $expected
  Set-Content -LiteralPath $StatusPath -Encoding UTF8 -Value ($status | ConvertTo-Json -Depth 20)
  Write-RunLog ("status fresh=" + $status.fresh_ok + " next=" + $status.next_prediction_ok + " review=" + $status.review_saved_ok + " recalculation=" + $status.recalculation_ok + " latest=" + $status.latest_taiwan_safe_update_time + " target=" + $status.target_taiwan_safe_update_time)

  if ($status.complete) {
    Save-Archive $analysis $expected
    Write-RunLog "after draw update complete and archived"
    exit 0
  }

  if ($attempt -lt $MaxAttempts) {
    Write-RunLog ("not complete yet; sleep " + $SleepSeconds + " seconds")
    Start-Sleep -Seconds $SleepSeconds
  }
}

throw "after draw update did not reach required fresh/review/recompute state"
