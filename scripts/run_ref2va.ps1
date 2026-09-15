# DEPRECATED compatibility wrapper. Use: .\scripts\h3.ps1 run <shot.yaml> --seed <seed> --profile keep
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs)
$ErrorActionPreference = 'Stop'
Write-Warning 'run_ref2va.ps1 is deprecated; dispatching to h3.ps1.'
& (Join-Path $PSScriptRoot 'h3.ps1') @CommandArgs
exit $LASTEXITCODE
