# 直接向本机 H3 ComfyUI 提交三参考高清生成任务
# 默认：约 960x544、5 秒、Turbo、8 步、固定种子

param(
    [string]$ApiUrl = 'http://127.0.0.1:8189',
    [double]$Megapixels = 0.5,
    [double]$Duration = 5.0,
    [int]$Steps = 8,
    [long]$Seed = 734112,
    [string]$Prefix = 'video/nun_3ref_hd',
    [string]$ActionText = 'The character starts in a calm standing pose, blinks once, makes a small controlled head turn, lightly adjusts the edge of her collar, then lowers her hand and holds a composed standing pose until the end.',
    [string]$CameraText = 'The camera is locked-off with only a very subtle slow push-in. Keep the full upper body and face clearly visible throughout.'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$configPath = Join-Path $repoRoot 'workflows\h3_ref2va_template_api.json'
$h3Input = Join-Path $repoRoot 'input'

$primary = 'nun_primary.png'
$alternate = 'nun_alternate.png'
$face = 'nun_face.png'
$required = @($primary, $alternate, $face)

if (-not (Test-Path -LiteralPath $configPath)) {
    throw "找不到基础工作流：$configPath"
}
foreach ($name in $required) {
    $full = Join-Path $h3Input $name
    if (-not (Test-Path -LiteralPath $full)) {
        throw "H3 输入目录缺少参考图：$full"
    }
}

try {
    Invoke-RestMethod -Uri ($ApiUrl + '/system_stats') -Method Get | Out-Null
} catch {
    throw "无法连接 H3 ComfyUI：$ApiUrl。请先启动 H3 服务。"
}

$jsonText = [System.IO.File]::ReadAllText($configPath, [System.Text.Encoding]::UTF8)
$graph = $jsonText | ConvertFrom-Json

# 参数：0.5 MP 是快速探索档；0.75 MP 是质量保留档；时长建议 4 到 6 秒。
$graph.'115'.inputs.megapixels = $Megapixels
$graph.'129'.inputs.noise_seed = $Seed
$graph.'132'.inputs.value = $Duration
$graph.'137'.inputs.image = $primary
$graph.'136'.inputs.ref_image_size = 'max'
$graph.'144'.inputs.value = $Steps
$graph.'146'.inputs.value = $true
$graph.'92'.inputs.filename_prefix = $Prefix

# Ref2VA 官方全参考格式：六个字段，正文用英文，参考标签在各字段中保持同一含义。
$promptText = @"
subject_definitions:
<Subject 1> is the adult female anime game character defined jointly by <Picture 1>, <Picture 2>, and <Picture 3>. She has blonde hair, purple-red eyes, a black-and-white nun habit, a black head covering, stable facial proportions, clean linework, and a consistent 2D game illustration style.
<Picture 1> is the primary standing-pose and composition reference for [Shot 1].
<Picture 2> is an alternate fully clothed character reference used to preserve the hairstyle, head covering, collar, sleeves, and garment structure.
<Picture 3> is a close-up identity reference used to preserve the eyes, eyebrows, nose, mouth, eyelashes, and face shape.
<Subject 2> is a plain light-gray studio background with no props, scenery, extra characters, particles, text, or watermark.

summary:
[reference-to-video] Generate one continuous 5-second single-character shot anchored by <Picture 1>. Preserve <Subject 1> identity, face, eyes, hairstyle, head covering, costume construction, colors, proportions, and 2D game-art rendering while adding only a small natural performance.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - preserve identity, eye design, face shape, blonde hair, black-and-white nun habit, head covering, proportions, colors, and linework.
<Picture 1> ([Shot 1] opening composition): fully_preserved - use it as the opening pose and framing anchor.
<Picture 2> (character and clothing reference for [Shot 1]): fully_preserved - preserve the alternate reference features that clarify clothing and hair structure.
<Picture 3> (face identity reference for [Shot 1]): fully_preserved - preserve the eye shape, iris color, eyelashes, and facial proportions.
<Subject 2> (appears in [Shot 1]): fully_preserved - keep the background plain and uncluttered.

detailed_description:
The target video uses a clean 2D anime game-illustration style with stable outlines, stable flat shading, and consistent facial rendering. The shot begins from <Picture 1> with <Subject 1> in the same standing composition. $CameraText [Shot 1] $ActionText Keep the character fully clothed and keep the face, eyes, hair, head covering, collar, sleeves, and body proportions stable. No scene cut, no camera orbit, no extra characters, no exposure, no adult content, no props, no complex scenery, no subtitle, no visible text, and no watermark. <Subject 2> remains unchanged throughout.

overall_soundscape:
N/A. Do not generate dialogue, singing, chanting, breathing, effects, or environmental ambience.

non_diegetic_music:
N/A. The deliverable should be treated as silent.
"@
$graph.'138'.inputs.value = $promptText

# 第 2、3 个参考槽位在旧工作流中不存在，需要显式添加。
$refInputs = $graph.'136'.inputs
if ($refInputs.PSObject.Properties.Name -contains 'ref_images.ref_image_1') {
    $refInputs.'ref_images.ref_image_1' = @('147', 0)
} else {
    $refInputs | Add-Member -MemberType NoteProperty -Name 'ref_images.ref_image_1' -Value @('147', 0)
}
if ($refInputs.PSObject.Properties.Name -contains 'ref_images.ref_image_2') {
    $refInputs.'ref_images.ref_image_2' = @('148', 0)
} else {
    $refInputs | Add-Member -MemberType NoteProperty -Name 'ref_images.ref_image_2' -Value @('148', 0)
}

if ($graph.PSObject.Properties.Name -contains '147') {
    $graph.'147'.inputs.image = $alternate
} else {
    $graph | Add-Member -MemberType NoteProperty -Name '147' -Value ([PSCustomObject]@{
        class_type = 'LoadImage'
        inputs = [PSCustomObject]@{ image = $alternate; upload = 'image' }
    })
}
if ($graph.PSObject.Properties.Name -contains '148') {
    $graph.'148'.inputs.image = $face
} else {
    $graph | Add-Member -MemberType NoteProperty -Name '148' -Value ([PSCustomObject]@{
        class_type = 'LoadImage'
        inputs = [PSCustomObject]@{ image = $face; upload = 'image' }
    })
}

$body = @{ prompt = $graph; client_id = 'nun_3ref_hd_manual' } | ConvertTo-Json -Depth 50
$result = Invoke-RestMethod -Uri ($ApiUrl + '/prompt') -Method Post -ContentType 'application/json' -Body $body

Write-Host ('已提交。任务编号：' + $result.prompt_id)
Write-Host ('参数：' + $Megapixels + ' MP，' + $Duration + ' 秒，Turbo，' + $Steps + ' 步，种子 ' + $Seed)
Write-Host '参考图：主立绘 + 备用立绘 + 脸部近景'
Write-Host ('输出目录：' + (Join-Path $repoRoot 'output\video'))
