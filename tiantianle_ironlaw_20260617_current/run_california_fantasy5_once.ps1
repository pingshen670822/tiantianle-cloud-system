param(
  [switch]$HistoryOnly,
  [switch]$NetworkOnly,
  [switch]$ValidateOnly,
  [switch]$All,
  [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$ReportsDir = Join-Path $ScriptDir "reports"
$SiteDir = Join-Path $ScriptDir "site"
$HistoryDir = Join-Path $ScriptDir "history_import"
$CacheDir = Join-Path $ScriptDir "data\latest_cache"
New-Item -ItemType Directory -Force -Path $ReportsDir, $SiteDir, $HistoryDir, $CacheDir | Out-Null

$RunLog = Join-Path $ReportsDir "one_click_status.txt"
function Step {
  param([string]$Text)
  Write-Host $Text
  Add-Content -Path $RunLog -Encoding UTF8 -Value $Text
}

Set-Content -Path $RunLog -Encoding UTF8 -Value ("one-click start: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))

Step "Step 1/5 prepare data and latest cache"
$GrabberDirName = -join @([char]0x6293, [char]0x53D6, [char]0x5668)
$DailyGrabberDirName = -join @([char]0x5929, [char]0x5929, [char]0x6A02, [char]0x6293, [char]0x53D6, [char]0x5668)
$UserCsv = Join-Path ([Environment]::GetFolderPath("Desktop")) (Join-Path $GrabberDirName (Join-Path $DailyGrabberDirName "fantasy5_full_history.csv"))
if (Test-Path -LiteralPath $UserCsv) {
  Copy-Item -LiteralPath $UserCsv -Destination (Join-Path $HistoryDir "00_user_selected_fantasy5_full_history.csv") -Force
  Step "history csv synced"
}

$LatestPages = @(
  @{ Name = "lotto8_latest.html"; Url = 'https://www.lotto-8.com/usa/listltoFT5.asp?indexpage=1&orderby=new' },
  @{ Name = "lottolyzer_latest.html"; Url = 'https://en.lottolyzer.com/history/united-states/fantasy-5-california/' },
  @{ Name = "lotteryusa_latest.html"; Url = 'https://www.lotteryusa.com/california/fantasy-5/' },
  @{ Name = "lotterynet_latest.html"; Url = 'https://www.lottery.net/california/fantasy-5/numbers' },
  @{ Name = "lotterynet_year.html"; Url = ('https://www.lottery.net/california/fantasy-5/numbers/' + (Get-Date).Year) }
)
foreach ($Page in $LatestPages) {
  try {
    Invoke-WebRequest -Uri $Page.Url -UseBasicParsing -TimeoutSec 15 -OutFile (Join-Path $CacheDir $Page.Name)
    Step ("cache updated: " + $Page.Name)
  } catch {
    Step ("cache skipped: " + $Page.Name)
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

$RunArgs = @(".\california_fantasy5_system.py")
if ($HistoryOnly) { $RunArgs += "--history-only" }
if ($NetworkOnly) { $RunArgs += "--network-only" }
if ($ValidateOnly) { $RunArgs += "--validate-only" }
if ($All) { $RunArgs += "--all" }

Step "Step 2/5 run main system"
& $PythonExe @RunArgs
if ($LASTEXITCODE -ne 0) { throw "main system failed: $LASTEXITCODE" }

Step "Step 3/5 build mobile pages"
& $PythonExe ".\pages_build.py"
if ($LASTEXITCODE -ne 0) { throw "mobile page build failed: $LASTEXITCODE" }

Step "Step 4/5 verify outputs"
$RequiredOutputs = @(
  (Join-Path $ReportsDir "latest_analysis.json"),
  (Join-Path $ReportsDir "tiantianle_ironlaw_battle_report.html"),
  (Join-Path $ReportsDir "prediction.html"),
  (Join-Path $ReportsDir "review.html"),
  (Join-Path $SiteDir "index.html"),
  (Join-Path $SiteDir "manifest.webmanifest"),
  (Join-Path $SiteDir "service-worker.js")
)
$Missing = @($RequiredOutputs | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($Missing.Count -gt 0) {
  throw ("missing outputs: " + ($Missing -join ", "))
}
Step "outputs verified"

$PyCache = Join-Path $ScriptDir "__pycache__"
if (Test-Path -LiteralPath $PyCache) {
  Remove-Item -LiteralPath $PyCache -Recurse -Force
  Step "runtime cache cleaned"
}

Step "Step 5/5 open latest page"
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
