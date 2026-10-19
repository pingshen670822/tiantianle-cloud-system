param([switch]$NoOpen)
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
& python (Join-Path $PSScriptRoot 'cloud_update_request.py')
if ($LASTEXITCODE -ne 0) { throw 'Cloud update request failed; previous report preserved.' }
