# Rebuild the Windows acceleration layer used by the canonical H3 graph.

param(
    [string]$RepoRoot = '',
    [switch]$SkipAgsoft
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

& $venvPython -m pip check
Write-Output 'ComfyUI acceleration environment is ready.'
