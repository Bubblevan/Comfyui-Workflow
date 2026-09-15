# MiniMax H3 Ref2VA production harness

这是一个 manifest-driven、可复现、可追溯的本地 MiniMax H3 Ref2VA Harness。Ref2VA 是主要生成路径；每个任务保持 4–6 秒单镜头。H3 synthetic frames 只用于 augmentation，不能替代原始游戏素材，最终训练数据必须人工审核。

## 目录

```text
characters/                  character manifests
shots/                       independent shot manifests
schemas/                     JSON Schema Draft 2020-12
templates/                   prompt template reference
scripts/h3.py                one Python CLI for validation, generation, QC
workflows/                   canonical workflow and node contract
configs/extra_model_paths.yaml 唯一模型路径配置
input/                       ComfyUI input staging area
output/video/                generated videos
output/frames/{pending,accepted,rejected}/ frame review lifecycle
output/qc/                   contact sheets
runs/YYYY-MM-DD/<run_id>/    prompt, workflow snapshot, and run.json
```

`ComfyUI/` 当前作为 pinned-in-repository upstream tree 保留；Harness 的 workflow、脚本和 provenance 与其分开。升级管理见 `COMFYUI_COMMIT`（若部署环境固定了上游 commit，请写入该文件）。

## 本地 NSFW library

成人向素材先进入独立的 [`library/nsfw/`](library/nsfw/)，以角色无关的 prompt cards、H3 兼容性参数、来源和审核状态保存；确认稳定后，再通过 `scripts/nsfw_library.py materialize` 物化为正式 `shots/` manifest。第一批条目只覆盖明确成年虚构角色的非露骨视觉状态、姿态和镜头控制，并要求明确同意的 roleplay / fantasy 语境。校验入口：

```powershell
python scripts/nsfw_library.py validate
python scripts/nsfw_library.py list
```

## 快速开始

使用仓库内运行时（Windows）：

```powershell
.\scripts\start_comfyui.ps1
.\scripts\h3.ps1 validate
```

标准生产顺序：

1. define character：复制并编辑 `characters/nun.yaml` 作为 example；
2. define shot：创建 `shots/<character>/<shot>.yaml`；
3. validate：`python scripts/h3.py validate`；
4. explore：`python scripts/h3.py explore shots/nun/shot01_idle.yaml`；
5. select seed：人工观看 explore 输出；
6. keep：`python scripts/h3.py run shots/nun/shot01_idle.yaml --seed 734112 --profile keep`；
7. extract：`python scripts/h3.py extract RUN_ID`；
8. QC：`python scripts/h3.py qc RUN_ID`；
9. accept/reject：`python scripts/h3.py accept RUN_ID frame_003` 或 `reject`。

Explore 默认约 0.5 MP / Turbo / 4 steps / 4 takes，并且串行提交；Keep 默认约 0.75 MP / Turbo / 8 steps / 1 take。主干默认使用参考 workflow 的 `match` reference-size、`euler + simple`、H3 flow shift `12/3` 和 Comfy Kitchen attention；shot 的 `runtime` 只用于覆盖这些值或进行可追溯的加速消融实验。

## H3 主干运行参数

参考 workflow 中实际接入主链的稳定参数已经合并进 canonical API graph：

| 能力 | 主干默认 | 说明 |
| --- | --- | --- |
| 多参考图尺寸 | `match` | 以目标尺寸匹配参考图，保留多图语义 |
| 采样 | `euler` | 参考 H3 workflow 的采样器，仍支持 shot 级覆盖 |
| 调度 | `simple` | 与参考 workflow 对齐，仍支持 shot 级覆盖 |
| H3 flow shift | video `12` / audio `3` | 通过 `MiniMaxH3SigmaShift` 接入模型链 |
| dense attention | Comfy Kitchen | 当前 H3 主干的正收益默认后端 |
| SageAttention | 已安装、显式启用 | KJNodes + SageAttention 2，作为 SM89 消融后端 |
| timestep cache | 仅显式启用 | 参考 workflow 中为 bypass，可能改变质量，不默认打开 |

H3 的近似加速器与 attention 加速器分开建模；同一 graph 不能叠加 `cache.enabled` 与
`approximation.method`，避免多个 cache 修改同一个 diffusion forward。当前可复现的近似方法为：

| 方法 | 类型 | keep/0.75MP/8steps 实测 | 结论 |
| --- | --- | ---: | --- |
| `teacache` | diffusion forecast/cache | 228.076s | 当前速度优先候选；冷进程约快 24.89%，会改变数值轨迹，需人工 A/B |
| `spectrum` | forecast/cache | 251.688s | 冷进程约快 17.11%，比 TeaCache 慢，近似偏差更大 |
| SageAttention `auto` | FP8 attention (SM89) | 292.167s | 可用，约快 3.60%，但未超过 Kitchen 的稳定优势 |
| SageAttention explicit CUDA | FP16 attention | 314.408s | 可运行但更慢 |
| SageAttention `allow_compile` | attention compile | 320.432s | 可运行但更慢 |
| `agsoft_cache` | legacy cache | 300.722s | 完成但无可测收益，不作为默认 |
| `fastpath` | middle-block cache | failed at 64.465s | 当前 aimdo Windows 内存图编译冲突 |
| `speed_cache` | diffusion cache | failed at 98.792s | H3 `FinalLayer` 接口不兼容 |

因此生产主干仍保留精确的 Kitchen graph；若接受近似轨迹，使用 `teacache` 作为速度配置，
而不是把一次单 shot 的正收益误写成无损优化。详细的 keep E2E 记录见
[`benchmarks/README.md`](benchmarks/README.md)。

实验时可以只覆盖需要比较的参数，例如：

```yaml
runtime:
  attention:
    backend: sage
    sage_attention: auto
    allow_compile: false
```

重复 backend 的 API 级消融可复现：

```powershell
python scripts/benchmark_h3_runtime.py shots/nun/shot01_idle.yaml `
  --api-url http://127.0.0.1:8189 --profile explore --seed 424242 `
  --variants mainline pytorch sage
```

当前 Ada/SM89 机器的实测记录见 [`benchmarks/`](benchmarks/)。

近似加速消融示例（每个候选都要在新的 ComfyUI 进程执行一次）：

```powershell
python scripts/benchmark_h3_runtime.py shots/nun/shot01_idle.yaml `
  --api-url http://127.0.0.1:8189 --profile keep --seed 424243 `
  --variants teacache
```

每个近似方案必须在独立 ComfyUI 进程中测试；Speed Cache 会做进程级 monkey-patch，不能与其他
variant 在同一进程连续比较。启动脚本会把 Triton 编译缓存放到仓库内的 `temp/triton-cache`，
避免 Windows 用户目录权限问题。

## Prompt 与参考图

`h3_prompt.py` 根据 character + shot manifest 编译官方 Ref2VA 六段结构：`subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`。镜头通过 `references` 明确选择 1–9 张图，编译器按实际使用顺序生成 `Picture 1` 到 `Picture 9` 以及对应 semantic role，不会注入未使用的参考图。

旧 shot 未填写 `reference_mode` 时保持兼容，默认使用 `first_frame`：`Picture 1` 作为开场帧锚点。需要让参考图只提供身份、服装、武器或画风，而由 H3 生成全新开场时，使用 `reference_mode: free`（或 `reference_generation`），并补充 `opening`、`beats`、`ending` 和 `constraints`；此模式不会写入“shot begins from Picture 1”。

例如：

```yaml
reference_mode: free
opening:
  framing: medium_full
  view: three_quarter_front
  description: The character is already standing in a relaxed new pose.
beats:
  - start: 0.0
    end: 2.0
    description: She raises her weapon.
  - start: 2.0
    end: 5.0
    description: She holds a stable ready stance.
ending:
  description: Stable three-quarter combat-ready pose.
```

## 可复现与追踪

每次生成都会创建 `runs/YYYY-MM-DD/<run_id>/run.json`，保存角色、镜头、参考图、prompt/workflow hash、seed、profile、model filenames、ComfyUI `prompt_id`、输出路径和耗时。ComfyUI 状态通过 `/history/<prompt_id>` 查询，支持 timeout 与 retry；不使用固定 sleep 判断完成。

## QC 与数据晋级

抽帧先进入 `output/frames/pending/<run_id>/`。筛选包含 Laplacian sharpness、brightness/corruption、dHash/SSIM 去重，以及只作 advisory 的 reference similarity；同时写出 CSV 和 `output/qc/<run_id>/contact_sheet.jpg`。`accept`/`reject` 是显式人工操作，accepted frame 才会生成 sidecar，并标记 `source_type: h3_synthetic`。

原始游戏素材应在独立数据流中标记为 `original_game`，不得与 synthetic frame 混淆。

角色文件和参考图可以按游戏名组织为 `characters/<game>/<character>.yaml` 与 `assets/references/<game>/<character>/`；Harness 会递归发现并解析这层目录，不需要移动现有文件。
