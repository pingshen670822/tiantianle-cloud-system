param([switch]$NoOpen, [switch]$All, [switch]$ForceRun)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONUTF8 = '1'
Push-Location -LiteralPath $Root
try {
    $Mode = if ($All) { 'deep' } else { 'realtime' }
    & python (Join-Path $Root 'system_update.py') --mode $Mode
    if ($LASTEXITCODE -ne 0) { throw "System update failed: $LASTEXITCODE" }
    if (-not $NoOpen) { Start-Process (Join-Path $Root 'site\index.html') }
} finally { Pop-Location }
