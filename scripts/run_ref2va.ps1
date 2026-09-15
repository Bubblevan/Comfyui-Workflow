# 通用 MiniMax H3 Ref2VA 提交脚本

param(
    [string]$RepoRoot = '',
    [string]$ApiUrl = 'http://127.0.0.1:8189',
    [string]$ReferenceDirectory = '',
    [string]$WorkflowPath = '',
    [string]$PrimaryImage = 'nun_primary.png',
    [string]$AlternateImage = 'nun_alternate.png',
    [string]$FaceImage = 'nun_face.png',
    [string[]]$ExtraImages = @(),
    [string]$PromptFile = '',
    [string]$ActionText = 'The character remains in a calm standing pose, blinks once, makes a small controlled head turn, lightly adjusts the edge of her collar, then returns to a composed pose.',
    [string]$CameraText = 'The camera is locked-off with only a very subtle slow push-in. Keep the face and upper body clearly visible.',
    [ValidateRange(4,15)][double]$Duration = 5.0,
    [ValidateRange(0.1,2.0)][double]$Megapixels = 0.5,
    [ValidateRange(1,100)][int]$Steps = 4,
    [long]$Seed = 734112,
    [switch]$NoTurbo,
    [string]$Prefix = 'video/ref2va',
    [string]$ClientId = 'h3_ref2va_manual'
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path $PSScriptRoot -Parent }
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
if ([string]::IsNullOrWhiteSpace($ReferenceDirectory)) { $ReferenceDirectory = Join-Path $RepoRoot 'input' }
if ([string]::IsNullOrWhiteSpace($WorkflowPath)) { $WorkflowPath = Join-Path $RepoRoot 'workflows\h3_ref2va_template_api.json' }
if (-not (Test-Path -LiteralPath $WorkflowPath)) { throw "找不到工作流：$WorkflowPath" }
if (-not (Test-Path -LiteralPath $ReferenceDirectory)) { throw "找不到参考目录：$ReferenceDirectory" }

$refFiles = @($PrimaryImage, $AlternateImage, $FaceImage) + @($ExtraImages)
$refFiles = @($refFiles | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
if ($refFiles.Count -lt 1 -or $refFiles.Count -gt 9) { throw '参考图数量必须在 1 到 9 张之间。' }
foreach ($file in $refFiles) {
    $full = Join-Path $ReferenceDirectory $file
    if (-not (Test-Path -LiteralPath $full)) { throw "参考图不存在：$full" }
}
if (-not $NoTurbo -and ($Steps -lt 4 -or $Steps -gt 8)) { throw 'Turbo 模式步数必须在 4 到 8 之间；需要更多步数时请使用 -NoTurbo。' }
try { Invoke-RestMethod -Uri ($ApiUrl + '/system_stats') -Method Get | Out-Null }
catch { throw "无法连接 H3 ComfyUI：$ApiUrl。请先启动仓库内服务。" }

$graph = ([IO.File]::ReadAllText($WorkflowPath, [Text.Encoding]::UTF8)) | ConvertFrom-Json
$graph.'115'.inputs.megapixels = $Megapixels
$graph.'129'.inputs.noise_seed = $Seed
$graph.'132'.inputs.value = $Duration
$graph.'144'.inputs.value = $Steps
$graph.'143'.inputs.value = $Steps
$graph.'146'.inputs.value = (-not $NoTurbo)
$graph.'92'.inputs.filename_prefix = $Prefix

if ([string]::IsNullOrWhiteSpace($PromptFile)) {
    $promptText = @"
subject_definitions:
<Subject 1> is the adult anime game character defined jointly by the supplied reference pictures. Preserve the same identity, face, eyes, hair, clothing construction, colors, body proportions, and clean 2D game-art style.
<Picture 1> is the primary identity and opening-composition reference for [Shot 1].
<Picture 2> is an alternate clothing and hair-structure reference for <Subject 1>.
<Picture 3> is a close-up face and eye-detail reference for <Subject 1>.
<Subject 2> is a plain light-gray background with no props, scenery, extra characters, particles, text, or watermark.

summary:
[reference-to-video] Generate one continuous $Duration-second single-character shot anchored by <Picture 1>. Preserve <Subject 1> while adding only one small controlled performance.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - preserve identity, eyes, face shape, hair, clothing, proportions, colors, and linework.
<Picture 1> ([Shot 1] opening composition): fully_preserved - use it as the opening pose and framing anchor.
<Picture 2> (clothing reference for [Shot 1]): fully_preserved - preserve garment and hair structure.
<Picture 3> (face reference for [Shot 1]): fully_preserved - preserve eye shape, iris color, eyelashes, and facial proportions.
<Subject 2> (appears in [Shot 1]): fully_preserved - keep the background plain.

detailed_description:
The target video uses a clean 2D anime game-illustration style with stable outlines, stable flat shading, and consistent facial rendering. The shot begins from <Picture 1>. $CameraText [Shot 1] $ActionText Keep the face, eyes, hair, clothing, and body proportions stable. No scene cut, no camera orbit, no extra characters, no exposure, no adult content, no props, no complex scenery, no subtitle, no visible text, and no watermark. <Subject 2> remains unchanged throughout.

overall_soundscape:
N/A. Do not generate dialogue, singing, effects, or environmental ambience.

non_diegetic_music:
N/A. Treat the deliverable as silent.
"@
} else {
    if (-not (Test-Path -LiteralPath $PromptFile)) { throw "找不到提示词文件：$PromptFile" }
    $promptText = [IO.File]::ReadAllText($PromptFile, [Text.Encoding]::UTF8)
}
$graph.'138'.inputs.value = $promptText

$refInputs = $graph.'136'.inputs
$nodeIds = @('137','147','148')
for ($i = 0; $i -lt $refFiles.Count; $i++) {
    if ($i -ge $nodeIds.Count) { $nodeIds += [string](149 + $i - 3) }
    $key = 'ref_images.ref_image_' + $i
    $nodeId = $nodeIds[$i]
    $pair = @($nodeId, 0)
    $inputProperty = $refInputs.PSObject.Properties[$key]
    if ($null -eq $inputProperty) { $refInputs | Add-Member -MemberType NoteProperty -Name $key -Value $pair } else { $inputProperty.Value = $pair }
    $nodeProperty = $graph.PSObject.Properties[$nodeId]
    if ($null -eq $nodeProperty) {
        $graph | Add-Member -MemberType NoteProperty -Name $nodeId -Value ([PSCustomObject]@{class_type='LoadImage';inputs=[PSCustomObject]@{image=$refFiles[$i];upload='image'}})
    } else { $nodeProperty.Value.inputs.image = $refFiles[$i] }
}
$graph.'136'.inputs.ref_image_size = 'max'

$body = @{ prompt = $graph; client_id = $ClientId } | ConvertTo-Json -Depth 50
$bodyBytes = [Text.Encoding]::UTF8.GetBytes($body)
$result = Invoke-RestMethod -Uri ($ApiUrl + '/prompt') -Method Post -ContentType 'application/json; charset=utf-8' -Body $bodyBytes
Write-Host ('已提交：' + $result.prompt_id)
Write-Host ('参数：' + $Megapixels + ' MP，' + $Duration + ' 秒，' + ($(if($NoTurbo){'原始采样'}else{'Turbo'})) + '，' + $Steps + ' 步，seed=' + $Seed)
Write-Host ('参考图：' + ($refFiles -join ', '))
Write-Host ('输出目录：' + (Join-Path $RepoRoot 'output\video'))
