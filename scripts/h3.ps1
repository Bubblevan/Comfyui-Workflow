param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$runtimePython = Join-Path $repoRoot 'runtime\python\python.exe'
$python = if (Test-Path -LiteralPath $runtimePython) { $runtimePython } else { (Get-Command python.exe -ErrorAction Stop).Source }
& $python (Join-Path $PSScriptRoot 'h3.py') @CommandArgs
exit $LASTEXITCODE
