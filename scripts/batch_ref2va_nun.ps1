# DEPRECATED compatibility wrapper for the original nun batch command.
param(
    [int]$Count = 4,
    [long]$StartSeed = 734112,
    [string]$ApiUrl = 'http://127.0.0.1:8189'
)
$ErrorActionPreference = 'Stop'
Write-Warning 'batch_ref2va_nun.ps1 is deprecated; use h3.ps1 explore with a shot manifest.'
& (Join-Path $PSScriptRoot 'h3.ps1') explore 'shots\nun\shot01_idle.yaml' --count $Count --start-seed $StartSeed --api-url $ApiUrl
exit $LASTEXITCODE
