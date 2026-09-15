# DEPRECATED compatibility wrapper for the original nun command.
param(
    [long]$Seed = 734112,
    [string]$ApiUrl = 'http://127.0.0.1:8189',
    [int]$Steps = 8
)
$ErrorActionPreference = 'Stop'
Write-Warning 'run_ref2va_nun.ps1 is deprecated; use h3.ps1 with a shot manifest.'
$profile = if ($Steps -le 4) { 'explore' } else { 'keep' }
& (Join-Path $PSScriptRoot 'h3.ps1') run 'shots\nun\shot01_idle.yaml' --seed $Seed --profile $profile --api-url $ApiUrl
exit $LASTEXITCODE
