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

Explore 默认约 0.5 MP / Turbo / 4 steps / 4 takes，并且串行提交；Keep 默认约 0.75 MP / Turbo / 8 steps / 1 take。已有 H3 成功参数不会被 Harness 重写。

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
