# MiniMax H3 参考生视频仓库

这是一个自包含的 MiniMax H3 本地参考生视频工作区。H3 负责参考驱动的镜头生成；SDXL、旧版 LoRA 和视频关键帧只作为可选的后处理或动作增广工具，不承担主要人物身份锁定。仓库根目录固定为 `E:\MinimaxH3`，输入、临时文件、日志和输出均在仓库内。

## 目录

```text
MinimaxH3/
├─ assets/references/     角色、服装、脸部和场景参考图
├─ configs/               API 工作流和本地路径配置
├─ docs/                  生产与质检规范
├─ manifests/             镜头清单和资产角色映射
├─ prompts/               每个镜头的英文 H3 提示词
├─ scripts/               单镜头、批量取样和抽帧脚本
├─ models/                H3 模型文件（本地保留，Git 忽略）
├─ runtime/               Python 和依赖运行时（本地保留，Git 忽略）
├─ input/                 本次任务使用的输入参考图
├─ output/                ComfyUI 生成结果（Git 忽略）
├─ temp/                  ComfyUI 临时文件（Git 忽略）
└─ logs/                  服务日志（Git 忽略）
```

## 当前运行环境

- H3 服务：`E:\MinimaxH3\ComfyUI`
- H3 地址：`http://127.0.0.1:8189`
- 参考图输入：`E:\MinimaxH3\input`
- 生成输出：`E:\MinimaxH3\output\video`
- 参考图使用纯英文文件名，避免 Windows PowerShell 5.1 传输乱码。
- 本地 Python：`E:\MinimaxH3\runtime\python\python.exe`
- 本地依赖：`E:\MinimaxH3\runtime\venv\Lib\site-packages`

模型文件已放在 `E:\MinimaxH3\models`，不需要访问其他模型目录。

## 推荐生产顺序

1. 准备角色参考包：主立绘、备用立绘、脸部近景，必要时再加入服装、武器和场景图。
2. 把剧情拆成 4～6 秒的单镜头，每个镜头只保留一个核心动作。
3. 用 0.5 MP、Turbo、4 步批量探索 3～4 个种子。
4. 只把通过逐帧检查的动作，用 0.75 MP、Turbo、8 步重跑。
5. 合格镜头抽帧，人工验收后再进入动作增广集。
6. 使用剪辑软件或 FFmpeg 拼接镜头；声音和字幕独立处理。

启动服务：

```powershell
cd /d E:\MinimaxH3
powershell -ExecutionPolicy Bypass -File .\scripts\start_comfyui.ps1
```

快速探索：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\batch_ref2va_nun.ps1" -Count 4 -Megapixels 0.5 -Steps 4 -Duration 5 -ShotName shot01
```

质量重跑：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\run_ref2va.ps1" -Megapixels 0.75 -Steps 8 -Seed 734112 -Duration 5
```

Linux/WSL 启动：

```bash
cd /mnt/e/MinimaxH3
bash ./scripts/start_comfyui.sh
```

完整参数与选择依据见 [docs/超参数说明.md](docs/超参数说明.md)。通用提交脚本支持 1～9 张参考图；默认使用 `input` 下的三张修女参考图，也可以通过参数替换。

## 参考依据

- [MiniMax H3 官方仓库](https://github.com/MiniMax-AI/MiniMax-H3)
- [H3 Ref2VA 官方全参考提示词规范](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/.agents/skills/h3-prompt-writing/references/ref-en.txt)
- [MiniMax H3 Drama 多镜头生产结构](https://github.com/chiphoton/MiniMax-H3-Codex-Drama)
