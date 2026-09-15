# 批量提交同一镜头的多个种子，用于快速挑选动作候选

param(
    [int]$Count = 4,
    [long]$StartSeed = 734112,
    [double]$Megapixels = 0.5,
    [double]$Duration = 5.0,
    [int]$Steps = 4,
    [string]$ShotName = 'shot01',
    [string]$ActionText = 'The character starts in a calm standing pose, blinks once, makes a small controlled head turn, lightly adjusts the edge of her collar, then lowers her hand and holds a composed standing pose until the end.'
)

$ErrorActionPreference = 'Stop'
$single = Join-Path $PSScriptRoot 'run_ref2va_nun.ps1'
if (-not (Test-Path -LiteralPath $single)) {
    throw "找不到单镜头脚本：$single"
}

for ($i = 1; $i -le $Count; $i++) {
    $seed = $StartSeed + $i - 1
    $prefix = 'video/nun_{0}_take{1:D2}' -f $ShotName, $i
    Write-Host ("提交 take {0}/{1}，seed={2}" -f $i, $Count, $seed)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $single `
        -Megapixels $Megapixels `
        -Duration $Duration `
        -Steps $Steps `
        -Seed $seed `
        -Prefix $prefix `
        -ActionText $ActionText
    if ($LASTEXITCODE -ne 0) {
        throw "第 $i 个 take 提交失败。"
    }
    Start-Sleep -Milliseconds 500
}

Write-Host '全部任务已提交，ComfyUI 会按队列顺序执行。'
