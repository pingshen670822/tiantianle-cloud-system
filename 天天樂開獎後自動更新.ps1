param([switch]$NoOpen)
& (Join-Path $PSScriptRoot 'run_california_fantasy5_once.ps1') -NoOpen:$NoOpen
if (-not $?) { exit 1 }
