param([switch]$NoOpen, [switch]$All)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONUTF8 = '1'
Push-Location -LiteralPath $Root
try {
    & python (Join-Path $Root 'system_update.py')
    if ($LASTEXITCODE -ne 0) { throw "System update failed: $LASTEXITCODE" }
    if (-not $NoOpen) { Start-Process (Join-Path $Root 'site\index.html') }
} finally { Pop-Location }
