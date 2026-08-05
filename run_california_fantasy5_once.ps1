param(
  [switch]$HistoryOnly,
  [switch]$NetworkOnly,
  [switch]$ValidateOnly,
  [switch]$All,
  [switch]$ForceRun,
  [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if ($All) {
  $env:TIANTIANLE_CORE_BACKTEST_ROUNDS = "720"
  $env:TIANTIANLE_INDUSTRIAL_BACKTEST_ROUNDS = "720"
  $env:TIANTIANLE_ADVANCED_BACKTEST_ROUNDS = "360"
  $env:TIANTIANLE_UNLIKELY_BACKTEST_ROUNDS = "360"
  $env:TIANTIANLE_FORMULA_BACKTEST_ROUNDS = "360"
  $env:TIANTIANLE_PACK_GOVERNANCE_ROUNDS = "720"
  $env:TIANTIANLE_PRECISION_TOURNAMENT_ROUNDS = "180"
  $env:TIANTIANLE_GROUP_BACKTEST_SHORT = "60"
  $env:TIANTIANLE_GROUP_BACKTEST_MID = "120"
  $env:TIANTIANLE_GROUP_BACKTEST_LONG = "720"
  $env:TIANTIANLE_RUN_MODE = "deep"
} else {
  $env:TIANTIANLE_CORE_BACKTEST_ROUNDS = "360"
  $env:TIANTIANLE_INDUSTRIAL_BACKTEST_ROUNDS = "360"
  $env:TIANTIANLE_ADVANCED_BACKTEST_ROUNDS = "180"
  $env:TIANTIANLE_UNLIKELY_BACKTEST_ROUNDS = "180"
  $env:TIANTIANLE_FORMULA_BACKTEST_ROUNDS = "240"
  $env:TIANTIANLE_PACK_GOVERNANCE_ROUNDS = "360"
  $env:TIANTIANLE_PRECISION_TOURNAMENT_ROUNDS = "180"
  $env:TIANTIANLE_GROUP_BACKTEST_SHORT = "60"
  $env:TIANTIANLE_GROUP_BACKTEST_MID = "120"
  $env:TIANTIANLE_GROUP_BACKTEST_LONG = "360"
  $env:TIANTIANLE_RUN_MODE = "standard"
}

$ReportsDir = Join-Path $ScriptDir "reports"
$SiteDir = Join-Path $ScriptDir "site"
$env:PYTHONFAULTHANDLER = "1"
$HistoryDir = Join-Path $ScriptDir "history_import"
$CacheDir = Join-Path $ScriptDir "data\latest_cache"
New-Item -ItemType Directory -Force -Path $ReportsDir, $SiteDir, $HistoryDir, $CacheDir | Out-Null

$RunLog = Join-Path $ReportsDir "one_click_status.txt"
function Step {
  param([string]$Text)
  Write-Host $Text
  Add-Content -Path $RunLog -Encoding UTF8 -Value $Text
}

function Test-FastRefreshAllowed {
  if ($HistoryOnly -or $NetworkOnly -or $ValidateOnly -or $All -or $ForceRun) {
    return $false
  }
  $AnalysisPath = Join-Path $ReportsDir "latest_analysis.json"
  if (-not (Test-Path -LiteralPath $AnalysisPath)) {
    return $false
  }
  try {
    $Analysis = Get-Content -LiteralPath $AnalysisPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $TargetText = [string]$Analysis.freshness.target_taiwan_safe_update_time
    if ([string]::IsNullOrWhiteSpace($TargetText)) {
      return $false
    }
    $TargetTime = [datetime]::ParseExact($TargetText, "yyyy-MM-dd HH:mm", [Globalization.CultureInfo]::InvariantCulture)
    return ((Get-Date) -lt $TargetTime)
  } catch {
    return $false
  }
}

Set-Content -Path $RunLog -Encoding UTF8 -Value ("one-click start: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))

$FastRefresh = Test-FastRefreshAllowed
if ($FastRefresh) {
  Step "Fast refresh: before Taiwan safe update time; skip network fetch and full model recompute"
} elseif ($ForceRun) {
  Step "Force run: bypass freshness skip and recompute full model"
}

Step "Step 1/8 prepare data and latest cache"
$GrabberDirName = -join @([char]0x6293, [char]0x53D6, [char]0x5668)
$DailyGrabberDirName = -join @([char]0x5929, [char]0x5929, [char]0x6A02, [char]0x6293, [char]0x53D6, [char]0x5668)
$UserCsv = Join-Path ([Environment]::GetFolderPath("Desktop")) (Join-Path $GrabberDirName (Join-Path $DailyGrabberDirName "fantasy5_full_history.csv"))
if (Test-Path -LiteralPath $UserCsv) {
  Copy-Item -LiteralPath $UserCsv -Destination (Join-Path $HistoryDir "00_user_selected_fantasy5_full_history.csv") -Force
  Step "history csv synced"
}

if (-not $FastRefresh) {
  $NoCacheStamp = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
  $FetchHeaders = @{
    "Cache-Control" = "no-cache"
    "Pragma" = "no-cache"
    "User-Agent" = "Mozilla/5.0 TiantianleIronlaw/20260805"
  }
  $LatestPages = @(
    @{ Name = "calottery_official.html"; Url = 'https://www.calottery.com/en/draw-games/fantasy-5' },
    @{ Name = "lotto8_latest.html"; Url = 'https://www.lotto-8.com/usa/listltoFT5.asp?indexpage=1&orderby=new' },
    @{ Name = "lottolyzer_latest.html"; Url = 'https://en.lottolyzer.com/history/united-states/fantasy-5-california/' },
    @{ Name = "lotteryusa_latest.html"; Url = 'https://www.lotteryusa.com/california/fantasy-5/' },
    @{ Name = "lotterynet_latest.html"; Url = 'https://www.lottery.net/california/fantasy-5/numbers' },
    @{ Name = "lotterynet_year.html"; Url = ('https://www.lottery.net/california/fantasy-5/numbers/' + (Get-Date).Year) }
  )
  foreach ($Page in $LatestPages) {
    $OutFile = Join-Path $CacheDir $Page.Name
    $TempFile = $OutFile + ".tmp"
    $PageUrl = $Page.Url
    if ($PageUrl.Contains("?")) {
      $PageUrl = $PageUrl + "&tiantianle_nocache=" + $NoCacheStamp
    } else {
      $PageUrl = $PageUrl + "?tiantianle_nocache=" + $NoCacheStamp
    }
    $Fetched = $false
    try {
      for ($FetchAttempt = 1; $FetchAttempt -le 3; $FetchAttempt++) {
        try {
          if (Test-Path -LiteralPath $TempFile) {
            Remove-Item -LiteralPath $TempFile -Force
          }
          Invoke-WebRequest -Uri $PageUrl -Headers $FetchHeaders -UseBasicParsing -TimeoutSec 45 -OutFile $TempFile
          $TempItem = Get-Item -LiteralPath $TempFile -Force
          if ($TempItem.Length -lt 500) {
            throw "download too small"
          }
          Move-Item -LiteralPath $TempFile -Destination $OutFile -Force
          Step ("cache updated: " + $Page.Name)
          $Fetched = $true
          break
        } catch {
          if ($FetchAttempt -ge 3) {
            throw
          }
          Start-Sleep -Seconds (3 * $FetchAttempt)
        }
      }
    } catch {
      if (Test-Path -LiteralPath $TempFile) {
        Remove-Item -LiteralPath $TempFile -Force
      }
      Step ("cache failed: " + $Page.Name + " / " + $_.Exception.Message)
    }
    if (-not $Fetched -and -not (Test-Path -LiteralPath $OutFile)) {
      Step ("cache unavailable: " + $Page.Name)
    }
  }
}

$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path -LiteralPath $BundledPython) {
  $PythonExe = $BundledPython
} else {
  $PythonCmd = Get-Command "python" -ErrorAction SilentlyContinue
  if (-not $PythonCmd) {
    throw "Python executable was not found."
  }
  $PythonExe = $PythonCmd.Source
}

$MainScriptName = -join @([char]0x7F8E, [char]0x570B, [char]0x52A0, [char]0x5DDE, [char]0x5929, [char]0x5929, [char]0x6A02, "_20260618_", [char]0x7B2C, "1", [char]0x7248, ".py")
$RunArgs = @((Join-Path "." $MainScriptName))
if ($HistoryOnly) { $RunArgs += "--history-only" }
if ($NetworkOnly) { $RunArgs += "--network-only" }
if ($ValidateOnly) { $RunArgs += "--validate-only" }
if ($All) { $RunArgs += "--all" }

Step "Step 2/8 run main system"
if ($FastRefresh) {
  Step "main system skipped: existing prediction is still current before safe update time"
} else {
  $MainExitCode = 1
  for ($Attempt = 1; $Attempt -le 2; $Attempt++) {
    & $PythonExe "-X" "faulthandler" @RunArgs
    $MainExitCode = $LASTEXITCODE
    if ($MainExitCode -eq 0) { break }
    Step ("main system retry " + $Attempt + "/2 after exit " + $MainExitCode)
    Start-Sleep -Seconds 3
  }
  if ($MainExitCode -ne 0) { throw "main system failed after retry: $MainExitCode" }
}

Step "Step 3/8 build mobile pages"
& $PythonExe ".\pages_build.py"
if ($LASTEXITCODE -ne 0) { throw "mobile page build failed: $LASTEXITCODE" }

Step "Step 3.5/8 clean stale legacy artifacts before audit"
$PreAuditCloudSnapshots = @(Get-ChildItem -LiteralPath $ScriptDir -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "cloud_*" })
if ($PreAuditCloudSnapshots.Count -gt 0) {
  foreach ($Snapshot in $PreAuditCloudSnapshots) {
    Remove-Item -LiteralPath $Snapshot.FullName -Force
  }
  Step ("stale root cloud snapshots cleaned before audit: " + $PreAuditCloudSnapshots.Count)
}
$PreAuditLegacyEmptyDb = Join-Path $ScriptDir "data\california_fantasy5.db"
if (Test-Path -LiteralPath $PreAuditLegacyEmptyDb) {
  $PreAuditLegacyEmptyDbItem = Get-Item -LiteralPath $PreAuditLegacyEmptyDb -Force
  if ($PreAuditLegacyEmptyDbItem.Length -eq 0) {
    Remove-Item -LiteralPath $PreAuditLegacyEmptyDb -Force
    Step "empty legacy database cleaned before audit"
  }
}

Step "Step 4/8 sanitize and audit system gaps"
$SanitizeScript = Join-Path $ScriptDir "sanitize_public_outputs.py"
if (Test-Path -LiteralPath $SanitizeScript) {
  & $PythonExe $SanitizeScript
  if ($LASTEXITCODE -ne 0) { throw "public output sanitize failed: $LASTEXITCODE" }
}
$GapAuditScript = Join-Path $ScriptDir "system_gap_audit.py"
if (-not (Test-Path -LiteralPath $GapAuditScript)) {
  throw "system gap audit script missing"
}
& $PythonExe $GapAuditScript "--fail-on-publish-blocking" "--local-only"
if ($LASTEXITCODE -ne 0) { throw "system gap audit failed: $LASTEXITCODE" }

Step "Step 5/8 verify outputs"
$RequiredOutputs = @(
  (Join-Path $ReportsDir "latest_analysis.json"),
  (Join-Path $ReportsDir "tiantianle_ironlaw_battle_report.html"),
  (Join-Path $ReportsDir "complete_report.html"),
  (Join-Path $ReportsDir "prediction.html"),
  (Join-Path $ReportsDir "review.html"),
  (Join-Path $ReportsDir "tiantianle_low_probability_avoid.html"),
  (Join-Path $ReportsDir "天天樂低機率精準暫避.html"),
  (Join-Path $ReportsDir "system_gap_audit.md"),
  (Join-Path $SiteDir "index.html"),
  (Join-Path $SiteDir "latest_analysis.json"),
  (Join-Path $SiteDir "complete_report.html"),
  (Join-Path $SiteDir "manifest.webmanifest"),
  (Join-Path $SiteDir "service-worker.js"),
  (Join-Path $SiteDir "system_gap_audit.md"),
  (Join-Path $SiteDir "reports\latest_analysis.json"),
  (Join-Path $SiteDir "reports\complete_report.html"),
  (Join-Path $SiteDir "reports\tiantianle_low_probability_avoid.html"),
  (Join-Path $SiteDir "reports\system_gap_audit.md")
)
$Missing = @($RequiredOutputs | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($Missing.Count -gt 0) {
  throw ("missing outputs: " + ($Missing -join ", "))
}
Step "outputs verified"

$StaleCloudSnapshots = @(Get-ChildItem -LiteralPath $ScriptDir -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "cloud_*" })
if ($StaleCloudSnapshots.Count -gt 0) {
  foreach ($Snapshot in $StaleCloudSnapshots) {
    Remove-Item -LiteralPath $Snapshot.FullName -Force
  }
  Step ("stale root cloud snapshots cleaned: " + $StaleCloudSnapshots.Count)
}

$LegacyEmptyDb = Join-Path $ScriptDir "data\california_fantasy5.db"
if (Test-Path -LiteralPath $LegacyEmptyDb) {
  $LegacyEmptyDbItem = Get-Item -LiteralPath $LegacyEmptyDb -Force
  if ($LegacyEmptyDbItem.Length -eq 0) {
    Remove-Item -LiteralPath $LegacyEmptyDb -Force
    Step "empty legacy database cleaned"
  }
}

$PyCache = Join-Path $ScriptDir "__pycache__"
if (Test-Path -LiteralPath $PyCache) {
  Remove-Item -LiteralPath $PyCache -Recurse -Force
  Step "runtime cache cleaned"
}

Step "Step 6/8 publish mobile cloud"
$CloudPublishSucceeded = $false
$CloudPublishStatusPath = Join-Path $ReportsDir "cloud_publish_status.json"
if ($HistoryOnly -or $NetworkOnly -or $ValidateOnly) {
  Step "cloud publish skipped for diagnostic-only mode"
} else {
  $PublishScript = Join-Path $ScriptDir "publish_mobile_site_only.py"
  if (-not (Test-Path -LiteralPath $PublishScript)) {
    throw "cloud publish script missing"
  }
  $PublishExitCode = 1
  for ($Attempt = 1; $Attempt -le 3; $Attempt++) {
    $PublishOut = Join-Path $ReportsDir ("cloud_publish_stdout_attempt_" + $Attempt + ".log")
    $PublishErr = Join-Path $ReportsDir ("cloud_publish_stderr_attempt_" + $Attempt + ".log")
    $Process = Start-Process -FilePath $PythonExe -ArgumentList @($PublishScript) -WorkingDirectory $ScriptDir -WindowStyle Hidden -PassThru -RedirectStandardOutput $PublishOut -RedirectStandardError $PublishErr
    if (-not $Process.WaitForExit(420000)) {
      Stop-Process -Id $Process.Id -Force
      $PublishExitCode = 124
      Step ("cloud publish timeout on attempt " + $Attempt)
    } else {
      $Process.Refresh()
      if ($null -eq $Process.ExitCode) {
        $PublishExitCode = 0
      } else {
        $PublishExitCode = [int]$Process.ExitCode
      }
    }
    if (Test-Path -LiteralPath $PublishOut) {
      Get-Content -LiteralPath $PublishOut -Encoding UTF8 -ErrorAction SilentlyContinue | Select-Object -Last 6 | ForEach-Object { Step ("cloud publish: " + $_) }
    }
    if (Test-Path -LiteralPath $PublishErr) {
      Get-Content -LiteralPath $PublishErr -Encoding UTF8 -ErrorAction SilentlyContinue | Select-Object -Last 6 | ForEach-Object { Step ("cloud publish error: " + $_) }
    }
    if ($PublishExitCode -eq 0) { break }
    Step ("cloud publish retry " + $Attempt + "/3 after exit " + $PublishExitCode)
    Start-Sleep -Seconds (5 * $Attempt)
  }
  if ($PublishExitCode -ne 0) {
    Step ("cloud publish failed after retry, local reports kept: " + $PublishExitCode)
    Set-Content -LiteralPath $CloudPublishStatusPath -Encoding UTF8 -Value (@{
      checked_at_taiwan = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
      status = "cloud_publish_failed_local_reports_kept"
      exit_code = $PublishExitCode
      action = "本機開獎、戰報、下期預測已完成；手機雲端等待下一次排程或權杖修復後同步。"
    } | ConvertTo-Json -Depth 5)
  } else {
    $CloudPublishSucceeded = $true
    Set-Content -LiteralPath $CloudPublishStatusPath -Encoding UTF8 -Value (@{
      checked_at_taiwan = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
      status = "cloud_published"
      exit_code = 0
    } | ConvertTo-Json -Depth 5)
    Step "cloud mobile site published"
  }
}

Step "Step 7/8 verify mobile sync"
$SyncVerifyScript = Join-Path $ScriptDir "verify_mobile_sync.py"
if (-not (Test-Path -LiteralPath $SyncVerifyScript)) {
  throw "mobile sync verify script missing"
}
if ($HistoryOnly -or $NetworkOnly -or $ValidateOnly) {
  & $PythonExe $SyncVerifyScript "--local-only"
} elseif ($CloudPublishSucceeded) {
  & $PythonExe $SyncVerifyScript "--remote" "--retries" "10" "--sleep" "6"
} else {
  Step "remote sync verify skipped because cloud publish failed; running local sync check"
  & $PythonExe $SyncVerifyScript "--local-only"
}
if ($LASTEXITCODE -ne 0) { throw "mobile sync verify failed: $LASTEXITCODE" }

Step "Step 8/8 open latest page"
if (-not $NoOpen) {
  if ($ValidateOnly) {
    Start-Process (Join-Path $ReportsDir "source_validation_report.md")
  } elseif ($NetworkOnly) {
    Start-Process (Join-Path $ReportsDir "network_diagnostic_report.md")
  } elseif ($HistoryOnly) {
    Start-Process (Join-Path $ReportsDir "history_scraper_report.md")
  } else {
    Start-Process (Join-Path $SiteDir "index.html")
  }
}

Step ("one-click complete: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
