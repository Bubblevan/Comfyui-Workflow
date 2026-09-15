# 从 MinimaxH3 仓库内部启动 ComfyUI

param(
    [string]$RepoRoot = '',
    [string]$PythonPath = '',
    [string]$Listen = '127.0.0.1',
    [int]$Port = 8189,
    [switch]$LowVram,
    [switch]$CpuVae
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path $PSScriptRoot -Parent }
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$comfyRoot = Join-Path $RepoRoot 'ComfyUI'
$inputDir = Join-Path $RepoRoot 'input'
$outputDir = Join-Path $RepoRoot 'output'
$tempDir = Join-Path $RepoRoot 'temp'
$logDir = Join-Path $RepoRoot 'logs'
$modelConfig = Join-Path $comfyRoot 'extra_model_paths.yaml'
foreach ($dir in @($inputDir,$outputDir,$tempDir,$logDir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
if (-not (Test-Path -LiteralPath (Join-Path $comfyRoot 'main.py'))) { throw "找不到 ComfyUI：$comfyRoot" }

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $localPython = Join-Path $RepoRoot 'runtime\python\python.exe'
    if (Test-Path -LiteralPath $localPython) { $PythonPath = $localPython }
    else { $PythonPath = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
}
if ([string]::IsNullOrWhiteSpace($PythonPath) -or -not (Test-Path -LiteralPath $PythonPath)) { throw '找不到 Python。请提供 -PythonPath，或准备 runtime\python\python.exe。' }

$sitePackages = Join-Path $RepoRoot 'runtime\venv\Lib\site-packages'
$env:PYTHONPATH = if (Test-Path -LiteralPath $sitePackages) { "$sitePackages;$comfyRoot" } else { $comfyRoot }
$args = @('main.py','--listen',$Listen,'--port',$Port,'--input-directory',$inputDir,'--output-directory',$outputDir,'--temp-directory',$tempDir,'--extra-model-paths-config',$modelConfig)
if ($LowVram) { $args += '--lowvram' }
if ($CpuVae) { $args += '--cpu-vae' }
Push-Location $comfyRoot
try { & $PythonPath @args } finally { Pop-Location }
