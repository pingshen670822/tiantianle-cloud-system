$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ScriptDir
$ReportsDir = Join-Path $ScriptDir "reports"
New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null
$LogPath = Join-Path $ReportsDir "hidden_mobile_publish.log"
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path -LiteralPath $BundledPython) {
  $PythonExe = $BundledPython
} else {
  $PythonExe = (Get-Command python -ErrorAction Stop).Source
}
Set-Content -LiteralPath $LogPath -Encoding UTF8 -Value ("hidden mobile publish start: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
try {
  & $PythonExe ".\publish_mobile_site_only.py" 2>&1 | ForEach-Object { Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ([string]$_) }
  $ExitCode = $LASTEXITCODE
  Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ("hidden mobile publish exit code: " + $ExitCode)
  if ($ExitCode -ne 0) { throw "hidden mobile publish failed: $ExitCode" }
  Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ("hidden mobile publish complete: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
} catch {
  Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ("hidden mobile publish failed: " + $_.Exception.Message)
  if ($_.ScriptStackTrace) { Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value $_.ScriptStackTrace }
  throw
}
