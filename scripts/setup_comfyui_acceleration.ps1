# Rebuild the Windows acceleration layer used by the canonical H3 graph.

param(
    [string]$RepoRoot = '',
    [switch]$SkipAgsoft,
    [switch]$SkipExperimentalH3Nodes
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path $PSScriptRoot -Parent }
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$venvPython = Join-Path $RepoRoot 'runtime\venv\Scripts\python.exe'
$requirements = Join-Path $RepoRoot 'requirements-comfyui-acceleration.txt'
$customNodes = Join-Path $RepoRoot 'ComfyUI\custom_nodes'
$kjPath = Join-Path $customNodes 'ComfyUI-KJNodes'
$agsoftPath = Join-Path $customNodes 'comfyui-AGSoft'
$kjRevision = 'd3cfe21625e5170126ce06fbfcfe1d88108688c3'
$agsoftRevision = '4d508dff4410ac1ae561d1527217cdbda742eb38'
$teaPath = Join-Path $customNodes 'ComfyUI-MiniMaxH3-TeaCache'
$teaRevision = '4cbb50d69c73a19a5d6ec42c5aec1989d5a04b6f'
$spectrumPath = Join-Path $customNodes 'ComfyUI-Spectrum-MiniMax-H3'
$spectrumRevision = '120d72e2f48b781235b34149e39bbdf0f1317d82'
$speedPath = Join-Path $customNodes 'comfyui-speed-minimaxH3'
$speedRevision = '2f507d687cd6767212ae003d272042bf886a3cd3'
$fastPath = Join-Path $customNodes 'ComfyUI-MiniMax-H3-FastPath'
$fastRevision = '23575c19bf85e541fd1d3dbbbee86e3bf5a55722'

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "找不到目标 ComfyUI Python：$venvPython"
}
if (-not (Test-Path -LiteralPath $requirements)) {
    throw "找不到加速依赖清单：$requirements"
}
New-Item -ItemType Directory -Force -Path $customNodes | Out-Null

& $venvPython -m pip install --upgrade -r $requirements

function Ensure-RepositoryRevision([string]$Path, [string]$Url, [string]$Revision) {
    if (-not (Test-Path -LiteralPath $Path)) {
        git clone --no-checkout $Url $Path
    }
    git -C $Path fetch --depth 1 origin $Revision
    git -C $Path checkout --detach $Revision
}

Ensure-RepositoryRevision $kjPath 'https://github.com/kijai/ComfyUI-KJNodes.git' $kjRevision
if (Test-Path -LiteralPath (Join-Path $kjPath 'requirements.txt')) {
    & $venvPython -m pip install -r (Join-Path $kjPath 'requirements.txt')
}

if (-not $SkipAgsoft) {
    Ensure-RepositoryRevision $agsoftPath 'https://github.com/Art-xmaster/comfyui-AGSoft.git' $agsoftRevision
    if (Test-Path -LiteralPath (Join-Path $agsoftPath 'requirements.txt')) {
        & $venvPython -m pip install -r (Join-Path $agsoftPath 'requirements.txt')
    }
}

if (-not $SkipExperimentalH3Nodes) {
    Ensure-RepositoryRevision $teaPath 'https://github.com/Icyoung/ComfyUI-MiniMaxH3-TeaCache.git' $teaRevision
    Ensure-RepositoryRevision $spectrumPath 'https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3.git' $spectrumRevision
    Ensure-RepositoryRevision $speedPath 'https://github.com/linjian-ufo/comfyui-speed-minimaxH3.git' $speedRevision
    Ensure-RepositoryRevision $fastPath 'https://github.com/capitan01R/ComfyUI-MiniMax-H3-FastPath.git' $fastRevision
}

& $venvPython -m pip check
Write-Output 'ComfyUI acceleration environment is ready.'
